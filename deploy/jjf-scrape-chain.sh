#!/usr/bin/env bash
#
# Jordan's Job Finder — daily scrape chain (installed at /usr/local/bin/).
#
# Every scraper runs under a hard wall-clock cap, and the sync ALWAYS runs.
#
# Before 2026-08-17 this was one cron line joining seven commands with `&&`.
# That day the PM scraper wedged inside Playwright on Meta's board and sat
# there for 7+ hours: no vertical after it scraped, the sync never ran, and the
# board silently showed nothing new all day. `&&` means one hung step costs the
# whole day. A cap per step plus an unconditional sync is the fix — a scraper
# that dies should cost its own jobs, never everyone else's.
set -u

APP=/var/www/jordansjobfinder
cd "$APP" || exit 1

set -a
# shellcheck disable=SC1091
. "$APP/.env"
set +a

PY="$APP/.venv/bin/python"
START=$(date +%s)

# Past this, skip whatever is left and go straight to the sync so the board
# still refreshes today. The 05:00 UTC start + 7h lands at 08:00 ET; the chain
# normally finishes in ~5h20m.
CHAIN_BUDGET=$((7 * 3600))

ts() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*"; }

run_scraper() {   # <script> <cap-minutes>
  local script=$1 cap=$2 rc elapsed
  elapsed=$(( $(date +%s) - START ))
  if [ "$elapsed" -ge "$CHAIN_BUDGET" ]; then
    ts "SKIP $script — chain budget exhausted after $((elapsed / 60))m"
    return
  fi

  ts "START $script (cap ${cap}m)"
  timeout -k 60 "${cap}m" "$PY" "$script" >> "$APP/${script%.py}.log" 2>&1
  rc=$?

  if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
    ts "TIMEOUT $script — killed after ${cap}m"
    # timeout kills the python process, not the browser it spawned. Orphaned
    # chromium holds hundreds of MB on a 2 GB box, so reap it before the next
    # scraper starts. Safe because the chain is strictly serial.
    pkill -9 -f "playwright/driver" 2>/dev/null
    pkill -9 -f "ms-playwright.*headless_shell" 2>/dev/null
  elif [ "$rc" -ne 0 ]; then
    ts "FAIL $script — exit $rc"
  else
    ts "OK $script"
  fi
}

ts "chain starting"

run_scraper scraper.py         150
run_scraper scraper_finance.py  90
run_scraper scraper_sales.py    60
run_scraper scraper_it.py       75
run_scraper scraper_hr.py       45
run_scraper scraper_ops.py     180

# Unconditional: even a day where every scraper failed still needs the sync, so
# the feeds that DID get written reach the board and stale matches age out.
ts "START run-daily-sync"
timeout -k 60 60m "$PY" manage.py run-daily-sync >> "$APP/app-sync.log" 2>&1
ts "run-daily-sync exit $? — chain total $(( ($(date +%s) - START) / 60 ))m"
