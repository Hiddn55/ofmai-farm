#!/usr/bin/env sh
# Run the OFMAI farm unit tests (no device needed).
cd "$(dirname "$0")/.." || exit 1
PY="${PY:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
PYTHONPATH=. "$PY" -m pytest tests/test_farm_*.py -q -p no:cacheprovider "$@"
