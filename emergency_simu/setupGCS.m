%% setupGCS.m
% Phase 4: Dynamic RF Coverage, Gap Detection & Candidate Placement Bridge
%
% Connects to FastAPI backend at http://127.0.0.1:8000, pulls real-time
% or accumulated RF survey dataset from the GCS RF Scan, transforms coordinates
% into local ENU metres, runs coverage classification, detects coverage gaps,
% generates ranked candidate locations for new communication nodes, and configures
% all workspace variables for EmergencyNetwork.slx.
%
% Key Features:
%   1. Dynamic Node Handling: Exactly N nodes deployed -> exactly N RSSI values.
%      No hardcoded 3-node fallback.
%   2. RFRangeScale = 0.25: Calibrates effective coverage distance to ~1/4 range
%      without altering UAV altitude or flight path.
%   3. Dynamic Affected Area: Adapts areaSize to the actual user polygon geometry.
%   4. Real RF Survey: Uses real GPS + RSSI points collected by the UAV.
%   5. Direct Model Integration: Configures and opens EmergencyNetwork.slx directly.

clear; clc;

%% ---- Configuration ----
BACKEND_HOST = '127.0.0.1';
BACKEND_PORT = 8000;
BACKEND_URL  = sprintf('http://%s:%d', BACKEND_HOST, BACKEND_PORT);
SURVEY_DATA_ENDPOINT = [BACKEND_URL '/api/rf-survey/data'];
NODES_ENDPOINT       = [BACKEND_URL '/api/nodes'];

% Phase 4: Configurable RF range scale (1.0 = normal, 0.25 = 1/4 effective range)
RFRangeScale = 0.25;

% Local tangent-plane conversion constant (matching backend/coordinate_mapper.py)
METRES_PER_DEG_LAT = 111320.0;

% Coverage classification thresholds (dBm)
GOOD_THRESH     = -60.0;
MODERATE_THRESH = -75.0;
WEAK_THRESH     = -85.0;
% GAP <= -85.0 dBm

fprintf('====================================================================\n');
fprintf('  Phase 4: Dynamic RF Coverage, Gap Detection & Candidate Placement \n');
fprintf('====================================================================\n');
fprintf('Backend URL:       %s\n', BACKEND_URL);
fprintf('RF Range Scale:    %.2f (effective horizontal coverage ~1/4)\n', RFRangeScale);

%% ---- Fetch Survey Data & Deployed Nodes from Backend ----
options = weboptions('Timeout', 10, 'ContentType', 'json');

surveyJson = [];
deployedNodesList = [];
try
    surveyJson = webread(SURVEY_DATA_ENDPOINT, options);
    fprintf('Connected to backend survey API. State: %s | Samples: %d\n', ...
        surveyJson.state, surveyJson.sample_count);
catch ME
    warning('Could not read survey data from %s: %s', SURVEY_DATA_ENDPOINT, ME.message);
    if exist('gcs_survey_data.mat', 'file')
        load('gcs_survey_data.mat');
        fprintf('Loaded cached survey data from gcs_survey_data.mat\n');
    else
        surveyJson = struct('state', 'IDLE', 'sample_count', 0, ...
            'scan_start_position', [], 'affected_area', [], ...
            'deployed_nodes', [], 'samples', []);
    end
end

% Also query /api/nodes directly to ensure active deployed nodes are current
try
    deployedNodesList = webread(NODES_ENDPOINT, options);
catch
    if isfield(surveyJson, 'deployed_nodes')
        deployedNodesList = surveyJson.deployed_nodes;
    end
end

%% ---- Process Affected Area & Dynamic Dimensions ----
hasArea = isfield(surveyJson, 'affected_area') && ~isempty(surveyJson.affected_area);
polyLats = [];
polyLons = [];

