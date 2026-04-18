/**
 * Shared queue labeling for search chips vs airport terminal tabs.
 *
 * chipQueueWaitLine — compact search dropdown: up to 2 queues, " · ", no "min" suffix.
 * airportTabQueueWaitRows — /airport tabs: every queue with minutes, max 2 per row, " min" suffix.
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

  function chipQueueWaitLine(queues) {
    var q = queues || {};
    var picked = [];
    for (var i = 0; i < CHIP_QUEUE_PRIORITY.length; i++) {
      if (picked.length >= 2) break;
      var qt = CHIP_QUEUE_PRIORITY[i];
      var slot = q[qt];
      if (slot && slot.minutes != null) {
        picked.push({ qt: qt, minutes: slot.minutes });
      }
    }
    if (!picked.length) return '';
    var segments = [];
    for (var j = 0; j < picked.length; j++) {
      segments.push(chipQueueTypeLabel(picked[j].qt) + ' ' + picked[j].minutes);
    }
    return segments.join(' · ');
  }

  /**
   * All queue types that have numeric minutes, in CHIP_QUEUE_PRIORITY order then any others sorted.
   * @returns {{ qt: string, minutes: number }[]}
   */
  function queuesWithMinutesOrdered(queues) {
    var q = queues || {};
    var out = [];
    var seen = {};
    for (var i = 0; i < CHIP_QUEUE_PRIORITY.length; i++) {
      var qt = CHIP_QUEUE_PRIORITY[i];
      var slot = q[qt];
      if (slot && slot.minutes != null) {
        out.push({ qt: qt, minutes: slot.minutes });
        seen[qt] = true;
      }
    }
    var rest = Object.keys(q)
      .filter(function (k) {
        return !seen[k] && q[k] && q[k].minutes != null;
      })
      .sort();
    for (var j = 0; j < rest.length; j++) {
      var rqt = rest[j];
      out.push({ qt: rqt, minutes: q[rqt].minutes });
    }
    return out;
  }

  /**
   * One string per row; each row has at most two "Label N min" segments joined by " · ".
   * @returns {string[]}
   */
  function airportTabQueueWaitRows(queues) {
    var ordered = queuesWithMinutesOrdered(queues);
    if (!ordered.length) return [];
    var rows = [];
    for (var start = 0; start < ordered.length; start += 2) {
      var slice = ordered.slice(start, start + 2);
      var segs = [];
      for (var s = 0; s < slice.length; s++) {
        segs.push(chipQueueTypeLabel(slice[s].qt) + ' ' + slice[s].minutes + ' min');
      }
      rows.push(segs.join(' · '));
    }
    return rows;
  }

  global.chipQueueTypeLabel = chipQueueTypeLabel;
  global.chipQueueWaitLine = chipQueueWaitLine;
  global.airportTabQueueWaitRows = airportTabQueueWaitRows;
})(typeof window !== 'undefined' ? window : this);
