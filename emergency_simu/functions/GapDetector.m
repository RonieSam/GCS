classdef GapDetector < matlab.System
    % GapDetector  Identifies which survey points are coverage gaps.
    %
    % A survey point is a gap when its recorded status == 0 (GAP), using the
    % Phase 3 CoverageClassifier thresholds -- this block doesn't reclassify
    % anything, it just filters what SurveyDataLogger already computed.
    %
    % Inputs:
    %   surveyX, surveyY, surveyStatus - 1xMaxPoints arrays from SurveyDataLogger
    %   pointCount                     - scalar, how many entries are valid
    %
    % Outputs:
    %   gapX, gapY - 1xMaxPoints, x/y of each gap point in order found
    %                (NaN in unused slots)
    %   gapCount   - scalar, number of gap points found (calculated, never
    %                hard-coded)

    properties (Nontunable)
        MaxPoints = 25
    end

    methods (Access = protected)
        function setupImpl(~)
            % MaxPoints is provided through the block dialog (e.g. MaxPoints = maxSurveyPoints).
            % No evalin access to base workspace.
        end

        function [gapX, gapY, gapCount] = stepImpl(obj, surveyX, surveyY, surveyStatus, pointCount)
            gapX = NaN(1, obj.MaxPoints);
            gapY = NaN(1, obj.MaxPoints);
            gapCount = 0;

            for i = 1:pointCount
                if surveyStatus(i) == 0
                    gapCount = gapCount + 1;
                    gapX(gapCount) = surveyX(i);
                    gapY(gapCount) = surveyY(i);
                end
            end
        end

        function num = getNumInputsImpl(~)
            num = 4;
        end
        function num = getNumOutputsImpl(~)
            num = 3;
        end

        % Explicit output propagation methods
        function varargout = getOutputSizeImpl(obj)
            mp = obj.MaxPoints;
            varargout{1} = [1 mp];   % gapX
            varargout{2} = [1 mp];   % gapY
            varargout{3} = [1 1];    % gapCount (scalar)
        end

        function varargout = getOutputDataTypeImpl(~)
            varargout{1} = 'double';
            varargout{2} = 'double';
            varargout{3} = 'double';
        end

        function varargout = isOutputComplexImpl(~)
            varargout{1} = false;
            varargout{2} = false;
            varargout{3} = false;
        end

        function varargout = isOutputFixedSizeImpl(~)
            varargout{1} = true;
            varargout{2} = true;
            varargout{3} = true;
        end
    end
end