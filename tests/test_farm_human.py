import statistics

from gitd.farm.human import HumanInput, ScreenSize, SessionProfile


class FakeDevice:
    serial = "fake"

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def adb(self, *args, timeout=30):
        self.calls.append(tuple(args))
        return ""

    def tap(self, x, y, delay=0.6):
        self.calls.append(("tap", x, y))

    def swipe(self, x1, y1, x2, y2, ms=500, delay=0.5):
        self.calls.append(("swipe", x1, y1, x2, y2, ms))


def _human(seed=1):
    dev = FakeDevice()
    h = HumanInput(dev, SessionProfile.generate(seed), screen=ScreenSize(1080, 2400), sleep=lambda s: None)
    return dev, h


def test_profile_is_deterministic_per_seed_and_differs_across_seeds():
    a, b, c = SessionProfile.generate(7), SessionProfile.generate(7), SessionProfile.generate(8)
    assert a.tap_sigma == b.tap_sigma and a.type_mu == b.type_mu
    assert (a.tap_sigma, a.swipe_dur_mu) != (c.tap_sigma, c.swipe_dur_mu)


def test_tap_is_a_short_swipe_with_tremor_and_hold():
    dev, h = _human()
    pts = [h.tap(540, 1200) for _ in range(50)]
    xs = [p[0] for p in pts]
    assert len(set(xs)) > 5  # not pixel-perfect
    assert all(abs(x - 540) < 40 for x in xs)
    for call in dev.calls:
        assert call[:3] == ("shell", "input", "swipe")
        hold = int(call[-1])
        assert 40 <= hold <= 350


def test_feed_swipe_varies_in_span_speed_and_drift():
    dev, h = _human()
    for _ in range(40):
        h.swipe_feed()
    durs = [int(c[-1]) for c in dev.calls]
    x_drift = [abs(int(c[5]) - int(c[3])) for c in dev.calls]
    y_span = [int(c[4]) - int(c[6]) for c in dev.calls]
    assert statistics.pstdev(durs) > 30
    assert max(x_drift) > 5
    assert all(150 <= d <= 1200 for d in durs)
    assert all(0.3 * 2400 < s < 0.9 * 2400 for s in y_span)


def test_typing_is_per_character_and_may_correct_typos():
    dev, h = _human(seed=3)
    h.profile.typo_rate = 1.0  # force a typo on every letter
    h.type_text("ok")
    kinds = [c[2:] for c in dev.calls]
    assert ("text", "o") in kinds and ("text", "k") in kinds
    assert ("keyevent", "KEYCODE_DEL") in kinds


def test_non_ascii_is_dropped_not_sent():
    dev, h = _human()
    h.profile.typo_rate = 0
    h.type_text("héllo 🎉")
    typed = "".join(c[3] for c in dev.calls if c[2] == "text")
    assert typed.replace("%s", " ") == "hllo "


def test_watch_time_distribution_has_skips_and_lingers():
    _, h = _human(seed=11)
    ws = [h.profile.watch_s() for _ in range(2000)]
    assert min(ws) >= 0.6 and max(ws) <= 60
    assert sum(1 for w in ws if w < 1.5) > 100  # quick skips exist
    assert sum(1 for w in ws if w > 12) > 30  # lingers exist
    assert 3 < statistics.median(ws) < 12
