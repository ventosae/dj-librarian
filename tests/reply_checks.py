"""The mechanical part of the pre-send checklist, for spot checks on DJ-facing text.

One checklist covers both checks R-1003 names: the pre-send block at the end of
plugin/shared/adhd.md. Its Voice line points to plugin/shared/voice.md; the part of the voice a
regex can see is the Avoid column of its word table. Everything else on the checklist (first
person, numbers from the tool, no tangents) is a reviewer's read.

Used by tests/test_skills.py (W-19) on the style guide's own example. R-1003's acceptance, a spot
check on 3 real outputs, is not met here: the outputs come later (the dj-report HTML from W-17, a
generated MD file from W-14, a chat reply from the W-28 test session). Those items call
`text_problems` / `reply_problems` on their real output.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

VOICE = Path(__file__).resolve().parents[1] / "plugin" / "shared" / "voice.md"

PREAMBLE = re.compile(
    r"^(hi|hello|hey|great|sure|certainly|of course|absolutely|thanks|thank you|happy to)\b",
    re.IGNORECASE,
)
STATE = re.compile(r"\bStep \d+ of \d+\b")
TIME = re.compile(
    r"\b(under|about|around) (a|an|one|two|\d+) (minute|minutes|hour|hours)\b|\b\d+ ?min\b",
    re.IGNORECASE,
)
FILE_NAMED = re.compile(r"[\w./-]+\.(md|json|xml|yaml|html)\b")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
HEADING = re.compile(r"^\s*#{1,6} ")


@cache
def avoided_words() -> tuple[str, ...]:
    """The Avoid column of the word table in voice.md, lower case."""
    text = VOICE.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.search(
        r"^## Words we use / words we avoid\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    if not m:
        raise ValueError("voice.md has no '## Words we use / words we avoid' section")
    rows = [line for line in m.group(1).split("\n") if line.startswith("|")][2:]
    return tuple(row.strip("|").split("|")[1].strip().lower() for row in rows)


def text_problems(text: str) -> list[str]:
    """Checks that hold for any DJ-facing text: a chat reply, an MD file, the words of a report."""
    lines = [line for line in text.replace("\r\n", "\n").strip().split("\n") if line.strip()]
    if not lines:
        return ["empty text"]
    problems = []
    first = next((line for line in lines if not HEADING.match(line)), "")
    if PREAMBLE.match(first.strip()):
        problems.append("rule 10: opens with a pleasantry")
    run = 0
    for line in lines:
        run = run + 1 if LIST_ITEM.match(line) else 0
        if run > 5:
            problems.append("rule 9: a list longer than 5")
            break
    for word in avoided_words():
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            problems.append(f"voice: uses the avoided word '{word}'")
    return problems


def reply_problems(reply: str) -> list[str]:
    """`text_problems` plus the checks that only a chat reply has to pass."""
    problems = text_problems(reply)
    if problems == ["empty text"]:
        return problems
    lines = [line for line in reply.strip().split("\n") if line.strip()]
    if not STATE.search(reply):
        problems.append("rule 5: no 'Step N of M'")
    if not FILE_NAMED.search(reply):
        problems.append("rule 7: no file named")
    if not TIME.search(lines[-1]):
        problems.append("rules 3/6: last line has no concrete time estimate")
    return problems
