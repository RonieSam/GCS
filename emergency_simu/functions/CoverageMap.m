classdef CoverageMap < matlab.System
    % CoverageMap  Accumulates drone survey measurements and draws a
    % point-based coverage map, with survey progress in the title.
    %
    % Inputs:
    %   dronePosition - 1x3, current drone position [x y z]
    %   rssiValues    - 1x3, RSSI (dBm) from each ground node at this position
    %
    % No outputs -- draws its own figure, same pattern as EnvironmentVisualizer.
    %
    % DESIGN NOTE (assumption): a survey point's coverage is classified using
    % the STRONGEST (max) of the 3 per-node RSSI values at that position --
    % i.e. "the best connection quality available here." Classification
    % reuses CoverageClassifier's exact thresholds via composition (it holds
    % and calls a real CoverageClassifier instance -- not a second, separately
    % maintained copy of the threshold logic).

    properties
        AreaSize  = [1000 1000]
        MaxPoints = 25   % total survey points, only used for the progress title
    end

    properties (Access = private)
        FigureHandle
        AxesHandle
        Classifier       % nested CoverageClassifier instance (reused, not duplicated)
        RecordedX
        RecordedY
        RecordedStatus
        PointCount
    end

    methods (Access = protected)
        function setupImpl(obj)
            if evalin('base', 'exist(''areaSize'', ''var'')')
                obj.AreaSize = evalin('base', 'areaSize');
            end
            if evalin('base', 'exist(''maxSurveyPoints'', ''var'')')
                obj.MaxPoints = max(evalin('base', 'maxSurveyPoints'), 25);
            end
            obj.FigureHandle = figure('Name', 'EmergencyNetwork - Coverage Map', ...
                'NumberTitle', 'off', 'Color', 'w');
            obj.AxesHandle = axes('Parent', obj.FigureHandle);
            obj.Classifier = CoverageClassifier();
            obj.RecordedX = [];
            obj.RecordedY = [];
            obj.RecordedStatus = [];
            obj.PointCount = 0;
        end

        function stepImpl(obj, dronePosition, rssiValues)
            bestRSSI    = max(rssiValues);
            pointStatus = obj.Classifier.step(bestRSSI);   % reuse Phase 3 thresholds

            obj.RecordedX(end + 1)      = dronePosition(1);
            obj.RecordedY(end + 1)      = dronePosition(2);
            obj.RecordedStatus(end + 1) = pointStatus;
            obj.PointCount = obj.PointCount + 1;

            ax = obj.AxesHandle;
            cla(ax);
            hold(ax, 'on'); grid(ax, 'on'); box(ax, 'on'); axis(ax, 'equal');
            xlim(ax, [0 obj.AreaSize(1)]);
            ylim(ax, [0 obj.AreaSize(2)]);
            xlabel(ax, 'X (metres)');
            ylabel(ax, 'Y (metres)');
            title(ax, sprintf('Coverage Map - Survey point %d / %d', ...
                obj.PointCount, obj.MaxPoints));

            statusColors = {[0.85 0 0], [1 0.55 0], [0.90 0.75 0], [0 0.6 0]}; % GAP WEAK MODERATE GOOD

            for i = 1:numel(obj.RecordedStatus)
                idx = obj.RecordedStatus(i) + 1;
                plot(ax, obj.RecordedX(i), obj.RecordedY(i), 's', ...
                    'MarkerFaceColor', statusColors{idx}, ...
                    'MarkerEdgeColor', 'k', 'MarkerSize', 12);
            end

            % Current drone position, highlighted
            plot(ax, dronePosition(1), dronePosition(2), '^', ...
                'MarkerFaceColor', 'y', 'MarkerEdgeColor', 'k', 'MarkerSize', 10);

            drawnow;
        end

        function resetImpl(obj)
            obj.RecordedX = [];
            obj.RecordedY = [];
            obj.RecordedStatus = [];
            obj.PointCount = 0;
        end

        function num = getNumInputsImpl(~)
            num = 2;
        end
        function num = getNumOutputsImpl(~)
            num = 0;
        end
    end
end