classdef RFModel < matlab.System
    % RFModel  Simplified log-distance path-loss RSSI calculator.
    %
    % Inputs:
    %   nodePositions - Nx3 matrix, [x y z] per ground node
    %   dronePosition - 1x3 vector, [x y z]
    %
    % Output:
    %   rssiValues - 1xN vector, simulated RSSI (dBm) from drone to each node
    %
    % Distance is purely horizontal (X-Y plane only).
    %   d        = hypot(droneX-nodeX, droneY-nodeY)
    %   d        = max(d, ReferenceDistance)
    %   dEff     = d / RFRangeScale
    %   RSSI     = ReferenceRSSI - 10*PathLossExponent*log10(dEff/ReferenceDistance)

    properties (Nontunable)
        ReferenceRSSI     = -30.0
        ReferenceDistance = 1.0
        PathLossExponent  = 2.2
        RFRangeScale      = 0.30
    end

    methods (Access = protected)
        function setupImpl(~)
            % No base-workspace access. All parameters come through block dialog.
        end

        function rssiValues = stepImpl(obj, nodePositions, dronePosition)
            numNodes = size(nodePositions, 1);
            rssiValues = zeros(1, numNodes);
            scale = max(obj.RFRangeScale, 1e-6);
            for i = 1:numNodes
                d = hypot(dronePosition(1) - nodePositions(i, 1), ...
                          dronePosition(2) - nodePositions(i, 2));
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

        function sizeOut = getOutputSizeImpl(obj)
            inputSize = propagatedInputSize(obj, 1);
            sizeOut = [1 inputSize(1)];
        end

        function typeOut = getOutputDataTypeImpl(~)
            typeOut = 'double';
        end

        function c = isOutputComplexImpl(~)
            c = false;
        end

        function f = isOutputFixedSizeImpl(~)
            f = true;
        end
    end
end