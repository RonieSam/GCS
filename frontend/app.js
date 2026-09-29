/* ==========================================================================
   UAV Emergency Deployment — GCS, Phase 5
   Scope: everything from Phases 1-4, now wired to the real FastAPI backend
   (backend/main.py) instead of the Phase 1 "not implemented yet" placeholder.
   Analyze Area -> POST /api/area, POST /api/analyze, GET /api/candidates ->
   real coverage %, gap %, and a scored, ranked top-2 recommendation.
   Select A/B -> POST /api/select-target. Generate Mission ->
   POST /api/mission/generate (persisted to SQLite). Send Target ->
   POST /api/mission/send, which is an honest 501 until Phase 6 builds the
   MAVLink connection — that response is logged, not hidden.
   ========================================================================== */

const NODES_URL = "/api/nodes";

// Generic synthetic test-area center (used if node data can't be loaded).
const FALLBACK_CENTER = { lat: 13.0827, lon: 80.2707 };

// Rendering every sampled grid point (can be 10,000+ for a large affected
// area) would noticeably lag the browser. The coverage/gap PERCENTAGES
// shown in the stats panel are always exact (computed server-side over the
// full grid) — only the on-map dot overlay is downsampled for display
// performance. This cap is a rendering choice, not an analysis shortcut.
const MAX_RENDERED_POINTS_PER_LAYER = 400;

const state = {
  drawing: false,           // true while "Draw Affected Area" is active
  points: [],               // array of {lat, lon} for the polygon being drawn
  vertexMarkers: [],        // Leaflet markers for each clicked point
  drawLine: null,           // Leaflet polyline connecting points while drawing
  areaPolygon: null,        // Leaflet polygon once the area is finished
  areaClosed: false,        // true once the polygon has been finished

  // Phase 1 — node state
  // availableNodes: node definitions loaded from the backend (inventory).
  //   These are NOT drawn until the operator presses AUTO DEPLOY INITIAL NODES.
  // deployedNodes:  nodes that have been logically placed on the map.
  //   Starts empty. Grows when the operator deploys nodes (initial or new).
  // nodeLayerGroup: Leaflet LayerGroup holding all deployed-node markers/rings.
  //   Using a LayerGroup means we can add to it later without touching existing
  //   markers (Node 1-3 stay when Node 4 is added).
  availableNodes: [],       // node definitions fetched from /api/nodes
  deployedNodes: [],        // nodes actually rendered on the map
  nodeLayerGroup: null,     // Leaflet LayerGroup for deployed-node markers

  // Node deployment selection — single source of truth for what AUTO DEPLOY will place.
  // selectedDeploymentLocation: {lat, lon, source} where source = 'map' | 'candidate'
  // deploymentSelectionMarker: temporary Leaflet marker shown while location is chosen
  selectedDeploymentLocation: null,
  deploymentSelectionMarker: null,

  gapLayer: null,           // LayerGroup of (downsampled) gap-point dots
  coveredLayer: null,       // LayerGroup of (downsampled) covered-point dots
  candidateLayer: null,     // LayerGroup of candidate markers
  topMarkers: {},           // candidate key -> Leaflet marker, for the top 2
  selectedMarker: null,     // highlighted marker for the chosen target

  candidates: [],           // last GET /api/candidates "candidates" array
  top: [],                  // last GET /api/candidates "top" array
  selectedTarget: null,     // {lat, lon} once Select A/B has been clicked

  // Phase 7 — live telemetry
  telemetryWs: null,        // current WebSocket, or null while disconnected
  telemetrySocketOpen: false,   // WebSocket itself connected to the backend
  vehicle: null,             // last "vehicle" object received over /ws/telemetry
  lastTelemetryAt: 0,        // ms timestamp telemetry was last received (Date.now())
  telemetryReconnectTimer: null,
  uavMarker: null,           // Leaflet marker for the live UAV position

  // Phase 8 — mission lifecycle
  missionGenerated: false,   // true after Generate Mission succeeded
  missionUploaded: false,    // true after Upload Mission succeeded (PX4 ACK)
  missionExecuting: false,   // true after Start Mission commanded
  missionCompleted: false,   // true after autonomous mission has reached final waypoint/landed
  returningHome: false,      // true while return-home mission is in flight
  returnCompleted: false,    // true after UAV has completed return flight and landed at home
  lastMissionId: null,       // SQLite id of last generated mission
  lastMissionItems: 0,       // number of items PX4 accepted

  // Manual override (gamepad)
  manualControl: {
    active: false,          // true = currently in POSCTL manual override
    gamepadIndex: null,     // index in navigator.getGamepads() of connected controller
    sendTimer: null,        // setInterval handle for 20 Hz velocity loop
    lastLogError: 0,        // throttle console error spam from velocity POST failures
  },

  // Phase 2 — RF scan survey
  rfScanState: "IDLE",       // IDLE | MISSION_GENERATED | MISSION_UPLOADED | RUNNING | COMPLETED | FAILED
  rfScanLayer: null,         // Leaflet LayerGroup for the survey path and waypoints
  rfScanMission: null,       // Last generated survey result object

  // Phase 5 — RF coverage heatmap + candidate generation
  rfAnalysis: null,          // last POST /api/rf-survey/analyze result object
  rfHeatmapLayer: null,      // Leaflet LayerGroup for heatmap circles
  rfGapLayer: null,          // Leaflet LayerGroup for gap-point markers
  rfCandidateLayer: null,    // Leaflet LayerGroup for RF candidate markers
  rfHeatmapVisible: true,
  rfGapVisible: true,
  rfCandidatesVisible: true,
  rfHeatmapOpacity: 0.55,    // 0.10 – 0.90
  rfAnalysisAutoTriggered: false,

  // Phase 6 — Re-Scan & Before/After Verification
  rfPhase6State: "BEFORE_SURVEY",
  rfBeforeAnalysis: null,
  rfAfterAnalysis: null,
  rfComparison: null,
  newlyDeployedNodeId: null,
  activeHeatmapView: "AFTER",
  rfBeforeHeatmapLayer: null,
  deploymentReleased: false,
  surveyHistory: [],
  rfHistoricalLayer: null,
};

// A message every ~1/MAVLINK stream rate is expected; if nothing arrives
// for a few multiples of that, treat the picture as stale rather than
// silently keep showing the last-known values as if they were current.
const TELEMETRY_STALE_MS = 2500;
const TELEMETRY_STALE_CHECK_MS = 500;
const TELEMETRY_RECONNECT_MS = 2000;

let map;
let canvasRenderer;
let usingFallbackTiles = false;

// ---------------------------------------------------------------------------
// Log panel
// ---------------------------------------------------------------------------

function logEvent(message) {
  const body = document.getElementById("log-body");
  const line = document.createElement("div");
  line.className = "log-line";

  const now = new Date();
  const time = now.toTimeString().slice(0, 8);

  const timeSpan = document.createElement("span");
  timeSpan.className = "log-time";
  timeSpan.textContent = `[${time}]`;

  line.appendChild(timeSpan);
  line.appendChild(document.createTextNode(message));

  body.appendChild(line);
  body.scrollTop = body.scrollHeight;
}

// ---------------------------------------------------------------------------
// Small API helpers
// ---------------------------------------------------------------------------

async function apiGet(path) {
  const res = await fetch(path);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
}

async function apiPost(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const body = await res.json().catch(() => null);
  // Callers that need to distinguish "honest 501 stub" from a real error
  // (e.g. Send Target) check res.status/body themselves via apiPostRaw.
  if (!res.ok && res.status !== 501) {
    const detail = body && body.detail ? body.detail : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return { status: res.status, body };
}

async function apiDelete(path) {
  const res = await fetch(path, { method: "DELETE" });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
}

// ---------------------------------------------------------------------------
// Map setup, with schematic fallback if tile imagery can't load
// ---------------------------------------------------------------------------

function initMap(centerLat, centerLon) {
  map = L.map("map", {
    zoomControl: true,
    attributionControl: true,
  }).setView([centerLat, centerLon], 16);

  canvasRenderer = L.canvas({ padding: 0.5 });

  const osmLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  });

  let tileErrorCount = 0;
  osmLayer.on("tileerror", () => {
    tileErrorCount += 1;
    // A handful of missed tiles is normal at map edges; only fall back
    // once it's clear tile imagery genuinely isn't reachable.
    if (tileErrorCount > 6 && !usingFallbackTiles) {
      enableFallbackBasemap();
    }
  });

  osmLayer.addTo(map);

  map.on("click", onMapClick);

  return map;
}

function enableFallbackBasemap() {
  usingFallbackTiles = true;
  map.eachLayer((layer) => {
    if (layer instanceof L.TileLayer) map.removeLayer(layer);
  });
  // Schematic fallback: no imagery dependency, just a coordinate grid so
  // drawing and analysis remain fully usable offline.
  document.getElementById("map").style.background =
    "repeating-linear-gradient(0deg, #10151b, #10151b 39px, #1c232b 40px), " +
    "repeating-linear-gradient(90deg, #10151b, #10151b 39px, #1c232b 40px)";
  document.getElementById("map-fallback-banner").classList.remove("hidden");
  logEvent("Map tiles unavailable — switched to schematic fallback grid.");
}

// ---------------------------------------------------------------------------
// Node display & deployment (Phase 4 — dynamic nodes, deletion & scaled RF range)
// ---------------------------------------------------------------------------

// Phase 4 Final: calibrate RF range to 3/10 of default range (0.30)
const RF_RANGE_SCALE = 0.30;

/**
 * loadNodes — fetches currently deployed node definitions from the backend.
 * Populates frontend state and renders all persisted nodes on the map.
 */
async function loadNodes() {
  try {
    const nodes = await apiGet(NODES_URL);
    state.availableNodes = nodes || [];
    if (state.nodeLayerGroup) {
      state.nodeLayerGroup.clearLayers();
    }
    state.deployedNodes = [];
    if (Array.isArray(nodes) && nodes.length > 0) {
      nodes.forEach((n) => {
        addDeployedNode(n);
        const match = (n.id || "").match(/\d+/);
        if (match) {
          const seqNum = parseInt(match[0], 10);
          if (!isNaN(seqNum) && seqNum > _deployNodeSeq) {
            _deployNodeSeq = seqNum;
          }
        }
      });
    }
  } catch (err) {
    logEvent(`Could not load nodes from ${NODES_URL} (${err.message})`);
    state.availableNodes = [];
    state.deployedNodes = [];
  }
  updateNodeUI();
  return state.deployedNodes;
}

/**
 * Canonical helper to normalize and validate geographical coordinates.
 * Returns { latitude: number, longitude: number } if valid, or null.
 */
function normalizeCoordinates(latInput, lonInput) {
  if (latInput == null || lonInput == null) return null;
  const lat = typeof latInput === "number" ? latInput : parseFloat(latInput);
  const lon = typeof lonInput === "number" ? lonInput : parseFloat(lonInput);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return { latitude: lat, longitude: lon };
}

/**
 * addDeployedNode — renders a single node onto the shared nodeLayerGroup
 * and appends it to state.deployedNodes if not already present.
 */
function addDeployedNode(node) {
  if (!node) return;
  const coords = normalizeCoordinates(node.lat ?? node.latitude, node.lon ?? node.longitude);
  if (!coords) {
    console.error("addDeployedNode received invalid coordinates:", node);
    return;
  }
  node.lat = coords.latitude;
  node.lon = coords.longitude;

  if (!state.nodeLayerGroup) {
    state.nodeLayerGroup = L.layerGroup().addTo(map);
  }

  // Prevent duplicate visual markers
  if (node._marker && state.nodeLayerGroup.hasLayer(node._marker)) {
    return;
  }

  const isNewlyDeployed = Boolean(state.newlyDeployedNodeId && node.id === state.newlyDeployedNodeId);
  const nodeColor = isNewlyDeployed ? "#00E5FF" : "#3FDA7F";
  const markerRadius = isNewlyDeployed ? 9 : 7;
  const markerWeight = isNewlyDeployed ? 3 : 2;
  const labelClass = isNewlyDeployed ? "node-label node-label-new" : "node-label";
  const tooltipText = isNewlyDeployed ? `${node.id} [NEWLY DEPLOYED]` : node.id;

  const marker = L.circleMarker([node.lat, node.lon], {
    radius: markerRadius,
    color: nodeColor,
    fillColor: nodeColor,
    fillOpacity: 0.95,
    weight: markerWeight,
  }).addTo(state.nodeLayerGroup);

  marker.bindTooltip(tooltipText, {
    permanent: true,
    direction: "top",
    offset: [0, -7],
    className: labelClass,
  });

  const scaledRadius = (node.coverage_radius_m || 250) * RF_RANGE_SCALE;

  const circle = L.circle([node.lat, node.lon], {
    radius: scaledRadius,
    color: nodeColor,
    weight: isNewlyDeployed ? 2 : 1.5,
    fillColor: nodeColor,
    fillOpacity: isNewlyDeployed ? 0.12 : 0.08,
    dashArray: isNewlyDeployed ? "6 3" : "4 4",
  }).addTo(state.nodeLayerGroup);

  // Popup provides node information only; deletion is strictly via the Nodes sidebar
  marker.bindPopup(`
    <div style="font-family: inherit; font-size: 13px; min-width: 150px; line-height: 1.5;">
      <strong style="color: ${nodeColor};">${node.id}${isNewlyDeployed ? " [NEWLY DEPLOYED]" : ""}</strong><br/>
      <span style="color: #aaa; font-size: 11px;">Lat: ${node.lat.toFixed(5)}<br/>Lon: ${node.lon.toFixed(5)}<br/>Coverage: ${Math.round(scaledRadius)} m (scaled 0.30)</span>
    </div>
  `);

  node._marker = marker;
  node._circle = circle;

  if (!state.deployedNodes.some((n) => n.id === node.id)) {
    state.deployedNodes.push(node);
  }

  updateNodeUI();
}

/**
 * Re-render all deployed nodes (e.g. when newlyDeployedNodeId changes).
 */
function renderAllDeployedNodes() {
  if (state.nodeLayerGroup) {
    state.nodeLayerGroup.clearLayers();
  }
  const nodes = [...state.deployedNodes];
  state.deployedNodes = [];
  nodes.forEach((n) => {
    n._marker = null;
    n._circle = null;
    addDeployedNode(n);
  });
}

/**
 * updateNodeUI — syncs stat counters and the Manage Deployed Nodes dropdown.
 */
function updateNodeUI() {
  const countEl = document.getElementById("stat-deployed-count");
  if (countEl) countEl.textContent = state.deployedNodes.length;

  const nodesEl = document.getElementById("stat-nodes");
  if (nodesEl) nodesEl.textContent = state.deployedNodes.length;

  const rfsNodesEl = document.getElementById("stat-rfs-nodes");
  if (rfsNodesEl) rfsNodesEl.textContent = state.deployedNodes.length;

  const selectEl = document.getElementById("select-delete-node");
  const deleteBtn = document.getElementById("btn-delete-node");
  if (selectEl) {
    selectEl.innerHTML = "";
    if (state.deployedNodes.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(No nodes deployed)";
      selectEl.appendChild(opt);
      if (deleteBtn) deleteBtn.disabled = true;
    } else {
      state.deployedNodes.forEach((n) => {
        const opt = document.createElement("option");
        opt.value = n.id;
        opt.textContent = `${n.id} (${n.lat.toFixed(4)}, ${n.lon.toFixed(4)})`;
        selectEl.appendChild(opt);
      });
      if (deleteBtn) deleteBtn.disabled = false;
    }
  }
}

/**
 * deleteDeployedNode — deletes a deployed node from backend, GCS state, and map.
 */
async function deleteDeployedNode(nodeId) {
  if (!nodeId) return;
  try {
    await apiDelete(`/api/nodes/${encodeURIComponent(nodeId)}`);
    const node = state.deployedNodes.find((n) => n.id === nodeId);
    if (node) {
      if (node._marker && state.nodeLayerGroup) state.nodeLayerGroup.removeLayer(node._marker);
      if (node._circle && state.nodeLayerGroup) state.nodeLayerGroup.removeLayer(node._circle);
    }
    state.deployedNodes = state.deployedNodes.filter((n) => n.id !== nodeId);
    updateNodeUI();
    logEvent(`Node ${nodeId} deleted. Active deployed nodes: ${state.deployedNodes.length}.`);
  } catch (err) {
    logEvent(`Failed to delete node ${nodeId}: ${err.message}`);
  }
}
window.deleteDeployedNode = deleteDeployedNode;

/**
 * selectDeploymentLocation — single shared entry point for setting the
 * pending deployment location, regardless of whether it came from a direct
 * map click or a candidate selection.
 */
