"""
Phase 8 — FastAPI backend with real MAVLink mission upload + execution.

Phases 1–7 are fully intact. This phase implements:

  POST /api/mission/send   — real MAVLink mission upload (was 501)
  POST /api/mission/start  — new; commands PX4 into mission mode
  POST /api/mission/abort  — real RTL abort (was 501)

The single-reader MAVLink architecture is preserved: all recv_match()
 calls happen inside the MAVLinkManager's background thread via the
 existing command-queue mechanism. FastAPI request handlers block on a
 threading.Event and never touch the pymavlink connection directly.
"""


import os
import math
import logging
import mavlink_commands   # NEW import, alongside the mavlink_manager import
import mavlink_mission    # Phase 8 — MAVLink mission protocol
import coordinate_mapper  # Phase 9A — simulation coordinate transformation
import survey_planner    # Phase 2 — RF scan survey path planner
from rf_collector import get_rf_collector, SCAN_STATE_ABORTED  # Phase 3 — RF Survey collector
import rf_survey_analyzer  # Phase 5 — RF-data-driven candidate generation

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional, Tuple

import copy
import time
from datetime import datetime, timezone
from pydantic import BaseModel

import config
from candidate_generator import generate_candidates
from coverage import compute_coverage, haversine_distance_m, point_in_polygon
from database import (
    clear_nodes,
    delete_node,
    get_mission,
    init_db,
    insert_mission,
    insert_node,
    list_deployments,
    list_missions,
    list_nodes,
    update_mission_status,
)

from mavlink_manager import MAVLinkManager
from models import (
    AnalyzeResponse,
    AreaRequest,
    AreaResponse,
    CandidateOut,
    CandidatesResponse,
    CoordinateReferencePoint,
    CoordinateReferenceResponse,
    CoordinateTranslateRequest,
    CoordinateTranslateResponse,
    DeploymentOut,
    LatLon,
    ManualControlResponse,
    ManualVelocityRequest,
    ManualVelocityResponse,
    MissionAbortResponse,
    MissionGenerateRequest,
    MissionOut,
    MissionStartResponse,
    MissionUploadResponse,
    NodeOut,
    NotImplementedResponse,
    RFScanGenerateRequest,
    RFScanGenerateResponse,
    RFScanWaypoint,
    ReturnHomeResponse,
    SelectTargetRequest,
    SelectTargetResponse,
    StatusResponse,
    VehicleStateOut,
)
from scoring import score_candidates, top_n
from telemetry_broadcaster import TelemetryBroadcaster

app = FastAPI(title="UAV Emergency Deployment GCS Backend", version="phase-8")

# Phase 6 — one manager for the app's single vehicle connection, matching
# the "single-operator, single-mission" scope the rest of main.py already
# assumes (see session_state below). Constructed here (not lazily) so its
# background thread has a fixed lifetime tied to app startup/shutdown.
mav_manager = MAVLinkManager(
    config.MAVLINK_CONNECTION,
    connect_timeout_s=config.MAVLINK_CONNECT_TIMEOUT_S,
    heartbeat_lost_s=config.MAVLINK_HEARTBEAT_LOST_S,
    reconnect_interval_s=config.MAVLINK_RECONNECT_INTERVAL_S,
    stream_rate_hz=config.MAVLINK_STREAM_RATE_HZ,
)

# Phase 7 — fans mav_manager's vehicle state out to /ws/telemetry clients.
# Reads the same get_vehicle_state() snapshot /api/vehicle/state uses;
# does not open a second MAVLink connection or touch pymavlink directly.
telemetry_broadcaster = TelemetryBroadcaster(
    mav_manager,
    rate_hz=config.MAVLINK_STREAM_RATE_HZ,
)

BASE_DIR = os.path.dirname(__file__)
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
DATA_DIR = os.path.join(BASE_DIR, "..", "data")

# In-process session state — one operator, one mission at a time (Stage 1
# scope). Reset whenever a new area is submitted, since a new area makes
# any prior analysis/candidates/target stale.
session_state = {
    "polygon": None,          # list of {"lat", "lon"} or None
    "last_coverage": None,    # compute_coverage() result dict or None
    "last_candidates": None,  # raw generate_candidates() output or None
    "last_scored": None,      # score_candidates() output or None
    "selected_target": None,  # {"lat", "lon"} or None
    "mission_state": "PLANNING",
    # Phase 8 — tracks the most recently generated mission row
    "last_mission_id": None,  # SQLite id of last generated mission, or None
    "last_mission": None,     # full MissionOut dict of last generated mission
    # Phase 2 — RF scan survey state
    "rf_scan_state": "IDLE",  # IDLE | MISSION_GENERATED | MISSION_UPLOADED | RUNNING | COMPLETED | FAILED
    "rf_scan_mission": None,  # survey_planner output dict or None
    # Phase 5 — RF survey analysis results (from POST /api/rf-survey/analyze)
    "rf_analysis": None,      # full analyze_rf_survey() result dict, or None (stale/not-yet-analyzed)
    # Phase 6 — Re-Scan & Before/After Verification state
    "rf_phase6_state": "BEFORE_SURVEY",  # BEFORE_SURVEY | BEFORE_ANALYZED | CANDIDATE_SELECTED | DEPLOYMENT_MISSION | NODE_DEPLOYED | AFTER_SURVEY | AFTER_ANALYZED | VERIFIED
    "rf_before_analysis": None,          # packaged snapshot of BEFORE survey
    "rf_after_analysis": None,           # packaged snapshot of AFTER survey
    "rf_comparison": None,               # computed comparison object
    "rf_newly_deployed_node_id": None,   # ID of newly deployed node
    # Phase 6 & History: Survey history & Deployment release
    "rf_survey_history": [],             # Last 5 completed RF surveys stored independently
    "rf_survey_history_counter": 0,      # Monotonic counter for survey IDs
    "deployment_released": False,        # Track if node has been released for active candidate
}

_CANDIDATE_MATCH_TOLERANCE_M = 1.0  # treat as "the same point" within this radius


@app.on_event("startup")
async def on_startup():
    init_db()
    # Phase 4 Final — fresh GCS session starts with 0 deployed nodes and clean RF collector
    clear_nodes()
    rf_collector = get_rf_collector()
    rf_collector.reset()
    rf_collector.update_deployed_nodes([])
    session_state["rf_scan_state"] = "IDLE"
    session_state["rf_scan_mission"] = None
    session_state["mission_state"] = "IDLE"
    session_state["rf_phase6_state"] = "BEFORE_SURVEY"
    session_state["rf_before_analysis"] = None
    session_state["rf_after_analysis"] = None
    session_state["rf_comparison"] = None
    session_state["rf_newly_deployed_node_id"] = None
    session_state["rf_survey_history"] = []
    session_state["rf_survey_history_counter"] = 0
    session_state["deployment_released"] = False
    # Non-blocking: SITL may not be up yet (or ever, in a pure-API test
    # run), and the rest of the API — area/coverage/candidates/missions —
    # doesn't depend on a vehicle link, so startup must not wait on it.
    mav_manager.start_background()
    # Runs as an asyncio task on the server's event loop — separate from
    # mav_manager's own background thread, so a slow/stalled WebSocket
    # client can never block MAVLink message processing.
    await telemetry_broadcaster.start()


@app.on_event("shutdown")
async def on_shutdown():
    await telemetry_broadcaster.stop()
    mav_manager.stop_background()


# ---------------------------------------------------------------------------
# Status / nodes
# ---------------------------------------------------------------------------


@app.get("/api/status", response_model=StatusResponse)
def api_status():
    return StatusResponse(
        status="ok",
        phase=8,
        mission_state=session_state["mission_state"],
        uav_connected=mav_manager.is_connected(),
        link_state=mav_manager.link_state,
        area_defined=session_state["polygon"] is not None,
        last_analysis_available=session_state["last_coverage"] is not None,
    )


@app.get("/api/vehicle/state", response_model=VehicleStateOut)
def api_vehicle_state():
    return VehicleStateOut(**mav_manager.get_vehicle_state())

@app.post("/api/vehicle/arm")
def api_vehicle_arm():
    logger.info("ARM requested")
    try:
        logger.info("ARM command sent")
        mav_manager.send_command("arm")
        logger.info("ARM result: ACCEPTED")
        return {"success": True, "command": "arm"}
    except mavlink_commands.CommandRejected as e:
        logger.warning(f"ARM result: REJECTED - {e}")
        return {"success": False, "command": "arm", "error": str(e)}
    except mavlink_commands.CommandTimeout as e:
        logger.warning(f"ARM result: TIMEOUT - {e}")
        return {"success": False, "command": "arm", "error": str(e)}
    except RuntimeError as e:
        logger.error(f"ARM result: ERROR - {e}")
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error(f"ARM result: ERROR - {e}")
        raise HTTPException(500, str(e))


@app.post("/api/vehicle/disarm")
def api_vehicle_disarm():
    logger.info("DISARM requested")
    try:
        logger.info("DISARM command sent")
        mav_manager.send_command("disarm")
        logger.info("DISARM result: ACCEPTED")
        return {"success": True, "command": "disarm"}
    except mavlink_commands.CommandRejected as e:
        logger.warning(f"DISARM result: REJECTED - {e}")
        return {"success": False, "command": "disarm", "error": str(e)}
    except mavlink_commands.CommandTimeout as e:
        logger.warning(f"DISARM result: TIMEOUT - {e}")
        return {"success": False, "command": "disarm", "error": str(e)}
    except RuntimeError as e:
        logger.error(f"DISARM result: ERROR - {e}")
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error(f"DISARM result: ERROR - {e}")
        raise HTTPException(500, str(e))


@app.post("/api/vehicle/mode/{mode_name}")
def api_vehicle_mode(mode_name: str):
    try:
        mav_manager.send_command("set_mode", mode=mode_name.upper())
        return {
            "success": True,
            "command": "set_mode",
            "mode": mode_name.upper(),
        }
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/vehicle/return-home", response_model=ReturnHomeResponse)
def api_vehicle_return_home():
    """Command the UAV to physically return to its original home coordinates.

    Used post-mission after the UAV has landed at the target.
    Uploads a dedicated return mission (TAKEOFF at current UAV pos -> WAYPOINT at home -> LAND at home),
    arms the vehicle, and commands PX4 into MISSION mode so the UAV physically flies home.
    """
    logger.info("RETURN HOME requested")

    # 1. Validate MAVLink link
    if not mav_manager.is_connected():
        logger.warning("RETURN HOME failed: PX4 is not connected.")
        raise HTTPException(503, "PX4 is not connected. Cannot command return to home.")

    # 2. Validate PX4 home/reference is available
    mapper = coordinate_mapper.get_mapper()
    refs = mapper.get_references()
    px4_ref = refs.get("px4_reference", {})
    home_lat = px4_ref.get("latitude")
    home_lon = px4_ref.get("longitude")

    if home_lat is None or home_lon is None:
        logger.warning("RETURN HOME failed: PX4 home/reference is not available.")
        raise HTTPException(400, "PX4 home/reference coordinate is not available.")

    # 3. Validate current UAV position
    uav_state = mav_manager.get_vehicle_state()
    uav_lat = uav_state.get("latitude")
    uav_lon = uav_state.get("longitude")

    if uav_lat is None or uav_lon is None:
        logger.warning("RETURN HOME failed: Current UAV position is unknown.")
        raise HTTPException(400, "Current UAV position is unknown.")

    logger.info(f"Current UAV position: lat={uav_lat:.7f}, lon={uav_lon:.7f}")
    logger.info(f"PX4 home/reference: lat={home_lat:.7f}, lon={home_lon:.7f}")

    # Check if already at home coordinates (within 3m) and not flying
    R = 6371000.0
    phi1, phi2 = math.radians(uav_lat), math.radians(home_lat)
    dphi = math.radians(home_lat - uav_lat)
    dlam = math.radians(home_lon - uav_lon)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    dist_to_home = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    if dist_to_home < 3.0 and not uav_state.get("armed"):
        logger.info(f"RETURN HOME: UAV is already at home coordinates ({dist_to_home:.1f}m away).")
        return ReturnHomeResponse(
            success=False,
            action="RETURN_HOME",
            home_target=CoordinateReferencePoint(latitude=home_lat, longitude=home_lon),
            error="UAV is already at home coordinates.",
        )

    # 4. Construct return mission from current position to home reference
    last_mission = session_state.get("last_mission")
    alt = last_mission.get("target_alt") if last_mission else config.DEFAULT_ALTITUDE
    if not alt or alt <= 0:
        alt = config.DEFAULT_ALTITUDE

    try:
        items = mavlink_mission.build_mission_items(
            target_lat=home_lat,
            target_lon=home_lon,
            target_alt_m=alt,
            home_lat=uav_lat,
            home_lon=uav_lon,
        )
    except mavlink_mission.InvalidMission as e:
        logger.error(f"RETURN HOME failed: Invalid return mission: {e}")
        raise HTTPException(400, f"Invalid return mission: {e}")

    logger.info("RETURN HOME command sent")

    try:
        upload_result = mav_manager.send_command(
            "upload_mission",
            items=items,
            timeout_s=config.MISSION_UPLOAD_TIMEOUT_S,
        )
        n_items = upload_result.get("items", len(items))

        # If vehicle is disarmed at target, arm it for the return flight
        if not uav_state.get("armed"):
            logger.info("Vehicle disarmed at target — commanding ARM for return flight")
            mav_manager.send_command("arm")

        # Command PX4 into MISSION mode to execute the return mission
        mav_manager.send_command("set_mode", mode="MISSION")

        session_state["mission_state"] = "RETURNING"
        logger.info("RETURN HOME result: ACCEPTED")

        return ReturnHomeResponse(
            success=True,
            action="RETURN_HOME",
            home_target=CoordinateReferencePoint(latitude=home_lat, longitude=home_lon),
            items=n_items,
        )

    except (mavlink_commands.CommandRejected, mavlink_mission.MissionRejected) as e:
        logger.warning(f"RETURN HOME result: REJECTED - {e}")
        return ReturnHomeResponse(
            success=False,
            action="RETURN_HOME",
            home_target=CoordinateReferencePoint(latitude=home_lat, longitude=home_lon),
            error=str(e),
        )
    except (mavlink_commands.CommandTimeout, mavlink_mission.MissionTimeout) as e:
        logger.warning(f"RETURN HOME result: TIMEOUT - {e}")
        return ReturnHomeResponse(
            success=False,
            action="RETURN_HOME",
            home_target=CoordinateReferencePoint(latitude=home_lat, longitude=home_lon),
            error=str(e),
        )
    except (RuntimeError, ValueError) as e:
        logger.error(f"RETURN HOME result: ERROR - {e}")
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error(f"RETURN HOME result: UNEXPECTED ERROR - {e}")
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Manual Control — POSCTL override + velocity setpoint + MISSION resume
# ---------------------------------------------------------------------------


