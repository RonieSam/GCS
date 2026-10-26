/**
 * E-Mesh Simplified Citizen Client API Wrapper
 * Zero-auth, mobile-first, robust mesh SOS and geolocation handling.
 */

(function () {
  const currentHost = window.location.hostname || 'localhost';
  const currentPort = window.location.port ? `:${window.location.port}` : '';
  
  // Prefer relative API path when served directly from backend, otherwise fall back to port 8000
  let API_BASE = '/api/v1';
  if (window.location.protocol === 'file:' || (window.location.port !== '8000' && window.location.port !== '8443')) {
    API_BASE = `http://${currentHost}:8000/api/v1`;
  }

  // Persistent anonymous client session identifier
  function getOrCreateClientId() {
    let cid = localStorage.getItem('emesh_client_id');
    if (!cid) {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        cid = 'client_' + crypto.randomUUID().replace(/-/g, '').slice(0, 12);
      } else {
        cid = 'client_' + Math.random().toString(36).substring(2, 14);
      }
      localStorage.setItem('emesh_client_id', cid);
    }
    return cid;
  }

  const clientId = getOrCreateClientId();

  window.API = {
    clientId,

    async request(endpoint, options = {}) {
      const url = `${API_BASE}${endpoint}`;
      const headers = {
        'Content-Type': 'application/json',
        ...options.headers
      };

      try {
        const response = await fetch(url, { ...options, headers });
        const data = await response.json().catch(() => null);

        if (!response.ok) {
          let errorMsg = `Server error (${response.status})`;
          if (data) {
            if (typeof data.detail === 'string') {
              errorMsg = data.detail;
            } else if (Array.isArray(data.detail)) {
              errorMsg = data.detail.map(err => {
                const cleanMsg = err.msg ? err.msg.replace(/^Value error,\s*/i, '') : 'Invalid value';
                return cleanMsg;
              }).join(' | ');
            } else if (data.message) {
              errorMsg = data.message;
            }
          }
          throw new Error(errorMsg);
        }

        return data;
      } catch (error) {
        if (error.name === 'TypeError' && error.message.includes('fetch')) {
          throw new Error("Mesh gateway unreachable. Check Wi-Fi connection to E-MESH.");
        }
        throw error;
      }
    },

    // ── SOS Submission ───────────────────────────────────────────────────────
    async sendSOS({ peopleCount = 1, notes = "", latitude = null, longitude = null, accuracy = null }) {
      const payload = {
        people_count: Number(peopleCount) || 1,
        notes: notes ? notes.trim() : undefined,
        latitude: latitude !== null ? Number(latitude) : undefined,
        longitude: longitude !== null ? Number(longitude) : undefined,
        accuracy: accuracy !== null ? Number(accuracy) : undefined,
        client_id: this.clientId
      };

      return await this.request('/sos', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
    },

    // ── Client Location Reporting ────────────────────────────────────────────
    async updateLocation(lat, lng, accuracy) {
      if (lat == null || lng == null) return;
      try {
        await this.request('/location', {
          method: 'POST',
          body: JSON.stringify({
            latitude: Number(lat),
            longitude: Number(lng),
            accuracy: accuracy != null ? Number(accuracy) : null,
            client_id: this.clientId
          })
        });
      } catch (e) {
        // Non-blocking location update failure
        console.debug('[E-Mesh] Location sync notice:', e.message);
      }
    },

    // ── Browser Geolocation Engine ───────────────────────────────────────────
    _locationWatchId: null,
    _locationIntervalId: null,
    _lastPosition: null,

    startLocationTracking(onLocationChange, onError) {
      if (!navigator.geolocation) {
        if (onError) onError({ code: 0, message: "Geolocation not supported by this browser (requires HTTPS/localhost)." });
        return;
      }

      if (this._locationWatchId !== null) return;

      const onSuccess = (pos) => {
        const { latitude, longitude, accuracy } = pos.coords;
        // Basic validity check: never allow NaN or (0, 0)
        if (typeof latitude !== 'number' || typeof longitude !== 'number' || (latitude === 0 && longitude === 0)) {
          return;
        }

        this._lastPosition = { latitude, longitude, accuracy: accuracy || null };
        this.updateLocation(latitude, longitude, accuracy);
        if (onLocationChange) onLocationChange(this._lastPosition);
      };

      const handleErr = (err) => {
        console.warn('[E-Mesh] Geolocation status:', err.message);
        if (onError) onError(err);
      };

      const opts = {
        enableHighAccuracy: true,
        maximumAge: 10000,
        timeout: 12000
      };

      // Initial fast fix
      navigator.geolocation.getCurrentPosition(onSuccess, handleErr, {
        enableHighAccuracy: false,
        timeout: 6000
      });

      // Continuous watcher
      this._locationWatchId = navigator.geolocation.watchPosition(onSuccess, handleErr, opts);

      // Periodic 20s heartbeat to keep connected client active on GCS
      this._locationIntervalId = setInterval(() => {
        if (this._lastPosition) {
          this.updateLocation(
            this._lastPosition.latitude,
            this._lastPosition.longitude,
            this._lastPosition.accuracy
          );
        } else {
          navigator.geolocation.getCurrentPosition(onSuccess, handleErr, opts);
        }
      }, 20000);
    },

    stopLocationTracking() {
      if (this._locationWatchId !== null) {
        navigator.geolocation.clearWatch(this._locationWatchId);
        this._locationWatchId = null;
      }
      if (this._locationIntervalId !== null) {
        clearInterval(this._locationIntervalId);
        this._locationIntervalId = null;
      }
      this._lastPosition = null;
    },

    getLastKnownPosition() {
      return this._lastPosition;
    },

    setManualPosition(latitude, longitude, accuracy = 10) {
      this._lastPosition = { latitude: Number(latitude), longitude: Number(longitude), accuracy: Number(accuracy) };
      this.updateLocation(this._lastPosition.latitude, this._lastPosition.longitude, this._lastPosition.accuracy);
      return this._lastPosition;
    },

    // ── WebSocket Connectivity ───────────────────────────────────────────────
    ws: null,
    wsReconnectTimer: null,
    _httpHealthInterval: null,

    connectWebSocket(onStatusChange) {
      // Periodic HTTP health check so mesh status is immediately ONLINE even if WS upgrade is blocked
      const pingHttpHealth = async () => {
        try {
          const res = await fetch(`${API_BASE}/nodes?page=1&page_size=1`, { method: 'GET' });
          if (res.ok && onStatusChange) {
            onStatusChange(true);
          }
        } catch (_) {}
      };
      pingHttpHealth();
      if (!this._httpHealthInterval) {
        this._httpHealthInterval = setInterval(pingHttpHealth, 6000);
      }

      if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
        return;
      }

      const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const curPort = window.location.port;
      let wsPort = ':8000';
      if (curPort === '8000' || curPort === '8001' || curPort === '8443') {
        wsPort = `:${curPort}`;
      }
      const wsHost = window.location.hostname || 'localhost';
      const wsUrl = `${wsProto}//${wsHost}${wsPort}/api/v1/ws?client_id=${encodeURIComponent(this.clientId)}`;

      try {
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
          console.log('[E-Mesh WS] Connected to mesh gateway');
          if (onStatusChange) onStatusChange(true);
        };

        this.ws.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            if (payload.type === 'ping') {
              this.ws.send(JSON.stringify({ type: 'pong' }));
            }
          } catch (e) {}
        };

        this.ws.onclose = () => {
          // If WS closes, do not immediately flip to offline if HTTP is reachable
          clearTimeout(this.wsReconnectTimer);
          this.wsReconnectTimer = setTimeout(() => this.connectWebSocket(onStatusChange), 5000);
        };

        this.ws.onerror = () => {
          // Handled via HTTP fallback
        };
      } catch (err) {
        // Handled via HTTP fallback
      }
    }
  };
})();