function selectDeploymentLocation(latInput, lonInput, source) {
  const coords = normalizeCoordinates(latInput, lonInput);
  if (!coords) {
    logEvent(`AUTO DEPLOY: rejected invalid selection coordinates (${latInput}, ${lonInput})`);
    return;
  }
  const { latitude, longitude } = coords;
  const src = source || "map";

  // Single canonical selected location object
  state.selectedLocation = { latitude, longitude, source: src };
  state.selectedDeploymentLocation = { lat: latitude, lon: longitude, source: src };

  // Show / move the temporary selection marker (cyan crosshair ring)
  if (state.deploymentSelectionMarker) {
    state.deploymentSelectionMarker.setLatLng([latitude, longitude]);
  } else {
    state.deploymentSelectionMarker = L.circleMarker([latitude, longitude], {
      radius: 10,
      color: "#00E5FF",
      fillColor: "#00E5FF",
      fillOpacity: 0.18,
      weight: 2.5,
      dashArray: "4 3",
    }).addTo(map);
  }

  state.deploymentSelectionMarker.bindTooltip(
    `Deploy here (${src})`,
    { direction: "top", offset: [0, -10], className: "node-label" }
  ).openTooltip();

  const locText = document.getElementById("deploy-location-text");
  if (locText) locText.textContent = `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;

  const srcEl = document.getElementById("stat-deploy-source");
  if (srcEl) srcEl.textContent = src.toUpperCase();

  state.deploymentReleased = false;
  updateDeploymentReleaseButton();

  logEvent(`Deployment location selected (${src}): lat=${latitude.toFixed(5)}, lon=${longitude.toFixed(5)}`);
}

// Running counter for deployed-node IDs
let _deployNodeSeq = 0;
let _deployInProgress = false;

function haversineDistanceM(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

/**
 * Phase 6 Requirements 3-6: Deployment RELEASE interlock evaluation.
 * RELEASE must only become enabled after:
 *   - deployment mission is no longer flying
 *   - UAV is actually landed
 *   - UAV is within configured distance tolerance (10m) of selected candidate
 * If UAV lands somewhere else or is airborne, RELEASE remains disabled.
 */
function updateDeploymentReleaseButton() {
  const deployBtn = document.getElementById("btn-auto-deploy");
  const interlockEl = document.getElementById("deploy-interlock-status");
  const hintEl = document.getElementById("deploy-hint");
  if (!deployBtn) return;

  const target = state.selectedLocation || state.selectedDeploymentLocation || state.selectedTarget;
  if (!target) {
    deployBtn.disabled = true;
    if (interlockEl) interlockEl.textContent = "Select target location and land UAV to enable release.";
    return;
  }

  if (state.deploymentReleased || _deployInProgress) {
    deployBtn.disabled = true;
    if (interlockEl) interlockEl.textContent = "Node already released at target. Duplicate release blocked.";
    return;
  }

  const v = state.vehicle;
  // If telemetry vehicle is connected:
  if (v && v.connected) {
    const relAlt = v.relative_altitude;
    const isAirborne = (relAlt != null && relAlt > 0.3) || state.missionExecuting;
    const isLanded = (relAlt != null && relAlt <= 0.3) && !isAirborne;

    const targetLat = target.latitude != null ? target.latitude : target.lat;
    const targetLon = target.longitude != null ? target.longitude : target.lon;
    let distM = null;
    let withinTolerance = false;

    if (v.latitude != null && v.longitude != null && targetLat != null && targetLon != null) {
      distM = haversineDistanceM(v.latitude, v.longitude, targetLat, targetLon);
      withinTolerance = distM <= 10.0; // 10 metre candidate tolerance
    }

    if (isAirborne) {
      deployBtn.disabled = true;
      const altStr = relAlt != null ? `${relAlt.toFixed(1)}m` : "airborne";
      if (interlockEl) interlockEl.textContent = `RELEASE DISABLED: UAV is airborne (alt ${altStr}).`;
      if (hintEl) hintEl.textContent = `Release disabled: UAV is airborne (${altStr}).`;
    } else if (!isLanded) {
      deployBtn.disabled = true;
      if (interlockEl) interlockEl.textContent = "RELEASE DISABLED: UAV is not landed.";
      if (hintEl) hintEl.textContent = "Release disabled: UAV is not landed.";
    } else if (!withinTolerance) {
      deployBtn.disabled = true;
      const distStr = distM != null ? `${distM.toFixed(1)}m` : "unknown";
      if (interlockEl) interlockEl.textContent = `RELEASE DISABLED: UAV landed off-target (${distStr} > 10m tolerance).`;
      if (hintEl) hintEl.textContent = `UAV landed off-target (${distStr}). Release disabled.`;
    } else {
      deployBtn.disabled = false;
      const distStr = distM != null ? `${distM.toFixed(1)}m` : "0m";
      if (interlockEl) interlockEl.textContent = `RELEASE ENABLED: UAV landed on target (dist ${distStr}).`;
      if (hintEl) hintEl.textContent = `Landed within tolerance (${distStr}). Press AUTO DEPLOY to release communication node.`;
    }
  } else {
    // Standalone test/offline mode without live PX4 telemetry
    deployBtn.disabled = false;
    if (interlockEl) interlockEl.textContent = "Direct placement ready (offline mode).";
  }
}

/**
 * autoDeploy — releases a communication node at the selected candidate coordinates.
 * Enforces server-side interlocks via POST /api/deployment/release.
 * Guarantees exactly one node is created, and repeated release cannot create duplicates.
 */
async function autoDeploy() {
  if (_deployInProgress || state.deploymentReleased) {
    logEvent("AUTO DEPLOY blocked: node already released or release in progress.");
    return;
  }

  const sel = state.selectedLocation || state.selectedDeploymentLocation || state.selectedTarget;
  if (!sel) {
    logEvent("AUTO DEPLOY: no location selected. Click the map or pick a candidate first.");
    return;
  }

  const rawLat = sel.latitude != null ? sel.latitude : sel.lat;
  const rawLon = sel.longitude != null ? sel.longitude : sel.lon;
  const coords = normalizeCoordinates(rawLat, rawLon);

  if (!coords) {
    logEvent(`AUTO DEPLOY failed: invalid coordinates (${rawLat}, ${rawLon}).`);
    const hintEl = document.getElementById("deploy-hint");
    if (hintEl) hintEl.textContent = "Error: Invalid coordinates selected.";
    return;
  }

  const { latitude, longitude } = coords;
  _deployInProgress = true;
  const deployBtn = document.getElementById("btn-auto-deploy");
  if (deployBtn) deployBtn.disabled = true;

  try {
    const res = await apiPost("/api/deployment/release", {
      lat: latitude,
      lon: longitude,
      coverage_radius_m: 250,
    });
    const created = res && res.body ? res.body : null;
    if (res && res.status !== 200) {
      throw new Error((created && created.detail) || `Server error: HTTP ${res.status}`);
    }

    state.deploymentReleased = true;
    state.newlyDeployedNodeId = created.id;
    if (state.rfBeforeAnalysis) {
      state.rfPhase6State = "NODE_DEPLOYED";
    }

    addDeployedNode(created);
    renderAllDeployedNodes();

    if (state.deploymentSelectionMarker) {
      map.removeLayer(state.deploymentSelectionMarker);
      state.deploymentSelectionMarker = null;
    }
    state.selectedLocation = null;
    state.selectedDeploymentLocation = null;

    const locText = document.getElementById("deploy-location-text");
    if (locText) locText.textContent = "None";
    const srcEl = document.getElementById("stat-deploy-source");
    if (srcEl) srcEl.textContent = "--";
    const hintEl = document.getElementById("deploy-hint");
    if (hintEl) hintEl.textContent = `Node ${created.id} released at target! Duplicate release blocked.`;
    const interlockEl = document.getElementById("deploy-interlock-status");
    if (interlockEl) interlockEl.textContent = `Node ${created.id} successfully released.`;

    const verifHint = document.getElementById("rf-verification-hint");
    if (verifHint) {
      verifHint.textContent = `Node ${created.id} deployed! Start a NEW RF survey (AFTER survey) to verify coverage improvement.`;
    }

    logEvent(
      `AUTO DEPLOY SUCCESS: Node ${created.id} deployed at lat=${latitude.toFixed(5)}, lon=${longitude.toFixed(5)}. ` +
      `Total active deployed nodes: ${state.deployedNodes.length}. Repeated release blocked.`
    );
  } catch (err) {
    logEvent(`AUTO DEPLOY rejected: ${err.message}`);
    const interlockEl = document.getElementById("deploy-interlock-status");
    if (interlockEl) interlockEl.textContent = `Release rejected: ${err.message}`;
    _deployInProgress = false;
    updateDeploymentReleaseButton();
    return;
  } finally {
    _deployInProgress = false;
    if (deployBtn) deployBtn.disabled = true;
  }
}

// ---------------------------------------------------------------------------
// Affected-area polygon drawing
// ---------------------------------------------------------------------------

function onMapClick(e) {
  const { lat, lng } = e.latlng;

  // ── Drawing mode: add polygon vertex ────────────────────────────────────
  if (state.drawing) {
    // Clicking near the first vertex closes the polygon, same as "Finish Area".
    if (state.points.length >= 3) {
      const first = state.vertexMarkers[0];
      const firstPoint = first.getLatLng();
      const distPx = map.latLngToContainerPoint(firstPoint)
        .distanceTo(map.latLngToContainerPoint(e.latlng));
      if (distPx < 14) {
        finishArea();
        return;
      }
    }
    addVertex(lat, lng);
    return;
  }

  // ── Idle / non-drawing: select a deployment location ───────────────────
  selectDeploymentLocation(lat, lng, "map");
}

function addVertex(lat, lng) {
  state.points.push({ lat, lon: lng });

  const isFirst = state.vertexMarkers.length === 0;
  const marker = L.circleMarker([lat, lng], {
    radius: isFirst ? 6 : 4,
    color: "#FFB020",
    fillColor: "#FFB020",
    fillOpacity: 1,
    weight: 2,
  }).addTo(map);

  state.vertexMarkers.push(marker);
  updateDrawLine();
  updatePointCount();
  updateFinishButton();
}

function updateDrawLine() {
  const latlngs = state.points.map((p) => [p.lat, p.lon]);
  if (state.drawLine) {
    state.drawLine.setLatLngs(latlngs);
  } else if (latlngs.length > 0) {
    state.drawLine = L.polyline(latlngs, {
      color: "#FFB020",
      weight: 2,
      dashArray: "5 5",
    }).addTo(map);
  }
}

function updatePointCount() {
  document.getElementById("stat-points").textContent = state.points.length;
}

function updateFinishButton() {
  document.getElementById("btn-finish").disabled = state.points.length < 3;
}

function startDrawing() {
  if (state.areaClosed) return; // must clear first
  state.drawing = true;
  setDrawingState("DRAWING");

  const drawBtn = document.getElementById("btn-draw");
  drawBtn.classList.add("active");
  drawBtn.textContent = "Drawing… (click map)";

  document.getElementById("btn-clear").disabled = false;
  logEvent("Draw Affected Area started — click the map to place vertices.");
}

function finishArea() {
  if (state.points.length < 3) return;

  state.drawing = false;
  state.areaClosed = true;

  if (state.drawLine) {
    map.removeLayer(state.drawLine);
    state.drawLine = null;
  }

  const latlngs = state.points.map((p) => [p.lat, p.lon]);
  state.areaPolygon = L.polygon(latlngs, {
    color: "#FFB020",
    weight: 2,
    fillColor: "#FFB020",
    fillOpacity: 0.12,
  }).addTo(map);

  const drawBtn = document.getElementById("btn-draw");
  drawBtn.classList.remove("active");
  drawBtn.textContent = "Draw Affected Area";
  drawBtn.disabled = true;

  document.getElementById("btn-finish").disabled = true;
  document.getElementById("btn-analyze").disabled = false;
  document.getElementById("analyze-hint").textContent =
    "Area defined — ready to analyze.";

  setDrawingState("AREA DEFINED");
  logEvent(`Affected area closed with ${state.points.length} points.`);
}

function clearArea() {
  state.drawing = false;
  state.areaClosed = false;
  state.points = [];

  state.vertexMarkers.forEach((m) => map.removeLayer(m));
  state.vertexMarkers = [];

  if (state.drawLine) {
    map.removeLayer(state.drawLine);
    state.drawLine = null;
  }
  if (state.areaPolygon) {
    map.removeLayer(state.areaPolygon);
    state.areaPolygon = null;
  }

  const drawBtn = document.getElementById("btn-draw");
  drawBtn.disabled = false;
  drawBtn.classList.remove("active");
  drawBtn.textContent = "Draw Affected Area";

  document.getElementById("btn-finish").disabled = true;
  document.getElementById("btn-clear").disabled = true;
  document.getElementById("btn-analyze").disabled = true;
  document.getElementById("analyze-hint").textContent =
    "Draw and close a polygon with at least 3 points to enable analysis.";

  updatePointCount();
  document.getElementById("stat-coverage").textContent = "--";
  document.getElementById("stat-gap").textContent = "--";

  clearAnalysisOverlays();
  clearRecommendedPanel();
  clearMissionPanel();
  clearRfScan();

  setDrawingState("IDLE");
  logEvent("Affected area cleared.");
}

function setDrawingState(label) {
  document.getElementById("stat-state").textContent = label;
}

// ---------------------------------------------------------------------------
// Analyze Area -> real backend coverage analysis (Phase 2-4, wired in Phase 5)
// ---------------------------------------------------------------------------

function clearAnalysisOverlays() {
  [state.gapLayer, state.coveredLayer, state.candidateLayer].forEach((layer) => {
    if (layer) map.removeLayer(layer);
  });
  state.gapLayer = null;
  state.coveredLayer = null;
  state.candidateLayer = null;
  state.topMarkers = {};
  if (state.selectedMarker) {
    map.removeLayer(state.selectedMarker);
    state.selectedMarker = null;
  }
}

function downsample(points, cap) {
  if (points.length <= cap) return points;
  const step = points.length / cap;
  const sampled = [];
  for (let i = 0; i < cap; i++) {
    sampled.push(points[Math.floor(i * step)]);
  }
  return sampled;
}

function renderCoverageOverlay(result) {
  state.gapLayer = L.layerGroup().addTo(map);
  state.coveredLayer = L.layerGroup().addTo(map);

  downsample(result.gap_points, MAX_RENDERED_POINTS_PER_LAYER).forEach((p) => {
    L.circleMarker([p.lat, p.lon], {
      renderer: canvasRenderer,
      radius: 2,
      color: "#FF5C5C",
      fillColor: "#FF5C5C",
      fillOpacity: 0.55,
      weight: 0,
    }).addTo(state.gapLayer);
  });

  downsample(result.covered_points, MAX_RENDERED_POINTS_PER_LAYER).forEach((p) => {
    L.circleMarker([p.lat, p.lon], {
      renderer: canvasRenderer,
      radius: 2,
      color: "#3FDA7F",
      fillColor: "#3FDA7F",
      fillOpacity: 0.35,
      weight: 0,
    }).addTo(state.coveredLayer);
  });
}

async function analyzeArea() {
  if (!state.areaClosed) return;

  const analyzeBtn = document.getElementById("btn-analyze");
  analyzeBtn.disabled = true;
  document.getElementById("analyze-hint").textContent = "Analyzing…";
  logEvent("Analyze Area requested.");

  try {
    await apiPost("/api/area", { polygon: state.points });

    const result = await apiPost("/api/analyze");
    if (result.status !== 200) {
      throw new Error(result.body && result.body.detail ? result.body.detail : `HTTP ${result.status}`);
    }

    const analysis = result.body;
    document.getElementById("stat-coverage").textContent = `${analysis.coverage_percentage.toFixed(1)}%`;
    document.getElementById("stat-gap").textContent = `${analysis.gap_percentage.toFixed(1)}%`;
    logEvent(
      `Coverage analysis complete — ${analysis.total_points} grid points, ` +
      `${analysis.coverage_percentage.toFixed(1)}% covered, ${analysis.gap_percentage.toFixed(1)}% gap.`
    );

    clearAnalysisOverlays();
    renderCoverageOverlay(analysis);

    document.getElementById("analyze-hint").textContent =
      "Analysis complete. Generating candidate locations…";

    await loadCandidates();
  } catch (err) {
    logEvent(`Analyze Area failed: ${err.message}`);
    document.getElementById("analyze-hint").textContent = `Error: ${err.message}`;
  } finally {
    analyzeBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Candidate generation + scoring (Phase 3-4, wired in Phase 5)
// ---------------------------------------------------------------------------

function candidateKey(c) {
  return `${c.lat.toFixed(6)},${c.lon.toFixed(6)}`;
}

function renderCandidates(candidates, top) {
  state.candidateLayer = L.layerGroup().addTo(map);
  state.topMarkers = {};

  const topKeys = new Set(top.map(candidateKey));

  candidates.forEach((c) => {
    const isTop = topKeys.has(candidateKey(c));
    const marker = L.circleMarker([c.lat, c.lon], {
      radius: isTop ? 9 : 6,
      color: isTop ? "#5CA8FF" : "#B98CFF",
      fillColor: isTop ? "#5CA8FF" : "#B98CFF",
      fillOpacity: isTop ? 0.9 : 0.6,
      weight: 2,
    }).addTo(state.candidateLayer);

    marker.bindTooltip(`score ${c.score.toFixed(1)}`, {
      direction: "top",
      offset: [0, -8],
      className: "node-label",
    });

    // Clicking a candidate marker selects it as a deployment location
    marker.on("click", (ev) => {
      L.DomEvent.stopPropagation(ev); // don't also fire onMapClick
      selectDeploymentLocation(c.lat, c.lon, "candidate");
    });

    if (isTop) {
      state.topMarkers[candidateKey(c)] = marker;
    }
  });
}

function renderRecommendedPanel(top) {
  document.getElementById("recommended-empty").classList.add("hidden");
  const list = document.getElementById("recommended-list");
  list.innerHTML = "";

  const labels = ["A", "B"];
  top.forEach((c, i) => {
    const label = labels[i] || String(i + 1);
    const card = document.createElement("div");
    card.className = "location-card";
    card.innerHTML = `
      <div class="location-card-header">
        <span class="location-card-label">Location ${label}</span>
        <span class="location-card-score">Score ${c.score.toFixed(1)}</span>
      </div>
      <div class="location-card-metrics">
        <span>Coverage +${c.coverage_improvement_pct.toFixed(1)}pp</span>
        <span>${c.distance_to_home_m.toFixed(0)}m from home</span>
      </div>
      <div class="btn-row">
        <button class="btn btn-select" data-key="${candidateKey(c)}">&#x1F3AF; Select ${label}</button>
        <button class="btn btn-primary btn-select-mission" data-key="${candidateKey(c)}">Mission</button>
      </div>
    `;
    list.appendChild(card);

    // "Select" → sets deployment location (does NOT immediately deploy)
    card.querySelector(".btn-select").addEventListener("click", () =>
      selectDeploymentLocation(c.lat, c.lon, "candidate")
    );

    // "Mission" → existing mission-planning workflow (POST /api/select-target)
    card.querySelector(".btn-select-mission").addEventListener("click", () =>
      selectLocation(c, label)
    );
  });
}

function clearRecommendedPanel() {
  document.getElementById("recommended-empty").classList.remove("hidden");
  document.getElementById("recommended-list").innerHTML = "";
  state.candidates = [];
  state.top = [];
}

async function loadCandidates() {
  try {
    const result = await apiGet("/api/candidates");
    state.candidates = result.candidates;
    state.top = result.top;

    renderCandidates(result.candidates, result.top);
    renderRecommendedPanel(result.top);

    document.getElementById("analyze-hint").textContent =
      `${result.candidates.length} candidates scored — top ${result.top.length} recommended.`;
    logEvent(`Candidate generation complete — ${result.candidates.length} candidates, top ${result.top.length} recommended.`);
  } catch (err) {
    logEvent(`Candidate generation failed: ${err.message}`);
    document.getElementById("analyze-hint").textContent = `Error: ${err.message}`;
  }
}

// ---------------------------------------------------------------------------
// Target selection + mission generation
// ---------------------------------------------------------------------------

function clearMissionPanel() {
  document.getElementById("mission-lat").value = "--";
  document.getElementById("mission-lon").value = "--";
  document.getElementById("btn-generate-mission").disabled = true;
  document.getElementById("btn-upload-mission").disabled = true;
  document.getElementById("btn-start-mission").disabled = true;
  document.getElementById("btn-abort-mission").disabled = true;
  document.getElementById("mission-hint").textContent =
    "Select a recommended location to generate a mission.";
  document.getElementById("stat-mission-state").textContent = "PLANNING";
  document.getElementById("stat-upload-status").textContent = "--";
  document.getElementById("stat-px4-ack").textContent = "--";
  document.getElementById("stat-mission-items").textContent = "--";
  document.getElementById("stat-mission-current").textContent = "--";
  state.selectedTarget = null;
  state.missionGenerated = false;
  state.missionUploaded = false;
  state.missionExecuting = false;
  state.lastMissionId = null;
  state.lastMissionItems = 0;
}

async function selectLocation(candidate, label) {
  try {
    const lat = candidate.lat != null ? candidate.lat : candidate.latitude;
    const lon = candidate.lon != null ? candidate.lon : candidate.longitude;
    const result = await apiPost("/api/select-target", { lat, lon });
    if (result.status !== 200) throw new Error(result.body && result.body.detail);

    state.selectedTarget = { lat, lon };

    document.getElementById("mission-lat").value = lat.toFixed(6);
    document.getElementById("mission-lon").value = lon.toFixed(6);
    document.getElementById("btn-generate-mission").disabled = false;

    // Requirement 23: Display Rank, Latitude, Longitude, Gap points, Score, Distance to nearest node
    let metaDesc = `SELECTED: ${label} (Lat: ${lat.toFixed(5)}, Lon: ${lon.toFixed(5)})`;
    if (candidate.score != null) {
      metaDesc += ` | Score: ${candidate.score} | Gap pts: ${candidate.gap_points ?? "--"} | Node dist: ${candidate.nearest_node_distance_m ?? "--"}m`;
    }
    metaDesc += ` — Click GENERATE MISSION to plan route.`;
    document.getElementById("mission-hint").textContent = metaDesc;

    // Requirement 26: Pre-populate Node Deployment panel for explicit AUTO DEPLOY
    selectDeploymentLocation(lat, lon, label || "candidate");

    if (state.selectedMarker) map.removeLayer(state.selectedMarker);
    state.selectedMarker = L.circleMarker([lat, lon], {
      radius: 12,
      color: "#FFB020",
      fillOpacity: 0,
      weight: 3,
    }).addTo(map);

    logEvent(`Selected Candidate ${label}: lat=${lat.toFixed(5)}, lon=${lon.toFixed(5)}`);
  } catch (err) {
    logEvent(`Select Location ${label} failed: ${err.message}`);
  }
}

async function generateMission() {
  if (!state.selectedTarget) return;

  const altInput = document.getElementById("mission-alt");
  const altitude = parseFloat(altInput.value) || 15;

  const btn = document.getElementById("btn-generate-mission");
  btn.disabled = true;

  try {
    const result = await apiPost("/api/mission/generate", {
      lat: state.selectedTarget.lat,
      lon: state.selectedTarget.lon,
      altitude_m: altitude,
    });
    if (result.status !== 200) throw new Error(result.body && result.body.detail);

    const mission = result.body;
    state.missionGenerated = true;
    state.missionUploaded = false;
    state.missionExecuting = false;
    state.missionCompleted = false;
    state.returningHome = false;
    state.returnCompleted = false;
    state.lastMissionId = mission.id;

    document.getElementById("stat-mission-state").textContent = "GENERATED";
    document.getElementById("stat-upload-status").textContent = "GENERATED";
    document.getElementById("stat-px4-ack").textContent = "--";
    document.getElementById("stat-mission-items").textContent = "--";

    // Upload is now possible; Start/Abort remain disabled.
    document.getElementById("btn-upload-mission").disabled = false;
    document.getElementById("btn-start-mission").disabled = true;
    document.getElementById("btn-abort-mission").disabled = true;

    document.getElementById("mission-hint").textContent =
      `Mission #${mission.id} generated (alt ${mission.target_alt}m). Upload it to PX4.`;
    logEvent(`Mission #${mission.id} generated — status ${mission.status}.`);
  } catch (err) {
    logEvent(`Generate Mission failed: ${err.message}`);
  } finally {
    btn.disabled = !state.selectedTarget;
  }
}

