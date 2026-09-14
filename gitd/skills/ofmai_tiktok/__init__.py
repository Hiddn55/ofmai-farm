"""OFMAI TikTok skill — warming sessions, posting, replies."""

from pathlib import Path

from gitd.skills.base import Skill

_SKILL_DIR = Path(__file__).parent


def load() -> Skill:
    from gitd.skills.ofmai_tiktok.actions import OpenApp
    from gitd.skills.ofmai_tiktok.workflows import PostVideo, WarmSession

    skill = Skill(_SKILL_DIR)
    skill.register_action(OpenApp)
    for cls in (WarmSession, PostVideo):
        skill.register_workflow(cls)
    return skill
