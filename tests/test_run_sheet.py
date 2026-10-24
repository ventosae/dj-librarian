"""The W-28 run sheet: docs/<test DJ>-session.md (W-32 item 4).

One page for the test session: Before (what the operator prepares), During (the six dj-start steps
with the expected reply and the time budget, what to watch, what not to help with), After (the live
checks A-01…A-08, the lessons, the three questions). The test DJ's name is read from the personas
table of docs/requirements.md, never written here: this file is grepped for real names (R-1206).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO / "docs" / "requirements.md"
QUESTIONS = ("Does the profile sound like you?", "Which proposal would you build?", "What did you not understand?")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _test_dj() -> str:
    """P-1's bold name in the personas table: the v0.1 test DJ."""
    match = re.search(r"^\| P-1 \| \*\*(.+?)\*\* — ", _text(REQUIREMENTS), re.MULTILINE)
    assert match, "docs/requirements.md has no P-1 persona"
    return match[1]


@pytest.fixture(scope="module")
def sheet_path() -> Path:
    return REPO / "docs" / f"{_test_dj().casefold()}-session.md"


@pytest.fixture(scope="module")
def sheet(sheet_path) -> str:
    assert sheet_path.is_file(), f"{sheet_path.name} is missing"
    return _text(sheet_path)


def _sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return {parts[i].split(" (")[0].strip(): parts[i + 1] for i in range(1, len(parts), 2)}


def test_the_sheet_is_one_page(sheet):
    """One printed A4 page: at 600 words or fewer it prints on one page at 10-11 pt (checked by
    printing it with headless Edge at W-32); counting source lines would not bound long lines."""
    assert sheet.startswith("# ") and "W-28" in sheet.splitlines()[0]
    assert len(sheet.split()) <= 600
    assert len(sheet.splitlines()) <= 60


def test_the_sheet_has_before_during_after(sheet):
    assert list(_sections(sheet)) == ["Before", "During", "After"]


def test_before_names_what_the_operator_prepares(sheet):
    before = _sections(sheet)["Before"]
    for needle in ("Upload plugin", "build_plugin_zip.py", "Folder name agreed", "rekordbox version", "Mac or Windows",
                   "docs/samples/reports/sample-library.html", "Cowork task"):  # fmt: skip
        assert needle in before, needle


def test_during_has_the_six_steps_with_a_budget_each(sheet):
    during = _sections(sheet)["During"]
    rows = re.findall(r"^\| (\d) (\w+) \| (.+?) \| (.+?) \| *\|$", during, re.MULTILINE)
    assert [(n, name) for n, name, _reply, _budget in rows] == [
        ("1", "Hello"), ("2", "Export"), ("3", "Folder"), ("4", "Working"), ("5", "Report"), ("6", "Next"),
    ]  # fmt: skip
    assert all(re.search(r"\d+ min", budget) for _n, _name, _reply, budget in rows)
    assert "Step N of 6" in during and "at most one question" in during


def test_during_says_what_to_watch_and_what_not_to_help_with(sheet):
    during = _sections(sheet)["During"]
    assert "R-106" in during and "at most 3" in during
    assert "under 5 lines" in during and "steps 4–5" in during
    dont = during.split("Do not help with:", 1)[1]
    for needle in ("Exporting", "Fixing", "Explaining the report"):
        assert needle in dont, needle


def test_after_lists_every_acceptance_check_as_a_checkbox(sheet):
    after = _sections(sheet)["After"]
    for n in range(1, 9):
        assert re.search(rf"^- \[ \] A-0{n} ", after, re.MULTILINE), f"A-0{n}"
    for needle in ("R-1003", "Q-16", "Q-24", "docs/lessons.md"):
        assert needle in after, needle


def test_after_asks_the_three_questions_in_order(sheet):
    after = _sections(sheet)["After"]
    asked = re.findall(r"^\d\. (.+)$", after, re.MULTILINE)
    assert tuple(asked) == QUESTIONS


def _check(after: str, n: int) -> str:
    return next(line for line in after.splitlines() if line.startswith(f"- [ ] A-0{n} "))


def test_the_operator_is_out_of_the_room_for_a01_and_a06(sheet):
    """A-01 and A-06 say "without <operator> in the room"; A-08 has the operator watch the whole
    session. The sheet squares them: out of the room, watching by screen share."""
    sections = _sections(sheet)
    assert "in the room" in _check(sections["After"], 1) and "in the room" in _check(sections["After"], 6)
    assert "screen share" in sections["Before"].casefold() and "screen share" in sections["During"]
    assert "coffee line in step 4" in sections["During"]


def test_a04_asks_a_yes_only_for_the_writes_that_need_one(sheet):
    """init, profile, structure, taste, identity, proposals and report each log a line with no yes
    (CLAUDE.md rule 1): the A-04 check asks a yes only for a build or crate XML."""
    a04 = _check(_sections(sheet)["After"], 4)
    assert "build or crate XML follows his yes" in a04 and "analysis log lines need none" in a04
    assert "matches a yes" not in sheet


def test_the_engine_and_spotify_checks_keep_their_conditions(sheet):
    """A-06 records which engine route worked (Q-31); R-801's pass mark is a setup without the operator
    and a working `dj pull`."""
    after = _sections(sheet)["After"]
    assert "Q-31" in _check(after, 6)
    a07 = _check(after, 7)
    assert "Spotify set up without " in a07 and "`dj pull` works" in a07
