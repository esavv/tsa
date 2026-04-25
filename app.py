#!/usr/bin/env python3
"""Simple webapp: latest wait times + 24h terminal history charts."""
import json
import os
import sqlite3
import threading
import time
from typing import Optional
from datetime import datetime, timezone, timedelta
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TSA_DB_PATH", os.path.join(APP_DIR, "tsa.db"))
CATALOG_PATH = os.path.join(APP_DIR, "data", "airports.json")


def load_airport_catalog():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


try:
    AIRPORT_CATALOG = load_airport_catalog()
except (OSError, json.JSONDecodeError):
    AIRPORT_CATALOG = {"metros": {}, "airports": []}


def catalog_airport_entry(code: str) -> Optional[dict]:
    for ap in AIRPORT_CATALOG.get("airports", []):
        if ap.get("code") == code:
            return ap
    return None


def airport_catalog_status(code: str) -> str:
    ent = catalog_airport_entry(code)
    if not ent:
        return "active"
    return ent.get("status") or "active"


def is_hidden_airport(code: str) -> bool:
    return airport_catalog_status(code) == "hidden"


_DEFAULT_TERMINAL_TAB = {
    "ignore_gate": False,
    "without_gate": "Terminal {terminal}",
    "with_gate": "Terminal {terminal}: Gates {gate}",
}

_DEFAULT_WAIT_TIMES_UI = {
    "chip": "absolute",
    "chart_series": ["absolute"],
}


def _merge_wait_times_ui(entry: dict) -> dict:
    merged = dict(_DEFAULT_WAIT_TIMES_UI)
    raw_ui = entry.get("wait_times_ui")
    if isinstance(raw_ui, dict):
        chip = raw_ui.get("chip")
        if chip in ("absolute", "range", "min", "max"):
            merged["chip"] = chip
        cs = raw_ui.get("chart_series")
        if isinstance(cs, list):
            allowed = {"absolute", "range", "min", "max"}
            series = [x for x in cs if isinstance(x, str) and x in allowed]
            if series:
                merged["chart_series"] = series
    return merged


def _catalog_airport_public_dict(entry: dict) -> dict:
    """Copy for JSON responses with terminal_tab + wait_times_ui defaults merged."""
    out = dict(entry)
    tab = dict(out.get("terminal_tab") or {})
    out["terminal_tab"] = {**_DEFAULT_TERMINAL_TAB, **tab}
    out["wait_times_ui"] = _merge_wait_times_ui(out)
    return out


def airport_catalog_entry_for_js(code: str) -> dict:
    """Catalog row for the current airport; terminal_tab merged with template defaults if partial."""
    raw = dict(catalog_airport_entry(code) or {})
    raw["code"] = code
    status = raw.get("status") or "active"
    if status not in ("active", "no_data", "coming_soon", "hidden"):
        status = "active"
    raw["status"] = status
    tab = dict(raw.get("terminal_tab") or {})
    merged_tab = {**_DEFAULT_TERMINAL_TAB, **tab}
    raw["terminal_tab"] = merged_tab
    raw["wait_times_ui"] = _merge_wait_times_ui(raw)
    return raw

# Keep in sync with scripts/scraper.py SCRAPE_AIRPORTS
AIRPORT_CODES = frozenset(
    {
        "LGA",
        "JFK",
        "EWR",
        "LAX",
        "MIA",
        "SEA",
        "DCA",
        "ATL",
        "DFW",
        "DEN",
        "CLT",
        "LAS",
        "MCO",
        "PHX",
    }
)

app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"))


def get_db():
    return sqlite3.connect(DB_PATH)


@app.route("/")
def index():
    return redirect(url_for("airport", code="JFK"), code=302)


@app.route("/<code>")
def airport(code: str):
    c = (code or "").strip().upper()
    if len(c) != 3 or not c.isalpha():
        abort(404)
    entry = catalog_airport_entry(c)
    if not entry or (entry.get("status") or "active") != "active":
        abort(404)
    initial_terminal = request.args.get("terminal") or ""
    initial_gate = request.args.get("gate") or ""
    airport_display_name = entry.get("display_name") or c
    city = entry.get("city") or ""
    state = entry.get("state") or ""
    locale_bits = [x for x in (city, state) if x]
    airport_locale_line = ", ".join(locale_bits) if locale_bits else None
    return render_template(
        "airport.html",
        airport=c,
        airport_display_name=airport_display_name,
        airport_locale_line=airport_locale_line,
        airport_catalog_entry=airport_catalog_entry_for_js(c),
        initial_terminal=initial_terminal,
        initial_gate=initial_gate,
    )


@app.route("/api/catalog")
def api_catalog():
    """Airport + metro metadata for client-side search (see data/airports.json)."""
    payload = dict(AIRPORT_CATALOG)
    payload["airports"] = [
        _catalog_airport_public_dict(ap)
        for ap in AIRPORT_CATALOG.get("airports", [])
        if not is_hidden_airport(ap.get("code") or "")
    ]
    return jsonify(payload)


_LATEST_CACHE_TTL_SEC = 30.0
_latest_cache_lock = threading.Lock()
_latest_cache: dict = {"mono_at": 0.0, "payload": None}