if hasArea
    rawArea = surveyJson.affected_area;
    if iscell(rawArea)
        nPoly = numel(rawArea);
        polyLats = zeros(nPoly, 1);
        polyLons = zeros(nPoly, 1);
        for i = 1:nPoly
            polyLats(i) = rawArea{i}.lat;
            polyLons(i) = rawArea{i}.lon;
        end
    elseif isstruct(rawArea)
        polyLats = [rawArea.lat]';
        polyLons = [rawArea.lon]';
    end
end

if ~isempty(polyLats)
    originLat = min(polyLats);
    originLon = min(polyLons);
    maxLat    = max(polyLats);
    maxLon    = max(polyLons);
    cosLat    = cosd((originLat + maxLat) / 2);
    
    widthM  = max((maxLon - originLon) * METRES_PER_DEG_LAT * cosLat, 80);
    heightM = max((maxLat - originLat) * METRES_PER_DEG_LAT, 80);
    
    % Pad dimensions slightly for visualization borders (10% padding)
    areaSize = [ceil(widthM * 1.1), ceil(heightM * 1.1)];
    
    affectedAreaPolyM = [ ...
        (polyLons - originLon) * METRES_PER_DEG_LAT * cosLat, ...
        (polyLats - originLat) * METRES_PER_DEG_LAT ...
    ];
else
    originLat = 13.0827; % GCS planning reference
    originLon = 80.2707;
    cosLat    = cosd(originLat);
    areaSize  = [1000 1000];
    affectedAreaPolyM = [0 0; 1000 0; 1000 1000; 0 1000];
end

fprintf('Affected Area Dimensions: [%.1f m, %.1f m]\n', areaSize(1), areaSize(2));

%% ---- Process Ground Communication Nodes (DYNAMIC) ----
% 1 node -> 1 RSSI; 2 nodes -> 2 RSSI; N nodes -> N RSSI.
% No hardcoded fallback to 3 nodes!
nodePositions = zeros(0, 3);
nodeLabels    = {};

rawNodes = [];
if ~isempty(deployedNodesList)
    rawNodes = deployedNodesList;
elseif isfield(surveyJson, 'deployed_nodes') && ~isempty(surveyJson.deployed_nodes)
    rawNodes = surveyJson.deployed_nodes;
end

if ~isempty(rawNodes)
    if iscell(rawNodes)
        numNodes = numel(rawNodes);
        nodePositions = zeros(numNodes, 3);
        nodeLabels    = cell(1, numNodes);
        for i = 1:numNodes
            n = rawNodes{i};
            nx = (n.lon - originLon) * METRES_PER_DEG_LAT * cosLat;
            ny = (n.lat - originLat) * METRES_PER_DEG_LAT;
            nz = 10.0;
            if isfield(n, 'alt') && ~isempty(n.alt), nz = n.alt; end
            nodePositions(i, :) = [nx, ny, nz];
            if isfield(n, 'id') && ~isempty(n.id)
                nodeLabels{i} = n.id;
            else
                nodeLabels{i} = sprintf('COMM-%03d', i);
            end
        end
    elseif isstruct(rawNodes)
        numNodes = numel(rawNodes);
        nodePositions = zeros(numNodes, 3);
        nodeLabels    = cell(1, numNodes);
        for i = 1:numNodes
            nx = (rawNodes(i).lon - originLon) * METRES_PER_DEG_LAT * cosLat;
            ny = (rawNodes(i).lat - originLat) * METRES_PER_DEG_LAT;
            nz = 10.0;
            if isfield(rawNodes(i), 'alt') && ~isempty(rawNodes(i).alt), nz = rawNodes(i).alt; end
            nodePositions(i, :) = [nx, ny, nz];
            if isfield(rawNodes(i), 'id') && ~isempty(rawNodes(i).id)
                nodeLabels{i} = rawNodes(i).id;
            else
                nodeLabels{i} = sprintf('COMM-%03d', i);
            end
        end
    end
end

numNodesTotal = size(nodePositions, 1);
fprintf('Active Deployed Nodes: %d\n', numNodesTotal);
for i = 1:numNodesTotal
    fprintf('  [%d] %s at [%.1f m, %.1f m, %.1f m]\n', ...
        i, nodeLabels{i}, nodePositions(i, 1), nodePositions(i, 2), nodePositions(i, 3));
