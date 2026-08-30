#!/usr/bin/env bash
# The daily run. Everything that is safe to automate.
#
#   scripts/daily.sh              dry run, sends nothing
#   scripts/daily.sh --live       sends, up to the daily cap
#
# What it does NOT do: approve candidates, or decide a booking. Both need a
# person. It prints what is waiting for you at the end.
#
# Set OUTBOUND_CONFIG to use a settings file other than config/settings.toml.
#
# Cron, weekdays at 08:40 New York:
#   40 8 * * 1-5 cd /path/to/hiring-outbound-function && scripts/daily.sh --live >> data/daily.log 2>&1

set -uo pipefail
cd "$(dirname "$0")/.."

CONFIG_ARGS=()
if [ -n "${OUTBOUND_CONFIG:-}" ]; then
  CONFIG_ARGS=(--config "$OUTBOUND_CONFIG")
elif [ ! -f config/settings.toml ]; then
  echo "config/settings.toml does not exist. Run: python3 -m outbound init"
  exit 1
fi

run() { python3 -m outbound "${CONFIG_ARGS[@]+"${CONFIG_ARGS[@]}"}" "$@"; }

LIVE=""
if [ "${1:-}" = "--live" ]; then
  LIVE="--live"
fi

ROLES=$(run roles | awk 'NR>1 && $2=="live" {print $1}')
if [ -z "$ROLES" ]; then
  echo "no live roles. Nothing to do."
  exit 0
fi

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ)  live=${LIVE:-no}"
FAILED=0

# FIRST, before anything is queued. A follow up must never go to someone who
# already replied, so the inbox is read before the queue is built.
echo "--- replies and bounces"
run replies sync || echo "replies sync skipped (IMAP not configured)"

for role in $ROLES; do
  echo "--- $role"
  if ! run doctor "$role"; then
    echo "SKIPPING $role: doctor failed"
    FAILED=1
    continue
  fi
  if ! run audit "$role"; then
    echo "SKIPPING $role: the list audit found a blocking problem"
    FAILED=1
    continue
  fi
  run enrich "$role"
  run verify "$role"
  run queue  "$role"
  run send   "$role" $LIVE
done

echo "--- bookings"
run bookings sync
run bookings triage

echo "--- report"
run report

exit $FAILED
