%% setupPhase1.m
% Phase 1 configuration for EmergencyNetwork.slx
%
% This script defines every tunable parameter of the Phase 1 scene in the
% BASE WORKSPACE. The Simulink model reads these variables by name (Constant
% blocks and MATLAB System block parameters), so you configure everything
% here and never touch the diagram to change a position or add a building.
%
% Run this script, then open/run EmergencyNetwork.slx.

clear; clc;

%% ---- Simulation area ----
areaSize = [1000 1000];   % [width_m, height_m]

%% ---- Ground nodes: one row per node, columns = [x y z] in metres ----
nodePositions = [150 200 10;   % Node 1
                 800 250 10;   % Node 2
                 450 750 10];  % Node 3

nodeLabels = {'Node 1', 'Node 2', 'Node 3'};

%% ---- Drone initial position: [x y z] in metres ----
dronePosition = [50 50 30];

%% ---- Buildings / obstacles ----
% One row per building: [x y width depth height]
% (x,y) = bottom-left corner of the building's footprint, in metres.
buildings = [300 300 150 100 40;
             600 500 120 180 30;
             200 600 100 100 25];

%% ---- Simulation timing ----
% Phase 1 has no dynamics, so the scene only needs to be drawn once.
simStopTime = 49;   % seconds

%% ---- Open the model (safe to call even if already open) ----
modelName = 'EmergencyNetwork';
if exist([modelName '.slx'], 'file')
    open_system(modelName);
end

fprintf('Phase 1 workspace variables loaded:\n');
fprintf('  areaSize, nodePositions, nodeLabels, dronePosition, buildings, simStopTime\n');
fprintf('Run the model to view the static environment.\n');
