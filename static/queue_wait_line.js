/**
 * Shared queue labeling for search chips vs airport terminal tabs.
 *
 * Queue slots from /api/latest look like:
 *   { minutes, wait_min_minutes, wait_max_minutes } (each nullable).
 *
 * Chip wording is controlled per-airport via catalog ``wait_times_ui.chip``.
 * Chart series use ``wait_times_ui.chart_series`` (see airport page script).
 */
(function (global) {
  var CHIP_QUEUE_PRIORITY = ['general', 'precheck', 'clear', 'priority'];

  function chipQueueTypeLabel(qt) {
    var map = {
      general: 'General',
      precheck: 'PreCheck',
      clear: 'Clear',
      priority: 'Priority',
    };
    if (map[qt]) return map[qt];
    return String(qt)
      .replace(/_/g, ' ')
      .replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
  }

  function slotHasWaitSignal(slot) {
    if (!slot || typeof slot !== 'object') return false;
    return (
      slot.minutes != null ||
      slot.wait_min_minutes != null ||
      slot.wait_max_minutes != null
    );
  }

  /**
   * @param {'absolute'|'range'|'min'|'max'} chip
   * @param {{ minutes: ?number, wait_min_minutes: ?number, wait_max_minutes: ?number }} slot
   * @returns {{ text: string, pillMetric: number | null }}
   * Range band: equal min/max (after rounding) show as one value (e.g. ``0m``), not ``0-0m``.
   */
  function formatWaitChipSlot(chip, slot) {
    var mn = slot.minutes;
    var lo = slot.wait_min_minutes;
    var hi = slot.wait_max_minutes;

    if (chip === 'min') {
      if (lo == null) return { text: '—', pillMetric: null };
      return { text: String(lo) + 'm', pillMetric: lo };
    }
    if (chip === 'max') {
      if (hi == null) return { text: '—', pillMetric: null };
      return { text: String(hi) + 'm', pillMetric: hi };
    }
    if (chip === 'range') {
      if (lo == null && hi != null) return { text: '<' + hi + 'm', pillMetric: hi };
      if (hi == null && lo != null) return { text: '>' + lo + 'm', pillMetric: lo };
      if (lo != null && hi != null) {
        var loN = Math.round(Number(lo));
        var hiN = Math.round(Number(hi));
        if (loN === hiN) {
          return { text: String(loN) + 'm', pillMetric: loN };
        }
        return { text: String(lo) + '-' + String(hi) + 'm', pillMetric: hi };
      }
      return { text: '-', pillMetric: null };
    }
    /* absolute */
    if (mn == null) return { text: '—', pillMetric: null };
    return { text: String(mn) + 'm', pillMetric: mn };
  }

  function chipQueueFirstTwoSlots(queues) {
    var q = queues || {};
    var picked = [];
    for (var i = 0; i < CHIP_QUEUE_PRIORITY.length; i++) {
      if (picked.length >= 2) break;
      var qt = CHIP_QUEUE_PRIORITY[i];
      var slot = q[qt];
      if (slot && slotHasWaitSignal(slot)) {
        picked.push({ qt: qt, slot: slot });
      }
    }
    return picked;
  }

  function chipQueueWaitLine(queues, chipMode) {
    var chip = chipMode || 'absolute';
    var picked = chipQueueFirstTwoSlots(queues);
    if (!picked.length) return '';
    var segments = [];
    for (var j = 0; j < picked.length; j++) {
      var disp = formatWaitChipSlot(chip, picked[j].slot);
      segments.push(chipQueueTypeLabel(picked[j].qt) + ' ' + disp.text);
    }
    return segments.join(' · ');
  }

  /** CSS class for wait-time pill (0–14 low, 15–29 mid, 30+ high). */
  function waitTimePillClass(minutes) {
    var m = Number(minutes);
    if (isNaN(m)) return 'wait-time-pill wait-time-pill--high';
    if (m <= 14) return 'wait-time-pill wait-time-pill--low';
    if (m <= 29) return 'wait-time-pill wait-time-pill--mid';
    return 'wait-time-pill wait-time-pill--high';
  }

  /**
   * Search chip waits: up to two queue types in a label|value grid (like airport tab chips);
   * second row is invisible placeholders when only one queue. `esc` required for HTML safety.
   */
  function chipQueueWaitLineHtml(queues, esc, chipMode) {
    var chip = chipMode || 'absolute';
    var picked = chipQueueFirstTwoSlots(queues);
    if (!picked.length) return '';

    function pairCells(qt, slot) {
      var disp = formatWaitChipSlot(chip, slot);
      var valueHtml;
      if (disp.pillMetric == null) {
        valueHtml =
          '<span class="airport-search-chip__wait--empty">' + esc(disp.text) + '</span>';
      } else {
        valueHtml =
          '<span class="' +
          waitTimePillClass(disp.pillMetric) +
          '">' +
          esc(disp.text) +
          '</span>';
      }
      return (
        '<span class="airport-search-chip__wait-lbl">' +
        esc(chipQueueTypeLabel(qt)) +
        '</span>' +
        '<span class="airport-search-chip__wait-val">' +
        valueHtml +
        '</span>'
      );
    }

    var cells = pairCells(picked[0].qt, picked[0].slot);
    if (picked.length >= 2) {
      cells += pairCells(picked[1].qt, picked[1].slot);
    } else {
      cells +=
        '<span class="airport-search-chip__wait-lbl airport-search-chip__wait-lbl--placeholder" aria-hidden="true">\u00a0</span>' +
        '<span class="airport-search-chip__wait-val airport-search-chip__wait-val--placeholder" aria-hidden="true">\u00a0</span>';
    }

    return '<div class="airport-search-chip__wait-grid">' + cells + '</div>';
  }

  /**
   * Queue types present in ``queues`` (from /api/latest), priority order then others sorted.
   * @returns {{ qt: string, slot: object }[]}
   */
  function queuesWithSlotsOrdered(queues) {
    var q = queues || {};
    var out = [];
    var seen = {};
    for (var i = 0; i < CHIP_QUEUE_PRIORITY.length; i++) {
      var qt = CHIP_QUEUE_PRIORITY[i];
      var slot = q[qt];
      if (slot && slotHasWaitSignal(slot)) {
        out.push({ qt: qt, slot: slot });
        seen[qt] = true;
      }
    }
    var rest = Object.keys(q)
      .filter(function (k) {
        return !seen[k] && q[k] && slotHasWaitSignal(q[k]);
      })
      .sort();
    for (var j = 0; j < rest.length; j++) {
      var rqt = rest[j];
      out.push({ qt: rqt, slot: q[rqt] });
    }
    return out;
  }

  /**
   * Each item is one visual row of the tab chip: up to two { label, text, pillMetric } pairs.
   * @returns {Array<Array<{ label: string, text: string, pillMetric: number | null }>>}
   */
  function airportTabQueueWaitGridRows(queues, chipMode) {
    var chip = chipMode || 'absolute';
    var ordered = queuesWithSlotsOrdered(queues);
    if (!ordered.length) return [];
    var cells = ordered.map(function (x) {
      var disp = formatWaitChipSlot(chip, x.slot);
      return { label: chipQueueTypeLabel(x.qt), text: disp.text, pillMetric: disp.pillMetric };
    });
    var rows = [];
    for (var start = 0; start < cells.length; start += 2) {
      rows.push(cells.slice(start, start + 2));
    }
    return rows;
  }

  /** Plain-text summary for title attributes (includes "6m" style). */
  function airportTabQueueWaitTitle(queues, chipMode) {
    return airportTabQueueWaitGridRows(queues, chipMode)
      .map(function (pairs) {
        return pairs
          .map(function (s) {
            return s.label + ' ' + s.text;
          })
          .join(' · ');
      })
      .join(' | ');
  }

  global.chipQueueTypeLabel = chipQueueTypeLabel;
  global.chipQueueFirstTwoSlots = chipQueueFirstTwoSlots;
  global.chipQueueWaitLine = chipQueueWaitLine;
  global.chipQueueWaitLineHtml = chipQueueWaitLineHtml;
  global.waitTimePillClass = waitTimePillClass;
  global.slotHasWaitSignal = slotHasWaitSignal;
  global.formatWaitChipSlot = formatWaitChipSlot;
  global.airportTabQueueWaitGridRows = airportTabQueueWaitGridRows;
  global.airportTabQueueWaitTitle = airportTabQueueWaitTitle;
})(typeof window !== 'undefined' ? window : this);
