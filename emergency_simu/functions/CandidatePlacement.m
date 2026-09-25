classdef CandidatePlacement < matlab.System
    % CandidatePlacement  Groups nearby gap points into gap regions and
    % produces ranked CANDIDATE node locations (not final deployment
    % positions -- this block never claims a candidate is optimal).
    %
    % Inputs:
    %   gapX, gapY    - 1xMaxPoints (from GapDetector), NaN-padded
    %   gapCount      - scalar, number of valid gap points
    %   nodePositions - 3x3 existing ground node positions (for the
    %                   distance-from-existing-network ranking factor)
    %
    % Outputs (all 1 x MaxCandidates, NaN-padded beyond candidateCount):
    %   candidateX, candidateY, candidateZ - candidate position (Z fixed
    %                                        at SurveyAltitude)
    %   candidateGapCount    - how many gap points this candidate represents
    %   candidateScore       - simple priority score (higher = higher priority)
    %   candidateInBuilding  - 1 if the candidate centroid falls inside a
    %                          known building footprint, else 0 (flagged,
    %                          not auto-relocated -- keeps this deterministic
    %                          and easy to reason about)
    %   candidateCount       - scalar, number of candidates generated
    %
    % METHOD (deliberately simple -- spatial engineering, not ML/optimization):
    %  1. GROUPING: single-link distance clustering. Two gap points join the
    %     same region if they're within GapClusterDistance of ANY point
    %     already in that region. Regions merge if a new point bridges them.
    %  2. CANDIDATE LOCATION: centroid (mean X, mean Y) of each region.
    %  3. SCORE = candidateGapCount * GapCountWeight
    %             + distanceToNearestExistingNode * DistanceWeight
    %     A region with more gap points, or farther from existing coverage,
    %     ranks higher. Weights are plain tunable numbers, not a claim of
    %     mathematical optimality.

    properties (Nontunable)
        GapClusterDistance = 250    % metres -- points this close join one region
        MaxPoints          = 25
        MaxCandidates      = 25
        SurveyAltitude     = 30     % metres, Z for every candidate
        AreaSize           = [1000 1000]
        Buildings          = zeros(0, 4)   % [x y width depth], optional
        GapCountWeight     = 10
        DistanceWeight     = 0.1
    end

    methods (Access = protected)
        function [candidateX, candidateY, candidateZ, candidateGapCount, ...
                candidateScore, candidateInBuilding, candidateCount] = ...
                stepImpl(obj, gapX, gapY, gapCount, nodePositions)

            candidateX          = NaN(1, obj.MaxCandidates);
            candidateY          = NaN(1, obj.MaxCandidates);
            candidateZ          = NaN(1, obj.MaxCandidates);
            candidateGapCount   = zeros(1, obj.MaxCandidates);
            candidateScore      = NaN(1, obj.MaxCandidates);
            candidateInBuilding = zeros(1, obj.MaxCandidates);
            candidateCount      = 0;

            if gapCount == 0
                return;   % no gaps -> no candidates
            end

            pointsX = gapX(1:gapCount);
            pointsY = gapY(1:gapCount);

            % --- Step 1: simple single-link distance clustering ---
            regionId = zeros(1, gapCount);   % 0 = unassigned
            nextRegion = 1;
            for i = 1:gapCount
                if regionId(i) ~= 0
                    continue;   % already placed in a region
                end
                regionId(i) = nextRegion;
                changed = true;
                while changed
                    changed = false;
                    for j = 1:gapCount
                        if regionId(j) ~= 0
                            continue;
                        end
                        % does point j lie within range of ANY point already
                        % in this region?
                        inRegionIdx = find(regionId == nextRegion);
                        d = hypot(pointsX(inRegionIdx) - pointsX(j), ...
                                  pointsY(inRegionIdx) - pointsY(j));
                        if any(d <= obj.GapClusterDistance)
                            regionId(j) = nextRegion;
                            changed = true;
                        end
                    end
                end
                nextRegion = nextRegion + 1;
            end
            numRegions = nextRegion - 1;

            % --- Step 2-3: centroid + score per region ---
            for r = 1:numRegions
                idx = (regionId == r);
                cx = mean(pointsX(idx));
                cy = mean(pointsY(idx));
                cx = min(max(cx, 0), obj.AreaSize(1));   % keep inside the area
                cy = min(max(cy, 0), obj.AreaSize(2));

                inBuilding = 0;
                for b = 1:size(obj.Buildings, 1)
                    bx = obj.Buildings(b, 1); by = obj.Buildings(b, 2);
                    bw = obj.Buildings(b, 3); bd = obj.Buildings(b, 4);
                    if cx >= bx && cx <= bx + bw && cy >= by && cy <= by + bd
                        inBuilding = 1;
                    end
                end

                nodeDistances = sqrt((nodePositions(:,1) - cx).^2 + ...
                                      (nodePositions(:,2) - cy).^2);
                nearestNodeDist = min(nodeDistances);

                gapPointsInRegion = sum(idx);
                score = gapPointsInRegion * obj.GapCountWeight + ...
                        nearestNodeDist * obj.DistanceWeight;

                candidateX(r)          = cx;
                candidateY(r)          = cy;
                candidateZ(r)          = obj.SurveyAltitude;
                candidateGapCount(r)   = gapPointsInRegion;
                candidateScore(r)      = score;
                candidateInBuilding(r) = inBuilding;
            end
            candidateCount = numRegions;

            % --- Rank by score, descending (higher-priority candidates first) ---
            if candidateCount > 1
                [~, order] = sort(candidateScore(1:candidateCount), 'descend');
                candidateX(1:candidateCount)          = candidateX(order);
                candidateY(1:candidateCount)          = candidateY(order);
                candidateZ(1:candidateCount)          = candidateZ(order);
                candidateGapCount(1:candidateCount)   = candidateGapCount(order);
                candidateScore(1:candidateCount)      = candidateScore(order);
                candidateInBuilding(1:candidateCount) = candidateInBuilding(order);
            end
        end

        function num = getNumInputsImpl(~)
            num = 4;
        end
        function num = getNumOutputsImpl(~)
            num = 7;
        end
    end
end