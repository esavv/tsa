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
    """Last 24h of wait times for one airport + terminal. Query params: airport, terminal."""
    airport = request.args.get("airport")
    terminal = request.args.get("terminal")
    if not airport or not terminal:
        return jsonify(error="airport and terminal required"), 400

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn = get_db()
    cur = conn.cursor()
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

    return jsonify(general=general, precheck=precheck)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
