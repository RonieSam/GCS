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

    properties
        MaxPoints = 25
    end

    methods (Access = protected)
        function setupImpl(obj)
            if evalin('base', 'exist(''maxSurveyPoints'', ''var'')')
                obj.MaxPoints = max(evalin('base', 'maxSurveyPoints'), 25);
            end
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
    end
end