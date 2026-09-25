classdef EnvironmentVisualizer < matlab.System
    % EnvironmentVisualizer  Draws the environment plus per-node RSSI/coverage.
    %
    % Inputs (Simulink signals):
    %   nodePositions - Nx3 matrix, [x y z] per ground node (metres)
    %   dronePosition - 1x3 vector, [x y z] (metres)
    %   rssiValues    - 1xN vector, RSSI in dBm per node (from RFModel)
    %   status        - 1xN vector, coverage code per node
    %                   (3=GOOD, 2=MODERATE, 1=WEAK, 0=GAP; from CoverageClassifier)
    %
    % Block parameters (dialog, tunable from base workspace):
    %   AreaSize    - [width height] in metres
    %   NodeLabels  - cell array of label strings
    %   Buildings   - Nx4 matrix [x y width depth]

    properties
        AreaSize   = [1000 1000]
        NodeLabels = {'Node 1', 'Node 2', 'Node 3'}
        Buildings  = zeros(0, 4)
    end

    properties (Access = private)
        FigureHandle
        AxesHandle
    end

    methods (Access = protected)
        function setupImpl(obj)
            if evalin('base', 'exist(''areaSize'', ''var'')')
                obj.AreaSize = evalin('base', 'areaSize');
            end
            if evalin('base', 'exist(''nodeLabels'', ''var'')')
                obj.NodeLabels = evalin('base', 'nodeLabels');
            end
            obj.FigureHandle = figure('Name', 'EmergencyNetwork - Coverage', ...
                'NumberTitle', 'off', 'Color', 'w');
            obj.AxesHandle = axes('Parent', obj.FigureHandle);
        end

        function stepImpl(obj, nodePositions, dronePosition, rssiValues, status)
            ax = obj.AxesHandle;
            cla(ax);
            hold(ax, 'on'); grid(ax, 'on'); box(ax, 'on'); axis(ax, 'equal');
            xlim(ax, [0 obj.AreaSize(1)]);
            ylim(ax, [0 obj.AreaSize(2)]);
            xlabel(ax, 'X (metres)');
            ylabel(ax, 'Y (metres)');
            title(ax, 'Emergency Network Environment - Coverage Status');

            % --- Buildings (grey rectangles) ---
            for i = 1:size(obj.Buildings, 1)
                x = obj.Buildings(i, 1); y = obj.Buildings(i, 2);
                w = obj.Buildings(i, 3); d = obj.Buildings(i, 4);
                rectangle(ax, 'Position', [x y w d], ...
                    'FaceColor', [0.6 0.6 0.6], 'EdgeColor', 'k');
            end

            % --- Status -> color / name lookup (index = status code + 1) ---
            statusColors = {[0.85 0 0], [1 0.55 0], [0.90 0.75 0], [0 0.6 0]}; % GAP WEAK MODERATE GOOD
            statusNames  = {'GAP', 'WEAK', 'MODERATE', 'GOOD'};

            % --- Ground nodes: colored marker + RSSI/status text ---
            for i = 1:size(nodePositions, 1)
                idx = status(i) + 1;
                nodeColor = statusColors{idx};
                plot(ax, nodePositions(i, 1), nodePositions(i, 2), 'o', ...
                    'MarkerFaceColor', nodeColor, 'MarkerEdgeColor', 'k', 'MarkerSize', 10);
                lbl = sprintf('Node %d', i);
                if i <= numel(obj.NodeLabels) && ~isempty(obj.NodeLabels{i})
                    lbl = obj.NodeLabels{i};
                end
                labelText = sprintf('%s\nRSSI: %.0f dBm\n%s', ...
                    lbl, rssiValues(i), statusNames{idx});
                text(ax, nodePositions(i, 1) + 15, nodePositions(i, 2), labelText, ...
                    'FontSize', 8, 'Color', nodeColor, 'VerticalAlignment', 'middle');
            end

            % --- Drone ---
            plot(ax, dronePosition(1), dronePosition(2), 'r^', ...
                'MarkerFaceColor', 'r', 'MarkerSize', 10);
            text(ax, dronePosition(1) + 15, dronePosition(2), 'Drone', ...
                'FontSize', 9, 'Color', 'r');

            % --- Static color key (fixed text box, not a dynamic legend) ---
            keyStr = sprintf('Status colors:\nGOOD (green)\nMODERATE (yellow)\nWEAK (orange)\nGAP (red)');
            text(ax, 20, obj.AreaSize(2) - 20, keyStr, 'FontSize', 8, ...
                'VerticalAlignment', 'top', 'BackgroundColor', 'w', 'EdgeColor', 'k');

            drawnow;
        end

        function resetImpl(~)
            % No internal state to reset.
        end
    end

    methods (Access = protected)
        function num = getNumInputsImpl(~)
            num = 4;
        end
        function num = getNumOutputsImpl(~)
            num = 0;
        end
        function flag = isInputSizeMutableImpl(~, ~)
            flag = true;
        end
    end
end