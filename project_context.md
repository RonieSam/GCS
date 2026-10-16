# UAV Emergency Deployment Ground Control Station (GCS) - Detailed Project Context

## 1. Project Overview
The UAV Emergency Deployment Ground Control Station (GCS) is an end-to-end software and hardware ecosystem designed to facilitate emergency communication network restoration. Using an unmanned aerial vehicle (UAV), the GCS conducts automated Radio Frequency (RF) surveys to map out coverage gaps in an emergency zone. It then calculates optimal candidate locations for deploying physical relay nodes and coordinates the UAV to autonomously fly and deploy these nodes to restore connectivity.

---

## 2. Hardware Implementation Status
- **Hardware Integration**: The physical hardware for the drone and the node payload release mechanism has been **fully implemented**.
- **GCS Control**: The drone is actively controllable directly from the GCS interface. MAVLink communication, telemetry parsing, and command execution (arming, disarming, manual override, mission upload) are all functional.
- **Pending Tasks**: The only remaining tasks for the hardware are **final calibrations** and **live physical delivery testing** (deploying actual nodes in a test environment).

---

## 3. Technology Stack and Implementation Details

### A. Frontend (User Interface)
The frontend is a custom-built, premium operational interface constructed purely with vanilla web technologies to ensure lightweight performance and full control over the UI state.
- **Technologies Used**: HTML5, Vanilla CSS3 (custom variables, responsive flex/grid layouts), Vanilla JavaScript (ES6+), Leaflet.js.
- **Core Files**:
  - `index.html`: Defines the layout, categorizing workflows into four distinct tabs (MISSION, RF, DEPLOY, HISTORY). It houses the Leaflet map container and various UI overlays (layer toggles, RF legends, area stats).
  - `style.css`: Contains an extensive, human-crafted design system implementing a dark-themed, glassmorphic, and highly professional layout. It includes micro-animations and robust CSS grid/flex structures.
  - `app.js`: The monolithic frontend controller managing map initialization, Leaflet overlays, API polling, WebSocket telemetry streams, and DOM event handling for all user interactions.
- **Key Frontend Features**:
  - **Leaflet Integration**: Uses custom `L.marker`, `L.polygon`, and `L.featureGroup` to render the UAV position, mission routes, deployed nodes, candidate locations, and RF heatmaps.
  - **Telemetry WebSocket**: Listens to `/ws/telemetry` for high-frequency updates, updating the HUD and UAV marker position smoothly.
  - **Historical Viewer**: A robust side-by-side comparative UI allowing operators to evaluate RF heatmaps from before and after node deployments.

### B. Backend (Server and Coordination)
The backend is the brain of the operation, providing APIs, maintaining state, and talking to the drone.
- **Technologies Used**: Python 3, FastAPI, Uvicorn (ASGI server), SQLite (via standard library), `pymavlink` (for UAV communication).
- **Core Modules**:
  - `main.py`: The FastAPI application entry point. Contains REST API endpoints for mission planning, execution, and deployment logic. Houses the critical **Deployment Release Gate** state machine ensuring nodes are only dropped when the UAV is safely landed at the target destination.
  - `mavlink_manager.py` & `mavlink_telemetry.py`: Manage the MAVLink connection to the UAV (via UDP to SITL/Gazebo or real hardware). They handle heartbeat parsing, state decoding (armed, flight mode, landed state), and dispatching telemetry to the WebSocket.
  - `mavlink_commands.py` & `mavlink_mission.py`: Construct and transmit MAVLink command packets (e.g., `MAV_CMD_COMPONENT_ARM_DISARM`, `MAV_CMD_NAV_WAYPOINT`) and handle the complex mission upload protocols.
  - `rf_collector.py` & `rf_survey_analyzer.py`: Handle the ingestion of RF data points, mapping them geographically, generating heatmap representations, and running algorithms to classify signal strength (GOOD, MODERATE, WEAK, GAP).
  - `candidate_generator.py` & `survey_planner.py`: Analyze coverage gaps to propose optimal geographical candidates for node placement, and automatically calculate lawnmower/survey flight paths over defined polygons.
  - `telemetry_broadcaster.py`: Manages asynchronous WebSocket connections to broadcast live UAV data to the browser.
- **Database (`uav_emergency.db`)**: A SQLite database storing historical RF surveys, node deployment records, and mission logs, enabling the Before/After verification workflows.

### C. Simulink and MATLAB Environment (`emergency_simu`)
The project utilizes a rich simulation environment built in MATLAB and Simulink to model the physical and RF dynamics before transitioning to the Python/FastAPI GCS.
- **Simulink Model (`EmergencyNetwork.slx`)**: Simulates the UAV dynamics, network connectivity, and node behavior within an emergency scenario.
- **MATLAB Functions (`emergency_simu/functions/`)**:
  - `RFModel.m` & `CoverageMap.m`: Mathematical models to simulate signal propagation, path loss, and coverage areas for the simulation.
  - `GapDetector.m` & `CandidatePlacement.m`: The algorithmic prototypes for identifying RF gaps and calculating optimal node placement coordinates. These models informed the Python backend's candidate generation logic.
  - `GCSDroneSurvey.m` & `DroneSurvey.m`: Scripts to simulate the drone flying a survey path and collecting RF data points, mimicking the real-world behavior the Python backend receives.
  - `CoverageClassifier.m`, `CoverageComparison.m`, `GapVisualizer.m`: Tools to classify the simulated RF data into discrete tiers and visualize the network improvements within the MATLAB environment.
- **Purpose**: The Simulink environment serves as the algorithm design and validation testbed. The proven logic (RF modeling, gap detection, candidate placement) is then translated to the Python backend to run against live MAVLink telemetry and real-world hardware.

---

## 4. Operational Workflow
1. **Define Area**: Operator draws a polygon on the GCS map encompassing the emergency zone.
2. **Plan & Execute Survey**: The backend calculates a survey grid. The UAV is armed and commanded to fly the route, constantly reporting RF data.
3. **Analyze**: The backend processes the RF data, rendering a heatmap and identifying candidate locations for node deployment in coverage gaps.
4. **Deploy Node**: Operator selects a candidate, generating a targeted flight mission. The UAV flies to the coordinates, lands, and the GCS enforces a strict telemetry-based safety gate (verifying altitude, position, and landed state) before enabling the physical payload release.
5. **Verify**: A post-deployment "After" survey is flown. The GCS compares the historical "Before" survey with the "After" survey side-by-side to quantify the coverage improvement.