@app.post("/api/vehicle/manual-control", response_model=ManualControlResponse)
def api_vehicle_manual_control():
    """Enter manual (POSCTL) override mode.

    Switches PX4 into Position Control (POSCTL) so the operator can fly
    the vehicle with a gamepad.  The current mission is NOT cleared — PX4
    preserves the mission sequence index across mode changes, so Resume
    Auto (POST /api/vehicle/resume-mission) will continue from the same
    waypoint.

    Prerequisites: PX4 must be connected and the vehicle must be armed.
    """
    logger.info("MANUAL CONTROL (POSCTL) requested")

    if not mav_manager.is_connected():
        raise HTTPException(503, "PX4 is not connected.")

    try:
        mav_manager.send_command("set_mode", mode="POSCTL")
        session_state["mission_state"] = "MANUAL"
        logger.info("MANUAL CONTROL result: POSCTL mode set")
        return ManualControlResponse(success=True, mode="POSCTL")

    except mavlink_commands.CommandRejected as e:
        logger.warning(f"MANUAL CONTROL result: REJECTED - {e}")
        return ManualControlResponse(success=False, mode="POSCTL", error=str(e))
    except mavlink_commands.CommandTimeout as e:
        logger.warning(f"MANUAL CONTROL result: TIMEOUT - {e}")
        return ManualControlResponse(success=False, mode="POSCTL", error=str(e))
    except (RuntimeError, ValueError) as e:
        raise HTTPException(503, str(e))


@app.post("/api/vehicle/manual-velocity", response_model=ManualVelocityResponse)
def api_vehicle_manual_velocity(req: ManualVelocityRequest):
    """Send a single NED velocity setpoint to PX4.

    Intended to be called at ~20 Hz by the frontend gamepad loop while the
    vehicle is in POSCTL mode.  The message is fire-and-forget
    (SET_POSITION_TARGET_LOCAL_NED) — PX4 does not ACK it, so this
    endpoint returns immediately.

    Clamp limits are enforced server-side to protect against runaway
    browser bugs: ±10 m/s on translational axes, ±1.5 rad/s on yaw_rate.
    """
    if not mav_manager.is_connected():
        # Silently succeed if the link dropped — the gamepad loop keeps
        # firing; we don't want to flood the browser with 503 errors.
        return ManualVelocityResponse(success=False, error="PX4 not connected")

    MAX_V   = 10.0   # m/s — hard clamp on each translational axis
    MAX_YAW = 1.5    # rad/s

    vx       = max(-MAX_V,   min(MAX_V,   req.vx))
    vy       = max(-MAX_V,   min(MAX_V,   req.vy))
    vz       = max(-MAX_V,   min(MAX_V,   req.vz))
    yaw_rate = max(-MAX_YAW, min(MAX_YAW, req.yaw_rate))

    try:
        mav_manager.send_command(
            "send_velocity",
            vx=vx, vy=vy, vz=vz, yaw_rate=yaw_rate,
        )
        return ManualVelocityResponse(success=True)
    except Exception as e:
        logger.warning(f"manual-velocity error: {e}")
        return ManualVelocityResponse(success=False, error=str(e))


@app.post("/api/vehicle/resume-mission", response_model=ManualControlResponse)
def api_vehicle_resume_mission():
    """Resume the loaded mission after manual override.

    Switches PX4 back into MISSION mode.  Because PX4 preserves the
    mission sequence index across mode changes, it will continue from
    the waypoint it was on when manual override was activated — no
    mission re-upload required.

    Prerequisites: PX4 must be connected.  A mission must have been
    uploaded previously.
    """
    logger.info("RESUME MISSION (MISSION mode) requested")

    if not mav_manager.is_connected():
        raise HTTPException(503, "PX4 is not connected.")

    try:
        mav_manager.send_command("set_mode", mode="MISSION")
        session_state["mission_state"] = "EXECUTING"
        logger.info("RESUME MISSION result: MISSION mode set")
        return ManualControlResponse(success=True, mode="MISSION")

    except mavlink_commands.CommandRejected as e:
        logger.warning(f"RESUME MISSION result: REJECTED - {e}")
        return ManualControlResponse(success=False, mode="MISSION", error=str(e))
    except mavlink_commands.CommandTimeout as e:
        logger.warning(f"RESUME MISSION result: TIMEOUT - {e}")
        return ManualControlResponse(success=False, mode="MISSION", error=str(e))
    except (RuntimeError, ValueError) as e:
        raise HTTPException(503, str(e))


@app.get("/api/nodes", response_model=List[NodeOut])
def api_nodes():
    return list_nodes()


@app.post("/api/nodes", response_model=NodeOut)
def api_add_node(node: NodeOut):
    """Deploy/register a communication node dynamically."""
    created = insert_node(
        node_id=node.id,
        lat=node.lat,
        lon=node.lon,
        coverage_radius_m=node.coverage_radius_m or config.COVERAGE_RADIUS_DEFAULT_M,
    )
    if not created:
        raise HTTPException(500, "Failed to insert node into database.")
    rf_collector = get_rf_collector()
    rf_collector.update_deployed_nodes(list_nodes())
    # Phase 6: Track newly deployed node and advance state
    session_state["rf_newly_deployed_node_id"] = created["id"]
    if session_state.get("rf_before_analysis"):
        session_state["rf_phase6_state"] = "NODE_DEPLOYED"
    logger.info(f"Node deployed: {created['id']} at ({created['lat']}, {created['lon']}) [Phase 6: {session_state.get('rf_phase6_state')}]")
    return NodeOut(**created)


@app.delete("/api/nodes/{node_id}")
def api_delete_node(node_id: str):
    """Delete a deployed communication node by ID."""
    deleted = delete_node(node_id)
    if not deleted:
        raise HTTPException(404, f"Node '{node_id}' not found.")
    rf_collector = get_rf_collector()
    rf_collector.update_deployed_nodes(list_nodes())
    if node_id == session_state.get("rf_newly_deployed_node_id"):
        session_state["rf_newly_deployed_node_id"] = None
    logger.info(f"Node deleted: {node_id}. Remaining nodes: {len(list_nodes())}")
    return {"success": True, "deleted": node_id, "remaining_count": len(list_nodes())}


@app.post("/api/nodes/clear")
def api_clear_nodes():
    """Remove all deployed communication nodes."""
    clear_nodes()
    rf_collector = get_rf_collector()
    rf_collector.update_deployed_nodes([])
    session_state["rf_newly_deployed_node_id"] = None
    logger.info("All deployed nodes cleared.")
    return {"success": True, "count": 0}


@app.post("/api/session/init")
def api_session_init():
    """Initialize a fresh clean GCS session: clear active nodes and reset RF collector."""
    clear_nodes()
    rf_collector = get_rf_collector()
    rf_collector.reset()
    rf_collector.update_deployed_nodes([])
    session_state["rf_scan_state"] = "IDLE"
    session_state["rf_scan_mission"] = None
    session_state["mission_state"] = "IDLE"
    session_state["rf_phase6_state"] = "BEFORE_SURVEY"
    session_state["rf_before_analysis"] = None
    session_state["rf_after_analysis"] = None
    session_state["rf_comparison"] = None
    session_state["rf_newly_deployed_node_id"] = None
    logger.info("Fresh GCS session initialized: 0 deployed nodes, RF collector IDLE.")
    return {"success": True, "active_nodes": 0, "rf_state": "IDLE"}


# ---------------------------------------------------------------------------
# Area + coverage analysis
# ---------------------------------------------------------------------------


@app.post("/api/area", response_model=AreaResponse)
def api_area(req: AreaRequest):
    polygon = [{"lat": p.lat, "lon": p.lon} for p in req.polygon]

    session_state["polygon"] = polygon
    # A new area invalidates any analysis/candidates/target that referred
    # to the old one.
    session_state["last_coverage"] = None
    session_state["last_candidates"] = None
    session_state["last_scored"] = None
    session_state["selected_target"] = None
    session_state["mission_state"] = "PLANNING"
    session_state["rf_scan_state"] = "IDLE"
    session_state["rf_scan_mission"] = None
    session_state["rf_analysis"] = None  # Phase 5 — invalidate RF analysis on area change

    # Phase 6 Requirement 9: Invalidate comparison if area changes between surveys
    if session_state.get("rf_before_analysis"):
        if not rf_survey_analyzer.are_polygons_equivalent(
            session_state["rf_before_analysis"].get("affected_area"),
            polygon
        ):
            session_state["rf_comparison"] = {
                "comparable": False,
                "invalidation_reason": "Affected area changed between BEFORE and AFTER surveys. Comparison is invalid.",
                "before": session_state["rf_before_analysis"],
                "after": session_state.get("rf_after_analysis"),
                "changes": {},
                "remaining_gaps": None,
                "remaining_gap_clusters": None,
            }

    return AreaResponse(accepted=True, point_count=len(polygon), polygon=req.polygon)


@app.post("/api/analyze", response_model=AnalyzeResponse)
def api_analyze():
    polygon = session_state["polygon"]
    if not polygon:
        raise HTTPException(400, "No affected area defined yet — POST /api/area first.")

    nodes = list_nodes()
    result = compute_coverage(polygon, nodes)
    if result["total_points"] == 0:
        raise HTTPException(
            400, "Affected area is too small or degenerate — no grid points could be sampled."
        )

    session_state["last_coverage"] = result
    # Candidates/scoring are derived from coverage — stale until recomputed.
    session_state["last_candidates"] = None
    session_state["last_scored"] = None

    return AnalyzeResponse(
        total_points=result["total_points"],
        covered_points=[LatLon(lat=p[0], lon=p[1]) for p in result["covered_points"]],
        gap_points=[LatLon(lat=p[0], lon=p[1]) for p in result["gap_points"]],
        coverage_percentage=result["coverage_percentage"],
        gap_percentage=result["gap_percentage"],
    )


