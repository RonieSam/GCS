classdef NodeDeployment < matlab.System
    % NodeDeployment  ONE deployment decision, frozen in time.
    %
    % THE BUG THIS FIXES: previously this block just mirrored whatever
    % candidate CandidatePlacement currently reported. But CandidatePlacement
    % recomputes every step from however much of the baseline survey has
    % happened so far -- so the "candidate" (and therefore Node 4's position)
    % was silently changing WHILE the baseline survey was still running,
    % contaminating early survey points with a node that later moved away.
    %
    % THE FIX: a two-step latch.
    %   1. ARM  -- once the BEFORE survey has recorded all 25 points AND a
    %              candidate exists, remember that (but don't act yet).
    %   2. LOCK -- on the very next simulation step, capture that candidate's
    %              X/Y once, permanently. This one-step delay is intentional:
    %              it lines up exactly with DroneSurvey wrapping back around
    %              to survey point 1, so the deployed node's position never
    %              changes mid-survey in either direction.
    %
    % Inputs:
    %   nodePositions       - 3x3, ORIGINAL ground nodes (read-only)
    %   candidateX, candidateY - 1xMaxPoints (from CandidatePlacement)
    %   candidateCount      - scalar
    %   baselinePointCount  - scalar (from the BEFORE SurveyDataLogger) --
    %                         this is what "have we finished the baseline
    %                         survey yet?" actually means here
    %
    % Outputs:
    %   deployedNodePositions - 4x3. Row 4 is [NaN NaN NaN] until locked,
    %                           then a FIXED [X Y Z] forever after.
    %   deployed              - scalar 0/1. Becomes 1 the instant the lock
    %                           happens and stays 1. Feed this into
    %                           SurveyDataLoggerAfter's `enable` input so
    %                           the AFTER survey only starts recording once
    %                           deployment is real and fixed.

    properties (Nontunable)
        NewNodeAltitude = 10   % metres
        MaxPoints       = 25   % must match the baseline survey length
    end

    properties (DiscreteState)
        PendingLock   % armed, waiting one step
        Locked        % 1 once the node position is permanently fixed
        LockedX
        LockedY
    end

    methods (Access = protected)
        function setupImpl(obj)
            obj.PendingLock = false;
            obj.Locked      = false;
            obj.LockedX     = NaN;
            obj.LockedY     = NaN;
        end

        function [deployedNodePositions, deployed] = stepImpl(obj, ...
                nodePositions, candidateX, candidateY, candidateCount, baselinePointCount)

            % Step 2 of the latch: actually lock, one tick after arming.
            if obj.PendingLock && ~obj.Locked
                obj.LockedX = candidateX(1);
                obj.LockedY = candidateY(1);
                obj.Locked  = true;
            end

            % Step 1 of the latch: arm, only once the baseline is COMPLETE.
            if ~obj.Locked && ~obj.PendingLock && ...
                    baselinePointCount >= obj.MaxPoints && candidateCount >= 1
                obj.PendingLock = true;
            end

            if obj.Locked
                newNode = [obj.LockedX, obj.LockedY, obj.NewNodeAltitude];
            else
                newNode = [NaN, NaN, NaN];
            end

            deployedNodePositions = [nodePositions; newNode];
            deployed = double(obj.Locked);
        end

        function resetImpl(obj)
            obj.PendingLock = false;
            obj.Locked      = false;
            obj.LockedX     = NaN;
            obj.LockedY     = NaN;
        end

        function num = getNumInputsImpl(~)
            num = 5;
        end
        function num = getNumOutputsImpl(~)
            num = 2;
        end
    end
end