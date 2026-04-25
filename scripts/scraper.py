#!/usr/bin/env python3
"""Fetch supported airport security wait times and insert them into SQLite."""
import argparse
import gzip
import html
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone

NYC_API_BASE = "https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints"
NYC_AIRPORTS = {
    "LGA": "https://www.laguardiaairport.com/",
    "JFK": "https://www.jfkairport.com/",
    "EWR": "https://www.newarkairport.com/",
}
LAX_WAIT_TIMES_URL = "https://www.flylax.com/wait-times"
MIA_WAIT_TIMES_PAGE_URL = "https://www.miami-airport.com/tsa-waittimes.asp"
SEA_WAIT_TIMES_URL = "https://www.portseattle.org/api/cwt/wait-times"
DCA_WAIT_TIMES_URL = "https://www.flyreagan.com/security-wait-times"
ATL_TIMES_URL = "https://www.atl.com/times/"
ATL_LEGACY_DOM_SELECTOR = "#nesclasser2 .declasser3 button span"
ATL_LAYOUT_READY_MS = 120_000
ATL_LEGACY_FALLBACK_MS = 20_000
ATL_NEW_SCAN_JS = r"""() => {
    const norm = (el) => (typeof el === "string" ? el : (el.textContent || ""))
        .replace(/\s+/g, " ")
        .trim();
    const apo = (s) => s.replace(/[\u2018\u2019`]/g, "'");
    const realmFromH1 = (tRaw) => {
        const t = apo(tRaw).toUpperCase();
        if (t === "DOMESTIC") return "Domestic";
        if (t === "INT'L" || t.includes("INT'L")) return "International";
        if (t.startsWith("INT")) return "International";
        if (t.includes("INTERNATIONAL")) return "International";
        return "";
    };
    const findWait = (h3) => {
        const n = (x) => (x.textContent || "").replace(/\s+/g, " ").trim();
        let el = h3.nextElementSibling;
        for (let i = 0; i < 12 && el; i++, el = el.nextElementSibling) {
            if (el.tagName === "H1" || el.tagName === "H2") break;
            const t = n(el);
            if (/^\d+$/.test(t)) return t;
            const btn = el.querySelector("button");
            if (btn) {
                const bt = n(btn);
                if (/^\d+$/.test(bt)) return bt;
            }
            for (const ch of el.children) {
                const ct = n(ch);
                if (/^\d+$/.test(ct)) return ct;
            }
        }
        const p = h3.parentElement;
        if (p && p.parentElement) {
            const row = p.parentElement;
            for (const cell of row.children) {
                if (cell.contains(h3)) continue;
                const t = n(cell);
                if (/^\d+$/.test(t)) return t;
                const b = cell.querySelector("button");
                if (b && /^\d+$/.test(n(b))) return n(b);
            }
        }
        return "";
    };
    const root = document.querySelector("main") || document.querySelector("#content")
        || document.body;
    let realm = "";
    let seenTsa = false;
    const results = [];
    for (const el of root.querySelectorAll("h1, h2, h3")) {
        if (el.tagName === "H1") {
            const t = norm(el);
            if (t.includes("TSA Security")) {
                seenTsa = true;
                realm = "";
                continue;
            }
            if (!seenTsa) continue;
            const r = realmFromH1(t);
            if (r) {
                realm = r;
                continue;
            }
            if (t === "ALERTS" || t.includes("Copyright")) realm = "";
            continue;
        }
        if (!seenTsa || !realm || el.tagName !== "H2") continue;
        const h2 = el;
        let h3 = h2.nextElementSibling;
        while (h3 && h3.tagName !== "H3") {
            if (h3.tagName === "H1" || h3.tagName === "H2") break;
            h3 = h3.nextElementSibling;
        }
        if (!h3 || h3.tagName !== "H3") continue;
        const waitText = findWait(h3);
        if (!waitText) continue;
        results.push({
            realm,
            checkpoint: norm(h2),
            sub: norm(h3),
            waitText,
        });
    }
    return results;
}"""
ATL_LEGACY_SCAN_JS = r"""() => {
    const results = [];
    function scan(section, realm) {
        if (!section) return;
        for (const row of section.querySelectorAll(":scope > .row")) {
            const h2 = row.querySelector("h2");
            const span = row.querySelector(".declasser3 button span");
            if (!h2 || !span) continue;
            const h3 = row.querySelector("h3");
            results.push({
                realm,
                checkpoint: h2.textContent.trim(),
                sub: h3 ? h3.textContent.trim() : "",
                waitText: span.textContent.trim(),
            });
        }
    }
    const root = document.querySelector("#nesclasser2");
    if (!root) return [];
    scan(root.querySelector(".col-lg-4.nesclasser2"), "Domestic");
    scan(root.querySelector(".col-lg-5.nesclasser1"), "International");
    return results;
}"""
DFW_WAIT_TIMES_URL = "https://api.dfwairport.mobi/wait-times/checkpoint/DFW"
DFW_MOBILE_API_KEY = "87856E0636AA4BF282150FCBE1AD63DE"
DFW_MOBILE_API_VERSION = "170"
CLT_WAIT_TIMES_URL = "https://api.cltairport.mobi/wait-times/checkpoint/CLT"
CLT_MOBILE_API_KEY = "5ccb418715f9428ca6cb4df1635d4815"
CLT_MOBILE_API_VERSION = "130"
MCO_WAIT_TIMES_URL = "https://api.goaa.aero/wait-times/checkpoint/MCO"
MCO_MOBILE_API_KEY = "8eaac7209c824616a8fe58d22268cd59"
MCO_MOBILE_API_VERSION = "140"
PHX_AVN_URL = "https://api.phx.aero/avn-wait-times/raw"
PHX_AVN_KEY_FALLBACK = "4f85fe2ef5a240d59809b63de94ef536"
PHX_HOME_URL = "https://www.skyharbor.com/"
DEN_FRUITION_TSA_URL = "https://app.flyfruition.com/api/public/tsa"
DEN_FRUITION_X_API_KEY = "vqw8ruvwqpv02pqu938bh5p028"
LAS_SECURITY_WAIT_URL = "https://www.harryreidairport.com/security-wait-times"
ZENSORS_TRPC_BASE = "https://embed.zensors.live/api/embeddable-widget/trpc"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_DB_PATH = os.path.join(REPO_ROOT, "tsa.db")
SCRAPE_AIRPORTS = (
    "LGA",
    "JFK",
    "EWR",
    "LAX",
    "MIA",
    "SEA",
    "DCA",
    "DFW",
    "DEN",
    "CLT",
    "LAS",
    "MCO",
    "PHX",
    "ATL",
)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Encoding": "gzip, deflate",
}
SCRAPE_ERROR_MAX_LEN = 512
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def fetch_bytes(url: str, headers: dict[str, str] | None = None) -> bytes:
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)
    req = urllib.request.Request(url, headers=merged_headers)
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if "gzip" in encoding:
            body = gzip.decompress(body)
        elif "deflate" in encoding:
            body = zlib.decompress(body)
        return body


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    return fetch_bytes(url, headers=headers).decode("utf-8", errors="ignore")