end

%% ---- Process Scan Start Position (scanStartPosition) ----
if isfield(surveyJson, 'scan_start_position') && ~isempty(surveyJson.scan_start_position)
    sp = surveyJson.scan_start_position;
    dx = (sp.longitude - originLon) * METRES_PER_DEG_LAT * cosLat;
    dy = (sp.latitude  - originLat) * METRES_PER_DEG_LAT;
    dz = sp.altitude;
    if dz <= 0, dz = 30.0; end
    dronePosition = [dx, dy, dz];
    scanStartPosition = sp;
else
    dronePosition = [50 50 30];
    scanStartPosition = struct('latitude', originLat, 'longitude', originLon, 'altitude', 30.0);
end

%% ---- Process Real RF Survey Samples ----
numSamples = 0;
if isfield(surveyJson, 'samples') && ~isempty(surveyJson.samples)
    rawSamples = surveyJson.samples;
    numSamples = numel(rawSamples);
end

if numSamples > 0
    surveyTimestamp = zeros(numSamples, 1);
    surveyLat       = zeros(numSamples, 1);
    surveyLon       = zeros(numSamples, 1);
    surveyAlt       = zeros(numSamples, 1);
    surveyX         = zeros(numSamples, 1);
    surveyY         = zeros(numSamples, 1);
    surveyBestRSSI  = zeros(numSamples, 1);
    surveyWaypoint  = zeros(numSamples, 1);
    surveyRSSI      = -100 * ones(numSamples, max(numNodesTotal, 1));
    
    for k = 1:numSamples
        if iscell(rawSamples)
            s = rawSamples{k};
        else
            s = rawSamples(k);
        end
        surveyTimestamp(k) = s.timestamp;
        surveyLat(k)       = s.latitude;
        surveyLon(k)       = s.longitude;
        surveyAlt(k)       = s.altitude;
        if isfield(s, 'best_rssi'), surveyBestRSSI(k) = s.best_rssi; end
        if isfield(s, 'current_waypoint'), surveyWaypoint(k) = s.current_waypoint; end
        
        surveyX(k) = (s.longitude - originLon) * METRES_PER_DEG_LAT * cosLat;
        surveyY(k) = (s.latitude  - originLat) * METRES_PER_DEG_LAT;
        
        if isfield(s, 'rssi') && ~isempty(s.rssi)
            rDict = s.rssi;
            for nIdx = 1:numNodesTotal
                nid = nodeLabels{nIdx};
                valName = regexprep(nid, '[^a-zA-Z0-9_]', '_');
                if isstruct(rDict) && isfield(rDict, valName)
                    surveyRSSI(k, nIdx) = rDict.(valName);
                elseif isstruct(rDict) && isfield(rDict, nid)
                    surveyRSSI(k, nIdx) = rDict.(nid);
                end
            end
        end
    end
    
    % Recompute bestRSSI as max across actual deployed nodes
    if numNodesTotal > 0
        surveyBestRSSI = max(surveyRSSI(:, 1:numNodesTotal), [], 2);
    else
        surveyBestRSSI = -100 * ones(numSamples, 1);
    end
    
    surveyPoints = [surveyX, surveyY, surveyAlt];
    fprintf('Loaded %d real survey samples from RF Scan.\n', numSamples);
