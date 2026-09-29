classdef SurveyDataLogger < matlab.System
    % SurveyDataLogger  Records drone survey results as fixed-size arrays,
    % for Phase 5's gap-analysis blocks to consume. Completely separate from
    % CoverageMap (which keeps drawing exactly as it did in Phase 4) so that
    % block is never touched.
    %
    % Inputs:
    %   dronePosition - 1x3, current drone position [x y z]
    %   rssiValues    - 1xN, RSSI (dBm) from each ground node at this position
    %
    % Outputs (all 1 x MaxPoints, in survey order; unfilled slots = NaN):
    %   surveyX      - x coordinate of each survey point
    %   surveyY      - y coordinate of each survey point
    %   surveyRSSI   - best (max) RSSI reaching the drone at that point
    %   surveyStatus - coverage code (3/2/1/0) for that point -- classified
    %                  with the SAME CoverageClassifier class as Phase 3/4
    %                  (reused via composition, thresholds never duplicated)
    %   pointCount   - scalar, how many points have been recorded so far

    properties (Nontunable)
        MaxPoints = 25
    end

    properties (Access = private)
        Classifier
        SurveyX
        SurveyY
        SurveyRSSI
        SurveyStatus
        PointCount
    end

    methods (Access = protected)
        function setupImpl(obj)
            % MaxPoints is provided through the block dialog (e.g. MaxPoints = maxSurveyPoints).
            % No evalin access to base workspace.
            obj.Classifier   = CoverageClassifier();
            obj.SurveyX      = NaN(1, obj.MaxPoints);
            obj.SurveyY      = NaN(1, obj.MaxPoints);
            obj.SurveyRSSI   = NaN(1, obj.MaxPoints);
            obj.SurveyStatus = NaN(1, obj.MaxPoints);
            obj.PointCount   = 0;
        end

        function [surveyX, surveyY, surveyRSSI, surveyStatus, pointCount] = ...
                stepImpl(obj, dronePosition, rssiValues)
            if obj.PointCount < obj.MaxPoints
                bestRSSI    = max(rssiValues);
                pointStatus = obj.Classifier.step(bestRSSI);

                idx = obj.PointCount + 1;
                obj.SurveyX(idx)      = dronePosition(1);
                obj.SurveyY(idx)      = dronePosition(2);
                obj.SurveyRSSI(idx)   = bestRSSI;
                obj.SurveyStatus(idx) = pointStatus;
                obj.PointCount = idx;
            end

            surveyX      = obj.SurveyX;
            surveyY      = obj.SurveyY;
            surveyRSSI   = obj.SurveyRSSI;
            surveyStatus = obj.SurveyStatus;
            pointCount   = obj.PointCount;
        end

        function resetImpl(obj)
            obj.SurveyX      = NaN(1, obj.MaxPoints);
            obj.SurveyY      = NaN(1, obj.MaxPoints);
            obj.SurveyRSSI   = NaN(1, obj.MaxPoints);
            obj.SurveyStatus = NaN(1, obj.MaxPoints);
            obj.PointCount   = 0;
        end

        function num = getNumInputsImpl(~)
            num = 2;
        end
        function num = getNumOutputsImpl(~)
            num = 5;
        end

        % Explicit output propagation methods
        function varargout = getOutputSizeImpl(obj)
            mp = obj.MaxPoints;
            varargout{1} = [1 mp];   % surveyX
            varargout{2} = [1 mp];   % surveyY
            varargout{3} = [1 mp];   % surveyRSSI
            varargout{4} = [1 mp];   % surveyStatus
            varargout{5} = [1 1];    % pointCount (scalar)
        end

        function varargout = getOutputDataTypeImpl(~)
            varargout{1} = 'double';
            varargout{2} = 'double';
            varargout{3} = 'double';
            varargout{4} = 'double';
            varargout{5} = 'double';
        end

        function varargout = isOutputComplexImpl(~)
            varargout{1} = false;
            varargout{2} = false;
            varargout{3} = false;
            varargout{4} = false;
            varargout{5} = false;
        end

        function varargout = isOutputFixedSizeImpl(~)
            varargout{1} = true;
            varargout{2} = true;
            varargout{3} = true;
            varargout{4} = true;
            varargout{5} = true;
        end
    end
end