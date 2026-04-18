/**
 * Shared queue labeling for search chips vs airport terminal tabs.
 *
 * chipQueueWaitLine — compact search dropdown: up to 2 queues, " · ", no unit suffix on minutes.
 * airportTabQueueWaitGridRows — /airport tabs: structured rows of up to 2 {label, minutes} pairs
 *   (minutes rendered as "6m" in the template). airportTabQueueWaitTitle builds a plain-text tooltip.
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
   * Each item is one visual row of the tab chip: up to two { label, minutes } (for a 4-column grid).
   * @returns {Array<Array<{ label: string, minutes: number }>>}
   */
  function airportTabQueueWaitGridRows(queues) {
    var ordered = queuesWithMinutesOrdered(queues);
    if (!ordered.length) return [];
    var rows = [];
    for (var start = 0; start < ordered.length; start += 2) {
      var slice = ordered.slice(start, start + 2);
      rows.push(
        slice.map(function (x) {
          return { label: chipQueueTypeLabel(x.qt), minutes: x.minutes };
        })
      );
    }
    return rows;
  }

  /** Plain-text summary for title attributes (includes "6m" style). */
  function airportTabQueueWaitTitle(queues) {
    return airportTabQueueWaitGridRows(queues)
      .map(function (pairs) {
        return pairs
          .map(function (s) {
            return s.label + ' ' + s.minutes + 'm';
          })
          .join(' · ');
      })
      .join(' | ');
  }

  global.chipQueueTypeLabel = chipQueueTypeLabel;
  global.chipQueueWaitLine = chipQueueWaitLine;
  global.airportTabQueueWaitGridRows = airportTabQueueWaitGridRows;
  global.airportTabQueueWaitTitle = airportTabQueueWaitTitle;
})(typeof window !== 'undefined' ? window : this);
