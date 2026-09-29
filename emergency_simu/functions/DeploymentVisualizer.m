classdef DeploymentVisualizer < matlab.System
    % DeploymentVisualizer  Side-by-side BEFORE / AFTER coverage view, with
    % the simulated new node clearly marked in the AFTER panel only.
    %
    % Inputs:
    %   nodePositions         - Nx3, ORIGINAL ground nodes (shown in both panels)
    %   deployedNodePositions - (N+1)x3, the final row is the simulated new node
    %                           (drawn only if it is not NaN -- i.e. only if Phase 5
    %                           actually produced a candidate).
    %                           Row count is dynamic; do NOT assume row 4.
    %   beforeX, beforeY, beforeStatus, beforeCount - BEFORE survey (N nodes)
    %   afterX,  afterY,  afterStatus,  afterCount  - AFTER survey (N+1 nodes)
    %
    % No outputs -- draws its own figure with two subplots.

    properties (Nontunable)
        AreaSize  = [1000 1000]
    end

    properties (Access = private)
        FigureHandle
        AxesBefore
        AxesAfter
    end

    methods (Access = protected)
        function setupImpl(obj)
            obj.FigureHandle = figure('Name', 'EmergencyNetwork - Before/After Deployment', ...
                'NumberTitle', 'off', 'Color', 'w', 'Position', [100 100 1100 520]);
            obj.AxesBefore = subplot(1, 2, 1, 'Parent', obj.FigureHandle);
            obj.AxesAfter  = subplot(1, 2, 2, 'Parent', obj.FigureHandle);
        end

        function stepImpl(obj, nodePositions, deployedNodePositions, ...
                beforeX, beforeY, beforeStatus, beforeCount, ...
                afterX, afterY, afterStatus, afterCount)

            statusColors = {[0.85 0 0], [1 0.55 0], [0.90 0.75 0], [0 0.6 0]}; % GAP WEAK MODERATE GOOD

            obj.drawPanel(obj.AxesBefore, 'BEFORE Deployment', nodePositions, ...
                beforeX, beforeY, beforeStatus, beforeCount, statusColors, [], false);

            % The newly deployed node is the LAST row of deployedNodePositions.
            % This is dynamic: it works regardless of N (do NOT hardcode row 4).
            nRows = size(deployedNodePositions, 1);
            if nRows > 0
                newNode = deployedNodePositions(nRows, :);
            else
                newNode = [NaN NaN NaN];
            end

            obj.drawPanel(obj.AxesAfter, 'AFTER Deployment', nodePositions, ...
                afterX, afterY, afterStatus, afterCount, statusColors, newNode, true);

            drawnow;
        end

        function resetImpl(~)
        end

        function num = getNumInputsImpl(~)
            num = 10;
        end
        function num = getNumOutputsImpl(~)
            num = 0;
        end
    end

    methods (Access = private)
        function drawPanel(obj, ax, panelTitle, nodePositions, ...
                pointX, pointY, pointStatus, pointCount, statusColors, newNode, showNewNode)
            cla(ax);
            hold(ax, 'on'); grid(ax, 'on'); box(ax, 'on'); axis(ax, 'equal');
            xlim(ax, [0 obj.AreaSize(1)]);
            ylim(ax, [0 obj.AreaSize(2)]);
            xlabel(ax, 'X (metres)');
            ylabel(ax, 'Y (metres)');
            title(ax, panelTitle);

            % No Buildings: the project has no building model.

            for i = 1:pointCount
                idx = pointStatus(i) + 1;
                plot(ax, pointX(i), pointY(i), 's', ...
                    'MarkerFaceColor', statusColors{idx}, 'MarkerEdgeColor', 'k', 'MarkerSize', 10);
            end

            plot(ax, nodePositions(:, 1), nodePositions(:, 2), 'o', ...
                'MarkerFaceColor', 'b', 'MarkerEdgeColor', 'k', 'MarkerSize', 9);

            if showNewNode && ~isempty(newNode) && ~isnan(newNode(1))
                plot(ax, newNode(1), newNode(2), 'p', ...
                    'MarkerFaceColor', 'g', 'MarkerEdgeColor', 'k', 'MarkerSize', 16);
                text(ax, newNode(1) + 15, newNode(2), 'Deployed Node', ...
                    'FontSize', 8, 'Color', [0 0.5 0], 'FontWeight', 'bold');
            end
        end
    end
end
