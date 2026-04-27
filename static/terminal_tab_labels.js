/**
 * Terminal / checkpoint tab labels from airport catalog `terminal_tab`.
 *
 * Each airport sets explicit templates (no named presets):
 *   - without_gate: shown when there is no gate (e.g. "Terminal {terminal}")
 *   - with_gate:    shown when there is a gate (e.g. "Terminal {terminal}: Gates {gate}")
 * Placeholders: {terminal}, {gate} (gate is transformed per gate_transform before insert).
 *
 * Optional:
 *   - ignore_gate: if true, gate is omitted for URLs, sorting, and matching; only without_gate is used.
 *   - gate_transform: "titlecase_words" to title-case each whitespace-delimited word of the gate for display.
 *   - terminal_labels: object mapping canonical terminal key (from DB/API) to UI label only.
 *
 * If templates are missing, defaults match the common "Terminal … / Gates …" pattern.
 */
(function (global) {
  var DEFAULT_TAB = {
    ignore_gate: false,
    gate_transform: 'none',
    without_gate: 'Terminal {terminal}',
    with_gate: 'Terminal {terminal}: Gates {gate}',
  };

  function titleCaseWords(s) {
    return String(s)
      .split(/\s+/)
      .map(function (word) {
        if (!word) return word;
        return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
      })
      .join(' ');
  }

  function sanitizeTerminalLabels(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var out = {};
    for (var k in raw) {
      if (!Object.prototype.hasOwnProperty.call(raw, k)) continue;
      var v = raw[k];
      if (typeof v === 'string' && v) out[k] = v;
    }
    return Object.keys(out).length ? out : null;
  }

  /**
   * @param {object|null|undefined} tab raw terminal_tab from catalog
   * @returns {{ ignore_gate: boolean, gate_transform: string, without_gate: string, with_gate: string, terminal_labels?: object }}
   */
  function normalizeTerminalTab(tab) {
    var t = tab && typeof tab === 'object' ? tab : {};
    var labels = sanitizeTerminalLabels(t.terminal_labels);
    var base = {
      ignore_gate: t.ignore_gate === true,
      gate_transform: t.gate_transform === 'titlecase_words' ? 'titlecase_words' : 'none',
      without_gate: typeof t.without_gate === 'string' && t.without_gate ? t.without_gate : DEFAULT_TAB.without_gate,
      with_gate: typeof t.with_gate === 'string' && t.with_gate ? t.with_gate : DEFAULT_TAB.with_gate,
    };
    if (labels) base.terminal_labels = labels;
    return base;
  }

  function terminalTabConfig(airportEntry) {
    return normalizeTerminalTab(airportEntry && airportEntry.terminal_tab);
  }

  function displayGateForLabel(cfg, gateRaw) {
    var g = gateRaw || '';
    if (!g) return '';
    if (cfg.gate_transform === 'titlecase_words') return titleCaseWords(g);
    return g;
  }

  function interpolate(template, terminal, gateDisplay) {
    return String(template)
      .replace(/\{terminal\}/g, terminal || '')
      .replace(/\{gate\}/g, gateDisplay || '');
  }

  function terminalForDisplay(cfg, terminalRaw) {
    var tr = terminalRaw || '';
    var map = cfg.terminal_labels;
    if (map && map[tr]) return map[tr];
    return tr;
  }

  /**
   * Gate value for URLs and matching; empty when catalog says to ignore gate (e.g. CLT).
   */
  function effectiveGateForTab(airportEntry, gateRaw) {
    var cfg = terminalTabConfig(airportEntry);
    if (cfg.ignore_gate) return '';
    return gateRaw || '';
  }

  /**
   * @param {object} airportEntry catalog row with terminal_tab
   */
  function terminalTabLabel(airportEntry, terminal, gateRaw) {
    var cfg = terminalTabConfig(airportEntry);
    var t = terminalForDisplay(cfg, terminal || '');
    var g = effectiveGateForTab(airportEntry, gateRaw);
    if (!g) return interpolate(cfg.without_gate, t, '');
    return interpolate(cfg.with_gate, t, displayGateForLabel(cfg, gateRaw));
  }

  global.normalizeTerminalTab = normalizeTerminalTab;
  global.effectiveGateForTab = effectiveGateForTab;
  global.terminalTabLabel = terminalTabLabel;
})(typeof window !== 'undefined' ? window : this);
