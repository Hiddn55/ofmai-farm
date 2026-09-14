"""``python -m gitd.farm.cli`` — accounts, budgets, plans, the planner daemon.

    accounts add instagram @handle --device SERIAL [--tz America/New_York] [--niche "fitness,ootd"]
    accounts list
    accounts enable|disable instagram @handle
    accounts clear-health instagram @handle        # after a human fixed the device
    accounts api-mode instagram @handle on|off     # production: no more warming sessions
    budget instagram @handle [--date 2026-09-20]
    plan instagram @handle [--date 2026-09-20]
    run instagram @handle [--minutes 5]            # one session now, through ghost's runner
    daemon [--interval 60]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from gitd.farm import ledger, policy


def _db():
    from gitd.models.base import SessionLocal

    ledger.init()
    return SessionLocal()


def cmd_accounts(args: argparse.Namespace) -> int:
    db = _db()
    if args.sub == "add":
        acc = ledger.add_account(
            db,
            platform=args.platform,
            handle=args.handle,
            device_serial=args.device,
            created_on=date.fromisoformat(args.created_on) if args.created_on else None,
            timezone=args.tz,
            character_id=args.character,
            niche=args.niche,
        )
        print(f"registered {acc.platform} @{acc.handle} on {acc.device_serial} (day 1 = {acc.created_on}, tz {acc.timezone})")
        return 0
    if args.sub == "list":
        for a in ledger.list_accounts(db):
            b = ledger.budget_for(a)
            flag = "" if a.enabled else " [disabled]"
            mode = " [api]" if a.api_mode else ""
            print(
                f"{a.platform:9} @{a.handle:22} {a.device_serial:18} day {b.day_of_life:3} {b.phase.value:8} "
                f"health={a.health}{flag}{mode}"
            )
        return 0
    acc = ledger.get_account(db, args.platform, args.handle)
    if not acc:
        print(f"unknown account {args.platform} @{args.handle}", file=sys.stderr)
        return 1
    if args.sub in ("enable", "disable"):
        acc.enabled = 1 if args.sub == "enable" else 0
    elif args.sub == "clear-health":
        acc.health = policy.Health.OK.value
        acc.health_until = None
        acc.phase_override = None
    elif args.sub == "api-mode":
        acc.api_mode = 1 if args.state == "on" else 0
    db.commit()
    print(f"ok: {args.platform} @{acc.handle} {args.sub}")
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    db = _db()
    acc = ledger.get_account(db, args.platform, args.handle)
    if not acc:
        print("unknown account", file=sys.stderr)
        return 1
    day = date.fromisoformat(args.date) if args.date else ledger.local_today(acc)
    t = ledger.tracker_for(db, acc, day)
    b = t.budget
    print(f"@{acc.handle} {acc.platform} — {day} — day {b.day_of_life}, phase {b.phase.value}" + (" — REST DAY" if b.rest_day else ""))
    print(f"sessions: {b.sessions} for {b.session_minutes} min total")
    for k in (policy.LIKE, policy.SAVE, policy.FOLLOW, policy.COMMENT, policy.POST, policy.STORY_VIEW, policy.PROFILE_VISIT, policy.SEARCH):
        print(f"  {k:14} {t.count(k):3} / {b.caps[k]:3}")
    print(f"  {'views':14} {t.count(policy.VIEW):3}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    db = _db()
    acc = ledger.get_account(db, args.platform, args.handle)
    if not acc:
        print("unknown account", file=sys.stderr)
        return 1
    day = date.fromisoformat(args.date) if args.date else ledger.local_today(acc)
    b = ledger.budget_for(acc, day)
    slots = policy.plan_sessions(b)
    if not slots:
        print(f"{day}: no session (rest day)" if b.rest_day else f"{day}: nothing planned")
    for s in slots:
        print(f"{s.start.strftime('%H:%M')}  {s.minutes:3} min")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    db = _db()
    acc = ledger.get_account(db, args.platform, args.handle)
    if not acc:
        print("unknown account", file=sys.stderr)
        return 1
    runner = Path(__file__).resolve().parents[1] / "skills" / "_run_skill.py"
    params = {"handle": acc.handle, "minutes": args.minutes or 0, "niche": acc.niche or ""}
    cmd = [
        sys.executable,
        "-u",
        str(runner),
        "--skill",
        {"instagram": "ofmai_instagram", "tiktok": "ofmai_tiktok"}[acc.platform],
        "--workflow",
        "warm_session",
        "--device",
        acc.device_serial,
        "--params",
        json.dumps(params),
    ]
    return subprocess.call(cmd)


def cmd_daemon(args: argparse.Namespace) -> int:
    import logging

    from gitd.farm import planner

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    planner.run_forever(args.interval)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="farm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)

    a = sp.add_parser("accounts")
    asp = a.add_subparsers(dest="sub", required=True)
    add = asp.add_parser("add")
    add.add_argument("platform", choices=("instagram", "tiktok"))
    add.add_argument("handle")
    add.add_argument("--device", required=True)
    add.add_argument("--tz", default="America/New_York")
    add.add_argument("--created-on", dest="created_on", default=None, help="ISO date of day 1 (default: today)")
    add.add_argument("--character", default=None, help="OFMAI character id")
    add.add_argument("--niche", default=None, help="comma-separated hashtags")
    asp.add_parser("list")
    for name in ("enable", "disable", "clear-health"):
        s = asp.add_parser(name)
        s.add_argument("platform", choices=("instagram", "tiktok"))
        s.add_argument("handle")
    am = asp.add_parser("api-mode")
    am.add_argument("platform", choices=("instagram", "tiktok"))
    am.add_argument("handle")
    am.add_argument("state", choices=("on", "off"))

    for name, fn in (("budget", cmd_budget), ("plan", cmd_plan)):
        s = sp.add_parser(name)
        s.add_argument("platform", choices=("instagram", "tiktok"))
        s.add_argument("handle")
        s.add_argument("--date", default=None)
        s.set_defaults(fn=fn)

    r = sp.add_parser("run")
    r.add_argument("platform", choices=("instagram", "tiktok"))
    r.add_argument("handle")
    r.add_argument("--minutes", type=float, default=0)
    r.set_defaults(fn=cmd_run)

    d = sp.add_parser("daemon")
    d.add_argument("--interval", type=int, default=60)
    d.set_defaults(fn=cmd_daemon)

    a.set_defaults(fn=cmd_accounts)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
