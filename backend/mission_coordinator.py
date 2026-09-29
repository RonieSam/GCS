import uuid
import time
from typing import Optional, Dict, Any
from .models import LatLon
import logging

logger = logging.getLogger(__name__)

class MissionCoordinator:
    def __init__(self):
        self.current_mission_id: Optional[str] = None
        self.current_mission_type: Optional[str] = None
        self.current_mission_state: str = "IDLE"
        self.target_destination: Optional[LatLon] = None
        self.destination_reached: bool = False
        self.release_ready: bool = False
        self.release_state: str = "NOT_READY"
        self.rf_collector_session_id: Optional[str] = None
        
        # Tracking telemetry state separately
        self.physical_state: str = "UNKNOWN"
        self.last_altitude: float = 0.0
        self.last_in_air: bool = False
        self.last_landed_state: str = "UNKNOWN"
        
        # History
        self.mission_history = []
        self.rf_survey_history = []
        
    def generate_mission(self, mission_type: str, target: Optional[LatLon] = None) -> str:
        # Save previous mission to history if it was active
        if self.current_mission_id and self.current_mission_state not in ("IDLE", "DRAFT"):
            self.mission_history.append({
                "id": self.current_mission_id,
                "type": self.current_mission_type,
                "state": self.current_mission_state,
                "target": self.target_destination
            })
            
        self.current_mission_id = f"{mission_type}-{uuid.uuid4().hex[:8].upper()}"
        self.current_mission_type = mission_type
        self.current_mission_state = "GENERATED"
        self.target_destination = target
        
        # Reset latched flags
        self.destination_reached = False
        self.release_ready = False
        self.release_state = "NOT_READY"
        
        if mission_type == "RF_SURVEY":
            self.rf_collector_session_id = f"RF-COLLECT-{uuid.uuid4().hex[:8].upper()}"
            
        return self.current_mission_id
