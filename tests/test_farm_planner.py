import itertools
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from gitd.farm import ledger, planner, policy
from gitd.models.base import SessionLocal
from gitd.models.schedule import JobQueue


def _fresh_db():
    from gitd.farm.models import FarmAction, FarmCommentCache, FarmSignal

    planner.init()
    db = SessionLocal()
    for a in ledger.list_accounts(db):
        db.delete(a)
    for p in db.execute(select(planner.FarmPlanned)).scalars():
        db.delete(p)
    for j in db.execute(select(JobQueue).where(JobQueue.trigger == "farm")).scalars():
        db.delete(j)
    for table in (FarmAction, FarmSignal, FarmCommentCache):
        db.query(table).delete()
    db.commit()
    return db


def _a_planned_moment(acc):
    """A datetime at which the planner would enqueue a session for ``acc``."""
    day = ledger.local_today(acc)
    slots = policy.plan_sessions(ledger.budget_for(acc, day))
    if not slots:  # rest day for this (account, date): use tomorrow's plan
        slots = policy.plan_sessions(ledger.budget_for(acc, day + timedelta(days=1)))
    assert slots
    return slots[0].start + timedelta(minutes=1)


def test_tick_enqueues_due_slot_once():
    db = _fresh_db()
    acc = ledger.add_account(db, platform="tiktok", handle="plan_me", device_serial="dev-plan", created_on=date.today() - timedelta(days=15))
    day = ledger.local_today(acc)
    slots = policy.plan_sessions(ledger.budget_for(acc, day))
    if not slots:  # rest day for this (account, date): pick tomorrow's plan instead
        day = day + timedelta(days=1)
        slots = policy.plan_sessions(ledger.budget_for(acc, day))
    assert slots
    fake_now = slots[0].start + timedelta(minutes=1)

    ids = planner.tick(db, now_for=lambda _acc: fake_now)
    assert len(ids) == 1
    job = db.get(JobQueue, ids[0])
    assert job.phone_serial == "dev-plan" and job.job_type == "skill_workflow" and job.trigger == "farm"
    cfg = json.loads(job.config_json)
    assert cfg["skill"] == "ofmai_tiktok" and cfg["params"]["handle"] == "plan_me"
    assert job.max_duration_s == (slots[0].minutes + planner.GRACE_MINUTES) * 60

    # same minute again: nothing new
    assert planner.tick(db, now_for=lambda _acc: fake_now) == []
    # too late: skipped
    late = slots[0].start + timedelta(minutes=planner.LATE_TOLERANCE_MINUTES + 5)
    assert planner.tick(db, now_for=lambda _acc: late) == []


def test_tick_skips_unhealthy_and_api_mode_accounts():
    db = _fresh_db()
    acc = ledger.add_account(db, platform="instagram", handle="sick", device_serial="dev-sick", created_on=date.today() - timedelta(days=15))
    acc.health = policy.Health.VERIFICATION.value
    db.commit()
    slots = policy.plan_sessions(ledger.budget_for(acc, date.today() + timedelta(days=1)))
    when = (slots[0].start if slots else datetime.now()) + timedelta(minutes=1)
    assert planner.tick(db, now_for=lambda _a: when) == []
    acc.health = "ok"
    acc.api_mode = 1
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) == []


# ── E1.1 / E1.2: roles, platform kill-switch, platforms without a skill ───────


def test_brand_never_planned():
    """The brand account is registered for the record, never warmed."""
    db = _fresh_db()
    acc = ledger.add_account(
        db,
        platform="instagram",
        handle="ofmai_brand",
        device_serial="dev-brand",
        created_on=date.today() - timedelta(days=20),
        role="brand",
    )
    when = _a_planned_moment(acc)
    assert planner.tick(db, now_for=lambda _a: when) == []  # created disabled
    acc.enabled = 1  # even enabled by hand, the role keeps it out
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) == []
    acc.role = "persona"
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) != []


def test_paused_until_skips_account():
    db = _fresh_db()
    acc = ledger.add_account(
        db,
        platform="x",
        handle="paused_x",
        device_serial="dev-paused",
        created_on=date.today() - timedelta(days=20),
    )
    when = _a_planned_moment(acc)
    acc.paused_until = (when + timedelta(hours=48)).isoformat()
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) == []
    # the pause expires on its own
    acc.paused_until = (when - timedelta(minutes=1)).isoformat()
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) != []


