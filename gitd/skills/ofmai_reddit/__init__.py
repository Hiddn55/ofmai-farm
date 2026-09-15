"""OFMAI Reddit skill — warming sessions. Publishing goes through the API."""

from pathlib import Path

from gitd.skills.base import Skill

_SKILL_DIR = Path(__file__).parent


def load() -> Skill:
    from gitd.skills.ofmai_reddit.actions import OpenApp
    from gitd.skills.ofmai_reddit.workflows import CommentReply, WarmSession

    skill = Skill(_SKILL_DIR)
    skill.register_action(OpenApp)
    for cls in (WarmSession, CommentReply):
        skill.register_workflow(cls)
    return skill
