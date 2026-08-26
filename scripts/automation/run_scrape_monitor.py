#!/usr/bin/env python3
"""Run the deterministic scrape monitor and an optional incident agent."""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__:
    from .scrape_health import check_health, format_utc, parse_utc
else:
    from scrape_health import check_health, format_utc, parse_utc

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_OPENCODE = Path.home() / ".opencode" / "bin" / "opencode"
DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "tsa-monitor"
DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "tsa-monitor"
AGENT_MODEL = "openai/gpt-5.6-sol"
AGENT_TIMEOUT_SECONDS = 7200
DEFAULT_RETRY_HOURS = 24
PROMPT_FILES = {
    "dry-run": PROMPT_DIR / "scrape_incident_dry_run.md",
    "live": PROMPT_DIR / "scrape_incident_live.md",
}
OUTCOME_MARKERS = {
    "MONITOR_RESOLVED": "resolved",
    "MONITOR_UNRESOLVED": "unresolved",
    "MONITOR_NOT_CONFIRMED": "not_confirmed",
    "MONITOR_DRY_RUN_CONFIRMED": "dry_run_confirmed",
    "MONITOR_DRY_RUN_NOT_CONFIRMED": "not_confirmed",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_prompt(report: dict, mode: str) -> str:
    template = PROMPT_FILES[mode].read_text(encoding="utf-8")
    placeholder = "{{MONITOR_EVIDENCE}}"
    if template.count(placeholder) != 1:
        raise RuntimeError(f"prompt must contain exactly one {placeholder} placeholder")
    return template.replace(placeholder, json.dumps(report, indent=2))


def incident_key(report: dict) -> str:
    identity = {
        "system": {
            "latest_scraper_run_at": (
                report.get("latest_scraper_run_at")
                if report.get("system_issues")
                else None
            ),
            "issues": report.get("system_issues", []),
        },
        "airports": [
            {
                "airport": incident.get("airport"),
                "last_success_at": incident.get("last_success_at"),
                "last_data_at": incident.get("last_data_at"),
            }
            for incident in report.get("incidents", [])
        ],
    }
    serialized = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode()).hexdigest()[:16]
    airports = "-".join(incident["airport"] for incident in report.get("incidents", []))
    label = airports or "system"
    return f"{label}-{digest}"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as state_file:
        state = json.load(state_file)
    if not isinstance(state, dict):
        raise RuntimeError("monitor state is not a JSON object")
    return state


def write_state(path: Path, state: dict) -> None:
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2)
        state_file.write("\n")
    temp_path.replace(path)


def retry_is_due(state: dict, key: str, now: datetime) -> bool:
    if state.get("incident_key") != key:
        return True
    next_retry_at = state.get("next_retry_at")
    if not next_retry_at:
        return True
    return now >= parse_utc(next_retry_at)


def detect_outcome(output: str, returncode: int) -> str:
    if returncode != 0:
        return "failed"
    matches = [status for marker, status in OUTCOME_MARKERS.items() if marker in output]
    if len(set(matches)) != 1:
        return "failed"
    return matches[0]


def run_agent(
    report: dict,
    mode: str,
    opencode_bin: Path,
    timeout: int,
    log_dir: Path,
    now: datetime,
) -> tuple[str, Path]:
    command = [
        str(opencode_bin),
        "run",
        "--dir",
        str(REPO_ROOT),
        "--auto",
        "--model",
        AGENT_MODEL,
        "--format",
        "json",
        "--title",
        f"TSA scrape monitor {mode}",
        build_prompt(report, mode),
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"agent-{timestamp}-{mode}.log"
    output = result.stdout + ("\nSTDERR\n" + result.stderr if result.stderr else "")
    log_path.write_text(output, encoding="utf-8")
    if mode == "dry-run":
        print(output)
    return detect_outcome(output, result.returncode), log_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("check", "dry-run", "live"),
        default="check",
        help="check only, diagnose without changes, or resolve and deploy",
    )
    parser.add_argument("--opencode-bin", type=Path, default=DEFAULT_OPENCODE)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--agent-timeout", type=int, default=AGENT_TIMEOUT_SECONDS)
    parser.add_argument("--retry-hours", type=int, default=DEFAULT_RETRY_HOURS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = args.state_dir / "monitor.lock"
    state_path = args.state_dir / "incident.json"
    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another scrape monitor process is active.", file=sys.stderr)
            return 1

        try:
            report = check_health()
        except Exception as exc:
            print(json.dumps({"healthy": False, "monitor_error": str(exc)}, indent=2))
            return 1
        print(json.dumps(report, indent=2))
        if report["healthy"]:
            return 0
        if args.mode == "check":
            return 2
        if not args.opencode_bin.is_file() or not os.access(args.opencode_bin, os.X_OK):
            print(f"OpenCode is unavailable: {args.opencode_bin}", file=sys.stderr)
            return 1

        now = utc_now()
        key = incident_key(report)
        if args.mode == "live":
            try:
                state = load_state(state_path)
            except (OSError, json.JSONDecodeError, RuntimeError) as exc:
                print(f"Cannot read monitor state: {exc}", file=sys.stderr)
                return 1
            if not retry_is_due(state, key, now):
                print(
                    f"Incident {key} already handled; next retry is "
                    f"{state['next_retry_at']}."
                )
                return 0
            write_state(
                state_path,
                {
                    "incident_key": key,
                    "status": "running",
                    "started_at": format_utc(now),
                    "next_retry_at": format_utc(
                        now + timedelta(seconds=args.agent_timeout, hours=1)
                    ),
                },
            )

        try:
            outcome, log_path = run_agent(
                report,
                args.mode,
                args.opencode_bin,
                args.agent_timeout,
                args.log_dir,
                now,
            )
        except subprocess.TimeoutExpired:
            outcome = "failed"
            log_path = args.log_dir / "agent-timeout-no-log"
            print("OpenCode investigation exceeded its timeout.", file=sys.stderr)

        print(f"Agent outcome: {outcome}; log: {log_path}")
        if args.mode == "live":
            write_state(
                state_path,
                {
                    "incident_key": key,
                    "status": outcome,
                    "started_at": format_utc(now),
                    "finished_at": format_utc(utc_now()),
                    "next_retry_at": format_utc(
                        utc_now() + timedelta(hours=args.retry_hours)
                    ),
                    "log_path": str(log_path),
                },
            )
        return 0 if outcome not in ("failed", "unresolved") else 1


if __name__ == "__main__":
    sys.exit(main())
