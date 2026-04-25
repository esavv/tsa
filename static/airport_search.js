/**
 * Airport catalog search: IATA code substring + tiered ranking on other fields
 * (per-word prefix only; no mid-token substring). No fuzzy/typo handling.
 * Expects /api/catalog (metros + airports) and uses /api/latest for row wait summaries.
 */
(function () {
  var CATALOG_URL = '/api/catalog';
  var LATEST_URL = '/api/latest';
  var LATEST_TTL_MS = 60000;
  var DEFAULT_MAX_RESULTS = 50;

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

  /** Split for prefix matching (whitespace and common separators between tokens). */
  function splitSearchWords(s) {
    return String(s)
      .toLowerCase()
      .split(/[\s\-–—,/]+/)
      .filter(function (w) {
        return w.length > 0;
      });
  }

  /**
   * IATA and similar codes: substring anywhere in the code string.
   * @param {string} hay
   * @param {string} ql normalized query
   * @param {number} tier lower = stronger field (code < display < …)
   * @returns {number} Infinity if no match
   */
  function matchScoreCode(hay, ql, tier) {
    if (!ql) return 0;
    if (hay == null || hay === '') return Infinity;
    var h = String(hay).toLowerCase();
    if (h === ql) return tier;
    if (h.startsWith(ql)) return tier + 2;
    var i = h.indexOf(ql);
    if (i < 0) return Infinity;
    return tier + 20 + i;
  }

  /**
   * Names, cities, aliases: each query word must prefix some hay word, in order
   * (subsequence over token list). No substring matches inside a token.
   * @returns {number} Infinity if no match
   */
  function matchScoreWordPrefix(hay, ql, tier) {
    if (!ql) return 0;
    if (hay == null || hay === '') return Infinity;
    var h = String(hay).toLowerCase();
    if (h === ql) return tier;
    if (h.startsWith(ql)) return tier + 2;

    var qWords = splitSearchWords(ql);
    if (qWords.length === 0) return Infinity;
    var hayWords = splitSearchWords(h);
    if (hayWords.length === 0) return Infinity;

    if (qWords.length === 1) {
      var q1 = qWords[0];
      var best = Infinity;
      for (var wi = 0; wi < hayWords.length; wi++) {
        var w = hayWords[wi];
        if (w === q1) best = Math.min(best, tier + 15);
        else if (w.startsWith(q1)) best = Math.min(best, tier + 25 + wi * 2);
      }
      return best;
    }

    var qi = 0;
    var score = tier + 35;
    for (var hi = 0; hi < hayWords.length && qi < qWords.length; hi++) {
      var hw = hayWords[hi];
      var qw = qWords[qi];
      if (hw === qw || hw.startsWith(qw)) {
        score += hi * 2 + qi * 3 + (hw === qw ? 0 : 1);
        qi++;
      }
    }
    if (qi < qWords.length) return Infinity;
    return score;
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
    scores.push(matchScoreCode(ap.code, ql, 0));
    scores.push(matchScoreWordPrefix(ap.display_name, ql, 200));
    if (ap.city) scores.push(matchScoreWordPrefix(ap.city, ql, 400));
    if (ap.state) scores.push(matchScoreWordPrefix(ap.state, ql, 500));
    if (ap.state_name) scores.push(matchScoreWordPrefix(ap.state_name, ql, 500));
    if (ap.city && ap.state) {
      scores.push(matchScoreWordPrefix(ap.city + ' ' + ap.state, ql, 420));
      scores.push(matchScoreWordPrefix(ap.city + ', ' + ap.state, ql, 420));
    }
    if (ap.city && ap.state_name) {
      scores.push(matchScoreWordPrefix(ap.city + ' ' + ap.state_name, ql, 420));
      scores.push(matchScoreWordPrefix(ap.city + ', ' + ap.state_name, ql, 420));
    }
    var aliases = ap.aliases || [];
    for (var a = 0; a < aliases.length; a++) {
      scores.push(matchScoreWordPrefix(aliases[a], ql, 600));
    }
    if (ap.metro_key && metros[ap.metro_key]) {
      var m = metros[ap.metro_key];
      scores.push(matchScoreWordPrefix(m.display_name, ql, 800));
      var ma = m.search_aliases || [];
      for (var b = 0; b < ma.length; b++) {
        scores.push(matchScoreWordPrefix(ma[b], ql, 800));
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
      var st = ap.status || 'active';
      if (st !== 'active' && st !== 'no_data' && st !== 'coming_soon') {
        st = 'active';
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
        status: st,
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

  function maxTerminalChipsForViewport() {
    if (typeof window !== 'undefined' && window.matchMedia) {
      return window.matchMedia('(max-width: 768px)').matches ? 2 : 3;
    }
    return 3;
  }

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
    var show = sorted.slice(0, maxTerminalChipsForViewport());
    var more = sorted.length - show.length;
    var html = '<div class="airport-search-row__chips" role="presentation">';
    html += '<div class="airport-search-row__chip-run">';
    for (var i = 0; i < show.length; i++) {
      var row = show[i];
      var label = terminalTabLabel(apEntry, row.terminal, row.gate);
      var chipMode =
        (apEntry.wait_times_ui && apEntry.wait_times_ui.chip) || 'absolute';
      var waitLineHtml = window.chipQueueWaitLineHtml(row.queues, esc, chipMode);
      var waitsHtml = '';
      if (waitLineHtml) {
        waitsHtml =
          '<span class="airport-search-chip__wait-line">' + waitLineHtml + '</span>';
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

  function searchChipsHtmlForRow(row, latest, catalogRows) {
    var st = row.status || 'active';
    if (st === 'coming_soon') {
      return (
        '<div class="airport-search-row__chips airport-search-row__chips--status muted" role="presentation">' +
        '<span class="airport-search-row__chips-msg">' +
        esc('Coming soon') +
        '</span><span class="airport-search-more-slot" aria-hidden="true"></span></div>'
      );
    }
    if (st === 'no_data') {
      return (
        '<div class="airport-search-row__chips airport-search-row__chips--status muted" role="presentation">' +
        '<span class="airport-search-row__chips-msg">' +
        esc('No data available') +
        '</span><span class="airport-search-more-slot" aria-hidden="true"></span></div>'
      );
    }
    return buildTerminalChipsHtml(row.code, latest, catalogRows);
  }

  function navigateToAirport(code) {
    window.location.href = '/' + encodeURIComponent(code);
  }

  /**
   * @param {object} opts
   * @param {HTMLInputElement} opts.input
   * @param {HTMLElement} opts.panel
   * @param {HTMLElement} opts.list
   * @param {number} [opts.maxResults]
   */
  function initTsaAirportSearch(opts) {
    var input = opts.input;
    var panel = opts.panel;
    var list = opts.list;
    var maxResults = opts.maxResults || DEFAULT_MAX_RESULTS;

    var rows = [];
    var metros = {};
    var activeIndex = -1;
    var open = false;
    var listId = list.id || 'airport-search-results';
    var matchOrderState = { prevSetKey: null, prevOrder: [] };

    var mqSearchMobile = window.matchMedia('(max-width: 768px)');
    var mqReduceMotion =
      window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
    function onSearchViewportChange() {
      if (!open) return;
      refreshList();
    }
    if (mqSearchMobile.addEventListener) {
      mqSearchMobile.addEventListener('change', onSearchViewportChange);
    } else if (mqSearchMobile.addListener) {
      mqSearchMobile.addListener(onSearchViewportChange);
    }

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
      input.setAttribute('aria-expanded', v ? 'true' : 'false');
      if (!v) activeIndex = -1;

      var reduceMotion = mqReduceMotion && mqReduceMotion.matches;
      if (reduceMotion) {
        panel.classList.remove('airport-search-panel--suppress-transition');
        if (v) {
          panel.hidden = false;
          panel.classList.add('airport-search-panel--open');
        } else {
          panel.classList.remove('airport-search-panel--open');
          panel.hidden = true;
        }
        return;
      }

      if (v) {
        panel.classList.remove('airport-search-panel--suppress-transition');
        panel.hidden = false;
        panel.classList.remove('airport-search-panel--open');
        void panel.offsetWidth;
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            panel.classList.add('airport-search-panel--open');
          });
        });
        return;
      }

      if (panel.hidden) return;
      panel.classList.add('airport-search-panel--suppress-transition');
      panel.classList.remove('airport-search-panel--open');
      panel.hidden = true;
      void panel.offsetWidth;
      panel.classList.remove('airport-search-panel--suppress-transition');
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
      if (!ql) {
        ranked = ranked.filter(function (s) {
          return (s.row.status || 'active') === 'active';
        });
      }
      ranked = stabilizeMatchOrder(ranked, matchOrderState);
      var slice = ranked.slice(0, maxResults);
      if (activeIndex >= slice.length) {
        activeIndex = slice.length > 0 ? slice.length - 1 : -1;
      }
      list.innerHTML = '';
      if (slice.length === 0) {
        activeIndex = -1;
        var empty = document.createElement('div');
        empty.className = 'airport-search-no-results';
        empty.setAttribute('role', 'status');
        empty.innerHTML = '<span class="muted">No results</span>';
        list.appendChild(empty);
        highlightActive();
        return;
      }
      for (var i = 0; i < slice.length; i++) {
        (function (row) {
          var div = document.createElement('div');
          div.className = 'airport-search-row';
          div.setAttribute('role', 'option');
          div.id = listId + '-opt-' + i;
          div.dataset.code = row.code;
          if ((row.status || 'active') !== 'active') {
            div.classList.add('airport-search-row--unavailable');
            div.setAttribute('aria-disabled', 'true');
          }

          var loc = [row.city, row.state].filter(Boolean).join(', ');
          var meta = loc || '';

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
            searchChipsHtmlForRow(row, latestJson, rows) +
            '</div>';

          div.addEventListener('mousedown', function (e) {
            e.preventDefault();
            if ((row.status || 'active') !== 'active') return;
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
        input.placeholder = 'Search airports';
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
          if (
            row &&
            row.dataset.code &&
            !row.classList.contains('airport-search-row--unavailable')
          ) {
            navigateToAirport(row.dataset.code);
          }
        } else if (n === 1) {
          var only = list.querySelector('.airport-search-row');
          if (
            only &&
            only.dataset.code &&
            !only.classList.contains('airport-search-row--unavailable')
          ) {
            navigateToAirport(only.dataset.code);
          }
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

    function searchShortcutIgnoresTarget(el) {
      if (!el) return false;
      if (el === input) return false;
      if (el.closest) {
        var ce = el.closest('[contenteditable="true"]');
        if (ce) return true;
      }
      var tag = el.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
      return false;
    }

    document.addEventListener(
      'keydown',
      function (e) {
        if (e.defaultPrevented || e.repeat) return;
        if (e.code !== 'Slash') return;
        if (!e.metaKey && !e.altKey) return;
        if (searchShortcutIgnoresTarget(e.target)) return;
        e.preventDefault();
        input.focus();
        openPanel();
      },
      true
    );
  }

  window.initTsaAirportSearch = initTsaAirportSearch;
})();
