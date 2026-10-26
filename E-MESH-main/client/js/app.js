/**
 * E-Mesh Simplified Citizen Client Controller
 * Focuses purely on reliable emergency SOS dispatch and live location feedback.
 */

(function () {
  let isSubmitting = false;
  let cooldownTimer = null;
  let cooldownSecondsLeft = 0;
  let lastSubmittedPayload = null;

  // ── DOM Element Cache ──────────────────────────────────────────────────
  const elements = {};

  function cacheElements() {
    elements.viewActive      = document.getElementById('view-sos-active');
    elements.viewConfirmed   = document.getElementById('view-sos-confirmed');
    elements.btnSos          = document.getElementById('btn-trigger-sos');
    elements.progressBox     = document.getElementById('sos-progress');
    elements.errorBox        = document.getElementById('sos-error-box');
    elements.errorMsg        = document.getElementById('sos-error-msg');
    elements.btnRetry        = document.getElementById('btn-retry-sos');
    elements.btnToggleDetails= document.getElementById('btn-toggle-details');
    elements.detailsBody     = document.getElementById('details-body');
    elements.detailsToggleIcon = document.getElementById('details-toggle-icon');
    elements.inputPeople     = document.getElementById('field-people-count');
    elements.btnPeopleDec    = document.getElementById('btn-people-dec');
    elements.btnPeopleInc    = document.getElementById('btn-people-inc');
    elements.inputNotes      = document.getElementById('field-notes');
    elements.netIndicator    = document.getElementById('net-indicator');
    elements.netLabel        = document.getElementById('net-label');
    elements.gpsIndicator    = document.getElementById('gps-indicator');
    elements.gpsLabel        = document.getElementById('gps-label');
    elements.locationText    = document.getElementById('location-text');
    elements.locationCoords  = document.getElementById('location-coords');
    elements.locationLatLon  = document.getElementById('location-latlon');
    elements.locationAcc     = document.getElementById('location-accuracy');
    elements.confirmedRefId  = document.getElementById('confirmed-ref-id');
    elements.confirmedStatus = document.getElementById('confirmed-status');
    elements.confirmedTime   = document.getElementById('confirmed-time');
    elements.confirmedPeople = document.getElementById('confirmed-people');
    elements.confirmedCoords = document.getElementById('confirmed-coords');
    elements.confirmedNotes  = document.getElementById('confirmed-notes');
    elements.confirmedNotesRow = document.getElementById('confirmed-notes-row');
    elements.cooldownText    = document.getElementById('cooldown-timer-text');
    elements.btnNewSos       = document.getElementById('btn-new-sos');
    elements.toastContainer  = document.getElementById('toast-container');
    elements.manualLat       = document.getElementById('manual-lat');
    elements.manualLon       = document.getElementById('manual-lon');
    elements.btnUsePresetLoc = document.getElementById('btn-use-preset-loc');
    elements.btnApplyManualLoc = document.getElementById('btn-apply-manual-loc');
  }

  // ── Toast System ───────────────────────────────────────────────────────
  function showToast(message, type = 'info') {
    if (!elements.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.textContent = message;
    elements.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('fade-out');
      setTimeout(() => toast.remove(), 400);
    }, 4000);
  }

  // ── Geolocation UI Updates ─────────────────────────────────────────────
  function onLocationSuccess(pos) {
    if (!elements.gpsIndicator) return;
    elements.gpsIndicator.className = 'status-chip status-chip--online';
    const acc = Math.round(pos.accuracy || 0);
    elements.gpsLabel.textContent = acc > 0 ? `GPS ±${acc}m` : 'GPS READY';

    if (elements.locationText) {
      elements.locationText.textContent = 'High-accuracy GPS fix established:';
    }
    if (elements.locationCoords) {
      elements.locationCoords.classList.remove('hidden');
    }
    if (elements.locationLatLon) {
      elements.locationLatLon.textContent = `${pos.latitude.toFixed(6)}°, ${pos.longitude.toFixed(6)}°`;
    }
    if (elements.locationAcc) {
      elements.locationAcc.textContent = acc > 0 ? `(accuracy: ±${acc} m)` : '';
    }
  }

  function onLocationError(err) {
    if (!elements.gpsIndicator) return;
    elements.gpsIndicator.className = 'status-chip status-chip--warn';

    let reason = 'Location unavailable';
    if (err.code === 1) { // PERMISSION_DENIED
      reason = 'Location permission denied';
      elements.gpsLabel.textContent = 'GPS DENIED';
    } else if (err.code === 2) { // POSITION_UNAVAILABLE
      reason = 'GPS signal unavailable (indoors/obstructed)';
      elements.gpsLabel.textContent = 'NO GPS FIX';
    } else if (err.code === 3) { // TIMEOUT
      reason = 'GPS acquisition timed out';
      elements.gpsLabel.textContent = 'GPS TIMEOUT';
    } else {
      elements.gpsLabel.textContent = 'NO GPS';
    }

    if (elements.locationText) {
      elements.locationText.textContent = `${reason}. SOS submission will proceed without coordinates.`;
    }
    if (elements.locationCoords) {
      elements.locationCoords.classList.add('hidden');
    }
  }

  // ── Network Health Updates ─────────────────────────────────────────────
  function onNetworkStatusChange(isOnline) {
    if (!elements.netIndicator) return;
    if (isOnline) {
      elements.netIndicator.className = 'status-chip status-chip--online';
      elements.netLabel.textContent = 'MESH: ONLINE';
    } else {
      elements.netIndicator.className = 'status-chip status-chip--offline';
      elements.netLabel.textContent = 'MESH: RECONNECTING';
    }
  }

  // ── SOS Submission Flow ────────────────────────────────────────────────
  async function triggerSos() {
    if (isSubmitting) return;

    const peopleCount = parseInt(elements.inputPeople.value) || 1;
    const notes = (elements.inputNotes.value || '').trim();
    const pos = API.getLastKnownPosition();

    // Preserve payload for retry if delivery fails
    lastSubmittedPayload = {
      peopleCount,
      notes,
      latitude: pos ? pos.latitude : null,
      longitude: pos ? pos.longitude : null,
      accuracy: pos ? pos.accuracy : null
    };

    setSubmittingState(true);
    hideError();

    // Haptic feedback if device supports it
    if (navigator.vibrate) {
      navigator.vibrate([200, 100, 200]);
    }

    try {
      const result = await API.sendSOS(lastSubmittedPayload);
      // Only transition to confirmed once the server explicitly acknowledges!
      showConfirmedScreen(result, lastSubmittedPayload);
      showToast("SOS Received by GCS Operator!", "success");
    } catch (err) {
      showError(err.message || "Unable to send SOS. Gateway unreachable.");
      showToast("Delivery Failed: Check Mesh Connection", "error");
    } finally {
      setSubmittingState(false);
    }
  }

  function setSubmittingState(submitting) {
    isSubmitting = submitting;
    if (elements.btnSos) {
      elements.btnSos.disabled = submitting;
      if (submitting) {
        elements.btnSos.classList.add('btn-sos--submitting');
      } else {
        elements.btnSos.classList.remove('btn-sos--submitting');
      }
    }
    if (elements.progressBox) {
      if (submitting) {
        elements.progressBox.classList.remove('hidden');
      } else {
        elements.progressBox.classList.add('hidden');
      }
    }
  }

  function showError(message) {
    if (elements.errorBox) {
      elements.errorBox.classList.remove('hidden');
    }
    if (elements.errorMsg) {
      elements.errorMsg.textContent = message;
    }
  }

  function hideError() {
    if (elements.errorBox) {
      elements.errorBox.classList.add('hidden');
    }
  }

  function showConfirmedScreen(sosData, submittedInfo) {
    if (elements.viewActive) elements.viewActive.classList.add('hidden');
    if (elements.viewConfirmed) elements.viewConfirmed.classList.remove('hidden');

    if (elements.confirmedRefId) {
      elements.confirmedRefId.textContent = sosData.sos_id || sosData.id || 'SOS-REGISTERED';
    }
    if (elements.confirmedStatus) {
      elements.confirmedStatus.textContent = sosData.status || 'ACTIVE';
    }
    if (elements.confirmedTime) {
      elements.confirmedTime.textContent = new Date().toLocaleTimeString();
    }
    if (elements.confirmedPeople) {
      elements.confirmedPeople.textContent = `${submittedInfo.peopleCount} Person${submittedInfo.peopleCount > 1 ? 's' : ''}`;
    }
    if (elements.confirmedCoords) {
      if (submittedInfo.latitude != null && submittedInfo.longitude != null) {
        const acc = submittedInfo.accuracy ? ` (±${Math.round(submittedInfo.accuracy)}m)` : '';
        elements.confirmedCoords.textContent = `${submittedInfo.latitude.toFixed(5)}°, ${submittedInfo.longitude.toFixed(5)}°${acc}`;
      } else {
        elements.confirmedCoords.textContent = 'None reported (GPS disabled)';
      }
    }
    if (elements.confirmedNotes && elements.confirmedNotesRow) {
      if (submittedInfo.notes) {
        elements.confirmedNotes.textContent = submittedInfo.notes;
        elements.confirmedNotesRow.classList.remove('hidden');
      } else {
        elements.confirmedNotesRow.classList.add('hidden');
      }
    }

    startCooldownTimer(60);
  }

  function resetToActiveScreen() {
    if (elements.viewConfirmed) elements.viewConfirmed.classList.add('hidden');
    if (elements.viewActive) elements.viewActive.classList.remove('hidden');
    hideError();
  }

  function startCooldownTimer(seconds) {
    cooldownSecondsLeft = seconds;
    clearInterval(cooldownTimer);
    updateCooldownDisplay();

    cooldownTimer = setInterval(() => {
      cooldownSecondsLeft -= 1;
      if (cooldownSecondsLeft <= 0) {
        clearInterval(cooldownTimer);
        if (elements.cooldownText) {
          elements.cooldownText.textContent = "You can transmit an updated SOS at any time.";
        }
      } else {
        updateCooldownDisplay();
      }
    }, 1000);
  }

  function updateCooldownDisplay() {
    if (elements.cooldownText) {
      elements.cooldownText.textContent = `Next distress update available in ${cooldownSecondsLeft}s`;
    }
  }

  // ── Event Setup ────────────────────────────────────────────────────────
  function setupEvents() {
    // SOS Main Trigger
    elements.btnSos.addEventListener('click', (e) => {
      e.preventDefault();
      triggerSos();
    });

    // Retry Button
    elements.btnRetry.addEventListener('click', (e) => {
      e.preventDefault();
      triggerSos();
    });

    // Toggle Optional Details
    elements.btnToggleDetails.addEventListener('click', () => {
      const isHidden = elements.detailsBody.classList.contains('hidden');
      if (isHidden) {
        elements.detailsBody.classList.remove('hidden');
        elements.btnToggleDetails.setAttribute('aria-expanded', 'true');
        elements.detailsToggleIcon.textContent = '▴';
      } else {
        elements.detailsBody.classList.add('hidden');
        elements.btnToggleDetails.setAttribute('aria-expanded', 'false');
        elements.detailsToggleIcon.textContent = '▾';
      }
    });

    // People Counter
    elements.btnPeopleDec.addEventListener('click', () => {
      let val = parseInt(elements.inputPeople.value) || 1;
      if (val > 1) elements.inputPeople.value = val - 1;
    });

    elements.btnPeopleInc.addEventListener('click', () => {
      let val = parseInt(elements.inputPeople.value) || 1;
      if (val < 999) elements.inputPeople.value = val + 1;
    });

    // New SOS Button
    elements.btnNewSos.addEventListener('click', () => {
      resetToActiveScreen();
    });

    // Manual Location Override Listeners
    if (elements.btnUsePresetLoc) {
      elements.btnUsePresetLoc.addEventListener('click', () => {
        if (elements.manualLat) elements.manualLat.value = "13.0827";
        if (elements.manualLon) elements.manualLon.value = "80.2707";
        applyManualCoordinates(13.0827, 80.2707);
      });
    }

    if (elements.btnApplyManualLoc) {
      elements.btnApplyManualLoc.addEventListener('click', () => {
        const lat = parseFloat(elements.manualLat ? elements.manualLat.value : NaN);
        const lon = parseFloat(elements.manualLon ? elements.manualLon.value : NaN);
        if (!isNaN(lat) && !isNaN(lon)) {
          applyManualCoordinates(lat, lon);
        } else {
          showToast("Please enter valid decimal coordinates", "error");
        }
      });
    }
  }

  function applyManualCoordinates(lat, lon) {
    const pos = API.setManualPosition(lat, lon, 10);
    onLocationSuccess(pos);
    showToast(`Manual GPS fix active: ${lat.toFixed(4)}, ${lon.toFixed(4)}`, "success");
  }

  // ── Bootstrap ──────────────────────────────────────────────────────────
  function init() {
    cacheElements();
    setupEvents();

    // Start geolocation engine immediately
    API.startLocationTracking(onLocationSuccess, onLocationError);

    // Connect WebSocket for mesh gateway health
    API.connectWebSocket(onNetworkStatusChange);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
