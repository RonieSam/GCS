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
// Node display (loaded from the backend, which seeds from data/nodes.json)
// ---------------------------------------------------------------------------

/**
 * loadNodes — fetches node definitions from the backend and stores them
 * in state.availableNodes.  Does NOT draw anything on the map.
 * Returns the list so boot() can use it to centre the map.
 */
async function loadNodes() {
  try {
    state.availableNodes = await apiGet(NODES_URL);
  } catch (err) {
    logEvent(`Could not load nodes from ${NODES_URL} (${err.message}) — using built-in fallback nodes.`);
    state.availableNodes = [
      { id: "NODE-001", lat: 13.0827, lon: 80.2707, coverage_radius_m: 250 },
      { id: "NODE-002", lat: 13.0891, lon: 80.2785, coverage_radius_m: 250 },
      { id: "NODE-003", lat: 13.0774, lon: 80.2812, coverage_radius_m: 250 },
    ];
  }
  return state.availableNodes;
}

/**
 * addDeployedNode — renders a single node onto the shared nodeLayerGroup
 * and appends it to state.deployedNodes.
 *
 * Using this helper (rather than drawing directly to `map`) means:
 *   - Every deployed node lives in the same LayerGroup, so we can
 *     add Node 4 later without touching Node 1-3 markers.
 *   - state.deployedNodes is the single source of truth for what is shown.
 */
function addDeployedNode(node) {
  // Ensure the shared layer group exists
  if (!state.nodeLayerGroup) {
    state.nodeLayerGroup = L.layerGroup().addTo(map);
  }

  const marker = L.circleMarker([node.lat, node.lon], {
    radius: 6,
    color: "#3FDA7F",
    fillColor: "#3FDA7F",
    fillOpacity: 0.9,
    weight: 2,
  }).addTo(state.nodeLayerGroup);

  marker.bindTooltip(node.id, {
    permanent: true,
    direction: "top",
    offset: [0, -6],
    className: "node-label",
  });

  L.circle([node.lat, node.lon], {
    radius: node.coverage_radius_m,
    color: "#3FDA7F",
    weight: 1,
    fillColor: "#3FDA7F",
    fillOpacity: 0.08,
    dashArray: "4 4",
  }).addTo(state.nodeLayerGroup);

  state.deployedNodes.push(node);
}

/**
 * selectDeploymentLocation — single shared entry point for setting the
 * pending deployment location, regardless of whether it came from a direct
 * map click or a candidate selection.
 *
 * @param {number} lat
 * @param {number} lon
 * @param {'map'|'candidate'} source  - for display/logging only
 */
function selectDeploymentLocation(lat, lon, source) {
  state.selectedDeploymentLocation = { lat, lon, source };

  // Show / move the temporary selection marker (cyan crosshair ring)
  if (state.deploymentSelectionMarker) {
    state.deploymentSelectionMarker.setLatLng([lat, lon]);
  } else {
    state.deploymentSelectionMarker = L.circleMarker([lat, lon], {
      radius: 10,
      color: "#00E5FF",
      fillColor: "#00E5FF",
      fillOpacity: 0.18,
      weight: 2.5,
      dashArray: "4 3",
    }).addTo(map);
  }

  // Bind a tooltip so the operator can see the coords at a glance
  state.deploymentSelectionMarker.bindTooltip(
    `Deploy here (${source})`,
    { direction: "top", offset: [0, -10], className: "node-label" }
  ).openTooltip();

  // Update the Node Deployment panel
  const locText = document.getElementById("deploy-location-text");
  if (locText) locText.textContent = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;

  const srcEl = document.getElementById("stat-deploy-source");
  if (srcEl) srcEl.textContent = source.toUpperCase();

  const hintEl = document.getElementById("deploy-hint");
  if (hintEl) hintEl.textContent = "Location selected — press AUTO DEPLOY to place a node here.";

  const deployBtn = document.getElementById("btn-auto-deploy");
  if (deployBtn) deployBtn.disabled = false;

  logEvent(`Deployment location selected (${source}): lat=${lat.toFixed(5)}, lon=${lon.toFixed(5)}`);
}

// Running counter for deployed-node IDs (session-scoped, starts at 1)
let _deployNodeSeq = 0;

/**
 * autoDeploy — creates a new logical communication node at
 * state.selectedDeploymentLocation and renders it on the map.
 *
 * This is the single deployment path for both map-click and candidate-select.
 * It does NOT touch the UAV marker, the mission system, or existing nodes.
 */