else
    fprintf('No survey samples in backend yet. Creating sample grid for demonstration...\n');
    % Generate a grid over the actual affected area for dry-run
    gridRes = 30;
    xSteps = 20:gridRes:(areaSize(1)-20);
    ySteps = 20:gridRes:(areaSize(2)-20);
    [Xg, Yg] = meshgrid(xSteps, ySteps);
    surveyX = Xg(:);
    surveyY = Yg(:);
    numSamples = numel(surveyX);
    surveyAlt = 25 * ones(numSamples, 1);
    surveyTimestamp = (1:numSamples)';
    surveyLat = originLat + surveyY / METRES_PER_DEG_LAT;
    surveyLon = originLon + surveyX / (METRES_PER_DEG_LAT * cosLat);
    surveyPoints = [surveyX, surveyY, surveyAlt];
    
    surveyRSSI = -100 * ones(numSamples, max(numNodesTotal, 1));
    for k = 1:numSamples
        for nIdx = 1:numNodesTotal
            d = norm([surveyX(k), surveyY(k), surveyAlt(k)] - nodePositions(nIdx, :));
            dEff = max(d, 1.0) / max(RFRangeScale, 1e-6);
            surveyRSSI(k, nIdx) = -30.0 - (10.0 * 2.2 * log10(dEff));
        end
    end
    if numNodesTotal > 0
        surveyBestRSSI = max(surveyRSSI(:, 1:numNodesTotal), [], 2);
    else
        surveyBestRSSI = -100 * ones(numSamples, 1);
    end
end

maxSurveyPoints = max(numSamples, 25);
simStopTime     = max(numSamples, 49);
buildings       = zeros(0, 5);

%% ---- Coverage Classification & Gap Detection ----
% Status codes: 3 = GOOD, 2 = MODERATE, 1 = WEAK, 0 = GAP
surveyStatus = zeros(numSamples, 1);
for k = 1:numSamples
    r = surveyBestRSSI(k);
    if r > GOOD_THRESH
        surveyStatus(k) = 3;
    elseif r > MODERATE_THRESH
        surveyStatus(k) = 2;
    elseif r > WEAK_THRESH
        surveyStatus(k) = 1;
    else
        surveyStatus(k) = 0; % GAP
    end
end

gapIdx   = find(surveyStatus == 0);
gapCount = numel(gapIdx);
gapX     = surveyX(gapIdx);
gapY     = surveyY(gapIdx);

nGood     = sum(surveyStatus == 3);
nModerate = sum(surveyStatus == 2);
nWeak     = sum(surveyStatus == 1);

fprintf('\n---- Coverage & Gap Detection Summary ----\n');
fprintf('Total Survey Points: %d\n', numSamples);
fprintf('  GOOD (> -60 dBm):      %4d (%5.1f%%)\n', nGood, 100 * nGood / numSamples);
fprintf('  MODERATE (-75..-60):   %4d (%5.1f%%)\n', nModerate, 100 * nModerate / numSamples);
fprintf('  WEAK (-85..-75):       %4d (%5.1f%%)\n', nWeak, 100 * nWeak / numSamples);
fprintf('  GAP (<= -85 dBm):      %4d (%5.1f%%)\n', gapCount, 100 * gapCount / numSamples);

%% ---- Candidate Placement Algorithm (Phase 4) ----
% Cluster gap points using single-link clustering scaled by RFRangeScale
GapClusterDistance = 250 * RFRangeScale; % e.g. 62.5 m
candidates = [];

