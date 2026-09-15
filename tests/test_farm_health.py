from gitd.farm.health import detect, zero_reach


def test_instagram_action_block_detected():
    xml = '<node text="Action Blocked" /><node text="Try Again Later" />'
    s = detect("instagram", xml)
    assert s and s.kind == "action_blocked"


def test_severity_order_suspended_wins():
    xml = '<node text="Try again later" /><node text="Your account has been suspended" />'
    assert detect("instagram", xml).kind == "suspended"


def test_tiktok_verification_and_logged_out():
    assert detect("tiktok", "<node text='Verify to continue'/>").kind == "verification"
    assert detect("tiktok", '<node text="Log in" content-desc="Log in"/>').kind == "logged_out"


def test_clean_screen_has_no_signal():
    xml = '<node content-desc="Like" /><node content-desc="Comment" /><node text="Following" />'
    assert detect("instagram", xml) is None
    assert detect("tiktok", xml) is None


def test_zero_reach_heuristic():
    assert zero_reach([120, 80, 0, 1, 2])
    assert not zero_reach([120, 80, 0, 1, 40])
    assert not zero_reach([0, 1])


# ── E3.1: X and Reddit ────────────────────────────────────────────────────────


def test_x_signals():
    assert detect("x", '<node text="Rate limit exceeded"/>').kind == "action_blocked"
    assert detect("x", '<node text="You are over the daily limit for sending Posts"/>').kind == "action_blocked"
    assert detect("x", '<node text="Your account is locked"/>').kind == "verification"
    assert detect("x", '<node text="We detected suspicious activity"/>').kind == "verification"
    assert detect("x", '<node text="Create your account"/>').kind == "logged_out"
    assert detect("x", '<node text="Your account is suspended"/>').kind == "suspended"


def test_reddit_signals():
    doing_a_lot = "<node text=\"You've been doing that a lot. Try again in 6 minutes.\"/>"
    assert detect("reddit", doing_a_lot).kind == "action_blocked"
    assert detect("reddit", '<node text="Verify your email to continue"/>').kind == "verification"
    assert detect("reddit", '<node text="Log in to Reddit"/>').kind == "logged_out"
    assert detect("reddit", '<node text="Your account has been suspended"/>').kind == "suspended"


def test_a_subreddit_ban_is_an_action_block_not_a_suspension():
    """Being banned from one sub costs 48 h and a strike on that sub, never a
    30-day quarantine of the phone and its exit IP (health-canaries.md S6)."""
    sig = detect("reddit", '<node text="You are banned from participating in r/fitness"/>')
    assert sig.kind == "action_blocked"


def test_the_word_suspended_in_a_post_never_quarantines_an_account():
    """A suspension quarantines the phone AND its exit IP for 30 days, so the
    pattern has to name the account rather than just contain the word."""
    feed = (
        '<node content-desc="Like. 3 likes"/>'
        '<node text="my gym membership got suspended lol"/>'
        '<node content-desc="Reply"/>'
    )
    assert detect("x", feed) is None
    assert detect("reddit", feed) is None


def test_severity_order_holds_on_the_new_platforms():
    xml = '<node text="Rate limit"/><node text="Your account has been suspended"/>'
    assert detect("x", xml).kind == "suspended"
    assert detect("reddit", xml).kind == "suspended"


def test_a_clean_x_or_reddit_screen_has_no_signal():
    xml = '<node content-desc="Like. 12 likes"/><node content-desc="Reply"/><node content-desc="Upvote"/>'
    assert detect("x", xml) is None
    assert detect("reddit", xml) is None


def test_every_platform_with_a_skill_has_health_patterns():
    from gitd.farm import planner
    from gitd.farm.health import _ORDER, _PATTERNS

    for platform in planner.SKILL_BY_PLATFORM:
        assert platform in _PATTERNS, platform
        assert set(_PATTERNS[platform]) == set(_ORDER), platform