function autoDeploy() {
  if (!state.selectedDeploymentLocation) {
    logEvent("AUTO DEPLOY: no location selected. Click the map or pick a candidate first.");
    return;
  }

  const { lat, lon } = state.selectedDeploymentLocation;
  _deployNodeSeq++;
  const nodeId = `COMM-${String(_deployNodeSeq).padStart(3, "0")}`;

  // Standard coverage radius — same as existing nodes
  const node = { id: nodeId, lat, lon, coverage_radius_m: 250 };
  addDeployedNode(node);

  // Remove the temporary selection marker now that the node is permanent
  if (state.deploymentSelectionMarker) {
    map.removeLayer(state.deploymentSelectionMarker);
    state.deploymentSelectionMarker = null;
  }

  // Clear the selection state
  state.selectedDeploymentLocation = null;

  // Update stat counters
  const countEl = document.getElementById("stat-deployed-count");
  if (countEl) countEl.textContent = state.deployedNodes.length;

  // Also keep the legacy "Existing Nodes" stat in Area Planning in sync
  const nodesEl = document.getElementById("stat-nodes");
  if (nodesEl) nodesEl.textContent = state.deployedNodes.length;

  // Reset the Node Deployment panel
  const locText = document.getElementById("deploy-location-text");
  if (locText) locText.textContent = "None";
  const srcEl = document.getElementById("stat-deploy-source");
  if (srcEl) srcEl.textContent = "--";
  const hintEl = document.getElementById("deploy-hint");
  if (hintEl) hintEl.textContent = "Click the map or select a candidate to set a deployment location.";

  const deployBtn = document.getElementById("btn-auto-deploy");
  if (deployBtn) deployBtn.disabled = true;

  logEvent(
    `AUTO DEPLOY: node ${nodeId} deployed at lat=${lat.toFixed(5)}, lon=${lon.toFixed(5)}. ` +
    `Total deployed: ${state.deployedNodes.length}.`
  );
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
    const result = await apiPost("/api/select-target", { lat: candidate.lat, lon: candidate.lon });
    if (result.status !== 200) throw new Error(result.body && result.body.detail);

    state.selectedTarget = { lat: candidate.lat, lon: candidate.lon };

    document.getElementById("mission-lat").value = candidate.lat.toFixed(6);
    document.getElementById("mission-lon").value = candidate.lon.toFixed(6);
    document.getElementById("btn-generate-mission").disabled = false;
    document.getElementById("mission-hint").textContent =
      `Location ${label} selected — set altitude and generate the mission.`;

    if (state.selectedMarker) map.removeLayer(state.selectedMarker);
    state.selectedMarker = L.circleMarker([candidate.lat, candidate.lon], {
      radius: 12,
      color: "#FFB020",
      fillOpacity: 0,
      weight: 3,
    }).addTo(map);

    logEvent(`Location ${label} selected — lat=${candidate.lat.toFixed(5)}, lon=${candidate.lon.toFixed(5)}.`);
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

    // Enable Start; keep Upload enabled (re-upload allowed).
    btn.disabled = false;
    document.getElementById("btn-start-mission").disabled = false;
    document.getElementById("btn-abort-mission").disabled = false;

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
  btn.disabled = true;
  document.getElementById("mission-hint").textContent = "Commanding PX4 into mission mode…";
  logEvent("Start Mission commanded.");

  try {
    const result = await apiPost("/api/mission/start", {});
    const body = result.body;

    if (result.status === 400 || result.status === 503) {
      const msg = body && body.detail ? body.detail : JSON.stringify(body);
      document.getElementById("mission-hint").textContent = `Start failed: ${msg}`;
      logEvent(`Start Mission failed: ${msg}`);
      btn.disabled = false;
      return;
    }

    if (!body.success) {
      document.getElementById("mission-hint").textContent =
        `Start failed: ${body.error || "PX4 rejected mode change"}`;
      logEvent(`Start Mission rejected: ${body.error}`);
      btn.disabled = false;
      return;
    }

    // PX4 entered mission mode.
    state.missionExecuting = true;
    document.getElementById("stat-mission-state").textContent = "EXECUTING";
    document.getElementById("mission-hint").textContent =
      "PX4 in mission mode. Watch telemetry for movement.";
    logEvent("PX4 entered MISSION mode — UAV executing mission.");

    // Disable Start while executing; Abort stays enabled.
    btn.disabled = true;
    document.getElementById("btn-abort-mission").disabled = false;

  } catch (err) {
    document.getElementById("mission-hint").textContent = `Start error: ${err.message}`;
    logEvent(`Start Mission error: ${err.message}`);
    btn.disabled = !state.missionUploaded;
  }
}