def _compute_api_latest_payload() -> dict:
    """Build the JSON-serializable body for ``GET /api/latest`` (no HTTP)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT scraped_at_utc FROM wait_times ORDER BY scraped_at_utc DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"scraped_at_utc": None, "airports": {}}

    scraped_at_utc = row[0]
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    cur.execute(
        """
        SELECT airport, terminal, gate, queue_type,
               wait_minutes, wait_min_minutes, wait_max_minutes
        FROM wait_times
        WHERE scraped_at_utc = ?
        """,
        (scraped_at_utc,),
    )
    latest_map: dict[tuple[str, str, str, str], dict[str, int | None]] = {}
    for (
        airport,
        terminal,
        gate,
        queue_type,
        wait_minutes,
        wait_min_minutes,
        wait_max_minutes,
    ) in cur.fetchall():
        g = gate or ""
        latest_map[(airport, terminal, g, queue_type)] = {
            "minutes": wait_minutes,
            "wait_min_minutes": wait_min_minutes,
            "wait_max_minutes": wait_max_minutes,
        }

    cur.execute(
        """
        SELECT DISTINCT airport, terminal, gate, queue_type
        FROM wait_times
        WHERE scraped_at_utc >= ?
        ORDER BY airport, terminal, gate, queue_type
        """,
        (since_24h,),
    )
    recent_keys = cur.fetchall()
    conn.close()

    airports: dict[str, dict[tuple[str, str], dict]] = {}
    for airport, terminal, gate, queue_type in recent_keys:
        if airport not in airports:
            airports[airport] = {}
        g = gate or ""
        key = (terminal, g)
        if key not in airports[airport]:
            airports[airport][key] = {"queues": {}}
        slot = airports[airport][key]["queues"]
        trip = latest_map.get((airport, terminal, g, queue_type)) or {}
        slot[queue_type] = {
            "minutes": trip.get("minutes"),
            "wait_min_minutes": trip.get("wait_min_minutes"),
            "wait_max_minutes": trip.get("wait_max_minutes"),
        }

    result = {}
    for airport, terms in airports.items():
        result[airport] = [
            {
                "terminal": t,
                "gate": g,
                "queues": d["queues"],
            }
            for (t, g), d in sorted(terms.items(), key=lambda item: (item[0][0], item[0][1]))
        ]

    result = {
        k: v for k, v in result.items() if not is_hidden_airport(k)
    }

    return {"scraped_at_utc": scraped_at_utc, "airports": result}


@app.route("/api/latest")
def api_latest():
    """Wait times at the newest global scrape, keyed by activity in the last 24 hours.

    ``scraped_at_utc`` is the latest timestamp in the DB (newest pipeline run).
    ``airports`` includes each airport / terminal / gate / queue_type that appears
    in the last 24 hours. ``minutes`` is the raw point wait at ``scraped_at_utc`` when
    stored, otherwise ``null`` (range-only rows or missing checkpoint at that scrape).

    Responses are ``Cache-Control: public, max-age=30`` and recomputed at most
    once per process every 30 seconds (in-memory), so bursts of traffic mostly
    hit RAM rather than SQLite.
    """
    with _latest_cache_lock:
        now = time.monotonic()
        if (
            _latest_cache["payload"] is not None
            and (now - _latest_cache["mono_at"]) < _LATEST_CACHE_TTL_SEC
        ):
            payload = _latest_cache["payload"]
        else:
            payload = _compute_api_latest_payload()
            _latest_cache["payload"] = payload
            _latest_cache["mono_at"] = now

    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "public, max-age=30"
    return resp


@app.route("/api/history")
def api_history():
    """History for one airport + terminal (+ optional gate). Returns queues keyed by queue_type."""
    airport = request.args.get("airport")
    terminal = request.args.get("terminal")
    if not airport or not terminal:
        return jsonify(error="airport and terminal required"), 400

    ap = (airport or "").strip().upper()
    if len(ap) == 3 and ap.isalpha() and is_hidden_airport(ap):
        abort(404)

    gate = request.args.get("gate") or ""

    hours = request.args.get("hours", "24")
    allowed_hours = {"6", "12", "24", "72", "168"}
    if hours not in allowed_hours:
        return jsonify(error="hours must be one of 6, 12, 24, 72, 168"), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT scraped_at_utc FROM wait_times ORDER BY scraped_at_utc DESC LIMIT 1"
    )
    global_latest_row = cur.fetchone()
    if not global_latest_row:
        conn.close()
        return jsonify(queues={}, latest_scraped_at_utc=None)

    global_latest_iso = global_latest_row[0]
    gl = global_latest_iso[:-1] + "+00:00" if global_latest_iso.endswith("Z") else global_latest_iso
    global_latest_dt = datetime.fromisoformat(gl)
    since_dt = global_latest_dt - timedelta(hours=int(hours))
    since = since_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cur.execute(
        """
        SELECT scraped_at_utc
        FROM wait_times
        WHERE airport = ? AND terminal = ? AND gate = ?
        ORDER BY scraped_at_utc DESC
        LIMIT 1
        """,
        (ap, terminal, gate),
    )
    latest_row = cur.fetchone()
    latest_scraped_at_utc = latest_row[0] if latest_row else None

    cur.execute(
        """
        SELECT scraped_at_utc, queue_type, wait_minutes,
               wait_min_minutes, wait_max_minutes
        FROM wait_times
        WHERE airport = ? AND terminal = ? AND gate = ? AND scraped_at_utc >= ?
        ORDER BY scraped_at_utc
        """,
        (ap, terminal, gate, since),
    )
    rows = cur.fetchall()
    conn.close()

    queues: dict[str, list[dict]] = {}
    for scraped_at_utc, queue_type, wait_minutes, wait_min_minutes, wait_max_minutes in rows:
        point = {
            "t": scraped_at_utc,
            "minutes": wait_minutes,
            "wait_min_minutes": wait_min_minutes,
            "wait_max_minutes": wait_max_minutes,
        }
        if queue_type not in queues:
            queues[queue_type] = []
        queues[queue_type].append(point)

    return jsonify(
        queues=queues,
        latest_scraped_at_utc=latest_scraped_at_utc,
    )


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    debug = os.environ.get("FLASK_DEBUG", "true").lower() in ("1", "true", "yes")
    app.run(host=host, port=5000, debug=debug)
