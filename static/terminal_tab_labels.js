/**
 * Terminal / checkpoint labels from catalog terminal_tab (preset + optional strings).
 * Used by airport pages, /all, and search chips.
 */
(function (global) {
  function titleCaseWords(s) {
    return String(s)
      .split(/\s+/)
      .map(function (word) {
        if (!word) return word;
        return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
      })
      .join(' ');
  }

  function terminalTabConfig(airportEntry) {
    var tab = (airportEntry && airportEntry.terminal_tab) || {};
    var out = {};
    out.preset = tab.preset || 'standard';
    out.strings = tab.strings || {};
    return out;
  }

  function str(strings, key, def) {
    if (strings && strings[key]) return strings[key];
    return def;
  }

  /**
   * Gate value for URLs and matching; empty when catalog says to ignore gate in label (e.g. CLT).
   */
  function effectiveGateForTab(airportEntry, gateRaw) {
    var cfg = terminalTabConfig(airportEntry);
    if (cfg.preset === 'clt') return '';
    if (airportEntry && airportEntry.terminal_tab && airportEntry.terminal_tab.ignore_gate === true) {
      return '';
    }
    return gateRaw || '';
  }

  /**
   * @param {object} airportEntry catalog row: { code, terminal_tab: { preset, strings?, ignore_gate? } }
   */
  function terminalTabLabel(airportEntry, terminal, gateRaw) {
    var cfg = terminalTabConfig(airportEntry);
    var preset = cfg.preset;
    var strings = cfg.strings;
    var t = terminal || '';
    var g = effectiveGateForTab(airportEntry, gateRaw);

    var terminalWord = str(strings, 'terminal_prefix', 'Terminal ');
    var checkpointWord = str(strings, 'checkpoint_prefix', 'Checkpoint ');
    var gatesPlural = str(strings, 'gates_plural', 'Gates ');
    var gateSingular = str(strings, 'gate_singular', 'Gate ');

    switch (preset) {
      case 'clt':
        return t;
      case 'atl':
        if (!g) return t;
        return t + ': ' + titleCaseWords(g);
      case 'mia':
        if (!g) return checkpointWord + t;
        return checkpointWord + t + ': ' + gatesPlural + g;
      case 'dfw':
        if (!g) return terminalWord + t;
        return terminalWord + t + ': ' + gateSingular + g;
      case 'las_phx':
        if (!g) return terminalWord + t;
        return terminalWord + t + ': ' + g;
      case 'ewr_mco':
        if (!g) return terminalWord + t;
        return terminalWord + t + ': ' + gatesPlural + g;
      case 'standard':
      default:
        if (!g) return terminalWord + t;
        return terminalWord + t + ': ' + gatesPlural + g;
    }
  }

  global.effectiveGateForTab = effectiveGateForTab;
  global.terminalTabLabel = terminalTabLabel;
})(typeof window !== 'undefined' ? window : this);