def test_x_and_reddit_get_their_own_skill():
    db = _fresh_db()
    for platform, serial in (("x", "dev-x"), ("reddit", "dev-rd")):
        acc = ledger.add_account(
            db,
            platform=platform,
            handle=f"{platform}_planned",
            device_serial=serial,
            created_on=date.today() - timedelta(days=20),
        )
        when = _a_planned_moment(acc)
        ids = planner.tick(db, now_for=lambda _a, w=when: w)
        assert ids, platform
        cfg = json.loads(db.get(JobQueue, ids[0]).config_json)
        assert cfg["skill"] == planner.SKILL_BY_PLATFORM[platform]
        assert cfg["workflow"] == "warm_session"


def test_a_platform_without_a_skill_is_never_planned():
    """Telegram can be registered (M2) but nothing schedules a session for it."""
    db = _fresh_db()
    acc = ledger.add_account(
        db,
        platform="telegram",
        handle="tg_soon",
        device_serial="dev-tg",
        created_on=date.today() - timedelta(days=20),
    )
    when = _a_planned_moment(acc)
    assert "telegram" not in planner.SKILL_BY_PLATFORM
    assert planner.tick(db, now_for=lambda _a: when) == []


# ── Collective rules and the machine kill-switch (E5.3) ──────────────────────


def test_is_blocked_respected(monkeypatch, tmp_path):
    """A platform paused by S3 / S4 plans nothing, even for a healthy account."""
    from gitd.farm import collective

    monkeypatch.setenv("FARM_DATA_DIR", str(tmp_path / "farm"))
    db = _fresh_db()
    collective.init()
    db.query(collective.FarmPlatform).delete()
    db.commit()
    acc = ledger.add_account(
        db,
        platform="instagram",
        handle="blocked_by_s3",
        device_serial="dev-s3",
        created_on=date.today() - timedelta(days=20),
    )
    when = _a_planned_moment(acc)

    collective.pause(db, "instagram", hours=48, reason="S3")
    assert planner.tick(db, now_for=lambda _a: when) == []

    collective.resume(db, "instagram")
    assert planner.tick(db, now_for=lambda _a: when) != []


def test_stop_file_respected(monkeypatch, tmp_path):
    """data/farm/STOP stops every enqueue, before anything else is looked at (R31)."""
    from gitd.farm import collective

    monkeypatch.setenv("FARM_DATA_DIR", str(tmp_path / "farm"))
    db = _fresh_db()
    acc = ledger.add_account(
        db,
        platform="instagram",
        handle="stopped",
        device_serial="dev-stop",
        created_on=date.today() - timedelta(days=20),
    )
    when = _a_planned_moment(acc)

    collective.stop()
    assert planner.tick(db, now_for=lambda _a: when) == []

    collective.start()
    assert planner.tick(db, now_for=lambda _a: when) != []


def test_comments_from_the_cache_reach_the_job(monkeypatch, tmp_path):
    """OFMAI owns the pool; the planner hands the cached texts to the session."""
    from gitd.farm.models import FarmCommentCache

    monkeypatch.setenv("FARM_DATA_DIR", str(tmp_path / "farm"))
    db = _fresh_db()
    db.query(FarmCommentCache).delete()
    db.commit()
    acc = ledger.add_account(
        db,
        platform="instagram",
        handle="chatty",
        device_serial="dev-chat",
        created_on=date.today() - timedelta(days=20),
    )
    db.add(FarmCommentCache(comment_id="cp_1", account_id=acc.id, kind="comment", text_="the light in this one!!"))
    db.add(FarmCommentCache(comment_id="cp_2", account_id=acc.id, kind="comment", text_="obsessed"))
    db.commit()
    when = _a_planned_moment(acc)

    ids = planner.tick(db, now_for=lambda _a: when)

    assert ids
    cfg = json.loads(db.get(JobQueue, ids[0]).config_json)
    assert cfg["params"]["comments"] == "the light in this one!!\nobsessed"


# ── E3.2 / E3.3: the answering passes (comment_reply, dm_reply) ──────────────