def fetch_json_url(url: str, headers: dict[str, str] | None = None):
    return json.loads(fetch_text(url, headers=headers))


def clean_html_text(value: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", value))).strip()


def normalize_terminal(value: str) -> str:
    value = clean_html_text(value)
    return re.sub(r"^Terminal\s+", "", value, flags=re.IGNORECASE)


def normalize_nyc_gate(raw) -> str:
    """Map Port Authority API `gate` to DB key; '' means whole-terminal (e.g. All Gates)."""
    if raw is None:
        return ""
    s = clean_html_text(str(raw)).strip()
    if not s:
        return ""
    low = s.lower().replace("–", "-")
    if low in ("all gates", "all gate", "all-gates", "all"):
        return ""
    return s


def normalize_queue_type(value: str) -> str:
    lowered = value.lower()
    if "pre" in lowered:
        return "precheck"
    if "priority" in lowered:
        return "priority"
    if "clear" in lowered:
        return "clear"
    return "general"


def parse_wait_minutes(value: str) -> int:
    lowered = value.lower()
    if any(marker in lowered for marker in ("closed", "opens", "unavailable")):
        return 0

    less_than = re.search(r"<\s*(\d+)", lowered)
    if less_than:
        return max(int(less_than.group(1)) - 1, 0)

    range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", lowered)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return round((start + end) / 2)

    integer_match = re.search(r"(\d+)", lowered)
    if integer_match:
        return int(integer_match.group(1))

    return 0


def parse_wait_text_to_fields(value: str) -> tuple[int | None, int | None, int | None]:
    """(wait_minutes, wait_min_minutes, wait_max_minutes). Point only for a lone integer; bands never fill point.

    ``<n`` → (None, 0, n); ``>n`` → (None, n, None); ``a-b`` → (None, a, b); closed/unavailable → (0, None, None).
    """
    lowered = (value or "").lower().strip()
    if not lowered:
        return None, None, None
    if any(marker in lowered for marker in ("closed", "opens", "unavailable")):
        return 0, None, None

    gt_match = re.search(r">\s*(\d+)", lowered)
    if gt_match:
        return None, int(gt_match.group(1)), None

    lt_match = re.search(r"<\s*(\d+)", lowered)
    if lt_match:
        return None, 0, int(lt_match.group(1))

    range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", lowered)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return None, start, end

    integer_match = re.search(r"(\d+)", lowered)
    if integer_match:
        return int(integer_match.group(1)), None, None

    return None, None, None


def parse_den_wait_minutes(value: str) -> int:
    """Parse DEN FlyFruition `wait_time` strings; numeric ranges use the high end (conservative)."""
    lowered = value.lower()
    if any(marker in lowered for marker in ("closed", "opens", "unavailable")):
        return 0

    less_than = re.search(r"<\s*(\d+)", lowered)
    if less_than:
        return max(int(less_than.group(1)) - 1, 0)

    range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", lowered)
    if range_match:
        return int(range_match.group(2))

    integer_match = re.search(r"(\d+)", lowered)
    if integer_match:
        return int(integer_match.group(1))

    return 0


def parse_den_wait_to_fields(value: str) -> tuple[int | None, int | None, int | None]:
    """DEN FlyFruition strings → (point, min, max). Same rules as parse_wait_text_to_fields (no synthetic point for ranges)."""
    lowered = (value or "").lower().strip()
    if not lowered:
        return None, None, None
    if any(marker in lowered for marker in ("closed", "opens", "unavailable")):
        return 0, None, None

    gt_match = re.search(r">\s*(\d+)", lowered)
    if gt_match:
        return None, int(gt_match.group(1)), None

    lt_match = re.search(r"<\s*(\d+)", lowered)
    if lt_match:
        return None, 0, int(lt_match.group(1))

    range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", lowered)
    if range_match:
        lo = int(range_match.group(1))
        hi = int(range_match.group(2))
        return None, lo, hi

    integer_match = re.search(r"(\d+)", lowered)
    if integer_match:
        return int(integer_match.group(1)), None, None

    return None, None, None


def _phx_mia_wait_fields(point: dict) -> tuple[int | None, int | None, int | None]:
    """MIA / PHX Avinor-style payloads: raw point from projected seconds; min/max from minute fields (partial OK)."""
    wait_m: int | None = None
    pws = point.get("projectedWaitTime")
    if pws is not None:
        try:
            wait_m = max(0, round(float(pws) / 60))
        except (TypeError, ValueError):
            wait_m = None

    min_m: int | None = None
    max_m: int | None = None
    mi, ma = point.get("projectedMinWaitMinutes"), point.get("projectedMaxWaitMinutes")
    if mi is not None:
        try:
            min_m = int(mi)
        except (TypeError, ValueError):
            pass
    if ma is not None:
        try:
            max_m = int(ma)
        except (TypeError, ValueError):
            pass
    if min_m is None and max_m is not None:
        min_m = 0
    return wait_m, min_m, max_m


def omit_nyc_wait_point(point: dict) -> bool:
    """Skip API points for a closed queue with no wait. Open-but-unavailable (e.g. 'No Wait') still records 0."""
    try:
        minutes = int(point.get("timeInMinutes", 0))
    except (TypeError, ValueError):
        minutes = 0
    if minutes != 0:
        return False
    if point.get("queueOpen") is False:
        return True
    return False


def fetch_nyc_airport(airport: str) -> list[dict]:
    url = f"{NYC_API_BASE}/{airport}"
    origin = NYC_AIRPORTS[airport]
    points = fetch_json_url(
        url,
        headers={
            "Referer": origin,
            "Origin": origin,
        },
    )
    rows = []
    for point in points:
        if omit_nyc_wait_point(point):
            continue
        raw_tm = point.get("timeInMinutes")
        if raw_tm is None:
            continue
        try:
            wm = int(raw_tm)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "airport": airport,
                "terminal": point.get("terminal", ""),
                "gate": normalize_nyc_gate(point.get("gate")),
                "queue_type": "general" if point.get("queueType") == "Reg" else "precheck",
                "wait_minutes": wm,
                "wait_min_minutes": None,
                "wait_max_minutes": None,
                "source_updated_at": point.get("updateTime") or None,
                "point_id": point.get("pointID"),
            }
        )
    return rows


