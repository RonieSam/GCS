%% setupGCS.m
% Phase 3: GCS <-> Simulink Bridge Configuration
%
% Connects to the FastAPI backend at http://127.0.0.1:8000, pulls the
% accumulated RF survey dataset, transforms the coordinates into local ENU metres
% using the project's exact coordinate reference system, and sets up all
% workspace variables for EmergencyNetwork_GCS.slx.
%
% Architecture:
%   PX4 / Gazebo -> MAVLink -> FastAPI backend -> RF Data Collection -> setupGCS.m -> Simulink
%
% Usage:
%   1. Ensure FastAPI backend is running (e.g. uvicorn main:app).
%   2. Perform an RF Scan mission in GCS.
%   3. Run this script in MATLAB:
%          setupGCS
%   4. EmergencyNetwork_GCS.slx will open with live/accumulated survey data.

clear; clc;

%% ---- Configuration ----
BACKEND_HOST = '127.0.0.1';
BACKEND_PORT = 8000;
BACKEND_URL  = sprintf('http://%s:%d', BACKEND_HOST, BACKEND_PORT);
SURVEY_DATA_ENDPOINT = [BACKEND_URL '/api/rf-survey/data'];
SURVEY_STATE_ENDPOINT = [BACKEND_URL '/api/rf-survey/state'];

% Local tangent-plane conversion constant (matching backend/coordinate_mapper.py)
METRES_PER_DEG_LAT = 111320.0;

fprintf('====================================================\n');
fprintf('  Phase 3: Emergency Communication Network GCS Bridge\n');
fprintf('====================================================\n');
fprintf('Connecting to backend: %s\n', BACKEND_URL);

%% ---- Fetch Survey Data from FastAPI Backend ----
options = weboptions('Timeout', 10, 'ContentType', 'json');

surveyJson = [];
try
    surveyJson = webread(SURVEY_DATA_ENDPOINT, options);
    fprintf('Successfully connected to backend.\n');
    fprintf('Survey State: %s | Total Samples: %d\n', ...
        surveyJson.state, surveyJson.sample_count);
catch ME
    warning('Could not connect to FastAPI backend at %s: %s', ...
        SURVEY_DATA_ENDPOINT, ME.message);
    fprintf('\nFalling back to simulated/default values or cached data...\n');
    if exist('gcs_survey_data.mat', 'file')
        load('gcs_survey_data.mat');
        fprintf('Loaded cached data from gcs_survey_data.mat\n');
    else
        % Create placeholder survey structure so Simulink model can still load
        surveyJson = struct();
        surveyJson.state = 'IDLE';
        surveyJson.sample_count = 0;
        surveyJson.scan_start_position = [];
        surveyJson.affected_area = [];
        surveyJson.deployed_nodes = [];
        surveyJson.samples = [];
    end
end

%% ---- Process Affected Area & Dynamic Dimensions ----
% GCS sends affected area as a polygon of {lat, lon} points.
% We calculate the bounding box and local origin (min_lat, min_lon).
hasArea = isfield(surveyJson, 'affected_area') && ~isempty(surveyJson.affected_area);

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
    else
        polyLats = [];
        polyLons = [];
    end
else
    polyLats = [];
    polyLons = [];
end

if ~isempty(polyLats)
    originLat = min(polyLats);
    originLon = min(polyLons);
    maxLat    = max(polyLats);
    maxLon    = max(polyLons);
    cosLat    = cosd((originLat + maxLat) / 2);
    
    widthM  = max((maxLon - originLon) * METRES_PER_DEG_LAT * cosLat, 100);
    heightM = max((maxLat - originLat) * METRES_PER_DEG_LAT, 100);
    
    % Pad dimensions slightly for visualization borders (10% padding)
    areaSize = [ceil(widthM * 1.1), ceil(heightM * 1.1)];
    
    % Convert polygon vertices to local metres [x y]
    affectedAreaPolyM = [ ...
        (polyLons - originLon) * METRES_PER_DEG_LAT * cosLat, ...
        (polyLats - originLat) * METRES_PER_DEG_LAT ...
    ];
else
    % Default reference when no polygon is drawn
    originLat = 13.0827; % GCS default reference latitude
    originLon = 80.2707; % GCS default reference longitude
    cosLat    = cosd(originLat);
    areaSize  = [1000 1000];
    affectedAreaPolyM = [0 0; 1000 0; 1000 1000; 0 1000];
end

fprintf('Simulation Area Size: [%.1f m, %.1f m]\n', areaSize(1), areaSize(2));

%% ---- Process Ground Communication Nodes ----
% Extract deployed nodes from backend (positions in GCS coordinates)
hasNodes = isfield(surveyJson, 'deployed_nodes') && ~isempty(surveyJson.deployed_nodes);