def _reply_account(db, platform, prefix, *, days=40, want_dm=True):
    """An account that is not resting today and may answer, with a clean cache.

    The rest day and the budget are seeded from the account key, which carries
    the row id, so the only way to land on the wanted day is to insert another
    row — one device each, since a device carries one account per platform (R8).
    """
    from gitd.farm.models import FarmCommentCache

    created = date.today() - timedelta(days=days)
    for i in range(60):
        acc = ledger.add_account(
            db, platform=platform, handle=f"{prefix}{i}", device_serial=f"dev-{prefix}{i}", created_on=created
        )
        budget = ledger.budget_for(acc)
        if budget.rest_day or not budget.caps.get(policy.COMMENT_REPLY):
            continue
        if want_dm and not budget.caps.get(policy.DM_REPLY):
            continue
        if not policy.plan_sessions(budget):
            continue
        db.query(FarmCommentCache).filter(FarmCommentCache.account_id == acc.id).delete()
        db.commit()
        return acc
    raise AssertionError("could not build an account that answers today")  # pragma: no cover


_POOL_BATCH = itertools.count()


def _pools(db, acc, *, ai=True, thanks=True, question=True):
    """The reply texts OFMAI reserved for this account, as the bridge caches them."""
    from gitd.farm.models import FarmCommentCache

    batch = next(_POOL_BATCH)
    wanted = {"reply_ai": ai, "reply_thanks": thanks, "reply_question": question}
    for kind, on in wanted.items():
        if not on:
            continue
        for n in range(planner.REPLY_POOL_SIZE):
            db.add(
                FarmCommentCache(
                    comment_id=f"{kind}-{acc.id}-{batch}-{n}",
                    account_id=acc.id,
                    kind=kind,
                    text_=f"{kind} text {n}",
                )
            )
    db.commit()


def _first_slot(acc):
    slots = policy.plan_sessions(ledger.budget_for(acc, ledger.local_today(acc)))
    assert slots
    return slots[0]


def _phone_is_free(db):
    """Ghost has run and released every farm job it was handed."""
    for job in db.execute(select(JobQueue).where(JobQueue.trigger == "farm")).scalars():
        job.status = "completed"
    db.commit()


def _plan_the_session(db, acc, slot):
    """The tick that enqueues the session itself, then the phone comes back free."""
    ids = planner.tick(db, now_for=lambda _a: slot.start + timedelta(minutes=1))
    assert ids, "the session itself should have been planned"
    _phone_is_free(db)


def test_a_comment_pass_follows_each_session_with_the_pools_of_the_platform():
    """The texts come from OFMAI through the cache; the farm writes none of them."""
    db = _fresh_db()
    acc = _reply_account(db, "instagram", "ig_pass_")
    _pools(db, acc)
    slot = _first_slot(acc)
    _plan_the_session(db, acc, slot)

    pass_ = planner.REPLY_PASSES[0]
    when = planner.reply_start(slot, pass_) + timedelta(minutes=1)
    ids = planner.tick(db, now_for=lambda _a: when)

    assert len(ids) == 1
    job = db.get(JobQueue, ids[0])
    assert job.phone_serial == acc.device_serial and job.trigger == "farm"
    assert job.priority == planner.REPLY_PRIORITY
    assert job.max_duration_s == planner.REPLY_MAX_MINUTES * 60
    cfg = json.loads(job.config_json)
    assert cfg["skill"] == "ofmai_instagram" and cfg["workflow"] == "comment_reply"
    assert cfg["params"]["handle"] == acc.handle
    assert cfg["params"]["replies_ai"].splitlines() == [f"reply_ai text {n}" for n in range(5)]
    assert cfg["params"]["replies_thanks"].splitlines() == [f"reply_thanks text {n}" for n in range(5)]
    assert cfg["params"]["replies_question"].splitlines() == [f"reply_question text {n}" for n in range(5)]
    # the pass carries nothing else: no caption, no niche, no minutes
    assert set(cfg["params"]) == {"handle", "replies_ai", "replies_thanks", "replies_question"}

    # a second tick in the same minute plans nothing more
    assert planner.tick(db, now_for=lambda _a: when) == []


def test_a_dm_pass_comes_after_the_comment_pass_and_only_where_there_are_dms():
    """Two gestures, never at the same minute: the phone does one thing at a time."""
    db = _fresh_db()
    acc = _reply_account(db, "instagram", "ig_dm_pass_")
    _pools(db, acc)
    slot = _first_slot(acc)
    _plan_the_session(db, acc, slot)
    comment_pass, dm_pass = planner.REPLY_PASSES
    assert dm_pass.offset_minutes > comment_pass.offset_minutes

    first = planner.tick(db, now_for=lambda _a: planner.reply_start(slot, comment_pass) + timedelta(minutes=1))
    assert len(first) == 1
    assert json.loads(db.get(JobQueue, first[0]).config_json)["workflow"] == "comment_reply"

    _phone_is_free(db)
    _pools(db, acc)  # OFMAI keeps the cache topped up between two passes
    ids = planner.tick(db, now_for=lambda _a: planner.reply_start(slot, dm_pass) + timedelta(minutes=1))

    assert len(ids) == 1
    cfg = json.loads(db.get(JobQueue, ids[0]).config_json)
    assert cfg["workflow"] == "dm_reply"
    assert cfg["params"]["replies_thanks"]


