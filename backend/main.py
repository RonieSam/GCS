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
import mavlink_commands   # NEW import, alongside the mavlink_manager import
import mavlink_mission    # Phase 8 — MAVLink mission protocol

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from typing import List

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
    DeploymentOut,
    LatLon,
    MissionAbortResponse,
    MissionGenerateRequest,
    MissionOut,
    MissionStartResponse,
    MissionUploadResponse,
    NodeOut,
    NotImplementedResponse,
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
    try:
        mav_manager.send_command("arm")
        return {"success": True, "command": "arm"}
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/vehicle/disarm")
def api_vehicle_disarm():
    try:
        mav_manager.send_command("disarm")
        return {"success": True, "command": "disarm"}
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
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

    # Validate coordinates before trying the upload.
    try:
        items = mavlink_mission.build_mission_items(lat, lon, alt)
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
