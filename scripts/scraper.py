#!/usr/bin/env python3
"""Fetch supported airport security wait times and insert them into SQLite."""

import argparse
import gzip
import html
import json
import math
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

NYC_API_BASE = (
    "https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints"
)
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
DFW_WAIT_TIMES_URL = "https://api.dfwairport.mobi/wait-times/checkpoint/DFW"
DFW_MOBILE_API_KEY = "87856E0636AA4BF282150FCBE1AD63DE"
DFW_MOBILE_API_VERSION = "170"
CLT_WAIT_TIMES_URL = "https://api.cltairport.mobi/wait-times/checkpoint/CLT"
CLT_MOBILE_API_KEY = "5ccb418715f9428ca6cb4df1635d4815"
CLT_MOBILE_API_VERSION = "130"
MCO_WAIT_TIMES_URL = "https://api.goaa.aero/wait-times/checkpoint/MCO"
MCO_MOBILE_API_KEY = "8eaac7209c824616a8fe58d22268cd59"
MCO_MOBILE_API_VERSION = "140"
IAH_WAIT_TIMES_URL = "https://api.houstonairports.mobi/wait-times/checkpoint/IAH"
IAH_MOBILE_API_KEY = "F2BC90CBC6F24FAE9285A8A72348C08D"
IAH_MOBILE_API_VERSION = "120"
PHX_AVN_URL = "https://api.phx.aero/avn-wait-times/raw"
PHX_AVN_KEY_FALLBACK = "4f85fe2ef5a240d59809b63de94ef536"
PHX_HOME_URL = "https://www.skyharbor.com/"
DEN_FRUITION_TSA_URL = "https://app.flyfruition.com/api/public/tsa"
DEN_FRUITION_X_API_KEY = "vqw8ruvwqpv02pqu938bh5p028"
LAS_SECURITY_WAIT_URL = "https://www.harryreidairport.com/security-wait-times"
MSP_WAIT_TIMES_URL = (
    "https://www.mspairport.com/airport/security-screening/security-wait-times"
)
DTW_WAIT_TIMES_URL = "https://proxy.metroairport.com/SkyFiiTSAProxy.ashx"
PHL_WAIT_TIMES_URL = "https://www.phl.org/phllivereach/metrics"
PHL_CHECKPOINT_PAGE_URL = (
    "https://www.phl.org/flights/security-information/checkpoint-hours"
)
PHL_WAIT_API_JS_URL = (
    "https://www.phl.org/modules/custom/phl_wait_api/js/wait-api.js?tec001"
)
BWI_WAIT_TIMES_URL = (
    "https://bwiairport.com/wp-content/themes/bwitheme/cache/wait-times.json"
)
BWI_HOME_URL = "https://bwiairport.com/"
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
    "IAH",
    "MSP",
    "DTW",
    "PHL",
    "BWI",
)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Encoding": "gzip, deflate",
}
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
# Everything a real Chrome tab sends on a top-level navigation, including the
# client hints and Sec-Fetch metadata. Cloudflare scores the completeness of
# this set: ATL returns its challenge page to requests that omit it, and serves
# the real page to requests that include it.
CHROME_NAV_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
# Residential egress, used only by sources that block this host's datacenter IP.
PROXY_ENV_VAR = "SCRAPE_PROXY_URL"
# Bounds a hung socket without failing slow-but-healthy sources: the slowest
# successful non-ATL fetch on record is DTW at ~31s.
FETCH_TIMEOUT_S = 60
SCRAPE_ERROR_MAX_LEN = 2048
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def _proxy_opener() -> urllib.request.OpenerDirector:
    proxy_url = os.environ.get(PROXY_ENV_VAR, "").strip()
    if not proxy_url:
        raise RuntimeError(
            f"{PROXY_ENV_VAR} is not set; this source needs residential egress"
        )
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    return urllib.request.build_opener(handler)


def fetch_bytes(
    url: str,
    headers: dict[str, str] | None = None,
    use_proxy: bool = False,
) -> bytes:
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)
    req = urllib.request.Request(url, headers=merged_headers)
    opener = _proxy_opener().open if use_proxy else urllib.request.urlopen
    with opener(req, timeout=FETCH_TIMEOUT_S) as resp:
        body = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if "gzip" in encoding:
            body = gzip.decompress(body)
        elif "deflate" in encoding:
            body = zlib.decompress(body)
        return body


