(function () {
  'use strict';

  var STEP_MS = 15 * 60 * 1000;

  var airportSelect = document.getElementById('preview-airport');
  var terminalSelect = document.getElementById('preview-terminal');
  var sizeSelect = document.getElementById('preview-size');
  var controlsEl = document.getElementById('preview-controls');
  var controlsToggleButton = document.getElementById('preview-controls-toggle');
  var startInput = document.getElementById('preview-start');
  var endInput = document.getElementById('preview-end');
  var applyRangeButton = document.getElementById('preview-apply-range');
  var statusEl = document.getElementById('preview-status');
  var stageEl = document.getElementById('preview-stage');
  var chartFrame = document.getElementById('preview-chart-frame');
  var calloutEl = document.getElementById('preview-callout');
  var calloutDateEl = document.getElementById('preview-callout-date');
  var calloutGeneralEl = document.getElementById('preview-callout-general-value');
  var calloutPrecheckEl = document.getElementById('preview-callout-precheck-value');
  var toggleCalloutButton = document.getElementById('preview-toggle-callout');
  var editCalloutButton = document.getElementById('preview-edit-callout');
  var calloutEditor = document.getElementById('preview-callout-editor');
  var calloutDatetimeInput = document.getElementById('preview-callout-datetime');
  var calloutGeneralInput = document.getElementById('preview-callout-general');
  var calloutPrecheckInput = document.getElementById('preview-callout-precheck');
  var calloutSizeInput = document.getElementById('preview-callout-size');
  var calloutSizeValue = document.getElementById('preview-callout-size-value');

  var optionsPayload = null;
  var selectedHours = 24;
  var customBounds = null;
  var calloutScale = 1;

  function setStatus(message, isError) {
    statusEl.textContent = message;
    statusEl.classList.toggle('is-error', Boolean(isError));
  }

  function localInputValue(date) {
    var shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return shifted.toISOString().slice(0, 16);
  }

  function selectedAirport() {
    if (!optionsPayload) return null;
    return optionsPayload.airports.find(function (airport) {
      return airport.code === airportSelect.value;
    }) || null;
  }

  function selectedTerminal() {
    var airport = selectedAirport();
    if (!airport) return null;
    var index = Number(terminalSelect.value);
    return airport.terminals[index] || null;
  }

  function updateTerminalOptions() {
    var airport = selectedAirport();
    terminalSelect.innerHTML = '';
    if (!airport) return;
    airport.terminals.forEach(function (row, index) {
      var option = document.createElement('option');
      option.value = String(index);
      option.textContent = window.terminalTabLabel(airport, row.terminal, row.gate);
      terminalSelect.appendChild(option);
    });
  }

  function updateRangeButtons() {
    document.querySelectorAll('.range-button').forEach(function (button) {
      button.classList.toggle(
        'active',
        customBounds == null && Number(button.dataset.hours) === selectedHours
      );
    });
  }

  function customTickHours(bounds) {
    var hours = (bounds.end.getTime() - bounds.start.getTime()) / 3600000;
    if (hours <= 6) return 6;
    if (hours <= 12) return 12;
    if (hours <= 24) return 24;
    if (hours <= 72) return 72;
    return 168;
  }

  function renderChart() {
    var airport = selectedAirport();
    var terminal = selectedTerminal();
    if (!airport || !terminal) {
      setStatus('No local history options are available.', true);
      return;
    }

    var params = new URLSearchParams({
      terminal: terminal.terminal,
      marketing_preview: '1',
      hours: String(customBounds ? customTickHours(customBounds) : selectedHours),
    });
    if (terminal.gate) params.set('gate', terminal.gate);
    if (customBounds) {
      params.set('start', customBounds.start.toISOString());
      params.set('end', customBounds.end.toISOString());
    }

    setStatus('Loading chart…', false);
    chartFrame.src = '/' + encodeURIComponent(airport.code) + '?' + params.toString();
  }

  function updateCallout() {
    var date = new Date(calloutDatetimeInput.value);
    if (!isFinite(date.getTime())) date = new Date();
    var weekday = date.toLocaleDateString([], { weekday: 'short' }).slice(0, 3);
    var day = date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    var time = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    calloutDateEl.textContent = weekday + ', ' + day + ', ' + time;

    [
      [calloutGeneralInput, calloutGeneralEl],
      [calloutPrecheckInput, calloutPrecheckEl],
    ].forEach(function (pair) {
      var minutes = Math.max(0, Math.round(Number(pair[0].value) || 0));
      pair[1].textContent = minutes + ' min';
      pair[1].className = window.waitTimePillClass(minutes);
    });
    clampCallout();
  }

  function updateCalloutScale() {
    calloutScale = Number(calloutSizeInput.value) / 100;
    calloutEl.style.setProperty('--callout-scale', String(calloutScale));
    calloutSizeValue.value = calloutSizeInput.value + '%';
    calloutSizeValue.textContent = calloutSizeInput.value + '%';
    clampCallout();
  }

  function clampCallout() {
    if (calloutEl.hidden) return;
    var visualWidth = calloutEl.offsetWidth * calloutScale;
    var visualHeight = calloutEl.offsetHeight * calloutScale;
    var maxLeft = Math.max(0, stageEl.clientWidth - visualWidth);
    var maxTop = Math.max(0, stageEl.clientHeight - visualHeight);
    var left = Math.max(0, Math.min(parseFloat(calloutEl.style.left) || 0, maxLeft));
    var top = Math.max(0, Math.min(parseFloat(calloutEl.style.top) || 0, maxTop));
    calloutEl.style.left = left + 'px';
    calloutEl.style.top = top + 'px';
  }

  function resetCalloutPosition() {
    calloutEl.style.left = Math.round(stageEl.clientWidth * 0.6) + 'px';
    calloutEl.style.top = '42px';
    clampCallout();
  }

  toggleCalloutButton.addEventListener('click', function () {
    var show = calloutEl.hidden;
    calloutEl.hidden = !show;
    toggleCalloutButton.setAttribute('aria-pressed', show ? 'true' : 'false');
    toggleCalloutButton.textContent = show ? 'Hide callout' : 'Show callout';
    if (show) {
      updateCallout();
      resetCalloutPosition();
    }
  });

  editCalloutButton.addEventListener('click', function () {
    var open = calloutEditor.hidden;
    calloutEditor.hidden = !open;
    editCalloutButton.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  [calloutDatetimeInput, calloutGeneralInput, calloutPrecheckInput].forEach(function (input) {
    input.addEventListener('input', updateCallout);
  });
  calloutSizeInput.addEventListener('input', updateCalloutScale);

  controlsToggleButton.addEventListener('click', function () {
    var expand = controlsEl.hidden;
    controlsEl.hidden = !expand;
    controlsToggleButton.setAttribute('aria-expanded', expand ? 'true' : 'false');
    controlsToggleButton.textContent = expand ? 'Collapse controls' : 'Expand controls';
  });

  calloutEl.addEventListener('pointerdown', function (event) {
    event.preventDefault();
    calloutEl.setPointerCapture(event.pointerId);
    var startX = event.clientX;
    var startY = event.clientY;
    var startLeft = calloutEl.offsetLeft;
    var startTop = calloutEl.offsetTop;

    function move(moveEvent) {
      calloutEl.style.left = startLeft + moveEvent.clientX - startX + 'px';
      calloutEl.style.top = startTop + moveEvent.clientY - startY + 'px';
      clampCallout();
    }
    function stop() {
      calloutEl.removeEventListener('pointermove', move);
      calloutEl.removeEventListener('pointerup', stop);
      calloutEl.removeEventListener('pointercancel', stop);
    }
    calloutEl.addEventListener('pointermove', move);
    calloutEl.addEventListener('pointerup', stop);
    calloutEl.addEventListener('pointercancel', stop);
  });

  sizeSelect.addEventListener('change', function () {
    stageEl.classList.toggle('preview-stage--og', sizeSelect.value === 'og');
    stageEl.classList.toggle('preview-stage--x', sizeSelect.value === 'x');
    stageEl.classList.toggle('preview-stage--web', sizeSelect.value === 'web');
    requestAnimationFrame(clampCallout);
  });

  document.querySelectorAll('.range-button').forEach(function (button) {
    button.addEventListener('click', function () {
      selectedHours = Number(button.dataset.hours);
      customBounds = null;
      updateRangeButtons();
      renderChart();
    });
  });

  applyRangeButton.addEventListener('click', function () {
    var start = new Date(startInput.value);
    var end = new Date(endInput.value);
    if (!isFinite(start.getTime()) || !isFinite(end.getTime()) || start >= end) {
      setStatus('Choose a valid custom start and end time.', true);
      return;
    }
    customBounds = { start: start, end: end };
    updateRangeButtons();
    renderChart();
  });

  airportSelect.addEventListener('change', function () {
    updateTerminalOptions();
    renderChart();
  });
  terminalSelect.addEventListener('change', renderChart);

  window.addEventListener('message', function (event) {
    if (event.origin !== window.location.origin || event.source !== chartFrame.contentWindow) return;
    var message = event.data || {};
    if (message.type === 'tsa-preview-chart-ready') {
      setStatus(
        message.rowCount
          ? Number(message.rowCount).toLocaleString() + ' history rows rendered.'
          : 'No history exists in this range.',
        false
      );
    } else if (message.type === 'tsa-preview-chart-error') {
      setStatus('Error: ' + (message.message || 'Chart failed to load'), true);
    }
  });

  var roundedNow = new Date(Math.round(Date.now() / STEP_MS) * STEP_MS);
  calloutDatetimeInput.value = localInputValue(roundedNow);
  updateCallout();
  updateCalloutScale();

  fetch('/api/preview/options')
    .then(function (response) {
      if (!response.ok) throw new Error('Could not load preview options');
      return response.json();
    })
    .then(function (data) {
      optionsPayload = data;
      airportSelect.innerHTML = '';
      data.airports.forEach(function (airport) {
        var option = document.createElement('option');
        option.value = airport.code;
        option.textContent = airport.code + ' — ' + airport.display_name;
        airportSelect.appendChild(option);
      });
      if (!data.airports.length) {
        setStatus('The local database has no airport history.', true);
        return;
      }
      var preferredIndex = data.airports.findIndex(function (airport) {
        return airport.code === 'JFK';
      });
      airportSelect.selectedIndex = preferredIndex >= 0 ? preferredIndex : 0;
      updateTerminalOptions();

      var latest = new Date(data.latest_scraped_at_utc);
      var earliest = new Date(data.earliest_scraped_at_utc);
      endInput.value = localInputValue(latest);
      startInput.value = localInputValue(
        new Date(Math.max(earliest.getTime(), latest.getTime() - 7 * 86400000))
      );
      renderChart();
    })
    .catch(function (error) {
      setStatus('Error: ' + error.message, true);
    });
})();
