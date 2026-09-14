"""Glue between ghost workflows and the farm: one Action that runs a session.

Both skills use :class:`WarmSessionAction` with their own adapter class, so
the skill files stay tiny and the loop stays in one place.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from gitd.farm import ledger, policy
from gitd.farm.human import HumanInput, SessionProfile
from gitd.farm.warm import WarmConfig, run_session
from gitd.skills.base import Action, ActionResult

log = logging.getLogger(__name__)


def parse_list(raw: Any, sep: str) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if not raw:
        return []
    return [x.strip() for x in str(raw).split(sep) if x.strip()]


class WarmSessionAction(Action):
    """Runs one budgeted, humanised warming session for ``handle``."""

    name = "warm_session_action"
    description = "Watch, like, follow, comment within today's budget"
    max_retries = 1
    platform: str = ""
    adapter_factory: Callable[..., Any] | None = None
    default_detours: tuple[str, ...] = ("search",)

    def __init__(
        self,
        device,
        elements,
        *,
        handle: str = "",
        minutes: float | int | str = 0,
        comments: Any = "",
        niche: Any = "",
        seed: int | str | None = None,
        **kwargs,
    ):
        super().__init__(device, elements)
        self.handle = handle.lstrip("@")
        self.minutes = float(minutes or 0)
        self.comments = parse_list(comments, "\n")
        self.niche = parse_list(niche, ",")
        self.seed = int(seed) if seed not in (None, "") else None

    def precondition(self) -> bool:
        return bool(self.handle) and bool(self.adapter_factory)

    def execute(self) -> ActionResult:
        ledger.init()
        try:
            session = ledger.open_session(self.platform, self.handle)
        except (LookupError, PermissionError) as e:
            return ActionResult(success=False, error=str(e))
        acc = session.account
        budget = session.tracker.budget
        if budget.rest_day:
            return ActionResult(success=True, data={"skipped": "rest day", "day_of_life": budget.day_of_life})
        minutes = self.minutes or max(1.0, budget.session_minutes / max(1, budget.sessions))
        niche = self.niche or parse_list(acc.niche, ",")
        now, sleep = _clock()
        human = HumanInput(self.device, SessionProfile.generate(self.seed), sleep=sleep)
        adapter = self.adapter_factory(self.device, self.elements, human)
        cfg = WarmConfig(
            minutes=minutes,
            phase=budget.phase,
            comments=self.comments,
            niche=niche,
            detour_kinds=self.default_detours,
        )
        log.info(
            "[warm] @%s %s day %s phase %s — %.1f min, caps %s",
            acc.handle,
            self.platform,
            budget.day_of_life,
            budget.phase.value,
            minutes,
            {k: v for k, v in budget.caps.items() if v and k != policy.VIEW},
        )
        stats = run_session(adapter, human, session, cfg, now=now)
        data = stats.as_dict() | {
            "handle": acc.handle,
            "day_of_life": budget.day_of_life,
            "phase": budget.phase.value,
            "profile_seed": human.profile.seed,
        }
        if stats.health:
            return ActionResult(success=False, error=f"health signal: {stats.health}", data=data)
        if stats.error and stats.videos == 0:
            return ActionResult(success=False, error=stats.error, data=data)
        return ActionResult(success=True, data=data)


def _clock():
    """(now, sleep): real time, or a virtual clock when FARM_FAST=1 (bench dry runs).

    In fast mode sleeps do not wait but still advance ``now``, so a "2 minute"
    session runs instantly yet makes the same decisions.
    """
    import time

    if os.environ.get("FARM_FAST") != "1":
        return time.monotonic, time.sleep
    t = [0.0]

    def now() -> float:
        return t[0]

    def sleep(s: float) -> None:
        t[0] += s

    return now, sleep
