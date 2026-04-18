/**
 * Airport catalog search: substring match + tiered ranking (no fuzzy/typo handling).
 * Expects /api/catalog (metros + airports) and uses /api/latest for row wait summaries.
 */
(function () {
  var CATALOG_URL = '/api/catalog';
  var LATEST_URL = '/api/latest';
  var LATEST_TTL_MS = 60000;
  var DEFAULT_MAX_RESULTS = 16;

  var catalogPromise = null;
  var latestJson = null;
  var latestFetchedAt = 0;

  function fetchCatalog() {
    if (catalogPromise) return catalogPromise;
    catalogPromise = fetch(CATALOG_URL).then(function (r) {
      if (!r.ok) throw new Error('catalog fetch failed');
      return r.json();
    });
    return catalogPromise;
  }

  function fetchLatest() {
    var now = Date.now();
    if (latestJson && now - latestFetchedAt < LATEST_TTL_MS) {
      return Promise.resolve(latestJson);
    }
    return fetch(LATEST_URL).then(function (r) {
      if (!r.ok) throw new Error('latest fetch failed');
      return r.json();
    }).then(function (j) {
      latestJson = j;
      latestFetchedAt = Date.now();
      return j;
    });
  }

  /**
   * @param {string} hay
   * @param {string} ql normalized query
   * @param {number} tier lower = stronger field (code < display < …)
   * @returns {number} Infinity if no match
   */
  function matchScore(hay, ql, tier) {
    if (!ql) return 0;
    if (hay == null || hay === '') return Infinity;
    var h = String(hay).toLowerCase();
    if (h === ql) return tier;
    if (h.startsWith(ql)) return tier + 2;
    var i = h.indexOf(ql);
    if (i < 0) return Infinity;
    return tier + 20 + i;
  }

  function minScore(scores) {
    var m = Infinity;
    for (var i = 0; i < scores.length; i++) {
      if (scores[i] < m) m = scores[i];
    }
    return m;
  }

  /**
   * @param {object} ap normalized airport (includes aliases, metro_key)
   * @param {object} metros
   * @param {string} ql trimmed lowercase query
   */
  function airportScore(ap, metros, ql) {
    if (!ql) return 0;
    var scores = [];
    scores.push(matchScore(ap.code, ql, 0));
    scores.push(matchScore(ap.display_name, ql, 200));
    if (ap.city) scores.push(matchScore(ap.city, ql, 400));
    if (ap.state) scores.push(matchScore(ap.state, ql, 500));
    if (ap.state_name) scores.push(matchScore(ap.state_name, ql, 500));
    if (ap.city && ap.state) {
      scores.push(matchScore(ap.city + ' ' + ap.state, ql, 420));
      scores.push(matchScore(ap.city + ', ' + ap.state, ql, 420));
    }
    if (ap.city && ap.state_name) {
      scores.push(matchScore(ap.city + ' ' + ap.state_name, ql, 420));
      scores.push(matchScore(ap.city + ', ' + ap.state_name, ql, 420));
    }
    var aliases = ap.aliases || [];
    for (var a = 0; a < aliases.length; a++) {
      scores.push(matchScore(aliases[a], ql, 600));
    }
    if (ap.metro_key && metros[ap.metro_key]) {
      var m = metros[ap.metro_key];
      scores.push(matchScore(m.display_name, ql, 800));
      var ma = m.search_aliases || [];
      for (var b = 0; b < ma.length; b++) {
        scores.push(matchScore(ma[b], ql, 800));
      }
    }
    return minScore(scores);
  }

  function normalizeAirports(catalog) {
    var metros = catalog.metros || {};
    var list = catalog.airports || [];
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var ap = list[i];
      var metroLabel = null;
      if (ap.metro_key && metros[ap.metro_key]) {
        metroLabel = metros[ap.metro_key].display_name || ap.metro_key;
      }
      var tt = ap.terminal_tab || {};
      var terminalTab = {};
      for (var tk in tt) {
        if (Object.prototype.hasOwnProperty.call(tt, tk) && tk !== 'preset') {
          terminalTab[tk] = tt[tk];
        }
      }
      out.push({
        code: ap.code,
        display_name: ap.display_name,
        city: ap.city || '',
        state: ap.state || '',
        state_name: ap.state_name || '',
        metro_key: ap.metro_key,
        metro_label: metroLabel,
        aliases: ap.aliases || [],
        terminal_tab: terminalTab,
      });
    }
    out.sort(function (a, b) {
      return a.code.localeCompare(b.code);
    });
    return out;
  }

  /**
   * Filter by substring rules (airportScore !== Infinity); sort by IATA code only.
   * Call stabilizeMatchOrder after this when the matched set should keep order across keystrokes.
   */
  function rankRows(rows, metros, ql) {
    var scored = [];
    var q = (ql || '').trim().toLowerCase();
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var sc = airportScore(r, metros, q);
      if (q && sc === Infinity) continue;
      scored.push({ row: r, score: sc });
    }
    scored.sort(function (a, b) {
      return a.row.code.localeCompare(b.row.code);
    });
    return scored;
  }

  /**
   * If the matched airport set is identical to the last render, keep the previous row order
   * (avoids reordering when refining e.g. "ny" → "nyc"). Otherwise rankRows' order stands.
   */
  function stabilizeMatchOrder(scored, st) {
    if (!scored.length) {
      st.prevSetKey = null;
      st.prevOrder = [];
      return scored;
    }
    var setKey = scored
      .map(function (s) {
        return s.row.code;
      })
      .sort()
      .join(',');
    if (
      st.prevSetKey != null &&
      setKey === st.prevSetKey &&
      st.prevOrder.length === scored.length
    ) {
      var pos = {};
      for (var i = 0; i < st.prevOrder.length; i++) {
        pos[st.prevOrder[i]] = i;
      }
      scored.sort(function (a, b) {
        return pos[a.row.code] - pos[b.row.code];
      });
    }
    st.prevSetKey = setKey;
    st.prevOrder = scored.map(function (s) {
      return s.row.code;
    });
    return scored;
  }

  function catalogEntryForCode(list, code) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].code === code) return list[i];
    }
    return { code: code, terminal_tab: {} };
  }

  function sortTerminalRows(catalogEntry, terminalRows) {
    return terminalRows.slice().sort(function (a, b) {
      var ga = effectiveGateForTab(catalogEntry, (a && a.gate) || '');
      var gb = effectiveGateForTab(catalogEntry, (b && b.gate) || '');
      var ka = String((a && a.terminal) || '') + '\0' + ga;
      var kb = String((b && b.terminal) || '') + '\0' + gb;
      return ka.localeCompare(kb);
    });
  }

  var MAX_TERMINAL_CHIPS = 3;

  function buildTerminalChipsHtml(code, latest, catalogRows) {
    var terminals = latest && latest.airports && latest.airports[code];
    if (!terminals || !terminals.length) {
      return (
        '<div class="airport-search-row__chips airport-search-row__chips--empty muted" role="presentation">' +
        '<span class="airport-search-row__chips-msg">No checkpoint data</span>' +
        '<span class="airport-search-more-slot" aria-hidden="true"></span>' +
        '</div>'
      );
    }
    var apEntry = catalogEntryForCode(catalogRows || [], code);
    var sorted = sortTerminalRows(apEntry, terminals);
    var show = sorted.slice(0, MAX_TERMINAL_CHIPS);
    var more = sorted.length - show.length;
    var html = '<div class="airport-search-row__chips" role="presentation">';
    html += '<div class="airport-search-row__chip-run">';
    for (var i = 0; i < show.length; i++) {
      var row = show[i];
      var label = terminalTabLabel(apEntry, row.terminal, row.gate);
      var waitLine = window.chipQueueWaitLine(row.queues);
      var waitsHtml = '';
      if (waitLine) {
        waitsHtml =
          '<span class="airport-search-chip__wait-line">' + esc(waitLine) + '</span>';
      } else {
        waitsHtml =
          '<span class="airport-search-chip__wait airport-search-chip__wait--empty">—</span>';
      }
      html +=
        '<div class="airport-search-chip">' +
        '<span class="airport-search-chip__label" title="' +
        esc(label) +
        '">' +
        esc(label) +
        '</span>' +
        '<div class="airport-search-chip__waits">' +
        waitsHtml +
        '</div>' +
        '</div>';
    }
    html += '</div>';
    html += '<span class="airport-search-more-slot">';
    if (more > 0) {
      var moreTitle =
        more +
        ' more terminal' +
        (more === 1 ? '' : 's') +
        ' — open ' +
        code +
        ' for full list';
      html +=
        '<span class="airport-search-chip-more" title="' +
        esc(moreTitle) +
        '">+' +
        more +
        '</span>';
    }
    html += '</span>';
    html += '</div>';
    return html;
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function navigateToAirport(code) {
    window.location.href = '/' + encodeURIComponent(code);
  }

  /**
   * @param {object} opts
   * @param {HTMLInputElement} opts.input
   * @param {HTMLElement} opts.panel
   * @param {HTMLElement} opts.list
   * @param {string} [opts.currentAirportCode]
   * @param {number} [opts.maxResults]
   */
  function initTsaAirportSearch(opts) {
    var input = opts.input;
    var panel = opts.panel;
    var list = opts.list;
    var currentCode = (opts.currentAirportCode || '').toUpperCase();
    var maxResults = opts.maxResults || DEFAULT_MAX_RESULTS;

    var rows = [];
    var metros = {};
    var activeIndex = -1;
    var open = false;
    var listId = list.id || 'airport-search-results';
    var matchOrderState = { prevSetKey: null, prevOrder: [] };

    input.disabled = false;
    input.removeAttribute('disabled');
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', listId);
    list.setAttribute('role', 'listbox');

    function setOpen(v) {
      open = v;
      panel.hidden = !v;
      input.setAttribute('aria-expanded', v ? 'true' : 'false');
      if (!v) activeIndex = -1;
    }

    function openPanel() {
      if (!open) setOpen(true);
      fetchLatest()
        .catch(function () {
          /* keep stale latestJson if any */
        })
        .then(function () {
          refreshList();
        });
    }

    function render() {
      var ql = input.value.trim().toLowerCase();
      var ranked = rankRows(rows, metros, ql);
      ranked = stabilizeMatchOrder(ranked, matchOrderState);
      var slice = ranked.slice(0, maxResults);
      if (activeIndex >= slice.length) {
        activeIndex = slice.length > 0 ? slice.length - 1 : -1;
      }
      list.innerHTML = '';
      for (var i = 0; i < slice.length; i++) {
        (function (row) {
          var div = document.createElement('div');
          div.className = 'airport-search-row';
          div.setAttribute('role', 'option');
          div.id = listId + '-opt-' + i;
          div.dataset.code = row.code;
          if (row.code === currentCode) div.classList.add('airport-search-row--current');

          var loc = [row.city, row.state].filter(Boolean).join(', ');
          var metaParts = [];
          if (loc) metaParts.push(loc);
          if (row.metro_label) metaParts.push(row.metro_label);
          var meta = metaParts.join(' · ');

          div.innerHTML =
            '<div class="airport-search-row__main">' +
            '<div class="airport-search-row__left">' +
            '<div class="airport-search-row__top">' +
            '<span class="airport-search-code">' +
            esc(row.code) +
            '</span>' +
            '<span class="airport-search-name">' +
            esc(row.display_name) +
            '</span></div>' +
            (meta
              ? '<div class="airport-search-row__meta muted">' + esc(meta) + '</div>'
              : '') +
            '</div>' +
            buildTerminalChipsHtml(row.code, latestJson, rows) +
            '</div>';

          div.addEventListener('mousedown', function (e) {
            e.preventDefault();
            navigateToAirport(row.code);
          });
          list.appendChild(div);
        })(slice[i].row);
      }
      highlightActive();
    }

    function highlightActive() {
      var children = list.querySelectorAll('.airport-search-row');
      for (var c = 0; c < children.length; c++) {
        children[c].classList.toggle('is-active', c === activeIndex);
        children[c].setAttribute('aria-selected', c === activeIndex ? 'true' : 'false');
      }
    }

    function refreshList() {
      render();
    }

    fetchCatalog()
      .then(function (cat) {
        metros = cat.metros || {};
        rows = normalizeAirports(cat);
        matchOrderState.prevSetKey = null;
        matchOrderState.prevOrder = [];
        input.placeholder = 'Search airports (code, name, city, metro)…';
        if (open) refreshList();
      })
      .catch(function () {
        input.placeholder = 'Catalog unavailable';
      });

    input.addEventListener('focus', function () {
      openPanel();
    });

    input.addEventListener('input', function () {
      activeIndex = -1;
      if (!open) openPanel();
      else {
        fetchLatest()
          .catch(function () {})
          .then(function () {
            refreshList();
          });
      }
    });

    input.addEventListener('keydown', function (e) {
      if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        openPanel();
      }
      var n = list.querySelectorAll('.airport-search-row').length;
      if (!open || n === 0) {
        if (e.key === 'Escape') setOpen(false);
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        activeIndex = (activeIndex + 1) % n;
        highlightActive();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        activeIndex = activeIndex <= 0 ? n - 1 : activeIndex - 1;
        highlightActive();
      } else if (e.key === 'Enter') {
        if (activeIndex >= 0) {
          var row = list.querySelectorAll('.airport-search-row')[activeIndex];
          if (row && row.dataset.code) navigateToAirport(row.dataset.code);
        } else if (n === 1) {
          var only = list.querySelector('.airport-search-row');
          if (only && only.dataset.code) navigateToAirport(only.dataset.code);
        }
      } else if (e.key === 'Escape') {
        setOpen(false);
        input.blur();
      }
    });

    document.addEventListener('click', function (e) {
      if (!open) return;
      var t = e.target;
      if (panel.contains(t) || input === t || input.contains(t)) return;
      setOpen(false);
    });
  }

  window.initTsaAirportSearch = initTsaAirportSearch;
})();
