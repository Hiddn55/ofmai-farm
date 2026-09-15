#!/usr/bin/env sh
# Keep every farm phone attached to this Mac.
#
# The phones are virtual and reachable over TCP: their serial is "<host>:<port>",
# and that serial is the only link between the phone provider, ghost's `phones`
# table, the farm ledger and OFMAI. After any network hiccup the connection has
# to be re-established, and — unlike ghost's own `_try_wifi_reconnect` — the
# shell login has to be replayed, which is why this script exists.
#
# Run it every minute from launchd (scripts/launchd/ai.ofmai.farm.adb-connect.plist).
#
#   sh scripts/farm_adb_connect.sh            # reconnect what is missing
#   sh scripts/farm_adb_connect.sh --verbose  # say what it does for every phone
#
# Registry: ~/.ofmai/farm/phones.json (chmod 600, outside the repo), one entry
# per character slug:
#
#   {
#     "sierra": {
#       "serial": "10.0.0.4:20899",
#       "timezone": "America/Los_Angeles",
#       "role": "persona",
#       "adb_code": "f850ef",                       # shell login code, rotates
#       "adb_code_keychain": "ofmai-adb-sierra"     # …or its Keychain entry name
#     }
#   }
#
# The file holds NAMES of Keychain entries, never proxy credentials or account
# passwords (R9). `adb_code` only authorises a shell on a phone this machine can
# already reach; when in doubt use `adb_code_keychain`.
#
# NOT TESTABLE WITHOUT A DEVICE: whether the phone really exposes ADB over TCP,
# whether the port survives a restart, and whether the shell stays authenticated
# after a drop. Everything this script decides is re-implemented and unit-tested
# in gitd/farm/devices.py.

set -u

cd "$(dirname "$0")/.." || exit 1

REGISTRY="${FARM_PHONES_JSON:-$HOME/.ofmai/farm/phones.json}"
GHOST_URL="${GHOST_URL:-http://127.0.0.1:5055}"
VERBOSE=0
[ "${1:-}" = "--verbose" ] && VERBOSE=1

log() { [ "$VERBOSE" = 1 ] && echo "$@"; return 0; }

if [ ! -f "$REGISTRY" ]; then
  echo "farm_adb_connect: no registry at $REGISTRY — nothing to connect" >&2
  exit 0
fi

if ! command -v adb >/dev/null 2>&1; then
  echo "farm_adb_connect: adb is not on PATH" >&2
  exit 1
fi

# slug<TAB>serial<TAB>code<TAB>keychain-entry, one line per phone
ENTRIES=$(python3 - "$REGISTRY" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception as e:                      # a broken registry must be loud
    print(f"farm_adb_connect: cannot read registry: {e}", file=sys.stderr)
    raise SystemExit(1)
for slug, entry in (data or {}).items():
    if not isinstance(entry, dict):
        continue
    serial = (entry.get("serial") or "").strip()
    if not serial:
        continue
    print("\t".join([slug, serial, str(entry.get("adb_code") or ""), str(entry.get("adb_code_keychain") or "")]))
PY
) || exit 1

CONNECTED=$(adb devices | awk '$2 == "device" { print $1 }')
# `while … done` runs in a subshell on the right of a pipe, so a variable set
# inside it would not survive: record failures in a file instead.
FAILED_FILE="$(mktemp)"
trap 'rm -f "$FAILED_FILE"' EXIT

echo "$ENTRIES" | while IFS="$(printf '\t')" read -r slug serial code keychain; do
  [ -z "${serial:-}" ] && continue
  if echo "$CONNECTED" | grep -qx "$serial"; then
    log "$slug $serial already connected"
    continue
  fi
  echo "farm_adb_connect: reconnecting $slug ($serial)"
  adb connect "$serial" >/dev/null 2>&1
  if [ -n "$keychain" ]; then
    code=$(security find-generic-password -s "$keychain" -w 2>/dev/null || echo "")
  fi
  if [ -n "$code" ]; then
    # the shell login is NOT replayed by ghost's own reconnect: do it here
    adb -s "$serial" shell glogin "$code" >/dev/null 2>&1 ||
      echo "farm_adb_connect: shell login refused for $slug ($serial) — the code has probably rotated" >&2
  fi
  if adb devices | awk '$2 == "device" { print $1 }' | grep -qx "$serial"; then
    log "$slug $serial back online"
  else
    echo "farm_adb_connect: $slug ($serial) is still offline" >&2
    echo "$slug" >> "$FAILED_FILE"
  fi
done

# Let ghost refresh its `phones` table (model, wifi ip/port, last_seen). Nothing
# else calls this endpoint unless a human opens the dashboard.
curl -s -o /dev/null --max-time 10 "$GHOST_URL/api/phone/devices" ||
  echo "farm_adb_connect: ghost is not answering on $GHOST_URL" >&2

[ -s "$FAILED_FILE" ] && exit 1
exit 0