def fetch_lax_airport() -> list[dict]:
    page = fetch_text(LAX_WAIT_TIMES_URL)
    updated_match = re.search(
        r"Data Last Updated:</div>\s*<div>(.*?)</div>",
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    source_updated_at = clean_html_text(updated_match.group(1)) if updated_match else None

    body_match = re.search(r"<tbody[^>]*>(.*?)</tbody>", page, flags=re.IGNORECASE | re.DOTALL)
    if not body_match:
        raise ValueError("Could not find LAX wait-times table body")

    rows = []
    for tr_html in re.findall(r"<tr[^>]*>(.*?)</tr>", body_match.group(1), flags=re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr_html, flags=re.IGNORECASE | re.DOTALL)
        if len(cells) < 3:
            continue
        terminal = normalize_terminal(cells[0])
        lane = clean_html_text(cells[1])
        wait_text = clean_html_text(cells[2])
        w, lo, hi = parse_wait_text_to_fields(wait_text)
        if w is None and lo is None and hi is None:
            continue
        rows.append(
            {
                "airport": "LAX",
                "terminal": terminal,
                "gate": "",
                "queue_type": normalize_queue_type(lane),
                "wait_minutes": w,
                "wait_min_minutes": lo,
                "wait_max_minutes": hi,
                "source_updated_at": source_updated_at,
                "point_id": None,
            }
        )
    return rows


def extract_mia_api_details() -> tuple[str, str]:
    page = fetch_text(MIA_WAIT_TIMES_PAGE_URL)
    script_match = re.search(r'src="([^"]*/js/wait-times/main\.[^"]+\.js)"', page)
    if not script_match:
        raise ValueError("Could not find MIA wait-times app bundle")

    script_url = urllib.request.urljoin(MIA_WAIT_TIMES_PAGE_URL, script_match.group(1))
    script = fetch_text(script_url)

    url_match = re.search(r'https://waittime\.api\.aero/waittime/v2/current/MIA', script)
    key_match = re.search(r'x-apikey":"([a-f0-9]+)"', script, flags=re.IGNORECASE)
    if not url_match or not key_match:
        raise ValueError("Could not extract MIA wait-times API details")
    return url_match.group(0), key_match.group(1)


def fetch_mia_airport() -> list[dict]:
    api_url, api_key = extract_mia_api_details()
    payload = fetch_json_url(
        api_url,
        headers={
            "x-apikey": api_key,
            "Referer": "https://www.miami-airport.com/",
            "Origin": "https://www.miami-airport.com",
        },
    )

    rows = []
    for point in payload.get("current", []):
        queue_name = (point.get("queueName") or "").strip()
        if not queue_name or " " not in queue_name:
            continue
        terminal, lane = queue_name.split(" ", 1)
        wait_minutes, min_wait_m, max_wait_m = _phx_mia_wait_fields(point)
        if wait_minutes is None and min_wait_m is None and max_wait_m is None:
            continue

        rows.append(
            {
                "airport": "MIA",
                "terminal": normalize_terminal(terminal),
                "gate": "",
                "queue_type": normalize_queue_type(lane),
                "wait_minutes": wait_minutes,
                "wait_min_minutes": min_wait_m,
                "wait_max_minutes": max_wait_m,
                "source_updated_at": point.get("time") or None,
                "point_id": None,
            }
        )
    return rows


def parse_microsoft_json_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"/Date\((\d+)\)/", value)
    if not match:
        return value
    dt = datetime.fromtimestamp(int(match.group(1)) / 1000, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_sea_airport() -> list[dict]:
    payload = fetch_json_url(SEA_WAIT_TIMES_URL)
    rows = []
    for checkpoint in payload:
        rows.append(
            {
                "airport": "SEA",
                "terminal": normalize_terminal(str(checkpoint.get("Name", ""))),
                "gate": "",
                "queue_type": "general",
                "wait_minutes": int(checkpoint.get("WaitTimeMinutes", 0)) if checkpoint.get("IsOpen") and checkpoint.get("IsDataAvailable") else 0,
                "wait_min_minutes": None,
                "wait_max_minutes": None,
                "source_updated_at": parse_microsoft_json_date(checkpoint.get("LastUpdated")),
                "point_id": checkpoint.get("CheckpointID"),
            }
        )
    return rows


def fetch_dca_airport() -> list[dict]:
    payload = fetch_json_url(DCA_WAIT_TIMES_URL)
    rows = []
    response = payload.get("response", {})
    checkpoints = response.get("res", {})

    for checkpoint in checkpoints.values():
        terminal = normalize_terminal(checkpoint.get("location", ""))
        if checkpoint.get("isDisabled") != 1:
            w, lo, hi = parse_wait_text_to_fields(str(checkpoint.get("waittime", "0")))
            if w is not None or lo is not None or hi is not None:
                rows.append(
                    {
                        "airport": "DCA",
                        "terminal": terminal,
                        "gate": "",
                        "queue_type": "general",
                        "wait_minutes": w,
                        "wait_min_minutes": lo,
                        "wait_max_minutes": hi,
                        "source_updated_at": None,
                        "point_id": None,
                    }
                )
        if checkpoint.get("pre_disabled") != 1:
            w, lo, hi = parse_wait_text_to_fields(str(checkpoint.get("pre", "0")))
            if w is not None or lo is not None or hi is not None:
                rows.append(
                    {
                        "airport": "DCA",
                        "terminal": terminal,
                        "gate": "",
                        "queue_type": "precheck",
                        "wait_minutes": w,
                        "wait_min_minutes": lo,
                        "wait_max_minutes": hi,
                        "source_updated_at": None,
                        "point_id": None,
                    }
                )
    return rows


def _mobi_optional_minutes_from_seconds(sec: object) -> int | None:
    if sec is None:
        return None
    try:
        v = int(sec)
    except (TypeError, ValueError):
        return None
    return max(0, round(v / 60))


def _fetch_mobi_checkpoint_json(url: str, api_key: str, api_version: str) -> dict:
    payload = fetch_json_url(
        url,
        headers={
            "api-key": api_key,
            "api-version": str(api_version),
            "Accept": "application/json",
        },
    )
    st = payload.get("status") or {}
    code = st.get("code")
    if code is not None and int(code) != 200:
        raise ValueError(f"Mobi wait-times API error: {st}")
    return payload


def _iso_from_mobi_timestamp(ts: object) -> str | None:
    if ts is None:
        return None
    try:
        sec = int(ts)
        if sec > 10_000_000_000:
            sec //= 1000
        return datetime.fromtimestamp(sec, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError):
        return None


def _mobi_lane_queue_type(lane: str) -> str:
    s = (lane or "").strip().lower()
    if s in ("general", "precheck"):
        return s
    if "priority" in s:
        return "priority"
    # DFW uses "TSA Pre"; substring "pre" maps to precheck.
    if "pre" in s:
        return "precheck"
    return "general"


def _mobi_queue_type(airport: str, wt: dict, lane: str) -> str:
    """Lane string is authoritative for DFW/MCO; CLT uses `attributes` (lane is always 'main')."""
    if airport == "CLT":
        attrs = wt.get("attributes") if isinstance(wt.get("attributes"), dict) else {}
        if attrs.get("preCheck") is True:
            return "precheck"
        if attrs.get("general") is True:
            return "general"
    return _mobi_lane_queue_type(lane)


def _mobi_terminal_gate(airport: str, wt: dict) -> tuple[str, str]:
    name = (wt.get("name") or "").strip()
    wid = str(wt.get("id") or "").strip()
    if airport == "DFW":
        m = re.match(r"^([A-Z])(\d+)$", name)
        if m:
            return m.group(1), m.group(2)
        return name, wid or ""
    if airport == "MCO":
        # Terminal: API `name` without lane-type suffix (queue comes from `lane`).
        terminal = re.sub(
            r"\s+(?:TSA\s+Pre(?:Check|check)?|Pre\s*Check|Standard)\s*$",
            "",
            name.strip(),
            flags=re.IGNORECASE,
        ).strip()
        attrs = wt.get("attributes") if isinstance(wt.get("attributes"), dict) else {}
        ming = str(attrs.get("minGate") or "").strip()
        maxg = str(attrs.get("maxGate") or "").strip()
        if ming and maxg:
            gate = f"{ming}-{maxg}"
        elif ming or maxg:
            gate = ming or maxg
        else:
            gate = ""
        return terminal, gate
    if airport == "CLT":
        # CLT Mobi uses numeric `id` (checkpoint id), not a gate range; keep gate empty.
        return name, ""
    return name, wid or ""


def _dedupe_wait_rows_by_checkpoint(rows: list[dict]) -> list[dict]:
    """Merge duplicate airport/terminal/gate/queue rows (prefer higher point wait, then fresher source)."""

    def _point_rank(w: object) -> tuple[int, int]:
        if w is None:
            return (-1, 0)
        try:
            return (1, int(w))
        except (TypeError, ValueError):
            return (-1, 0)

    merged: dict[tuple[str, str, str, str], dict] = {}
    for r in rows:
        k = (r["airport"], r["terminal"], r.get("gate", ""), r["queue_type"])
        if k not in merged:
            merged[k] = dict(r)
            continue
        cur = merged[k]
        rw, cw = r.get("wait_minutes"), cur.get("wait_minutes")
        r_rank, r_val = _point_rank(rw)
        c_rank, c_val = _point_rank(cw)
        if (r_rank, r_val) > (c_rank, c_val):
            merged[k] = dict(r)
            continue
        if (r_rank, r_val) == (c_rank, c_val):
            a, b = r.get("source_updated_at") or "", cur.get("source_updated_at") or ""
            if a > b:
                merged[k] = dict(r)
            continue
        a, b = r.get("source_updated_at") or "", cur.get("source_updated_at") or ""
        if a > b:
            cur["source_updated_at"] = r.get("source_updated_at")
            cur["wait_min_minutes"] = r.get("wait_min_minutes")
            cur["wait_max_minutes"] = r.get("wait_max_minutes")
            if rw is not None and cw is None:
                cur["wait_minutes"] = rw
    return list(merged.values())


def _parse_mobi_checkpoint_wait_rows(airport: str, payload: dict) -> list[dict]:
    data = payload.get("data") or {}
    wait_times = data.get("wait_times")
    if not isinstance(wait_times, list):
        raise ValueError(f"{airport} wait-times API returned unexpected payload")
    rows: list[dict] = []
    for wt in wait_times:
        if not wt.get("isOpen"):
            continue
        if wt.get("isDisplayable") is False:
            continue
        lane = str(wt.get("lane") or "")
        ws = wt.get("waitSeconds")
        if ws is None:
            wait_minutes: int | None = None
        else:
            try:
                wait_minutes = max(0, round(int(ws) / 60))
            except (TypeError, ValueError):
                wait_minutes = None
        wait_lo = _mobi_optional_minutes_from_seconds(wt.get("minWaitSeconds"))
        wait_hi = _mobi_optional_minutes_from_seconds(wt.get("maxWaitSeconds"))
        if wait_minutes is None and wait_lo is None and wait_hi is None:
            continue
        terminal, gate = _mobi_terminal_gate(airport, wt)
        wid = str(wt.get("id") or "").strip()
        point_id: int | None
        if wid.isdigit():
            point_id = int(wid)
        else:
            point_id = None
        rows.append(
            {
                "airport": airport,
                "terminal": terminal,
                "gate": gate,
                "queue_type": _mobi_queue_type(airport, wt, lane),
                "wait_minutes": wait_minutes,
                "wait_min_minutes": wait_lo,
                "wait_max_minutes": wait_hi,
                "source_updated_at": _iso_from_mobi_timestamp(wt.get("lastUpdatedTimestamp")),
                "point_id": point_id,
            }
        )
    if not rows:
        raise ValueError(f"{airport} Mobi API returned no open displayable checkpoints")
    return _dedupe_wait_rows_by_checkpoint(rows)


def fetch_dfw_airport() -> list[dict]:
    payload = _fetch_mobi_checkpoint_json(
        DFW_WAIT_TIMES_URL, DFW_MOBILE_API_KEY, DFW_MOBILE_API_VERSION
    )
    return _parse_mobi_checkpoint_wait_rows("DFW", payload)


def fetch_clt_airport() -> list[dict]:
    payload = _fetch_mobi_checkpoint_json(
        CLT_WAIT_TIMES_URL, CLT_MOBILE_API_KEY, CLT_MOBILE_API_VERSION
    )
    return _parse_mobi_checkpoint_wait_rows("CLT", payload)


def fetch_mco_airport() -> list[dict]:
    payload = _fetch_mobi_checkpoint_json(
        MCO_WAIT_TIMES_URL, MCO_MOBILE_API_KEY, MCO_MOBILE_API_VERSION
    )
    return _parse_mobi_checkpoint_wait_rows("MCO", payload)


def _extract_phx_avn_key() -> str:
    page = fetch_text(PHX_HOME_URL)
    m = re.search(r"api\.phx\.aero/avn-wait-times/raw\?Key=([a-f0-9]+)", page, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return PHX_AVN_KEY_FALLBACK


def fetch_phx_airport() -> list[dict]:
    key = _extract_phx_avn_key()
    url = f"{PHX_AVN_URL}?Key={urllib.parse.quote(key)}"
    payload = fetch_json_url(
        url,
        headers={
            "Referer": PHX_HOME_URL,
            "Origin": "https://www.skyharbor.com",
        },
    )
    points = payload.get("current")
    if not isinstance(points, list) or not points:
        raise ValueError("PHX avn-wait-times API returned no current[] data")
    rows: list[dict] = []
    for point in points:
        qn = (point.get("queueName") or "").strip()
        if not qn or " " not in qn:
            continue
        route, lane_word = qn.rsplit(" ", 1)
        lane_l = lane_word.lower()
        if "general" in lane_l:
            queue_type = "general"
        elif "pre" in lane_l:
            queue_type = "precheck"
        else:
            queue_type = normalize_queue_type(lane_word)
        wait_minutes, min_wait_m, max_wait_m = _phx_mia_wait_fields(point)
        if wait_minutes is None and min_wait_m is None and max_wait_m is None:
            continue
        m = re.match(r"^(T\d+)\s+(.*)$", route)
        if m:
            terminal, gate = m.group(1), m.group(2).strip()
        else:
            terminal, gate = route, ""
        rows.append(
            {
                "airport": "PHX",
                "terminal": terminal,
                "gate": gate,
                "queue_type": queue_type,
                "wait_minutes": wait_minutes,
                "wait_min_minutes": min_wait_m,
                "wait_max_minutes": max_wait_m,
                "source_updated_at": point.get("time") or None,
                "point_id": None,
            }
        )
    if not rows:
        raise ValueError("PHX avn-wait-times produced no rows")
    return rows


def fetch_den_airport() -> list[dict]:
    zones = fetch_json_url(
        DEN_FRUITION_TSA_URL,
        headers={
            "x-api-key": DEN_FRUITION_X_API_KEY,
            "Referer": "https://www.flydenver.com/",
            "Origin": "https://www.flydenver.com",
        },
    )
    if not isinstance(zones, list):
        raise ValueError("DEN FlyFruition TSA API returned unexpected payload")
    rows: list[dict] = []
    for zone in zones:
        terminal = clean_html_text(str(zone.get("title") or ""))
        terminal = re.sub(r"\s+Security\s*$", "", terminal, flags=re.IGNORECASE).strip()
        if not terminal:
            continue
        for lane in zone.get("lanes") or []:
            if lane.get("hide_lane"):
                continue
            if lane.get("closed"):
                continue
            lane_title = clean_html_text(str(lane.get("title") or ""))
            if not lane_title:
                continue
            w, lo, hi = parse_den_wait_to_fields(str(lane.get("wait_time") or "0"))
            if w is None and lo is None and hi is None:
                continue
            rows.append(
                {
                    "airport": "DEN",
                    "terminal": terminal,
                    "gate": "",
                    "queue_type": normalize_queue_type(lane_title),
                    "wait_minutes": w,
                    "wait_min_minutes": lo,
                    "wait_max_minutes": hi,
                    "source_updated_at": None,
                    "point_id": None,
                }
            )
    if not rows:
        raise ValueError("DEN FlyFruition TSA API returned no lanes")
    return rows


def _extract_las_zensors_slug_token(page_html: str) -> tuple[str, str]:
    m = re.search(
        r"embed\.zensors\.live/LAS/([^/\"\s]+)/waitTimeExplorer\?token=([^&\"\s]+)",
        page_html,
        flags=re.IGNORECASE,
    )
    if not m:
        raise ValueError("LAS page missing Zensors embed slug/token")
    slug, token = m.group(1), html.unescape(m.group(2))
    return slug, token


def _zensors_trpc_get(procedure: str, body0: dict) -> list | dict:
    inp = json.dumps({"0": body0}, separators=(",", ":"))
    q = urllib.parse.urlencode({"batch": "1", "input": inp})
    url = f"{ZENSORS_TRPC_BASE}/{procedure}?{q}"
    return fetch_json_url(url)


def fetch_las_airport() -> list[dict]:
    page = fetch_text(LAS_SECURITY_WAIT_URL)
    slug, token = _extract_las_zensors_slug_token(page)
    init_batch = _zensors_trpc_get(
        "waitTimeExplorer.init",
        {"slug": slug, "domainSlug": "LAS", "token": token},
    )
    if not isinstance(init_batch, list) or not init_batch:
        raise ValueError("LAS Zensors init returned empty batch")
    init_data = (init_batch[0].get("result") or {}).get("data") or {}
    journeys = init_data.get("journeys") or {}
    if not isinstance(journeys, dict) or not journeys:
        raise ValueError("LAS Zensors init missing journeys")

    rows: list[dict] = []
    for journey_id, meta in journeys.items():
        journey_name = (meta.get("name") or journey_id).strip()
        m = re.match(r"^(T\d+)\s*-\s*(.+)$", journey_name)
        if m:
            terminal, gate = m.group(1), m.group(2).strip()
        else:
            terminal, gate = journey_name, ""
        upd_batch = _zensors_trpc_get(
            "waitTimeExplorer.update",
            {"journey": journey_id, "slug": slug, "domainSlug": "LAS", "token": token},
        )
        if not isinstance(upd_batch, list) or not upd_batch:
            continue
        paths = ((upd_batch[0].get("result") or {}).get("data") or {}).get("paths") or {}
        if not isinstance(paths, dict):
            continue
        for path_key, path in paths.items():
            pk = str(path_key).lower()
            if pk in ("general", "precheck"):
                queue_type = pk
            else:
                queue_type = normalize_queue_type(str(path_key))
            wt = (path or {}).get("waitTime") or {}
            if not (path or {}).get("open", True):
                continue
            val = wt.get("value")
            if val is None:
                continue
            try:
                wait_minutes = max(0, int(round(float(val))))
            except (TypeError, ValueError):
                continue
            ts = wt.get("timestamp")
            source_updated_at: str | None
            try:
                ms = int(ts)
                sec = ms // 1000 if ms > 10_000_000_000 else ms
                source_updated_at = datetime.fromtimestamp(
                    sec, timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (TypeError, ValueError, OSError):
                source_updated_at = None
            rows.append(
                {
                    "airport": "LAS",
                    "terminal": terminal,
                    "gate": gate,
                    "queue_type": queue_type,
                    "wait_minutes": wait_minutes,
                    "wait_min_minutes": None,
                    "wait_max_minutes": None,
                    "source_updated_at": source_updated_at,
                    "point_id": None,
                }
            )
    if not rows:
        raise ValueError("LAS Zensors produced no wait rows")
    return rows


def _atl_scan_items_to_rows(raw: list) -> list[dict]:
    rows: list[dict] = []
    for item in raw:
        wait_text = (item.get("waitText") or "").strip()
        w, lo, hi = parse_wait_text_to_fields(wait_text)
        if w is None and lo is None and hi is None:
            continue
        sub = (item.get("sub") or "").lower()
        queue_type = "precheck" if "pre" in sub else "general"
        checkpoint = (item.get("checkpoint") or "").strip()
        realm = (item.get("realm") or "").strip()
        rows.append(
            {
                "airport": "ATL",
                "terminal": realm,
                "gate": checkpoint,
                "queue_type": queue_type,
                "wait_minutes": w,
                "wait_min_minutes": lo,
                "wait_max_minutes": hi,
                "source_updated_at": None,
                "point_id": None,
            }
        )
    return rows


def fetch_atl_airport() -> list[dict]:
    """Load ATL /times/ in a real browser (Cloudflare); parse checkpoint rows from the DOM."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        try:
            page.goto(ATL_TIMES_URL, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_function(
                """() => {
                    if (document.querySelector("#nesclasser2")) return true;
                    return [...document.querySelectorAll("h1")].some((h) =>
                        (h.innerText || "").includes("TSA Security"));
                }""",
                timeout=ATL_LAYOUT_READY_MS,
            )
            page.wait_for_timeout(1500)
            raw_new = page.evaluate(ATL_NEW_SCAN_JS)
            rows = _atl_scan_items_to_rows(raw_new)
            if not rows:
                try:
                    page.wait_for_selector(
                        ATL_LEGACY_DOM_SELECTOR,
                        timeout=ATL_LEGACY_FALLBACK_MS,
                    )
                except Exception:
                    pass
                page.wait_for_timeout(500)
                raw_legacy = page.evaluate(ATL_LEGACY_SCAN_JS)
                rows = _atl_scan_items_to_rows(raw_legacy)
        finally:
            context.close()
            browser.close()

    if not rows:
        raise ValueError("ATL page loaded but no checkpoint rows were found")
    return rows


def _wait_row_has_signal(row: dict) -> bool:
    """At least one of point wait or range columns must be present (DB invariant)."""
    return (
        row.get("wait_minutes") is not None
        or row.get("wait_min_minutes") is not None
        or row.get("wait_max_minutes") is not None
    )


def fetch_airport(airport: str) -> list[dict]:
    if airport in NYC_AIRPORTS:
        return fetch_nyc_airport(airport)
    if airport == "LAX":
        return fetch_lax_airport()
    if airport == "MIA":
        return fetch_mia_airport()
    if airport == "SEA":
        return fetch_sea_airport()
    if airport == "DCA":
        return fetch_dca_airport()
    if airport == "ATL":
        return fetch_atl_airport()
    if airport == "DFW":
        return fetch_dfw_airport()
    if airport == "DEN":
        return fetch_den_airport()
    if airport == "CLT":
        return fetch_clt_airport()
    if airport == "LAS":
        return fetch_las_airport()
    if airport == "MCO":
        return fetch_mco_airport()
    if airport == "PHX":
        return fetch_phx_airport()
    raise ValueError(f"Unsupported airport: {airport}")


def store(db_path: str, rows: list[dict], scraped_at_utc: str) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    inserted = 0
    for row in rows:
        if not _wait_row_has_signal(row):
            raise ValueError(
                "wait row must set at least one of wait_minutes, wait_min_minutes, "
                f"wait_max_minutes: {row!r}"
            )
        try:
            cur.execute(
                """
                INSERT INTO wait_times
                (scraped_at_utc, airport, terminal, gate, queue_type, wait_minutes,
                 wait_min_minutes, wait_max_minutes, source_updated_at, point_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scraped_at_utc,
                    row["airport"],
                    row["terminal"],
                    row.get("gate", ""),
                    row["queue_type"],
                    row.get("wait_minutes"),
                    row.get("wait_min_minutes"),
                    row.get("wait_max_minutes"),
                    row.get("source_updated_at"),
                    row.get("point_id"),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return inserted


def _truncate_scrape_error(message: str) -> str:
    if len(message) <= SCRAPE_ERROR_MAX_LEN:
        return message
    return message[: SCRAPE_ERROR_MAX_LEN - 3] + "..."


def upsert_scrape_airport_stat(
    db_path: str,
    scraped_at_utc: str,
    airport: str,
    duration_ms: int,
    ok: bool,
    error: str | None,
) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    err_val = _truncate_scrape_error(error) if error else None
    cur.execute(
        """
        INSERT INTO scrape_airport_stats
            (scraped_at_utc, airport, duration_ms, ok, error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(scraped_at_utc, airport) DO UPDATE SET
            duration_ms = excluded.duration_ms,
            ok = excluded.ok,
            error = excluded.error
        """,
        (scraped_at_utc, airport, duration_ms, 1 if ok else 0, err_val),
    )
    conn.commit()
    conn.close()


def print_mobi_raw(airport: str) -> None:
    """Print the raw Mobi checkpoint JSON (DFW / CLT / MCO) for taxonomy / field inspection."""
    code = airport.strip().upper()
    endpoints: dict[str, tuple[str, str, str]] = {
        "DFW": (DFW_WAIT_TIMES_URL, DFW_MOBILE_API_KEY, DFW_MOBILE_API_VERSION),
        "CLT": (CLT_WAIT_TIMES_URL, CLT_MOBILE_API_KEY, CLT_MOBILE_API_VERSION),
        "MCO": (MCO_WAIT_TIMES_URL, MCO_MOBILE_API_KEY, MCO_MOBILE_API_VERSION),
    }
    if code not in endpoints:
        raise SystemExit("--raw supports DFW, CLT, and MCO (same Mobi API family).")
    url, api_key, api_version = endpoints[code]
    payload = _fetch_mobi_checkpoint_json(url, api_key, api_version)
    print(json.dumps(payload, indent=2))


def preview(airport: str) -> None:
    """Fetch one airport and print rows to stdout (no database writes)."""
    code = airport.strip().upper()
    scraped_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = fetch_airport(code)
    print(f"# preview {code} at {scraped_at_utc} ({len(rows)} rows, not stored)")
    if not rows:
        return

    keys = (
        "airport",
        "terminal",
        "gate",
        "queue_type",
        "wait_minutes",
        "wait_min_minutes",
        "wait_max_minutes",
        "source_updated_at",
        "point_id",
    )
    headers = ("airport", "terminal", "gate", "queue", "wait", "min", "max", "updated", "point_id")

    def cell(row: dict, key: str) -> str:
        val = row.get(key)
        return "" if val is None else str(val)

    body = [[cell(r, k) for k in keys] for r in rows]
    widths = [
        max(len(headers[i]), *(len(body[j][i]) for j in range(len(body))))
        for i in range(len(keys))
    ]

    def fmt_line(cells: tuple[str, ...] | list[str]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths))

    print(fmt_line(list(headers)))
    print(fmt_line(["-" * w for w in widths]))
    for row_cells in body:
        print(fmt_line(row_cells))


def run(db_path: str | None = None) -> None:
    db_path = db_path or os.environ.get("TSA_DB_PATH", DEFAULT_DB_PATH)
    scraped_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = 0
    failures: list[str] = []

    for airport in SCRAPE_AIRPORTS:
        t0 = time.perf_counter()
        try:
            rows = fetch_airport(airport)
            inserted = store(db_path, rows, scraped_at_utc)
            total += inserted
            duration_ms = int(round((time.perf_counter() - t0) * 1000))
            upsert_scrape_airport_stat(
                db_path, scraped_at_utc, airport, duration_ms, ok=True, error=None
            )
            print(f"{airport}: stored {inserted} rows")
        except Exception as exc:
            duration_ms = int(round((time.perf_counter() - t0) * 1000))
            upsert_scrape_airport_stat(
                db_path,
                scraped_at_utc,
                airport,
                duration_ms,
                ok=False,
                error=str(exc),
            )
            failures.append(f"{airport}: {exc}")
            print(f"{airport}: ERROR {exc}")

    if failures and total == 0:
        raise RuntimeError("All airport scrapes failed: " + "; ".join(failures))

    print(f"{scraped_at_utc} stored {total} rows ({db_path})")
    if failures:
        print("Failures: " + "; ".join(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch airport TSA wait times and store them in SQLite, or preview / inspect one airport."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--preview",
        metavar="CODE",
        help="Airport IATA code: fetch current wait times and print a table to stdout without writing to the database.",
    )
    group.add_argument(
        "--raw",
        metavar="CODE",
        help="DFW, CLT, or MCO only: print raw Mobi checkpoint JSON (includes attributes) for inspection; no DB write.",
    )
    args = parser.parse_args()
    if args.preview:
        preview(args.preview)
    elif args.raw:
        print_mobi_raw(args.raw)
    else:
        run()