// ---------------------------------------------------------------------------
// Phase 8 — Upload / Start / Abort
// ---------------------------------------------------------------------------

async function uploadMission() {
  if (!state.missionGenerated) return;

  const btn = document.getElementById("btn-upload-mission");
  btn.disabled = true;
  document.getElementById("btn-start-mission").disabled = true;
  document.getElementById("btn-abort-mission").disabled = true;
  document.getElementById("stat-mission-state").textContent = "UPLOADING";
  document.getElementById("stat-upload-status").textContent = "UPLOADING…";
  document.getElementById("stat-px4-ack").textContent = "…";
  document.getElementById("mission-hint").textContent = "Uploading mission to PX4…";
  logEvent("Mission upload started.");

  try {
    const result = await apiPost("/api/mission/send", {});
    const body = result.body;

    if (result.status === 503) {
      // PX4 not connected.
      document.getElementById("stat-mission-state").textContent = "GENERATED";
      document.getElementById("stat-upload-status").textContent = "NO PX4 LINK";
      document.getElementById("stat-px4-ack").textContent = "--";
      document.getElementById("mission-hint").textContent =
        "PX4 not connected. Start SITL and wait for telemetry link.";
      logEvent(`Mission upload failed: PX4 not connected.`);
      btn.disabled = false;
      return;
    }

    if (!body.success) {
      document.getElementById("stat-mission-state").textContent = "FAILED";
      document.getElementById("stat-upload-status").textContent = body.status.toUpperCase();
      document.getElementById("stat-px4-ack").textContent = "REJECTED";
      document.getElementById("mission-hint").textContent =
        `Upload failed: ${body.error || body.status}`;
      logEvent(`Mission upload failed: ${body.error || body.status}`);
      state.missionUploaded = false;
      btn.disabled = false;
      return;
    }

    // Success — PX4 acknowledged.
    state.missionUploaded = true;
    state.missionExecuting = false;
    state.lastMissionItems = body.items;

    document.getElementById("stat-mission-state").textContent = "UPLOADED";
    document.getElementById("stat-upload-status").textContent = "UPLOADED";
    document.getElementById("stat-px4-ack").textContent = "ACCEPTED";
    document.getElementById("stat-mission-items").textContent = `${body.items} items`;
    document.getElementById("mission-hint").textContent =
      `Mission uploaded (${body.items} items). Arm vehicle then Start Mission.`;
    logEvent(`Mission uploaded — ${body.items} items accepted by PX4.`);

    // Enable Start only if armed; keep Upload enabled (re-upload allowed).
    btn.disabled = false;
    const isArmed = Boolean(state.vehicle && state.vehicle.armed);
    document.getElementById("btn-start-mission").disabled = !isArmed;
    document.getElementById("btn-abort-mission").disabled = false;
    if (!isArmed) {
      document.getElementById("mission-hint").textContent =
        `Mission uploaded (${body.items} items). UAV must be armed before starting the mission.`;
    }

  } catch (err) {
    document.getElementById("stat-mission-state").textContent = "FAILED";
    document.getElementById("stat-upload-status").textContent = "ERROR";
    document.getElementById("mission-hint").textContent = `Upload error: ${err.message}`;
    logEvent(`Mission upload error: ${err.message}`);
    btn.disabled = false;
  }
}

async function startMission() {
  if (!state.missionUploaded) return;

  const btn = document.getElementById("btn-start-mission");
  const rfStartBtn = document.getElementById("btn-start-rf-scan");

  // Phase 5 Requirement 25: START MISSION must not work while the UAV is disarmed.
  const isArmed = Boolean(state.vehicle && state.vehicle.armed);
  if (!isArmed) {
    const msg = "UAV must be armed before starting the mission.";
    document.getElementById("mission-hint").textContent = msg;
    const rfHintEl = document.getElementById("rf-scan-hint");
    if (rfHintEl && state.rfScanState === "MISSION_UPLOADED") {
      rfHintEl.textContent = msg;
    }
    if (btn) btn.disabled = true;
    if (rfStartBtn) rfStartBtn.disabled = true;
    logEvent(`Start Mission rejected: ${msg}`);
    return;
  }

  if (btn) btn.disabled = true;
  if (rfStartBtn) rfStartBtn.disabled = true;
  document.getElementById("mission-hint").textContent = "Commanding PX4 into mission mode…";
  logEvent("Start Mission commanded.");

  try {
    const result = await apiPost("/api/mission/start", {});
    const body = result.body;

    if (result.status === 400 || result.status === 503) {
      const msg = body && body.detail ? body.detail : JSON.stringify(body);
      document.getElementById("mission-hint").textContent = `Start failed: ${msg}`;
      logEvent(`Start Mission failed: ${msg}`);
      if (btn) btn.disabled = false;
      if (rfStartBtn) rfStartBtn.disabled = false;
      return;
    }

    if (!body.success) {
      document.getElementById("mission-hint").textContent =
        `Start failed: ${body.error || "PX4 rejected mode change"}`;
      logEvent(`Start Mission rejected: ${body.error}`);
      if (btn) btn.disabled = false;
      if (rfStartBtn) rfStartBtn.disabled = false;
      return;
    }

    // PX4 entered mission mode.
    state.missionExecuting = true;
    document.getElementById("stat-mission-state").textContent = "EXECUTING";
    document.getElementById("mission-hint").textContent =
      "PX4 in mission mode. Watch telemetry for movement.";
    logEvent("PX4 entered MISSION mode — UAV executing mission.");

    // Disable Start while executing; Abort ENABLED because there's now an active mission.
    if (btn) btn.disabled = true;
    if (rfStartBtn) rfStartBtn.disabled = true;
    document.getElementById("btn-abort-mission").disabled = false;

  } catch (err) {
    document.getElementById("mission-hint").textContent = `Start error: ${err.message}`;
    logEvent(`Start Mission error: ${err.message}`);
    if (btn) btn.disabled = !state.missionUploaded;
    if (rfStartBtn) rfStartBtn.disabled = !state.missionUploaded;
  }
}

