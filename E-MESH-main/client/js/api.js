/**
 * E-Mesh Simplified Citizen Client API Wrapper
 * Zero-auth, mobile-first, robust mesh SOS and high-accuracy geolocation handling.
 */

(function () {
  const currentHost = window.location.hostname || 'localhost';
  
  // Prefer relative API path on http/https so origin, protocol, and port match naturally.
  // This completely eliminates Mixed Content errors on mobile browsers.
  let API_BASE = '/api/v1';
  if (window.location.protocol === 'file:') {
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
    API_BASE,

    // Real-time diagnostics state for verification on campus
    diagnostics: {
      rawLatitude: null,
      rawLongitude: null,
      horizontalAccuracy: null,
      positionAcquiredAt: null,
      lastSyncTime: null,
      isFresh: false,
      permissionStatus: "INITIALIZING",
      backendSyncStatus: "NOT_SYNCED",
      syncCount: 0,
      syncError: null,
      isSecureContext: (typeof window !== 'undefined' && window.isSecureContext === true),
    },

    _diagListeners: [],

    onDiagnosticsChange(callback) {
      if (typeof callback === 'function') {
        this._diagListeners.push(callback);
        callback(this.diagnostics);
      }
    },

    _notifyDiagnostics() {
      for (const cb of this._diagListeners) {
        try { cb(this.diagnostics); } catch (e) { console.error(e); }
      }
    },

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
    async sendSOS({ peopleCount = 1, notes = "", latitude = null, longitude = null, accuracy = null, timestamp = null }) {
      const payload = {
        people_count: Number(peopleCount) || 1,
        notes: notes ? notes.trim() : undefined,
        latitude: latitude !== null && latitude !== undefined ? Number(latitude) : undefined,
        longitude: longitude !== null && longitude !== undefined ? Number(longitude) : undefined,
        accuracy: accuracy !== null && accuracy !== undefined ? Number(accuracy) : undefined,
        timestamp: timestamp !== null && timestamp !== undefined ? Number(timestamp) : undefined,
        client_id: this.clientId
      };

      const result = await this.request('/sos', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      this.diagnostics.lastSyncTime = new Date();
      this.diagnostics.backendSyncStatus = "SOS_ACKNOWLEDGED";
      this._notifyDiagnostics();

      return result;
    },

    // ── Client Location Reporting ────────────────────────────────────────────
    async updateLocation(lat, lng, accuracy, timestamp) {
      if (lat == null || lng == null) return;
      const nLat = Number(lat);
      const nLng = Number(lng);
      if (!isFinite(nLat) || !isFinite(nLng) || (nLat === 0 && nLng === 0)) return;

      const nAcc = accuracy != null && isFinite(Number(accuracy)) ? Number(accuracy) : null;
      const ts = timestamp != null && isFinite(Number(timestamp)) ? Number(timestamp) : (Date.now() / 1000);

      this.diagnostics.backendSyncStatus = "TRANSMITTING";
      this._notifyDiagnostics();

      try {
        await this.request('/location', {
          method: 'POST',
          body: JSON.stringify({
            latitude: nLat,
            longitude: nLng,
            accuracy: nAcc,
            timestamp: ts,
            client_id: this.clientId
          })
        });

        this.diagnostics.lastSyncTime = new Date();
        this.diagnostics.syncCount = (this.diagnostics.syncCount || 0) + 1;
        this.diagnostics.backendSyncStatus = "ACKNOWLEDGED_BY_SERVER";
        this.diagnostics.syncError = null;
        this._notifyDiagnostics();
      } catch (e) {
        this.diagnostics.backendSyncStatus = "SYNC_FAILED";
        this.diagnostics.syncError = e.message;
        this._notifyDiagnostics();
        console.debug('[E-Mesh] Location sync notice:', e.message);
      }
    },

    // ── Browser Geolocation Engine ───────────────────────────────────────────
    _locationWatchId: null,
    _locationIntervalId: null,
    _lastPosition: null,

    startLocationTracking(onLocationChange, onError) {
      const isSec = typeof window !== 'undefined' && window.isSecureContext === true;
      this.diagnostics.isSecureContext = isSec;

      if (!navigator.geolocation) {
        const msg = "Geolocation not supported by this browser (requires HTTPS/localhost).";
        this.diagnostics.permissionStatus = "UNSUPPORTED";
        this._notifyDiagnostics();
        if (onError) onError({ code: 0, message: msg });
        return;
      }

      if (!isSec) {
        console.warn("[E-Mesh] Warning: Page loaded over insecure origin (HTTP). Modern mobile browsers block GPS hardware on HTTP.");
        this.diagnostics.permissionStatus = "INSECURE_HTTP";
        this._notifyDiagnostics();
      }

      if (this._locationWatchId !== null) return;

      const onSuccess = (pos) => {
        const { latitude, longitude, accuracy } = pos.coords;
        if (typeof latitude !== 'number' || typeof longitude !== 'number' || !isFinite(latitude) || !isFinite(longitude)) {
          return;
        }
        if (latitude === 0 && longitude === 0) {
          return;
        }
        if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) {
          return;
        }

        const fixTimeMs = (pos.timestamp && pos.timestamp > 0) ? pos.timestamp : Date.now();
        const fixDate = new Date(fixTimeMs);
        const ageSec = Math.max(0, (Date.now() - fixTimeMs) / 1000);
        const isFresh = ageSec <= 30;

        // Position Quality Guard:
        // Do NOT allow an incoming coarse fix (e.g. cell tower accuracy ±1500m) to overwrite
        // an existing high-accuracy GPS fix (e.g. ±5m) if the high-accuracy fix is still fresh.
        if (this._lastPosition) {
          const oldAcc = this._lastPosition.accuracy || 999999;
          const oldTs = this._lastPosition.timestamp || 0;
          const oldAgeSec = Math.max(0, (Date.now() - oldTs) / 1000);

          if (fixTimeMs < oldTs - 3000) {
            // Older fix from browser cache — ignore
            return;
          }
          if (accuracy && accuracy > 300 && oldAcc < 50 && oldAgeSec < 45) {
            console.debug("[E-Mesh] Ignoring low-accuracy coarse fix (±" + accuracy + "m) in favor of fresh high-accuracy fix (±" + oldAcc + "m)");
            return;
          }
        }

        this._lastPosition = {
          latitude: Number(latitude),
          longitude: Number(longitude),
          accuracy: accuracy != null && isFinite(accuracy) ? Number(accuracy) : null,
          timestamp: fixTimeMs,
          acquired_at: fixDate.toISOString(),
          is_fresh: isFresh,
        };

        // Update real-time diagnostics
        this.diagnostics.rawLatitude = this._lastPosition.latitude;
        this.diagnostics.rawLongitude = this._lastPosition.longitude;
        this.diagnostics.horizontalAccuracy = this._lastPosition.accuracy;
        this.diagnostics.positionAcquiredAt = fixDate;
        this.diagnostics.isFresh = isFresh;
        this.diagnostics.permissionStatus = "GRANTED";
        this._notifyDiagnostics();

        // Send to backend with acquisition timestamp
        this.updateLocation(
          this._lastPosition.latitude,
          this._lastPosition.longitude,
          this._lastPosition.accuracy,
          fixTimeMs / 1000
        );

        if (onLocationChange) onLocationChange(this._lastPosition);
      };

      const handleErr = (err) => {
        console.warn('[E-Mesh] Geolocation status:', err.message);
        if (err.code === 1) {
          this.diagnostics.permissionStatus = "DENIED";
        } else if (err.code === 2) {
          this.diagnostics.permissionStatus = "UNAVAILABLE";
        } else if (err.code === 3) {
          this.diagnostics.permissionStatus = "TIMEOUT";
        } else {
          this.diagnostics.permissionStatus = "ERROR";
        }
        this._notifyDiagnostics();
        if (onError) onError(err);
      };

      // Strict high-accuracy options: hardware GPS chip required
      const watchOpts = {
        enableHighAccuracy: true,
        maximumAge: 3000,
        timeout: 15000
      };

      this.diagnostics.permissionStatus = "ACQUIRING";
      this._notifyDiagnostics();

      // Initial high-accuracy fix request (never use enableHighAccuracy: false)
      navigator.geolocation.getCurrentPosition(onSuccess, handleErr, {
        enableHighAccuracy: true,
        maximumAge: 0,
        timeout: 15000
      });

      // Continuous high-accuracy watcher
      this._locationWatchId = navigator.geolocation.watchPosition(onSuccess, handleErr, watchOpts);

      // Periodic 20s heartbeat to keep connected client active on GCS
      this._locationIntervalId = setInterval(() => {
        if (this._lastPosition) {
          const ageSec = Math.max(0, (Date.now() - (this._lastPosition.timestamp || 0)) / 1000);
          this._lastPosition.is_fresh = (ageSec <= 35);
          this.diagnostics.isFresh = this._lastPosition.is_fresh;
          this._notifyDiagnostics();

          this.updateLocation(
            this._lastPosition.latitude,
            this._lastPosition.longitude,
            this._lastPosition.accuracy,
            (this._lastPosition.timestamp || Date.now()) / 1000
          );
        } else {
          navigator.geolocation.getCurrentPosition(onSuccess, handleErr, {
            enableHighAccuracy: true,
            maximumAge: 0,
            timeout: 10000
          });
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

    // Refresh control for manual/operator triggered location refresh
    refreshLocation() {
      return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
          const err = new Error("Geolocation not supported by this browser.");
          reject(err);
          return;
        }

        this.diagnostics.permissionStatus = "REFRESHING";
        this._notifyDiagnostics();

        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const { latitude, longitude, accuracy } = pos.coords;
            const fixTimeMs = (pos.timestamp && pos.timestamp > 0) ? pos.timestamp : Date.now();
            const fixDate = new Date(fixTimeMs);

            this._lastPosition = {
              latitude: Number(latitude),
              longitude: Number(longitude),
              accuracy: accuracy != null && isFinite(accuracy) ? Number(accuracy) : null,
              timestamp: fixTimeMs,
              acquired_at: fixDate.toISOString(),
              is_fresh: true,
            };

            this.diagnostics.rawLatitude = this._lastPosition.latitude;
            this.diagnostics.rawLongitude = this._lastPosition.longitude;
            this.diagnostics.horizontalAccuracy = this._lastPosition.accuracy;
            this.diagnostics.positionAcquiredAt = fixDate;
            this.diagnostics.isFresh = true;
            this.diagnostics.permissionStatus = "GRANTED";
            this._notifyDiagnostics();

            this.updateLocation(
              this._lastPosition.latitude,
              this._lastPosition.longitude,
              this._lastPosition.accuracy,
              fixTimeMs / 1000
            );

            resolve(this._lastPosition);
          },
          (err) => {
            if (err.code === 1) this.diagnostics.permissionStatus = "DENIED";
            else if (err.code === 2) this.diagnostics.permissionStatus = "UNAVAILABLE";
            else if (err.code === 3) this.diagnostics.permissionStatus = "TIMEOUT";
            this._notifyDiagnostics();
            reject(err);
          },
          {
            enableHighAccuracy: true,
            maximumAge: 0,
            timeout: 15000
          }
        );
      });
    },

    getLastKnownPosition() {
      return this._lastPosition;
    },

    setManualPosition(latitude, longitude, accuracy = 10) {
      const nowMs = Date.now();
      this._lastPosition = {
        latitude: Number(latitude),
        longitude: Number(longitude),
        accuracy: Number(accuracy),
        timestamp: nowMs,
        acquired_at: new Date(nowMs).toISOString(),
        is_fresh: true,
        is_manual: true,
      };

      this.diagnostics.rawLatitude = this._lastPosition.latitude;
      this.diagnostics.rawLongitude = this._lastPosition.longitude;
      this.diagnostics.horizontalAccuracy = this._lastPosition.accuracy;
      this.diagnostics.positionAcquiredAt = new Date(nowMs);
      this.diagnostics.isFresh = true;
      this.diagnostics.permissionStatus = "MANUAL_FIX";
      this._notifyDiagnostics();

      this.updateLocation(
        this._lastPosition.latitude,
        this._lastPosition.longitude,
        this._lastPosition.accuracy,
        nowMs / 1000
      );
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
      let wsHostAndPort = window.location.host;
      if (!curPort) {
        wsHostAndPort = window.location.hostname;
      }

      // Connect WebSocket via current host and port
      const wsUrl = `${wsProto}//${wsHostAndPort}/api/v1/ws?client_id=${encodeURIComponent(this.clientId)}`;

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
