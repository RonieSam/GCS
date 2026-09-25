classdef CoverageSummary < matlab.System
    % CoverageSummary  Counts how many nodes fall into each coverage category.
    %
    % Input:
    %   status - 1xN vector of coverage codes (3=GOOD, 2=MODERATE, 1=WEAK, 0=GAP)
    %
    % Output:
    %   summary - 1x4 vector: [GoodCount ModerateCount WeakCount GapCount]
    %             Recomputed every step from whatever status currently holds
    %             — nothing here is hard-coded.

    methods (Access = protected)
        function summary = stepImpl(~, status)
            goodCount     = sum(status == 3);
            moderateCount = sum(status == 2);
            weakCount     = sum(status == 1);
            gapCount      = sum(status == 0);
            summary = [goodCount, moderateCount, weakCount, gapCount];
        end

        function num = getNumInputsImpl(~)
            num = 1;
        end
        function num = getNumOutputsImpl(~)
            num = 1;
        end
    end
end