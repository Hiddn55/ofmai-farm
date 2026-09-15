"""``python -m gitd.farm.cli`` — accounts, budgets, plans, the planner daemon.

    accounts add instagram @handle --device SERIAL [--tz America/New_York] [--niche "fitness,ootd"]
                                   [--role persona|brand] [--market US] [--ofmai-id sa_01]
    accounts list
    accounts enable|disable instagram @handle
    accounts clear-health instagram @handle --reason "..."   # after a human fixed the device
    accounts api-mode instagram @handle on|off     # production: no more warming sessions
    budget instagram @handle [--date 2026-09-20]
    plan instagram @handle [--date 2026-09-20]
    run instagram @handle [--minutes 5]            # one session now, through ghost's runner
    devices list                                   # what `adb devices` sees, plus the observer
    devices check                                  # one line per account: online, timezone, aligned
    daemon [--interval 60]                         # the planner
    bridge [--interval 300] [--once]               # the OFMAI bridge
    platform pause|cut|resume tiktok [--hours 48] [--reason "..."]
    stop | start                                   # machine kill-switch (R31)
    health                                         # platforms, then every account off `ok`
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from gitd.farm import devices as farm_devices
from gitd.farm import ledger, planner, policy


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
            role=args.role,
            market=args.market,
            ofmai_account_id=args.ofmai_id,
        )
        extra = " [disabled: brand]" if acc.role == "brand" else ""
        print(
            f"registered {acc.platform} @{acc.handle} on {acc.device_serial} "
            f"(day 1 = {acc.created_on}, tz {acc.timezone}, role {acc.role}, market {acc.market}){extra}"
        )
        return 0
    if args.sub == "list":
        for a in ledger.list_accounts(db):
            b = ledger.budget_for(a)
            flag = "" if a.enabled else " [disabled]"
            mode = " [api]" if a.api_mode else ""
            role = "" if a.role == "persona" else f" [{a.role}]"
            paused = f" [paused until {a.paused_until}]" if ledger.paused(a, ledger.local_now(a)) else ""
            print(
                f"{a.platform:9} @{a.handle:22} {a.device_serial:18} day {b.day_of_life:3} {b.phase.value:8} "
                f"health={a.health}{flag}{mode}{role}{paused}"
            )
        return 0
    acc = ledger.get_account(db, args.platform, args.handle)
    if not acc:
        print(f"unknown account {args.platform} @{args.handle}", file=sys.stderr)
        return 1
    if args.sub in ("enable", "disable"):
        acc.enabled = 1 if args.sub == "enable" else 0
    elif args.sub == "clear-health":
        # R26 — a human gesture, audited: --reason is mandatory, it writes a
        # `cleared` signal and pushes the return to `ok` to OFMAI.
        reason = (getattr(args, "reason", "") or "").strip()
        if not reason:
            print("clear-health needs --reason \"...\" (R26: the audit of the return to ok)", file=sys.stderr)
            return 1
        ledger.clear_health(db, acc, reason)
        print(f"ok: {args.platform} @{acc.handle} clear-health — {reason}")
        return 0
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
    # Sessions and the answering passes that follow them, in clock order, so the
    # line that says "what does this phone do today" is complete.
    lines: list[tuple[str, str]] = []
    for s in slots:
        lines.append((s.start.strftime("%H:%M"), f"{s.minutes:3} min"))
        for reply in planner.REPLY_PASSES:
            if acc.platform not in reply.platforms or not b.caps.get(reply.action):
                continue
            start = planner.reply_start(s, reply)
            if start.date() != s.start.date() or start.hour in policy.QUIET_HOURS:
                continue
            lines.append((start.strftime("%H:%M"), f"    {reply.workflow}"))
    for when, what in sorted(lines):
        print(f"{when}  {what}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    db = _db()
    acc = ledger.get_account(db, args.platform, args.handle)
    if not acc:
        print("unknown account", file=sys.stderr)
        return 1
    skill = planner.SKILL_BY_PLATFORM.get(acc.platform)
    if not skill:
        print(f"no warming skill for {acc.platform}", file=sys.stderr)
        return 1
    runner = Path(__file__).resolve().parents[1] / "skills" / "_run_skill.py"
    params = {"handle": acc.handle, "minutes": args.minutes or 0, "niche": acc.niche or ""}
    cmd = [
        sys.executable,
        "-u",
        str(runner),
        "--skill",
        skill,
        "--workflow",
        "warm_session",
        "--device",
        acc.device_serial,
        "--params",
        json.dumps(params),
    ]
    return subprocess.call(cmd)


def cmd_devices(args: argparse.Namespace) -> int:
    """What ADB sees, and whether each account's phone still agrees with the ledger."""
    from gitd.config import settings

    farm_devices.clear_cache()
    if args.sub == "list":
        online = sorted(farm_devices.online_serials())
        observer = settings.farm_observer_device
        if not online:
            print("no device answers `adb devices` (adb missing, server down, or nothing connected)")
        for serial in online:
            tag = "  [observer]" if serial and serial == observer else ""
            print(f"{serial:22} device{tag}")
        if observer and observer not in online:
            print(f"{observer:22} OFFLINE  [observer]")
        return 0

    db = _db()
    accounts = ledger.list_accounts(db)
    if not accounts:
        print("no account registered")
        return 0
    bad = 0
    print(f"{'platform':9} {'handle':23} {'serial':22} {'state':7} {'tz_device':20} {'tz_ledger':20} aligned")
    for acc in accounts:
        st = farm_devices.check_alignment(acc, use_cache=False)
        print(st.as_line())
        if not st.online or not st.aligned:
            bad += 1
    return 1 if bad else 0


