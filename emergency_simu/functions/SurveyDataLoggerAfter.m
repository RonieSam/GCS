classdef SurveyDataLoggerAfter < matlab.System
    % SurveyDataLoggerAfter  Same recording logic as SurveyDataLogger, but
    % GATED by an `enable` signal -- it records nothing at all until
    % deployment is actually locked (see NodeDeployment's `deployed` output).
    %
    % This is a separate class (not a change to SurveyDataLogger) so the
    % original BEFORE logger, and every existing use of SurveyDataLogger,
    % is completely untouched.
    %
    % Inputs:
    %   dronePosition - 1x3
    %   rssiValues    - 1x4 (from RFModel (After))
    %   enable        - scalar; while this is 0, no recording happens at
    %                   all -- not even into a "temporary" slot. While the
    %                   baseline survey is still running, this stays 0, so
    %                   nothing here can be contaminated by it.
    %
    % Outputs: identical shape/meaning to SurveyDataLogger's --
    %   surveyX, surveyY, surveyRSSI, surveyStatus (1xMaxPoints, NaN-padded)
    %   pointCount (scalar)

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
            obj.Classifier   = CoverageClassifier();
            obj.SurveyX      = NaN(1, obj.MaxPoints);
            obj.SurveyY      = NaN(1, obj.MaxPoints);
            obj.SurveyRSSI   = NaN(1, obj.MaxPoints);
            obj.SurveyStatus = NaN(1, obj.MaxPoints);
            obj.PointCount   = 0;
        end

        function [surveyX, surveyY, surveyRSSI, surveyStatus, pointCount] = ...
                stepImpl(obj, dronePosition, rssiValues, enable)

            if enable ~= 0 && obj.PointCount < obj.MaxPoints
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
            num = 3;
        end
        function num = getNumOutputsImpl(~)
            num = 5;
        end
    end
end
