"""
Phase 5 — Pydantic request/response models for the FastAPI backend.

Kept separate from main.py so the API's data shapes are visible at a
glance, and so main.py itself stays focused on routing/orchestration.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class LatLon(BaseModel):
    lat: float
    lon: float


class NodeOut(BaseModel):
    id: str
    lat: float
    lon: float
    coverage_radius_m: Optional[float] = 250.0


class StatusResponse(BaseModel):
    status: str
    phase: int
    mission_state: str
    uav_connected: bool
    link_state: str  # DISCONNECTED | CONNECTING | CONNECTED | HEARTBEAT_LOST
    area_defined: bool
    last_analysis_available: bool


class VehicleStateOut(BaseModel):
    connected: bool
    armed: bool
    mode: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    altitude: Optional[float]
    relative_altitude: Optional[float]
    ground_speed: Optional[float]
    heading: Optional[float]
    battery: Optional[float]
    gps_fix: Optional[str]
    satellites: Optional[int]
    last_heartbeat: Optional[float]
    # Phase 8 — mission progress (None when no mission is executing)
    mission_current: Optional[int] = None
    mission_item_reached: Optional[int] = None


class TelemetryMessage(BaseModel):
    """Phase 7 — one /ws/telemetry push. Wraps the same VehicleStateOut
    shape used by GET /api/vehicle/state so REST polling and the
    WebSocket stream agree on field names/types."""

    type: str = "telemetry"
    timestamp: float
    vehicle: VehicleStateOut


class AreaRequest(BaseModel):
    polygon: List[LatLon] = Field(..., min_length=3)


class AreaResponse(BaseModel):
    accepted: bool
    point_count: int
    polygon: List[LatLon]


class AnalyzeResponse(BaseModel):
    total_points: int
    covered_points: List[LatLon]
    gap_points: List[LatLon]
    coverage_percentage: float
    gap_percentage: float


class CandidateOut(BaseModel):
    lat: float
    lon: float
    cluster_size: int
    coverage_improvement_pct: float
    distance_to_home_m: float
    boundary_distance_m: float
    coverage_score: float
    distance_score: float
    suitability_score: float
    score: float


class CandidatesResponse(BaseModel):
    candidates: List[CandidateOut]
    top: List[CandidateOut]


class SelectTargetRequest(BaseModel):
    lat: float
    lon: float


class SelectTargetResponse(BaseModel):
    accepted: bool
    lat: float
    lon: float
    matched_candidate: bool


class MissionGenerateRequest(BaseModel):
    lat: float
    lon: float
    altitude_m: Optional[float] = None


class MissionOut(BaseModel):
    id: int
    created_at: str
    target_lat: float
    target_lon: float
    target_alt: float
    score: Optional[float]
    status: str


class DeploymentOut(BaseModel):
    id: int
    mission_id: Optional[int]
    node_id: Optional[str]
    lat: float
    lon: float
    timestamp: str
    status: str


class NotImplementedResponse(BaseModel):
    implemented: bool = False
    phase_required: int
    message: str


# ---------------------------------------------------------------------------
# Phase 8 — mission upload / execution response models
# ---------------------------------------------------------------------------


class MissionUploadResponse(BaseModel):
    """Returned by POST /api/mission/send after a real MAVLink upload."""
    success: bool
    mission_id: Optional[int] = None
    status: str                      # e.g. "uploaded", "failed", "timeout"
    items: int = 0                   # number of items accepted by PX4
    error: Optional[str] = None      # human-readable error if success=False


class MissionStartResponse(BaseModel):
    """Returned by POST /api/mission/start."""
    success: bool
    mode: Optional[str] = None
    error: Optional[str] = None


class MissionAbortResponse(BaseModel):
    """Returned by POST /api/mission/abort."""
    success: bool
    action: str = "RTL"
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase 9A — Coordinate transformation API models
# ---------------------------------------------------------------------------


class CoordinateReferencePoint(BaseModel):
    """A single lat/lon reference coordinate."""
    latitude: float
    longitude: float


class CoordinateReferenceResponse(BaseModel):
    """Returned by GET /api/coordinates/reference."""
    simulation_mode: bool
    gcs_reference: CoordinateReferencePoint
    px4_reference: CoordinateReferencePoint


class CoordinateTranslateRequest(BaseModel):
    """Input for POST /api/coordinates/translate."""
    latitude: float
    longitude: float


class CoordinateTranslateResponse(BaseModel):
    """Output of POST /api/coordinates/translate.

    All four coordinates plus the intermediate displacement so callers
    can inspect exactly what the mapper computed.
    """
    gcs_latitude:  float
    gcs_longitude: float
    px4_latitude:  float
    px4_longitude: float
    north_m:       float
    east_m:        float


class ReturnHomeResponse(BaseModel):
    """Returned by POST /api/vehicle/return-home."""
    success: bool
    action: str = "RETURN_HOME"
    home_target: Optional[CoordinateReferencePoint] = None
    items: Optional[int] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Manual Control — velocity override models
# ---------------------------------------------------------------------------


class ManualVelocityRequest(BaseModel):
    """Body for POST /api/vehicle/manual-velocity.

    All velocities are in the MAV_FRAME_LOCAL_NED frame:
      vx  : forward/back  m/s  (+North, -South)
      vy  : right/left    m/s  (+East,  -West)
      vz  : up/down       m/s  (+Down,  -Up)   — caller must negate for intuitive input
      yaw_rate : rad/s, positive = clockwise
    """
    vx: float
    vy: float
    vz: float
    yaw_rate: float


class ManualVelocityResponse(BaseModel):
    """Returned by POST /api/vehicle/manual-velocity."""
    success: bool
    error: Optional[str] = None


class ManualControlResponse(BaseModel):
    """Returned by POST /api/vehicle/manual-control and POST /api/vehicle/resume-mission."""
    success: bool
    mode: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase 2 — RF Scan survey mission models
# ---------------------------------------------------------------------------


class RFScanWaypoint(BaseModel):
    seq: int
    lat: float
    lon: float
    alt: float
    line_idx: Optional[int] = None


class RFScanGenerateRequest(BaseModel):
    polygon: Optional[List[LatLon]] = None
    spacing_m: Optional[float] = 25.0
    altitude_m: Optional[float] = 15.0


class RFScanGenerateResponse(BaseModel):
    success: bool
    state: str
    total_distance_m: float
    waypoint_count: int
    line_count: int
    spacing_m: float
    altitude_m: float
    waypoints: List[RFScanWaypoint]
    px4_waypoints: List[RFScanWaypoint]
    error: Optional[str] = None

