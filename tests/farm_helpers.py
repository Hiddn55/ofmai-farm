"""Helpers shared by the farm test files."""

from __future__ import annotations

import shlex

__all__ = ["typed_text"]


def typed_text(calls) -> str:
    """What the input field really holds after a humanised ``type_text()``.

    ``HumanInput.type_text`` (``gitd/farm/human.py``) imitates a person: now and
    then it types a wrong letter, sends ``KEYCODE_DEL``, then types the right
    one — ``typo_rate`` is 1-5 % per character, drawn per session. Concatenating
    every ``input text`` call therefore yields a string full of ghost letters,
    "prowud" instead of "proud", and any assertion on it passes or fails with
    the draw rather than with the code.

    So replay the calls the way the field would: append what is typed, drop the
    last character on a backspace. ``input_text_arg`` shell-quotes its argument
    and encodes spaces as ``%s`` (``gitd/bots/common/adb.py``), so undo both.

    The result is exact for every draw — verified up to ``typo_rate = 1.0``,
    where the naive concatenation degrades to gibberish — which means a test can
    assert on the typed text with ``==`` instead of a vague substring check.

    Not for the recorded-skill path (``RecordedStepAction``), which types a whole
    string in one call with no humanisation: there the raw calls *are* the text.
    """
    buf: list[str] = []
    for c in calls:
        if len(c) >= 4 and c[:3] == ("shell", "input", "text"):
            buf.extend("".join(shlex.split(c[3])).replace("%s", " "))
        elif len(c) >= 4 and c[:3] == ("shell", "input", "keyevent") and c[3] == "KEYCODE_DEL":
            if buf:
                buf.pop()
    return "".join(buf)
