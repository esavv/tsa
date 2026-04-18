/**
 * Shared "chip" wait line for search dropdown and airport terminal tabs:
 * up to two queue types with full labels (General, PreCheck, …), " · " separator, no "m" suffix.
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

  global.chipQueueTypeLabel = chipQueueTypeLabel;
  global.chipQueueWaitLine = chipQueueWaitLine;
})(typeof window !== 'undefined' ? window : this);
