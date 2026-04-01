#!/usr/bin/env python3
"""Simple webapp: latest wait times + 24h terminal history charts."""
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta

from flask import Flask, render_template, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TSA_DB_PATH", os.path.join(APP_DIR, "tsa.db"))

app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"))
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

_access_logger = logging.getLogger("tsa.access")
_access_logger.setLevel(logging.INFO)
if not _access_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    _access_logger.addHandler(_h)
_access_logger.propagate = False
logging.getLogger("werkzeug").setLevel(logging.WARNING)


def _access_log_enabled():
    return os.environ.get("TSA_ACCESS_LOG", "true").lower() in ("1", "true", "yes")


@app.before_request
def _access_mark_start():
    if _access_log_enabled():
        request.environ["tsa.t0"] = time.perf_counter()


@app.after_request
def _access_log_line(response):
    if not _access_log_enabled():
        return response
    t0 = request.environ.get("tsa.t0")
    duration_ms = (
        round((time.perf_counter() - t0) * 1000, 2) if t0 is not None else None
    )
    payload = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "client_ip": request.remote_addr,
        "method": request.method,
        "path": request.path,
        "status": response.status_code,
        "duration_ms": duration_ms,
    }
    _access_logger.info(json.dumps(payload, separators=(",", ":")))
    return response


def get_db():
    return sqlite3.connect(DB_PATH)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/terminal/<airport>/<terminal>")
def terminal_detail(airport: str, terminal: str):
    return render_template("terminal.html", airport=airport, terminal=terminal)


@app.route("/api/latest")
def api_latest():
    """Latest scrape + 6h sparkline series per airport/terminal/queue."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT scraped_at_utc FROM wait_times ORDER BY scraped_at_utc DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify(scraped_at_utc=None, airports={})

    scraped_at_utc = row[0]
    cur.execute(
        """
        SELECT airport, terminal, queue_type, wait_minutes
        FROM wait_times
        WHERE scraped_at_utc = ?
        ORDER BY airport, terminal, queue_type
        """,
        (scraped_at_utc,),
    )
    rows = cur.fetchall()
    airports = {}
    for airport, terminal, queue_type, wait_minutes in rows:
        if airport not in airports:
            airports[airport] = {}
        if terminal not in airports[airport]:
            airports[airport][terminal] = {
                "general": None,
                "precheck": None,
                "spark_general": [],
                "spark_precheck": [],
            }
        key = "general" if queue_type == "general" else "precheck"
        airports[airport][terminal][key] = wait_minutes

    # Add 6-hour sparkline history per terminal/queue.
    since_6h = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cur.execute(
        """
        SELECT airport, terminal, queue_type, scraped_at_utc, wait_minutes
        FROM wait_times
        WHERE scraped_at_utc >= ?
        ORDER BY scraped_at_utc
        """,
        (since_6h,),
    )
    history_rows = cur.fetchall()
    conn.close()

    for airport, terminal, queue_type, scraped_at_utc, wait_minutes in history_rows:
        if airport not in airports or terminal not in airports[airport]:
            continue
        series_key = "spark_general" if queue_type == "general" else "spark_precheck"
        airports[airport][terminal][series_key].append(
            {"t": scraped_at_utc, "minutes": wait_minutes}
        )

    # Convert to list of { terminal, general, precheck } per airport
    result = {}
    for airport, terms in airports.items():
        result[airport] = [
            {
                "terminal": t,
                "general": d["general"],
                "precheck": d["precheck"],
                "spark_general": d["spark_general"],
                "spark_precheck": d["spark_precheck"],
            }
            for t, d in sorted(terms.items())
        ]

    return jsonify(scraped_at_utc=scraped_at_utc, airports=result)


@app.route("/api/history")
def api_history():
    """History for one airport + terminal. Query params: airport, terminal, hours."""
    airport = request.args.get("airport")
    terminal = request.args.get("terminal")
    if not airport or not terminal:
        return jsonify(error="airport and terminal required"), 400

    hours = request.args.get("hours", "24")
    allowed_hours = {"6", "12", "24", "72", "168"}
    if hours not in allowed_hours:
        return jsonify(error="hours must be one of 6, 12, 24, 72, 168"), 400

    since = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT scraped_at_utc
        FROM wait_times
        WHERE airport = ? AND terminal = ?
        ORDER BY scraped_at_utc DESC
        LIMIT 1
        """,
        (airport, terminal),
    )
    latest_row = cur.fetchone()
    latest_scraped_at_utc = latest_row[0] if latest_row else None

    cur.execute(
        """
        SELECT scraped_at_utc, queue_type, wait_minutes
        FROM wait_times
        WHERE airport = ? AND terminal = ? AND scraped_at_utc >= ?
        ORDER BY scraped_at_utc
        """,
        (airport, terminal, since),
    )
    rows = cur.fetchall()
    conn.close()

    general = []
    precheck = []
    for scraped_at_utc, queue_type, wait_minutes in rows:
        point = {"t": scraped_at_utc, "minutes": wait_minutes}
        if queue_type == "general":
            general.append(point)
        else:
            precheck.append(point)

    return jsonify(
        general=general,
        precheck=precheck,
        latest_scraped_at_utc=latest_scraped_at_utc,
    )


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    debug = os.environ.get("FLASK_DEBUG", "true").lower() in ("1", "true", "yes")
    app.run(host=host, port=5000, debug=debug)