def cmd_daemon(args: argparse.Namespace) -> int:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    planner.run_forever(args.interval)
    return 0


def cmd_bridge(args: argparse.Namespace) -> int:
    """The OFMAI bridge: one tick, or the daemon.

    A machine where the secret or the address has never been set does not crash:
    it says exactly what to put where, and exits 1.
    """
    import logging

    from gitd.farm import bridge

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        client = bridge.OfmaiClient.from_env()
    except bridge.BridgeNotConfigured as e:
        print(f"bridge not configured: {e}", file=sys.stderr)
        return 1
    if args.once:
        db = _db()
        bridge.init()
        report = bridge.tick(db, client)
        print(json.dumps(report.as_dict(), default=str, indent=2))
        return 1 if report.error else 0
    bridge.run_forever(args.interval)
    return 0


def cmd_platform(args: argparse.Namespace) -> int:
    """S3 / S4 by hand (R30, R31). `resume` is the only way back from a cut."""
    from gitd.farm import collective

    db = _db()
    collective.init()
    if args.sub == "pause":
        state = collective.pause(db, args.platform, hours=args.hours, reason=args.reason)
    elif args.sub == "cut":
        state = collective.cut(db, args.platform, reason=args.reason)
    else:
        state = collective.resume(db, args.platform)
    paused = state.paused_until.isoformat() if state.paused_until else "-"
    print(f"ok: {args.platform} {args.sub} — cut={state.cut} paused_until={paused} reason={state.reason or '-'}")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """Machine kill-switch (R31): the file first, then every running job."""
    from gitd.farm import collective

    path = collective.stop()
    print(f"ok: {path} created — planner and bridge enqueue nothing more")
    killed = _kill_running_jobs()
    print(f"ok: {killed} running job(s) killed")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    from gitd.farm import collective

    collective.start()
    print("ok: STOP removed — planner and bridge resume at their next tick")
    return 0


def _kill_running_jobs() -> int:
    """POST /api/scheduler/queue/{qid}/kill on every running job (health-canaries.md §4).

    Best effort on purpose: the STOP file is already down, so nothing new is
    enqueued whatever happens here. A missing queue or a server that is not
    running must not turn the kill-switch into a traceback.
    """
    from sqlalchemy import select as _select

    from gitd.config import settings
    from gitd.models.schedule import JobQueue

    try:
        planner.init()  # job_queue may not exist yet on a fresh machine
        db = _db()
        rows = list(db.execute(_select(JobQueue).where(JobQueue.status == "running")).scalars())
    except Exception as e:  # noqa: BLE001
        print(f"could not read the job queue: {e}", file=sys.stderr)
        return 0
    if not rows:
        return 0
    base = f"http://127.0.0.1:{settings.port}"
    token = os.environ.get("GITD_ADMIN_TOKEN", "")
    killed = 0
    try:
        import requests
    except ImportError:
        print("requests is missing: kill the jobs by hand", file=sys.stderr)
        return 0
    for row in rows:
        try:
            response = requests.post(
                f"{base}/api/scheduler/queue/{row.id}/kill",
                headers={"X-Ghost-Admin-Token": token} if token else {},
                timeout=10,
            )
            killed += 1 if response.status_code < 400 else 0
        except Exception as e:  # noqa: BLE001 — the server may not be running
            print(f"could not kill job #{row.id}: {e}", file=sys.stderr)
    return killed


