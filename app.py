#!/usr/bin/env python3
"""Simple webapp: latest wait times + 24h terminal history charts."""
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify, request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TSA_DB_PATH", os.path.join(APP_DIR, "tsa.db"))

app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"))


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
    """Latest scrape: one timestamp, all airports/terminals with general + precheck."""
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
    conn.close()

    airports = {}
    for airport, terminal, queue_type, wait_minutes in rows:
        if airport not in airports:
            airports[airport] = {}
        if terminal not in airports[airport]:
            airports[airport][terminal] = {"general": None, "precheck": None}
        key = "general" if queue_type == "general" else "precheck"
        airports[airport][terminal][key] = wait_minutes

    # Convert to list of { terminal, general, precheck } per airport
    result = {}
    for airport, terms in airports.items():
        result[airport] = [
            {"terminal": t, "general": d["general"], "precheck": d["precheck"]}
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
