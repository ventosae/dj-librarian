"""dj-profile: dj.analysis.common, dj.analysis.profile, its script and `dj library profile`.

R-311 (the measured profile from a fixture library), R-302 (numbers from code, provenance line,
lists of 5), R-341 (no write session, nothing outside the library folder), R-301 / R-312 (the
skill names the patterns it reads first and the habits.md template).
"""

from __future__ import annotations

import builtins
import io
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml
from typer.testing import CliRunner

from dj import cli, safety
from dj.analysis import common, profile
from dj.analysis.common import (
    NotALibraryFolder,
    dup_key,
    library_folder,
    md_table,
    norm_key,
    parse_day,
    pct,
    provenance_line,
    resolve_xml,
    write_json,
)
from dj.libfolder import LibraryFolder, LibraryFolderError, import_export, scaffold
from dj.model import Library, LibraryError, Track
from dj.readers.xml import read_xml

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "plugin" / "skills" / "dj-profile"
SCRIPT = SKILL / "scripts" / "profile.py"
DAY = date(2026, 10, 20)
EXPORT = "exports/2026-10-20-collection.xml"
PROVENANCE = f"> Measured by code: dj.analysis.profile from {EXPORT}, 2026-10-20."
SECTIONS = [
    "Size", "Formats and bitrates", "Eras", "Timeline", "Fields used", "Empty fields",
    "Duplicate candidates", "The 5 stats that matter",
]  # fmt: skip
ENGINE = ("pyrekordbox", "rapidfuzz", "httpx", "typer", "mcp", "mutagen")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
ABSOLUTE = re.compile(r"(?<![\w/])(?:[A-Za-z]:[/\\]|/(?:Users|Volumes|home|tmp|private)/|\\\\|file://)")

runner = CliRunner()


# -- fixtures ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lib() -> Library:
    return read_xml(fx.SAMPLE_XML)


@pytest.fixture(scope="module")
def measured(lib) -> dict:
    return profile.facts(lib, today=DAY)


@pytest.fixture
def folder(tmp_path) -> Path:
    """A scaffolded dj-library with the fixture export imported as exports/2026-10-20-collection.xml."""
    root = tmp_path / "dj-library"
    scaffold(root, device="windows", today=DAY)
    target = import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=DAY)
    assert LibraryFolder(root).relative(target) == EXPORT
    return root


def make_lib(tracks: list[Track], source: str = "xml") -> Library:
    return Library(source=source, tracks={t.id: t for t in tracks})


def big_lib() -> Library:
    """More of everything than a list of 5 can show: 11 decades, 6 formats, 8 duplicate groups."""
    kinds = ("mp3", "m4a", "flac", "wav", "aiff", "unknown")
    tracks = []
    for i in range(1, 111):
        tracks.append(Track(
            id=str(i), artist=f"Artist {i}", title=f"Title {i}", kind=kinds[i % 6],
            bitrate=0 if i % 13 == 0 else (96, 160, 224, 288, 320)[i % 5],
            year=1920 + (i - 1) % 110, date_added=date(2000 + i % 20, 1 + i % 12, 1) if i % 9 else None,
            duration_s=300, file_size=10_000_000,
        ))  # fmt: skip
    for g in range(8):  # 8 duplicate groups of 2
        tracks.append(Track(id=str(200 + g), artist=f"Artist {g + 1}", title=f"Title {g + 1}", kind="mp3", bitrate=320))
    return make_lib(tracks)


def sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    return {p.split("\n", 1)[0].strip(): p.split("\n", 1)[1] if "\n" in p else "" for p in parts}


def table_sizes(body: str) -> list[int]:
    """Data rows of each Markdown table in `body`."""
    sizes, run = [], 0
    for line in body.split("\n") + [""]:
        if line.startswith("|"):
            run += 1
        elif run:
            sizes.append(run - 2)
            run = 0
    return sizes


def assert_lists_capped(text: str) -> None:
    for name, body in sections(text).items():
        assert all(size <= 5 for size in table_sizes(body)), f"{name}: a table over 5 rows"
        assert len(table_sizes(body)) <= 1, f"{name}: more than one table"
        items = [line for line in body.split("\n") if LIST_ITEM.match(line)]
        assert len(items) <= 5, f"{name}: a list over 5 items"


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# -- common: norm_key ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (("Beyoncé", "Café Del Mar"), ("Beyonce", "Cafe del Mar")),  # accents, case
        (("Jørn Ébène", "Søndag på Taget"), ("Jorn Ebene", "Sondag pa Taget")),  # letters NFKD keeps
        (("Halvard & Nim", "Slow Burn Social"), ("Halvard and Nim", "Slow Burn Social")),  # &
        (("Marlo Venn", "Hallway Light (Original Mix)"), ("Marlo Venn", "Hallway Light")),
        (("Marlo Venn", "Hallway Light [Original Version]"), ("Marlo Venn", "Hallway Light")),
        (("Marlo Venn", "Hallway Light (original)"), ("Marlo Venn", "Hallway Light")),
        (("Marlo Venn", "Hallway Light - Original Mix"), ("Marlo Venn", "Hallway Light")),
        (("A ft. B", "Song"), ("A feat. B", "Song")),
        (("  Grid   Saint ", "Pressure-Vessel!"), ("grid saint", "pressure vessel")),  # punctuation, spaces
        (("ＤＪ Ｘ", "Ｓｏｎｇ"), ("DJ X", "Song")),  # NFKD: full-width letters
    ],
)
def test_norm_key_same(a, b):
    assert norm_key(*a) == norm_key(*b) != ""


@pytest.mark.parametrize(
    "version",
    ["(Club Edit)", "(Extended Mix)", "(Dub Atelier Remix)", "(Dub)", "(Radio Edit)", "(Original Remix)"],
)
def test_norm_key_keeps_version_words(version):
    # A remix, an edit, an extended or a dub is not a duplicate of the original.
    assert norm_key("The Velvet Ferrymen", f"Brass Tide {version}") != norm_key("The Velvet Ferrymen", "Brass Tide")