def test_x_and_reddit_answer_comments_but_never_a_dm():
    """No direct messages on those two in V1 (publishing.md §9): never planned."""
    comment_pass, dm_pass = planner.REPLY_PASSES
    assert set(dm_pass.platforms) == {"instagram", "tiktok"}

    for platform in ("x", "reddit"):
        db = _fresh_db()
        acc = _reply_account(db, platform, f"{platform}_pass_", want_dm=False)
        _pools(db, acc)
        slot = _first_slot(acc)
        _plan_the_session(db, acc, slot)

        comment_when = planner.reply_start(slot, comment_pass) + timedelta(minutes=1)
        ids = planner.tick(db, now_for=lambda _a: comment_when)
        assert len(ids) == 1, platform
        assert json.loads(db.get(JobQueue, ids[0]).config_json)["workflow"] == "comment_reply"

        # the dm moment comes and goes without a single dm job, ever
        _phone_is_free(db)
        _pools(db, acc)
        dm_when = planner.reply_start(slot, dm_pass) + timedelta(minutes=1)
        due = [p.workflow for p, _ in planner.due_reply_passes(acc, dm_when)]
        assert "dm_reply" not in due, platform
        assert planner.tick(db, now_for=lambda _a: dm_when) == [], platform
        db.close()


def test_a_pass_without_a_single_text_is_never_planned():
    """No pool, no pass: the farm never writes a reply itself (R13)."""
    db = _fresh_db()
    acc = _reply_account(db, "instagram", "ig_nopool_")
    slot = _first_slot(acc)
    _plan_the_session(db, acc, slot)

    when = planner.reply_start(slot, planner.REPLY_PASSES[0]) + timedelta(minutes=1)
    assert planner.tick(db, now_for=lambda _a: when) == []

    # OFMAI sends one pool — an undeclared character has no `ai` texts, which is
    # normal (publishing.md §1.1) — and the pass happens.
    _pools(db, acc, ai=False, question=False)
    ids = planner.tick(db, now_for=lambda _a: when)
    assert len(ids) == 1
    cfg = json.loads(db.get(JobQueue, ids[0]).config_json)
    assert cfg["params"]["replies_ai"] == ""
    assert cfg["params"]["replies_thanks"]


def test_two_passes_in_a_day_never_exceed_the_daily_cap():
    """The cap is the ledger's: 20 comment replies a day, passes included."""
    from gitd.farm.models import FarmAction

    db = _fresh_db()
    acc = _reply_account(db, "instagram", "ig_cap_")
    _pools(db, acc)
    slot = _first_slot(acc)
    _plan_the_session(db, acc, slot)
    when = planner.reply_start(slot, planner.REPLY_PASSES[0]) + timedelta(minutes=1)

    cap = ledger.budget_for(acc).caps[policy.COMMENT_REPLY]
    day = ledger.local_today(acc).isoformat()
    for n in range(cap - 1):
        db.add(FarmAction(account_id=acc.id, day=day, kind=policy.COMMENT_REPLY, target=f"post:fan{n}"))
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) != []  # one left: the pass runs

    # the first pass spent the last one; a later slot gets nothing
    _phone_is_free(db)
    db.add(FarmAction(account_id=acc.id, day=day, kind=policy.COMMENT_REPLY, target="post:fan_last"))
    db.commit()
    later = planner.reply_start(_first_slot(acc), planner.REPLY_PASSES[1]) + timedelta(minutes=1)
    assert ledger.tracker_for(db, acc).remaining(policy.COMMENT_REPLY) == 0
    assert [
        j for j in planner.tick(db, now_for=lambda _a: later)
        if json.loads(db.get(JobQueue, j).config_json)["workflow"] == "comment_reply"
    ] == []


