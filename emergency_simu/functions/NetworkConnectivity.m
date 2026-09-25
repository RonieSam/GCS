classdef NetworkConnectivity < matlab.System
    % NetworkConnectivity  Determines which nodes are within simulated
    % communication range, for any node count N (3 for BEFORE, 4 for AFTER --
    % not hardcoded either way, same class reused for both).
    %
    % Inputs:
    %   nodePositions - Nx3 (accepted now for consistency with the rest of
    %                   the model; not used in this step's calculation --
    %                   Phase 7 Step 2's link visualization is what will
    %                   need the actual positions)
    %   rssiValues    - 1xN, the RSSI already computed for each node by
    %                   RFModel / RFModel (After) -- this block does NOT
    %                   recompute RF physics, it just classifies what's
    %                   already been calculated
    %
    % Outputs:
    %   connected            - 1xN, 1 if that node's RSSI >= CommunicationThreshold, else 0
    %   connectedCount       - scalar
    %   disconnectedCount    - scalar
    %   connectedPercentage  - scalar, 100 * connectedCount / N (0 if N == 0)
    %
    % DEMO ASSUMPTION (simulation only, not a real Wi-Fi/networking spec):
    % a node counts as "reachable" when its measured RSSI is at or above
    % CommunicationThreshold. This is a plain, tunable block parameter --
    % change it on the block dialog, not in this file, if you want to
    % experiment with a stricter or looser definition of "connected."

    properties (Nontunable)
        CommunicationThreshold = -85   % dBm
    end

    methods (Access = protected)
        function [connected, connectedCount, disconnectedCount, connectedPercentage] = ...
                stepImpl(obj, ~, rssiValues)

            n = numel(rssiValues);
            connected = double(rssiValues >= obj.CommunicationThreshold);

            connectedCount    = sum(connected);
            disconnectedCount = n - connectedCount;

            if n > 0
                connectedPercentage = 100 * connectedCount / n;
            else
                connectedPercentage = 0;
            end
        end

        function num = getNumInputsImpl(~)
            num = 2;
        end
        function num = getNumOutputsImpl(~)
            num = 4;
        end
    end
end
