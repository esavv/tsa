#!/usr/bin/env python3
"""Preview, backtest, or publish threshold-based TSA wait alerts to X."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from init_db import init_db

CATALOG_PATH = os.path.join(REPO_ROOT, "data", "airports.json")
DEFAULT_DB_PATH = os.path.join(REPO_ROOT, "tsa.db")
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://tsa-times.com").rstrip("/")
THRESHOLDS = (45, 60, 90)
COOLDOWN = timedelta(hours=6)
LINK_COOLDOWN = timedelta(days=7)
X_URL_LENGTH = 23
TEXT_POST_COST = Decimal("0.015")
LINK_POST_COST = Decimal("0.200")


@dataclass(frozen=True, order=True)
class Target:
    airport: str
    terminal: str
    gate: str


@dataclass(frozen=True)
class Candidate:
    target: Target
    threshold: int
    wait_minutes: int
    wait_display: str
    label: str
    is_escalation: bool = False


@dataclass(frozen=True)
class AlertPost:
    scraped_at_utc: str
    airport: str
    candidates: tuple[Candidate, ...]
    text: str
    url: str
    included_link: bool

    @property
    def post_id(self) -> str:
        timestamp = utc_from_iso(self.scraped_at_utc).strftime("%Y%m%dT%H%M%SZ")
        identity = "\n".join(
            [
                self.scraped_at_utc,
                self.airport,
                self.text,
                *(
                    f"{candidate.target.terminal}\0{candidate.target.gate}"
                    f"\0{candidate.threshold}\0{candidate.wait_minutes}"
                    for candidate in self.candidates
                ),
            ]
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        return f"{timestamp}-{self.airport}-{digest}"


def utc_from_iso(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_catalog() -> dict[str, dict]:
    with open(CATALOG_PATH, encoding="utf-8") as catalog_file:
        raw = json.load(catalog_file)
    return {
        str(entry.get("code") or "").upper(): entry
        for entry in raw.get("airports", [])
        if entry.get("code")
    }


def alerts_enabled(entry: dict) -> bool:
    config = entry.get("tweet_alerts")
    return isinstance(config, dict) and config.get("enabled") is True


def terminal_tab_config(entry: dict) -> dict:
    raw = entry.get("terminal_tab")
    tab = raw if isinstance(raw, dict) else {}
    return {
        "ignore_gate": tab.get("ignore_gate") is True,
        "gate_transform": tab.get("gate_transform") or "none",
        "without_gate": tab.get("without_gate") or "Terminal {terminal}",
        "with_gate": tab.get("with_gate") or "Terminal {terminal}: Gates {gate}",
        "terminal_labels": tab.get("terminal_labels") or {},
    }


def effective_gate(entry: dict, gate: str) -> str:
    return "" if terminal_tab_config(entry)["ignore_gate"] else (gate or "")


def terminal_label(entry: dict, terminal: str, gate: str) -> str:
    config = terminal_tab_config(entry)
    terminal_display = config["terminal_labels"].get(terminal, terminal)
    gate_display = effective_gate(entry, gate)
    if config["gate_transform"] == "titlecase_words":
        gate_display = " ".join(word.capitalize() for word in gate_display.split())
    template = config["with_gate"] if gate_display else config["without_gate"]
    return template.replace("{terminal}", terminal_display).replace("{gate}", gate_display)


def wait_metric_and_display(entry: dict, row: sqlite3.Row) -> tuple[int, str] | None:
    ui = entry.get("wait_times_ui")
    chip = ui.get("chip", "absolute") if isinstance(ui, dict) else "absolute"
    point = row["wait_minutes"]
    low = row["wait_min_minutes"]
    high = row["wait_max_minutes"]

    if chip == "min":
        return (int(low), f"{low} min") if low is not None else None
    if chip == "max":
        return (int(high), f"{high} min") if high is not None else None
    if chip == "range":
        if low is None and high is not None:
            return int(high), f"<{high} min"
        if high is None and low is not None:
            return int(low), f">{low} min"
        if low is not None and high is not None:
            metric = int(high)
            display = f"{low} min" if int(low) == metric else f"{low}-{high} min"
            return metric, display
        return None
    return (int(point), f"{point} min") if point is not None else None


def crossed_threshold(wait_minutes: int) -> int | None:
    crossed = [threshold for threshold in THRESHOLDS if wait_minutes >= threshold]
    return max(crossed) if crossed else None


def candidates_for_rows(
    rows: list[sqlite3.Row],
    catalog: dict[str, dict],
) -> list[Candidate]:
    best_by_target: dict[Target, tuple[int, str]] = {}
    for row in rows:
        airport = str(row["airport"]).upper()
        entry = catalog.get(airport)
        terminal = str(row["terminal"] or "").strip()
        if not entry or not terminal:
            continue
        target = Target(
            airport=airport,
            terminal=terminal,
            gate=effective_gate(entry, str(row["gate"] or "")),
        )
        wait = wait_metric_and_display(entry, row)
        if wait is None:
            continue
        previous = best_by_target.get(target)
        if previous is None or wait[0] > previous[0]:
            best_by_target[target] = wait

    candidates = []
    for target, (wait_minutes, wait_display) in best_by_target.items():
        threshold = crossed_threshold(wait_minutes)
        if threshold is None:
            continue
        candidates.append(
            Candidate(
                target=target,
                threshold=threshold,
                wait_minutes=wait_minutes,
                wait_display=wait_display,
                label=terminal_label(
                    catalog[target.airport], target.terminal, target.gate
                ),
            )
        )
    return sorted(candidates, key=lambda item: item.target)


def eligible_candidates(
    candidates: list[Candidate],
    at: datetime,
    state: dict[Target, tuple[datetime, int]],
) -> list[Candidate]:
    eligible = []
    for candidate in candidates:
        previous = state.get(candidate.target)
        if previous is None:
            eligible.append(candidate)
            continue
        previous_at, previous_threshold = previous
        if at - previous_at >= COOLDOWN:
            eligible.append(candidate)
        elif candidate.threshold > previous_threshold:
            eligible.append(replace(candidate, is_escalation=True))
    return eligible


def target_url(target: Target) -> str:
    params = {"terminal": target.terminal}
    if target.gate:
        params["gate"] = target.gate
    return f"{SITE_BASE_URL}/{target.airport.lower()}?{urlencode(params)}"


def weighted_post_length(text: str, url: str) -> int:
    if url not in text:
        return len(text)
    return len(text) - len(url) + X_URL_LENGTH


def make_post(
    scraped_at_utc: str,
    airport: str,
    candidates: list[Candidate],
    *,
    include_link: bool,
) -> AlertPost:
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            -candidate.wait_minutes,
            candidate.target.terminal,
            candidate.target.gate,
        ),
    )
    url = target_url(ordered[0].target)
    lines = [f"{candidate.label}: {candidate.wait_display}" for candidate in ordered]
    if len(lines) == 1:
        candidate = ordered[0]
        if candidate.is_escalation and candidate.threshold >= 90:
            qualifier = "very long"
        elif candidate.is_escalation and candidate.threshold >= 60:
            qualifier = "even longer"
        else:
            qualifier = "elevated"
        text = f"TSA wait times are {qualifier} at {airport} {lines[0]}"
    else:
        text = f"TSA wait times are elevated at {airport}:\n\n" + "\n".join(lines)
    if include_link:
        text += f"\n\nLive updates: {url}"
    if weighted_post_length(text, url) > 280:
        raise ValueError(
            f"{airport} alert is too long for X "
            f"({weighted_post_length(text, url)} weighted characters)"
        )
    return AlertPost(
        scraped_at_utc=scraped_at_utc,
        airport=airport,
        candidates=tuple(ordered),
        text=text,
        url=url,
        included_link=include_link,
    )


def posts_for_candidates(
    scraped_at_utc: str,
    candidates: list[Candidate],
    *,
    link_available: bool,
) -> list[AlertPost]:
    grouped: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.target.airport, []).append(candidate)
    posts = []
    for airport in sorted(grouped):
        include_link = link_available and not posts
        posts.append(
            make_post(
                scraped_at_utc,
                airport,
                grouped[airport],
                include_link=include_link,
            )
        )
    return posts


def wait_rows_at(
    conn: sqlite3.Connection,
    scraped_at_utc: str,
    airport: str | None,
) -> list[sqlite3.Row]:
    sql = """
        SELECT airport, terminal, gate, queue_type,
               wait_minutes, wait_min_minutes, wait_max_minutes
        FROM wait_times
        WHERE scraped_at_utc = ?
    """
    params: list[str] = [scraped_at_utc]
    if airport:
        sql += " AND airport = ?"
        params.append(airport)
    return list(conn.execute(sql, params))


def latest_scrape_at(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT scraped_at_utc FROM wait_times ORDER BY scraped_at_utc DESC LIMIT 1"
    ).fetchone()
    return str(row[0]) if row else None


def actual_alert_state(
    conn: sqlite3.Connection,
    airport: str | None,
) -> dict[Target, tuple[datetime, int]]:
    sql = """
        SELECT airport, terminal, gate, threshold_minutes, alerted_at_utc
        FROM tweet_alerts
        WHERE is_test = 0
    """
    params: list[str] = []
    if airport:
        sql += " AND airport = ?"
        params.append(airport)
    sql += " ORDER BY alerted_at_utc"
    state = {}
    for row in conn.execute(sql, params):
        state[Target(row["airport"], row["terminal"], row["gate"])] = (
            utc_from_iso(row["alerted_at_utc"]),
            int(row["threshold_minutes"]),
        )
    return state


def last_production_link_at(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        """
        SELECT MAX(alerted_at_utc)
        FROM tweet_alerts
        WHERE is_test = 0 AND included_link = 1
        """
    ).fetchone()
    return utc_from_iso(row[0]) if row and row[0] else None


def preview_latest(
    conn: sqlite3.Connection,
    catalog: dict[str, dict],
    airport: str | None,
    live: bool,
) -> list[AlertPost]:
    scraped_at_utc = latest_scrape_at(conn)
    if not scraped_at_utc:
        return []
    rows = wait_rows_at(conn, scraped_at_utc, airport)
    candidates = candidates_for_rows(rows, catalog)
    if live:
        candidates = [
            candidate
            for candidate in candidates
            if alerts_enabled(catalog[candidate.target.airport])
        ]
    at = utc_from_iso(scraped_at_utc)
    eligible = eligible_candidates(candidates, at, actual_alert_state(conn, airport))
    last_link_at = last_production_link_at(conn)
    link_available = (
        last_link_at is None
        or datetime.now(timezone.utc) - last_link_at >= LINK_COOLDOWN
    )
    return posts_for_candidates(
        scraped_at_utc,
        eligible,
        link_available=link_available,
    )


def historical_posts(
    conn: sqlite3.Connection,
    catalog: dict[str, dict],
    airport: str | None,
    start: datetime,
    end: datetime,
) -> list[AlertPost]:
    sql = """
        SELECT DISTINCT scraped_at_utc
        FROM wait_times
        WHERE scraped_at_utc <= ?
    """
    params: list[str] = [utc_iso(end)]
    if airport:
        sql += " AND airport = ?"
        params.append(airport)
    sql += " ORDER BY scraped_at_utc"

    state: dict[Target, tuple[datetime, int]] = {}
    last_link_at: datetime | None = None
    posts: list[AlertPost] = []
    for timestamp_row in conn.execute(sql, params):
        scraped_at_utc = str(timestamp_row[0])
        at = utc_from_iso(scraped_at_utc)
        rows = wait_rows_at(conn, scraped_at_utc, airport)
        candidates = candidates_for_rows(rows, catalog)
        eligible = eligible_candidates(candidates, at, state)
        for candidate in eligible:
            state[candidate.target] = (at, candidate.threshold)
        generated = posts_for_candidates(
            scraped_at_utc,
            eligible,
            link_available=(
                last_link_at is None or at - last_link_at >= LINK_COOLDOWN
            ),
        )
        if any(post.included_link for post in generated):
            last_link_at = at
        if at >= start:
            posts.extend(generated)
    return posts


def backtest(
    conn: sqlite3.Connection,
    catalog: dict[str, dict],
    airport: str | None,
    days: int,
) -> list[AlertPost]:
    latest = latest_scrape_at(conn)
    if not latest:
        return []
    end = utc_from_iso(latest)
    return historical_posts(conn, catalog, airport, end - timedelta(days=days), end)


POST_ID_RE = re.compile(r"^\d{8}T\d{6}Z-([A-Z]{3})-[0-9a-f]{12}$")


def find_post_by_id(
    conn: sqlite3.Connection,
    catalog: dict[str, dict],
    post_id: str,
) -> AlertPost | None:
    match = POST_ID_RE.fullmatch(post_id)
    if not match:
        return None
    airport = match.group(1)
    if airport not in catalog:
        return None

    for post in preview_latest(conn, catalog, airport, live=False):
        if post.post_id == post_id:
            return post

    timestamp_text = post_id.split("-", 1)[0]
    timestamp = datetime.strptime(timestamp_text, "%Y%m%dT%H%M%SZ").replace(
        tzinfo=timezone.utc
    )
    for post in historical_posts(conn, catalog, airport, timestamp, timestamp):
        if post.post_id == post_id:
            return post
    return None


def print_posts(posts: list[AlertPost]) -> None:
    if not posts:
        print("No tweets would be generated.")
        return
    for index, post in enumerate(posts):
        if index:
            print("\n" + "-" * 72)
        print(f"Tweet ID: {post.post_id}")
        print(f"{post.scraped_at_utc} | {post.airport}")
        print(post.text)
        print(
            "[link included]"
            if post.included_link
            else "[text only: link used during the prior 7 days]"
        )
        print(f"[{weighted_post_length(post.text, post.url)} weighted characters]")


def post_cost(post: AlertPost) -> Decimal:
    return LINK_POST_COST if post.included_link else TEXT_POST_COST


def total_cost(posts: list[AlertPost]) -> Decimal:
    return sum((post_cost(post) for post in posts), start=Decimal("0"))


def format_cost(cost: Decimal) -> str:
    return f"${cost:.3f}"


def print_summary(posts: list[AlertPost], days: int) -> None:
    print(f"Projected tweets: {len(posts)} over {days} days")
    link_posts = sum(post.included_link for post in posts)
    print(f"Link posts: {link_posts}")
    print(f"Text-only posts: {len(posts) - link_posts}")
    print(f"Expected API cost: {format_cost(total_cost(posts))}")
    counts = Counter(post.airport for post in posts)
    if counts:
        print("\nBy airport:")
        width = max(len(airport) for airport in counts)
        for airport in sorted(counts):
            airport_posts = [post for post in posts if post.airport == airport]
            print(
                f"  {airport:<{width}}  {counts[airport]:>3} tweets  "
                f"{format_cost(total_cost(airport_posts)):>7}"
            )


def x_client():
    missing = [
        name
        for name in (
            "X_CONSUMER_KEY",
            "X_CONSUMER_SECRET",
            "X_ACCESS_TOKEN",
            "X_ACCESS_TOKEN_SECRET",
        )
        if not os.environ.get(name)
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    try:
        import tweepy
    except ImportError as exc:
        raise RuntimeError(
            "Tweepy is required for --live; install requirements.txt"
        ) from exc
    return tweepy.Client(
        consumer_key=os.environ["X_CONSUMER_KEY"],
        consumer_secret=os.environ["X_CONSUMER_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def record_post(
    conn: sqlite3.Connection,
    post: AlertPost,
    tweet_id: str,
    alerted_at_utc: str,
    is_test: bool,
) -> None:
    for candidate in post.candidates:
        conn.execute(
            """
            INSERT INTO tweet_alerts (
                airport, terminal, gate, threshold_minutes, wait_minutes,
                tweet_text, tweet_url, tweet_id, alerted_at_utc, scraped_at_utc,
                source_post_id, is_test, included_link
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.target.airport,
                candidate.target.terminal,
                candidate.target.gate,
                candidate.threshold,
                candidate.wait_minutes,
                post.text,
                post.url,
                tweet_id,
                alerted_at_utc,
                post.scraped_at_utc,
                post.post_id,
                int(is_test),
                int(post.included_link),
            ),
        )
    conn.commit()