def test_norm_key_shape_and_empty_parts():
    assert norm_key("Marlo Venn", "Hallway Light") == "marlo venn|hallway light"
    assert norm_key("", "Hallway Light") == ""
    assert norm_key("Marlo Venn", "  ") == ""
    assert norm_key("Marlo Venn", "(Original Mix)") == ""  # nothing left of the title


def test_dup_key_adds_a_remixer_the_title_does_not_name():
    plain = dup_key("The Velvet Ferrymen", "Brass Tide")
    assert plain == norm_key("The Velvet Ferrymen", "Brass Tide")
    # The remix is only in the Remixer field: not the original's key.
    assert dup_key("The Velvet Ferrymen", "Brass Tide", "Dub Atelier") == plain + "|dub atelier" != plain
    # The title names the remixer already: the field changes nothing, so copies still match.
    titled = "Brass Tide (Dub Atelier Remix)"
    assert dup_key("The Velvet Ferrymen", titled, "Dub Atelier") == dup_key("The Velvet Ferrymen", titled)
    assert dup_key("The Velvet Ferrymen", titled, "Dúb  Atelier") == dup_key("The Velvet Ferrymen", titled)
    # "Original Mix" in the Remixer field names no remix; an empty key stays empty.
    assert dup_key("The Velvet Ferrymen", "Brass Tide", "Original Mix") == plain
    assert dup_key("", "Brass Tide", "Dub Atelier") == ""


# -- common: the rest ---------------------------------------------------------------------------


def test_provenance_line():
    line = provenance_line("dj.analysis.profile", EXPORT, DAY)
    assert line == PROVENANCE
    assert provenance_line("m", "collection.xml", DAY) == "> Measured by code: m from collection.xml, 2026-10-20."


@pytest.mark.parametrize(
    "bad", ["/Users/dj/x.xml", "D:/Music/x.xml", "d:x.xml", "C:\\x.xml", "exports\\x.xml", "../x.xml",
            "file://localhost/x.xml", "", " exports/x.xml", "a\nb"],
)  # fmt: skip
def test_provenance_line_refuses_an_absolute_or_odd_source(bad):
    with pytest.raises(ValueError):
        provenance_line("dj.analysis.profile", bad, DAY)


def test_md_table_caps_rows_and_counts_the_rest():
    rows = [[f"r{i}", i] for i in range(8)]
    text = md_table(["Name", "N"], rows, where="profile/facts.json")
    assert text.split("\n")[:2] == ["| Name | N |", "|---|---|"]
    assert table_sizes(text) == [5]
    assert text.endswith("\n\nAnd 3 more in profile/facts.json.")
    assert md_table(["A"], [[1], [2]], limit=1).endswith("\n\nAnd 1 more.")
    assert "And" not in md_table(["A"], [[1]] * 5)


def test_md_table_escapes_cells_and_checks_its_input():
    assert md_table(["A"], [["x | y\nz"]]).split("\n")[2] == "| x \\| y z |"
    with pytest.raises(ValueError):
        md_table(["A"], [[1]], limit=6)
    with pytest.raises(ValueError):
        md_table(["A"], [[1]], limit=0)
    with pytest.raises(ValueError):
        md_table(["A", "B"], [[1]])
    with pytest.raises(ValueError):
        md_table([], [])


def test_write_json_sorted_indented_lf(tmp_path):
    path = write_json(tmp_path / "x.json", {"b": 1, "a": {"d": [1, 2], "c": "Jørn"}})
    raw = path.read_bytes()
    assert raw == '{\n  "a": {\n    "c": "Jørn",\n    "d": [\n      1,\n      2\n    ]\n  },\n  "b": 1\n}\n'.encode()
    assert b"\r" not in raw
    assert not list(tmp_path.glob("*.tmp"))
    with pytest.raises(ValueError):
        write_json(tmp_path / "nan.json", {"x": float("nan")})


@pytest.mark.parametrize(
    ("n", "d", "want"),
    [(0, 0, 0), (5, 0, 0), (0, 24, 0), (24, 24, 100), (21, 24, 88), (17, 24, 71), (1, 8, 13),
     (14, 24, 58), (239, 240, 99), (1, 1000, 1), (2, 1, 200)],
)  # fmt: skip
def test_pct(n, d, want):
    assert pct(n, d) == want


def test_parse_day():
    assert parse_day("2026-10-20") == DAY
    assert parse_day(None) is None and parse_day("") is None
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_day("20/10/2026")


# -- facts on the fixture library (R-311) ---------------------------------------------------------


def test_facts_size(measured):
    assert measured["size"] == {"tracks": 24, "hours": 2.3, "gb": 0.62}


def test_facts_formats(measured):
    assert measured["formats"] == {"aiff": 2, "flac": 4, "m4a": 2, "mp3": 14, "wav": 2}


def test_facts_bitrate_buckets(measured):
    assert measured["bitrates"] == {"<192": 2, "192-255": 2, "256-319": 4, "320": 8, "lossless": 8, "unknown": 0}
    assert measured["bitrate_formats"] == {
        "<192": {"mp3": 2}, "192-255": {"mp3": 2}, "256-319": {"m4a": 2, "mp3": 2}, "320": {"mp3": 8},
        "lossless": {"aiff": 2, "flac": 4, "wav": 2},
    }  # fmt: skip


@pytest.mark.parametrize(
    ("kind", "kbps", "bucket"),
    [("mp3", 0, "unknown"), ("mp3", 128, "<192"), ("mp3", 191, "<192"), ("mp3", 192, "192-255"),
     ("mp3", 255, "192-255"), ("m4a", 256, "256-319"), ("mp3", 319, "256-319"), ("mp3", 320, "320"),
     ("unknown", 330, "320"), ("flac", 0, "lossless"), ("wav", 1411, "lossless"), ("aiff", 128, "lossless"),
     ("m4a", 1000, "lossless"), ("m4a", 399, "320")],
)  # fmt: skip
def test_bitrate_bucket_rules(kind, kbps, bucket):
    assert profile.bitrate_bucket(Track(id="1", kind=kind, bitrate=kbps)) == bucket