def cmd_health(args: argparse.Namespace) -> int:
    """One line per platform, then every account that is not plainly `ok`."""
    from gitd.farm import collective

    db = _db()
    collective.init()
    accounts = ledger.list_accounts(db)
    if collective.is_stopped():
        print(f"STOP present ({collective.stop_file()}) — nothing is being enqueued")
    for platform in sorted({a.platform for a in accounts}):
        state = collective.state(db, platform)
        reds = collective.red_accounts(db, platform)
        n = len([a for a in accounts if a.platform == platform])
        paused = state.paused_until.isoformat(timespec="minutes") if state.paused_until else "-"
        flag = "CUT" if state.cut else ("PAUSED" if state.blocked() else "open")
        print(f"{platform:9} {n:2} accounts  red/48h {len(reds):2}  {flag:7} until {paused}  {state.reason or ''}")
    for acc in accounts:
        if acc.health == "ok" and not acc.paused_until:
            continue
        print(
            f"  {acc.platform:9} @{acc.handle:22} {acc.device_serial:18} health={acc.health} "
            f"until={acc.health_until or '-'} override={acc.phase_override or '-'} paused={acc.paused_until or '-'}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="farm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)

    a = sp.add_parser("accounts")
    asp = a.add_subparsers(dest="sub", required=True)
    add = asp.add_parser("add")
    add.add_argument("platform", choices=policy.PLATFORMS)
    add.add_argument("handle")
    add.add_argument("--device", required=True)
    add.add_argument("--tz", default="America/New_York")
    add.add_argument("--created-on", dest="created_on", default=None, help="ISO date of day 1 (default: today)")
    add.add_argument("--character", default=None, help="OFMAI character id")
    add.add_argument("--niche", default=None, help="comma-separated hashtags")
    add.add_argument("--role", choices=policy.ROLES, default="persona", help="brand accounts are created disabled")
    add.add_argument("--market", default="US")
    add.add_argument("--ofmai-id", dest="ofmai_id", default=None, help="OFMAI SocialAccount id")
    asp.add_parser("list")
    for name in ("enable", "disable", "clear-health"):
        s = asp.add_parser(name)
        s.add_argument("platform", choices=policy.PLATFORMS)
        s.add_argument("handle")
        if name == "clear-health":
            s.add_argument("--reason", default="", help="why the account is healthy again (R26, mandatory)")
    am = asp.add_parser("api-mode")
    am.add_argument("platform", choices=policy.PLATFORMS)
    am.add_argument("handle")
    am.add_argument("state", choices=("on", "off"))

    for name, fn in (("budget", cmd_budget), ("plan", cmd_plan)):
        s = sp.add_parser(name)
        s.add_argument("platform", choices=policy.PLATFORMS)
        s.add_argument("handle")
        s.add_argument("--date", default=None)
        s.set_defaults(fn=fn)

    r = sp.add_parser("run")
    r.add_argument("platform", choices=policy.PLATFORMS)
    r.add_argument("handle")
    r.add_argument("--minutes", type=float, default=0)
    r.set_defaults(fn=cmd_run)

    dv = sp.add_parser("devices")
    dvsp = dv.add_subparsers(dest="sub", required=True)
    dvsp.add_parser("list")
    dvsp.add_parser("check")
    dv.set_defaults(fn=cmd_devices)

    d = sp.add_parser("daemon")
    d.add_argument("--interval", type=int, default=60)
    d.set_defaults(fn=cmd_daemon)

    b = sp.add_parser("bridge")
    b.add_argument("--interval", type=int, default=300)
    b.add_argument("--once", action="store_true", help="one tick, then exit")
    b.set_defaults(fn=cmd_bridge)

    pl = sp.add_parser("platform")
    plsp = pl.add_subparsers(dest="sub", required=True)
    for name in ("pause", "cut", "resume"):
        s = plsp.add_parser(name)
        s.add_argument("platform", choices=policy.PLATFORMS)
        s.add_argument("--reason", default=None)
        if name == "pause":
            s.add_argument("--hours", type=int, default=48)
    pl.set_defaults(fn=cmd_platform)

    sp.add_parser("stop").set_defaults(fn=cmd_stop)
    sp.add_parser("start").set_defaults(fn=cmd_start)
    sp.add_parser("health").set_defaults(fn=cmd_health)

    a.set_defaults(fn=cmd_accounts)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
