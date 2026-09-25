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

    properties (Nontunable)
        ReferenceRSSI     = -30
        PathLossExponent  = 2.2
        ReferenceDistance = 1
    end

    methods (Access = protected)
        function rssiValues = stepImpl(obj, nodePositions, dronePosition)
            numNodes = size(nodePositions, 1);
            rssiValues = zeros(1, numNodes);
            for i = 1:numNodes
                d = norm(dronePosition - nodePositions(i, :));
                d = max(d, obj.ReferenceDistance);  % avoid log(0) if drone is on top of a node
                rssiValues(i) = obj.ReferenceRSSI - ...
                    10 * obj.PathLossExponent * log10(d / obj.ReferenceDistance);
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