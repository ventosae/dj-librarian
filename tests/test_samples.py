"""docs/samples (W-31, R-409): the files a DJ gets after the first run, the sample report and its
screenshots, built by scripts/make_samples.py from the synthetic fixture library.

The samples are current (a fresh build gives the same bytes), carry no absolute or temporary
path, the sample HTML holds no "http", the liner notes keep the dj-identity template (W-30b: four
lines, booth words, numbers from identity.json), the chat of session 1 is dj-start's own reply
templates (Q-15), and the screenshots are full pages 1100 px wide."""

from __future__ import annotations

import importlib.util
import re
import struct
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "docs" / "samples"
SCRIPT = REPO / "scripts" / "make_samples.py"


def load_script():
    spec = importlib.util.spec_from_file_location("make_samples", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ms = load_script()
TEXT = [*ms.SAMPLE_FILES, ms.SAMPLE_REPORT, ms.SAMPLE_CHAT]
PNGS = [*ms.SHOTS.values(), ms.R409]


def text(rel: str) -> str:
    return (SAMPLES / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR", path.name
    return struct.unpack(">II", head[16:24])


@pytest.mark.parametrize("rel", TEXT + PNGS)
def test_the_sample_files_exist(rel):
    assert (SAMPLES / rel).is_file(), rel


@pytest.mark.parametrize("rel", TEXT)
def test_no_absolute_or_temporary_path_in_a_sample(rel):
    body = text(rel)
    assert not re.search(r"\b[A-Za-z]:[\\/]|/Users/|/home/|/tmp/|file:/|AppData|djl-samples-", body), rel
    assert str(REPO) not in body and REPO.as_posix() not in body


def test_the_sample_report_is_self_contained_and_shows_the_sample_dj():
    page = text(ms.SAMPLE_REPORT)
    assert "http" not in page.lower() and page.lower().count("<script") == 1
    assert f">{ms.HANDLE}</h2>" in page and 'data-theme="dark"' in page
    for section in ("who", "structure", "proposals", "next"):
        assert f'<section id="{section}">' in page
    for link in re.findall(r'class="table-link" href="\.\./([^"]+)"', page):
        assert (SAMPLES / link).is_file(), link  # every table link resolves inside docs/samples


def test_the_liner_notes_stay_short_and_take_numbers_from_identity_json():
    notes = text("profile/identity.md")
    assert notes.startswith("# Liner notes\n\n> Words by Claude, from profile/identity.json.\n")
    assert len(notes.split()) <= ms.LINER_MAX_WORDS
    source = text("profile/identity.json")
    assert all(n in source for n in re.findall(r"(?<![\w.])\d+(?:[.,:-]\d+)*", notes))


def test_the_screenshots_are_full_pages_1100_px_wide():
    sizes = {name: png_size(SAMPLES / name) for name in PNGS}
    for name, (width, height) in sizes.items():
        assert width == ms.WIDTH and 1500 < height < ms.HEIGHT, (name, width, height)
    assert (SAMPLES / ms.R409).read_bytes() == (SAMPLES / ms.SHOTS["booth"]).read_bytes()


def test_the_samples_are_current_and_reproducible(tmp_path):
    """A fresh build (text only) gives the bytes in docs/samples: rerun scripts/make_samples.py
    after any change to the report or the analysis, and commit what it writes (R-409)."""
    out = tmp_path / "samples"
    assert ms.main(["--out", str(out), "--no-screenshots"]) == 0
    for rel in TEXT:
        fresh = (out / rel).read_text(encoding="utf-8")
        assert fresh == text(rel), f"{rel} is stale: run `uv run python scripts/make_samples.py`"
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == sorted(TEXT)


def test_every_number_in_the_liner_notes_is_a_value_of_identity_json():
    """R-1404, R-302: each number in identity.md is one of identity.json's values (an input, a
    decade, a number an input's name or the archetype carries), not a substring of the file (W-31
    review: 67 of 0..99 were substrings of it). A count written as a word ("Six") counts too."""
    import json

    identity = json.loads(text("profile/identity.json"))
    allowed = ms.identity_numbers(identity)
    found = ms._numbers(text("profile/identity.md"))
    assert found and found <= allowed, sorted(found - allowed)
    assert "6" in found and "Six decades" in text("profile/identity.md")  # the word is checked as its digit
    assert "9" not in allowed and "17" not in allowed  # a wrong count would be caught
    inputs = ms._numbers(" ".join(str(v) for a in identity["axes"].values() for v in a["inputs"].values()))
    scores = [str(a["score"]) for a in identity["axes"].values() if str(a["score"]) not in inputs]
    assert scores and not set(scores) & allowed  # no score at all (dj-identity/SKILL.md), even a bare one
    with pytest.raises(SystemExit, match=f"not values in profile/identity.json: {scores[0]}"):
        ms.check_identity_numbers(f"You score {scores[0]} on the old records.", identity, "x")
    with pytest.raises(SystemExit, match="not values in profile/identity.json: 9"):
        ms.check_identity_numbers("The soft spot is the files: 9 tracks under 256 kbps.", identity, "x")
    with pytest.raises(SystemExit, match="not values in profile/identity.json: 9"):
        ms.check_identity_numbers("Nine decades in the crates.", identity, "x")


def test_the_liner_notes_keep_the_four_line_template():
    """W-30b, R-1404 (dj-identity/SKILL.md): four lines under the heading: the two strong axes in
    booth words, the booth line in quotes, the weakest axis as the DJ's call, what the library is
    good at on a floor. No score, never an axis name and a number in one sentence."""
    import json

    identity = json.loads(text("profile/identity.json"))
    notes = text("profile/identity.md")
    body = [line for line in notes.split("\n")[3:] if line.strip()]
    assert len(body) == ms.LINER_LINES == 4
    assert body[1] == f"“{identity['archetype']['booth_line']}”"
    assert body[2].endswith("your call.") and body[3].startswith("On a floor: ")
    assert "that means" not in body[3]  # line 4 stands on its own, never points back at the soft spot
    assert all(line.startswith("On a floor: ") and "that means" not in line for line in ms.FLOOR.values())
    names = [axis["name"] for axis in identity["axes"].values()]
    assert not any(name.lower() in notes.lower() for name in names)  # booth words, not the chart
    assert not re.search(r"\b(?:" + "|".join(names) + r") \d", notes)
    assert identity["archetype"]["name"] not in notes and identity["archetype"]["meaning"] not in notes
    ms.check_booth_words(notes, identity, "x")
    with pytest.raises(SystemExit, match=r"an axis name and a number in one sentence \(Depth\)"):
        ms.check_booth_words(notes.replace("Six decades", "Depth 94: six decades"), identity, "x")
    with pytest.raises(SystemExit, match="5 lines under the heading, at most 4"):
        ms.check_booth_words(notes + "\nOne more line.\n", identity, "x")


def test_the_chat_sample_is_dj_starts_own_templates():
    """chat-session-1.md (Q-15) comes from the ```text blocks of dj-start/SKILL.md: the hello and
    the Windows export card word for word, the step-3 line with the init numbers filled in. The
    R-1003 check of each reply is tests/test_skills.py::test_r1003_spot_check_on_the_chat_replies."""
    from reply_checks import session_replies

    skill = (REPO / "plugin" / "skills" / "dj-start" / "SKILL.md").read_text(encoding="utf-8")
    steps = ms.skill_steps(skill)
    replies = [reply for reply, _widgets in session_replies(text(ms.SAMPLE_CHAT))]
    assert replies[0] == ms._blocks(steps[1])[0][1] and "What do they call you in the booth?" in replies[0]
    assert replies[1] == next(block for before, block in ms._blocks(steps[2]) if before == "Windows:")
    assert replies[3].startswith("Step 3 of 6 · done in under a minute. Created ")
    assert "exports/2026-10-20-collection.xml: 24 tracks, 8 playlists." in replies[3]
    with pytest.raises(SystemExit, match="step 2 has no Windows card"):
        ms.chat_session(skill.replace("Windows:\n", "Win:\n").replace("Windows:\r\n", "Win:\r\n"),
                        start={"counts": {"tracks": 1, "playlists": 1}, "created": [], "export": "e"},
                        report={"report": "r", "proposals": []})  # fmt: skip
