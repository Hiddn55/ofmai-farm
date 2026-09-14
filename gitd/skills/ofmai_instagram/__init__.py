"""OFMAI Instagram skill — warming sessions, posting, replies."""

from pathlib import Path

from gitd.skills.base import Skill

_SKILL_DIR = Path(__file__).parent


def load() -> Skill:
    from gitd.skills.ofmai_instagram.actions import GoReels, OpenApp
    from gitd.skills.ofmai_instagram.workflows import PostVideo, WarmSession

    skill = Skill(_SKILL_DIR)
    for cls in (OpenApp, GoReels):
        skill.register_action(cls)
    for cls in (WarmSession, PostVideo):
        skill.register_workflow(cls)
    return skill
