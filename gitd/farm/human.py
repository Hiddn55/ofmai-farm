"""Humanised input for a ghost ``Device``.

Every session gets its own :class:`SessionProfile` (a slightly different
"person" each time: hand tremor, tap hold, swipe speed, typing speed, typo
rate, attention span). All primitives sample from that profile, so two
sessions never share the same timing signature and a single session stays
internally consistent.

Only the *edges* touch a device; the sampling is pure so it can be tested.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class DeviceLike(Protocol):
    serial: str

    def adb(self, *args: str, timeout: int = ...) -> str: ...

    def tap(self, x: int, y: int, delay: float = ...) -> None: ...

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = ..., delay: float = ...) -> None: ...


# ── Session profile ───────────────────────────────────────────────────────────


@dataclass
class SessionProfile:
    """One person's motor signature for one session. All times in seconds."""

    seed: int
    # hand tremor (px, sigma) on taps and swipe endpoints
    tap_sigma: float = 6.0
    # how long a finger stays down on a tap (log-normal, seconds)
    tap_hold_mu: float = math.log(0.09)
    tap_hold_sigma: float = 0.35
    # swipe duration (log-normal, seconds) and lateral drift (px, sigma)
    swipe_dur_mu: float = math.log(0.38)
    swipe_dur_sigma: float = 0.30
    swipe_drift_sigma: float = 18.0
    # fraction of the screen a feed swipe covers (uniform range)
    swipe_span: tuple[float, float] = (0.45, 0.62)
    # typing: per-character delay (log-normal) and typo probability
    type_mu: float = math.log(0.14)
    type_sigma: float = 0.45
    typo_rate: float = 0.03
    # pauses between actions ("reading", "thinking"), log-normal seconds
    pause_mu: float = math.log(1.1)
    pause_sigma: float = 0.6
    # watch time per video (log-normal seconds) and long-linger probability
    watch_mu: float = math.log(6.5)
    watch_sigma: float = 0.55
    linger_rate: float = 0.08
    linger_mu: float = math.log(22.0)
    linger_sigma: float = 0.4
    # quick-skip probability (video judged in < 1.5 s)
    skip_rate: float = 0.18
    rng: random.Random = field(default_factory=random.Random, repr=False)

    @classmethod
    def generate(cls, seed: int | None = None, **overrides: Any) -> SessionProfile:
        """Sample a new person. Deterministic for a given seed."""
        seed = random.randrange(1 << 30) if seed is None else int(seed)
        rng = random.Random(seed)
        p = cls(
            seed=seed,
            tap_sigma=rng.uniform(4.0, 9.0),
            tap_hold_mu=math.log(rng.uniform(0.07, 0.13)),
            swipe_dur_mu=math.log(rng.uniform(0.28, 0.55)),
            swipe_drift_sigma=rng.uniform(8.0, 28.0),
            swipe_span=(rng.uniform(0.40, 0.50), rng.uniform(0.55, 0.68)),
            type_mu=math.log(rng.uniform(0.09, 0.22)),
            typo_rate=rng.uniform(0.01, 0.05),
            pause_mu=math.log(rng.uniform(0.7, 1.8)),
            watch_mu=math.log(rng.uniform(4.0, 9.0)),
            linger_rate=rng.uniform(0.04, 0.14),
            skip_rate=rng.uniform(0.10, 0.28),
            rng=rng,
        )
        for k, v in overrides.items():
            setattr(p, k, v)
        return p

    # ── samplers (pure) ───────────────────────────────────────────────

    def _lognorm(self, mu: float, sigma: float, lo: float, hi: float) -> float:
        return min(hi, max(lo, self.rng.lognormvariate(mu, sigma)))

    def tap_hold_s(self) -> float:
        return self._lognorm(self.tap_hold_mu, self.tap_hold_sigma, 0.04, 0.35)

    def swipe_dur_s(self) -> float:
        return self._lognorm(self.swipe_dur_mu, self.swipe_dur_sigma, 0.15, 1.2)

    def char_delay_s(self) -> float:
        return self._lognorm(self.type_mu, self.type_sigma, 0.04, 0.8)

    def pause_s(self, scale: float = 1.0) -> float:
        return scale * self._lognorm(self.pause_mu, self.pause_sigma, 0.2, 8.0)

    def watch_s(self) -> float:
        """How long to watch one video: quick skip, normal watch, or linger."""
        r = self.rng.random()
        if r < self.skip_rate:
            return self.rng.uniform(0.6, 1.5)
        if r < self.skip_rate + self.linger_rate:
            return self._lognorm(self.linger_mu, self.linger_sigma, 12.0, 60.0)
        return self._lognorm(self.watch_mu, self.watch_sigma, 1.5, 20.0)

    def jitter(self, x: float, y: float, sigma: float | None = None) -> tuple[int, int]:
        s = self.tap_sigma if sigma is None else sigma
        return int(round(x + self.rng.gauss(0, s))), int(round(y + self.rng.gauss(0, s)))

    def chance(self, p: float) -> bool:
        return self.rng.random() < p


