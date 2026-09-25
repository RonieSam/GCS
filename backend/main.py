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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional

import config
from candidate_generator import generate_candidates
from coverage import compute_coverage, haversine_distance_m, point_in_polygon
from database import (
    get_mission,
    init_db,
    insert_mission,
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
}

_CANDIDATE_MATCH_TOLERANCE_M = 1.0  # treat as "the same point" within this radius


@app.on_event("startup")
async def on_startup():
    init_db()
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

    try:
        result = survey_planner.generate_survey_path(
            polygon,
            spacing_m=spacing_m,
            altitude_m=altitude_m,
        )
    except ValueError as e:
        session_state["rf_scan_state"] = "FAILED"
        raise HTTPException(400, str(e))

    session_state["rf_scan_state"] = "MISSION_GENERATED"
    session_state["rf_scan_mission"] = result

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

    try:
        mav_manager.send_command("set_mode", mode="MISSION")
        session_state["mission_state"] = "EXECUTING"
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
    """Abort the active mission by commanding PX4 into Return-to-Launch mode.

    RTL is the safest abort action available: PX4 returns to home and
    lands. Does not automatically disarm.
    """
    if not mav_manager.is_connected():
        raise HTTPException(
            503,
            "PX4 is not connected. Cannot send abort/RTL command.",
        )

    try:
        mav_manager.send_command("set_mode", mode="RTL")
        session_state["mission_state"] = "ABORTED"
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
