from datetime import date, datetime, timedelta

from gitd.farm import policy
from gitd.farm.policy import (
    COMMENT,
    FOLLOW,
    LIKE,
    POST,
    PROFILE_VISIT,
    VIEW,
    BudgetTracker,
    DailyBudget,
    Health,
    HealthState,
    Phase,
    apply_signal,
    phase_for_day,
    plan_sessions,
)


def test_phases_instagram_and_tiktok_offsets():
    assert phase_for_day(1) == Phase.CONSUME
    assert phase_for_day(3) == Phase.CONSUME
    assert phase_for_day(4) == Phase.LIGHT
    assert phase_for_day(8) == Phase.NETWORK
    assert phase_for_day(15) == Phase.CRUISE
    # tiktok: +3 days per phase
    assert phase_for_day(6, "tiktok") == Phase.CONSUME
    assert phase_for_day(7, "tiktok") == Phase.LIGHT
    assert phase_for_day(13, "tiktok") == Phase.LIGHT
    assert phase_for_day(14, "tiktok") == Phase.NETWORK
    assert phase_for_day(24, "tiktok") == Phase.CRUISE


def test_phases_x_reddit_follow_instagram():
    """X and Reddit get no extra warm-up days; telegram is reserved for M2."""
    for platform in ("x", "reddit", "telegram"):
        assert policy.PHASE_EXTRA_DAYS[platform] == 0, platform
        assert phase_for_day(3, platform) == Phase.CONSUME
        assert phase_for_day(4, platform) == Phase.LIGHT
        assert phase_for_day(8, platform) == Phase.NETWORK
        assert phase_for_day(15, platform) == Phase.CRUISE
    # only TikTok is slower
    assert phase_for_day(15, "tiktok") == Phase.NETWORK
    # every known platform has a calendar, and nothing else sneaks in
    assert set(policy.PHASE_EXTRA_DAYS) == set(policy.PLATFORMS)
    # the observer profile is not a role an account can carry
    assert "observer" not in policy.ROLES


def test_budget_is_deterministic_and_between_40_and_100_percent_of_caps():
    created = date(2026, 9, 1)
    for dol in (1, 5, 10, 20):
        day = date(2026, 9, dol)
        a = DailyBudget.build("instagram:1", "instagram", created, day)
        b = DailyBudget.build("instagram:1", "instagram", created, day)
        assert a == b
        caps = policy.CAPS[a.phase]
        if not a.rest_day:
            assert 0 <= a.caps[LIKE] <= caps.likes
            if caps.likes:
                assert a.caps[LIKE] >= int(0.4 * caps.likes) - 1
            assert caps.session_minutes[0] <= a.session_minutes <= caps.session_minutes[1]


def test_consume_phase_allows_nothing_but_watching():
    b = DailyBudget.build("k", "instagram", date(2026, 9, 1), date(2026, 9, 2))
    t = BudgetTracker(b)
    assert b.phase == Phase.CONSUME
    assert not t.allow(LIKE)
    assert not t.allow(FOLLOW)
    assert not t.allow(COMMENT)
    assert not t.allow(POST)
    assert t.allow(VIEW)


def test_like_ratio_never_exceeds_15_percent_of_views():
    b = DailyBudget.build("k", "instagram", date(2026, 9, 1), date(2026, 9, 20))
    t = BudgetTracker(b)
    assert b.phase == Phase.CRUISE
    # no views yet → one like allowed at most (1 > 0.15*1 is false? 1 > 0.15 → blocked)
    assert not t.allow(LIKE)
    for _ in range(20):
        t.record(VIEW)
    assert t.allow(LIKE)
    for _ in range(3):
        t.record(LIKE)
    assert not t.allow(LIKE)  # 4 > 0.15 * 20
    for _ in range(20):
        t.record(VIEW)
    assert t.allow(LIKE)


def test_follow_ratio_needs_profile_visits():
    b = DailyBudget.build("k", "instagram", date(2026, 9, 1), date(2026, 9, 12))
    t = BudgetTracker(b)
    assert b.phase == Phase.NETWORK
    assert not t.allow(FOLLOW)
    for _ in range(4):
        t.record(PROFILE_VISIT)
    assert t.allow(FOLLOW)
    t.record(FOLLOW)
    assert not t.allow(FOLLOW)  # 2 > 0.3 * 4


def test_daily_cap_is_hard():
    b = DailyBudget.build("k", "instagram", date(2026, 9, 1), date(2026, 9, 20))
    t = BudgetTracker(b)
    for _ in range(2000):
        t.record(VIEW)
    n = 0
    while t.allow(LIKE):
        t.record(LIKE)
        n += 1
    assert n == b.caps[LIKE]