# ---------------------------------------------------------------------------
# Phase 2 — RF Scan survey mission endpoints
# ---------------------------------------------------------------------------


@app.post("/api/rf-scan/generate", response_model=RFScanGenerateResponse)
def api_rf_scan_generate(req: Optional[RFScanGenerateRequest] = None):
    """
    Generate an RF scan survey mission (zig-zag / lawnmower pattern)
    covering the user-defined affected area polygon.
    """
    polygon = None
    if req and req.polygon:
        polygon = [{"lat": p.lat, "lon": p.lon} for p in req.polygon]
        session_state["polygon"] = polygon
    else:
        polygon = session_state.get("polygon")

    if not polygon or len(polygon) < 3:
        session_state["rf_scan_state"] = "IDLE"
        session_state["rf_scan_mission"] = None
        raise HTTPException(400, "Define an affected area first.")

    spacing_m = req.spacing_m if (req and req.spacing_m) else 25.0
    altitude_m = req.altitude_m if (req and req.altitude_m) else config.DEFAULT_ALTITUDE

    # Capture UAV current position (GCS frame) for nearest-endpoint selection.
    # This ensures the green dot (start) is the survey endpoint closest to the UAV.
    uav_state = mav_manager.get_vehicle_state()
    raw_uav_lat = uav_state.get("latitude")
    raw_uav_lon = uav_state.get("longitude")

    # Convert UAV pos to GCS frame if connected (handles both PX4 and GCS raw frames)
    uav_gcs_lat = None
    uav_gcs_lon = None
    if raw_uav_lat is not None and raw_uav_lon is not None:
        mapper = coordinate_mapper.get_mapper()
        if config.SIMULATION_MODE:
            refs = mapper.get_references()
            px4_ref = refs.get("px4_reference", {})
            gcs_ref = refs.get("gcs_reference", {})
            p_lat = px4_ref.get("latitude", config.PX4_REFERENCE_LAT)
            p_lon = px4_ref.get("longitude", config.PX4_REFERENCE_LON)
            g_lat = gcs_ref.get("latitude", config.GCS_REFERENCE_LAT)
            g_lon = gcs_ref.get("longitude", config.GCS_REFERENCE_LON)
            raw_lat_f = float(raw_uav_lat)
            raw_lon_f = float(raw_uav_lon)
            if math.hypot(raw_lat_f - g_lat, raw_lon_f - g_lon) < math.hypot(raw_lat_f - p_lat, raw_lon_f - p_lon):
                uav_gcs_lat, uav_gcs_lon = raw_lat_f, raw_lon_f
            else:
                uav_gcs_lat, uav_gcs_lon = mapper.px4_to_gcs(raw_lat_f, raw_lon_f)
        else:
            uav_gcs_lat, uav_gcs_lon = float(raw_uav_lat), float(raw_uav_lon)
        logger.info(
            f"RF scan generate: UAV GCS pos lat={uav_gcs_lat:.7f}, lon={uav_gcs_lon:.7f} "
            f"— will select nearest survey endpoint as start."
        )
    else:
        logger.info(
            "RF scan generate: UAV position unknown — using default path order (endpoint A)."
        )

    try:
        result = survey_planner.generate_survey_path(
            polygon,
            spacing_m=spacing_m,
            altitude_m=altitude_m,
            uav_lat=uav_gcs_lat,
            uav_lon=uav_gcs_lon,
        )
    except ValueError as e:
        session_state["rf_scan_state"] = "FAILED"
        raise HTTPException(400, str(e))

    session_state["rf_scan_state"] = "MISSION_GENERATED"
    session_state["rf_scan_mission"] = result
    session_state["rf_analysis"] = None  # Phase 5 — new survey invalidates previous analysis
    if session_state.get("rf_before_analysis"):
        session_state["rf_phase6_state"] = "AFTER_SURVEY"
        session_state["rf_after_analysis"] = None
        session_state["rf_comparison"] = None
    else:
        session_state["rf_phase6_state"] = "BEFORE_SURVEY"


    start_ep = result.get("start_endpoint")
    logger.info(
        f"RF scan generated: {result['waypoint_count']} waypoints, "
        f"start_endpoint=lat={start_ep['lat']:.7f}, lon={start_ep['lon']:.7f} "
        f"(green dot = first survey waypoint)."
    )

    return RFScanGenerateResponse(
        success=True,
        state="MISSION_GENERATED",
        total_distance_m=result["total_distance_m"],
        waypoint_count=result["waypoint_count"],
        line_count=result["line_count"],
        spacing_m=result["spacing_m"],
        altitude_m=result["altitude_m"],
        waypoints=[RFScanWaypoint(**wp) for wp in result["waypoints"]],
        px4_waypoints=[RFScanWaypoint(**wp) for wp in result["px4_waypoints"]],
        start_endpoint=start_ep,
    )


@app.get("/api/rf-scan/state")
def api_rf_scan_state():
    """Return the current RF scan state and summary."""
    mission = session_state.get("rf_scan_mission")
    return {
        "state": session_state.get("rf_scan_state", "IDLE"),
        "has_mission": mission is not None,
        "waypoint_count": mission["waypoint_count"] if mission else 0,
        "line_count": mission["line_count"] if mission else 0,
        "total_distance_m": mission["total_distance_m"] if mission else 0.0,
        "spacing_m": mission["spacing_m"] if mission else 25.0,
        "altitude_m": mission["altitude_m"] if mission else config.DEFAULT_ALTITUDE,
    }


@app.post("/api/rf-scan/upload", response_model=MissionUploadResponse)
def api_rf_scan_upload():
    """Upload the generated RF scan survey mission to PX4 via MAVLink.

    Reuses the identical upload pathway as /api/mission/send. The RF scan
    waypoints (already in PX4 coordinate space) are assembled into a valid
    PX4 mission: TAKEOFF → survey waypoints → LAND. On success the
    mav_manager upload state is set to UPLOADED so /api/mission/start can
    immediately start the scan without any additional state hacks.

    Prerequisites:
        - RF scan must have been generated (MISSION_GENERATED state).
        - PX4 must be connected.
    """
    rf_mission = session_state.get("rf_scan_mission")
    if not rf_mission:
        raise HTTPException(
            400,
            "No RF scan mission has been generated yet. "
            "POST /api/rf-scan/generate first.",
        )

    if session_state.get("rf_scan_state") not in (
        "MISSION_GENERATED", "MISSION_UPLOADED", "FAILED"
    ):
        raise HTTPException(
            400,
            f"RF scan is in state {session_state['rf_scan_state']!r} — "
            "generate a scan first.",
        )

    px4_waypoints = rf_mission.get("px4_waypoints")
    if not px4_waypoints:
        raise HTTPException(400, "RF scan mission has no PX4 waypoints.")

    # Obtain the PX4 home position (needed for the TAKEOFF item).
    mapper = coordinate_mapper.get_mapper()
    refs = mapper.get_references()
    px4_ref = refs.get("px4_reference", {})
    home_lat = px4_ref.get("latitude")
    home_lon = px4_ref.get("longitude")

    if home_lat is None or home_lon is None:
        raise HTTPException(
            400,
            "PX4 home/reference coordinate is not available. "
            "Start PX4 SITL and wait for a heartbeat.",
        )

    # Capture the UAV's original position before starting/uploading the RF Scan mission.
    # Call this: scanStartPosition.
    uav_state = mav_manager.get_vehicle_state()
    raw_uav_lat = uav_state.get("latitude")
    raw_uav_lon = uav_state.get("longitude")
    uav_alt = uav_state.get("altitude", 0.0)

    # Use current UAV telemetry position if available, fallback to PX4 home reference
    if raw_uav_lat is not None and raw_uav_lon is not None:
        start_lat = raw_uav_lat
        start_lon = raw_uav_lon
    else:
        start_lat = home_lat
        start_lon = home_lon

    gcs_start_lat, gcs_start_lon = mapper.px4_to_gcs(start_lat, start_lon)
    scan_start_pos = {
        "latitude": gcs_start_lat,
        "longitude": gcs_start_lon,
        "altitude": uav_alt,
        "px4_latitude": start_lat,
        "px4_longitude": start_lon,
    }
    session_state["scan_start_position"] = scan_start_pos
    logger.info(f"RF Scan start position captured (scanStartPosition): {scan_start_pos}")

    # Build the MAVLink mission items (TAKEOFF -> survey waypoints -> RETURN TO START -> LAND).
    # The return altitude follows the configured survey altitude.
    survey_alt = rf_mission.get("altitude_m", config.DEFAULT_ALTITUDE)
    try:
        items = mavlink_mission.build_survey_mission_items(
            px4_waypoints=px4_waypoints,
            home_lat=home_lat,
            home_lon=home_lon,
            return_lat=start_lat,
            return_lon=start_lon,
            return_alt_m=survey_alt,
        )
    except mavlink_mission.InvalidMission as e:
        raise HTTPException(400, str(e))

    if not mav_manager.is_connected():
        raise HTTPException(
            503,
            "PX4 is not connected. Start PX4 SITL and wait for a heartbeat.",
        )

    session_state["rf_scan_state"] = "UPLOADING"

    logger.info(
        f"RF scan upload started: {len(items)} items "
        f"({rf_mission['waypoint_count']} survey waypoints)"
    )

    try:
        result = mav_manager.send_command(
            "upload_mission",
            items=items,
            timeout_s=config.MISSION_UPLOAD_TIMEOUT_S,
        )
        n = result["items"]

    except mavlink_mission.MissionTimeout as e:
        session_state["rf_scan_state"] = "FAILED"
        return MissionUploadResponse(
            success=False,
            status="timeout",
            items=0,
            error=str(e),
        )

    except mavlink_mission.MissionRejected as e:
        session_state["rf_scan_state"] = "FAILED"
        return MissionUploadResponse(
            success=False,
            status="rejected",
            items=0,
            error=str(e),
        )

    except mavlink_mission.MissionUploadError as e:
        session_state["rf_scan_state"] = "FAILED"
        return MissionUploadResponse(
            success=False,
            status="failed",
            items=0,
            error=str(e),
        )

    except RuntimeError as e:
        session_state["rf_scan_state"] = "FAILED"
        return MissionUploadResponse(
            success=False,
            status="disconnected",
            items=0,
            error=str(e),
        )

    # PX4 accepted the survey mission.
    session_state["rf_scan_state"] = "MISSION_UPLOADED"

    # Set the MAVLink manager's upload state to UPLOADED so the shared
    # /api/mission/start endpoint (which checks this state) is immediately
    # usable for starting the RF scan, exactly as it is for normal missions.
    mav_manager.set_mission_upload_state(
        status="UPLOADED",
        mission_id=None,
        items=n,
        error=None,
    )

    # Phase 4 — prepare the RF Survey Collector with the scan start position,
    # affected area, deployed nodes, and mission item counts.
    # Total items = waypoint_count + 1 (TAKEOFF + survey_wps).
    # Survey finishes at the final survey waypoint with no return-to-start or landing leg.
    deployed_nodes = list_nodes()
    rf_collector = get_rf_collector()
    first_wp = rf_mission["waypoints"][0] if rf_mission.get("waypoints") else None
    first_survey_wp = (
        {"latitude": first_wp["lat"], "longitude": first_wp["lon"]} if first_wp else None
    )
    rf_collector.prepare_scan(
        start_position=scan_start_pos,
        affected_area=session_state.get("polygon"),
        deployed_nodes=deployed_nodes,
        survey_waypoint_count=rf_mission["waypoint_count"],
        total_mission_items=n,
        first_survey_waypoint=first_survey_wp,
    )
    logger.info(
        f"RF scan mission uploaded: {n} items accepted by PX4. "
        f"Collector prepared with {len(deployed_nodes)} nodes."
    )

    return MissionUploadResponse(
        success=True,
        status="uploaded",
        items=n,
    )


# ---------------------------------------------------------------------------
# Candidate generation + scoring
# ---------------------------------------------------------------------------