def test_facts_eras(measured):
    assert measured["eras"] == {
        "1970s": 2, "1980s": 4, "1990s": 5, "2000s": 3, "2010s": 6, "2020s": 3, "unknown": 1,
    }  # fmt: skip


@pytest.mark.parametrize(("year", "want"), [(0, "unknown"), (1899, "unknown"), (1900, "1900s"), (1994, "1990s"),
                                            (2099, "2090s"), (2100, "unknown"), (-5, "unknown")])  # fmt: skip
def test_decade(year, want):
    assert profile.decade(year) == want


def test_facts_timeline(measured):
    assert measured["timeline"] == {
        "per_year": {"2019": 3, "2020": 2, "2021": 3, "2022": 3, "2023": 3, "2024": 3, "2025": 3, "2026": 4},
        "first_added": "2019-04-12",
        "last_added": "2026-08-08",
        "busiest_year": {"year": "2026", "tracks": 4},
        "busiest_month": {"month": "2019-04", "tracks": 2},
        "undated": 0,
        "last_365_days": 4,
    }


def test_timeline_ties_go_to_the_earlier_month_and_the_window_is_365_days():
    days = [date(2024, 3, 5), date(2024, 3, 9), date(2025, 7, 1), date(2025, 7, 2), date(2025, 10, 21)]
    tracks = [Track(id=str(i), date_added=d) for i, d in enumerate(days, 1)] + [Track(id="9")]
    t = profile.facts(make_lib(tracks), today=DAY)["timeline"]
    assert t["busiest_month"] == {"month": "2024-03", "tracks": 2}
    assert t["busiest_year"] == {"year": "2025", "tracks": 3}
    assert t["undated"] == 1
    assert t["last_365_days"] == 1  # 2025-10-21 is in; 2025-10-20 would be out


def test_facts_fields_share(measured):
    assert measured["fields"] == {
        "genre": {"filled": 23, "pct": 96},
        "bpm": {"filled": 24, "pct": 100},
        "key": {"filled": 22, "pct": 92},
        "rating": {"filled": 20, "pct": 83},
        "colour": {"filled": 17, "pct": 71},
        "comment": {"filled": 17, "pct": 71},
        "label": {"filled": 21, "pct": 88},
        "my_tags": None,  # the XML export does not carry My Tags
    }
    assert measured["not_in_source"] == ["my_tags"]
    assert measured["reader"] == "xml"


def test_facts_empty_counts(measured):
    assert measured["empty"] == {
        "artist": 0, "title": 0, "album": 20, "year": 1, "genre": 1, "bpm": 0, "key": 2,
        "rating": 4, "colour": 7, "comment": 7, "label": 3, "my_tags": None,
    }  # fmt: skip


def test_a_db_library_measures_my_tags():
    tracks = [Track(id="1", my_tags=("Peak",)), Track(id="2"), Track(id="3", my_tags=("Warm Up", "Vocal"))]
    f = profile.facts(make_lib(tracks, source="db"), today=DAY)
    assert f["fields"]["my_tags"] == {"filled": 2, "pct": 67}
    assert f["empty"]["my_tags"] == 1 and f["not_in_source"] == [] and f["reader"] == "db"


def test_facts_duplicates_on_the_fixture(measured, lib):
    d = measured["duplicates"]
    assert d["groups"] == 2 and d["tracks"] == 4
    assert d["all"] == [["8", "22"], ["17", "23"]]
    assert d["top"] == [
        {"track_ids": ["8", "22"], "label_lines": ["Marlo Venn - Hallway Light"] * 2,
         "formats": ["mp3 320 kbps", "flac"]},
        {"track_ids": ["17", "23"], "label_lines": ["Grid Saint - Pressure Vessel"] * 2,
         "formats": ["flac", "mp3 128 kbps"]},
    ]  # fmt: skip
    # 13 is "Brass Tide (Club Edit)" by the artist of 2 "Brass Tide": an edit, not a duplicate.
    assert lib.tracks["13"].title == "Brass Tide (Club Edit)" and lib.tracks["2"].title == "Brass Tide"
    grouped = {i for group in d["all"] for i in group}
    assert not grouped & {"2", "13"}


def test_duplicates_original_mix_groups_and_versions_do_not():
    tracks = [
        Track(id="1", artist="Okoro Lane", title="Sunday Sermon"),
        Track(id="2", artist="okoro lane", title="Sunday Sermon (Original Mix)"),
        Track(id="3", artist="Okoro Lane", title="Sunday Sermon (Extended Mix)"),
        Track(id="4", artist="Okoro Lane", title="Sunday Sermon (Dub)"),
        Track(id="5", artist="Okoro Lane", title="Sunday Sermon (Kestrel Unit Remix)"),
        Track(id="10", artist="Cassia Drift & Lumen Sato", title="Rink"),
        Track(id="11", artist="Cassia Drift and Lumen Sato", title="Rink"),
        Track(id="12", artist="Cássia Drift and Lumen Sato", title="RINK"),
        Track(id="20", artist="", title="Untitled"),
        Track(id="21", artist="", title="Untitled"),  # no artist: not a candidate
    ]
    d = profile.facts(make_lib(tracks), today=DAY)["duplicates"]
    assert d["all"] == [["10", "11", "12"], ["1", "2"]]  # biggest group first
    assert d["groups"] == 2 and d["tracks"] == 5