def test_a_pass_is_never_planned_on_a_phone_that_is_still_busy():
    """A session on the device, or a job of its own: the pass waits its turn."""
    db = _fresh_db()
    acc = _reply_account(db, "instagram", "ig_busy_")
    _pools(db, acc)
    slot = _first_slot(acc)
    ids = planner.tick(db, now_for=lambda _a: slot.start + timedelta(minutes=1))
    assert ids  # the session, still pending

    when = planner.reply_start(slot, planner.REPLY_PASSES[0]) + timedelta(minutes=1)
    assert planner.phone_busy(db, acc) is True
    assert planner.tick(db, now_for=lambda _a: when) == []

    # nothing was written down, so the next tick tries again while the slot is fresh
    _phone_is_free(db)
    assert planner.phone_busy(db, acc) is False
    assert len(planner.tick(db, now_for=lambda _a: when)) == 1


def test_a_pass_older_than_the_tolerance_is_skipped_not_caught_up():
    db = _fresh_db()
    acc = _reply_account(db, "instagram", "ig_late_")
    _pools(db, acc)
    slot = _first_slot(acc)
    _plan_the_session(db, acc, slot)

    comment_pass, dm_pass = planner.REPLY_PASSES
    start = planner.reply_start(slot, comment_pass)
    just_late = start + timedelta(minutes=planner.LATE_TOLERANCE_MINUTES + 1)
    assert comment_pass not in [p for p, _ in planner.due_reply_passes(acc, just_late)]

    # past the last pass of the slot too: the day simply moves on
    late = planner.reply_start(slot, dm_pass) + timedelta(minutes=planner.LATE_TOLERANCE_MINUTES + 1)
    assert planner.due_reply_passes(acc, late) == []
    assert planner.tick(db, now_for=lambda _a: late) == []


def test_a_rest_day_answers_nobody():
    db = _fresh_db()
    acc = None
    others = []
    for i in range(60):
        candidate = ledger.add_account(
            db,
            platform="instagram",
            handle=f"ig_rest_{i}",
            device_serial=f"dev-ig-rest-{i}",
            created_on=date.today() - timedelta(days=40),
        )
        if ledger.budget_for(candidate).rest_day:
            acc = candidate
            break
        others.append(candidate)
    assert acc is not None, "no resting account could be built"
    # the non-resting candidates would be scheduled by tick() below and fail the
    # assertion for the wrong reason: drop them now — AFTER the resting one got
    # its row id (SQLite hands a deleted last id to the next insert, which would
    # repeat the same draw forever)
    for other in others:
        db.delete(other)
    db.commit()
    _pools(db, acc)
    assert ledger.budget_for(acc).caps[policy.COMMENT_REPLY] == 0
    day = ledger.local_today(acc)
    moment = datetime.combine(day, datetime.min.time()) + timedelta(hours=12)
    assert planner.due_reply_passes(acc, moment) == []
    assert planner.tick(db, now_for=lambda _a: moment) == []


def test_a_pass_never_lands_in_the_quiet_hours_nor_after_midnight(monkeypatch):
    """Same windows as a session: nothing between 01:00 and 06:59, nothing tomorrow."""
    db = _fresh_db()
    acc = _reply_account(db, "instagram", "ig_quiet_")
    _pools(db, acc)
    day = ledger.local_today(acc)
    comment_pass = planner.REPLY_PASSES[0]

    # a session whose pass would fall at 01:00 — inside QUIET_HOURS
    quiet = policy.SessionSlot(datetime.combine(day, datetime.min.time()) + timedelta(hours=0, minutes=40), 10)
    monkeypatch.setattr(policy, "plan_sessions", lambda _b: [quiet])
    start = planner.reply_start(quiet, comment_pass)
    assert start.hour in policy.QUIET_HOURS
    assert planner.due_reply_passes(acc, start) == []

    # a late-evening session whose pass would fall after midnight
    late = policy.SessionSlot(datetime.combine(day, datetime.min.time()) + timedelta(hours=23, minutes=30), 40)
    monkeypatch.setattr(policy, "plan_sessions", lambda _b: [late])
    start = planner.reply_start(late, comment_pass)
    assert start.date() != day
    assert planner.due_reply_passes(acc, start) == []


