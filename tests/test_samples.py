"""docs/samples (W-31, R-409): the files a DJ gets after the first run, the sample report and its
screenshots, built by scripts/make_samples.py from the synthetic fixture library.

The samples are current (a fresh build gives the same bytes), carry no absolute or temporary
path, the sample HTML holds no "http", the liner notes stay within 120 words and the
screenshots are full pages 1100 px wide."""

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
TEXT = [*ms.SAMPLE_FILES, ms.SAMPLE_REPORT]
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
    """R-1404, R-302: each number in identity.md is one of identity.json's values (a score, an
    input, a decade, a number an input's name or the archetype carries), not a substring of the
    file (W-31 review: 67 of 0..99 were substrings of it)."""
    import json

    identity = json.loads(text("profile/identity.json"))
    allowed = ms.identity_numbers(identity)
    found = set(re.findall(r"(?<![\w.])\d+(?:[.,:-]\d+)*", text("profile/identity.md")))
    assert found and found <= allowed, sorted(found - allowed)
    assert "9" not in allowed and "17" not in allowed  # a wrong count would be caught
    with pytest.raises(SystemExit, match="not values in profile/identity.json: 9"):
        ms.check_identity_numbers("Selectivity sits lowest at 57: 9 tracks under 256 kbps.", identity, "x")