# ── Device wrapper ────────────────────────────────────────────────────────────


@dataclass
class ScreenSize:
    width: int
    height: int


class HumanInput:
    """Humanised primitives around a ghost ``Device``.

    ``sleep`` is injectable so tests run instantly.
    """

    def __init__(
        self,
        device: DeviceLike,
        profile: SessionProfile | None = None,
        *,
        screen: ScreenSize | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.device = device
        self.profile = profile or SessionProfile.generate()
        self._screen = screen
        self.sleep = sleep

    # ── screen ────────────────────────────────────────────────────────

    @property
    def screen(self) -> ScreenSize:
        if self._screen is None:
            out = self.device.adb("shell", "wm", "size")
            # "Physical size: 1080x2400" (may also carry an "Override size" line)
            import re

            m = re.search(r"(\d+)x(\d+)", out)
            self._screen = ScreenSize(int(m.group(1)), int(m.group(2))) if m else ScreenSize(1080, 2400)
        return self._screen

    # ── primitives ────────────────────────────────────────────────────

    def tap(self, x: int, y: int, *, settle: float | None = None) -> tuple[int, int]:
        """Tap with tremor and a real finger-down duration (a tiny swipe)."""
        p = self.profile
        jx, jy = p.jitter(x, y)
        w, h = self.screen.width, self.screen.height
        jx, jy = max(1, min(w - 2, jx)), max(1, min(h - 2, jy))
        hold_ms = int(p.tap_hold_s() * 1000)
        # a finger never lands perfectly still: 0-2 px of travel during the hold
        ex, ey = p.jitter(jx, jy, sigma=0.8)
        self.device.adb("shell", "input", "swipe", str(jx), str(jy), str(ex), str(ey), str(hold_ms))
        self.sleep(p.pause_s(0.5) if settle is None else settle)
        return jx, jy

    def swipe_feed(self, direction: str = "up") -> None:
        """A feed scroll: vertical, with lateral drift, variable span and speed."""
        p = self.profile
        w, h = self.screen.width, self.screen.height
        span = p.rng.uniform(*p.swipe_span) * h
        x1 = int(w * p.rng.uniform(0.35, 0.65))
        if direction == "up":
            y1 = int(h * p.rng.uniform(0.62, 0.80))
            y2 = int(max(h * 0.08, y1 - span))
        else:
            y1 = int(h * p.rng.uniform(0.20, 0.38))
            y2 = int(min(h * 0.92, y1 + span))
        x2 = int(x1 + p.rng.gauss(0, p.swipe_drift_sigma))
        x1, y1 = p.jitter(x1, y1)
        x2, y2 = p.jitter(x2, y2)
        dur_ms = int(p.swipe_dur_s() * 1000)
        self.device.adb("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(dur_ms))
        self.sleep(p.pause_s(0.4))

    def swipe_between(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Generic drag/swipe with jittered endpoints and variable speed."""
        p = self.profile
        a = p.jitter(x1, y1)
        b = p.jitter(x2, y2)
        dur_ms = int(p.swipe_dur_s() * 1000)
        self.device.adb("shell", "input", "swipe", str(a[0]), str(a[1]), str(b[0]), str(b[1]), str(dur_ms))
        self.sleep(p.pause_s(0.4))

    def type_text(self, text: str) -> None:
        """Type like a person: per-character rhythm, occasional typo + backspace.

        ASCII only (Android ``input text``). Non-ASCII characters are dropped:
        comments and captions with emoji must go through the app's own emoji
        keyboard or be kept ASCII, which is what we do.
        """
        from gitd.bots.common.adb import input_text_arg

        p = self.profile
        neighbours = "qwertyuiopasdfghjklzxcvbnm"
        for ch in text:
            if ord(ch) > 127:
                continue
            if ch.isalpha() and p.chance(p.typo_rate):
                wrong = p.rng.choice(neighbours)
                self.device.adb("shell", "input", "text", input_text_arg(wrong))
                self.sleep(p.char_delay_s() * 1.6)
                self.device.adb("shell", "input", "keyevent", "KEYCODE_DEL")
                self.sleep(p.char_delay_s())
            self.device.adb("shell", "input", "text", input_text_arg(ch))
            self.sleep(p.char_delay_s() * (2.2 if ch == " " else 1.0))
        self.sleep(p.pause_s(0.8))

    def pause(self, scale: float = 1.0) -> float:
        s = self.profile.pause_s(scale)
        self.sleep(s)
        return s

    def watch(self) -> float:
        """Watch the current video; returns seconds spent."""
        s = self.profile.watch_s()
        self.sleep(s)
        return s
