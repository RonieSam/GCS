classdef GapVisualizer < matlab.System
    % GapVisualizer  Shows the current network, detected coverage gaps, and
    % ranked candidate node locations in one figure. Separate from
    % EnvironmentVisualizer and CoverageMap -- both keep working unchanged.
    %
    % Inputs:
    %   nodePositions  - 3x3, existing ground node positions
    %   gapX, gapY     - 1xMaxPoints (NaN-padded), from GapDetector
    %   gapCount       - scalar
    %   candidateX, candidateY - 1xMaxCandidates (NaN-padded), from CandidatePlacement
    %   candidateCount - scalar
    %
    % No outputs -- draws its own figure.
    %
    % Legend: existing nodes = blue circles, gap survey points = red
    % squares, candidate locations = black stars (larger, sized/labeled by
    % rank so higher-priority candidates stand out).

    properties (Nontunable)
        AreaSize  = [1000 1000]
        Buildings = zeros(0, 4)
    end

    properties (Access = private)
        FigureHandle
        AxesHandle
    end

    methods (Access = protected)
        function setupImpl(obj)
            obj.FigureHandle = figure('Name', 'EmergencyNetwork - Gap Analysis', ...
                'NumberTitle', 'off', 'Color', 'w');
            obj.AxesHandle = axes('Parent', obj.FigureHandle);
        end

        function stepImpl(obj, nodePositions, gapX, gapY, gapCount, ...
                candidateX, candidateY, candidateCount)
            ax = obj.AxesHandle;
            cla(ax);
            hold(ax, 'on'); grid(ax, 'on'); box(ax, 'on'); axis(ax, 'equal');
            xlim(ax, [0 obj.AreaSize(1)]);
            ylim(ax, [0 obj.AreaSize(2)]);
            xlabel(ax, 'X (metres)');
            ylabel(ax, 'Y (metres)');
            title(ax, sprintf('Gap Analysis - %d gap points, %d candidate(s)', ...
                gapCount, candidateCount));

            % --- Buildings ---
            for i = 1:size(obj.Buildings, 1)
                x = obj.Buildings(i, 1); y = obj.Buildings(i, 2);
                w = obj.Buildings(i, 3); d = obj.Buildings(i, 4);
                rectangle(ax, 'Position', [x y w d], ...
                    'FaceColor', [0.6 0.6 0.6], 'EdgeColor', 'k');
            end

            % --- Existing ground nodes: blue circles ---
            plot(ax, nodePositions(:,1), nodePositions(:,2), 'o', ...
                'MarkerFaceColor', 'b', 'MarkerEdgeColor', 'k', 'MarkerSize', 9, ...
                'DisplayName', 'Existing node');

            % --- Gap survey points: red squares ---
            validGaps = ~isnan(gapX(1:gapCount));
            plot(ax, gapX(validGaps), gapY(validGaps), 's', ...
                'MarkerFaceColor', 'r', 'MarkerEdgeColor', 'k', 'MarkerSize', 9, ...
                'DisplayName', 'Coverage gap');

            % --- Candidate locations: black stars, labeled by rank ---
            for i = 1:candidateCount
                plot(ax, candidateX(i), candidateY(i), 'p', ...
                    'MarkerFaceColor', 'k', 'MarkerEdgeColor', 'y', ...
                    'MarkerSize', 18, 'LineWidth', 1.5);
                text(ax, candidateX(i) + 15, candidateY(i), ...
                    sprintf('Candidate %d', i), ...
                    'FontSize', 9, 'FontWeight', 'bold', 'Color', 'k');
            end

            legend(ax, {'Existing node', 'Coverage gap'}, 'Location', 'bestoutside');
            drawnow;
        end

        function resetImpl(~)
        end

        function num = getNumInputsImpl(~)
            num = 7;
        end
        function num = getNumOutputsImpl(~)
            num = 0;
        end
    end
end