async function abortMission() {
  const btn = document.getElementById("btn-abort-mission");

  // Guard: do not abort if there is no executing mission
  if (!state.missionExecuting && state.rfScanState !== "RUNNING" && state.rfScanState !== "APPROACHING") {
    logEvent("ABORT: no active mission to abort — button should be disabled.");
    btn.disabled = true;
    return;
  }

  btn.disabled = true;  // Disable immediately on press — stays disabled after abort
  document.getElementById("mission-hint").textContent = "Sending abort command…";
  logEvent("Abort commanded.");

  try {
    const result = await apiPost("/api/mission/abort", {});
    const body = result.body;

    if (result.status === 503) {
      const msg = body && body.detail ? body.detail : "PX4 not connected";
      document.getElementById("mission-hint").textContent = `Abort failed: ${msg}`;
      logEvent(`Abort failed: ${msg}`);
      // Only re-enable if still executing (the mission didn't stop)
      if (state.missionExecuting) btn.disabled = false;
      return;
    }

    if (!body.success && body.error !== "No active mission to abort.") {
      document.getElementById("mission-hint").textContent =
        `Abort failed: ${body.error || "PX4 rejected abort"}`;
      logEvent(`Abort rejected: ${body.error}`);
      if (state.missionExecuting) btn.disabled = false;
      return;
    }

    // Abort succeeded (or there was no active mission — both cases leave btn disabled)
    state.missionExecuting = false;
    document.getElementById("stat-mission-state").textContent = "ABORTED";

    // Update RF scan state if this was an RF scan abort
    if (state.rfScanState === "RUNNING" || state.rfScanState === "MISSION_UPLOADED" || state.rfScanState === "APPROACHING") {
      state.rfScanState = "ABORTED";
      const rfStateEl = document.getElementById("stat-rf-state");
      if (rfStateEl) rfStateEl.textContent = "ABORTED";
      const rfHintEl = document.getElementById("rf-scan-hint");
      if (rfHintEl) rfHintEl.textContent = "RF scan aborted — sample collection stopped.";
      const rfsStateEl = document.getElementById("stat-rfs-state");
      if (rfsStateEl) rfsStateEl.textContent = "ABORTED";
      const rfsHintEl = document.getElementById("rf-survey-hint");
      if (rfsHintEl) rfsHintEl.textContent = "Scan aborted. Partial data preserved. Reset survey to start fresh.";
      logEvent("RF scan ABORTED — sample collection stopped.");
    }

    document.getElementById("mission-hint").textContent =
      "Mission aborted. No active mission.";
    logEvent("Mission aborted successfully.");

    // btn-abort-mission remains DISABLED — there is no active mission to abort
    // btn-start-mission also disabled — no uploaded mission anymore
    document.getElementById("btn-start-mission").disabled = true;

  } catch (err) {
    document.getElementById("mission-hint").textContent = `Abort error: ${err.message}`;
    logEvent(`Abort error: ${err.message}`);
    // Only re-enable if mission may still be active
    if (state.missionExecuting) btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Phase 8.5 — Arm/Disarm
// ---------------------------------------------------------------------------

async function armVehicle() {
  const btn = document.getElementById("btn-arm");
  btn.disabled = true;
  logEvent("ARM commanded.");

  try {
    const result = await apiPost("/api/vehicle/arm", {});
    const body = result.body;

    if (result.status !== 200 || !body.success) {
      logEvent(`ARM failed: ${body?.error || "Unknown error"}`);
    } else {
      logEvent("ARM command sent successfully.");
    }
  } catch (err) {
    logEvent(`ARM error: ${err.message}`);
  }
}

async function disarmVehicle() {
  const btn = document.getElementById("btn-disarm");
  btn.disabled = true;
  logEvent("DISARM commanded.");

  try {
    const result = await apiPost("/api/vehicle/disarm", {});
    const body = result.body;

    if (result.status !== 200 || !body.success) {
      logEvent(`DISARM failed: ${body?.error || "Unknown error"}`);
    } else {
      logEvent("DISARM command sent successfully.");
    }
  } catch (err) {
    logEvent(`DISARM error: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Return to Home (Post-mission return workflow)
// ---------------------------------------------------------------------------

async function returnHome() {
  const btn = document.getElementById("btn-return-home");
  if (btn) btn.disabled = true;

  document.getElementById("stat-mission-state").textContent = "RETURNING HOME";
  document.getElementById("mission-hint").textContent = "Commanding UAV to return to home…";
  logEvent("Return to Home commanded.");

  try {
    const result = await apiPost("/api/vehicle/return-home", {});
    const body = result.body;

    if (result.status === 503 || result.status === 400) {
      const msg = body && body.detail ? body.detail : JSON.stringify(body);
      document.getElementById("mission-hint").textContent = `Return failed: ${msg}`;
      logEvent(`Return to Home failed: ${msg}`);
      if (btn) btn.disabled = false;
      return;
    }

    if (!body.success) {
      document.getElementById("mission-hint").textContent =
        `Return failed: ${body.error || "PX4 rejected return"}`;
      logEvent(`Return to Home rejected: ${body.error}`);
      if (btn) btn.disabled = false;
      return;
    }

    state.returningHome = true;
    state.missionExecuting = false;
    state.lastMissionItems = body.items || 3;
    document.getElementById("stat-mission-state").textContent = "RETURNING HOME";
    document.getElementById("mission-hint").textContent =
      "UAV returning to home coordinates. Watch telemetry for movement.";
    logEvent("PX4 executing Return to Home mission.");

  } catch (err) {
    document.getElementById("mission-hint").textContent = `Return error: ${err.message}`;
    logEvent(`Return to Home error: ${err.message}`);
    if (btn) btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Manual Control — POSCTL override + Gamepad velocity loop + MISSION resume
// ---------------------------------------------------------------------------

/**
 * Axis mapping (Standard W3C Gamepad API — Xbox / PlayStation layout):
 *   axes[0] = Left stick X   → vy  (+right / East)
 *   axes[1] = Left stick Y   → vx  (-forward / North, inverted)
 *   axes[2] = Right stick X  → yaw_rate
 *   axes[3] = Right stick Y  → vz  (NED down — right-stick up = negative = ascending)
 */
const GAMEPAD_MAX_V   = 3.0;   // m/s max on translational axes (GCS-side cap)
const GAMEPAD_MAX_YAW = 0.5;   // rad/s
const GAMEPAD_DEADZONE = 0.08;
const GAMEPAD_POLL_MS = 50;    // 20 Hz

function _gpDeadzone(v) {
  return Math.abs(v) < GAMEPAD_DEADZONE ? 0 : v;
}

function _detectGamepad() {
  const pads = navigator.getGamepads ? navigator.getGamepads() : [];
  for (let i = 0; i < pads.length; i++) {
    if (pads[i]) return i;
  }
  return null;
}

function _updateGamepadStat() {
  const el = document.getElementById("stat-gamepad");
  if (!el) return;
  const idx = state.manualControl.gamepadIndex;
  if (idx === null) {
    el.textContent = "NONE";
    el.classList.remove("status-connected");
    el.classList.add("status-disconnected");
  } else {
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    const gp = pads[idx];
    el.textContent = gp ? `PAD ${idx}` : `PAD ${idx} (lost)`;
    el.classList.remove("status-disconnected");
    el.classList.add("status-connected");
  }
}

function _updateOverrideStat() {
  const el = document.getElementById("stat-override-mode");
  if (!el) return;
  if (state.manualControl.active) {
    el.textContent = "MANUAL";
    el.classList.add("status-degraded");
    el.classList.remove("status-connected");
  } else {
    el.textContent = "AUTO";
    el.classList.remove("status-degraded");
    el.classList.add("status-connected");
  }
}

function _sendGamepadVelocity() {
  const mc = state.manualControl;
  if (!mc.active) return;

  const idx = mc.gamepadIndex !== null ? mc.gamepadIndex : _detectGamepad();
  if (idx === null) return;

  const pads = navigator.getGamepads ? navigator.getGamepads() : [];
  const gp = pads[idx];
  if (!gp) return;

  const raw_vx  = _gpDeadzone(-(gp.axes[1] || 0));  // left-Y inverted  → forward
  const raw_vy  = _gpDeadzone(  gp.axes[0] || 0);   // left-X            → right
  const raw_vz  = _gpDeadzone(  gp.axes[3] || 0);   // right-Y NED down  → down
  const raw_yaw = _gpDeadzone(  gp.axes[2] || 0);   // right-X           → yaw CW

  const vx       = raw_vx  * GAMEPAD_MAX_V;
  const vy       = raw_vy  * GAMEPAD_MAX_V;
  const vz       = raw_vz  * GAMEPAD_MAX_V;
  const yaw_rate = raw_yaw * GAMEPAD_MAX_YAW;

  // Update live velocity readout in Manual Override panel
  const setV = (id, val) => {
    const e = document.getElementById(id);
    if (e) e.textContent = val.toFixed(2);
  };
  setV("stat-vx", vx);
  setV("stat-vy", vy);
  setV("stat-vz", vz);
  const yrEl = document.getElementById("stat-yaw-rate");
  if (yrEl) yrEl.textContent = (yaw_rate * 57.296).toFixed(1);  // rad/s → deg/s

  apiPost("/api/vehicle/manual-velocity", { vx, vy, vz, yaw_rate })
    .catch((err) => {
      const now = Date.now();
      if (now - mc.lastLogError > 5000) {
        mc.lastLogError = now;
        logEvent(`Manual velocity send error: ${err.message}`);
      }
    });
}

function _startGamepadLoop() {
  if (state.manualControl.sendTimer) return;
  state.manualControl.sendTimer = setInterval(_sendGamepadVelocity, GAMEPAD_POLL_MS);
}

function _stopGamepadLoop() {
  if (state.manualControl.sendTimer) {
    clearInterval(state.manualControl.sendTimer);
    state.manualControl.sendTimer = null;
  }
  // Zero out the velocity readouts
  ["stat-vx", "stat-vy", "stat-vz", "stat-yaw-rate"].forEach((id) => {
    const e = document.getElementById(id);
    if (e) e.textContent = "--";
  });
}

function initGamepadListeners() {
  window.addEventListener("gamepadconnected", (e) => {
    logEvent(`Gamepad connected: ${e.gamepad.id} (index ${e.gamepad.index})`);
    if (state.manualControl.gamepadIndex === null) {
      state.manualControl.gamepadIndex = e.gamepad.index;
    }
    _updateGamepadStat();
    _updateManualButtons();
  });

  window.addEventListener("gamepaddisconnected", (e) => {
    logEvent(`Gamepad disconnected: index ${e.gamepad.index}`);
    if (state.manualControl.gamepadIndex === e.gamepad.index) {
      state.manualControl.gamepadIndex = null;
      // Try to pick up another connected pad
      const fallback = _detectGamepad();
      state.manualControl.gamepadIndex = fallback;
    }
    _updateGamepadStat();
    _updateManualButtons();
  });
}

function _updateManualButtons() {
  const manualBtn = document.getElementById("btn-manual-control");
  const resumeBtn = document.getElementById("btn-resume-mission");
  if (!manualBtn || !resumeBtn) return;

  const mc = state.manualControl;
  const vehicle = state.vehicle;
  const fresh = isTelemetryFresh();
  const linked = state.telemetrySocketOpen && fresh && vehicle && vehicle.connected;
  const armed  = linked && vehicle.armed;
  // Manual Control available when: connected + armed + (executing or manual already) + NOT returning home
  const canManual = armed && !state.returningHome &&
                    (state.missionExecuting || mc.active || state.missionUploaded);
  const canResume = mc.active && linked;

  manualBtn.disabled = !canManual || mc.active;  // disabled once already in manual
  resumeBtn.disabled = !canResume;
}

async function enterManualControl() {
  const mc = state.manualControl;
  const btn = document.getElementById("btn-manual-control");
  if (btn) btn.disabled = true;

  logEvent("MANUAL CONTROL requested — switching to POSCTL.");
  document.getElementById("manual-hint").textContent = "Switching to POSCTL…";

  try {
    const result = await apiPost("/api/vehicle/manual-control", {});
    const body = result.body;

    if (result.status === 503) {
      const msg = body && body.detail ? body.detail : "PX4 not connected";
      document.getElementById("manual-hint").textContent = `Manual failed: ${msg}`;
      logEvent(`Manual Control failed: ${msg}`);
      if (btn) btn.disabled = false;
      return;
    }

    if (!body.success) {
      document.getElementById("manual-hint").textContent =
        `Manual failed: ${body.error || "PX4 rejected POSCTL"}`;
      logEvent(`Manual Control rejected: ${body.error}`);
      if (btn) btn.disabled = false;
      return;
    }

    mc.active = true;
    state.missionExecuting = false;  // pause auto-mission state tracking

    // If no gamepad index set yet, try detecting one now
    if (mc.gamepadIndex === null) {
      mc.gamepadIndex = _detectGamepad();
    }

    _startGamepadLoop();
    _updateOverrideStat();
    _updateGamepadStat();
    _updateManualButtons();

    document.getElementById("stat-mission-state").textContent = "MANUAL";
    document.getElementById("manual-hint").textContent =
      mc.gamepadIndex !== null
        ? "POSCTL active — use gamepad to fly. Click Resume Auto to hand back."
        : "POSCTL active — no gamepad detected yet. Connect one to fly.";
    logEvent("POSCTL manual override active. Gamepad loop started.");

  } catch (err) {
    document.getElementById("manual-hint").textContent = `Manual error: ${err.message}`;
    logEvent(`Manual Control error: ${err.message}`);
    if (btn) btn.disabled = false;
  }
}

async function resumeMission() {
  const mc = state.manualControl;
  const btn = document.getElementById("btn-resume-mission");
  if (btn) btn.disabled = true;

  logEvent("RESUME AUTO requested — switching to MISSION mode.");
  document.getElementById("manual-hint").textContent = "Resuming autonomous mission…";

  _stopGamepadLoop();

  try {
    const result = await apiPost("/api/vehicle/resume-mission", {});
    const body = result.body;

    if (result.status === 503) {
      const msg = body && body.detail ? body.detail : "PX4 not connected";
      document.getElementById("manual-hint").textContent = `Resume failed: ${msg}`;
      logEvent(`Resume Mission failed: ${msg}`);
      // Re-start loop — still in manual if PX4 couldn't switch modes
      if (mc.active) _startGamepadLoop();
      if (btn) btn.disabled = !mc.active;
      return;
    }

    if (!body.success) {
      document.getElementById("manual-hint").textContent =
        `Resume failed: ${body.error || "PX4 rejected MISSION mode"}`;
      logEvent(`Resume Mission rejected: ${body.error}`);
      if (mc.active) _startGamepadLoop();
      if (btn) btn.disabled = !mc.active;
      return;
    }

    mc.active = false;
    state.missionExecuting = true;  // back to auto tracking

    _updateOverrideStat();
    _updateManualButtons();

    document.getElementById("stat-mission-state").textContent = "EXECUTING";
    document.getElementById("manual-hint").textContent =
      "PX4 resumed MISSION mode — UAV continuing autonomous waypoints.";
    logEvent("PX4 resumed MISSION mode — autonomous mission continuing.");

  } catch (err) {
    document.getElementById("manual-hint").textContent = `Resume error: ${err.message}`;
    logEvent(`Resume Mission error: ${err.message}`);
    if (mc.active) _startGamepadLoop();
    if (btn) btn.disabled = !mc.active;
  }
}

// ---------------------------------------------------------------------------
// Live telemetry (Phase 7) — /ws/telemetry -> UAV marker + telemetry panel
// ---------------------------------------------------------------------------

function telemetryWsUrl() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/telemetry`;
}

function setStat(id, text, statusClass) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.classList.remove("status-connected", "status-degraded", "status-disconnected", "status-stale");
  if (statusClass) el.classList.add(statusClass);
}

function fmtNum(value, digits, suffix) {
  if (value === null || value === undefined) return "--";
  return `${value.toFixed(digits)}${suffix || ""}`;
}

// Is the data we're currently showing fresh enough to trust?
function isTelemetryFresh() {
  return state.lastTelemetryAt > 0 && (Date.now() - state.lastTelemetryAt) < TELEMETRY_STALE_MS;
}

function renderTelemetryPanel() {
  const socketUp = state.telemetrySocketOpen;
  const vehicle = state.vehicle;
  const fresh = isTelemetryFresh();

  if (!socketUp) {
    setStat("tel-connection", "DISCONNECTED", "status-disconnected");
  } else if (!fresh) {
    setStat("tel-connection", "STALE", "status-stale");
  } else if (vehicle && vehicle.connected) {
    setStat("tel-connection", "CONNECTED", "status-connected");
  } else {
    setStat("tel-connection", "NO PX4 LINK", "status-degraded");
  }

  const stale = !socketUp || !fresh || !vehicle || !vehicle.connected;
  const v = vehicle || {};

  setStat("tel-armed", v.armed ? "ARMED" : "DISARMED", v.armed ? "status-degraded" : null);

  const armBtn = document.getElementById("btn-arm");
  const disarmBtn = document.getElementById("btn-disarm");
  const returnHomeBtn = document.getElementById("btn-return-home");

  if (stale) {
    armBtn.disabled = true;
    disarmBtn.disabled = true;
    if (returnHomeBtn) returnHomeBtn.disabled = true;
  } else {
    if (v.armed) {
      armBtn.disabled = true;
      disarmBtn.disabled = false;
    } else {
      armBtn.disabled = false;
      disarmBtn.disabled = true;
    }

    if (returnHomeBtn) {
      // Return to Home is enabled only post-mission when mission completed, UAV at target, not executing/returning
      if (state.missionExecuting || state.returningHome || !state.missionCompleted || state.returnCompleted) {
        returnHomeBtn.disabled = true;
      } else {
        returnHomeBtn.disabled = false;
      }
    }

    // Phase 5 Requirement 25: START MISSION / START RF SCAN available only after ARM
    const startMissionBtn = document.getElementById("btn-start-mission");
    if (startMissionBtn && state.missionUploaded && !state.missionExecuting) {
      startMissionBtn.disabled = !v.armed;
    }
    const startRfBtn = document.getElementById("btn-start-rf-scan");
    if (startRfBtn && state.rfScanState === "MISSION_UPLOADED") {
      startRfBtn.disabled = !v.armed;
    }
  }

  // Update Manual Override button gating whenever telemetry refreshes
  _updateManualButtons();
  _updateOverrideStat();
  updateDeploymentReleaseButton();

  setStat("tel-mode", v.mode || "--");
  setStat("tel-gps-fix", v.gps_fix || "--");
  setStat("tel-lat", v.latitude != null ? v.latitude.toFixed(6) : "--");
  setStat("tel-lon", v.longitude != null ? v.longitude.toFixed(6) : "--");
  setStat("tel-alt", fmtNum(v.altitude, 1, " m"));
  setStat("tel-rel-alt", fmtNum(v.relative_altitude, 1, " m"));
  setStat("tel-ground-speed", fmtNum(v.ground_speed, 1, " m/s"));
  setStat("tel-heading", v.heading != null ? `${v.heading.toFixed(0)}°` : "--");
  setStat("tel-battery", fmtNum(v.battery, 0, "%"));
  setStat("tel-satellites", v.satellites != null ? String(v.satellites) : "--");

  // Phase 8 — mission waypoint progress from live PX4 telemetry.
  const mcur = v.mission_current;
  const mreached = v.mission_item_reached;
  setStat("tel-mission-current", mcur != null ? `WP ${mcur}` : "--");
  setStat("tel-mission-reached", mreached != null ? `WP ${mreached}` : "--");

  // Also update the mission panel's Current WP stat.
  document.getElementById("stat-mission-current").textContent =
    mcur != null ? `WP ${mcur}` : "--";

  // If we reach the final waypoint of forward mission, update mission state.
  if (state.missionExecuting && mreached != null && state.lastMissionItems > 0) {
    if (mreached >= state.lastMissionItems - 1) {
      state.missionCompleted = true;
      state.missionExecuting = false;
      document.getElementById("stat-mission-state").textContent = "COMPLETED";
      document.getElementById("mission-hint").textContent =
        "Mission complete — UAV landed at target. Ready to Return to Home.";
      if (state.rfScanState === "MISSION_UPLOADED") {
        state.rfScanState = "COMPLETED";
        const rfStateEl = document.getElementById("stat-rf-state");
        if (rfStateEl) rfStateEl.textContent = "COMPLETED";
        const rfHintEl = document.getElementById("rf-scan-hint");
        if (rfHintEl) rfHintEl.textContent = "RF scan survey flight completed.";
      }
      logEvent(`Mission COMPLETED — waypoint ${mreached} reached.`);
    }
  }

  // If returning home and reached final waypoint, mark return complete.
  if (state.returningHome && mreached != null && state.lastMissionItems > 0) {
    if (mreached >= state.lastMissionItems - 1) {
      state.returningHome = false;
      state.returnCompleted = true;
      document.getElementById("stat-mission-state").textContent = "RETURN COMPLETE";
      document.getElementById("mission-hint").textContent =
        "Return complete — UAV reached home coordinates.";
      logEvent(`Return to Home COMPLETED — waypoint ${mreached} reached.`);
    }
  }

  // Also drives the existing Mission-panel connection indicator, since
  // that field's meaning (is the vehicle link up?) is the same one.
  setStat(
    "stat-connection",
    !socketUp ? "DISCONNECTED" : (fresh && v.connected ? "CONNECTED" : "DISCONNECTED"),
    !socketUp ? "status-disconnected" : (fresh && v.connected ? "status-connected" : "status-degraded")
  );

  updateUavMarker(vehicle, stale);
}

function uavIcon(headingDeg, stale) {
  const angle = headingDeg == null ? 0 : headingDeg;
  return L.divIcon({
    className: "",
    html:
      `<div class="uav-marker-icon${stale ? " stale" : ""}" style="transform: rotate(${angle}deg);">` +
      `<svg width="26" height="26" viewBox="0 0 26 26">` +
      `<polygon points="13,2 21,23 13,17 5,23" fill="#5CA8FF" stroke="#0A0D11" stroke-width="1.5"/>` +
      `</svg></div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

function updateUavMarker(vehicle, stale) {
  // Never invent a position: only place/move the marker when we have an
  // actual lat/lon from PX4. If we've never had a fix yet, there's simply
  // no marker to draw.
  if (!vehicle || vehicle.latitude == null || vehicle.longitude == null) {
    if (state.uavMarker) {
      // Had a fix before but this update lacks one (e.g. link just
      // dropped) — dim the last known position rather than remove it,
      // so the operator can still see where the UAV was last seen.
      state.uavMarker.setIcon(uavIcon(null, true));
    }
    return;
  }

  const latlng = [vehicle.latitude, vehicle.longitude];
  const icon = uavIcon(vehicle.heading, stale);

  if (!state.uavMarker) {
    state.uavMarker = L.marker(latlng, { icon, zIndexOffset: 1000 }).addTo(map);
  } else {
    state.uavMarker.setLatLng(latlng);
    state.uavMarker.setIcon(icon);
  }
}

function connectTelemetry() {
  if (state.telemetryReconnectTimer) {
    clearTimeout(state.telemetryReconnectTimer);
    state.telemetryReconnectTimer = null;
  }

  let ws;
  try {
    ws = new WebSocket(telemetryWsUrl());
  } catch (err) {
    scheduleTelemetryReconnect();
    return;
  }

  state.telemetryWs = ws;

  ws.onopen = () => {
    state.telemetrySocketOpen = true;
    logEvent("Telemetry stream connected.");
    document.getElementById("telemetry-hint").textContent = "Streaming live PX4 telemetry.";
    renderTelemetryPanel();
  };

  ws.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (err) {
      // Malformed telemetry message — ignore this one rather than crash
      // the stream or invent values from it.
      return;
    }
    if (!data || data.type !== "telemetry" || !data.vehicle) return;

    state.vehicle = data.vehicle;
    state.lastTelemetryAt = Date.now();
    renderTelemetryPanel();
  };

  ws.onclose = () => {
    const wasOpen = state.telemetrySocketOpen;
    state.telemetrySocketOpen = false;
    state.telemetryWs = null;
    renderTelemetryPanel();
    if (wasOpen) logEvent("Telemetry stream disconnected — attempting to reconnect.");
    document.getElementById("telemetry-hint").textContent = "Telemetry disconnected — reconnecting…";
    scheduleTelemetryReconnect();
  };

  ws.onerror = () => {
    // onclose fires right after onerror for a WebSocket; let onclose
    // handle cleanup/reconnect so it only happens once.
    try {
      ws.close();
    } catch (err) {
      /* already closing */
    }
  };
}

function scheduleTelemetryReconnect() {
  if (state.telemetryReconnectTimer) return;
  state.telemetryReconnectTimer = setTimeout(() => {
    state.telemetryReconnectTimer = null;
    connectTelemetry();
  }, TELEMETRY_RECONNECT_MS);
}

function startTelemetryStaleWatch() {
  setInterval(() => {
    // Re-render on a timer too (not just on message receipt) so the UI
    // actually flips to STALE/DISCONNECTED promptly when messages stop
    // arriving, instead of only updating on the next real telemetry push.
    if (state.telemetrySocketOpen || state.vehicle) renderTelemetryPanel();
  }, TELEMETRY_STALE_CHECK_MS);
}

// ---------------------------------------------------------------------------
// Phase 2 — RF Scan Survey (Zig-zag / Lawnmower Mission)
// ---------------------------------------------------------------------------

function clearRfScan() {
  if (state.rfScanLayer) {
    map.removeLayer(state.rfScanLayer);
    state.rfScanLayer = null;
  }
  state.rfScanMission = null;
  state.rfScanState = "IDLE";

  const stateEl = document.getElementById("stat-rf-state");
  if (stateEl) stateEl.textContent = "IDLE";
  const wpEl = document.getElementById("stat-rf-waypoints");
  if (wpEl) wpEl.textContent = "--";
  const linesEl = document.getElementById("stat-rf-lines");
  if (linesEl) linesEl.textContent = "--";
  const distEl = document.getElementById("stat-rf-distance");
  if (distEl) distEl.textContent = "--";
  const spacingEl = document.getElementById("stat-rf-spacing");
  if (spacingEl) spacingEl.textContent = "--";
  const altEl = document.getElementById("stat-rf-altitude");
  if (altEl) altEl.textContent = "--";
  const container = document.getElementById("rf-waypoints-container");
  if (container) container.classList.add("hidden");
  const hintEl = document.getElementById("rf-scan-hint");
  if (hintEl) hintEl.textContent = "Define an affected area, then click RF SCAN to generate a survey path.";

  const uploadBtn = document.getElementById("btn-upload-rf-scan");
  if (uploadBtn) uploadBtn.disabled = true;
  const startBtn = document.getElementById("btn-start-rf-scan");
  if (startBtn) startBtn.disabled = true;

  // Phase 5 Requirement 27: New survey invalidates old analysis
  resetRfAnalysisState("RF scan cleared. Define area and generate survey to start.");
}

function renderRfScanPath(waypoints) {
  if (!waypoints || waypoints.length === 0) return;

  if (state.rfScanLayer) {
    map.removeLayer(state.rfScanLayer);
  }
  state.rfScanLayer = L.layerGroup().addTo(map);

  const latlngs = waypoints.map(wp => [wp.lat, wp.lon]);

  // 1. Draw survey flight path polyline (vibrant cyan dashed line)
  L.polyline(latlngs, {
    color: "#00E5FF",
    weight: 2.5,
    dashArray: "5 5",
    opacity: 0.9,
  }).addTo(state.rfScanLayer);

  // 2. Add waypoint markers along the survey path
  waypoints.forEach((wp, idx) => {
    const isFirst = idx === 0;
    const isLast = idx === waypoints.length - 1;

    let markerColor = "#00E5FF";
    let markerRadius = 3.5;
    let weight = 1.5;

    if (isFirst) {
      markerColor = "#3FDA7F"; // Green start
      markerRadius = 6;
      weight = 2.5;
    } else if (isLast) {
      markerColor = "#FF5C5C"; // Red end
      markerRadius = 6;
      weight = 2.5;
    }

    const marker = L.circleMarker([wp.lat, wp.lon], {
      radius: markerRadius,
      color: markerColor,
      fillColor: isFirst ? "#3FDA7F" : isLast ? "#FF5C5C" : "#0A0D11",
      fillOpacity: 0.9,
      weight: weight,
    }).addTo(state.rfScanLayer);

    const label = isFirst
      ? `START WP #0 (Line 1)`
      : isLast
      ? `END WP #${wp.seq} (Line ${wp.line_idx + 1})`
      : `WP #${wp.seq} (Line ${wp.line_idx + 1})`;

    marker.bindTooltip(
      `<div style="font-family:var(--font-data); font-size:11px;">
        <strong>${label}</strong><br>
        Lat: ${wp.lat.toFixed(6)}<br>
        Lon: ${wp.lon.toFixed(6)}<br>
        Alt: ${wp.alt}m
      </div>`,
      { direction: "top", offset: [0, -5] }
    );
  });
}

async function handleRfScan() {
  const hintEl = document.getElementById("rf-scan-hint");

  // Step 1 check: valid affected area exists
  if (!state.areaClosed || !state.points || state.points.length < 3) {
    if (hintEl) hintEl.textContent = "Define an affected area first.";
    logEvent("RF SCAN rejected: Define an affected area first.");
    return;
  }

  const spacingInput = document.getElementById("scan-spacing");
  const altInput = document.getElementById("scan-alt");
  const spacing_m = parseFloat(spacingInput ? spacingInput.value : 25) || 25;
  const altitude_m = parseFloat(altInput ? altInput.value : 15) || 15;

  const btn = document.getElementById("btn-rf-scan");
  if (btn) btn.disabled = true;
  if (hintEl) hintEl.textContent = "Generating zig-zag survey path…";
  logEvent(`RF SCAN requested — calculating survey path (spacing ${spacing_m}m, alt ${altitude_m}m)…`);

  try {
    const result = await apiPost("/api/rf-scan/generate", {
      polygon: state.points,
      spacing_m: spacing_m,
      altitude_m: altitude_m,
    });

    if (result.status !== 200) {
      throw new Error(result.body && result.body.detail ? result.body.detail : `HTTP ${result.status}`);
    }

    const data = result.body;
    state.rfScanState = data.state;
    state.rfScanMission = data;

    // Phase 5 Requirement 27: New survey invalidates old analysis
    resetRfAnalysisState("New RF scan generated. Complete scan to run coverage analysis.");

    // Update UI stats
    const stateEl = document.getElementById("stat-rf-state");
    if (stateEl) stateEl.textContent = data.state;
    const wpEl = document.getElementById("stat-rf-waypoints");
    if (wpEl) wpEl.textContent = data.waypoint_count;
    const linesEl = document.getElementById("stat-rf-lines");
    if (linesEl) linesEl.textContent = data.line_count;
    // Format distance: show km when >= 1000 m, otherwise metres.
    const distM = data.total_distance_m;
    const distFormatted = distM >= 1000
      ? `${(distM / 1000).toFixed(2)} km`
      : `${distM.toFixed(1)} m`;
    const distEl = document.getElementById("stat-rf-distance");
    if (distEl) distEl.textContent = distFormatted;
    const spacingEl = document.getElementById("stat-rf-spacing");
    if (spacingEl) spacingEl.textContent = `${data.spacing_m} m`;
    const altEl = document.getElementById("stat-rf-altitude");
    if (altEl) altEl.textContent = `${data.altitude_m} m`;

    // Render path on map — full path stays visible.
    renderRfScanPath(data.waypoints);

    // Show compact summary card instead of a full waypoint list.
    const container = document.getElementById("rf-waypoints-container");
    const summary = document.getElementById("rf-waypoints-summary");
    if (container) {
      container.classList.remove("hidden");
      if (summary) {
        summary.innerHTML =
          `<div class="rf-summary-row"><span class="rf-summary-label">Waypoints</span><span class="rf-summary-value">${data.waypoint_count}</span></div>` +
          `<div class="rf-summary-row"><span class="rf-summary-label">Survey Lines</span><span class="rf-summary-value">${data.line_count}</span></div>` +
          `<div class="rf-summary-row"><span class="rf-summary-label">Spacing</span><span class="rf-summary-value">${data.spacing_m} m</span></div>` +
          `<div class="rf-summary-row"><span class="rf-summary-label">Altitude</span><span class="rf-summary-value">${data.altitude_m} m</span></div>` +
          `<div class="rf-summary-row"><span class="rf-summary-label">Est. Distance</span><span class="rf-summary-value">${distFormatted}</span></div>`;
      }
    }

    // Enable Upload button now that a valid mission exists.
    const uploadBtn = document.getElementById("btn-upload-rf-scan");
    if (uploadBtn) uploadBtn.disabled = false;
    const startBtn = document.getElementById("btn-start-rf-scan");
    if (startBtn) startBtn.disabled = true; // stays disabled until uploaded

    if (hintEl) {
      const startEp = data.start_endpoint;
      const startDesc = startEp
        ? ` ● Green start: ${startEp.lat.toFixed(5)}, ${startEp.lon.toFixed(5)} (nearest endpoint to UAV).`
        : "";
      hintEl.textContent =
        `Survey path generated — ${data.waypoint_count} waypoints, ${data.line_count} lines.` +
        startDesc +
        ` Click Upload RF Scan to send to PX4.`;
    }
    const startEpLog = data.start_endpoint
      ? ` | Green start dot: lat=${data.start_endpoint.lat.toFixed(5)}, lon=${data.start_endpoint.lon.toFixed(5)} (first waypoint, nearest to UAV)`
      : "";
    logEvent(
      `RF survey mission generated: ${data.waypoint_count} waypoints across ` +
      `${data.line_count} lines, total dist ${distFormatted}.${startEpLog}`
    );
  } catch (err) {
    if (hintEl) hintEl.textContent = `Error: ${err.message}`;
    logEvent(`RF SCAN generation failed: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Phase 2 — RF Scan Upload (reuses existing /api/mission/start via mav_manager)
// ---------------------------------------------------------------------------

async function uploadRfScanMission() {
  if (!state.rfScanMission) {
    logEvent("RF SCAN upload rejected: no mission generated yet.");
    return;
  }

  const uploadBtn = document.getElementById("btn-upload-rf-scan");
  const startBtn  = document.getElementById("btn-start-rf-scan");
  const hintEl    = document.getElementById("rf-scan-hint");
  const stateEl   = document.getElementById("stat-rf-state");

  if (uploadBtn) uploadBtn.disabled = true;
  if (startBtn)  startBtn.disabled  = true;
  if (stateEl)   stateEl.textContent = "UPLOADING";
  if (hintEl)    hintEl.textContent  = "Uploading RF scan mission to PX4…";
  logEvent("RF scan mission upload started.");

  try {
    const result = await apiPost("/api/rf-scan/upload", {});
    const body   = result.body;

    if (result.status === 503) {
      const msg = body && body.detail ? body.detail : "PX4 not connected";
      if (stateEl) stateEl.textContent = "FAILED";
      if (hintEl)  hintEl.textContent  = `Upload failed: ${msg}`;
      logEvent(`RF scan upload failed: ${msg}`);
      if (uploadBtn) uploadBtn.disabled = false;
      return;
    }

    if (!body.success) {
      if (stateEl) stateEl.textContent = "FAILED";
      if (hintEl)  hintEl.textContent  = `Upload failed: ${body.error || body.status}`;
      logEvent(`RF scan upload failed: ${body.error || body.status}`);
      if (uploadBtn) uploadBtn.disabled = false;
      return;
    }

    // PX4 accepted the survey mission.
    state.rfScanState   = "MISSION_UPLOADED";
    // Signal the existing startMission() gate (it checks state.missionUploaded).
    state.missionUploaded   = true;
    state.missionExecuting  = false;
    state.lastMissionItems  = body.items;

    if (stateEl) stateEl.textContent = "UPLOADED";
    if (hintEl)  hintEl.textContent  =
      `RF scan mission uploaded (${body.items} items). ` +
      `Arm vehicle then click START RF SCAN.`;
    logEvent(`RF scan mission uploaded — ${body.items} items accepted by PX4.`);

    // Enable Start only if vehicle is armed; keep Upload enabled (re-upload is allowed).
    const isArmed = Boolean(state.vehicle && state.vehicle.armed);
    if (uploadBtn) uploadBtn.disabled = false;
    if (startBtn)  startBtn.disabled  = !isArmed;
    if (hintEl) {
      hintEl.textContent = isArmed
        ? `RF scan mission uploaded (${body.items} items). Ready to Start RF Scan.`
        : `RF scan mission uploaded (${body.items} items). UAV must be armed before starting the RF scan.`;
    }

    // Keep Mission panel upload status in sync so telemetry WP display works.
    document.getElementById("stat-mission-state").textContent  = "UPLOADED";
    document.getElementById("stat-upload-status").textContent  = "UPLOADED";
    document.getElementById("stat-px4-ack").textContent        = "ACCEPTED";
    document.getElementById("stat-mission-items").textContent  = `${body.items} items`;

  } catch (err) {
    if (stateEl) stateEl.textContent = "FAILED";
    if (hintEl)  hintEl.textContent  = `Upload error: ${err.message}`;
    logEvent(`RF scan upload error: ${err.message}`);
    if (uploadBtn) uploadBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Phase 5 — RF Coverage Heatmap + Candidate Generation from real survey data
// ---------------------------------------------------------------------------

/**
 * RSSI color per classification status (matches backend thresholds exactly).
 */
const RF_STATUS_COLOR = {
  GOOD:       "#3FDA7F",
  MODERATE:   "#F5A623",
  WEAK:       "#FF9500",
  GAP:        "#FF5C5C",
  UNMEASURED: "#4A5568",
};

/**
 * Remove all heatmap / gap-point / RF-candidate Leaflet layers from the map.
 */
function clearRfAnalysisLayers() {
  if (state.rfHeatmapLayer) { map.removeLayer(state.rfHeatmapLayer); state.rfHeatmapLayer = null; }
  if (state.rfGapLayer)     { map.removeLayer(state.rfGapLayer);     state.rfGapLayer = null; }
  if (state.rfCandidateLayer){ map.removeLayer(state.rfCandidateLayer); state.rfCandidateLayer = null; }
}

/**
 * Phase 5 Requirement 27: Reset all RF analysis state and UI panels when
 * a new survey starts, an area changes, or data is reset.
 */
function resetRfAnalysisState(hintMessage) {
  clearRfAnalysisLayers();
  state.rfAnalysis = null;
  state.rfAnalysisAutoTriggered = false;
  const summaryEl = document.getElementById("rf-coverage-summary");
  if (summaryEl) summaryEl.classList.add("hidden");
  const ctrlEl = document.getElementById("rf-heatmap-controls");
  if (ctrlEl) ctrlEl.classList.add("hidden");
  const candListEl = document.getElementById("recommended-list");
  if (candListEl) candListEl.innerHTML = "";
  const candEmptyEl = document.getElementById("recommended-empty");
  if (candEmptyEl) candEmptyEl.classList.remove("hidden");
  const rfaHintEl = document.getElementById("rf-analysis-hint");
  if (rfaHintEl) {
    rfaHintEl.textContent = hintMessage || "Complete an RF scan, then click Analyze to generate the coverage heatmap and candidates.";
  }
}

/**
 * Helper to build a Leaflet LayerGroup for an RF coverage heatmap dataset.
 */
function createHeatmapLayer(heatmapPoints, opacity, radius = 5) {
  const layer = L.layerGroup();
  if (!heatmapPoints || heatmapPoints.length === 0) return layer;

  const fillOpacity = Math.max(0.05, Math.min(0.95, opacity));
  const strokeOpacity = Math.min(1, fillOpacity * 1.4);

  for (const pt of heatmapPoints) {
    const color = RF_STATUS_COLOR[pt.status] || RF_STATUS_COLOR.UNMEASURED;
    const rssiText = pt.best_rssi != null ? `${pt.best_rssi} dBm` : "--";

    L.circleMarker([pt.latitude, pt.longitude], {
      radius: radius,
      color: color,
      fillColor: color,
      fillOpacity,
      opacity: strokeOpacity,
      weight: 0.8,
      renderer: canvasRenderer,
    })
      .bindTooltip(
        `<div style="font-family:var(--font-data);font-size:11px">`
        + `<strong>${pt.status}</strong><br>RSSI: ${rssiText}<br>`
        + `${pt.latitude.toFixed(6)}, ${pt.longitude.toFixed(6)}</div>`,
        { direction: "top", offset: [0, -4] }
      )
      .addTo(layer);
  }
  return layer;
}

/**
 * Render the RF coverage heatmap from heatmap_points array.
 * Each point: {latitude, longitude, best_rssi, status}
 */
function renderRfHeatmap(heatmapPoints, opacity) {
  if (state.rfHeatmapLayer) { map.removeLayer(state.rfHeatmapLayer); state.rfHeatmapLayer = null; }
  if (!heatmapPoints || heatmapPoints.length === 0) return;

  state.rfHeatmapLayer = createHeatmapLayer(heatmapPoints, opacity);

  if (state.rfHeatmapVisible) {
    state.rfHeatmapLayer.addTo(map);
  }
}

/**
 * Render gap-point cluster markers (red diamonds).
 */
function renderRfGapPoints(gapPoints) {
  if (state.rfGapLayer) { map.removeLayer(state.rfGapLayer); state.rfGapLayer = null; }
  if (!gapPoints || gapPoints.length === 0) return;

  state.rfGapLayer = L.layerGroup().addTo(map);

  for (const pt of gapPoints) {
    L.circleMarker([pt.latitude, pt.longitude], {
      radius: 4,
      color: "#FF5C5C",
      fillColor: "#FF5C5C",
      fillOpacity: 0.0,
      opacity: 0.7,
      weight: 1.5,
      renderer: canvasRenderer,
    }).addTo(state.rfGapLayer);
  }

  if (!state.rfGapVisible) {
    map.removeLayer(state.rfGapLayer);
  }
}

/**
 * Render RF analysis candidates on the map and populate the Recommended panel.
 */
function renderRfCandidates(candidates) {
  if (state.rfCandidateLayer) { map.removeLayer(state.rfCandidateLayer); state.rfCandidateLayer = null; }

  const listEl = document.getElementById("recommended-list");
  const emptyEl = document.getElementById("recommended-empty");

  if (!candidates || candidates.length === 0) {
    if (listEl) listEl.innerHTML = "";
    if (emptyEl) emptyEl.classList.remove("hidden");
    return;
  }

  if (emptyEl) emptyEl.classList.add("hidden");
  state.rfCandidateLayer = L.layerGroup().addTo(map);

  if (listEl) listEl.innerHTML = "";

  candidates.forEach((c, idx) => {
    const label = `Candidate #${c.rank || (idx + 1)}`;
    const isTop = idx === 0;

    // Map marker
    const color = isTop ? "#FFB020" : "#F5A623";
    const marker = L.circleMarker([c.latitude, c.longitude], {
      radius: isTop ? 10 : 8,
      color,
      fillColor: color,
      fillOpacity: 0.18,
      weight: isTop ? 3 : 2.5,
    })
      .bindTooltip(
        `<div style="font-family:var(--font-data);font-size:11px">`
        + `<strong>${label}</strong><br>`
        + `Score: ${c.score}<br>`
        + `Gap pts: ${c.gap_points} | Node dist: ${c.nearest_node_distance_m}m<br>`
        + `${c.latitude.toFixed(6)}, ${c.longitude.toFixed(6)}`
        + `</div>`,
        { direction: "top", offset: [0, -6] }
      )
      .addTo(state.rfCandidateLayer);

    // Requirement 23: Clicking marker selects the candidate
    marker.on("click", () => {
      selectLocation(c, label);
      document.querySelectorAll(".rf-candidate-card").forEach(el => el.classList.remove("selected"));
      card.classList.add("selected");
    });

    // Rank label divIcon
    L.marker([c.latitude, c.longitude], {
      icon: L.divIcon({
        className: "",
        html: `<div style="font-size:10px;font-weight:700;color:${color};font-family:var(--font-data);text-shadow:0 0 3px #000;white-space:nowrap">#${c.rank || (idx+1)}</div>`,
        iconAnchor: [-10, 4],
      }),
      interactive: false,
    }).addTo(state.rfCandidateLayer);

    // Side-panel card
    const card = document.createElement("div");
    card.className = `rf-candidate-card${isTop ? " rank-1" : ""}`;
    card.id = `rf-cand-${idx}`;
    card.innerHTML =
      `<div class="rf-candidate-rank${isTop ? " rank-1" : ""}">★ ${label}${isTop ? " (BEST)" : ""}</div>`
      + `<div class="rf-candidate-meta">`
      + `Score: ${c.score}&nbsp;&nbsp;|&nbsp;&nbsp;Gap pts: ${c.gap_points}<br>`
      + `Nearest node: ${c.nearest_node_distance_m} m<br>`
      + `Lat: ${c.latitude.toFixed(6)}&nbsp;&nbsp;Lon: ${c.longitude.toFixed(6)}`
      + `</div>`
      + `<div class="rf-candidate-actions">`
      + `<button class="btn btn-primary" id="rfcand-select-${idx}">Select for Mission</button>`
      + `</div>`;
    if (listEl) listEl.appendChild(card);

    // Wire "Select for Mission" button
    setTimeout(() => {
      const btn = document.getElementById(`rfcand-select-${idx}`);
      if (btn) {
        btn.addEventListener("click", () => {
          selectLocation(c, label);
          // Highlight selected card
          document.querySelectorAll(".rf-candidate-card").forEach(el => el.classList.remove("selected"));
          card.classList.add("selected");
        });
      }
    }, 0);
  });

  if (!state.rfCandidatesVisible) {
    map.removeLayer(state.rfCandidateLayer);
  }
}

/**
 * Update the RF coverage summary stats panel.
 */
function updateRfCoverageSummary(data) {
  const total = data.survey_samples || 0;
  function pct(n) {
    return total > 0 ? ` (${((n / total) * 100).toFixed(0)}%)` : "";
  }

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set("rfa-samples",  total);
  set("rfa-clusters", data.gap_cluster_count ?? "--");
  set("rfa-good",     `${data.good_count}${pct(data.good_count)}`);
  set("rfa-moderate", `${data.moderate_count}${pct(data.moderate_count)}`);
  set("rfa-weak",     `${data.weak_count}${pct(data.weak_count)}`);
  set("rfa-gap",      `${data.gap_count}${pct(data.gap_count)}`);
}

/**
 * Main Phase 5 action: POST /api/rf-survey/analyze and render results.
 */
async function analyzeRfSurvey() {
  const btn     = document.getElementById("btn-analyze-rf");
  const hintEl  = document.getElementById("rf-analysis-hint");

  if (btn) btn.disabled = true;
  if (hintEl) hintEl.textContent = "Running RF coverage analysis…";
  logEvent("RF coverage analysis requested…");

  try {
    const result = await apiPost("/api/rf-survey/analyze", {});

    if (result.status === 400) {
      const msg = result.body && result.body.detail ? result.body.detail : `HTTP ${result.status}`;
      if (hintEl) hintEl.textContent = `Analysis failed: ${msg}`;
      logEvent(`RF analysis failed: ${msg}`);
      return;
    }

    if (result.status !== 200) {
      throw new Error(result.body && result.body.detail ? result.body.detail : `HTTP ${result.status}`);
    }

    const data = result.body;
    state.rfAnalysis = data;
    state.rfPhase6State = data.phase6_state || state.rfPhase6State;

    if (data.survey_role === "BEFORE") {
      state.rfBeforeAnalysis = data.before_analysis || data;
      state.activeHeatmapView = "BEFORE";
      const verifHint = document.getElementById("rf-verification-hint");
      if (verifHint) {
        verifHint.textContent = "BEFORE survey complete & preserved! Select candidate, deploy node, then run AFTER survey.";
      }
      const viewSel = document.getElementById("heatmap-view-selector-container");
      if (viewSel) viewSel.classList.add("hidden");
      const verifResults = document.getElementById("verification-results");
      if (verifResults) verifResults.classList.add("hidden");
    } else if (data.survey_role === "AFTER") {
      state.rfAfterAnalysis = data.after_analysis || data;
      state.rfComparison = data.comparison;
      state.activeHeatmapView = "AFTER";
      const viewSel = document.getElementById("heatmap-view-selector-container");
      if (viewSel) viewSel.classList.remove("hidden");
      renderVerificationPanel(data.comparison, data.before_analysis, data.after_analysis);
      const verifHint = document.getElementById("rf-verification-hint");
      if (verifHint) {
        verifHint.textContent = "Deployment verification complete. See comparison metrics below.";
      }
    }

    // --- Update coverage summary ---
    updateRfCoverageSummary(data);

    // --- Render heatmap ---
    clearRfAnalysisLayers();
    renderRfHeatmap(data.heatmap, state.rfHeatmapOpacity);
    renderRfGapPoints(data.gap_points);
    renderRfCandidates(data.candidates);

    // --- Show controls ---
    const summaryEl = document.getElementById("rf-coverage-summary");
    if (summaryEl) summaryEl.classList.remove("hidden");
    const ctrlEl = document.getElementById("rf-heatmap-controls");
    if (ctrlEl) ctrlEl.classList.remove("hidden");

    const total = data.survey_samples || 0;
    const gapPct = total > 0 ? ((data.gap_count / total) * 100).toFixed(0) : 0;
    if (hintEl) {
      hintEl.textContent =
        `${total} samples analyzed [${data.survey_role || "SURVEY"}]. Gap coverage: ${gapPct}%. `
        + `${data.gap_cluster_count} gap cluster(s) → ${data.candidates.length} candidate(s).`;
    }
    logEvent(
      `RF analysis done [${data.survey_role || "SURVEY"}]: ${total} samples | GOOD=${data.good_count} MODERATE=${data.moderate_count} `
      + `WEAK=${data.weak_count} GAP=${data.gap_count} | `
      + `${data.gap_cluster_count} clusters → ${data.candidates.length} candidates.`
    );

    // Refresh RF survey history dropdown (Requirements 7, 8, 13)
    await fetchSurveyHistory();

  } catch (err) {
    if (hintEl) hintEl.textContent = `Analysis error: ${err.message}`;
    logEvent(`RF analysis error: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/**
 * Phase 6 Requirement 8, 13, 14: Populate Deployment Verification panel.
 */
function renderVerificationPanel(comp, beforeData, afterData) {
  const container = document.getElementById("verification-results");
  const warnEl = document.getElementById("verif-invalidation-warning");
  const warnReason = document.getElementById("verif-invalidation-reason");
  const gapsBanner = document.getElementById("remaining-gaps-banner");
  const gapsCount = document.getElementById("remaining-gaps-count");

  if (!comp || !beforeData || !afterData) {
    if (container) container.classList.add("hidden");
    return;
  }

  if (comp.comparable === false) {
    if (warnEl) warnEl.classList.remove("hidden");
    if (warnReason) warnReason.textContent = comp.invalidation_reason || "Surveys cannot be compared.";
    if (container) container.classList.remove("hidden");
    const remGaps = comp.remaining_gaps != null ? comp.remaining_gaps : (afterData.gap_count ?? 0);
    if (gapsCount) gapsCount.textContent = remGaps;
    if (gapsBanner) {
      gapsBanner.className = "verification-badge " + (remGaps === 0 ? "gaps-resolved" : "gaps-remaining");
    }
    return;
  } else {
    if (warnEl) warnEl.classList.add("hidden");
  }

  if (container) container.classList.remove("hidden");

  const remGaps = comp.remaining_gaps != null ? comp.remaining_gaps : (afterData.gap_count ?? 0);
  if (gapsCount) gapsCount.textContent = remGaps;
  if (gapsBanner) {
    gapsBanner.className = "verification-badge " + (remGaps === 0 ? "gaps-resolved" : (remGaps < (beforeData.gap_count || 1) ? "gaps-remaining" : "gaps-severe"));
  }

  const bPcts = beforeData.coverage_percentages || {};
  const aPcts = afterData.coverage_percentages || {};
  const chg = comp.changes || {};

  function fmtChg(val, isPercentagePoints = false, invertSign = false) {
    if (val == null || isNaN(val)) return "--";
    const sign = val > 0 ? "+" : "";
    const suffix = isPercentagePoints ? " pp" : "";
    const text = `${sign}${val}${suffix}`;
    let cls = "change-neutral";
    if (invertSign) {
      if (val < 0) cls = "change-positive";
      else if (val > 0) cls = "change-negative";
    } else {
      if (val > 0) cls = "change-positive";
      else if (val < 0) cls = "change-negative";
    }
    return `<span class="${cls}">${text}</span>`;
  }

  const setHtml = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
  const setText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

  setText("verif-nodes-before", beforeData.active_node_count ?? beforeData.node_positions?.length ?? "--");
  setText("verif-nodes-after", afterData.active_node_count ?? afterData.node_positions?.length ?? "--");
  setHtml("verif-nodes-change", fmtChg(chg.node_count_change, false, false));

  setText("verif-good-before", `${bPcts.good_pct ?? 0}%`);
  setText("verif-good-after", `${aPcts.good_pct ?? 0}%`);
  setHtml("verif-good-change", fmtChg(chg.good_change_percentage_points, true, false));

  setText("verif-mod-before", `${bPcts.moderate_pct ?? 0}%`);
  setText("verif-mod-after", `${aPcts.moderate_pct ?? 0}%`);
  setHtml("verif-mod-change", fmtChg(chg.moderate_change_percentage_points, true, false));

  setText("verif-weak-before", `${bPcts.weak_pct ?? 0}%`);
  setText("verif-weak-after", `${aPcts.weak_pct ?? 0}%`);
  setHtml("verif-weak-change", fmtChg(chg.weak_change_percentage_points, true, true));

  setText("verif-gap-before", `${bPcts.gap_pct ?? 0}%`);
  setText("verif-gap-after", `${aPcts.gap_pct ?? 0}%`);
  setHtml("verif-gap-change", fmtChg(chg.gap_change_percentage_points, true, true));

  setText("verif-gappoints-before", beforeData.gap_count ?? "--");
  setText("verif-gappoints-after", afterData.gap_count ?? "--");
  setHtml("verif-gappoints-change", fmtChg(chg.gap_point_change, false, true));

  setText("verif-gapclusters-before", beforeData.gap_cluster_count ?? "--");
  setText("verif-gapclusters-after", afterData.gap_cluster_count ?? "--");
  setHtml("verif-gapclusters-change", fmtChg(chg.gap_cluster_change, false, true));
}

/**
 * Phase 6 Requirement 11: Switch between AFTER, BEFORE, or OVERLAY heatmap view.
 */
function setHeatmapView(view) {
  state.activeHeatmapView = view;
  const btnAfter = document.getElementById("btn-view-after-heatmap");
  const btnBefore = document.getElementById("btn-view-before-heatmap");
  const btnOverlay = document.getElementById("btn-view-overlay-heatmap");

  if (btnAfter) btnAfter.classList.toggle("active", view === "AFTER");
  if (btnBefore) btnBefore.classList.toggle("active", view === "BEFORE");
  if (btnOverlay) btnOverlay.classList.toggle("active", view === "OVERLAY");

  clearRfAnalysisLayers();

  if (view === "AFTER") {
    const afterData = state.rfAfterAnalysis || state.rfAnalysis;
    if (afterData && afterData.heatmap) {
      renderRfHeatmap(afterData.heatmap, state.rfHeatmapOpacity);
      renderRfGapPoints(afterData.gap_points);
    }
  } else if (view === "BEFORE") {
    if (state.rfBeforeAnalysis && state.rfBeforeAnalysis.heatmap) {
      renderRfHeatmap(state.rfBeforeAnalysis.heatmap, state.rfHeatmapOpacity);
      renderRfGapPoints(state.rfBeforeAnalysis.gap_points);
    }
  } else if (view === "OVERLAY") {
    // Show BEFORE at medium opacity and AFTER on top
    if (state.rfBeforeAnalysis && state.rfBeforeAnalysis.heatmap) {
      state.rfBeforeHeatmapLayer = createHeatmapLayer(state.rfBeforeAnalysis.heatmap, 0.35, 4);
      if (state.rfHeatmapVisible) state.rfBeforeHeatmapLayer.addTo(map);
    }
    const afterData = state.rfAfterAnalysis || state.rfAnalysis;
    if (afterData && afterData.heatmap) {
      renderRfHeatmap(afterData.heatmap, 0.75);
      renderRfGapPoints(afterData.gap_points);
    }
  }
}

/**
 * Phase 6 Requirement 16: Reset verification session without deleting deployed nodes.
 */
async function resetVerificationSession() {
  logEvent("Resetting RF verification session…");
  try {
    await apiPost("/api/rf-survey/session-reset", {});
    state.rfBeforeAnalysis = null;
    state.rfAfterAnalysis = null;
    state.rfComparison = null;
    state.rfAnalysis = null;
    state.newlyDeployedNodeId = null;
    state.rfPhase6State = "BEFORE_SURVEY";
    state.activeHeatmapView = "AFTER";

    clearRfAnalysisLayers();
    renderAllDeployedNodes();

    const verifResults = document.getElementById("verification-results");
    if (verifResults) verifResults.classList.add("hidden");
    const viewSelContainer = document.getElementById("heatmap-view-selector-container");
    if (viewSelContainer) viewSelContainer.classList.add("hidden");
    const warnEl = document.getElementById("verif-invalidation-warning");
    if (warnEl) warnEl.classList.add("hidden");
    const verifHint = document.getElementById("rf-verification-hint");
    if (verifHint) {
      verifHint.textContent = "Deploy a communication node at a candidate site, then complete and analyze an AFTER survey to verify coverage impact.";
    }
    resetRfAnalysisState("Verification session reset. Complete an RF scan, then click Analyze.");
    logEvent("RF verification session reset complete. All deployed nodes preserved.");
  } catch (err) {
    logEvent(`Verification session reset failed: ${err.message}`);
  }
}

/**
 * Initialize Phase 6 Verification controls.
 */
function initVerificationControls() {
  const btnAfter = document.getElementById("btn-view-after-heatmap");
  const btnBefore = document.getElementById("btn-view-before-heatmap");
  const btnOverlay = document.getElementById("btn-view-overlay-heatmap");
  const btnResetVerif = document.getElementById("btn-reset-verification");

  if (btnAfter) btnAfter.addEventListener("click", () => setHeatmapView("AFTER"));
  if (btnBefore) btnBefore.addEventListener("click", () => setHeatmapView("BEFORE"));
  if (btnOverlay) btnOverlay.addEventListener("click", () => setHeatmapView("OVERLAY"));
  if (btnResetVerif) btnResetVerif.addEventListener("click", resetVerificationSession);
}

/**
 * Phase 6 Requirements 7-14: Fetch and populate RF Survey History (up to 5 completed runs).
 */
async function fetchSurveyHistory() {
  try {
    const data = await apiGet("/api/rf-survey/history");
    const surveys = (data && data.surveys) ? data.surveys : [];
    state.surveyHistory = surveys;

    const selectHist = document.getElementById("select-history-survey");
    const selectA = document.getElementById("select-compare-a");
    const selectB = document.getElementById("select-compare-b");
    const btnView = document.getElementById("btn-view-history-survey");
    const btnComp = document.getElementById("btn-run-history-compare");

    if (!selectHist) return;

    selectHist.innerHTML = "";
    if (selectA) selectA.innerHTML = '<option value="">Survey A...</option>';
    if (selectB) selectB.innerHTML = '<option value="">Survey B...</option>';

    if (surveys.length === 0) {
      selectHist.innerHTML = '<option value="">(No historical surveys yet)</option>';
      if (btnView) btnView.disabled = true;
      if (btnComp) btnComp.disabled = true;
      return;
    }

    surveys.forEach((s) => {
      const timeStr = s.timestamp ? s.timestamp.substring(11, 19) : "--";
      const roleStr = s.survey_role || "SURVEY";
      const label = `${s.survey_id} [${roleStr}] - ${timeStr} | Nodes: ${s.node_count}, GAP: ${s.gap_pct}%`;

      const opt = document.createElement("option");
      opt.value = s.survey_id;
      opt.textContent = label;
      selectHist.appendChild(opt);

      if (selectA) {
        const optA = document.createElement("option");
        optA.value = s.survey_id;
        optA.textContent = `${s.survey_id} [${roleStr}]`;
        selectA.appendChild(optA);
      }

      if (selectB) {
        const optB = document.createElement("option");
        optB.value = s.survey_id;
        optB.textContent = `${s.survey_id} [${roleStr}]`;
        selectB.appendChild(optB);
      }
    });

    if (btnView) btnView.disabled = false;

    // Default select A and B if at least 2 surveys
    if (surveys.length >= 2 && selectA && selectB) {
      selectA.selectedIndex = 1;
      selectB.selectedIndex = 2;
      if (btnComp) btnComp.disabled = false;
    } else if (btnComp) {
      btnComp.disabled = true;
    }
  } catch (err) {
    console.warn("fetchSurveyHistory error:", err);
  }
}

/**
 * Phase 6 Requirement 10: Viewing historical surveys must never modify current nodes,
 * current RF collection, current mission, or current candidates.
 */
async function viewHistoricalSurvey(surveyId) {
  if (!surveyId) {
    const sel = document.getElementById("select-history-survey");
    surveyId = sel ? sel.value : null;
  }
  if (!surveyId) return;

  logEvent(`Viewing historical survey ${surveyId}…`);
  try {
    const s = await apiGet(`/api/rf-survey/history/${surveyId}`);
    if (!s) throw new Error("Survey not found");

    if (state.rfHistoricalLayer) {
      map.removeLayer(state.rfHistoricalLayer);
      state.rfHistoricalLayer = null;
    }

    state.rfHistoricalLayer = L.layerGroup().addTo(map);

    // Render historical heatmap
    if (s.heatmap && s.heatmap.length > 0) {
      s.heatmap.forEach((cell) => {
        let color = "#3FDA7F";
        if (cell.status === "MODERATE") color = "#F5A623";
        else if (cell.status === "WEAK") color = "#FF9500";
        else if (cell.status === "GAP") color = "#FF5C5C";

        const marker = L.circleMarker([cell.lat, cell.lon], {
          radius: 6,
          color: color,
          fillColor: color,
          fillOpacity: 0.65,
          weight: 1.5,
        }).addTo(state.rfHistoricalLayer);

        marker.bindTooltip(
          `<div style="font-family:var(--font-data); font-size:11px;">
            <strong>${surveyId} (HISTORICAL)</strong><br>
            RSSI: ${cell.rssi != null ? cell.rssi.toFixed(1) : "--"} dBm (${cell.status})<br>
            Lat: ${cell.lat.toFixed(5)}, Lon: ${cell.lon.toFixed(5)}
          </div>`,
          { direction: "top", offset: [0, -4] }
        );
      });
    }

    // Render historical gap points
    if (s.gaps && s.gaps.gap_points) {
      s.gaps.gap_points.forEach((gp) => {
        L.circleMarker([gp.lat, gp.lon], {
          radius: 4,
          color: "#FF5C5C",
          fillColor: "#0A0D11",
          fillOpacity: 0.9,
          weight: 2,
        }).addTo(state.rfHistoricalLayer).bindTooltip(
          `<strong>${surveyId} GAP POINT</strong><br>Lat: ${gp.lat.toFixed(5)}, Lon: ${gp.lon.toFixed(5)}`,
          { direction: "top", offset: [0, -3] }
        );
      });
    }

    logEvent(
      `Historical survey ${surveyId} rendered on map (read-only): ` +
      `${s.sample_count} samples, ${s.node_count} nodes at that time. Live mission & current nodes unchanged.`
    );
  } catch (err) {
    logEvent(`View historical survey error: ${err.message}`);
  }
}

/**
 * Phase 6 Requirement 11 & 12: Compare two historical surveys.
 * Shows: node count, sample count, GOOD %, MODERATE %, WEAK %, GAP %,
 * gap points, gap clusters, and heatmaps.
 */
async function compareHistoricalSurveys() {
  const selectA = document.getElementById("select-compare-a");
  const selectB = document.getElementById("select-compare-b");
  const idA = selectA ? selectA.value : null;
  const idB = selectB ? selectB.value : null;

  if (!idA || !idB) {
    logEvent("Please select both Survey A and Survey B to compare.");
    return;
  }
  if (idA === idB) {
    logEvent("Please select two distinct historical surveys to compare.");
    return;
  }

  logEvent(`Comparing historical surveys: ${idA} vs ${idB}…`);
  try {
    const res = await apiPost("/api/rf-survey/history/compare", {
      survey_id_1: idA,
      survey_id_2: idB,
    });
    const comp = res.body;
    if (res.status !== 200) {
      throw new Error(comp && comp.detail ? comp.detail : `HTTP ${res.status}`);
    }

    const resContainer = document.getElementById("history-compare-results");
    if (resContainer) resContainer.classList.remove("hidden");

    const badgeEl = document.getElementById("history-compare-badge");
    if (badgeEl) {
      if (comp.comparable) {
        badgeEl.className = "verification-badge gaps-resolved";
        badgeEl.textContent = `COMPARED: ${idA} vs ${idB} (Area Compatible)`;
      } else {
        badgeEl.className = "verification-badge gaps-remaining";
        badgeEl.textContent = `WARNING: ${comp.invalidation_reason || "Area Mismatch"}`;
      }
    }

    const thA = document.getElementById("hist-th-a");
    const thB = document.getElementById("hist-th-b");
    if (thA) thA.textContent = `${idA} [${comp.survey_1.survey_role}]`;
    if (thB) thB.textContent = `${idB} [${comp.survey_2.survey_role}]`;

    const s1 = comp.survey_1;
    const s2 = comp.survey_2;
    const d = comp.delta;

    const setField = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    setField("hist-nodes-a", s1.node_count);
    setField("hist-nodes-b", s2.node_count);
    setField("hist-nodes-delta", (d.node_count_change >= 0 ? "+" : "") + d.node_count_change);

    setField("hist-samples-a", s1.sample_count);
    setField("hist-samples-b", s2.sample_count);
    setField("hist-samples-delta", (d.sample_count_change >= 0 ? "+" : "") + d.sample_count_change);

    setField("hist-good-a", `${s1.good_pct}%`);
    setField("hist-good-b", `${s2.good_pct}%`);
    setField("hist-good-delta", `${d.good_pct_change >= 0 ? "+" : ""}${d.good_pct_change}%`);

    setField("hist-mod-a", `${s1.moderate_pct}%`);
    setField("hist-mod-b", `${s2.moderate_pct}%`);
    setField("hist-mod-delta", `${d.moderate_pct_change >= 0 ? "+" : ""}${d.moderate_pct_change}%`);

    setField("hist-weak-a", `${s1.weak_pct}%`);
    setField("hist-weak-b", `${s2.weak_pct}%`);
    setField("hist-weak-delta", `${d.weak_pct_change >= 0 ? "+" : ""}${d.weak_pct_change}%`);

    setField("hist-gap-a", `${s1.gap_pct}%`);
    setField("hist-gap-b", `${s2.gap_pct}%`);
    setField("hist-gap-delta", `${d.gap_pct_change >= 0 ? "+" : ""}${d.gap_pct_change}%`);

    setField("hist-gappoints-a", s1.gap_points_count);
    setField("hist-gappoints-b", s2.gap_points_count);
    setField("hist-gappoints-delta", `${s2.gap_points_count - s1.gap_points_count >= 0 ? "+" : ""}${s2.gap_points_count - s1.gap_points_count}`);

    setField("hist-gapclusters-a", s1.gap_clusters_count);
    setField("hist-gapclusters-b", s2.gap_clusters_count);
    setField("hist-gapclusters-delta", `${d.gap_clusters_change >= 0 ? "+" : ""}${d.gap_clusters_change}`);

    logEvent(
      `Comparison complete: ${idA} -> ${idB} | GAP %: ${s1.gap_pct}% -> ${s2.gap_pct}% ` +
      `(${d.gap_pct_change >= 0 ? "+" : ""}${d.gap_pct_change}%), Gaps resolved: ${d.gaps_resolved}`
    );
  } catch (err) {
    logEvent(`History comparison failed: ${err.message}`);
  }
}

function initSurveyHistoryControls() {
  const btnView = document.getElementById("btn-view-history-survey");
  const btnComp = document.getElementById("btn-run-history-compare");
  const selectA = document.getElementById("select-compare-a");
  const selectB = document.getElementById("select-compare-b");

  if (btnView) btnView.addEventListener("click", () => viewHistoricalSurvey());
  if (btnComp) btnComp.addEventListener("click", compareHistoricalSurveys);

  const checkComp = () => {
    if (btnComp && selectA && selectB) {
      btnComp.disabled = !selectA.value || !selectB.value || (selectA.value === selectB.value);
    }
  };
  if (selectA) selectA.addEventListener("change", checkComp);
  if (selectB) selectB.addEventListener("change", checkComp);
}

/**
 * Heatmap opacity slider handler.
 */
function initRfHeatmapControls() {
  const toggle  = document.getElementById("toggle-heatmap");
  const opacity = document.getElementById("heatmap-opacity");
  const opVal   = document.getElementById("heatmap-opacity-val");
  const gapChk  = document.getElementById("toggle-gap-points");
  const candChk = document.getElementById("toggle-rf-candidates");

  if (opacity) {
    opacity.addEventListener("input", () => {
      const pct = parseInt(opacity.value, 10);
      if (opVal) opVal.textContent = `${pct}%`;
      state.rfHeatmapOpacity = pct / 100;
      // Re-render heatmap at new opacity
      if (state.rfAnalysis && state.rfHeatmapVisible) {
        renderRfHeatmap(state.rfAnalysis.heatmap, state.rfHeatmapOpacity);
      }
    });
  }

  if (toggle) {
    toggle.addEventListener("change", () => {
      state.rfHeatmapVisible = toggle.checked;
      if (state.rfHeatmapLayer) {
        if (state.rfHeatmapVisible) map.addLayer(state.rfHeatmapLayer);
        else map.removeLayer(state.rfHeatmapLayer);
      }
    });
  }

  if (gapChk) {
    gapChk.addEventListener("change", () => {
      state.rfGapVisible = gapChk.checked;
      if (state.rfGapLayer) {
        if (state.rfGapVisible) map.addLayer(state.rfGapLayer);
        else map.removeLayer(state.rfGapLayer);
      }
    });
  }

  if (candChk) {
    candChk.addEventListener("change", () => {
      state.rfCandidatesVisible = candChk.checked;
      if (state.rfCandidateLayer) {
        if (state.rfCandidatesVisible) map.addLayer(state.rfCandidateLayer);
        else map.removeLayer(state.rfCandidateLayer);
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Phase 3 — RF Survey Live Data (WebSocket to /ws/rf-survey)
// ---------------------------------------------------------------------------

const RF_SURVEY_WS_RECONNECT_MS = 3000;

const rfSurveyWsState = {
  ws: null,
  open: false,
  reconnectTimer: null,
  lastData: null,         // last full rf_survey_data message
  latestSample: null,     // last rf_survey_sample received
};

function rfSurveyWsUrl() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/rf-survey`;
}

function connectRfSurveyWs() {
  if (rfSurveyWsState.reconnectTimer) {
    clearTimeout(rfSurveyWsState.reconnectTimer);
    rfSurveyWsState.reconnectTimer = null;
  }

  let ws;
  try {
    ws = new WebSocket(rfSurveyWsUrl());
  } catch (err) {
    scheduleRfSurveyReconnect();
    return;
  }

  rfSurveyWsState.ws = ws;

  ws.onopen = () => {
    rfSurveyWsState.open = true;
  };

  ws.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (!data) return;

    if (data.type === "rf_survey_data") {
      rfSurveyWsState.lastData = data;
      // Update latest sample from last element if available
      if (data.samples && data.samples.length > 0) {
        rfSurveyWsState.latestSample = data.samples[data.samples.length - 1];
      }
      renderRfSurveyPanel(data);
    } else if (data.type === "rf_survey_sample") {
      rfSurveyWsState.latestSample = data.sample;
      // Update sample count and state without waiting for full data
      renderRfSurveySample(data);
    }
  };

  ws.onclose = () => {
    rfSurveyWsState.open = false;
    rfSurveyWsState.ws = null;
    scheduleRfSurveyReconnect();
  };

  ws.onerror = () => {
    try { ws.close(); } catch { /* already closing */ }
  };
}

function scheduleRfSurveyReconnect() {
  if (rfSurveyWsState.reconnectTimer) return;
  rfSurveyWsState.reconnectTimer = setTimeout(() => {
    rfSurveyWsState.reconnectTimer = null;
    connectRfSurveyWs();
  }, RF_SURVEY_WS_RECONNECT_MS);
}

/**
 * Phase 4 RSSI classification:
 * GOOD:      RSSI > -60 dBm      (#3FDA7F)
 * MODERATE:  -75 < RSSI <= -60   (#F5A623)
 * WEAK:      -85 < RSSI <= -75   (#FF9500)
 * GAP:       RSSI <= -85 dBm     (#FF5C5C)
 */
function getRssiClassification(val) {
  if (val > -60) return { label: "GOOD", color: "#3FDA7F" };
  if (val > -75) return { label: "MODERATE", color: "#F5A623" };
  if (val > -85) return { label: "WEAK", color: "#FF9500" };
  return { label: "GAP", color: "#FF5C5C" };
}

/**
 * Render the RF Survey live data panel from a full rf_survey_data message.
 */
function renderRfSurveyPanel(data) {
  const stateEl   = document.getElementById("stat-rfs-state");
  const samplesEl = document.getElementById("stat-rfs-samples");
  const rssiEl    = document.getElementById("stat-rfs-best-rssi");
  const nodesEl   = document.getElementById("stat-rfs-nodes");
  const hintEl    = document.getElementById("rf-survey-hint");

  const collectorState = data.state || "IDLE";
  if (stateEl)   stateEl.textContent   = collectorState;
  if (samplesEl) samplesEl.textContent = data.sample_count || 0;
  if (nodesEl)   nodesEl.textContent   = (data.deployed_nodes || []).length;

  // Best RSSI from last sample
  const samples = data.samples || [];
  if (samples.length > 0) {
    const last = samples[samples.length - 1];
    if (rssiEl) {
      if (last.best_rssi != null) {
        rssiEl.textContent = `${last.best_rssi} dBm`;
        rssiEl.style.color = getRssiClassification(last.best_rssi).color;
      } else {
        rssiEl.textContent = "--";
        rssiEl.style.color = "";
      }
    }
    _renderRssiTable(last.rssi || {});
  } else {
    if (rssiEl) {
      rssiEl.textContent = "--";
      rssiEl.style.color = "";
    }
  }

  // Update hint based on state
  if (hintEl) {
    const hints = {
      IDLE:          "No scan active. Upload and start an RF Scan mission to collect data.",
      SCAN_READY:    "Mission uploaded. Start RF Scan to begin collecting data.",
      APPROACHING:   "UAV en route to survey start point (Green Dot). Sampling will begin on arrival.",
      SCANNING:      `Collecting samples… ${data.sample_count || 0} samples so far.`,
      SCAN_COMPLETE: `Scan complete — ${data.sample_count || 0} survey samples collected. UAV hovering at final survey waypoint.`,
      ABORTED:       `Scan aborted — ${data.sample_count || 0} samples preserved (incomplete dataset). Reset to start a new scan.`,
      FAILED:        "RF scan failed. Check logs.",
    };
    hintEl.textContent = hints[collectorState] || `State: ${collectorState}`;
  }

  // Also update the RF scan state badge in the RF Scan panel
  const rfStateEl = document.getElementById("stat-rf-state");
  if (rfStateEl && collectorState !== "IDLE") {
    rfStateEl.textContent = collectorState;
  }

  // Phase 5 Requirement 11: SCAN_COMPLETE -> automatically request RF coverage analysis & heatmap
  if (collectorState === "SCAN_COMPLETE" && !state.rfAnalysisAutoTriggered && (data.sample_count || 0) > 0) {
    state.rfAnalysisAutoTriggered = true;
    logEvent("RF survey complete — automatically generating coverage heatmap and candidates…");
    analyzeRfSurvey();
  }
}

/**
 * Fast-update from a single new rf_survey_sample message.
 */
function renderRfSurveySample(data) {
  const samplesEl = document.getElementById("stat-rfs-samples");
  const rssiEl    = document.getElementById("stat-rfs-best-rssi");
  const stateEl   = document.getElementById("stat-rfs-state");
  const hintEl    = document.getElementById("rf-survey-hint");

  const sample = data.sample || {};
  const collectorState = data.state || "SCANNING";

  if (stateEl)   stateEl.textContent = collectorState;
  if (samplesEl && sample.sample_id) samplesEl.textContent = sample.sample_id;
  if (rssiEl) {
    if (sample.best_rssi != null) {
      rssiEl.textContent = `${sample.best_rssi} dBm`;
      rssiEl.style.color = getRssiClassification(sample.best_rssi).color;
    } else {
      rssiEl.textContent = "--";
      rssiEl.style.color = "";
    }
  }
  if (hintEl) hintEl.textContent = `Collecting… sample #${sample.sample_id || "?"} at WP ${sample.current_waypoint || "?"}`;

  _renderRssiTable(sample.rssi || {});

  // Log to mission log on every 10th sample to avoid flooding
  if (sample.sample_id && sample.sample_id % 10 === 0) {
    logEvent(`RF sample #${sample.sample_id}: lat=${sample.latitude?.toFixed(5)}, best=${sample.best_rssi} dBm`);
  }
}

/**
 * Render the per-node RSSI mini-table from the most recent sample.
 */
function _renderRssiTable(rssiDict) {
  const container = document.getElementById("rf-rssi-table-container");
  const table     = document.getElementById("rf-rssi-table");
  if (!container || !table) return;

  const nodeIds = Object.keys(rssiDict);
  if (nodeIds.length === 0) {
    container.classList.add("hidden");
    return;
  }

  container.classList.remove("hidden");
  table.innerHTML = nodeIds.map(id => {
    const val = rssiDict[id];
    const bar = Math.max(0, Math.min(100, Math.round((val + 100) * 2)));
    const { color } = getRssiClassification(val);
    return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;font-family:var(--font-data);font-size:10px">` +
           `<span style="color:#8A9AB0;min-width:64px">${id}</span>` +
           `<div style="flex:1;background:#1c232b;border-radius:2px;height:6px">` +
           `<div style="width:${bar}%;height:6px;background:${color};border-radius:2px"></div></div>` +
           `<span style="color:${color};min-width:54px;text-align:right">${val} dBm</span>` +
           `</div>`;
  }).join("");
}

/**
 * Reset the RF survey data on the backend and clear the live panel.
 */
async function resetSurveyData() {
  const btn = document.getElementById("btn-reset-rf-survey");
  if (btn) btn.disabled = true;

  try {
    await apiPost("/api/rf-survey/reset", {});
    rfSurveyWsState.lastData    = null;
    rfSurveyWsState.latestSample = null;

    const stateEl   = document.getElementById("stat-rfs-state");
    const samplesEl = document.getElementById("stat-rfs-samples");
    const rssiEl    = document.getElementById("stat-rfs-best-rssi");
    const nodesEl   = document.getElementById("stat-rfs-nodes");
    const hintEl    = document.getElementById("rf-survey-hint");
    const container = document.getElementById("rf-rssi-table-container");
    const rfStateEl = document.getElementById("stat-rf-state");

    if (stateEl)   stateEl.textContent   = "IDLE";
    if (samplesEl) samplesEl.textContent = "0";
    if (rssiEl)    rssiEl.textContent    = "--";
    if (nodesEl)   nodesEl.textContent   = state.deployedNodes.length;
    if (hintEl)    hintEl.textContent    = "Survey data cleared. Ready for next scan.";
    if (container) container.classList.add("hidden");
    if (rfStateEl) rfStateEl.textContent = "IDLE";

    // Phase 5 Requirement 27: New survey invalidates old analysis
    resetRfAnalysisState("Survey data reset. Run a new scan to analyze.");

    logEvent("RF survey data reset to IDLE.");
  } catch (err) {
    logEvent(`RF survey reset failed: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Wire up controls
// ---------------------------------------------------------------------------

function initControls() {
  document.getElementById("btn-draw").addEventListener("click", startDrawing);
  document.getElementById("btn-finish").addEventListener("click", finishArea);
  document.getElementById("btn-clear").addEventListener("click", clearArea);
  document.getElementById("btn-analyze").addEventListener("click", analyzeArea);
  document.getElementById("btn-generate-mission").addEventListener("click", generateMission);
  // Phase 8 buttons
  document.getElementById("btn-upload-mission").addEventListener("click", uploadMission);
  document.getElementById("btn-start-mission").addEventListener("click", startMission);
  document.getElementById("btn-abort-mission").addEventListener("click", abortMission);
  // Arm/Disarm buttons
  document.getElementById("btn-arm").addEventListener("click", armVehicle);
  document.getElementById("btn-disarm").addEventListener("click", disarmVehicle);
  // Return to Home button
  const returnHomeBtn = document.getElementById("btn-return-home");
  if (returnHomeBtn) {
    returnHomeBtn.addEventListener("click", returnHome);
  }
  // Manual Override buttons
  const manualBtn = document.getElementById("btn-manual-control");
  if (manualBtn) manualBtn.addEventListener("click", enterManualControl);
  const resumeBtn = document.getElementById("btn-resume-mission");
  if (resumeBtn) resumeBtn.addEventListener("click", resumeMission);
  // Node Deployment (Phase 1)
  const autoDeployBtn = document.getElementById("btn-auto-deploy");
  if (autoDeployBtn) autoDeployBtn.addEventListener("click", autoDeploy);
  // RF Scan Survey (Phase 2)
  const rfScanBtn = document.getElementById("btn-rf-scan");
  if (rfScanBtn) rfScanBtn.addEventListener("click", handleRfScan);
  const uploadRfBtn = document.getElementById("btn-upload-rf-scan");
  if (uploadRfBtn) uploadRfBtn.addEventListener("click", uploadRfScanMission);
  const startRfBtn = document.getElementById("btn-start-rf-scan");
  if (startRfBtn) startRfBtn.addEventListener("click", startMission);
  // Phase 3 — RF Survey Live Data reset button
  const resetRfBtn = document.getElementById("btn-reset-rf-survey");
  if (resetRfBtn) resetRfBtn.addEventListener("click", resetSurveyData);
  // Phase 4 — Delete Node button
  const deleteNodeBtn = document.getElementById("btn-delete-node");
  if (deleteNodeBtn) {
    deleteNodeBtn.addEventListener("click", () => {
      const selectEl = document.getElementById("select-delete-node");
      if (selectEl && selectEl.value) {
        deleteDeployedNode(selectEl.value);
      }
    });
  }
  // Phase 5 — RF coverage analysis
  const analyzeRfBtn = document.getElementById("btn-analyze-rf");
  if (analyzeRfBtn) analyzeRfBtn.addEventListener("click", analyzeRfSurvey);
  // Phase 5 — heatmap toggle/opacity controls (wired after map is ready)
  initRfHeatmapControls();
  // Phase 6 — deployment verification controls
  initVerificationControls();
  // Phase 6 — survey history controls
  initSurveyHistoryControls();
}


// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  // Phase 4 Final: Fresh session begins with clean state (0 deployed nodes, RF collector IDLE)
  try {
    await apiPost("/api/session/init", {});
  } catch (err) {
    console.warn("Session init notice:", err.message);
  }

  // Initialize map first so LayerGroups and markers can attach properly
  initMap(FALLBACK_CENTER.lat, FALLBACK_CENTER.lon);
  initControls();

  // Load and render active deployed nodes (clean session = 0 nodes)
  const nodes = await loadNodes();
  if (Array.isArray(nodes) && nodes.length > 0) {
    map.setView([nodes[0].lat, nodes[0].lon], 16);
  }

  connectTelemetry();
  startTelemetryStaleWatch();
  renderTelemetryPanel();

  // Phase 3 — connect to RF survey real-time stream alongside telemetry.
  connectRfSurveyWs();

  // Phase 6 — populate RF survey history (last 5 completed runs)
  fetchSurveyHistory();

  // Phase 5 — try to restore cached RF analysis from backend (survives page reload)
  try {
    const res = await apiGet("/api/rf-survey/analysis");
    if (res && !res.error && res.survey_samples > 0) {
      state.rfAnalysis = res;
      updateRfCoverageSummary(res);
      renderRfHeatmap(res.heatmap, state.rfHeatmapOpacity);
      renderRfGapPoints(res.gap_points);
      renderRfCandidates(res.candidates);
      const summaryEl = document.getElementById("rf-coverage-summary");
      if (summaryEl) summaryEl.classList.remove("hidden");
      const ctrlEl = document.getElementById("rf-heatmap-controls");
      if (ctrlEl) ctrlEl.classList.remove("hidden");
      const hintEl = document.getElementById("rf-analysis-hint");
      if (hintEl) hintEl.textContent = `Previous analysis restored: ${res.survey_samples} samples, ${res.candidates.length} candidates.`;
      logEvent(`RF analysis restored from server: ${res.survey_samples} samples.`);
    }
  } catch (_) {
    /* no cached analysis — that's fine */
  }

  // Phase 6 — try to restore verification state from backend
  try {
    const verif = await apiGet("/api/rf-survey/verification");
    if (verif && !verif.error) {
      state.rfPhase6State = verif.phase6_state || state.rfPhase6State;
      state.newlyDeployedNodeId = verif.newly_deployed_node_id || null;
      state.rfBeforeAnalysis = verif.before || null;
      state.rfAfterAnalysis = verif.after || null;
      state.rfComparison = verif.comparison || null;

      if (state.newlyDeployedNodeId) {
        renderAllDeployedNodes();
      }

      if (verif.comparison && verif.before && verif.after) {
        renderVerificationPanel(verif.comparison, verif.before, verif.after);
        const viewSel = document.getElementById("heatmap-view-selector-container");
        if (viewSel) viewSel.classList.remove("hidden");
      }
    }
  } catch (_) {
    /* no cached verification state */
  }

  initGamepadListeners();
  _updateGamepadStat();
  _updateOverrideStat();

  logEvent("GCS initialized — Phase 6 ready.");
}

boot();
