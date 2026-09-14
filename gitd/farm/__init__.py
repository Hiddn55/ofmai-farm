"""OFMAI farm — warming, humanised input and account policy on top of ghost.

Pure-Python core (no ghost import) so it can be unit-tested without a device:

- ``human``  : per-session behaviour profile + humanised tap/swipe/type/pause
- ``policy`` : day-by-day warming phases, daily budgets, ratios, session windows
- ``health`` : on-screen health signals (action block, verification, suspension)
- ``ledger`` : SQLite-backed action ledger and account registry (SQLAlchemy)
"""
