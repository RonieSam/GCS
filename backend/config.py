"""
Central configuration for the UAV emergency deployment system.

Phase 1 does not use this module yet (Phase 1 is frontend-only: map +
polygon drawing + static node display). It exists now so later phases
have a single place to change values instead of scattering magic
numbers through the code, per the project spec.
"""

# ---------------------------------------------------------------------------
# Phase 9A — Simulation coordinate transformation
# ---------------------------------------------------------------------------

# Set to True when running against PX4 SITL / Gazebo so the backend
# transparently remaps coordinates between the GCS planning space and the
# PX4/Gazebo geographic space.  Set to False for real-hardware deployments
# where GCS and vehicle share the same WGS84 reference frame.
SIMULATION_MODE = True

# GCS map reference origin — the point on the GCS map that corresponds to the
# PX4/Gazebo home position.  All user-selected targets are expressed as a
# displacement from this point before being re-anchored around PX4_REFERENCE.
# Using the Chennai node cluster centre as the GCS planning origin.
GCS_REFERENCE_LAT = 13.0827   # °N  (Chennai)
GCS_REFERENCE_LON = 80.2707   # °E

# PX4/Gazebo home position — the physical location that maps to
# (GCS_REFERENCE_LAT, GCS_REFERENCE_LON) in the simulation.
# These are static fallback values; the MAVLinkManager overrides them at
# runtime with the first HOME_POSITION message received from PX4 so we
# remain correct regardless of PX4_HOME_LAT/LON environment variables.
PX4_REFERENCE_LAT = 47.397742   # °N  (PX4 SITL default — overridden at runtime)
PX4_REFERENCE_LON = 8.545594    # °E

# --- MAVLink / SITL (used from Phase 6 onward) ---
MAVLINK_CONNECTION = "udp:127.0.0.1:14550"
ARRIVAL_THRESHOLD_METERS = 5

# How long to block waiting for the first HEARTBEAT before treating a
# connection attempt as failed and retrying.
MAVLINK_CONNECT_TIMEOUT_S = 10
# Once connected, how long without a HEARTBEAT before we consider the link
# lost (ArduPilot/SITL sends one at ~1Hz, so this gives several missed beats
# of margin before flipping the GCS to HEARTBEAT_LOST).
MAVLINK_HEARTBEAT_LOST_S = 5
# Delay between reconnect attempts after a failed/lost connection.
MAVLINK_RECONNECT_INTERVAL_S = 3
# Rate (Hz) requested for ArduPilot's streamed telemetry (position, VFR_HUD,
# etc.) — ArduPilot does not stream these over MAVLink until asked.
MAVLINK_STREAM_RATE_HZ = 4

# --- Mission defaults (used from Phase 5/8 onward) ---
DEFAULT_ALTITUDE = 15  # meters

# --- Phase 8: MAVLink mission upload timeouts ---
# Total time to wait for the complete upload handshake (CLEAR → COUNT → items → ACK).
MISSION_UPLOAD_TIMEOUT_S = 15
# Per-item timeout: how long to wait for PX4 to request the next item.
MISSION_ITEM_TIMEOUT_S = 5

# --- Coverage model (used from Phase 2 onward) ---
COVERAGE_RADIUS_DEFAULT_M = 250  # fallback if a node omits coverage_radius_m
GRID_RESOLUTION_M = 20  # spacing between coverage-grid sample points

# --- Scoring weights (used from Phase 4 onward) ---
COVERAGE_WEIGHT = 0.60
DISTANCE_WEIGHT = 0.25
SUITABILITY_WEIGHT = 0.15

# --- Candidate generation (used from Phase 3 onward) ---
MIN_CLUSTER_SIZE = 2  # gap clusters smaller than this are treated as noise
MIN_CANDIDATES = 5    # prototype should surface at least this many candidates

# --- Target validation (used from Phase 5 onward) ---
MIN_NODE_SEPARATION_M = 30  # reject a target this close to an existing node

# --- UAV home / launch point (used from Phase 6 onward) ---
# NOTE: In simulation mode this is the GCS map home, not the PX4 home.
# Coordinate remapping is handled by coordinate_mapper.py.
UAV_HOME_LAT = GCS_REFERENCE_LAT
UAV_HOME_LON = GCS_REFERENCE_LON

# --- Data files ---
NODES_FILE = "data/nodes.json"
SCENARIOS_FILE = "data/scenarios.json"
