classdef DroneSurvey < matlab.System
    % DroneSurvey
    % Replays survey points supplied through the SurveyPoints property.
    %
    % Input:
    %   None
    %
    % Output:
    %   dronePosition - 1x3 vector [x y z]
    %
    % One survey point is output every simulated second.

    properties (Nontunable)
        SurveyPoints = [ ...
            50   50  30;
            250  50  30;
            450  50  30;
            650  50  30;
            850  50  30;
            850 250  30;
            650 250  30;
            450 250  30;
            250 250  30;
             50 250  30;
             50 450  30;
            250 450  30;
            450 450  30;
            650 450  30;
            850 450  30;
            850 650  30;
            650 650  30;
            450 650  30;
            250 650  30;
             50 650  30;
             50 850  30;
            250 850  30;
            450 850  30;
            650 850  30;
            850 850  30;
        ];
    end

    properties (DiscreteState)
        Index
    end

    methods (Access = protected)

        function setupImpl(obj)
            obj.Index = 1;
        end

        function dronePosition = stepImpl(obj)

            n = size(obj.SurveyPoints, 1);

            if n > 0
                idx = min(obj.Index, n);

                dronePosition = obj.SurveyPoints(idx, :);

                obj.Index = obj.Index + 1;

                if obj.Index > n
                    obj.Index = 1;
                end
            else
                dronePosition = [50 50 30];
            end
        end

        function resetImpl(obj)
            obj.Index = 1;
        end
        function [sz, dt, cp] = getDiscreteStateSpecificationImpl(~, name)
            if strcmp(name, 'Index')
                sz = [1 1];
                dt = 'double';
                cp = false;
            else
                error('Unknown discrete state: %s', name);
            end
        end
        function sts = getSampleTimeImpl(obj)
            sts = createSampleTime(obj, ...
                'Type', 'Discrete', ...
                'SampleTime', 1);
        end

        function num = getNumInputsImpl(~)
            num = 0;
        end

        function num = getNumOutputsImpl(~)
            num = 1;
        end

        % Explicit output properties for Simulink propagation
        function sizeOut = getOutputSizeImpl(~)
            sizeOut = [1 3];
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