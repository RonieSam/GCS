classdef CoverageClassifier < matlab.System
    % CoverageClassifier  Converts RSSI values into a 4-level coverage status.
    %
    % Input:
    %   rssiValues - 1xN vector, RSSI in dBm (from RFModel)
    %
    % Output:
    %   status - 1xN vector, numeric coverage code per node:
    %            3 = GOOD, 2 = MODERATE, 1 = WEAK, 0 = GAP
    %
    % DEMO THRESHOLDS (simulation-only, not real Wi-Fi specs):
    %   GOOD     : RSSI > -60 dBm
    %   MODERATE : -75 dBm < RSSI <= -60 dBm
    %   WEAK     : -85 dBm < RSSI <= -75 dBm
    %   GAP      : RSSI <= -85 dBm

    properties (Nontunable)
        GoodThreshold     = -60
        ModerateThreshold = -75
        WeakThreshold     = -85
    end

    methods (Access = protected)
        function status = stepImpl(obj, rssiValues)
            n = numel(rssiValues);
            status = zeros(1, n);
            for i = 1:n
                r = rssiValues(i);
                if r > obj.GoodThreshold
                    status(i) = 3;
                elseif r > obj.ModerateThreshold
                    status(i) = 2;
                elseif r > obj.WeakThreshold
                    status(i) = 1;
                else
                    status(i) = 0;
                end
            end
        end

        function num = getNumInputsImpl(~)
            num = 1;
        end
        function num = getNumOutputsImpl(~)
            num = 1;
        end
    end
end