def test_duplicates_keep_a_remixer_only_remix_apart():
    tracks = [
        Track(id="1", artist="The Velvet Ferrymen", title="Brass Tide"),
        Track(id="2", artist="The Velvet Ferrymen", title="Brass Tide", remixer="Dub Atelier"),
        Track(id="3", artist="The Velvet Ferrymen", title="Brass Tide", remixer="Kestrel Unit"),
        Track(id="4", artist="The Velvet Ferrymen", title="Brass Tide", remixer="dub atelier"),
        Track(id="5", artist="Okoro Lane", title="Sunday Sermon (Kestrel Unit Remix)", remixer="Kestrel Unit"),
        Track(id="6", artist="Okoro Lane", title="Sunday Sermon (Kestrel Unit Remix)"),
    ]
    d = profile.facts(make_lib(tracks), today=DAY)["duplicates"]
    # 1 (the original), 2 and 3 (two remixes) stay apart; 2 and 4 are one remix twice;
    # 5 and 6 are one remix named in the title, with and without the Remixer field.
    assert d["all"] == [["2", "4"], ["5", "6"]]


def test_headline_exactly_five(measured):
    assert measured["headline"] == [
        {"label": "Collection", "value": "24 tracks", "note": "2.3 hours, 0.62 GB"},
        {"label": "Formats", "value": "58% mp3", "note": "8 lossless, 8 at 320 kbps, 4 under 256 kbps"},
        {"label": "Eras", "value": "1970s to 2020s", "note": "most from the 2010s (6 tracks); 1 without a year"},
        {"label": "Weakest field", "value": "Colour 71%", "note": "7 of 24 tracks without it"},
        {"label": "Duplicate candidates", "value": "2 groups", "note": "4 tracks share an artist and title"},
    ]


def test_headline_without_duplicates_shows_the_timeline():
    tracks = [
        Track(id="1", artist="A", title="One", kind="flac", year=1999, genre="House", date_added=date(2020, 5, 1)),
        Track(id="2", artist="B", title="Two", kind="mp3", bitrate=0, year=1999, date_added=date(2024, 6, 2)),
    ]
    head = profile.facts(make_lib(tracks), today=DAY)["headline"]
    assert len(head) == 5
    assert head[1] == {"label": "Formats", "value": "50% mp3", "note": "1 lossless, 0 at 320 kbps, 0 under 256 kbps, 1 no bitrate"}
    assert head[2] == {"label": "Eras", "value": "1990s", "note": "most from the 1990s (2 tracks)"}
    assert head[4] == {"label": "Timeline", "value": "2020 to 2024", "note": "busiest month 2020-05 (1 track)"}


def test_facts_is_deterministic_and_json_ready(lib):
    a, b = profile.facts(lib, today=DAY), profile.facts(lib, today=DAY)
    assert a == b
    assert json.loads(json.dumps(a, sort_keys=True, allow_nan=False)) == a
    assert all(isinstance(k, str) for k in a)
    assert {"size", "formats", "bitrates", "eras", "timeline", "fields", "empty", "duplicates", "headline"} <= set(a)


def test_facts_holds_no_path(measured):
    text = json.dumps(measured, ensure_ascii=False)
    assert not ABSOLUTE.search(text) and "Music" not in text


# -- an empty library ------------------------------------------------------------------------------


def test_empty_library_does_not_crash(tmp_path):
    f = profile.facts(Library(source="xml"), today=DAY)
    assert f["size"] == {"tracks": 0, "hours": 0.0, "gb": 0.0}
    assert f["formats"] == {} and f["eras"] == {"unknown": 0} and f["duplicates"]["groups"] == 0
    assert f["timeline"]["first_added"] is None and f["timeline"]["busiest_month"] is None
    assert [h["label"] for h in f["headline"]] == ["Collection", "Formats", "Eras", "Weakest field", "Timeline"]
    assert all(h["value"] and h["note"] for h in f["headline"])
    text = profile.render(f, source=EXPORT, today=DAY)
    assert list(sections(text)) == SECTIONS
    assert_lists_capped(text)


def test_run_on_an_export_with_no_tracks(tmp_path):
    root = tmp_path / "dj-library"
    scaffold(root, device="mac", today=DAY)
    empty = tmp_path / "empty.xml"
    empty.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<DJ_PLAYLISTS Version="1.0.0">'
                     '<PRODUCT Name="rekordbox" Version="7.2.18"/><COLLECTION Entries="0"/>'
                     '<PLAYLISTS><NODE Type="0" Name="ROOT" Count="0"/></PLAYLISTS></DJ_PLAYLISTS>\n',
                     encoding="utf-8")  # fmt: skip
    import_export(root, empty, today=DAY)
    result = profile.run(root, today=DAY)
    assert result["headline"][0]["value"] == "0 tracks"
    assert (root / "profile" / "stats.md").is_file()


# -- stats.md and facts.json (R-302) ----------------------------------------------------------------


def test_run_returns_written_headline_source(folder, measured):
    result = profile.run(folder, today=DAY)
    assert result == {
        "written": ["profile/stats.md", "profile/facts.json"],
        "headline": measured["headline"],
        "source": EXPORT,
    }


def test_stats_md_title_provenance_and_sections(folder):
    profile.run(folder, today=DAY)
    text = (folder / "profile" / "stats.md").read_text(encoding="utf-8")
    lines = text.split("\n")
    assert lines[0] == "# Library profile" and lines[1] == "" and lines[2] == PROVENANCE
    assert list(sections(text)) == SECTIONS
    assert "| Lossless | 8 | 33% | flac 4, aiff 2, wav 2 |" in text
    assert "| Marlo Venn - Hallway Light | 2 | mp3 320 kbps, flac |" in text
    assert "| Not in this source | My Tags |" in text
    assert "| Duplicate candidates | 2 groups | 4 tracks share an artist and title |" in text
    assert table_sizes(sections(text)["The 5 stats that matter"]) == [5]


