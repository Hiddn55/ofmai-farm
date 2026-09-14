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
