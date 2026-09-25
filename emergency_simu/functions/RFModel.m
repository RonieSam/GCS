classdef RFModel < matlab.System
    % RFModel  Simplified log-distance path-loss RSSI calculator.
    %
    % Inputs:
    %   nodePositions - 3x3 matrix, [x y z] per ground node
    %   dronePosition - 1x3 vector, [x y z]
    %
    % Output:
    %   rssiValues - 1x3 vector, simulated RSSI (dBm) from drone to each node
    %
    % DEMO ASSUMPTIONS (not real Wi-Fi specs):
    %   ReferenceRSSI      = -40 dBm at ReferenceDistance
    %   ReferenceDistance  = 1 m
    %   PathLossExponent   = 3 (moderate outdoor/obstructed environment)

    properties
        ReferenceRSSI     = -30
        PathLossExponent  = 2.2
        ReferenceDistance = 1
        RFRangeScale      = 0.25
    end

    methods (Access = protected)
        function setupImpl(obj)
            if evalin('base', 'exist(''RFRangeScale'', ''var'')')
                obj.RFRangeScale = evalin('base', 'RFRangeScale');
            end
        end

        function rssiValues = stepImpl(obj, nodePositions, dronePosition)
            numNodes = size(nodePositions, 1);
            rssiValues = zeros(1, numNodes);
            scale = max(obj.RFRangeScale, 1e-6);
            for i = 1:numNodes
                d = norm(dronePosition - nodePositions(i, :));
                d = max(d, obj.ReferenceDistance);
                dEff = d / scale;
                rssiValues(i) = obj.ReferenceRSSI - ...
                    10 * obj.PathLossExponent * log10(dEff / obj.ReferenceDistance);
            end
        end

        function num = getNumInputsImpl(~)
            num = 2;
        end
        function num = getNumOutputsImpl(~)
            num = 1;
        end
    end
end