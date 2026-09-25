classdef DroneSurvey < matlab.System
    % DroneSurvey  Generates the drone's position over time as it moves
    % through a predefined lawnmower survey path.
    %
    % No inputs.
    %
    % Output:
    %   dronePosition - 1x3 vector, [x y z] of the drone's CURRENT survey point
    %
    % Behaviour: outputs one fixed waypoint from SurveyPoints per simulation
    % second (see getSampleTimeImpl), advancing to the next row each step.
    % Deterministic, no flight dynamics, no PX4 -- the drone simply "teleports"
    % to its next planned survey point once per second.
    %
    % Survey path: a 5x5 lawnmower grid over the 1000x1000 m area
    % (200 m spacing, altitude 30 m), 25 points total, direction alternating
    % row to row so consecutive points are always adjacent.

    properties
        SurveyPoints = [ ...
            50   50  30;  250   50  30;  450   50  30;  650   50  30;  850   50  30; ...
            850  250  30;  650  250  30;  450  250  30;  250  250  30;   50  250  30; ...
            50  450  30;  250  450  30;  450  450  30;  650  450  30;  850  450  30; ...
            850  650  30;  650  650  30;  450  650  30;  250  650  30;   50  650  30; ...
            50  850  30;  250  850  30;  450  850  30;  650  850  30;  850  850  30];
    end

    properties (DiscreteState)
        Index   % which row of SurveyPoints is "current"
    end

    methods (Access = protected)
        function setupImpl(obj)
            obj.Index = 1;
            if evalin('base', 'exist(''surveyPoints'', ''var'')')
                pts = evalin('base', 'surveyPoints');
                if ~isempty(pts)
                    obj.SurveyPoints = pts;
                end
            end
        end

        function dronePosition = stepImpl(obj)
            n = size(obj.SurveyPoints, 1);
            if n > 0
                idx = min(obj.Index, n);
                dronePosition = obj.SurveyPoints(idx, :);
                obj.Index = mod(obj.Index, n) + 1;
            else
                dronePosition = [50 50 30];
            end
        end

        function resetImpl(obj)
            obj.Index = 1;
        end

        function sts = getSampleTimeImpl(obj)
            % Move to a new survey point once per simulated second.
            sts = createSampleTime(obj, 'Type', 'Discrete', 'SampleTime', 1);
        end

        function num = getNumInputsImpl(~)
            num = 0;
        end
        function num = getNumOutputsImpl(~)
            num = 1;
        end
    end
end