def test_stats_md_numbers_all_come_from_facts(folder):
    profile.run(folder, today=DAY)
    text = (folder / "profile" / "stats.md").read_text(encoding="utf-8")
    data = json.loads((folder / "profile" / "facts.json").read_text(encoding="utf-8"))
    for h in data["headline"]:
        assert f"| {h['label']} | {h['value']} | {h['note']} |" in text
    for name, share in data["fields"].items():
        if share is not None:
            assert f"{profile.FIELD_NAMES[name]} {share['pct']}%" in text


def test_stats_md_no_section_over_five_rows(folder):
    profile.run(folder, today=DAY)
    text = (folder / "profile" / "stats.md").read_text(encoding="utf-8")
    assert_lists_capped(text)
    assert "And 1 more in profile/facts.json." in sections(text)["Eras"]  # 6 decades, 5 shown
    assert "And 3 more in profile/facts.json." in sections(text)["Empty fields"]  # 8 gaps, 5 shown


def test_stats_md_cuts_long_lists_with_and_n_more():
    f = profile.facts(big_lib(), today=DAY)
    assert f["duplicates"]["groups"] == 8 and len(f["duplicates"]["top"]) == 5 and len(f["duplicates"]["all"]) == 8
    text = profile.render(f, source=EXPORT, today=DAY)
    assert_lists_capped(text)
    parts = sections(text)
    assert "And 6 more in profile/facts.json." in parts["Eras"]  # 11 decades
    assert "And 3 more in profile/facts.json." in parts["Duplicate candidates"]
    assert "with no bitrate in the source" in parts["Formats and bitrates"]
    assert "without a date added" in parts["Timeline"]


def test_no_absolute_path_in_any_written_file(folder, tmp_path):
    profile.run(folder, today=DAY)
    for rel in ("profile/stats.md", "profile/facts.json", "log.md"):
        text = (folder / rel).read_text(encoding="utf-8")
        assert str(tmp_path) not in text and tmp_path.as_posix() not in text, rel
        assert not ABSOLUTE.search(text), rel


def test_facts_json_carries_provenance_and_the_facts(folder, measured):
    profile.run(folder, today=DAY)
    data = json.loads((folder / "profile" / "facts.json").read_text(encoding="utf-8"))
    assert data.pop("provenance") == {"module": "dj.analysis.profile", "source": EXPORT, "date": "2026-10-20"}
    assert data == measured


def test_facts_json_byte_identical_across_two_runs(folder):
    profile.run(folder, today=DAY)
    first = (folder / "profile" / "facts.json").read_bytes()
    first_md = (folder / "profile" / "stats.md").read_bytes()
    profile.run(folder, today=DAY)
    assert (folder / "profile" / "facts.json").read_bytes() == first
    assert (folder / "profile" / "stats.md").read_bytes() == first_md
    assert b"\r" not in first and b"\r" not in first_md


def test_run_writes_only_stats_facts_and_log(folder):
    before = snapshot(folder)
    profile.run(folder, today=DAY)
    after = snapshot(folder)
    changed = {k for k in after if before.get(k) != after[k]} | (set(before) - set(after))
    assert changed == {"profile/stats.md", "profile/facts.json", "log.md"}
    assert after["log.md"].startswith(before["log.md"])  # appended, nothing rewritten


def test_run_appends_one_log_line(folder):
    profile.run(folder, today=DAY)
    lines = (folder / "log.md").read_text(encoding="utf-8").splitlines()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} profile -> 24 tracks, 2 duplicates; profile/stats\.md", lines[-1])
    assert sum(" profile -> " in line for line in lines) == 1


def test_run_never_writes_habits_md(folder):
    profile.run(folder, today=DAY)
    assert not (folder / "profile" / "habits.md").exists()
    habits = folder / "profile" / "habits.md"
    habits.write_bytes(b"# Who you are as a DJ\n\nThe DJ's own edit.\n")
    profile.run(folder, today=DAY)
    assert habits.read_bytes() == b"# Who you are as a DJ\n\nThe DJ's own edit.\n"


