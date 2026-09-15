#!/usr/bin/env sh
# Run the OFMAI farm unit tests (no device needed).
#
# Each run gets its OWN ledger. Every farm test file's `db` fixture deletes
# *all* accounts, so two runs sharing one ledger wipe each other's rows in the
# middle of a test — the symptom is a scatter of "account @… is not registered"
# across files nobody touched. Measured on 2026-09-15: two suites started at the
# same moment on a shared ledger gave 13 and 17 failures; the same two suites
# with a ledger each gave 387 passed and 387 passed. Several agents run on this
# repo at once, so a shared ledger turns the suite into noise — failures that
# are not real, and real ones it can hide.
#
# tests/conftest.py already keeps the suite away from the dev database
# (data/gitd.db), but it keys its path to the worktree: that is one file per
# checkout, not one per run. This is the missing half.
#
# Pin the ledger with FARM_TEST_DB=/path/to.db (or an exported DB_PATH) when you
# want to inspect what a failing run left behind: a pinned ledger is kept, and
# its path is printed. Otherwise the ledger lives in a temp directory removed on
# the way out — including when the suite fails, and on ^C.
cd "$(dirname "$0")/.." || exit 1
PY="${PY:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python

FARM_DB="${FARM_TEST_DB:-${DB_PATH:-}}"
if [ -n "$FARM_DB" ]; then
    printf 'farm tests: ledger pinned at %s (kept after the run)\n' "$FARM_DB"
else
    # strip a trailing slash: $TMPDIR carries one on macOS, and the "//" it
    # would leave in the path is normalised away by the time SQLAlchemy builds
    # its URL — which trips the substring check of conftest.py's isolation guard
    FARM_TMP="${TMPDIR:-/tmp}"
    FARM_RUN_DIR="$(mktemp -d "${FARM_TMP%/}/farm-tests-XXXXXX")" || exit 1
    # EXIT fires on success and on failure alike; INT and TERM cover ^C and a
    # kill, which do not always reach the EXIT trap on their own.
    trap 'rm -rf "$FARM_RUN_DIR"' EXIT
    trap 'rm -rf "$FARM_RUN_DIR"; exit 130' INT
    trap 'rm -rf "$FARM_RUN_DIR"; exit 143' TERM
    FARM_DB="$FARM_RUN_DIR/ledger.db"
fi

DB_PATH="$FARM_DB" PYTHONPATH=. "$PY" -m pytest tests/test_farm_*.py -q -p no:cacheprovider "$@"
status=$?
# exit explicitly, so the trap's rm can never become the script's exit status
exit $status