@app.get("/api/candidates", response_model=CandidatesResponse)
def api_candidates():
    polygon = session_state["polygon"]
    if not polygon:
        raise HTTPException(400, "No affected area defined yet — POST /api/area first.")
    if session_state["last_coverage"] is None:
        raise HTTPException(400, "Run POST /api/analyze before requesting candidates.")

    nodes = list_nodes()
    candidates = generate_candidates(polygon, nodes)
    if not candidates:
        raise HTTPException(
            400,
            "No coverage gaps found — the affected area is already fully covered, "
            "so no candidate deployment sites can be generated.",
        )

    scored = score_candidates(candidates, polygon, nodes)
    session_state["last_candidates"] = candidates
    session_state["last_scored"] = scored

    return CandidatesResponse(
        candidates=[CandidateOut(**c) for c in scored],
        top=[CandidateOut(**c) for c in top_n(scored, 2)],
    )


# ---------------------------------------------------------------------------
# Target selection + mission generation
# ---------------------------------------------------------------------------


def _closest_scored_candidate(lat, lon):
    for c in session_state.get("last_scored") or []:
        if haversine_distance_m(lat, lon, c["lat"], c["lon"]) < _CANDIDATE_MATCH_TOLERANCE_M:
            return c
    rf_analysis = session_state.get("rf_analysis") or {}
    for c in rf_analysis.get("candidates") or []:
        c_lat = c.get("latitude") if c.get("latitude") is not None else c.get("lat")
        c_lon = c.get("longitude") if c.get("longitude") is not None else c.get("lon")
        if c_lat is not None and c_lon is not None:
            if haversine_distance_m(lat, lon, c_lat, c_lon) < _CANDIDATE_MATCH_TOLERANCE_M:
                return {
                    "lat": c_lat,
                    "lon": c_lon,
                    "score": c.get("score", 0.0),
                    "coverage_gain": c.get("gap_points", 0),
                    "dist_to_nearest_m": c.get("nearest_node_distance_m", 0.0),
                }
    return None


@app.post("/api/select-target", response_model=SelectTargetResponse)
def api_select_target(req: SelectTargetRequest):
    polygon = session_state["polygon"]
    if not polygon:
        raise HTTPException(400, "No affected area defined yet.")
    if not point_in_polygon(req.lat, req.lon, polygon):
        raise HTTPException(400, "Target is outside the affected area.")

    for node in list_nodes():
        d = haversine_distance_m(req.lat, req.lon, node["lat"], node["lon"])
        if d < config.MIN_NODE_SEPARATION_M:
            raise HTTPException(
                400,
                f"Target is too close to existing node {node['id']} "
                f"({d:.0f}m, minimum separation is {config.MIN_NODE_SEPARATION_M}m).",
            )

    matched = _closest_scored_candidate(req.lat, req.lon) is not None
    session_state["selected_target"] = {"lat": req.lat, "lon": req.lon}
    session_state["deployment_released"] = False
    if session_state.get("rf_phase6_state") == "BEFORE_ANALYZED":
        session_state["rf_phase6_state"] = "CANDIDATE_SELECTED"

    return SelectTargetResponse(accepted=True, lat=req.lat, lon=req.lon, matched_candidate=matched)


@app.post("/api/mission/generate", response_model=MissionOut)
def api_mission_generate(req: MissionGenerateRequest):
    polygon = session_state["polygon"]
    if not polygon:
        raise HTTPException(400, "No affected area defined yet.")
    if not point_in_polygon(req.lat, req.lon, polygon):
        raise HTTPException(400, "Target is outside the affected area.")

    altitude = req.altitude_m if req.altitude_m is not None else config.DEFAULT_ALTITUDE
    if altitude <= 0:
        raise HTTPException(400, "Target altitude must be positive.")

    matched = _closest_scored_candidate(req.lat, req.lon)
    score = matched["score"] if matched else None

    mission = insert_mission(req.lat, req.lon, altitude, score, status="MISSION_READY")
    session_state["mission_state"] = "GENERATED"
    session_state["selected_target"] = {"lat": req.lat, "lon": req.lon}
    session_state["last_mission_id"] = mission["id"]
    session_state["last_mission"] = mission
    if session_state.get("rf_phase6_state") in ("CANDIDATE_SELECTED", "BEFORE_ANALYZED"):
        session_state["rf_phase6_state"] = "DEPLOYMENT_MISSION"

    # Sync the MAVLinkManager upload state so the UI shows GENERATED.
    mav_manager.set_mission_upload_state(
        status="GENERATED",
        mission_id=mission["id"],
        items=0,
        error=None,
    )

    return MissionOut(**mission)


# ---------------------------------------------------------------------------
# Phase 8 — Mission upload and execution
# ---------------------------------------------------------------------------


@app.post("/api/mission/send", response_model=MissionUploadResponse)
def api_mission_send():
    """Upload the current generated mission to PX4 via MAVLink.

    Steps:
        1. Validate a mission exists (GENERATED state).
        2. Validate coordinates and altitude.
        3. Validate PX4 is connected.
        4. Build MAVLink mission items.
        5. Upload via MAVLink protocol (queued to the owning thread).
        6. Wait for PX4 MISSION_ACK.
        7. Return success/failure with meaningful error.

    This endpoint is separate from /api/mission/start. Uploading a
    mission does NOT arm the vehicle or begin flight.
    """
    mission = session_state.get("last_mission")
    if not mission:
        raise HTTPException(
            400,
            "No mission has been generated yet. "
            "POST /api/mission/generate first.",
        )

    lat  = mission["target_lat"]
    lon  = mission["target_lon"]
    alt  = mission["target_alt"]
    mid  = mission["id"]

    # Phase 9A — when running against SITL, transform the GCS planning
    # coordinates into the PX4/Gazebo geographic frame before building
    # mission items.  In production (SIMULATION_MODE=False) this is a
    # no-op that returns (lat, lon) unchanged.
    if config.SIMULATION_MODE:
        mapper = coordinate_mapper.get_mapper()
        px4_lat, px4_lon = mapper.gcs_to_px4(lat, lon)
        
        # Step 2: Debug logging as requested
        refs = mapper.get_references()
        gcs_ref = refs["gcs_reference"]
        px4_ref = refs["px4_reference"]
        
        north_m, east_m = mapper.gcs_to_displacement(lat, lon)
        
        uav_state = mav_manager.get_vehicle_state()
        uav_lat = uav_state.get("latitude")
        uav_lon = uav_state.get("longitude")
        
        logger.info("\n--- COORDINATE DEBUG CHAIN ---")
        if uav_lat is not None and uav_lon is not None:
            gcs_uav_lat, gcs_uav_lon = mapper.px4_to_gcs(uav_lat, uav_lon)
            logger.info(f"GCS UAV:\n    lat={gcs_uav_lat:.7f}\n    lon={gcs_uav_lon:.7f}")
        else:
            logger.info("GCS UAV:\n    lat=UNKNOWN\n    lon=UNKNOWN")
            
        logger.info(f"\nGCS TARGET:\n    lat={lat:.7f}\n    lon={lon:.7f}")
        logger.info(f"\nGCS DISPLACEMENT:\n    north={north_m:+.1f}m\n    east={east_m:+.1f}m")
        logger.info(f"\nPX4 REFERENCE:\n    lat={px4_ref['latitude']:.7f}\n    lon={px4_ref['longitude']:.7f}")
        logger.info(f"\nPX4 TARGET:\n    lat={px4_lat:.7f}\n    lon={px4_lon:.7f}")
        
        if uav_lat is not None and uav_lon is not None:
            # Calculate distance and bearing from UAV to target
            R = 6371000.0
            phi1, phi2 = math.radians(uav_lat), math.radians(px4_lat)
            dphi = math.radians(px4_lat - uav_lat)
            dlam = math.radians(px4_lon - uav_lon)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
            distance_m = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            
            y = math.sin(dlam) * math.cos(phi2)
            x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
            bearing_deg = (math.degrees(math.atan2(y, x)) + 360) % 360
            
            MPD = 111320.0
            px4_cos = math.cos(math.radians(uav_lat))
            target_north_m = (px4_lat - uav_lat) * MPD
            target_east_m = (px4_lon - uav_lon) * MPD * px4_cos
            
            logger.info(f"\nEXPECTED (From current PX4 UAV pos to PX4 target):\n    north={target_north_m:+.1f}m\n    east={target_east_m:+.1f}m\n    distance={distance_m:.1f}m\n    bearing={bearing_deg:.1f}deg")
        logger.info("------------------------------\n")
        
    else:
        px4_lat, px4_lon = lat, lon

    # Validate coordinates before trying the upload.
    try:
        items = mavlink_mission.build_mission_items(px4_lat, px4_lon, alt,px4_ref["latitude"],px4_ref["longitude"])
    except mavlink_mission.InvalidMission as e:
        raise HTTPException(400, str(e))

    if not mav_manager.is_connected():
        raise HTTPException(
            503,
            "PX4 is not connected. Start PX4 SITL and wait for a "
            "heartbeat before uploading a mission.",
        )

    # Update DB and session state to UPLOADING before queuing.
    update_mission_status(mid, "UPLOADING")
    session_state["mission_state"] = "UPLOADING"

    try:
        result = mav_manager.send_command(
            "upload_mission",
            items=items,
            mission_id=mid,
            timeout_s=config.MISSION_UPLOAD_TIMEOUT_S,
        )
        n = result["items"]

    except mavlink_mission.MissionTimeout as e:
        update_mission_status(mid, "FAILED")
        session_state["mission_state"] = "FAILED"
        return MissionUploadResponse(
            success=False,
            mission_id=mid,
            status="timeout",
            items=0,
            error=str(e),
        )

    except mavlink_mission.MissionRejected as e:
        update_mission_status(mid, "FAILED")
        session_state["mission_state"] = "FAILED"
        return MissionUploadResponse(
            success=False,
            mission_id=mid,
            status="rejected",
            items=0,
            error=str(e),
        )

    except mavlink_mission.MissionUploadError as e:
        update_mission_status(mid, "FAILED")
        session_state["mission_state"] = "FAILED"
        return MissionUploadResponse(
            success=False,
            mission_id=mid,
            status="failed",
            items=0,
            error=str(e),
        )

    except RuntimeError as e:
        # MAVLink connection dropped between the connected check and send.
        update_mission_status(mid, "FAILED")
        session_state["mission_state"] = "FAILED"
        return MissionUploadResponse(
            success=False,
            mission_id=mid,
            status="disconnected",
            items=0,
            error=str(e),
        )

    # PX4 accepted the mission.
    update_mission_status(mid, "UPLOADED")
    session_state["mission_state"] = "UPLOADED"
    # Keep last_mission up-to-date so /api/mission/start can verify the state.
    session_state["last_mission"] = get_mission(mid)

    return MissionUploadResponse(
        success=True,
        mission_id=mid,
        status="uploaded",
        items=n,
    )


