classdef CoverageComparison < matlab.System
    % CoverageComparison  Computes actual numerical before/after coverage
    % statistics -- never a "looks better" visual judgment.
    %
    % Inputs:
    %   beforeStatus, afterStatus - 1xMaxPoints status arrays (3/2/1/0),
    %                               NaN in unfilled slots
    %   beforeCount, afterCount  - scalars, how many entries are valid
    %
    % Outputs (all scalars):
    %   beforeGap, beforeWeak, beforeModerate, beforeGood - BEFORE counts
    %   afterGap,  afterWeak,  afterModerate,  afterGood  - AFTER counts
    %   improvedPoints             - # survey points where afterStatus > beforeStatus
    %                                (GAP=0 < WEAK=1 < MODERATE=2 < GOOD=3)
    %   gapReduction               - beforeGap - afterGap
    %   coverageImprovementPercent - 100*(beforeGap-afterGap)/beforeGap,
    %                                or 0 if beforeGap == 0 (never divides by zero)
    %   totalPoints                - number of points actually compared

    properties (Nontunable)
        MaxPoints = 25
    end

    methods (Access = protected)
        function [beforeGap, beforeWeak, beforeModerate, beforeGood, ...
                afterGap, afterWeak, afterModerate, afterGood, ...
                improvedPoints, gapReduction, coverageImprovementPercent, totalPoints] = ...
                stepImpl(~, beforeStatus, afterStatus, beforeCount, afterCount)

            totalPoints = min(beforeCount, afterCount);

            beforeGap = 0; beforeWeak = 0; beforeModerate = 0; beforeGood = 0;
            afterGap  = 0; afterWeak  = 0; afterModerate  = 0; afterGood  = 0;
            improvedPoints = 0;

            for i = 1:totalPoints
                b = beforeStatus(i);
                a = afterStatus(i);

                switch b
                    case 0, beforeGap      = beforeGap + 1;
                    case 1, beforeWeak     = beforeWeak + 1;
                    case 2, beforeModerate = beforeModerate + 1;
                    case 3, beforeGood     = beforeGood + 1;
                end
                switch a
                    case 0, afterGap      = afterGap + 1;
                    case 1, afterWeak     = afterWeak + 1;
                    case 2, afterModerate = afterModerate + 1;
                    case 3, afterGood     = afterGood + 1;
                end

                if a > b
                    improvedPoints = improvedPoints + 1;
                end
            end

            gapReduction = beforeGap - afterGap;

            if beforeGap > 0
                coverageImprovementPercent = 100 * (beforeGap - afterGap) / beforeGap;
            else
                coverageImprovementPercent = 0;
            end
        end

        function num = getNumInputsImpl(~)
            num = 4;
        end
        function num = getNumOutputsImpl(~)
            num = 12;
        end
    end
end
