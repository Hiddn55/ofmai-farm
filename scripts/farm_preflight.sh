#!/usr/bin/env sh
# Ten lines that say whether the farm may run right now.
#
#   sh scripts/farm_preflight.sh
#
# Exits non-zero when any account is offline, in the wrong timezone (R20), or
# unhealthy without being explicitly disabled. This is the "Preflight" step of
# the account onboarding workflow and the first thing to run after a reboot.
#
# NOT TESTABLE WITHOUT A DEVICE: the device and scheduler lines need real
# phones and a running ghost. The decisions behind them are unit-tested in
# gitd/farm/devices.py and gitd/farm/ledger.py.

set -u

cd "$(dirname "$0")/.." || exit 1

PY="${PY:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
GHOST_URL="${GHOST_URL:-http://127.0.0.1:5055}"
FARM="env PYTHONPATH=. $PY -m gitd.farm.cli"
STATUS=0

echo "── devices ─────────────────────────────────────────────────────────────"
$FARM devices check || STATUS=1

echo "── accounts ────────────────────────────────────────────────────────────"
ACCOUNTS=$($FARM accounts list) || STATUS=1
echo "$ACCOUNTS"

# unhealthy and not deliberately parked
UNHEALTHY=$(echo "$ACCOUNTS" | grep 'health=' | grep -v 'health=ok' | grep -v '\[disabled\]' || true)
if [ -n "$UNHEALTHY" ]; then
  echo "!! a human owes these accounts a look (health-canaries.md §6):" >&2
  echo "$UNHEALTHY" >&2
  STATUS=1
fi

PAUSED=$(echo "$ACCOUNTS" | grep '\[paused' || true)
if [ -n "$PAUSED" ]; then
  echo "!! a platform kill-switch is running:" >&2
  echo "$PAUSED" >&2
  STATUS=1
fi

echo "── today's budget ──────────────────────────────────────────────────────"
echo "$ACCOUNTS" | awk '{ print $1, $2 }' | while read -r platform handle; do
  [ -z "${handle:-}" ] && continue
  $FARM budget "$platform" "$handle" | head -2
done

echo "── scheduler ───────────────────────────────────────────────────────────"
if ! curl -s --max-time 5 "$GHOST_URL/api/scheduler/status"; then
  echo "!! ghost is not answering on $GHOST_URL" >&2
  STATUS=1
fi
echo

[ "$STATUS" = 0 ] && echo "preflight: ok" || echo "preflight: NOT ready (see above)" >&2
exit "$STATUS"