def fetch_text(
    url: str,
    headers: dict[str, str] | None = None,
    use_proxy: bool = False,
) -> str:
    return fetch_bytes(url, headers=headers, use_proxy=use_proxy).decode(
        "utf-8", errors="ignore"
    )


def fetch_json_url(
    url: str,
    headers: dict[str, str] | None = None,
    use_proxy: bool = False,
):
    return json.loads(fetch_text(url, headers=headers, use_proxy=use_proxy))


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
    if "premier" in lowered:
        return "premier"
    if "priority" in lowered:
        return "priority"
    if "clear" in lowered:
        return "clear"
    return "general"


def parse_wait_text_to_fields(value: str) -> tuple[int | None, int | None, int | None]:
    """(wait_minutes, wait_min_minutes, wait_max_minutes). Point only for a lone integer; bands never fill point.

    ``<n`` → (None, 0, n); ``>n`` → (None, n, None); ``a-b`` → (None, a, b).
    Substrings ``closed`` or ``unavailable`` → (None, None, None) so callers omit the row (no wait signal).
    """
    lowered = (value or "").lower().strip()
    if not lowered:
        return None, None, None
    if any(marker in lowered for marker in ("closed", "unavailable")):
        return None, None, None

    gt_match = re.search(r"(?:>|more than|over)\s*(\d+)", lowered)
    if gt_match:
        return None, int(gt_match.group(1)), None

    lt_match = re.search(r"(?:<|less than|under)\s*(\d+)", lowered)
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
                "queue_type": "general"
                if point.get("queueType") == "Reg"
                else "precheck",
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
    source_updated_at = (
        clean_html_text(updated_match.group(1)) if updated_match else None
    )

    body_match = re.search(
        r"<tbody[^>]*>(.*?)</tbody>", page, flags=re.IGNORECASE | re.DOTALL
    )
    if not body_match:
        raise ValueError("Could not find LAX wait-times table body")

    rows = []
    for tr_html in re.findall(
        r"<tr[^>]*>(.*?)</tr>", body_match.group(1), flags=re.IGNORECASE | re.DOTALL
    ):
        cells = re.findall(
            r"<td[^>]*>(.*?)</td>", tr_html, flags=re.IGNORECASE | re.DOTALL
        )
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

    url_match = re.search(
        r"https://waittime\.api\.aero/waittime/v2/current/MIA", script
    )
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
        if not checkpoint.get("IsOpen") or not checkpoint.get("IsDataAvailable"):
            continue
        rows.append(
            {
                "airport": "SEA",
                "terminal": normalize_terminal(str(checkpoint.get("Name", ""))),
                "gate": "",
                "queue_type": "general",
                "wait_minutes": int(checkpoint.get("WaitTimeMinutes", 0)),
                "wait_min_minutes": None,
                "wait_max_minutes": None,
                "source_updated_at": parse_microsoft_json_date(
                    checkpoint.get("LastUpdated")
                ),
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
        # Bare "Terminal" normalizes to "" (prefix strip); skip — no stable tab key.
        if not terminal:
            continue
        if checkpoint.get("isDisabled") != 1:
            raw_wt = checkpoint.get("waittime")
            if raw_wt is not None and str(raw_wt).strip() != "":
                w, lo, hi = parse_wait_text_to_fields(str(raw_wt))
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
            raw_pre = checkpoint.get("pre")
            if raw_pre is not None and str(raw_pre).strip() != "":
                w, lo, hi = parse_wait_text_to_fields(str(raw_pre))
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


def _iah_is_customs_checkpoint(wt: dict) -> bool:
    attrs = wt.get("attributes") or []
    if isinstance(attrs, dict):
        attr_values = [str(k).lower() for k, v in attrs.items() if v]
    elif isinstance(attrs, list):
        attr_values = [str(v).lower() for v in attrs]
    else:
        attr_values = []
    lane = str(wt.get("lane") or "").strip().lower()
    name = str(wt.get("name") or "").strip().lower()
    return (
        "fis" in attr_values
        or lane == "fis"
        or "customs" in name
        or "immigration" in name
    )


def _iah_queue_type(wt: dict) -> str:
    name = str(wt.get("name") or "").lower()
    if "precheck" in name or "pre check" in name:
        return "precheck"
    if "premier" in name:
        return "premier"
    if "priority" in name:
        return "priority"
    return "general"


def _mobi_queue_type(airport: str, wt: dict, lane: str) -> str:
    """Lane string is authoritative for DFW/MCO; CLT uses `attributes` (lane is always 'main')."""
    if airport == "IAH":
        return _iah_queue_type(wt)
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
    if airport == "IAH":
        terminal = re.sub(r"^IAH\s+", "", name, flags=re.IGNORECASE).strip()
        terminal = re.sub(r"^Terminal\s+", "", terminal, flags=re.IGNORECASE).strip()
        terminal = re.sub(
            r"\s+(?:Standard|Pre\s*Check|PreCheck|Premier)\s*$",
            "",
            terminal,
            flags=re.IGNORECASE,
        ).strip()
        m = re.match(r"^([A-Z])(?:\s+(.+))?$", terminal)
        if m:
            return m.group(1), (m.group(2) or "").strip()
        return terminal, ""
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
        if airport == "IAH" and _iah_is_customs_checkpoint(wt):
            continue
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
                "source_updated_at": _iso_from_mobi_timestamp(
                    wt.get("lastUpdatedTimestamp")
                ),
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


def fetch_iah_airport() -> list[dict]:
    payload = _fetch_mobi_checkpoint_json(
        IAH_WAIT_TIMES_URL, IAH_MOBILE_API_KEY, IAH_MOBILE_API_VERSION
    )
    return _parse_mobi_checkpoint_wait_rows("IAH", payload)


def _extract_phx_avn_key() -> str:
    page = fetch_text(PHX_HOME_URL)
    m = re.search(
        r"api\.phx\.aero/avn-wait-times/raw\?Key=([a-f0-9]+)", page, flags=re.IGNORECASE
    )
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
        paths = ((upd_batch[0].get("result") or {}).get("data") or {}).get(
            "paths"
        ) or {}
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
                source_updated_at = datetime.fromtimestamp(sec, timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
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


class _AtlCheckpointParser(HTMLParser):
    """Pull checkpoint rows out of ATL's ``#nesclasser2`` wait-times block.

    The page nests each realm's checkpoints in its own column, and every row
    pairs a checkpoint heading with the wait number rendered inside a
    ``.declasser3`` button. Some headings are commented out in the markup, so
    this walks real tags rather than matching on raw text.
    """

    _REALM_MARKERS = (
        ("nesclasser2", "Domestic"),
        ("nesclasser1", "International"),
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._depth = 0
        self._realm = ""
        self._realm_depth = -1
        self._wait_depth = -1
        self._capturing: str | None = None
        self._buffer: list[str] = []
        self._pending: dict | None = None

    def _flush_pending(self) -> None:
        if self._pending and self._pending["waitText"]:
            self.items.append(self._pending)
        self._pending = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div":
            self._depth += 1
            classes = set((dict(attrs).get("class") or "").split())
            if "declasser3" in classes and self._wait_depth < 0:
                self._wait_depth = self._depth
            if self._realm_depth < 0:
                for marker, realm in self._REALM_MARKERS:
                    if marker in classes and "container-fluid" not in classes:
                        self._realm = realm
                        self._realm_depth = self._depth
                        break
            return
        if not self._realm:
            return
        if tag in ("h2", "h3") or (tag == "span" and self._wait_depth >= 0):
            self._capturing = "wait" if tag == "span" else tag
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capturing and (
            tag == self._capturing or (tag == "span" and self._capturing == "wait")
        ):
            text = SPACE_RE.sub(" ", "".join(self._buffer)).strip()
            field = self._capturing
            self._capturing = None
            self._buffer = []
            if field == "h2":
                self._flush_pending()
                self._pending = {
                    "realm": self._realm,
                    "checkpoint": text,
                    "sub": "",
                    "waitText": "",
                }
            elif field == "h3" and self._pending and not self._pending["sub"]:
                self._pending["sub"] = text
            elif field == "wait" and self._pending and not self._pending["waitText"]:
                self._pending["waitText"] = text
        if tag != "div":
            return
        if self._depth == self._wait_depth:
            self._wait_depth = -1
        if self._depth == self._realm_depth:
            self._flush_pending()
            self._realm = ""
            self._realm_depth = -1
        self._depth -= 1

    def close(self) -> None:
        super().close()
        self._flush_pending()


def _atl_page_debug_excerpt(page: str) -> str:
    """Compact page state for scrape_airport_stats.error when ATL parsing fails."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", page, re.IGNORECASE | re.S)
    title = clean_html_text(title_match.group(1))[:100] if title_match else ""
    challenged = bool(
        re.search(
            r"just a moment|checking your browser|cf-browser-verification", page, re.I
        )
    )
    return (
        f"len={len(page)} title={title!r} challenge={challenged} "
        f"legacy_dom={'nesclasser2' in page}"
    )


def fetch_atl_airport() -> list[dict]:
    """Read ATL's wait times straight from the server-rendered HTML.

    The page needs no JavaScript, but Cloudflare challenges requests whose
    headers do not look like a browser navigation. If the direct request is
    challenged anyway, retry through the residential proxy when one is
    configured.
    """
    page = ""
    direct_error = ""
    try:
        page = fetch_text(ATL_TIMES_URL, headers=CHROME_NAV_HEADERS)
        rows = _atl_scan_items_to_rows(_atl_parse_page(page))
        if rows:
            return rows
        direct_error = "no checkpoint rows; " + _atl_page_debug_excerpt(page)
    except Exception as exc:
        direct_error = f"{type(exc).__name__}: {exc}"

    if not os.environ.get(PROXY_ENV_VAR, "").strip():
        raise RuntimeError(f"ATL direct fetch failed ({direct_error}); no proxy set")

    page = fetch_text(ATL_TIMES_URL, headers=CHROME_NAV_HEADERS, use_proxy=True)
    rows = _atl_scan_items_to_rows(_atl_parse_page(page))
    if not rows:
        raise RuntimeError(
            f"ATL direct fetch failed ({direct_error}); proxy retry also found "
            f"no rows: {_atl_page_debug_excerpt(page)}"
        )
    return rows


def _atl_parse_page(page: str) -> list[dict]:
    parser = _AtlCheckpointParser()
    parser.feed(page)
    parser.close()
    return parser.items


def fetch_msp_airport() -> list[dict]:
    page = fetch_text(MSP_WAIT_TIMES_URL, headers=BROWSER_HEADERS)
    updated_match = re.search(
        r'class="security-wait-times-block__timestamp">\s*(.*?)\s*</div>',
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    source_updated_at = (
        clean_html_text(updated_match.group(1)) if updated_match else None
    )

    card_re = re.compile(
        r'<div class="security-wait-time[^"]*">.*?'
        r'<div class="security-wait-time__checkpoint-name">\s*<div>(?P<name>.*?)</div>.*?'
        r'<div class="security-wait-time__message">(?P<message>.*?)</div>.*?'
        r'<div class="security-wait-time__time">(?P<time>.*?)</div>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    rows: list[dict] = []
    for match in card_re.finditer(page):
        checkpoint = clean_html_text(match.group("name"))
        message = clean_html_text(match.group("message"))
        wait_text = clean_html_text(match.group("time")) or message
        w, lo, hi = parse_wait_text_to_fields(wait_text)
        if w is None and lo is None and hi is None:
            continue
        m = re.match(r"^T(\d+)\s+(.+)$", checkpoint, flags=re.IGNORECASE)
        if m:
            terminal, gate = m.group(1), m.group(2).strip()
        else:
            terminal, gate = checkpoint, ""
        queue_type = normalize_queue_type(message)
        rows.append(
            {
                "airport": "MSP",
                "terminal": terminal,
                "gate": gate,
                "queue_type": queue_type,
                "wait_minutes": w,
                "wait_min_minutes": lo,
                "wait_max_minutes": hi,
                "source_updated_at": source_updated_at,
                "point_id": None,
            }
        )
    if not rows:
        raise ValueError("MSP page produced no open wait-time cards")
    return rows


def fetch_dtw_airport() -> list[dict]:
    payload = fetch_json_url(DTW_WAIT_TIMES_URL)
    if not isinstance(payload, list):
        raise ValueError("DTW TSA proxy returned unexpected payload")
    rows: list[dict] = []
    for point in payload:
        terminal = clean_html_text(str(point.get("Name") or ""))
        if not terminal:
            continue
        try:
            wait_minutes = int(point.get("WaitTime"))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "airport": "DTW",
                "terminal": terminal,
                "gate": "",
                "queue_type": "general",
                "wait_minutes": max(0, wait_minutes),
                "wait_min_minutes": None,
                "wait_max_minutes": None,
                "source_updated_at": None,
                "point_id": None,
            }
        )
    if not rows:
        raise ValueError("DTW TSA proxy produced no rows")
    return rows


PHL_METRIC_MAP: dict[int, tuple[str, str, str, str]] = {
    4377: ("A", "West", "general", "tA"),
    4368: ("A", "East", "general", "tAe"),
    4386: ("A", "East", "precheck", "tAepre"),
    5047: ("B", "", "general", "tB"),
    5052: ("C", "", "general", "tC"),
    3971: ("D/E", "", "general", "tDE"),
    4126: ("D/E", "", "precheck", "tDEpre"),
    5068: ("F", "", "general", "tF"),
}


def _parse_phl_checkpoint_hours(js_text: str) -> dict[str, tuple[str, str]]:
    m = re.search(r"const\s+tHours\s*=\s*\{(?P<body>.*?)\};", js_text, flags=re.DOTALL)
    if not m:
        raise ValueError("PHL wait-api.js missing tHours block")
    hours: dict[str, tuple[str, str]] = {}
    entry_re = re.compile(
        r"['\"](?P<key>[^'\"]+)['\"]\s*:\s*\{\s*"
        r"['\"]open['\"]\s*:\s*['\"](?P<open>\d{2}:\d{2})['\"]\s*,\s*"
        r"['\"]close['\"]\s*:\s*['\"](?P<close>\d{2}:\d{2})['\"]\s*,?\s*\}",
        flags=re.DOTALL,
    )
    for item in entry_re.finditer(m.group("body")):
        hours[item.group("key")] = (item.group("open"), item.group("close"))
    missing = sorted({meta[3] for meta in PHL_METRIC_MAP.values()} - set(hours))
    if missing:
        raise ValueError(
            "PHL wait-api.js missing tHours entries: " + ", ".join(missing)
        )
    return hours


def _phl_schedule_is_open(hours: dict[str, tuple[str, str]], schedule_key: str) -> bool:
    open_time, close_time = hours[schedule_key]
    if open_time == close_time:
        return False
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M")
    if open_time < close_time:
        return open_time < now < close_time
    return now > open_time or now < close_time


def fetch_phl_airport() -> list[dict]:
    wait_api_js = fetch_text(
        PHL_WAIT_API_JS_URL, headers={"Referer": PHL_CHECKPOINT_PAGE_URL}
    )
    checkpoint_hours = _parse_phl_checkpoint_hours(wait_api_js)
    payload = fetch_json_url(
        PHL_WAIT_TIMES_URL,
        headers={
            "Accept": "application/json",
            "Referer": PHL_CHECKPOINT_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    rows_raw = (
        ((payload.get("content") or {}).get("rows"))
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(rows_raw, list):
        raise ValueError("PHL metrics endpoint returned unexpected payload")

    rows: list[dict] = []
    for item in rows_raw:
        if not isinstance(item, list) or len(item) < 2:
            continue
        try:
            metric_id = int(item[0])
        except (TypeError, ValueError):
            continue
        mapped = PHL_METRIC_MAP.get(metric_id)
        if not mapped:
            continue
        terminal, gate, queue_type, schedule_key = mapped
        if not _phl_schedule_is_open(checkpoint_hours, schedule_key):
            continue
        try:
            wait_minutes = max(0, math.ceil(float(item[1])))
        except (TypeError, ValueError):
            wait_minutes = None
        bounds = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}
        wait_lo = None
        wait_hi = None
        try:
            if bounds.get("lower_bound") is not None:
                wait_lo = max(0, int(bounds.get("lower_bound")))
        except (TypeError, ValueError):
            pass
        try:
            if bounds.get("upper_bound") is not None:
                wait_hi = max(0, int(bounds.get("upper_bound")))
        except (TypeError, ValueError):
            pass
        if wait_minutes is None and wait_lo is None and wait_hi is None:
            continue
        rows.append(
            {
                "airport": "PHL",
                "terminal": terminal,
                "gate": gate,
                "queue_type": queue_type,
                "wait_minutes": wait_minutes,
                "wait_min_minutes": wait_lo,
                "wait_max_minutes": wait_hi,
                "source_updated_at": None,
                "point_id": metric_id,
            }
        )
    if not rows:
        raise ValueError("PHL metrics endpoint produced no mapped rows")
    return rows


def _bwi_wait_minutes(value: object) -> int | None:
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _bwi_checkpoint_code(raw_code: str) -> str:
    code = raw_code.strip().upper()
    if code == "BC":
        return "C"
    if code == "DE":
        return "D/E"
    return code


def fetch_bwi_airport() -> list[dict]:
    payload = fetch_json_url(
        BWI_WAIT_TIMES_URL,
        headers={
            **BROWSER_HEADERS,
            "Accept": "application/json,*/*",
            "Referer": BWI_HOME_URL,
        },
    )
    wait_times = payload.get("waittimes") if isinstance(payload, dict) else None
    if not isinstance(wait_times, list):
        raise ValueError("BWI wait-times cache returned unexpected payload")
    rows: list[dict] = []
    for item in wait_times:
        if not isinstance(item, dict):
            continue
        if str(item.get("Queue_State") or "").strip().lower() == "closure":
            continue
        name = clean_html_text(str(item.get("Queue_Name") or ""))
        m = re.match(r"^Checkpoint\s+(\S+)\s+(.+)$", name, flags=re.IGNORECASE)
        if not m:
            continue
        terminal = _bwi_checkpoint_code(m.group(1))
        queue_type = normalize_queue_type(m.group(2))
        wait_minutes = _bwi_wait_minutes(item.get("Projected_Wait_Time"))
        wait_lo = _bwi_wait_minutes(item.get("Projected_Min_Wait_Minutes"))
        wait_hi = _bwi_wait_minutes(item.get("Projected_Max_Wait_Minutes"))
        if wait_minutes is None and wait_lo is None and wait_hi is None:
            continue
        rows.append(
            {
                "airport": "BWI",
                "terminal": terminal,
                "gate": "",
                "queue_type": queue_type,
                "wait_minutes": wait_minutes,
                "wait_min_minutes": wait_lo,
                "wait_max_minutes": wait_hi,
                "source_updated_at": item.get("Updated_Time") or None,
                "point_id": None,
            }
        )
    if not rows:
        raise ValueError("BWI wait-times cache produced no open rows")
    return _dedupe_wait_rows_by_checkpoint(rows)


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
    if airport == "IAH":
        return fetch_iah_airport()
    if airport == "MSP":
        return fetch_msp_airport()
    if airport == "DTW":
        return fetch_dtw_airport()
    if airport == "PHL":
        return fetch_phl_airport()
    if airport == "BWI":
        return fetch_bwi_airport()
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
    """Print the raw Mobi checkpoint JSON (DFW / CLT / MCO / IAH) for taxonomy / field inspection."""
    code = airport.strip().upper()
    endpoints: dict[str, tuple[str, str, str]] = {
        "DFW": (DFW_WAIT_TIMES_URL, DFW_MOBILE_API_KEY, DFW_MOBILE_API_VERSION),
        "CLT": (CLT_WAIT_TIMES_URL, CLT_MOBILE_API_KEY, CLT_MOBILE_API_VERSION),
        "MCO": (MCO_WAIT_TIMES_URL, MCO_MOBILE_API_KEY, MCO_MOBILE_API_VERSION),
        "IAH": (IAH_WAIT_TIMES_URL, IAH_MOBILE_API_KEY, IAH_MOBILE_API_VERSION),
    }
    if code not in endpoints:
        raise SystemExit(
            "--raw supports DFW, CLT, MCO, and IAH (same Mobi API family)."
        )
    url, api_key, api_version = endpoints[code]
    payload = _fetch_mobi_checkpoint_json(url, api_key, api_version)
    print(json.dumps(payload, indent=2))


def _natural_preview_part(value: object) -> list[tuple[int, object]]:
    parts = re.split(r"(\d+)", "" if value is None else str(value).strip().lower())
    return [(1, int(p)) if p.isdigit() else (0, p) for p in parts]


def _preview_row_sort_key(row: dict) -> tuple:
    return (
        _natural_preview_part(row.get("terminal")),
        _natural_preview_part(row.get("gate")),
        _natural_preview_part(row.get("queue_type")),
    )


def preview(airport: str) -> None:
    """Fetch one airport and print rows to stdout (no database writes)."""
    code = airport.strip().upper()
    scraped_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = sorted(fetch_airport(code), key=_preview_row_sort_key)
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
    headers = (
        "airport",
        "terminal",
        "gate",
        "queue",
        "wait",
        "min",
        "max",
        "updated",
        "point_id",
    )

    def cell(row: dict, key: str) -> str:
        val = row.get(key)
        return "" if val is None else str(val)

    body = [[cell(r, k) for k in keys] for r in rows]
    widths = [
        max(len(headers[i]), *(len(body[j][i]) for j in range(len(body))))
        for i in range(len(keys))
    ]

    def fmt_line(cells: tuple[str, ...] | list[str]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True))

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
        help="DFW, CLT, MCO, or IAH only: print raw Mobi checkpoint JSON (includes attributes) for inspection; no DB write.",
    )
    args = parser.parse_args()
    if args.preview:
        preview(args.preview)
    elif args.raw:
        print_mobi_raw(args.raw)
    else:
        run()