def test_run_reads_an_xml_outside_the_folder_by_name_only(folder, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    outside = fx.write_xml(tmp_path / "elsewhere" / "my export.xml")
    result = profile.run(folder, xml=outside, today=DAY)
    assert result["source"] == "my export.xml"
    text = (folder / "profile" / "stats.md").read_text(encoding="utf-8")
    assert "> Measured by code: dj.analysis.profile from my export.xml, 2026-10-20." in text
    assert str(tmp_path) not in text


def test_run_needs_an_export_or_a_folder(tmp_path):
    root = tmp_path / "dj-library"
    scaffold(root, device="windows", today=DAY)
    with pytest.raises(LibraryError, match="No export"):
        profile.run(root, today=DAY)
    with pytest.raises(LibraryError, match="does not exist"):
        profile.run(tmp_path / "missing", xml=fx.SAMPLE_XML, today=DAY)
    assert not (root / "profile" / "stats.md").exists()


def test_write_refuses_an_absolute_source_before_writing(folder, measured):
    with pytest.raises(ValueError):
        profile.write(LibraryFolder(folder), measured, source=str(folder / EXPORT), today=DAY)
    assert not (folder / "profile" / "stats.md").exists()


# -- which folder, which file: resolved once, checked before anything is written ---------------------


def test_run_with_a_relative_library_gives_folder_relative_paths(folder, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the parent of dj-library
    result = profile.run("dj-library", today=DAY)
    assert result["source"] == EXPORT
    assert result["written"] == ["profile/stats.md", "profile/facts.json"]
    assert (folder / "profile" / "stats.md").read_text(encoding="utf-8").split("\n")[2] == PROVENANCE
    data = json.loads((folder / "profile" / "facts.json").read_text(encoding="utf-8"))
    assert data["provenance"]["source"] == EXPORT
    assert not (folder / "dj-library").exists()


def test_script_with_a_relative_library(folder, tmp_path):
    done = run_script("--library", "dj-library", "--today", "2026-10-20", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    data = json.loads(done.stdout)
    assert data["source"] == EXPORT and data["written"] == ["profile/stats.md", "profile/facts.json"]
    assert (folder / "profile" / "stats.md").read_text(encoding="utf-8").split("\n")[2] == PROVENANCE


def test_cli_with_a_relative_library(folder, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = ["library", "profile", "--library", "dj-library", "--today", "2026-10-20", "--json"]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["source"] == EXPORT and data["written"] == ["profile/stats.md", "profile/facts.json"]


def empty_export(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<DJ_PLAYLISTS Version="1.0.0">'
                    '<PRODUCT Name="rekordbox" Version="7.2.18"/><COLLECTION Entries="0"/>'
                    '<PLAYLISTS><NODE Type="0" Name="ROOT" Count="0"/></PLAYLISTS></DJ_PLAYLISTS>\n',
                    encoding="utf-8")  # fmt: skip
    return path


def test_a_relative_xml_is_looked_up_in_the_library_folder_first(folder, tmp_path, monkeypatch):
    other = tmp_path / "other"
    empty_export(other / EXPORT)  # same relative name in the current folder, 0 tracks
    monkeypatch.chdir(other)
    result = profile.run(folder, xml=EXPORT, today=DAY)
    assert result["source"] == EXPORT and result["headline"][0]["value"] == "24 tracks"
    text = (folder / "profile" / "stats.md").read_text(encoding="utf-8")
    assert text.split("\n")[2] == PROVENANCE and "| Tracks | 24 |" in text


def test_a_relative_xml_not_in_the_library_folder_is_read_from_the_current_folder(folder, tmp_path, monkeypatch):
    other = tmp_path / "other"
    empty_export(other / "good.xml")
    monkeypatch.chdir(other)
    result = profile.run(folder, xml="good.xml", today=DAY)
    # The file that was read (outside the folder, 0 tracks) is the file named: by name only.
    assert result["source"] == "good.xml" and result["headline"][0]["value"] == "0 tracks"
    assert "| Tracks | 0 |" in (folder / "profile" / "stats.md").read_text(encoding="utf-8")


def test_a_relative_xml_found_nowhere_is_an_error_before_writing(folder, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = snapshot(folder)
    with pytest.raises(LibraryFolderError, match="file not found"):
        profile.run(folder, xml="exports/missing.xml", today=DAY)
    assert snapshot(folder) == before


def test_script_with_a_relative_xml_from_another_folder(folder, tmp_path):
    other = tmp_path / "other"
    empty_export(other / EXPORT)
    done = run_script("--library", str(folder), "--xml", EXPORT, "--today", "2026-10-20", cwd=other)
    assert done.returncode == 0, done.stderr
    data = json.loads(done.stdout)
    assert data["source"] == EXPORT and data["headline"][0]["value"] == "24 tracks"


def test_resolve_xml(folder, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_xml(folder, EXPORT) == (folder / EXPORT).resolve()
    assert resolve_xml(folder, "collection.xml") == (tmp_path / "collection.xml").resolve()
    assert resolve_xml(folder, tmp_path / "collection.xml") == (tmp_path / "collection.xml").resolve()
    with pytest.raises(LibraryFolderError, match="not found"):
        resolve_xml(folder, "nope.xml")


def plain_folder(tmp_path: Path) -> Path:
    """A folder the DJ owns, not a dj-library: a photo and their own log.md."""
    plain = tmp_path / "Music"
    plain.mkdir()
    (plain / "holiday.jpg").write_bytes(b"\xff\xd8 not really a photo")
    (plain / "log.md").write_bytes(b"my own notes\n")
    return plain


def test_run_refuses_a_folder_that_is_not_a_dj_library(tmp_path):
    plain = plain_folder(tmp_path)
    before = snapshot(plain)
    with pytest.raises(NotALibraryFolder, match="dj-start"):
        profile.run(plain, xml=fx.SAMPLE_XML, today=DAY)
    with pytest.raises(NotALibraryFolder):
        profile.write(plain, profile.facts(read_xml(fx.SAMPLE_XML), today=DAY), source="x.xml", today=DAY)
    assert snapshot(plain) == before
    assert sorted(p.name for p in plain.iterdir()) == ["holiday.jpg", "log.md"]


def test_run_refuses_an_invalid_library_yaml(folder):
    (folder / "library.yaml").write_text("schema_version: 99\ndevice: toaster\n", encoding="utf-8")
    before = snapshot(folder)
    with pytest.raises(NotALibraryFolder, match="library.yaml is not valid"):
        profile.run(folder, xml=fx.SAMPLE_XML, today=DAY)
    (folder / "library.yaml").write_text("{not: yaml", encoding="utf-8")
    with pytest.raises(NotALibraryFolder, match="library.yaml"):
        profile.run(folder, xml=fx.SAMPLE_XML, today=DAY)
    after = snapshot(folder)
    assert {k: v for k, v in after.items() if k != "library.yaml"} == {
        k: v for k, v in before.items() if k != "library.yaml"
    }


def test_run_refuses_the_home_folder(folder, monkeypatch):
    # A folder that is (or holds) the home folder is never written into, scaffolded or not.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: folder / "inside"))
    before = snapshot(folder)
    with pytest.raises(NotALibraryFolder, match="home folder"):
        profile.run(folder, xml=fx.SAMPLE_XML, today=DAY)
    assert snapshot(folder) == before


def test_library_folder_refuses_a_drive_root(tmp_path):
    with pytest.raises(NotALibraryFolder, match="whole drive"):
        library_folder(Path(tmp_path.anchor))


def test_library_folder_resolves_and_accepts_a_dj_library(folder, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    got = library_folder("dj-library")
    assert got.root == folder.resolve() and got.root.is_absolute()
    assert library_folder(LibraryFolder(folder)).root == folder.resolve()


def test_script_refuses_a_plain_folder_with_exit_2(tmp_path):
    plain = plain_folder(tmp_path)
    before = snapshot(plain)
    done = run_script("--library", str(plain), "--xml", str(fx.SAMPLE_XML), cwd=tmp_path)
    assert done.returncode == 2, done.stdout + done.stderr
    data = json.loads(done.stdout)
    assert data["ok"] is False and "dj-start" in data["refused"]
    assert snapshot(plain) == before


def test_cli_refuses_a_plain_folder(tmp_path):
    plain = plain_folder(tmp_path)
    before = snapshot(plain)
    args = ["library", "profile", "--library", str(plain), "--xml", str(fx.SAMPLE_XML)]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 1 and "ERROR" in result.stderr and "dj-start" in result.stderr
    assert snapshot(plain) == before


# -- R-341: analysis never writes to rekordbox, Spotify or audio files ---------------------------------


def test_r341_run_works_with_master_db_and_engine_packages_blocked(folder, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("analysis opened a master.db session")

    monkeypatch.setattr(safety, "open_db", refuse)
    monkeypatch.setattr(safety, "_connect", refuse)
    for name in ENGINE:
        monkeypatch.setitem(sys.modules, name, None)  # `import name` now raises ImportError
    result = profile.run(folder, today=DAY)
    assert result["written"] == ["profile/stats.md", "profile/facts.json"]


def test_r341_every_write_stays_inside_the_library_folder(folder, tmp_path, monkeypatch):
    """Two checks: a recorder on every way to write a file (open, io.open as pathlib uses it,
    os.open, os.replace, os.link, os.rename, os.mkdir, shutil copies), and a snapshot of
    everything outside the library folder, the current folder included."""
    root, touched = folder.resolve(), []
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    real_replace, real_link, real_rename, real_mkdir = os.replace, os.link, os.rename, os.mkdir
    real_copyfile, real_copy2 = shutil.copyfile, shutil.copy2

    def opener(real):
        def rec(file, mode="r", *args, **kwargs):
            if not isinstance(file, int) and any(c in mode for c in "wax+"):
                touched.append(Path(os.fsdecode(file)))
            return real(file, mode, *args, **kwargs)

        return rec

    def rec_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND):
            touched.append(Path(os.fsdecode(path)))
        return real_os_open(path, flags, *args, **kwargs)

    def to_dst(real):
        def rec(src, dst, *args, **kwargs):
            touched.append(Path(os.fsdecode(dst)))
            return real(src, dst, *args, **kwargs)

        return rec

    def rec_mkdir(path, *args, **kwargs):
        touched.append(Path(os.fsdecode(path)))
        return real_mkdir(path, *args, **kwargs)

    outside_before = {k: v for k, v in snapshot(tmp_path).items() if not k.startswith("dj-library/")}
    monkeypatch.setattr(builtins, "open", opener(real_open))
    monkeypatch.setattr(io, "open", opener(real_io_open))
    monkeypatch.setattr(os, "open", rec_os_open)
    monkeypatch.setattr(os, "replace", to_dst(real_replace))
    monkeypatch.setattr(os, "link", to_dst(real_link))
    monkeypatch.setattr(os, "rename", to_dst(real_rename))
    monkeypatch.setattr(os, "mkdir", rec_mkdir)
    monkeypatch.setattr(shutil, "copyfile", to_dst(real_copyfile))
    monkeypatch.setattr(shutil, "copy2", to_dst(real_copy2))
    shutil.rmtree(folder / "profile")  # so the run has to create profile/ again
    profile.run(folder, today=DAY)
    monkeypatch.undo()
    assert touched, "the recorder saw no write at all"
    assert any(p.name == "profile" for p in touched), "the recorder missed the mkdir"
    outside = [p for p in touched if not p.resolve().is_relative_to(root)]
    assert outside == []
    outside_after = {k: v for k, v in snapshot(tmp_path).items() if not k.startswith("dj-library/")}
    assert outside_after == outside_before
    assert not list(cwd.iterdir())


def test_r341_recorder_sees_pathlib_writes(tmp_path, monkeypatch):
    # The io.open patch is what catches Path.write_text / Path.open; builtins.open alone does not.
    seen = []
    real = io.open

    def rec(file, mode="r", *args, **kwargs):
        if any(c in mode for c in "wax+"):
            seen.append(Path(os.fsdecode(file)).name)
        return real(file, mode, *args, **kwargs)

    monkeypatch.setattr(io, "open", rec)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    monkeypatch.undo()
    assert seen == ["x.txt"]


# -- the skill script (Door 1) ------------------------------------------------------------------------


def _env() -> dict[str, str]:
    paths = [str(REPO / "src")] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    return dict(os.environ, PYTHONPATH=os.pathsep.join(paths), PYTHONUTF8="1")


def run_script(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=_env())  # fmt: skip


def test_script_by_subprocess(folder, tmp_path, measured):
    done = run_script("--library", str(folder), "--today", "2026-10-20", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    assert len(lines) == 1  # one JSON object
    data = json.loads(lines[0])
    assert data == {"ok": True, "written": ["profile/stats.md", "profile/facts.json"],
                    "headline": measured["headline"], "source": EXPORT}  # fmt: skip
    assert (folder / "profile" / "stats.md").read_text(encoding="utf-8").split("\n")[2] == PROVENANCE


def test_script_runs_with_engine_packages_blocked(folder, tmp_path):
    code = textwrap.dedent(f"""
        import json, runpy, sys
        for name in {ENGINE!r}:
            sys.modules[name] = None
        sys.argv = [{str(SCRIPT)!r}, "--library", {str(folder)!r}, "--today", "2026-10-20"]
        try:
            runpy.run_path({str(SCRIPT)!r}, run_name="__main__")
        except SystemExit as exc:
            code = exc.code
        loaded = [m for m in ("dj.readers.db", "dj.library", "dj.spotify", "dj.tidy", "dj.match")
                  if m in sys.modules]
        print(json.dumps(loaded), file=sys.stderr)
        sys.exit(code)
    """)
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=_env())  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["ok"] is True
    assert json.loads(done.stderr.strip().splitlines()[-1]) == []


@pytest.mark.parametrize(
    ("args", "fragment"),
    [((), "--library"), (("--today", "20/10/2026"), "YYYY-MM-DD"), ((), "No export")],
    ids=["no-library", "bad-today", "no-export"],
)
def test_script_errors_exit_1_with_one_json_object(tmp_path, args, fragment):
    root = tmp_path / "dj-library"
    scaffold(root, device="windows", today=DAY)
    argv = list(args) if fragment == "--library" else ["--library", str(root), *args]
    done = run_script(*argv, cwd=tmp_path)
    assert done.returncode == 1
    data = json.loads(done.stdout)
    assert data["ok"] is False and fragment in data["error"]


# -- the CLI (engine door) ------------------------------------------------------------------------------


def test_cli_profile_json(folder, measured):
    result = runner.invoke(cli.app, ["library", "profile", "--library", str(folder), "--today", "2026-10-20", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data == {"written": ["profile/stats.md", "profile/facts.json"], "headline": measured["headline"],
                    "source": EXPORT}  # fmt: skip


def test_cli_profile_defaults_to_the_configured_library(folder, monkeypatch):
    monkeypatch.setenv("DJ_LIBRARY", str(folder))
    result = runner.invoke(cli.app, ["library", "profile", "--today", "2026-10-20"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[:3] == ["wrote profile/stats.md", "wrote profile/facts.json", f"source: {EXPORT}"]
    assert "Collection: 24 tracks (2.3 hours, 0.62 GB)" in result.stdout
    assert (folder / "profile" / "facts.json").is_file()


def test_cli_profile_reads_an_xml_option(folder, tmp_path):
    other = fx.write_xml(tmp_path / "other.xml")
    result = runner.invoke(cli.app, ["library", "profile", "--library", str(folder), "--xml", str(other), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["source"] == "other.xml"


def test_cli_profile_errors_exit_1(tmp_path):
    root = tmp_path / "dj-library"
    scaffold(root, device="windows", today=DAY)
    result = runner.invoke(cli.app, ["library", "profile", "--library", str(root)])
    assert result.exit_code == 1 and "ERROR No export" in result.stderr
    result = runner.invoke(cli.app, ["library", "profile", "--library", str(root), "--today", "tomorrow"])
    assert result.exit_code == 1 and "YYYY-MM-DD" in result.stderr


# -- the skill (R-301, R-312, R-341) ------------------------------------------------------------------


CHECKLIST = """\
## Pre-send checklist

Before every reply, check:

- [ ] The first line is the next action or the answer. No preamble, no pleasantries.
- [ ] Where we are is restated in one line (for example "Step 2 of 6").
- [ ] Steps are numbered, with one concrete time estimate.
- [ ] Lists have 5 items or fewer.
- [ ] No tangents: only what this step needs.
- [ ] Finished work is visible: name the file that was written.
- [ ] Errors are stated matter-of-fact: what failed, what happens next.
- [ ] It ends with one action that takes under 2 minutes.
- [ ] Voice: a working DJ talking to a DJ. Blunt, practical, no hype (shared/voice.md).
- [ ] Nothing was written to rekordbox, Spotify or audio files without a preview and an explicit yes.
"""


@pytest.fixture(scope="module")
def skill_text() -> str:
    return (SKILL / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_skill_frontmatter_and_header(skill_text):
    m = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", skill_text, re.DOTALL)
    assert m
    meta, body = yaml.safe_load(m.group(1)), m.group(2)
    assert meta["name"] == "dj-profile" and meta["description"].strip()
    top = body.split("\n## ", 1)[0]
    assert ("**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by "
            "[shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file "
            "before each reply.") in top  # fmt: skip
    assert "**Requirements:** R-301, R-302, R-311, R-312, R-341." in top


def test_skill_names_the_patterns_it_reads_first(skill_text):
    part = sections(skill_text)["Patterns I read first"]
    for pattern in ("Formats and bitrates", "Eras", "date-added timeline", "Fields used", "Duplicates"):
        assert pattern in part
    assert "Nothing is suggested before these five are read." in part


def test_skill_runs_both_doors_and_owns_habits_md(skill_text):
    assert "scripts/profile.py --library" in skill_text and "dj library profile" in skill_text
    habits = sections(skill_text)["Then write profile/habits.md (R-312)"]
    assert "# Who you are as a DJ\n\n> Words by Claude, from profile/stats.md and profile/facts.json." in habits
    template = re.search(r"```markdown\n(.*?)```", habits, re.DOTALL).group(1)
    paragraphs = [p for p in template.split("\n\n")[2:] if p.strip()]
    assert len(paragraphs) == 4
    assert "taste/vocabulary.md" in habits and "one page" in habits and "R-302" in habits


def test_skill_says_analysis_never_writes_outside(skill_text):
    assert "rekordbox, Spotify or audio files" in sections(skill_text)["What this skill never does (R-341)"]


def test_skill_ends_with_the_canonical_checklist(skill_text):
    heads = list(re.finditer(r"^## ", skill_text, re.MULTILINE))
    assert skill_text[heads[-1].start():].rstrip("\n") == CHECKLIST.rstrip("\n")


def test_skill_lists_have_five_items_or_fewer(skill_text):
    body = skill_text.split("## Pre-send checklist")[0]
    run = 0
    for line in body.split("\n"):
        run = run + 1 if LIST_ITEM.match(line) else 0
        assert run <= 5


def test_common_module_names():
    names = ("norm_key", "dup_key", "provenance_line", "md_table", "write_json", "pct", "library_folder", "resolve_xml")
    for name in names:
        assert callable(getattr(common, name))