if gapCount > 0
    regionId = zeros(gapCount, 1);
    nextRegion = 1;
    for i = 1:gapCount
        if regionId(i) ~= 0, continue; end
        regionId(i) = nextRegion;
        changed = true;
        while changed
            changed = false;
            for j = 1:gapCount
                if regionId(j) ~= 0, continue; end
                inRegion = find(regionId == nextRegion);
                d = hypot(gapX(inRegion) - gapX(j), gapY(inRegion) - gapY(j));
                if any(d <= GapClusterDistance)
                    regionId(j) = nextRegion;
                    changed = true;
                end
            end
        end
        nextRegion = nextRegion + 1;
    end
    numRegions = nextRegion - 1;
    
    candX     = zeros(numRegions, 1);
    candY     = zeros(numRegions, 1);
    candGaps  = zeros(numRegions, 1);
    candDist  = zeros(numRegions, 1);
    candScore = zeros(numRegions, 1);
    
    for r = 1:numRegions
        idx = (regionId == r);
        cx = mean(gapX(idx));
        cy = mean(gapY(idx));
        cx = min(max(cx, 10), areaSize(1) - 10);
        cy = min(max(cy, 10), areaSize(2) - 10);
        
        candX(r) = cx;
        candY(r) = cy;
        candGaps(r) = sum(idx);
        
        if numNodesTotal > 0
            dists = hypot(nodePositions(:,1) - cx, nodePositions(:,2) - cy);
            candDist(r) = min(dists);
        else
            candDist(r) = 100.0;
        end
        
        candScore(r) = candGaps(r) * 10.0 + candDist(r) * 0.1;
    end
    
    % Rank descending by score (Candidate 1 is best)
    [~, sortOrder] = sort(candScore, 'descend');
    candX     = candX(sortOrder);
    candY     = candY(sortOrder);
    candGaps  = candGaps(sortOrder);
    candDist  = candDist(sortOrder);
    candScore = candScore(sortOrder);
    
    candidates = [candX, candY, 10 * ones(numRegions, 1)];
    
    fprintf('\n---- Ranked Candidate Locations ----\n');
    fprintf('Detected %d gap cluster(s):\n', numRegions);
    for c = 1:numRegions
        if c == 1
            star = ' ★ [BEST CANDIDATE]';
        else
            star = '';
        end
        fprintf('  Rank %d: [%.1f m, %.1f m] | Gap Points: %d | Dist to Node: %.1f m | Score: %.1f%s\n', ...
            c, candX(c), candY(c), candGaps(c), candDist(c), candScore(c), star);
    end
else
    fprintf('\nNo coverage gaps detected! Full coverage achieved.\n');
end

%% ---- Visualizations (Coverage Map & Gap Analysis) ----
% 1. Coverage Map Figure
figCov = figure('Name', 'EmergencyNetwork - Real RF Coverage Map', ...
    'NumberTitle', 'off', 'Color', 'w', 'Position', [100, 100, 750, 600]);
axCov = axes('Parent', figCov);
hold(axCov, 'on'); grid(axCov, 'on'); box(axCov, 'on'); axis(axCov, 'equal');
xlim(axCov, [0 areaSize(1)]);
ylim(axCov, [0 areaSize(2)]);
xlabel(axCov, 'X (metres, East)');
ylabel(axCov, 'Y (metres, North)');
title(axCov, sprintf('Real RF Survey Coverage Map (RFRangeScale = %.2f)', RFRangeScale));

statusColors = {[0.85 0 0], [1 0.55 0], [0.90 0.75 0], [0 0.6 0]}; % GAP WEAK MODERATE GOOD
for k = 1:numSamples
    idx = surveyStatus(k) + 1;
    plot(axCov, surveyX(k), surveyY(k), 's', ...
        'MarkerFaceColor', statusColors{idx}, ...
        'MarkerEdgeColor', 'k', 'MarkerSize', 10);
end

% Plot deployed ground nodes with coverage circles
for nIdx = 1:numNodesTotal
    plot(axCov, nodePositions(nIdx, 1), nodePositions(nIdx, 2), 'o', ...
        'MarkerFaceColor', 'b', 'MarkerEdgeColor', 'k', 'MarkerSize', 10);
    text(axCov, nodePositions(nIdx, 1) + 12, nodePositions(nIdx, 2), ...
        nodeLabels{nIdx}, 'FontWeight', 'bold', 'Color', 'b');
    % Scaled coverage radius
    viscircles(axCov, [nodePositions(nIdx, 1), nodePositions(nIdx, 2)], 250 * RFRangeScale, ...
        'Color', [0 0.5 1], 'LineStyle', '--', 'LineWidth', 1.2);
end

% 2. Gap Analysis & Candidate Placement Figure
figGap = figure('Name', 'EmergencyNetwork - Gap Analysis & Candidate Placement', ...
    'NumberTitle', 'off', 'Color', 'w', 'Position', [870, 100, 750, 600]);