def publish_posts(
    conn: sqlite3.Connection,
    posts: list[AlertPost],
    *,
    is_test: bool = False,
) -> None:
    if not posts:
        print("No eligible tweets to publish.")
        return
    client = x_client()
    for post in posts:
        response = client.create_tweet(text=post.text)
        tweet_id = str(response.data["id"])
        alerted_at_utc = utc_iso(datetime.now(timezone.utc))
        record_post(conn, post, tweet_id, alerted_at_utc, is_test=is_test)
        print(f"Published https://x.com/tsatimez/status/{tweet_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="preview eligible alerts from the latest scrape (default)",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="publish eligible alerts for enrolled airports",
    )
    mode.add_argument(
        "--backtest-days",
        type=int,
        metavar="DAYS",
        help="report tweets that historical data would have generated",
    )
    mode.add_argument(
        "--post-id",
        help="publish one generated dry-run/backtest tweet as an explicit live test",
    )
    parser.add_argument(
        "--airport",
        help="limit evaluation to one three-letter airport code",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="with --backtest-days, show only totals by airport",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    airport = args.airport.strip().upper() if args.airport else None
    catalog = load_catalog()
    if airport and airport not in catalog:
        print(f"Unknown airport code: {airport}", file=sys.stderr)
        return 2
    if args.backtest_days is not None and args.backtest_days <= 0:
        print("--backtest-days must be greater than zero", file=sys.stderr)
        return 2
    if args.summary and args.backtest_days is None:
        print("--summary requires --backtest-days", file=sys.stderr)
        return 2
    if args.post_id and airport:
        print("--airport cannot be combined with --post-id", file=sys.stderr)
        return 2

    db_path = init_db(os.environ.get("TSA_DB_PATH", DEFAULT_DB_PATH))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if args.post_id:
            existing = conn.execute(
                "SELECT tweet_id FROM tweet_alerts WHERE source_post_id = ? LIMIT 1",
                (args.post_id,),
            ).fetchone()
            if existing:
                print(
                    f"Tweet ID {args.post_id} was already published as "
                    f"https://x.com/tsatimez/status/{existing['tweet_id']}",
                    file=sys.stderr,
                )
                return 2
            post = find_post_by_id(conn, catalog, args.post_id)
            if post is None:
                print(f"Tweet ID not found: {args.post_id}", file=sys.stderr)
                return 2
            if not alerts_enabled(catalog[post.airport]):
                print(
                    f"{post.airport} is not enrolled for live tweet alerts",
                    file=sys.stderr,
                )
                return 2
            publish_posts(conn, [post], is_test=True)
        elif args.backtest_days is not None:
            posts = backtest(conn, catalog, airport, args.backtest_days)
            if args.summary:
                print_summary(posts, args.backtest_days)
            else:
                print_posts(posts)
                print(f"\nProjected tweets: {len(posts)} over {args.backtest_days} days")
                print(f"Expected API cost: {format_cost(total_cost(posts))}")
        else:
            posts = preview_latest(conn, catalog, airport, live=args.live)
            if args.live:
                publish_posts(conn, posts)
            else:
                print_posts(posts)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