if hasNodes
    rawNodes = surveyJson.deployed_nodes;
    if iscell(rawNodes)
        numNodes = numel(rawNodes);
        nodePositions = zeros(numNodes, 3);
        nodeLabels = cell(1, numNodes);
        for i = 1:numNodes
            n = rawNodes{i};
            nx = (n.lon - originLon) * METRES_PER_DEG_LAT * cosLat;
            ny = (n.lat - originLat) * METRES_PER_DEG_LAT;
            nz = 10.0;
            if isfield(n, 'alt') && ~isempty(n.alt), nz = n.alt; end
            nodePositions(i, :) = [nx, ny, nz];
            if isfield(n, 'id')
                nodeLabels{i} = n.id;
            else
                nodeLabels{i} = sprintf('COMM-%03d', i);
            end
        end
    elseif isstruct(rawNodes)
        numNodes = numel(rawNodes);
        nodePositions = zeros(numNodes, 3);
        nodeLabels = cell(1, numNodes);
        for i = 1:numNodes
            nx = (rawNodes(i).lon - originLon) * METRES_PER_DEG_LAT * cosLat;
            ny = (rawNodes(i).lat - originLat) * METRES_PER_DEG_LAT;
            nz = 10.0;
            if isfield(rawNodes(i), 'alt') && ~isempty(rawNodes(i).alt), nz = rawNodes(i).alt; end
            nodePositions(i, :) = [nx, ny, nz];
            if isfield(rawNodes(i), 'id')
                nodeLabels{i} = rawNodes(i).id;
            else
                nodeLabels{i} = sprintf('COMM-%03d', i);
            end
        end
    end
else
    % Fallback standard 3 ground nodes
    nodePositions = [ ...
        areaSize(1)*0.20, areaSize(2)*0.25, 10; ...
        areaSize(1)*0.80, areaSize(2)*0.30, 10; ...
        areaSize(1)*0.50, areaSize(2)*0.75, 10  ...
    ];
    nodeLabels = {'COMM-001', 'COMM-002', 'COMM-003'};
end

fprintf('Configured %d ground communication nodes:\n', size(nodePositions, 1));
for i = 1:size(nodePositions, 1)
    fprintf('  %s: [%.1f, %.1f, %.1f] m\n', ...
        nodeLabels{i}, nodePositions(i, 1), nodePositions(i, 2), nodePositions(i, 3));
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

%% ---- Process Accumulated RF Survey Samples ----
numSamples = 0;
if isfield(surveyJson, 'samples') && ~isempty(surveyJson.samples)
    rawSamples = surveyJson.samples;
    if iscell(rawSamples)
        numSamples = numel(rawSamples);
    elseif isstruct(rawSamples)
        numSamples = numel(rawSamples);
    end
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
    numNodesTotal   = size(nodePositions, 1);
    surveyRSSI      = -100 * ones(numSamples, numNodesTotal);
    
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
        surveyBestRSSI(k)  = s.best_rssi;
        if isfield(s, 'current_waypoint'), surveyWaypoint(k) = s.current_waypoint; end
        
        % Convert to local metres
        surveyX(k) = (s.longitude - originLon) * METRES_PER_DEG_LAT * cosLat;
        surveyY(k) = (s.latitude  - originLat) * METRES_PER_DEG_LAT;
        
        % Extract per-node RSSI
        if isfield(s, 'rssi') && ~isempty(s.rssi)
            rDict = s.rssi;
            for nIdx = 1:numNodesTotal
                nid = nodeLabels{nIdx};
                % Handle struct field or cell/map
                valName = regexprep(nid, '[^a-zA-Z0-9_]', '_');
                if isstruct(rDict) && isfield(rDict, valName)
                    surveyRSSI(k, nIdx) = rDict.(valName);
                elseif isstruct(rDict) && isfield(rDict, nid)
                    surveyRSSI(k, nIdx) = rDict.(nid);
                end
            end
        end
    end
    fprintf('Loaded %d survey samples from backend.\n', numSamples);
else
    fprintf('No survey samples in backend yet. Ready for scan execution.\n');
    surveyTimestamp = [];
    surveyLat       = [];
    surveyLon       = [];
    surveyAlt       = [];
    surveyX         = [];
    surveyY         = [];
    surveyBestRSSI  = [];
    surveyWaypoint  = [];
    surveyRSSI      = [];
end

%% ---- Environment & Visualizer Variables ----
% Match variables expected by EmergencyNetwork.slx blocks
buildings = zeros(0, 5); % Empty obstacle list for open RF survey
simStopTime = max(numSamples, 49);

%% ---- Save Survey Workspace to MAT file ----
save('gcs_survey_data.mat', ...
    'areaSize', 'nodePositions', 'nodeLabels', 'dronePosition', ...
    'scanStartPosition', 'affectedAreaPolyM', ...
    'surveyTimestamp', 'surveyLat', 'surveyLon', 'surveyAlt', ...
    'surveyX', 'surveyY', 'surveyBestRSSI', 'surveyWaypoint', 'surveyRSSI', ...
    'simStopTime');

fprintf('\nSurvey variables exported to base workspace and gcs_survey_data.mat.\n');
fprintf('  - areaSize:         [%.1f x %.1f m]\n', areaSize(1), areaSize(2));
fprintf('  - nodePositions:    %d nodes\n', size(nodePositions, 1));
fprintf('  - dronePosition:    [%.1f, %.1f, %.1f] m\n', dronePosition(1), dronePosition(2), dronePosition(3));
fprintf('  - surveySamples:    %d points\n', numSamples);
fprintf('  - simStopTime:      %d s\n', simStopTime);

%% ---- Open Integration Model ----
modelName = 'EmergencyNetwork_GCS';
if exist([modelName '.slx'], 'file')
    fprintf('\nOpening %s.slx...\n', modelName);
    open_system(modelName);
else
    fprintf('\nNote: %s.slx not found in current folder.\n', modelName);
end
fprintf('Setup complete.\n');