async function abortMission() {
  const btn = document.getElementById("btn-abort-mission");
  btn.disabled = true;
  document.getElementById("mission-hint").textContent = "Sending RTL (Return-to-Launch)…";
  logEvent("Abort (RTL) commanded.");

  try {
    const result = await apiPost("/api/mission/abort", {});
    const body = result.body;

    if (result.status === 503) {
      const msg = body && body.detail ? body.detail : "PX4 not connected";
      document.getElementById("mission-hint").textContent = `Abort failed: ${msg}`;
      logEvent(`Abort failed: ${msg}`);
      btn.disabled = false;
      return;
    }

    if (!body.success) {
      document.getElementById("mission-hint").textContent =
        `Abort failed: ${body.error || "PX4 rejected RTL"}`;
      logEvent(`Abort rejected: ${body.error}`);
      btn.disabled = false;
      return;
    }

    state.missionExecuting = false;
    document.getElementById("stat-mission-state").textContent = "ABORTED";
    document.getElementById("mission-hint").textContent =
      "RTL commanded — PX4 returning to launch point.";
    logEvent("Mission aborted — PX4 returning to launch (RTL).");

    document.getElementById("btn-start-mission").disabled = false;
    btn.disabled = false;

  } catch (err) {
    document.getElementById("mission-hint").textContent = `Abort error: ${err.message}`;
    logEvent(`Abort error: ${err.message}`);
    btn.disabled = false;
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
  }

  // Update Manual Override button gating whenever telemetry refreshes
  _updateManualButtons();
  _updateOverrideStat();

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
  const container = document.getElementById("rf-waypoints-container");
  if (container) container.classList.add("hidden");
  const list = document.getElementById("rf-waypoints-list");
  if (list) list.innerHTML = "";
  const hintEl = document.getElementById("rf-scan-hint");
  if (hintEl) hintEl.textContent = "Define an affected area, then click RF SCAN to generate a survey path.";
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

    // Update UI stats
    const stateEl = document.getElementById("stat-rf-state");
    if (stateEl) stateEl.textContent = data.state;
    const wpEl = document.getElementById("stat-rf-waypoints");
    if (wpEl) wpEl.textContent = data.waypoint_count;
    const linesEl = document.getElementById("stat-rf-lines");
    if (linesEl) linesEl.textContent = data.line_count;
    const distEl = document.getElementById("stat-rf-distance");
    if (distEl) distEl.textContent = `${data.total_distance_m} m`;

    // Render path on map
    renderRfScanPath(data.waypoints);

    // Populate waypoint inspection list
    const container = document.getElementById("rf-waypoints-container");
    const list = document.getElementById("rf-waypoints-list");
    const summary = document.getElementById("rf-waypoints-summary");

    if (container && list) {
      container.classList.remove("hidden");
      if (summary) summary.textContent = `${data.waypoint_count} waypoints, ${data.line_count} lines`;

      list.innerHTML = data.waypoints.map(wp => `
        <div class="rf-wp-item">
          <span class="rf-wp-seq">WP #${wp.seq} (L${wp.line_idx + 1})</span>
          <span class="rf-wp-coords">${wp.lat.toFixed(5)}, ${wp.lon.toFixed(5)} [${wp.alt}m]</span>
        </div>
      `).join("");
    }

    if (hintEl) {
      hintEl.textContent = `Survey path generated (${data.waypoint_count} WPs, ${data.line_count} lines, ${data.total_distance_m}m).`;
    }
    logEvent(
      `RF survey mission generated: ${data.waypoint_count} waypoints across ${data.line_count} lines, total dist ${data.total_distance_m}m.`
    );
  } catch (err) {
    if (hintEl) hintEl.textContent = `Error: ${err.message}`;
    logEvent(`RF SCAN generation failed: ${err.message}`);
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
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  // Load node definitions (inventory) so we can centre the map — but
  // do NOT draw them yet.  The operator must press AUTO DEPLOY INITIAL
  // NODES to place them on the map (Phase 1 requirement).
  const nodes = await loadNodes();

  const centerLat = nodes.length ? nodes[0].lat : FALLBACK_CENTER.lat;
  const centerLon = nodes.length ? nodes[0].lon : FALLBACK_CENTER.lon;

  initMap(centerLat, centerLon);
  // drawNodes() is intentionally NOT called here — deployedNodes starts empty.
  initControls();

  connectTelemetry();
  startTelemetryStaleWatch();
  renderTelemetryPanel();

  initGamepadListeners();
  _updateGamepadStat();
  _updateOverrideStat();

  logEvent("GCS initialized — Phase 8 ready. Press AUTO DEPLOY INITIAL NODES to place communication nodes.");
}

boot();