def test_weekly_post_cap():
    b = DailyBudget.build("k", "instagram", date(2026, 9, 1), date(2026, 9, 12))
    t = BudgetTracker(b, posts_this_week=policy.CAPS[Phase.NETWORK].posts_per_week)
    assert not t.allow(POST)
    t2 = BudgetTracker(b, posts_this_week=0)
    assert t2.allow(POST)
    t2.record(POST)
    assert not t2.allow(POST)  # one a day


def test_one_rest_day_per_week_after_day_3():
    created = date(2026, 9, 1)
    days = [date(2026, 9, d) for d in range(7, 14)]  # one full week, dol 7..13
    rest = [DailyBudget.build("k", "instagram", created, d).rest_day for d in days]
    assert sum(rest) == 1
    # never during the first three days
    assert not any(DailyBudget.build("k", "instagram", created, date(2026, 9, d)).rest_day for d in (1, 2, 3))


def test_sessions_avoid_quiet_hours_and_vary_by_day():
    created = date(2026, 9, 1)
    starts = set()
    for d in range(4, 30):
        b = DailyBudget.build("acct", "instagram", created, date(2026, 9, d))
        slots = plan_sessions(b)
        if b.rest_day:
            assert slots == []
            continue
        assert 1 <= len(slots) <= 4
        for s in slots:
            assert s.start.hour not in policy.QUIET_HOURS
            assert s.minutes >= 1
            starts.add(s.start.time())
        # sessions are separated by at least 45 min
        for a, c in zip(slots, slots[1:], strict=False):
            assert (c.start - a.start).total_seconds() >= (a.minutes + 45) * 60
    assert len(starts) > 15  # no fixed daily time


def test_health_transitions():
    now = datetime(2026, 9, 10, 12, 0)
    s = apply_signal(HealthState(), "action_blocked", now, Phase.NETWORK)
    assert s.status == Health.COOLDOWN
    assert s.phase_override == Phase.LIGHT
    assert not s.can_run(now)
    assert s.can_run(now.replace(day=12, hour=13))
    assert s.effective_phase(Phase.CRUISE) == Phase.LIGHT
    v = apply_signal(s, "verification", now, Phase.NETWORK)
    assert v.status == Health.VERIFICATION and not v.can_run(now.replace(year=2030))
    sb = apply_signal(HealthState(), "shadowban", now, Phase.CRUISE)
    assert sb.phase_override == Phase.CONSUME
    su = apply_signal(HealthState(), "suspended", now, Phase.CRUISE)
    assert su.status == Health.SUSPENDED and not su.can_run(now.replace(year=2030))


def test_story_post_cap():
    """E3.4 — a story is Instagram only, one a day from `network`, never a post.

    Three properties in one test, because the three together are the rule
    (docs/social/warming-policy.md §2): the cap exists only on Instagram, it
    opens at `network`, and spending it leaves the feed's POST budget alone —
    a story is not a publication.
    """
    created = date(2026, 9, 1)

    # consume and light: no story at all
    for day, phase in ((date(2026, 9, 2), Phase.CONSUME), (date(2026, 9, 6), Phase.LIGHT)):
        b = DailyBudget.build("instagram:1", "instagram", created, day)
        assert b.phase == phase
        assert b.caps[policy.STORY_POST] == 0
        assert not BudgetTracker(b).allow(policy.STORY_POST)

    # network and cruise: exactly one a day, and it never eats the feed post
    seen = 0
    for day in (date(2026, 9, 12), date(2026, 9, 20)):
        b = DailyBudget.build("instagram:1", "instagram", created, day)
        if b.rest_day:
            continue
        seen += 1
        assert b.phase in (Phase.NETWORK, Phase.CRUISE)
        assert b.caps[policy.STORY_POST] == 1
        t = BudgetTracker(b)
        assert t.allow(policy.STORY_POST)
        t.record(policy.STORY_POST)
        assert not t.allow(policy.STORY_POST)  # one a day, hard
        assert t.allow(POST)  # the feed post of the day is untouched
        assert t.count(POST) == 0
    assert seen  # at least one of the two days was not a rest day

    # the rest day takes it away like everything else
    rest = next(
        (
            b
            for d in range(4, 20)
            if (b := DailyBudget.build("instagram:1", "instagram", created, created + timedelta(days=d))).rest_day
        ),
        None,
    )
    assert rest is not None and rest.caps[policy.STORY_POST] == 0

    # no other platform can ever spend one: TikTok has no story workflow, X and
    # Reddit have no stories
    for platform in ("tiktok", "x", "reddit", "telegram"):
        for d in range(1, 40):
            b = DailyBudget.build(f"{platform}:1", platform, created, created + timedelta(days=d))
            assert b.caps[policy.STORY_POST] == 0, (platform, d)

    # and it stays distinct from watching someone else's story
    assert policy.STORY_POST != policy.STORY_VIEW
    assert policy.STORY_POST in policy.ACTIONS and policy.STORY_VIEW in policy.ACTIONS