@app.post("/api/mission/start", response_model=MissionStartResponse)
def api_mission_start():
    """Command PX4 into mission (AUTO.MISSION) mode to execute the
    uploaded mission.

    Prerequisites:
        - A mission must have been successfully uploaded (UPLOADED state).
        - PX4 must be connected.

    Does NOT automatically arm the vehicle. The user must arm separately
    via POST /api/vehicle/arm before or after setting mission mode.

    Phase 3: If the current uploaded mission is an RF Scan (rf_scan_state ==
    MISSION_UPLOADED), the RF collector is transitioned to SCANNING so that
    live telemetry samples begin accumulating immediately.
    """
    upload_st = mav_manager.get_mission_upload_state()
    if upload_st["status"] != "UPLOADED":
        raise HTTPException(
            400,
            f"Mission has not been successfully uploaded yet "
            f"(current status: {upload_st['status']}). "
            "POST /api/mission/send first.",
        )

    if not mav_manager.is_connected():
        raise HTTPException(
            503,
            "PX4 is not connected. Cannot start mission.",
        )

    # Phase 5 Requirement 25: START MISSION must not work while the UAV is disarmed.
    vstate = mav_manager.get_vehicle_state()
    if not vstate.get("armed"):
        raise HTTPException(
            400,
            "UAV must be armed before starting the mission.",
        )

    try:
        mav_manager.send_command("set_mode", mode="MISSION")
        session_state["mission_state"] = "EXECUTING"

        # Phase 3 — if this start is for an RF Scan mission, transition the
        # RF collector to SCANNING so telemetry samples begin accumulating.
        if session_state.get("rf_scan_state") == "MISSION_UPLOADED":
            rf_collector = get_rf_collector()
            rf_collector.start_scan()
            session_state["rf_scan_state"] = "RUNNING"
            logger.info(f"RF Scan mission started — collector state: {rf_collector.state}.")

        return MissionStartResponse(success=True, mode="MISSION")

    except mavlink_commands.CommandRejected as e:
        return MissionStartResponse(
            success=False,
            mode="MISSION",
            error=str(e),
        )
    except mavlink_commands.CommandTimeout as e:
        return MissionStartResponse(
            success=False,
            error=str(e),
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(503, str(e))


@app.post("/api/mission/abort", response_model=MissionAbortResponse)
def api_mission_abort():
    """Abort the active mission.

    For RF scan missions: immediately stops RF sample collection (collector
    transitions to ABORTED) in addition to commanding RTL.
    Guards against double-abort — if there is no active mission returns a
    clear status without issuing another PX4 command.
    """
    # Connection check FIRST — consistent with all other PX4-command endpoints.
    if not mav_manager.is_connected():
        raise HTTPException(
            503,
            "PX4 is not connected. Cannot send abort/RTL command.",
        )

    # Guard against double-abort: if already aborted, reject subsequent abort attempts
    if session_state.get("mission_state") == "ABORTED" and session_state.get("rf_scan_state") in ("ABORTED", "IDLE"):
        logger.info("ABORT requested but mission already aborted — no active mission.")
        return MissionAbortResponse(
            success=False,
            action="NONE",
            error="No active mission to abort.",
        )

    # Immediately abort RF sample collection if RF scan was active.
    # This MUST happen before the RTL command so samples stop the instant abort is triggered.
    rf_scan_active = session_state.get("rf_scan_state") in ("RUNNING", "MISSION_UPLOADED", "APPROACHING")
    if rf_scan_active:
        rf_collector = get_rf_collector()
        rf_collector.abort_scan(reason="User abort via /api/mission/abort")
        session_state["rf_scan_state"] = "ABORTED"
        logger.info("RF scan ABORTED — sample collection stopped immediately.")

    try:
        mav_manager.send_command("set_mode", mode="RTL")
        session_state["mission_state"] = "ABORTED"
        logger.info("Mission aborted — PX4 commanded into RTL mode.")
        return MissionAbortResponse(success=True, action="RTL")

    except mavlink_commands.CommandRejected as e:
        return MissionAbortResponse(
            success=False,
            action="RTL",
            error=str(e),
        )
    except mavlink_commands.CommandTimeout as e:
        return MissionAbortResponse(
            success=False,
            action="RTL",
            error=str(e),
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(503, str(e))


@app.post("/api/deployment/simulate", response_model=NotImplementedResponse, status_code=501)
def api_deployment_simulate():
    return NotImplementedResponse(
        phase_required=10,
        message="Virtual deployment simulation arrives in Phase 10.",
    )


# ---------------------------------------------------------------------------
# Phase 9A — Coordinate transformation diagnostic endpoints
# ---------------------------------------------------------------------------


@app.get("/api/coordinates/reference", response_model=CoordinateReferenceResponse)
def api_coordinates_reference():
    """Return the current GCS and PX4 reference coordinates.

    The PX4 reference is updated dynamically from the vehicle's
    HOME_POSITION message once PX4 SITL connects, so this endpoint
    reflects the live mapping currently in use.
    """
    refs = coordinate_mapper.get_mapper().get_references()
    return CoordinateReferenceResponse(
        simulation_mode=config.SIMULATION_MODE,
        gcs_reference=CoordinateReferencePoint(
            latitude=refs["gcs_reference"]["latitude"],
            longitude=refs["gcs_reference"]["longitude"],
        ),
        px4_reference=CoordinateReferencePoint(
            latitude=refs["px4_reference"]["latitude"],
            longitude=refs["px4_reference"]["longitude"],
        ),
    )


@app.post("/api/coordinates/translate", response_model=CoordinateTranslateResponse)
def api_coordinates_translate(req: CoordinateTranslateRequest):
    """Translate a coordinate through the current GCS ↔ PX4 mapping.

    Accepts a WGS84 coordinate (interpreted as a GCS map coordinate) and
    returns both the corresponding PX4 coordinate and the intermediate
    north/east displacement.  Useful for verifying that the coordinate
    mapper is producing the expected results.

    When SIMULATION_MODE is False, gcs_lat/lon and px4_lat/lon will be
    identical (identity transform).
    """
    mapper = coordinate_mapper.get_mapper()
    north_m, east_m = mapper.gcs_to_displacement(req.latitude, req.longitude)
    px4_lat, px4_lon = mapper.gcs_to_px4(req.latitude, req.longitude)
    return CoordinateTranslateResponse(
        gcs_latitude=req.latitude,
        gcs_longitude=req.longitude,
        px4_latitude=px4_lat,
        px4_longitude=px4_lon,
        north_m=north_m,
        east_m=east_m,
    )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@app.get("/api/missions", response_model=List[MissionOut])
def api_missions():
    return list_missions()


@app.get("/api/deployments", response_model=List[DeploymentOut])
def api_deployments():
    # Always empty until Phase 10 writes to the deployments table — the
    # table exists now (see database.py) so this endpoint is honestly
    # "no deployments yet", not "not implemented".
    return list_deployments()



# ---------------------------------------------------------------------------
# Phase 3 — RF Survey Data endpoints (HTTP + WebSocket for Simulink bridge)
# ---------------------------------------------------------------------------


@app.get("/api/rf-survey/state")
def api_rf_survey_state():
    """Return the current RF survey collector state and summary.

    Used by Simulink / external tools to check scan progress without
    pulling the full sample dataset.
    """
    rf_collector = get_rf_collector()
    survey = rf_collector.get_survey_data()
    mission = session_state.get("rf_scan_mission")
    return {
        "state": survey["state"],
        "backend_rf_scan_state": session_state.get("rf_scan_state", "IDLE"),
        "sample_count": survey["sample_count"],
        "scan_start_position": survey["scan_start_position"],
        "affected_area": survey["affected_area"],
        "deployed_node_count": len(survey["deployed_nodes"]),
        "waypoint_count": mission["waypoint_count"] if mission else 0,
        "line_count": mission["line_count"] if mission else 0,
        "spacing_m": mission["spacing_m"] if mission else 0.0,
        "altitude_m": mission["altitude_m"] if mission else 0.0,
    }


@app.get("/api/rf-survey/data")
def api_rf_survey_data():
    """Return the complete accumulated RF survey dataset.

    Intended for Simulink to poll after (or during) an RF Scan to retrieve
    all GPS + RSSI samples.  The response is stable under concurrent reads
    (RFSurveyCollector uses a lock) and never mutates between calls.

    Response fields:
        state           — current collector state (IDLE/SCANNING/RETURNING/etc.)
        sample_count    — number of survey samples accumulated so far
        scan_start_position — {lat, lon, alt, px4_lat, px4_lon} captured at upload
        affected_area   — polygon [{lat, lon}, ...] of the user-drawn area
        deployed_nodes  — [{id, lat, lon, ...}] list used for RSSI calculation
        samples         — array of survey samples (see RFSurveyCollector docstring)
    """
    rf_collector = get_rf_collector()
    return rf_collector.get_survey_data()


@app.post("/api/rf-survey/reset")
def api_rf_survey_reset():
    """Reset the RF survey collector to IDLE, clearing all accumulated data.

    Under Phase 6:
      - If a BEFORE survey has already been analyzed and preserved, rf_before_analysis is kept intact!
      - rf_collector is reset and re-synchronized with all current deployed nodes (e.g. N+1).
      - Old temporary candidate analysis is cleared, preparing for the AFTER survey.
    """
    rf_collector = get_rf_collector()
    rf_collector.reset()
    active_nodes = list_nodes()
    rf_collector.update_deployed_nodes(active_nodes)
    session_state["rf_scan_state"] = "IDLE"
    session_state["rf_scan_mission"] = None
    session_state["rf_analysis"] = None  # Invalidate stale active analysis
    if session_state.get("rf_before_analysis"):
        session_state["rf_phase6_state"] = "AFTER_SURVEY"
        session_state["rf_after_analysis"] = None
        session_state["rf_comparison"] = None
    else:
        session_state["rf_phase6_state"] = "BEFORE_SURVEY"

    logger.info(f"RF Survey collector reset to IDLE with {len(active_nodes)} active nodes (Phase 6: {session_state['rf_phase6_state']}).")
    return {
        "success": True,
        "state": "IDLE",
        "active_nodes": len(active_nodes),
        "phase6_state": session_state["rf_phase6_state"],
    }


@app.post("/api/rf-survey/session-reset")
def api_rf_survey_session_reset():
    """
    Phase 6 Requirement 16: Reset the entire RF analysis and verification session.
    Clears BEFORE analysis, AFTER analysis, comparison, heatmaps, gap displays, candidates.
    Does NOT delete actual deployed communication nodes from the database.
    """
    rf_collector = get_rf_collector()
    rf_collector.reset()
    active_nodes = list_nodes()
    rf_collector.update_deployed_nodes(active_nodes)
    session_state["rf_scan_state"] = "IDLE"
    session_state["rf_scan_mission"] = None
    session_state["rf_analysis"] = None
    session_state["rf_before_analysis"] = None
    session_state["rf_after_analysis"] = None
    session_state["rf_comparison"] = None
    session_state["rf_phase6_state"] = "BEFORE_SURVEY"
    session_state["rf_newly_deployed_node_id"] = None
    session_state["deployment_released"] = False
    logger.info(f"RF verification session reset. {len(active_nodes)} active nodes preserved.")
    return {
        "success": True,
        "phase6_state": "BEFORE_SURVEY",
        "active_nodes": len(active_nodes),
    }


# ---------------------------------------------------------------------------
# Phase 5 & 6 — RF Survey Analysis & Verification
# ---------------------------------------------------------------------------


@app.post("/api/rf-survey/analyze")
def api_rf_survey_analyze():
    """
    Analyze the completed RF survey dataset and return:
      - Coverage heatmap (one point per real survey sample)
      - Gap points (samples with bestRSSI <= -85 dBm)
      - Gap cluster count
      - Ranked candidate locations (MATLAB CandidatePlacement algorithm)
      - Coverage summary percentages
      - Phase 6 BEFORE vs AFTER preservation and comparison verification
      - Actual survey history record (last 5 completed surveys stored independently)
    """
    rf_collector = get_rf_collector()
    survey_data = rf_collector.get_survey_data()

    state_val = survey_data.get("state", "IDLE")
    samples = survey_data.get("samples") or []
    deployed_nodes = list_nodes()  # current active nodes (single source of truth)

    if not samples:
        raise HTTPException(
            400,
            f"No RF survey samples available (collector state: {state_val}). "
            "Complete an RF scan before analyzing.",
        )

    logger.info(
        f"RF survey analysis requested: {len(samples)} samples, "
        f"{len(deployed_nodes)} active nodes, collector state={state_val}"
    )

    result = rf_survey_analyzer.analyze_rf_survey(
        samples=samples,
        deployed_nodes=deployed_nodes,
        affected_area=session_state.get("polygon"),
    )

    # Package snapshot for immutable BEFORE / AFTER storage
    snapshot = rf_survey_analyzer.package_analysis_snapshot(
        analysis_result=result,
        deployed_nodes=deployed_nodes,
        affected_area=session_state.get("polygon"),
    )

    # Phase 6: Check whether this is BEFORE or AFTER survey
    if session_state.get("rf_before_analysis") is None:
        session_state["rf_before_analysis"] = snapshot
        session_state["rf_after_analysis"] = None
        session_state["rf_comparison"] = None
        session_state["rf_phase6_state"] = "BEFORE_ANALYZED"
        survey_role = "BEFORE"
        comparison = None
    else:
        session_state["rf_after_analysis"] = snapshot
        comparison = rf_survey_analyzer.compare_before_after(
            session_state["rf_before_analysis"],
            snapshot,
        )
        session_state["rf_comparison"] = comparison
        session_state["rf_phase6_state"] = "VERIFIED"
        survey_role = "AFTER"

    result["survey_role"] = survey_role
    result["phase6_state"] = session_state["rf_phase6_state"]
    result["before_analysis"] = session_state.get("rf_before_analysis")
    result["after_analysis"] = session_state.get("rf_after_analysis")
    result["comparison"] = session_state.get("rf_comparison")
    result["newly_deployed_node_id"] = session_state.get("rf_newly_deployed_node_id")

    # Phase 6 & History: Check whether this survey is aborted.
    # Requirement 14: An aborted survey must not be treated as a completed historical survey.
    if state_val != SCAN_STATE_ABORTED:
        session_state["rf_survey_history_counter"] = session_state.get("rf_survey_history_counter", 0) + 1
        survey_id = f"SURVEY-{session_state['rf_survey_history_counter']:03d}"
        cov_stats = rf_survey_analyzer.calculate_coverage_statistics(result)
        good_pct = cov_stats["good_percentage"]
        moderate_pct = cov_stats["moderate_percentage"]
        weak_pct = cov_stats["weak_percentage"]
        gap_pct = cov_stats["gap_percentage"]

        history_record = {
            "survey_id": survey_id,
            "survey_role": survey_role,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_epoch": time.time(),
            "affected_area": [dict(p) for p in (session_state.get("polygon") or [])],
            "node_set": [dict(n) for n in deployed_nodes],
            "node_count": len(deployed_nodes),
            "samples": [
                {
                    "lat": s.get("lat") if s.get("lat") is not None else s.get("latitude"),
                    "lon": s.get("lon") if s.get("lon") is not None else s.get("longitude"),
                    "latitude": s.get("latitude") if s.get("latitude") is not None else s.get("lat"),
                    "longitude": s.get("longitude") if s.get("longitude") is not None else s.get("lon"),
                    "rssi": s.get("rssi"),
                    "best_rssi": s.get("best_rssi"),
                    "status": s.get("status"),
                }
                for s in samples
            ],
            "sample_count": len(samples),
            "measured_count": cov_stats["measured_count"],
            "unmeasured_count": cov_stats["unmeasured_count"],
            "heatmap": [
                {
                    "lat": c.get("lat") if c.get("lat") is not None else c.get("latitude"),
                    "lon": c.get("lon") if c.get("lon") is not None else c.get("longitude"),
                    "latitude": c.get("latitude") if c.get("latitude") is not None else c.get("lat"),
                    "longitude": c.get("longitude") if c.get("longitude") is not None else c.get("lon"),
                    "rssi": c.get("rssi") if c.get("rssi") is not None else c.get("best_rssi"),
                    "best_rssi": c.get("best_rssi") if c.get("best_rssi") is not None else c.get("rssi"),
                    "status": c.get("status"),
                }
                for c in (result.get("heatmap") or [])
            ],
            "good_percentage": good_pct,
            "moderate_percentage": moderate_pct,
            "weak_percentage": weak_pct,
            "gap_percentage": gap_pct,
            "good_pct": good_pct,
            "moderate_pct": moderate_pct,
            "weak_pct": weak_pct,
            "gap_pct": gap_pct,
            "coverage_statistics": {
                "good_count": cov_stats["good_count"],
                "moderate_count": cov_stats["moderate_count"],
                "weak_count": cov_stats["weak_count"],
                "gap_count": cov_stats["gap_count"],
                "unmeasured_count": cov_stats["unmeasured_count"],
                "measured_count": cov_stats["measured_count"],
                "total_samples": cov_stats["total_samples"],
                "good_percentage": good_pct,
                "moderate_percentage": moderate_pct,
                "weak_percentage": weak_pct,
                "gap_percentage": gap_pct,
                "good_pct": good_pct,
                "moderate_pct": moderate_pct,
                "weak_pct": weak_pct,
                "gap_pct": gap_pct,
            },
            "gaps": {
                "gap_count": cov_stats["gap_count"],
                "gap_cluster_count": result.get("gap_cluster_count", 0),
                "gap_points": [
                    {
                        "lat": p.get("lat") if p.get("lat") is not None else p.get("latitude"),
                        "lon": p.get("lon") if p.get("lon") is not None else p.get("longitude"),
                        "latitude": p.get("latitude") if p.get("latitude") is not None else p.get("lat"),
                        "longitude": p.get("longitude") if p.get("longitude") is not None else p.get("lon"),
                        "rssi": p.get("rssi") if p.get("rssi") is not None else p.get("best_rssi"),
                        "best_rssi": p.get("best_rssi") if p.get("best_rssi") is not None else p.get("rssi"),
                    }
                    for p in (result.get("gap_points") or [])
                ],
                "gap_clusters": [dict(c) for c in (result.get("gap_clusters") or [])],
            },
            "candidates": [dict(c) for c in (result.get("candidates") or [])],
            "analysis": copy.deepcopy(result),
        }
        history = session_state.setdefault("rf_survey_history", [])
        history.append(history_record)
        # Store last 5 completed RF surveys independently (ring buffer)
        if len(history) > 5:
            history.pop(0)

        result["survey_id"] = survey_id

    session_state["rf_analysis"] = result

    logger.info(
        f"RF analysis complete [{survey_role}]: {result['survey_samples']} samples | "
        f"GOOD={result['good_count']} MODERATE={result['moderate_count']} "
        f"WEAK={result['weak_count']} GAP={result['gap_count']} "
        f"UNMEASURED={result['unmeasured_count']} | "
        f"{result['gap_cluster_count']} gap clusters, "
        f"{len(result['candidates'])} candidates | "
        f"Phase 6 state: {session_state['rf_phase6_state']}"
    )

    return result


@app.get("/api/rf-survey/analysis")
def api_rf_survey_analysis_get():
    """Return the most recently computed RF analysis result."""
    result = session_state.get("rf_analysis")
    if result is None:
        raise HTTPException(
            404,
            "No RF analysis results available. POST /api/rf-survey/analyze first.",
        )
    return result


@app.get("/api/rf-survey/before")
def api_rf_survey_before_get():
    """Return the preserved BEFORE RF survey analysis snapshot."""
    before_data = session_state.get("rf_before_analysis")
    if before_data is None:
        raise HTTPException(404, "No BEFORE RF survey analysis available.")
    return before_data


@app.get("/api/rf-survey/after")
def api_rf_survey_after_get():
    """Return the preserved AFTER RF survey analysis snapshot."""
    after_data = session_state.get("rf_after_analysis")
    if after_data is None:
        raise HTTPException(404, "No AFTER RF survey analysis available.")
    return after_data


@app.get("/api/rf-survey/comparison")
def api_rf_survey_comparison_get():
    """Return the computed BEFORE vs AFTER verification comparison."""
    comp = session_state.get("rf_comparison")
    if comp is None:
        b = session_state.get("rf_before_analysis")
        a = session_state.get("rf_after_analysis")
        if b and a:
            comp = rf_survey_analyzer.compare_before_after(b, a)
            session_state["rf_comparison"] = comp
        else:
            raise HTTPException(404, "No comparison available. Complete both BEFORE and AFTER surveys.")
    return comp


@app.get("/api/rf-survey/verification")
def api_rf_survey_verification_get():
    """Return full Phase 6 deployment verification status."""
    return {
        "phase6_state": session_state.get("rf_phase6_state", "BEFORE_SURVEY"),
        "before": session_state.get("rf_before_analysis"),
        "after": session_state.get("rf_after_analysis"),
        "comparison": session_state.get("rf_comparison"),
        "newly_deployed_node_id": session_state.get("rf_newly_deployed_node_id"),
    }


# ---------------------------------------------------------------------------
# Phase 6 — Actual RF Survey History & Multi-Survey Comparison
# ---------------------------------------------------------------------------


class HistoryCompareRequest(BaseModel):
    survey_id_1: str
    survey_id_2: str


def _execute_history_comparison(survey_id_1: str, survey_id_2: str) -> dict:
    history = session_state.get("rf_survey_history", [])
    s1 = next((s for s in history if s["survey_id"] == survey_id_1), None)
    s2 = next((s for s in history if s["survey_id"] == survey_id_2), None)
    if not s1:
        raise HTTPException(404, f"Historical survey '{survey_id_1}' not found in history.")
    if not s2:
        raise HTTPException(404, f"Historical survey '{survey_id_2}' not found in history.")

    area1 = s1.get("affected_area") or []
    area2 = s2.get("affected_area") or []
    comparable = rf_survey_analyzer.are_polygons_equivalent(area1, area2)
    invalidation_reason = None
    if not comparable:
        invalidation_reason = "Affected areas differ between surveys. Comparison may be unrepresentative."

    raw_s1 = s1.get("samples") or s1.get("heatmap") or []
    raw_s2 = s2.get("samples") or s2.get("heatmap") or []
    s1_stats = rf_survey_analyzer.calculate_coverage_statistics(raw_s1, affected_area=area1)
    s2_stats = rf_survey_analyzer.calculate_coverage_statistics(raw_s2, affected_area=area2)

    s1_good = s1_stats["good_percentage"]
    s1_mod = s1_stats["moderate_percentage"]
    s1_weak = s1_stats["weak_percentage"]
    s1_gap = s1_stats["gap_percentage"]

    s2_good = s2_stats["good_percentage"]
    s2_mod = s2_stats["moderate_percentage"]
    s2_weak = s2_stats["weak_percentage"]
    s2_gap = s2_stats["gap_percentage"]

    delta_good_pp = round(s2_good - s1_good, 1)
    delta_mod_pp = round(s2_mod - s1_mod, 1)
    delta_weak_pp = round(s2_weak - s1_weak, 1)
    delta_gap_pp = round(s2_gap - s1_gap, 1)

    s1_gap_count = s1_stats["gap_count"]
    s2_gap_count = s2_stats["gap_count"]
    s1_gaps = s1.get("gaps", {})
    s2_gaps = s2.get("gaps", {})
    s1_clusters = s1_gaps.get("gap_cluster_count", 0)
    s2_clusters = s2_gaps.get("gap_cluster_count", 0)

    delta_gap_count = s2_gap_count - s1_gap_count

    survey_a = {
        "survey_id": s1["survey_id"],
        "survey_role": s1.get("survey_role", "SURVEY"),
        "timestamp": s1["timestamp"],
        "sample_count": s1_stats["sample_count"],
        "measured_count": s1_stats["measured_count"],
        "unmeasured_count": s1_stats["unmeasured_count"],
        "node_count": s1["node_count"],
        "good_percentage": s1_good,
        "moderate_percentage": s1_mod,
        "weak_percentage": s1_weak,
        "gap_percentage": s1_gap,
        "gap_count": s1_gap_count,
        "gap_cluster_count": s1_clusters,
        # backward compat aliases:
        "good_pct": s1_good,
        "moderate_pct": s1_mod,
        "weak_pct": s1_weak,
        "gap_pct": s1_gap,
        "gap_points_count": s1_gap_count,
        "gap_clusters_count": s1_clusters,
        "gap_points": s1_gaps.get("gap_points", []),
        "gap_clusters": s1_gaps.get("gap_clusters", []),
        "heatmap": s1.get("heatmap", []),
    }

    survey_b = {
        "survey_id": s2["survey_id"],
        "survey_role": s2.get("survey_role", "SURVEY"),
        "timestamp": s2["timestamp"],
        "sample_count": s2_stats["sample_count"],
        "measured_count": s2_stats["measured_count"],
        "unmeasured_count": s2_stats["unmeasured_count"],
        "node_count": s2["node_count"],
        "good_percentage": s2_good,
        "moderate_percentage": s2_mod,
        "weak_percentage": s2_weak,
        "gap_percentage": s2_gap,
        "gap_count": s2_gap_count,
        "gap_cluster_count": s2_clusters,
        # backward compat aliases:
        "good_pct": s2_good,
        "moderate_pct": s2_mod,
        "weak_pct": s2_weak,
        "gap_pct": s2_gap,
        "gap_points_count": s2_gap_count,
        "gap_clusters_count": s2_clusters,
        "gap_points": s2_gaps.get("gap_points", []),
        "gap_clusters": s2_gaps.get("gap_clusters", []),
        "heatmap": s2.get("heatmap", []),
    }

    delta = {
        "good_percentage_pp": delta_good_pp,
        "moderate_percentage_pp": delta_mod_pp,
        "weak_percentage_pp": delta_weak_pp,
        "gap_percentage_pp": delta_gap_pp,
        "sample_count": s2_stats["sample_count"] - s1_stats["sample_count"],
        "node_count": s2["node_count"] - s1["node_count"],
        "gap_count": delta_gap_count,
        "gap_cluster_count": s2_clusters - s1_clusters,
        # backward compat aliases:
        "good_pct_change": delta_good_pp,
        "moderate_pct_change": delta_mod_pp,
        "weak_pct_change": delta_weak_pp,
        "gap_pct_change": delta_gap_pp,
        "sample_count_change": s2_stats["sample_count"] - s1_stats["sample_count"],
        "node_count_change": s2["node_count"] - s1["node_count"],
        "gaps_resolved": max(0, s1_gap_count - s2_gap_count),
        "gap_clusters_change": s2_clusters - s1_clusters,
    }

    return {
        "survey_a": survey_a,
        "survey_b": survey_b,
        "survey_1": survey_a,
        "survey_2": survey_b,
        "delta": delta,
        "comparable": comparable,
        "invalidation_reason": invalidation_reason,
    }


@app.get("/api/rf-survey/history")
def api_rf_survey_history_list():
    """
    Phase 6 Requirement 7, 8, 9: Return summary list of the last 5 completed RF surveys.
    Authoritatively derives statistics from actual historical survey samples on read.
    Does NOT modify current state.
    """
    history = session_state.get("rf_survey_history", [])
    surveys_summary = []
    for s in history:
        raw_samples = s.get("samples") or s.get("heatmap") or []
        stats = rf_survey_analyzer.calculate_coverage_statistics(
            raw_samples,
            affected_area=s.get("affected_area"),
        )
        good_pct = stats["good_percentage"]
        mod_pct = stats["moderate_percentage"]
        weak_pct = stats["weak_percentage"]
        gap_pct = stats["gap_percentage"]
        gap_count = stats["gap_count"]
        gap_cluster_count = s.get("gaps", {}).get("gap_cluster_count", 0)

        surveys_summary.append({
            "survey_id": s["survey_id"],
            "survey_role": s.get("survey_role", "SURVEY"),
            "timestamp": s["timestamp"],
            "node_count": s["node_count"],
            "sample_count": stats["sample_count"],
            "measured_count": stats["measured_count"],
            "unmeasured_count": stats["unmeasured_count"],
            "good_percentage": good_pct,
            "moderate_percentage": mod_pct,
            "weak_percentage": weak_pct,
            "gap_percentage": gap_pct,
            "good_pct": good_pct,
            "moderate_pct": mod_pct,
            "weak_pct": weak_pct,
            "gap_pct": gap_pct,
            "gap_count": gap_count,
            "gap_cluster_count": gap_cluster_count,
            "candidate_count": len(s.get("candidates", [])),
        })
    return {
        "count": len(surveys_summary),
        "surveys": surveys_summary,
    }


@app.get("/api/rf-survey/history/{survey_id}")
def api_rf_survey_history_get(survey_id: str):
    """
    Phase 6 Requirement 8, 9, 10:
    Return complete historical survey record retaining:
      survey timestamp, affected area, node set at that time, samples,
      heatmap, coverage statistics, gaps, candidates/analysis.
    Authoritatively derives statistics from immutable raw samples on read.
    Viewing historical surveys never modifies current nodes, current RF collection,
    current mission, or current candidates.
    """
    history = session_state.get("rf_survey_history", [])
    for s in history:
        if s["survey_id"] == survey_id:
            s_copy = copy.deepcopy(s)
            raw_samples = s_copy.get("samples") or s_copy.get("heatmap") or []
            stats = rf_survey_analyzer.calculate_coverage_statistics(
                raw_samples,
                affected_area=s_copy.get("affected_area"),
            )
            s_copy["sample_count"] = stats["sample_count"]
            s_copy["measured_count"] = stats["measured_count"]
            s_copy["unmeasured_count"] = stats["unmeasured_count"]
            s_copy["good_percentage"] = stats["good_percentage"]
            s_copy["moderate_percentage"] = stats["moderate_percentage"]
            s_copy["weak_percentage"] = stats["weak_percentage"]
            s_copy["gap_percentage"] = stats["gap_percentage"]
            s_copy["good_pct"] = stats["good_pct"]
            s_copy["moderate_pct"] = stats["moderate_pct"]
            s_copy["weak_pct"] = stats["weak_pct"]
            s_copy["gap_pct"] = stats["gap_pct"]

            cov_stats = s_copy.setdefault("coverage_statistics", {})
            cov_stats["good_count"] = stats["good_count"]
            cov_stats["moderate_count"] = stats["moderate_count"]
            cov_stats["weak_count"] = stats["weak_count"]
            cov_stats["gap_count"] = stats["gap_count"]
            cov_stats["unmeasured_count"] = stats["unmeasured_count"]
            cov_stats["measured_count"] = stats["measured_count"]
            cov_stats["total_samples"] = stats["total_samples"]
            cov_stats["good_percentage"] = stats["good_percentage"]
            cov_stats["moderate_percentage"] = stats["moderate_percentage"]
            cov_stats["weak_percentage"] = stats["weak_percentage"]
            cov_stats["gap_percentage"] = stats["gap_percentage"]
            cov_stats["good_pct"] = stats["good_pct"]
            cov_stats["moderate_pct"] = stats["moderate_pct"]
            cov_stats["weak_pct"] = stats["weak_pct"]
            cov_stats["gap_pct"] = stats["gap_pct"]

            if "gaps" in s_copy:
                s_copy["gaps"]["gap_count"] = stats["gap_count"]

            return s_copy
    raise HTTPException(404, f"Historical RF survey '{survey_id}' not found.")


@app.get("/api/rf-survey/history/{survey_id}/diagnostics")
def api_rf_survey_history_diagnostics(survey_id: str):
    """
    Phase 6 Requirement 12: Diagnostic endpoint inspecting raw survey samples,
    classification counts, measured/unmeasured counts, and exact percentages.
    """
    history = session_state.get("rf_survey_history", [])
    survey = next((s for s in history if s["survey_id"] == survey_id), None)
    if not survey:
        raise HTTPException(404, f"Historical survey '{survey_id}' not found in history.")

    raw_samples = survey.get("samples") or survey.get("heatmap") or []
    sample_schema = {}
    if raw_samples:
        s0 = raw_samples[0]
        sample_schema = {
            "keys": list(s0.keys()),
            "sample_0_best_rssi": s0.get("best_rssi"),
            "sample_0_rssi_type": type(s0.get("rssi")).__name__,
            "sample_0_rssi_val": s0.get("rssi"),
            "sample_0_status": s0.get("status"),
        }

    stats = rf_survey_analyzer.calculate_coverage_statistics(
        raw_samples,
        affected_area=survey.get("affected_area"),
    )

    return {
        "survey_id": survey_id,
        "sample_count": stats["sample_count"],
        "measured_count": stats["measured_count"],
        "unmeasured_count": stats["unmeasured_count"],
        "good": stats["good_count"],
        "moderate": stats["moderate_count"],
        "weak": stats["weak_count"],
        "gap": stats["gap_count"],
        "good_percentage": stats["good_percentage"],
        "moderate_percentage": stats["moderate_percentage"],
        "weak_percentage": stats["weak_percentage"],
        "gap_percentage": stats["gap_percentage"],
        "sample_schema": sample_schema,
    }


@app.post("/api/rf-survey/history/compare")
def api_rf_survey_history_compare_post(payload: HistoryCompareRequest):
    """
    Phase 6 Requirement 11 & 12: Select two historical surveys and compare them.
    Shows: node count, sample count, GOOD %, MODERATE %, WEAK %, GAP %,
    gap points, gap clusters, and heatmaps.
    """
    return _execute_history_comparison(payload.survey_id_1, payload.survey_id_2)


@app.get("/api/rf-survey/history-compare")
def api_rf_survey_history_compare_get(survey_1: str, survey_2: str):
    """GET variant of historical survey comparison for easy browser/query access."""
    return _execute_history_comparison(survey_1, survey_2)


# ---------------------------------------------------------------------------
# Phase 6 — Deployment RELEASE & Interlocks (Requirements 3, 4, 5, 6)
# ---------------------------------------------------------------------------


class DeploymentReleaseRequest(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    coverage_radius_m: Optional[float] = 250.0


def _resolve_uav_coords(uav_lat: float, uav_lon: float) -> Tuple[float, float]:
    """Resolve UAV telemetry coordinates to GCS map planning space.
    Gracefully handles both raw PX4 simulation coordinates and already-mapped GCS coordinates."""
    mapper = coordinate_mapper.get_mapper()
    if not config.SIMULATION_MODE:
        return uav_lat, uav_lon

    refs = mapper.get_references()
    px4_ref = refs.get("px4_reference", {})
    gcs_ref = refs.get("gcs_reference", {})
    p_lat = px4_ref.get("latitude", config.PX4_REFERENCE_LAT)
    p_lon = px4_ref.get("longitude", config.PX4_REFERENCE_LON)
    g_lat = gcs_ref.get("latitude", config.GCS_REFERENCE_LAT)
    g_lon = gcs_ref.get("longitude", config.GCS_REFERENCE_LON)

    dist_to_gcs = math.hypot(uav_lat - g_lat, uav_lon - g_lon)
    dist_to_px4 = math.hypot(uav_lat - p_lat, uav_lon - p_lon)

    if dist_to_gcs < dist_to_px4:
        return uav_lat, uav_lon
    return mapper.px4_to_gcs(uav_lat, uav_lon)


@app.get("/api/deployment/status")
def api_deployment_status():
    """
    Phase 6 Requirements 3-6: Deployment RELEASE status and gate evaluation.
    RELEASE must only become enabled after:
      - deployment mission has reached intended destination / deployment phase
      - UAV is physically landed/on ground (authoritative telemetry in_air/landed_state)
      - altitude is at or below configured landing threshold (1.0m, handling negative altitudes safely)
      - UAV is within configured distance tolerance of selected candidate (10.0m)
      - deployment has not already been released
    Mission state "EXECUTING" does NOT classify the UAV as airborne.
    """
    target = session_state.get("selected_target")
    released = session_state.get("deployment_released", False)
    uav_state = mav_manager.get_vehicle_state()
    rel_alt = uav_state.get("relative_altitude")
    raw_alt = rel_alt if rel_alt is not None else uav_state.get("altitude")
    normalized_altitude = max(0.0, raw_alt) if raw_alt is not None else 0.0

    in_air = uav_state.get("in_air")
    landed_state = uav_state.get("landed_state")
    flight_mode = str(uav_state.get("flight_mode") or uav_state.get("mode") or "").upper()
    mission_state = session_state.get("mission_state", "IDLE")

    # Authoritative physical flight state:
    # 1. Telemetry in_air flag
    # 2. Telemetry landed_state (EXTENDED_SYS_STATE)
    # 3. Altitude threshold (<= 1.0m, normalized)
    # NOTE: mission_state == "EXECUTING" must NEVER override confirmed physical landed state!
    if in_air is True:
        is_airborne = True
    elif in_air is False:
        is_airborne = False if normalized_altitude <= 1.0 else True
    elif landed_state is not None:
        if landed_state == "ON_GROUND":
            is_airborne = False if normalized_altitude <= 1.0 else True
        else:
            is_airborne = True
    else:
        is_airborne = normalized_altitude > 1.0

    is_landed = (not is_airborne) and (normalized_altitude <= 1.0)
    is_aborted = mission_state in ("ABORTED", "FAILED") or "RTL" in flight_mode

    upload_st = mav_manager.get_mission_upload_state()
    total_items = upload_st.get("items", 0)
    mreached = uav_state.get("mission_item_reached")

    dist_m = None
    within_tolerance = False
    uav_lat = uav_state.get("latitude")
    uav_lon = uav_state.get("longitude")

    if target and uav_lat is not None and uav_lon is not None:
        gcs_uav_lat, gcs_uav_lon = _resolve_uav_coords(float(uav_lat), float(uav_lon))
        dist_m = haversine_distance_m(gcs_uav_lat, gcs_uav_lon, target["lat"], target["lon"])
        within_tolerance = dist_m <= config.CANDIDATE_DEPLOY_TOLERANCE_M
    elif target and not mav_manager.is_connected():
        dist_m = 0.0
        within_tolerance = True
        is_landed = True
        is_airborne = False

    destination_reached = within_tolerance or (
        total_items > 0 and mreached is not None and mreached >= total_items - 1
    ) or (not mav_manager.is_connected())

    # Synchronize mission_state if UAV landed at destination
    if destination_reached and is_landed and mission_state == "EXECUTING":
        session_state["mission_state"] = "COMPLETED"
        mission_state = "COMPLETED"

    can_release = bool(
        (target is not None)
        and (not is_airborne)
        and is_landed
        and within_tolerance
        and destination_reached
        and (not released)
        and (not is_aborted)
    )

    reason = "Ready for release"
    if not target:
        reason = "No candidate selected"
    elif released:
        reason = "Node already released for this candidate"
    elif is_aborted:
        reason = f"RELEASE disabled: Deployment mission was aborted or entered RTL (state={mission_state})"
    elif is_airborne:
        alt_str = f"{raw_alt:.1f}m" if raw_alt is not None else "airborne"
        reason = f"RELEASE disabled: UAV is airborne ({alt_str})"
    elif not within_tolerance:
        dist_str = f"{dist_m:.1f}m" if dist_m is not None else "unknown"
        reason = f"RELEASE disabled: UAV landed off-target ({dist_str} > {config.CANDIDATE_DEPLOY_TOLERANCE_M}m tolerance)"
    elif not destination_reached:
        reason = "RELEASE disabled: Deployment destination has not been reached"
    elif not is_landed:
        reason = f"RELEASE disabled: UAV is not landed (normalized_alt={normalized_altitude:.2f}m)"

    # Live diagnostic log (Bug 2 Requirement 5)
    logger.info(
        "RELEASE CHECK:\n"
        f"in_air={str(in_air).lower() if in_air is not None else 'unknown'}\n"
        f"landed_state={landed_state or 'UNKNOWN'}\n"
        f"altitude={f'{raw_alt:.3f}m' if raw_alt is not None else 'unknown'}\n"
        f"normalized_altitude={normalized_altitude:.3f}m\n"
        f"mission_state={mission_state}\n"
        f"distance_to_candidate={f'{dist_m:.1f}m' if dist_m is not None else 'unknown'}\n"
        f"destination_reached={str(destination_reached).lower()}\n"
        f"already_released={str(released).lower()}\n"
        f"can_release={str(can_release).lower()}"
    )

    return {
        "can_release": can_release,
        "reason": reason,
        "is_airborne": is_airborne,
        "is_landed": is_landed,
        "is_aborted": is_aborted,
        "within_tolerance": within_tolerance,
        "destination_reached": destination_reached,
        "distance_to_candidate_m": round(dist_m, 2) if dist_m is not None else None,
        "candidate_tolerance_m": config.CANDIDATE_DEPLOY_TOLERANCE_M,
        "selected_target": target,
        "already_released": released,
    }


@app.post("/api/deployment/release", response_model=NodeOut)
def api_deployment_release(payload: Optional[DeploymentReleaseRequest] = None):
    """
    Phase 6 Requirements 3-6: Command node physical release.
    Enforces all release interlocks:
      1. UAV must not be airborne (authoritative flight telemetry).
      2. Mission must no longer be flying and not aborted.
      3. UAV must actually be landed (altitude <= 1.0m, normalized).
      4. UAV must be within distance tolerance of selected candidate (10.0m).
      5. Exactly one node is created at candidate coordinates.
      6. Repeated release cannot create duplicates.
    """
    target = session_state.get("selected_target")
    if not target:
        if payload and payload.lat is not None and payload.lon is not None:
            target = {"lat": payload.lat, "lon": payload.lon}
        else:
            raise HTTPException(400, "Cannot release: No target candidate selected.")

    if session_state.get("deployment_released", False):
        raise HTTPException(
            400,
            "Node already released for this candidate. Repeated release is prohibited.",
        )

    uav_state = mav_manager.get_vehicle_state()
    rel_alt = uav_state.get("relative_altitude")
    raw_alt = rel_alt if rel_alt is not None else uav_state.get("altitude")
    normalized_altitude = max(0.0, raw_alt) if raw_alt is not None else 0.0

    in_air = uav_state.get("in_air")
    landed_state = uav_state.get("landed_state")
    flight_mode = str(uav_state.get("flight_mode") or uav_state.get("mode") or "").upper()
    mission_state = session_state.get("mission_state", "IDLE")

    if in_air is True:
        is_airborne = True
    elif in_air is False:
        is_airborne = False if normalized_altitude <= 1.0 else True
    elif landed_state is not None:
        if landed_state == "ON_GROUND":
            is_airborne = False if normalized_altitude <= 1.0 else True
        else:
            is_airborne = True
    else:
        is_airborne = normalized_altitude > 1.0

    is_landed = (not is_airborne) and (normalized_altitude <= 1.0)
    is_aborted = mission_state in ("ABORTED", "FAILED") or "RTL" in flight_mode

    upload_st = mav_manager.get_mission_upload_state()
    total_items = upload_st.get("items", 0)
    mreached = uav_state.get("mission_item_reached")

    dist_m = None
    within_tolerance = False
    uav_lat = uav_state.get("latitude")
    uav_lon = uav_state.get("longitude")

    if uav_lat is not None and uav_lon is not None:
        gcs_uav_lat, gcs_uav_lon = _resolve_uav_coords(float(uav_lat), float(uav_lon))
        dist_m = haversine_distance_m(gcs_uav_lat, gcs_uav_lon, target["lat"], target["lon"])
        within_tolerance = dist_m <= config.CANDIDATE_DEPLOY_TOLERANCE_M
    elif not mav_manager.is_connected():
        dist_m = 0.0
        within_tolerance = True
        is_landed = True
        is_airborne = False

    destination_reached = within_tolerance or (
        total_items > 0 and mreached is not None and mreached >= total_items - 1
    ) or (not mav_manager.is_connected())

    if destination_reached and is_landed and mission_state == "EXECUTING":
        session_state["mission_state"] = "COMPLETED"
        mission_state = "COMPLETED"

    can_release = bool(
        (not is_airborne)
        and is_landed
        and within_tolerance
        and destination_reached
        and (not is_aborted)
    )

    logger.info(
        "RELEASE CHECK:\n"
        f"in_air={str(in_air).lower() if in_air is not None else 'unknown'}\n"
        f"landed_state={landed_state or 'UNKNOWN'}\n"
        f"altitude={f'{raw_alt:.3f}m' if raw_alt is not None else 'unknown'}\n"
        f"normalized_altitude={normalized_altitude:.3f}m\n"
        f"mission_state={mission_state}\n"
        f"distance_to_candidate={f'{dist_m:.1f}m' if dist_m is not None else 'unknown'}\n"
        f"destination_reached={str(destination_reached).lower()}\n"
        f"already_released=false\n"
        f"can_release={str(can_release).lower()}"
    )

    if is_aborted:
        raise HTTPException(
            400,
            f"RELEASE disabled: Deployment mission was aborted or entered RTL (state={mission_state}, mode={flight_mode}).",
        )

    if is_airborne:
        alt_str = f"{raw_alt:.3f}m" if raw_alt is not None else "airborne"
        raise HTTPException(
            400,
            f"RELEASE disabled: UAV is airborne (alt={alt_str}, in_air={in_air}, landed_state={landed_state}).",
        )

    if not within_tolerance:
        dist_str = f"{dist_m:.1f}m" if dist_m is not None else "unknown"
        raise HTTPException(
            400,
            f"RELEASE disabled: UAV landed off-target ({dist_str} > {config.CANDIDATE_DEPLOY_TOLERANCE_M}m tolerance).",
        )

    if not destination_reached:
        raise HTTPException(
            400,
            "RELEASE disabled: Deployment destination has not been reached.",
        )

    if not is_landed:
        raise HTTPException(
            400,
            f"RELEASE disabled: UAV is not landed (normalized_alt={normalized_altitude:.2f}m).",
        )

    existing = list_nodes()
    for ex in existing:
        dist_to_ex = haversine_distance_m(target["lat"], target["lon"], ex["lat"], ex["lon"])
        if dist_to_ex < 1.0:
            raise HTTPException(
                400,
                f"Node '{ex['id']}' already exists at this candidate position. Cannot create duplicate.",
            )

    node_id = f"COMM-{len(existing) + 1:03d}"
    cov_radius = (payload.coverage_radius_m if payload and payload.coverage_radius_m else None) or config.COVERAGE_RADIUS_DEFAULT_M
    created = insert_node(
        node_id=node_id,
        lat=target["lat"],
        lon=target["lon"],
        coverage_radius_m=cov_radius,
    )
    if not created:
        raise HTTPException(500, "Failed to insert node into database.")

    rf_collector = get_rf_collector()
    rf_collector.update_deployed_nodes(list_nodes())

    session_state["deployment_released"] = True
    session_state["rf_newly_deployed_node_id"] = created["id"]
    if session_state.get("rf_before_analysis"):
        session_state["rf_phase6_state"] = "NODE_DEPLOYED"

    logger.info(
        f"Deployment RELEASE successful: Node {created['id']} deployed at ({created['lat']}, {created['lon']}). "
        f"Phase 6 state: {session_state.get('rf_phase6_state')}"
    )
    return NodeOut(**created)


@app.websocket("/ws/rf-survey")
async def ws_rf_survey(websocket: WebSocket):
    """WebSocket endpoint for real-time RF survey sample streaming.

    On connect, immediately sends the current full survey dataset (so
    Simulink gets a complete picture from the first message). Thereafter,
    each new sample collected during an active scan is pushed as it arrives.

    Message format:
        {"type": "rf_survey_data", "state": ..., "sample_count": ...,
         "samples": [...], "scan_start_position": {...},
         "affected_area": [...], "deployed_nodes": [...]}

    or for individual new samples:
        {"type": "rf_survey_sample", "sample": {...}}
    """
    import asyncio
    import queue as _queue

    await websocket.accept()
    logger.info("RF survey WebSocket client connected.")

    # Queue that the collector's callback posts new samples into.
    # The asyncio event loop then drains it.
    sample_q: _queue.SimpleQueue = _queue.SimpleQueue()

    def _on_new_sample(sample: dict):
        sample_q.put_nowait(sample)

    rf_collector = get_rf_collector()
    rf_collector.subscribe(_on_new_sample)

    try:
        # Send the current complete dataset immediately on connect.
        await websocket.send_json({
            "type": "rf_survey_data",
            **rf_collector.get_survey_data(),
        })

        # Drain incoming websocket messages (disconnect detection) while also
        # forwarding new samples from the collector's callback.
        loop = asyncio.get_event_loop()
        while True:
            # Check for new samples (non-blocking) and forward them.
            forwarded = 0
            while not sample_q.empty():
                try:
                    sample = sample_q.get_nowait()
                    await websocket.send_json({
                        "type": "rf_survey_sample",
                        "sample": sample,
                        "state": rf_collector.get_state(),
                    })
                    forwarded += 1
                except _queue.Empty:
                    break

            # Wait briefly for the next message / disconnect from the client.
            try:
                msg = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=0.1,  # 100 ms — keeps forwarding at up to 10 Hz
                )
                if msg.get("type") == "websocket.disconnect":
                    break
            except asyncio.TimeoutError:
                pass  # normal; just loop again

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"RF survey WebSocket error: {e}")
    finally:
        rf_collector.unsubscribe(_on_new_sample)
        logger.info("RF survey WebSocket client disconnected.")


# ---------------------------------------------------------------------------
# Telemetry (Phase 7) — live vehicle-state stream.
#
# telemetry_broadcaster reads mav_manager.get_vehicle_state() on a timer
# and fans it out to every connected client; this handler just registers/
# unregisters the socket and pushes one immediate snapshot on connect so
# the frontend doesn't wait for the next tick to see current state.
# ---------------------------------------------------------------------------


@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    await websocket.accept()
    await telemetry_broadcaster.register(websocket)

    try:
        # Initial state immediately on connect (requirement 10), rather
        # than waiting for the next broadcast tick.
        await websocket.send_json(telemetry_broadcaster.build_message())

        # This endpoint is push-only from the server's side. Block here so
        # we're notified the moment the client disconnects, without
        # polling or touching MAVLink from this coroutine.
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

    except WebSocketDisconnect:
        pass
    finally:
        await telemetry_broadcaster.unregister(websocket)


# ---------------------------------------------------------------------------
# Static frontend + data serving (so the whole app runs from one origin)
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/frontend/index.html")


app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
