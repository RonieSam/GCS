classdef GCSDroneSurvey < matlab.System
    % GCSDroneSurvey  Replays real UAV survey telemetry and RSSI values
    % collected by the FastAPI backend during an active GCS RF Scan mission.
    %
    % Outputs:
    %   dronePosition - 1x3 vector [x y z] in local metres
    %   rssiValues    - 1xN vector of simulated/measured RSSI in dBm
    %
    % If no survey samples were loaded, falls back to a 50m hover at origin.

    properties (Nontunable)
        SurveyPoints = zeros(0, 3)  % Nx3 matrix of [x y z]
        SurveyRSSI   = zeros(0, 3)  % NxM matrix of RSSI values
        SampleTime   = 1            % seconds per step
    end

    properties (DiscreteState)
        Index
    end

    methods (Access = protected)
        function setupImpl(obj)
            obj.Index = 1;
        end

        function [dronePosition, rssiValues] = stepImpl(obj)
            nP = size(obj.SurveyPoints, 1);
            if nP > 0
                idx = min(obj.Index, nP);
                dronePosition = obj.SurveyPoints(idx, :);
                if size(obj.SurveyRSSI, 1) >= idx
                    rssiValues = obj.SurveyRSSI(idx, :);
                else
                    rssiValues = -100 * ones(1, 3);
                end
                obj.Index = mod(obj.Index, nP) + 1;
            else
                dronePosition = [50 50 30];
                rssiValues = [-100 -100 -100];
            end
        end

        function resetImpl(obj)
            obj.Index = 1;
        end

        function sts = getSampleTimeImpl(obj)
            sts = createSampleTime(obj, 'Type', 'Discrete', 'SampleTime', obj.SampleTime);
        end

        function num = getNumInputsImpl(~)
            num = 0;
        end

        function num = getNumOutputsImpl(~)
            num = 2;
        end
    end
end