def test_a_paused_or_blocked_account_answers_nobody(monkeypatch, tmp_path):
    """The passes go through the very same gates as a session (E5.3, R31)."""
    from gitd.farm import collective

    monkeypatch.setenv("FARM_DATA_DIR", str(tmp_path / "farm"))
    db = _fresh_db()
    collective.init()
    db.query(collective.FarmPlatform).delete()
    db.commit()
    acc = _reply_account(db, "instagram", "ig_gate_")
    _pools(db, acc)
    slot = _first_slot(acc)
    _plan_the_session(db, acc, slot)
    when = planner.reply_start(slot, planner.REPLY_PASSES[0]) + timedelta(minutes=1)

    acc.paused_until = (when + timedelta(hours=48)).isoformat()
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) == []
    acc.paused_until = None
    acc.health = policy.Health.VERIFICATION.value
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) == []
    acc.health = "ok"
    db.commit()

    collective.pause(db, "instagram", hours=48, reason="S3")
    assert planner.tick(db, now_for=lambda _a: when) == []
    collective.resume(db, "instagram")

    collective.stop()
    assert planner.tick(db, now_for=lambda _a: when) == []
    collective.start()

    acc.api_mode = 1
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) == []
    acc.api_mode = 0
    db.commit()

    assert len(planner.tick(db, now_for=lambda _a: when)) == 1


def test_a_text_handed_to_a_job_is_spent_and_never_typed_twice():
    """`used_at` is the local half of OFMAI's 24 h reservation (bridge §3.4)."""
    from gitd.farm.models import FarmCommentCache

    db = _fresh_db()
    acc = _reply_account(db, "instagram", "ig_spend_")
    _pools(db, acc)
    slot = _first_slot(acc)
    _plan_the_session(db, acc, slot)
    when = planner.reply_start(slot, planner.REPLY_PASSES[0]) + timedelta(minutes=1)

    first = planner.tick(db, now_for=lambda _a: when)
    assert len(first) == 1
    used = db.execute(
        select(FarmCommentCache).where(
            FarmCommentCache.account_id == acc.id, FarmCommentCache.used_at.is_not(None)
        )
    ).scalars()
    assert len({r.kind for r in used}) == 3

    # the pools are empty now: the next pass finds nothing rather than repeating itself
    assert planner.reply_pools_for(db, acc) == {"replies_ai": "", "replies_thanks": "", "replies_question": ""}
    _phone_is_free(db)
    later = planner.reply_start(_first_slot(acc), planner.REPLY_PASSES[1]) + timedelta(minutes=1)
    assert planner.tick(db, now_for=lambda _a: later) == []


def test_the_planner_never_enqueues_a_publication():
    """post_video / post_photo / post_story belong to OFMAI's queue, not here."""
    planned = {"warm_session"} | {p.workflow for p in planner.REPLY_PASSES}
    assert planned == {"warm_session", "comment_reply", "dm_reply"}
    source = (Path(planner.__file__)).read_text()
    for workflow in ("post_video", "post_photo", "post_story"):
        assert f'"{workflow}"' not in source, workflow


def test_every_planned_pass_exists_in_the_skill_it_is_planned_for():
    """The table and the four skills say the same thing about every gesture."""
    import importlib

    for reply in planner.REPLY_PASSES:
        for platform, skill_name in planner.SKILL_BY_PLATFORM.items():
            skill = importlib.import_module(f"gitd.skills.{skill_name}").load()
            names = set(skill.list_workflows())
            assert (reply.workflow in names) is (platform in reply.platforms), (
                f"{skill_name}: {reply.workflow} present={reply.workflow in names}, planned={platform in reply.platforms}"
            )


def test_the_plan_command_shows_the_passes_next_to_the_sessions(capsys):
    """`farm plan` is the only place a human reads the day: it must be complete."""
    import argparse

    from gitd.farm import cli

    db = _fresh_db()
    acc = _reply_account(db, "instagram", "ig_cli_")
    day = ledger.local_today(acc)
    args = argparse.Namespace(platform="instagram", handle=acc.handle, date=day.isoformat())
    assert cli.cmd_plan(args) == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    times = [line[:5] for line in lines]
    assert times == sorted(times), "the day is printed in clock order"
    assert sum("comment_reply" in line for line in lines) == len(policy.plan_sessions(ledger.budget_for(acc, day)))
    assert any("dm_reply" in line for line in lines)

    # a platform without DMs never shows one
    db2 = _fresh_db()
    acc2 = _reply_account(db2, "reddit", "rd_cli_", want_dm=False)
    args2 = argparse.Namespace(platform="reddit", handle=acc2.handle, date=ledger.local_today(acc2).isoformat())
    assert cli.cmd_plan(args2) == 0
    out = capsys.readouterr().out
    assert "comment_reply" in out and "dm_reply" not in out