axGap = axes('Parent', figGap);
hold(axGap, 'on'); grid(axGap, 'on'); box(axGap, 'on'); axis(axGap, 'equal');
xlim(axGap, [0 areaSize(1)]);
ylim(axGap, [0 areaSize(2)]);
xlabel(axGap, 'X (metres, East)');
ylabel(axGap, 'Y (metres, North)');
title(axGap, sprintf('Gap Analysis & Ranked Candidates (%d gap points, %d candidates)', ...
    gapCount, size(candidates, 1)));

% Plot ground nodes
if numNodesTotal > 0
    plot(axGap, nodePositions(:, 1), nodePositions(:, 2), 'o', ...
        'MarkerFaceColor', 'b', 'MarkerEdgeColor', 'k', 'MarkerSize', 10, ...
        'DisplayName', 'Existing Node');
    for nIdx = 1:numNodesTotal
        text(axGap, nodePositions(nIdx, 1) + 12, nodePositions(nIdx, 2), ...
            nodeLabels{nIdx}, 'FontWeight', 'bold', 'Color', 'b');
    end
end

% Plot gap points
if gapCount > 0
    plot(axGap, gapX, gapY, 's', ...
        'MarkerFaceColor', 'r', 'MarkerEdgeColor', 'k', 'MarkerSize', 8, ...
        'DisplayName', 'Coverage Gap (<= -85 dBm)');
end

% Plot ranked candidates with best candidate highlighted
if ~isempty(candidates)
    numCand = size(candidates, 1);
    for c = 1:numCand
        if c == 1
            % Best candidate prominently highlighted
            plot(axGap, candidates(c, 1), candidates(c, 2), 'p', ...
                'MarkerFaceColor', [1 0.8 0], 'MarkerEdgeColor', [0 0.2 0.8], ...
                'MarkerSize', 24, 'LineWidth', 2.5, ...
                'DisplayName', 'Best Candidate (Rank 1)');
            text(axGap, candidates(c, 1) + 16, candidates(c, 2), ...
                sprintf('★ BEST CANDIDATE (Rank 1, Score %.1f)', candScore(c)), ...
                'FontSize', 10, 'FontWeight', 'bold', 'Color', [0.8 0.4 0]);
        else
            plot(axGap, candidates(c, 1), candidates(c, 2), 'p', ...
                'MarkerFaceColor', 'k', 'MarkerEdgeColor', 'y', ...
                'MarkerSize', 16, 'LineWidth', 1.5);
            text(axGap, candidates(c, 1) + 14, candidates(c, 2), ...
                sprintf('Candidate %d', c), ...
                'FontSize', 9, 'FontWeight', 'bold', 'Color', 'k');
        end
    end
end
legend(axGap, 'Location', 'bestoutside');

%% ---- Save Workspace Variables & Open EmergencyNetwork.slx ----
save('gcs_survey_data.mat', ...
    'areaSize', 'nodePositions', 'nodeLabels', 'dronePosition', ...
    'scanStartPosition', 'affectedAreaPolyM', ...
    'surveyTimestamp', 'surveyLat', 'surveyLon', 'surveyAlt', ...
    'surveyX', 'surveyY', 'surveyBestRSSI', 'surveyWaypoint', 'surveyRSSI', ...
    'surveyPoints', 'maxSurveyPoints', 'RFRangeScale', 'buildings', 'simStopTime', ...
    'gapCount', 'candidates');

fprintf('\nWorkspace variables loaded for EmergencyNetwork.slx:\n');
fprintf('  areaSize, nodePositions, nodeLabels, dronePosition, surveyPoints, RFRangeScale, simStopTime\n');

% Open the existing EmergencyNetwork.slx model directly
modelName = 'EmergencyNetwork';
if exist([modelName '.slx'], 'file')
    fprintf('Opening %s.slx...\n', modelName);
    open_system(modelName);
else
    fprintf('Note: %s.slx not found in directory.\n', modelName);
end

fprintf('\nPhase 4 setup complete. Ready to run EmergencyNetwork.slx!\n');
