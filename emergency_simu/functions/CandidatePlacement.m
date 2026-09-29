classdef CandidatePlacement < matlab.System
    % CandidatePlacement  Groups nearby gap points into gap regions and
    % produces ranked CANDIDATE node locations (not final deployment
    % positions -- this block never claims a candidate is optimal).
    %
    % Inputs:
    %   gapX, gapY    - 1xMaxPoints (from GapDetector), NaN-padded
    %   gapCount      - scalar, number of valid gap points
    %   nodePositions - Nx3 existing ground node positions (for the
    %                   distance-from-existing-network ranking factor)
    %
    % Outputs (all 1 x MaxCandidates, NaN-padded beyond candidateCount):
    %   candidateX, candidateY, candidateZ - candidate position (Z fixed
    %                                        at SurveyAltitude)
    %   candidateGapCount    - how many gap points this candidate represents
    %   candidateScore       - simple priority score (higher = higher priority)
    %   candidateInBuilding  - permanently zero (no building model in project)
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
        GapClusterDistance = 75     % metres -- derived as 250 * RFRangeScale in setupImpl
        MaxPoints          = 25
        MaxCandidates      = 25
        SurveyAltitude     = 30     % metres, Z for every candidate
        AreaSize           = [1000 1000]
        GapCountWeight     = 10
        DistanceWeight     = 0.1
        RFRangeScale       = 0.30
    end

    methods (Access = protected)
        function setupImpl(obj)
            % All parameters come through block dialog -- no evalin.
            % Derive GapClusterDistance from the Nontunable RFRangeScale property.
            % NOTE: Nontunable properties cannot be changed after setup,
            % so GapClusterDistance must be used directly in stepImpl via
            % obj.RFRangeScale instead of being overwritten here.
            % (Cannot write to a Nontunable property in setupImpl after
            %  the object is locked.)
        end

        function [candidateX, candidateY, candidateZ, candidateGapCount, ...
                candidateScore, candidateInBuilding, candidateCount] = ...
                stepImpl(obj, gapX, gapY, gapCount, nodePositions)

            % Effective cluster distance derived from RFRangeScale
            clusterDist = 250 * obj.RFRangeScale;

            candidateX          = NaN(1, obj.MaxCandidates);
            candidateY          = NaN(1, obj.MaxCandidates);
            candidateZ          = NaN(1, obj.MaxCandidates);
            candidateGapCount   = zeros(1, obj.MaxCandidates);
            candidateScore      = NaN(1, obj.MaxCandidates);
            candidateInBuilding = zeros(1, obj.MaxCandidates);  % always 0: no buildings
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
                        if any(d <= clusterDist)
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
                candidateInBuilding(r) = 0;   % no building model
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

        % Explicit output propagation methods
        function varargout = getOutputSizeImpl(obj)
            mc = obj.MaxCandidates;
            varargout{1} = [1 mc];   % candidateX
            varargout{2} = [1 mc];   % candidateY
            varargout{3} = [1 mc];   % candidateZ
            varargout{4} = [1 mc];   % candidateGapCount
            varargout{5} = [1 mc];   % candidateScore
            varargout{6} = [1 mc];   % candidateInBuilding
            varargout{7} = [1 1];    % candidateCount (scalar)
        end

        function varargout = getOutputDataTypeImpl(~)
            for k = 1:7
                varargout{k} = 'double';
            end
        end

        function varargout = isOutputComplexImpl(~)
            for k = 1:7
                varargout{k} = false;
            end
        end

        function varargout = isOutputFixedSizeImpl(~)
            for k = 1:7
                varargout{k} = true;
            end
        end
    end
end