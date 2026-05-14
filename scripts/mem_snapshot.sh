#!/usr/bin/env bash
# Hourly memory / top-process snapshot, for diagnosing slow leaks (e.g. the
# May 2026 OOM event where the instance wedged after ~32 days of uptime).
# Appends to logs/mem_snapshot.log next to logs/cron.log. Wire up via cron.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_ROOT/logs"
LOG_FILE="$LOG_DIR/mem_snapshot.log"

mkdir -p "$LOG_DIR"

{
    echo "===== $(date -u +'%Y-%m-%dT%H:%M:%SZ') ====="
    free -m
    echo
    echo "-- top 10 RSS --"
    ps --sort=-rss -eo pid,user,rss,vsz,etime,cmd | head -n 11
    echo
    chrome_count="$(pgrep -c -f 'chrom(e|ium)' 2>/dev/null || echo 0)"
    echo "-- chrome/chromium process count: $chrome_count"
    echo
} >> "$LOG_FILE"
