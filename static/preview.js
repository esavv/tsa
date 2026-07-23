(function () {
  'use strict';

  var STEP_MS = 15 * 60 * 1000;
  var GAP_BREAK_MS = 45 * 60 * 1000;
  var LINE_COLORS = [
    '#2563eb', '#16a34a', '#ca8a04', '#9333ea', '#dc2626',
    '#0891b2', '#4f46e5', '#db2777', '#0d9488', '#7c3aed',
  ];
  var QUEUE_ORDER = ['general', 'precheck', 'premier', 'priority', 'clear'];
  var DOT_SPACING = 4;
  var DOT_RADIUS = 1;

  var airportSelect = document.getElementById('preview-airport');
  var terminalSelect = document.getElementById('preview-terminal');
  var sizeSelect = document.getElementById('preview-size');
  var startInput = document.getElementById('preview-start');
  var endInput = document.getElementById('preview-end');
  var applyRangeButton = document.getElementById('preview-apply-range');
  var statusEl = document.getElementById('preview-status');
  var stageEl = document.getElementById('preview-stage');
  var chartCanvas = document.getElementById('preview-chart');
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

  var optionsPayload = null;
  var chart = null;
  var historyAbort = null;
  var selectedHours = 24;
  var customBounds = null;

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

  function currentBounds() {
    if (customBounds) return customBounds;
    var latest = optionsPayload && Date.parse(optionsPayload.latest_scraped_at_utc);
    if (!isFinite(latest)) return null;
    return {
      start: new Date(latest - selectedHours * 60 * 60 * 1000),
      end: new Date(latest),
    };
  }

  function sortedQueueTypes(queues) {
    var keys = Object.keys(queues || {});
    return keys.sort(function (a, b) {
      var ai = QUEUE_ORDER.indexOf(a);
      var bi = QUEUE_ORDER.indexOf(b);
      if (ai === -1) ai = QUEUE_ORDER.length;
      if (bi === -1) bi = QUEUE_ORDER.length;
      return ai === bi ? a.localeCompare(b) : ai - bi;
    });
  }

  function normalizedSeriesKinds(airport) {
    var kinds = (
      airport &&
      airport.wait_times_ui &&
      Array.isArray(airport.wait_times_ui.chart_series)
    ) ? airport.wait_times_ui.chart_series : ['absolute'];
    return kinds.length ? kinds : ['absolute'];
  }

  function pointValue(point, kind) {
    if (kind === 'absolute') return point.minutes;
    if (kind === 'min') return point.wait_min_minutes;
    return point.wait_max_minutes;
  }

  function makeGapSegment(color) {
    return {
      borderColor: function (ctx) {
        var x0 = ctx.p0.parsed.x;
        var x1 = ctx.p1.parsed.x;
        return x0 != null && x1 != null && x1 - x0 > GAP_BREAK_MS
          ? 'transparent'
          : color;
      },
    };
  }

  function hexRgb(hex) {
    var number = parseInt(hex.slice(1), 16);
    return {
      r: (number >> 16) & 255,
      g: (number >> 8) & 255,
      b: number & 255,
    };
  }

  var dottedFadeFillPlugin = {
    id: 'previewDottedFadeFill',
    beforeDatasetsDraw: function (chartRef) {
      var ctx = chartRef.ctx;
      var area = chartRef.chartArea;
      if (!area) return;
      ctx.save();
      ctx.beginPath();
      ctx.rect(area.left, area.top, area.width, area.height);
      ctx.clip();

      chartRef.data.datasets.forEach(function (dataset, datasetIndex) {
        if (!dataset.dottedFadeFillColor || !chartRef.isDatasetVisible(datasetIndex)) return;
        var line = chartRef.getDatasetMeta(datasetIndex).dataset;
        if (!line || !line.points || line.points.length < 2) return;
        var rgb = hexRgb(dataset.dottedFadeFillColor);
        var seriesTop = line.points.reduce(function (top, point) {
          if (!point || point.skip || !isFinite(point.y)) return top;
          return Math.min(top, Math.max(area.top, Math.min(area.bottom, point.y)));
        }, area.bottom);
        var fadeHeight = area.bottom - seriesTop;
        if (fadeHeight <= DOT_SPACING) return;
        var rows = new Map();

        (line.segments || []).forEach(function (segment) {
          if (segment.style && segment.style.borderColor === 'transparent') return;
          var first = line.points[segment.start];
          var last = line.points[segment.end];
          if (!first || !last || first.skip || last.skip) return;
          var xStart = Math.max(area.left, Math.min(first.x, last.x));
          var xEnd = Math.min(area.right, Math.max(first.x, last.x));
          for (
            var x = Math.ceil(xStart / DOT_SPACING) * DOT_SPACING;
            x <= xEnd;
            x += DOT_SPACING
          ) {
            var curvePoint = line.interpolate({ x: x }, 'x');
            if (Array.isArray(curvePoint)) curvePoint = curvePoint[0];
            if (!curvePoint || !isFinite(curvePoint.y)) continue;
            var curveY = Math.max(area.top, Math.min(area.bottom, curvePoint.y));
            for (
              var y = Math.ceil((curveY + 1) / DOT_SPACING) * DOT_SPACING;
              y < area.bottom;
              y += DOT_SPACING
            ) {
              if (!rows.has(y)) rows.set(y, []);
              rows.get(y).push(x);
            }
          }
        });

        rows.forEach(function (xs, y) {
          var alpha = Math.max(0, Math.min(1, (area.bottom - y) / fadeHeight));
          ctx.fillStyle =
            'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',' + alpha + ')';
          ctx.beginPath();
          xs.forEach(function (x) {
            ctx.moveTo(x + DOT_RADIUS, y);
            ctx.arc(x, y, DOT_RADIUS, 0, Math.PI * 2);
          });
          ctx.fill();
        });
      });
      ctx.restore();
    },
  };

  Chart.register(dottedFadeFillPlugin);

  function buildDatasets(queues, airport) {
    var datasets = [];
    var colorIndex = 0;
    var kinds = normalizedSeriesKinds(airport);
    sortedQueueTypes(queues).forEach(function (queueType) {
      kinds.forEach(function (kind) {
        var points = (queues[queueType] || []).map(function (point) {
          var value = pointValue(point, kind);
          return {
            x: Date.parse(point.t),
            y: value == null || !isFinite(Number(value)) ? null : Number(value),
          };
        });
        if (!points.some(function (point) { return point.y != null; })) return;
        var color = LINE_COLORS[colorIndex % LINE_COLORS.length];
        colorIndex += 1;
        datasets.push({
          data: points,
          parsing: false,
          borderColor: color,
          borderWidth: 2,
          backgroundColor: 'transparent',
          pointRadius: 0,
          pointHoverRadius: 0,
          fill: false,
          tension: 0.2,
          spanGaps: false,
          segment: makeGapSegment(color),
          dottedFadeFillColor: kind === 'absolute' || kind === 'range' ? color : null,
        });
      });
    });
    return datasets;
  }

  function drawChart(data, bounds) {
    if (chart) chart.destroy();
    chart = new Chart(chartCanvas.getContext('2d'), {
      type: 'line',
      data: { datasets: buildDatasets(data.queues || {}, selectedAirport()) },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        events: [],
        layout: { padding: 12 },
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false },
        },
        scales: {
          x: {
            type: 'time',
            display: false,
            min: bounds.start.getTime(),
            max: bounds.end.getTime(),
          },
          y: {
            display: false,
            beginAtZero: true,
          },
        },
      },
    });
  }

  function renderChart() {
    var airport = selectedAirport();
    var terminal = selectedTerminal();
    var bounds = currentBounds();
    if (!airport || !terminal || !bounds) {
      setStatus('No local history options are available.', true);
      return;
    }
    if (historyAbort) historyAbort.abort();
    historyAbort = new AbortController();
    setStatus('Loading chart…', false);

    var params = new URLSearchParams({
      airport: airport.code,
      terminal: terminal.terminal,
      gate: terminal.gate || '',
      start: bounds.start.toISOString(),
      end: bounds.end.toISOString(),
    });
    fetch('/api/preview/history?' + params.toString(), { signal: historyAbort.signal })
      .then(function (response) {
        return response.json().then(function (body) {
          if (!response.ok || body.error) throw new Error(body.error || 'History request failed');
          return body;
        });
      })
      .then(function (data) {
        drawChart(data, bounds);
        var pointCount = Object.keys(data.queues || {}).reduce(function (total, key) {
          return total + data.queues[key].length;
        }, 0);
        setStatus(
          pointCount
            ? pointCount.toLocaleString() + ' history rows rendered.'
            : 'No history exists in this range.',
          false
        );
      })
      .catch(function (error) {
        if (error.name === 'AbortError') return;
        setStatus('Error: ' + error.message, true);
      });
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

  function clampCallout() {
    if (calloutEl.hidden) return;
    var maxLeft = Math.max(0, stageEl.clientWidth - calloutEl.offsetWidth);
    var maxTop = Math.max(0, stageEl.clientHeight - calloutEl.offsetHeight);
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
    requestAnimationFrame(function () {
      if (chart) chart.resize();
      clampCallout();
    });
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

  var roundedNow = new Date(Math.round(Date.now() / STEP_MS) * STEP_MS);
  calloutDatetimeInput.value = localInputValue(roundedNow);
  updateCallout();

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
