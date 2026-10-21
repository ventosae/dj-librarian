"""dj-taste (W-16): taste facts from the fixture (R-331), appended taste files (R-332), no writes
to rekordbox (R-341), numbers from code with a provenance line (R-302), the skill (R-301)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import date, datetime
from itertools import combinations
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml
from typer.testing import CliRunner

from dj import cli, libfolder, safety
from dj.analysis import taste
from dj.model import Library, LibraryError, PlaylistNode, Track
from dj.readers.xml import read_xml
from dj.taste_files import read_entries

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "plugin" / "skills" / "dj-taste"
SCRIPT = SKILL / "scripts" / "taste.py"
D1, D2 = date(2026, 10, 20), date(2026, 10, 27)
MD_FILES = ["taste/lanes.md", "taste/labels-artists.md", "taste/anchors.md", "taste/vocabulary.md"]
ALL_FILES = MD_FILES + ["taste/facts.json", "taste/cooccurrence.json"]
PROVENANCE = "> Measured by code: dj.analysis.taste from exports/2026-10-20-collection.xml, 2026-10-20."
runner = CliRunner()


@pytest.fixture(scope="module")
def lib() -> Library:
    return read_xml(fx.SAMPLE_XML)


@pytest.fixture(scope="module")
def data(lib) -> dict:
    return taste.facts(lib, today=D1)


@pytest.fixture
def lib_dir(tmp_path) -> Path:
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="windows", today=D1)
    libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=D1)
    return root


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def section(body: str, heading: str) -> str:
    out, inside = [], False
    for line in body.split("\n"):
        if line.startswith(("# ", "## ")):
            inside = line.strip() == heading
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip("\n")


def bullets(body: str, heading: str) -> list[str]:
    return [line for line in section(body, heading).split("\n") if line.startswith("- ")]


def longest_list(body: str) -> int:
    """The longest run of list lines, blank lines skipped (W-19's rule 9 check counts the same)."""
    run = longest = 0
    for line in (line for line in body.split("\n") if line.strip()):
        run = run + 1 if re.match(r"^\s*(?:[-*+]|\d+[.)])\s", line) else 0
        longest = max(longest, run)
    return longest


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def mini_library(bpms: dict[str, list[float]], **track_fields) -> Library:
    """Playlists named by the keys, tracks numbered across them, BPMs as given (0 = untagged)."""
    tracks, roots, n = {}, [], 0
    for name, values in bpms.items():
        ids = []
        for bpm in values:
            n += 1
            tracks[str(n)] = Track(id=str(n), artist=f"Artist {n}", title=f"Title {n}", bpm=bpm, **track_fields)
            ids.append(str(n))
        roots.append(PlaylistNode(id=name, kind="playlist", name=name, track_ids=tuple(ids)))
    return Library(source="xml", tracks=tracks, roots=tuple(roots))


# -- facts on the fixture (R-331)


def test_labels(data):
    labels = data["labels"]
    assert labels["distinct"] == 4 and labels["without_label"] == 3  # tracks 5, 19, 24
    assert [(r["name"], r["tracks"], r["playlists"]) for r in labels["top"]] == [
        ("Low Ceiling Records", 7, 6),
        ("Night Shift Tapes", 7, 4),
        ("Paper Lantern", 4, 5),
        ("Fathom Disc", 3, 3),
    ]
    assert labels["top"][0]["top_artists"] == ["Marlo Venn", "Tessa Quorum", "Dub Atelier"]
    assert labels["top"][1]["top_artists"] == ["Grid Saint", "Kestrel Unit", "Odelia Strand"]
    # independent count from the spec
    spec_counts = {}
    for t in fx.SPEC["tracks"]:
        if t["label"]:
            spec_counts[t["label"]] = spec_counts.get(t["label"], 0) + 1
    assert {r["name"]: r["tracks"] for r in labels["top"]} == spec_counts


def test_artists(data):
    artists = data["artists"]
    assert artists["distinct"] == 16 and artists["without_artist"] == 0
    assert [(r["name"], r["tracks"]) for r in artists["by_tracks"][:2]] == [("Marlo Venn", 3), ("Grid Saint", 3)]
    assert [(r["name"], r["playlists"]) for r in artists["by_playlists"][:3]] == [
        ("Marlo Venn", 5),
        ("Tessa Quorum", 5),
        ("The Velvet Ferrymen", 5),
    ]
    assert "Saffi Wren" not in [r["name"] for r in artists["by_playlists"]]  # an orphan: in no playlist


def test_three_bpm_lanes(data):
    lanes = data["lanes"]
    assert [lane["label"] for lane in lanes] == ["100-109", "119-122", "122-127"]
    assert [lane["playlists"] for lane in lanes] == [
        ["funk & disco 78-92"],
        ["House/1.1_warm_up", "House/Deep/deep_rollers"],
        ["House/1.2_peak", "Gigs/Gig 2025-03 Warehouse"],
    ]
    assert [(lane["tracks"], lane["median"]) for lane in lanes] == [(7, 104), (6, 120), (9, 124)]
    assert [lane["key"] for lane in lanes] == [
        "lane:funk-disco-78-92", "lane:house-1-1-warm-up", "lane:gigs-gig-2025-03-warehouse",
    ]  # fmt: skip
    rows = {r["path"]: r for r in data["bpm_playlists"]}
    assert "House/Deep/empty_ideas" not in rows  # no BPM-tagged tracks
    assert rows["House/1.1_warm_up"]["range"] == "119-121" and rows["House/1.1_warm_up"]["median"] == 120
    assert rows["Gigs/Gig 2025-03 Warehouse"]["range"] == "123-127"  # 126.5 rounds half up
    mixed = [r["path"] for r in data["bpm_playlists"] if r["mixed"]]
    assert mixed == ["Gigs/Gig 2025-11 Rooftop", "unsorted dump"]
    assert all(r["lane"] is None for r in rows.values() if r["mixed"])


def test_lane_rules():
    lib = mini_library({
        "touch_a": [118, 119, 121, 122],  # 119-121
        "touch_b": [121, 121, 122, 123],  # 121-122: shares only 121 with touch_a -> its own lane
        "over": [120, 120, 121, 121],  # 120-121: overlaps touch_a -> merged
        "two_only": [130, 131, 0, 0],  # 2 BPM-tagged tracks: no lane
        "wide": [90, 100, 120, 140],  # middle half 98-125: mixed
    })  # fmt: skip
    data = taste.facts(lib)
    assert [(lane["label"], lane["playlists"]) for lane in data["lanes"]] == [
        ("119-121", ["touch_a", "over"]),
        ("121-122", ["touch_b"]),
    ]
    rows = {r["path"]: r for r in data["bpm_playlists"]}
    assert "two_only" not in rows
    assert rows["wide"]["mixed"] and rows["wide"]["range"] == "98-125"


def lanes_of(bpms: dict[str, list[float]]) -> list[tuple[str, list[str]]]:
    return [(lane["label"], lane["playlists"]) for lane in taste.facts(mini_library(bpms))["lanes"]]


@pytest.mark.parametrize(
    ("bpms", "lanes"),
    [
        ({"deep A": [124] * 4, "deep B": [124] * 4}, [("124-124", ["deep A", "deep B"])]),  # the same point
        ({"wide": [119, 120, 122, 123], "flat122": [122] * 4}, [("120-122", ["wide", "flat122"])]),  # inside
        ({"wide": [119, 120, 122, 123], "flat120": [120] * 4}, [("120-122", ["wide", "flat120"])]),  # holds it
        ({"a": [119, 120, 122, 123], "point": [124] * 4}, [("120-122", ["a"]), ("124-124", ["point"])]),
        ({"warm": [118, 119, 122, 123], "peak": [121, 122, 124, 125]}, [("119-122", ["warm"]), ("122-124", ["peak"])]),
    ],
)  # fmt: skip
def test_lane_merge_rule(bpms, lanes):
    """Overlap by more than a boundary BPM, or one range holds the other; a shared boundary is
    not enough."""
    assert lanes_of(bpms) == lanes


def test_a_ladder_of_overlapping_ranges_does_not_collapse_into_one_lane():
    ladder = {
        "deep house": [119, 120, 124, 125],  # 120-124
        "house": [122, 123, 127, 128],  # 123-127
        "tech house": [125, 126, 130, 131],  # 126-130
        "techno warm": [128, 129, 133, 134],  # 129-133
        "techno": [131, 132, 136, 137],  # 132-136
        "hard techno": [134, 135, 139, 140],  # 135-139
    }
    data = taste.facts(mini_library(ladder))
    assert [r["range"] for r in data["bpm_playlists"]] == ["120-124", "123-127", "126-130", "129-133", "132-136",
                                                           "135-139"]  # fmt: skip
    assert not any(r["mixed"] for r in data["bpm_playlists"])
    lanes = data["lanes"]
    assert [(lane["label"], lane["playlists"]) for lane in lanes] == [
        ("120-130", ["deep house", "house", "tech house"]),
        ("129-139", ["techno warm", "techno", "hard techno"]),
    ]
    assert all(lane["hi"] - lane["lo"] <= taste.MAX_LANE_WIDTH for lane in lanes)


def test_keys(data):
    keys = data["keys"]
    assert keys["top"][:3] == [{"key": "Am", "tracks": 5}, {"key": "Gm", "tracks": 4}, {"key": "Dm", "tracks": 3}]
    assert (keys["tagged"], keys["untagged"], keys["minor"], keys["major"]) == (22, 2, 21, 1)
    assert keys["minor_share"] == 0.95 and keys["major_share"] == 0.05


@pytest.mark.parametrize(
    ("key", "mode"),
    [("Am", "minor"), ("F#m", "minor"), ("Bbm", "minor"), ("C", "major"), ("Eb", "major"), ("Amin", "minor"),
     ("8A", "minor"), ("8B", "major"), ("12a", "minor"), ("1m", "minor"), ("6d", "major"), ("", "unknown"),
     ("weird", "unknown"), ("13A", "unknown")],
)  # fmt: skip
def test_key_mode(key, mode):
    assert taste.key_mode(key) == mode


def test_cooccurrence_matches_the_fixture(data):
    co = data["cooccurrence"]
    # brute force from the spec: track sets per playlist, pairs counted over playlists
    sets = []

    def walk(nodes):
        for node in nodes:
            if node["kind"] == "folder":
                walk(node["children"])
            elif node["kind"] == "playlist":
                sets.append(set(node["tracks"]))

    walk(fx.without_smart()["tree"])
    expected = {}
    for members in sets:
        for a, b in combinations(sorted(members, key=int), 2):
            expected[(a, b)] = expected.get((a, b), 0) + 1
    expected = {pair: n for pair, n in expected.items() if n >= 2}
    assert {(a, b): n for a, b, n in co["pairs"]} == expected
    assert co["count"] == co["kept"] == len(expected) == 45 and co["max_pairs"] == taste.MAX_PAIRS
    assert [(p["a"], p["b"], p["count"]) for p in co["top"][:4]] == [
        ("1", "2", 3), ("1", "4", 3), ("2", "4", 3), ("11", "12", 3),
    ]  # fmt: skip
    assert co["pairs"][:4] == [["1", "2", 3], ["1", "4", 3], ["2", "4", 3], ["11", "12", 3]]
    assert ["10", "21", 2] in co["pairs"]  # 1.1_warm_up and deep_rollers
    pair = co["top"][0]
    assert pair["playlists"] == ["Gigs/Gig 2025-11 Rooftop", "unsorted dump", "funk & disco 78-92"]
    assert pair["tracks"] == ["Okoro Lane - Sunday Sermon", "The Velvet Ferrymen - Brass Tide"]
    assert len(co["top"]) == taste.TOP_PAIRS


def test_cooccurrence_skips_big_playlists(lib, monkeypatch):
    monkeypatch.setattr(taste, "MAX_PAIR_PLAYLIST", 6)
    co = taste.facts(lib)["cooccurrence"]
    assert co["skipped_playlists"] == ["Gigs/Gig 2025-03 Warehouse", "unsorted dump", "funk & disco 78-92"]
    assert ("11", "12") not in {(a, b) for a, b, _n in co["pairs"]}  # only in skipped or one kept


def test_cooccurrence_keeps_the_strongest_pairs(lib, data, monkeypatch, tmp_path):
    monkeypatch.setattr(taste, "MAX_PAIRS", 10)
    co = taste.facts(lib)["cooccurrence"]
    assert co["count"] == 45 and co["kept"] == 10 and co["max_pairs"] == 10
    assert co["pairs"] == data["cooccurrence"]["pairs"][:10]  # the strongest, in the same order
    folder = tmp_path / "dj-library"
    libfolder.scaffold(folder, device="mac", today=D1)
    taste.write(folder, taste.facts(lib), source="exports/x.xml", today=D1)
    body = read(folder / "taste/cooccurrence.json")
    pairs = json.loads(body)
    assert (pairs["count"], pairs["kept"], len(pairs["pairs"])) == (45, 10, 10)
    assert '    ["1","2",3],\n' in body  # compact, one pair per line


def test_cooccurrence_json_stays_small_on_a_big_library(tmp_path):
    """Sets drawn from crates give many pairs: the file is bounded by MAX_PAIRS, not by them."""
    tracks = {str(n): Track(id=str(n), artist=f"A{n % 50}", title=f"T{n}", bpm=120) for n in range(1, 2001)}
    crates = [[str(n) for n in range(start, start + 100)] for start in range(1, 2001, 100)]
    sets = [crates[i % 20][j:j + 50] + crates[(i + 1) % 20][j:j + 50] for i in range(40) for j in (0, 25, 50)]
    roots = tuple(PlaylistNode(id=f"s{i}", kind="playlist", name=f"set {i}", track_ids=tuple(ids))
                  for i, ids in enumerate(sets))  # fmt: skip
    data = taste.facts(Library(source="xml", tracks=tracks, roots=roots))
    co = data["cooccurrence"]
    assert co["count"] > taste.MAX_PAIRS and co["kept"] == taste.MAX_PAIRS
    folder = tmp_path / "dj-library"
    libfolder.scaffold(folder, device="mac", today=D1)
    taste.write(folder, data, source="exports/x.xml", today=D1)
    size = (folder / "taste/cooccurrence.json").stat().st_size
    assert size < 30 * taste.MAX_PAIRS  # about 20 bytes a pair
    assert len(json.loads(read(folder / "taste/cooccurrence.json"))["pairs"]) == taste.MAX_PAIRS


def test_clusters_and_anchors(data):
    clusters = data["clusters"]
    assert [(c["name"], c["names"], c["tracks"]) for c in clusters] == [
        ("Low Ceiling Records", ["Low Ceiling Records", "Night Shift Tapes"], 14),
        ("Paper Lantern", ["Paper Lantern"], 4),
        ("Fathom Disc", ["Fathom Disc", "Brother Ferro"], 4),  # an unlabelled artist joins by playlists
    ]
    assert [c["anchors"] for c in clusters] == [["17", "9", "16"], ["13", "2", "1"], ["4"]]
    assert all(1 <= len(c["anchors"]) <= taste.MAX_ANCHORS for c in clusters)
    assert all(set(c["anchors"]) <= set(c["track_ids"]) for c in clusters)
    anchors = data["anchors"]
    assert [a["id"] for a in anchors] == ["17", "9", "16", "13", "2", "1", "4"]
    assert anchors[0] == {
        "id": "17", "track": "Grid Saint - Pressure Vessel", "rating": 5, "play_count": 33, "bpm": 128,
        "key": "Gm", "cluster": "Low Ceiling Records", "partners": 1,
    }  # fmt: skip
    # Volta Rook (only in the dump) and Saffi Wren (an orphan) join no cluster
    members = {name for c in clusters for name in c["names"]}
    assert not members & {"Volta Rook", "Saffi Wren"}
    assert data["labels"]["top"][1]["cluster"] == "Low Ceiling Records"


def test_anchor_rules():
    tracks = {
        "1": Track(id="1", artist="A", title="Same", label="L", rating=5, play_count=9),
        "2": Track(id="2", artist="a", title="same ", label="L", rating=5, play_count=8),  # duplicate of 1
        "3": Track(id="3", artist="B", title="Other", label="L", rating=3, play_count=50),  # under 4 stars
        "4": Track(id="4", artist="C", title="Low", label="M", rating=0, play_count=0),
        "5": Track(id="5", artist="D", title="Low too", label="M", rating=0, play_count=0),
    }
    roots = (
        PlaylistNode(id="p", kind="playlist", name="p", track_ids=("1", "2", "3")),
        PlaylistNode(id="q", kind="playlist", name="q", track_ids=("4", "5")),
    )
    data = taste.facts(Library(source="xml", tracks=tracks, roots=roots))
    assert [(c["name"], c["anchors"]) for c in data["clusters"]] == [("L", ["1"]), ("M", ["4"])]


def test_top_rated_and_most_played(data):
    top, played = data["top_rated"], data["most_played"]
    assert top["count"] == 12 and all(t["rating"] >= 4 for t in top["top"])
    assert [t["id"] for t in top["top"][:4]] == ["17", "9", "13", "2"]
    assert played["count"] == 20 and [t["play_count"] for t in played["top"][:3]] == [33, 31, 27]
    plays = [t["play_count"] for t in played["top"]]
    assert plays == sorted(plays, reverse=True)


def test_vocabulary(data):
    vocab = data["vocabulary"]
    counts = {w["word"]: w["count"] for w in vocab["top"]}
    assert {"warm", "peak", "deep", "gig", "rollers", "warehouse", "funk", "disco"} <= set(counts)
    assert counts["deep"] == 2 and counts["gig"] == 2 and counts["warm"] == 1
    assert vocab["top"][0] == {"word": "deep", "count": 2, "examples": ["House/Deep", "House/Deep/deep_rollers"]}
    assert vocab["names"] == 11 and len(vocab["top"]) <= taste.TOP_WORDS
    for word in counts:
        assert re.fullmatch(r"[^\W\d_]{3,}", word) and word == word.lower()
    assert not set(counts) & {"up", "the", "and", "2025", "78"}


def test_words_of():
    assert taste.words_of("The 1.1_warm_up & Untitled Playlist 2025-03") == ["warm"]
    assert taste.words_of("Deep deep DEEP rollers") == ["deep", "rollers"]
    assert taste.words_of("Søndag på Taget") == ["søndag", "taget"]


def test_facts_are_deterministic_and_json(lib, data):
    assert taste.facts(lib) == data
    shuffled = Library(source="xml", tracks=dict(reversed(list(lib.tracks.items()))), roots=lib.roots)
    assert taste.facts(shuffled) == data  # no dependence on dict order
    assert json.loads(json.dumps(data)) == data


def test_facts_on_an_empty_library(tmp_path):
    data = taste.facts(Library(source="xml"))
    assert data["lanes"] == [] and data["clusters"] == [] and data["vocabulary"]["top"] == []
    folder = tmp_path / "dj-library"
    libfolder.scaffold(folder, device="mac", today=D1)
    result = taste.write(folder, data, source="exports/x.xml", today=D1)
    assert all(lines == [] for lines in result["added"].values())
    for rel in MD_FILES:
        assert 1 == len(bullets(read(folder / rel), "## Now"))  # a placeholder line, no list


# -- the files (R-332, R-302)


def test_run_writes_the_taste_files(lib_dir, monkeypatch):
    monkeypatch.setattr(libfolder, "_wall_clock", lambda: datetime(2026, 10, 21, 13, 20))  # Q-28: the wall clock
    result = taste.run(lib_dir, today=D1)
    assert result["written"] == ALL_FILES
    assert result["source"] == "exports/2026-10-20-collection.xml"
    assert result["counts"] == {
        "tracks": 24, "lanes": 3, "clusters": 3, "anchors": 7, "pairs": 45, "words": 15,
        "lines_added": sum(len(v) for v in result["added"].values()),
    }  # fmt: skip
    assert list(result["counts"])[0] == "tracks"  # counts first
    titles = {"taste/lanes.md": "# BPM lanes", "taste/labels-artists.md": "# Labels and artists",
              "taste/anchors.md": "# Anchor tracks", "taste/vocabulary.md": "# Naming vocabulary"}  # fmt: skip
    for rel in MD_FILES:
        body = read(lib_dir / rel)
        lines = [line for line in body.split("\n") if line.strip()]
        assert lines[0] == titles[rel] and lines[1] == PROVENANCE  # R-302
        assert 1 <= len(bullets(body, "## Now")) <= 5
        assert bullets(body, "## Log") == result["added"][rel]  # the diff shown is what was written
        assert 1 <= len(result["added"][rel]) <= 5  # lists <= 5 (contract section 0)
        assert longest_list(body) <= 5, rel
    lanes = read(lib_dir / "taste/lanes.md")
    for label in ("100-109 BPM", "119-122 BPM", "122-127 BPM"):
        assert label in section(lanes, "## Now") and label in section(lanes, "## Log")
    assert "Mixed BPM, not a lane: Gigs/Gig 2025-11 Rooftop (104-122), unsorted dump (107-122)" in lanes
    assert "<!-- key:label:low ceiling records -->" in read(lib_dir / "taste/labels-artists.md")
    assert "<!-- key:artist:marlo venn -->" in read(lib_dir / "taste/labels-artists.md")
    anchors = read(lib_dir / "taste/anchors.md")
    assert "Grid Saint - Pressure Vessel: anchor for Low Ceiling Records; 5 stars, 33 plays, 128 BPM, key Gm" in anchors
    assert len(bullets(anchors, "## Now")) == 3  # one line per cluster
    words = read(lib_dir / "taste/vocabulary.md")
    assert "<!-- key:word:deep -->" in words and "<!-- key:word:gig -->" in words
    assert [e.key for e in read_entries(lib_dir / "taste/vocabulary.md")] == [
        f"word:{w['word']}" for w in taste.facts(read_xml(fx.SAMPLE_XML))["vocabulary"]["top"][:5]
    ]
    facts_json = json.loads(read(lib_dir / "taste/facts.json"))
    assert facts_json["measured"] == {"by": "dj.analysis.taste", "source": "exports/2026-10-20-collection.xml",
                                      "date": "2026-10-20"}  # fmt: skip
    assert "pairs" not in facts_json["cooccurrence"] and facts_json["cooccurrence"]["count"] == 45
    assert "peak" in {w["word"] for w in facts_json["vocabulary"]["top"]}  # the full list is in the JSON
    pairs_json = json.loads(read(lib_dir / "taste/cooccurrence.json"))
    assert len(pairs_json["pairs"]) == 45 and pairs_json["pairs"][0] == ["1", "2", 3]
    assert pairs_json["measured"] == facts_json["measured"] and pairs_json["count"] == pairs_json["kept"] == 45
    log = read(lib_dir / "log.md").strip().split("\n")[-1]
    assert log == f"2026-10-20 13:20 taste -> {result['counts']['lines_added']} lines added; taste"


def test_same_export_gives_the_same_files(tmp_path):
    folders = []
    for name in ("a", "b"):
        root = tmp_path / name / "dj-library"
        libfolder.scaffold(root, device="mac", today=D1)
        libfolder.import_export(root, fx.write_xml(tmp_path / name / "collection.xml"), today=D1)
        taste.run(root, today=D1)
        folders.append(root)
    a, b = ({rel: (root / rel).read_bytes() for rel in ALL_FILES} for root in folders)
    assert a == b


def test_numbers_in_md_come_from_the_facts(lib_dir):
    taste.run(lib_dir, today=D1)
    facts_json = json.loads(read(lib_dir / "taste/facts.json"))
    lanes = read(lib_dir / "taste/lanes.md")
    for lane in facts_json["lanes"]:
        assert f"{lane['label']} BPM" in lanes and f"median {lane['median']}" in lanes
    labels = read(lib_dir / "taste/labels-artists.md")
    for label in facts_json["labels"]["top"][: taste.LOG_LABELS]:
        assert f"{label['name']}: {label['tracks']} tracks in {label['playlists']} playlists" in labels
    now = section(labels, "## Now")
    for label in facts_json["labels"]["top"][:5]:
        assert f"{label['name']} {label['tracks']}" in now
    keys = [e.key for e in read_entries(lib_dir / "taste/labels-artists.md")]
    assert keys == ["label:low ceiling records", "label:night shift tapes", "label:paper lantern",
                    "artist:marlo venn", "artist:grid saint"]  # fmt: skip
    anchors = [e.key for e in read_entries(lib_dir / "taste/anchors.md")]
    assert anchors == ["anchor:17", "anchor:9", "anchor:13", "anchor:2", "anchor:4"]  # each cluster in turn


def test_second_run_adds_nothing_and_the_log_is_byte_identical(lib_dir):
    taste.run(lib_dir, today=D1)
    first = {rel: (lib_dir / rel).read_bytes() for rel in MD_FILES}
    again = taste.run(lib_dir, today=D1)
    assert again["counts"]["lines_added"] == 0 and all(v == [] for v in again["added"].values())
    assert {rel: (lib_dir / rel).read_bytes() for rel in MD_FILES} == first
    later = taste.run(lib_dir, today=D2)  # a later session, same library
    assert later["counts"]["lines_added"] == 0
    for rel in MD_FILES:
        body = read(lib_dir / rel)
        assert section(body, "## Log") == section(first[rel].decode("utf-8"), "## Log")
        assert "2026-10-27." in body.split("\n")[2]  # only the provenance date moved
    assert read(lib_dir / "log.md").count("taste -> 0 lines added") == 2


def test_changed_library_appends_updated_entries(lib_dir, tmp_path):
    taste.run(lib_dir, today=D1)
    before = {rel: section(read(lib_dir / rel), "## Log") for rel in MD_FILES}
    spec = fx.spec_copy()
    next(t for t in spec["tracks"] if t["id"] == "17")["play_count"] = 40
    gigs = next(n for n in spec["tree"] if n["name"] == "Gigs")
    gigs["children"].append(fx._pl("Gig 2026-09 Basement", [16, 17, 18, 20]))
    libfolder.import_export(lib_dir, fx.write_xml(tmp_path / "changed.xml", spec), today=D2)
    result = taste.run(lib_dir, today=D2)
    assert result["source"] == "exports/2026-10-27-collection.xml"
    added = result["added"]
    assert any(line.startswith("- [2026-10-27] updated: Grid Saint - Pressure Vessel") and "40 plays" in line
               for line in added["taste/anchors.md"])  # fmt: skip
    assert "- [2026-10-27] 128-130 BPM: Gigs/Gig 2026-09 Basement; 4 tracks, median 128.5 " \
           "<!-- key:lane:gigs-gig-2026-09-basement -->" in added["taste/lanes.md"]
    assert any("<!-- key:word:basement -->" in line for line in added["taste/vocabulary.md"])
    for rel in MD_FILES:
        log = section(read(lib_dir / rel), "## Log")
        assert log.startswith(before[rel])  # every earlier line kept, in place
        assert log[len(before[rel]):].strip().split("\n") == (added[rel] or [""])


def test_hand_written_lines_survive_and_rebuild_needs_the_flag(lib_dir, monkeypatch):
    monkeypatch.setattr(libfolder, "_wall_clock", lambda: datetime(2026, 10, 21, 13, 20))  # Q-28: the wall clock
    taste.run(lib_dir, today=D1)
    lanes = lib_dir / "taste/lanes.md"
    mine = "- [2026-10-21] Sunday sets never go above 122. My own line."
    lanes.write_bytes(lanes.read_bytes() + (mine + "\n").encode("utf-8"))
    taste.run(lib_dir, today=D2)
    assert mine in read(lanes).split("\n")

    old = {rel: (lib_dir / rel).read_bytes() for rel in MD_FILES}
    result = taste.run(lib_dir, today=D2, rebuild=True)
    assert result["rebuild"] is True
    assert mine not in read(lanes)
    assert bullets(read(lanes), "## Log") == result["added"]["taste/lanes.md"]
    assert all(line.startswith("- [2026-10-27] ") for line in result["added"]["taste/lanes.md"])
    n = result["counts"]["lines_added"]
    assert n == sum(len(v) for v in result["added"].values())
    # the old files, the DJ's line included, are kept byte for byte in .cache
    backup = ".cache/taste-rebuild-2026-10-27"
    assert result["backup"] == {"folder": backup, "files": [rel.split("/")[1] for rel in MD_FILES]}
    for rel in MD_FILES:
        assert (lib_dir / backup / rel.split("/")[1]).read_bytes() == old[rel]
    assert mine in read(lib_dir / backup / "lanes.md").split("\n")
    last = read(lib_dir / "log.md").strip().split("\n")[-1]
    assert last == f"2026-10-27 13:20 taste -> {n} lines added, 4 files rebuilt, 4 old files kept in {backup}; taste"

    again = taste.run(lib_dir, today=D2, rebuild=True)  # a second rebuild that day: a new folder
    assert again["backup"]["folder"] == backup + "-2"
    assert (lib_dir / backup / "lanes.md").read_bytes() == old["taste/lanes.md"]  # the first copy untouched


def test_rebuild_with_no_taste_files_yet_keeps_no_copy(lib_dir):
    result = taste.run(lib_dir, today=D1, rebuild=True)
    assert result["backup"] is None and not (lib_dir / ".cache").exists()
    assert read(lib_dir / "log.md").strip().split("\n")[-1].endswith("lines added, 4 files rebuilt; taste")


def test_no_absolute_paths_in_the_library_folder(lib_dir, tmp_path):
    taste.run(lib_dir, today=D1)
    taste.run(lib_dir, xml=tmp_path / "collection.xml", today=D2)  # an export outside the folder
    assert "from collection.xml, 2026-10-27." in read(lib_dir / "taste/lanes.md")
    for rel in ALL_FILES + ["log.md"]:
        body = read(lib_dir / rel)
        for needle in (str(tmp_path), tmp_path.as_posix(), "D:/", "file://", "/Users/", "//nas", "\\"):
            assert needle not in body, (rel, needle)


def test_a_relative_xml_is_taken_from_the_working_directory(lib_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = taste.run(lib_dir, xml="dj-library/exports/2026-10-20-collection.xml", today=D1)
    assert result["source"] == "exports/2026-10-20-collection.xml"
    assert result["counts"]["tracks"] == 24


def test_a_relative_xml_is_looked_up_in_the_library_folder_first(lib_dir, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "exports").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)  # the same relative path exists nowhere here
    result = taste.run(lib_dir, xml="exports/2026-10-20-collection.xml", today=D1)
    assert result["source"] == "exports/2026-10-20-collection.xml" and result["counts"]["tracks"] == 24
    # a file in the library folder wins over one with the same relative path in the current folder
    (elsewhere / "exports" / "2026-10-20-collection.xml").write_bytes(b"not xml")
    assert taste.run(lib_dir, xml="exports/2026-10-20-collection.xml", today=D1)["counts"]["tracks"] == 24
    with pytest.raises(libfolder.LibraryFolderError, match="not found in the library folder or the current folder"):
        taste.run(lib_dir, xml="exports/missing.xml", today=D1)


def test_keys_survive_names_that_look_like_comment_markers(tmp_path):
    tracks = {
        str(n): Track(id=str(n), artist="Arrow --> Man", title=f"T{n}", label="Label <!-- x --->", bpm=119 + n,
                      rating=5 - n)
        for n in (1, 2, 3)
    }  # fmt: skip
    roots = (
        PlaylistNode(id="p", kind="playlist", name="peak ---> warm", track_ids=("1", "2", "3")),
        PlaylistNode(id="r", kind="playlist", name="r", track_ids=("1", "2")),
    )
    data = taste.facts(Library(source="xml", tracks=tracks, roots=roots))
    folder = tmp_path / "dj-library"
    libfolder.scaffold(folder, device="mac", today=D1)
    first = taste.write(folder, data, source="exports/x.xml", today=D1)
    assert sum(len(v) for v in first["added"].values()) > 0
    for rel in MD_FILES:
        for line in bullets(read(folder / rel), "## Log"):
            assert line.count("<!--") == 1 and line.count("-->") == 1, line
        for line in bullets(read(folder / rel), "## Now"):
            assert "<!--" not in line and "-->" not in line, line
    assert "peak -> warm" in section(read(folder / "taste/lanes.md"), "## Now")
    keys = [e.key for e in read_entries(folder / "taste/labels-artists.md")]
    assert "label:label <!-%2D x -%2D%2D>" in keys and "artist:arrow -%2D> man" in keys
    again = taste.write(folder, data, source="exports/x.xml", today=D2)
    assert all(lines == [] for lines in again["added"].values())  # the keys are stable


def test_names_that_differ_only_in_dashes_get_their_own_keys(tmp_path):
    """'Night--Shift' and 'Night-Shift' are two labels: two keys, no collision, no abort."""
    labels = ["Night--Shift", "Night-Shift", "100% Records", "100%25 Records"]
    tracks = {
        str(n): Track(id=str(n), artist="Night--Shift" if n <= 4 else "Night-Shift", title=f"T{n}",
                      label=labels[(n - 1) // 2], bpm=120)
        for n in range(1, 9)
    }  # fmt: skip
    roots = (PlaylistNode(id="p", kind="playlist", name="p", track_ids=tuple(tracks)),
             PlaylistNode(id="q", kind="playlist", name="q", track_ids=tuple(tracks)))  # fmt: skip
    data = taste.facts(Library(source="xml", tracks=tracks, roots=roots))
    label_keys = [taste._key("label", name) for name in labels]
    assert len(set(label_keys)) == 4 and not any("--" in key for key in label_keys)
    assert label_keys[:2] == ["label:night-%2Dshift", "label:night-shift"]
    assert label_keys[2:] == ["label:100%25 records", "label:100%2525 records"]
    folder = tmp_path / "dj-library"
    libfolder.scaffold(folder, device="mac", today=D1)
    first = taste.write(folder, data, source="exports/x.xml", today=D1)
    keys = [e.key for e in read_entries(folder / "taste/labels-artists.md")]
    assert keys == ["label:100%25 records", "label:100%2525 records", "label:night-%2Dshift",
                    "artist:night-%2Dshift", "artist:night-shift"]  # fmt: skip
    again = taste.write(folder, data, source="exports/x.xml", today=D2)
    assert sum(len(v) for v in first["added"].values()) > 0
    assert all(lines == [] for lines in again["added"].values())


def test_a_text_that_starts_with_updated_adds_nothing_on_the_second_run(tmp_path):
    """An artist called 'Updated' and the word 'updated' from 'Updated picks' (review finding)."""
    tracks = {str(n): Track(id=str(n), artist="Updated", title=f"T{n}", label="Updated: Records", bpm=120)
              for n in (1, 2, 3)}  # fmt: skip
    roots = (PlaylistNode(id="p", kind="playlist", name="Updated picks", track_ids=("1", "2", "3")),
             PlaylistNode(id="q", kind="playlist", name="updated warmup", track_ids=("1", "2")))  # fmt: skip
    data = taste.facts(Library(source="xml", tracks=tracks, roots=roots))
    folder = tmp_path / "dj-library"
    libfolder.scaffold(folder, device="mac", today=D1)
    first = taste.write(folder, data, source="exports/x.xml", today=D1)
    assert any(line.startswith("- [2026-10-20] updated: 2 names") for line in first["added"]["taste/vocabulary.md"])
    assert any(line.startswith("- [2026-10-20] Updated: 3 tracks") for line in first["added"]["taste/labels-artists.md"])
    before = {rel: (folder / rel).read_bytes() for rel in MD_FILES}
    again = taste.write(folder, data, source="exports/x.xml", today=D1)
    assert all(lines == [] for lines in again["added"].values())
    assert {rel: (folder / rel).read_bytes() for rel in MD_FILES} == before


def test_a_bad_taste_file_stops_the_run_before_anything_is_written(lib_dir):
    taste.run(lib_dir, today=D1)
    anchors = lib_dir / "taste/anchors.md"
    anchors.write_bytes("# Anchor tracks\n\n## Log\n\n- caf\xe9 by hand\n".encode("cp1252"))
    before = snapshot(lib_dir)
    with pytest.raises(LibraryError, match="anchors.md is not UTF-8"):
        taste.run(lib_dir, xml=fx.SAMPLE_XML, today=D2)  # another export: every file would change
    assert snapshot(lib_dir) == before  # no MD file, no JSON file, no log line


def test_a_write_that_fails_part_way_names_what_was_written_and_logs_it(lib_dir, monkeypatch):
    monkeypatch.setattr(libfolder, "_wall_clock", lambda: datetime(2026, 10, 21, 13, 20))  # Q-28: the wall clock
    real = taste.write_plan

    def fail_on_anchors(plan):
        if plan.path.name == "anchors.md":
            raise PermissionError(13, "Permission denied")
        return real(plan)

    monkeypatch.setattr(taste, "write_plan", fail_on_anchors)
    with pytest.raises(taste.TasteWriteError) as caught:
        taste.run(lib_dir, today=D1)
    err = caught.value
    assert err.written == ["taste/lanes.md", "taste/labels-artists.md"]
    assert list(err.added) == err.written and all(err.added.values())
    assert "taste/anchors.md: cannot write it (Permission denied)" in str(err)
    assert "Written before it: taste/lanes.md, taste/labels-artists.md" in str(err)
    assert bullets(read(lib_dir / "taste/lanes.md"), "## Log") == err.added["taste/lanes.md"]
    assert not (lib_dir / "taste/anchors.md").exists() and not (lib_dir / "taste/facts.json").exists()
    n = sum(len(v) for v in err.added.values())
    last = read(lib_dir / "log.md").strip().split("\n")[-1]
    assert last == f"2026-10-20 13:20 taste -> {n} lines added, 2 files written, 4 files not written; taste"


def test_cli_shows_the_lines_of_a_run_that_failed_part_way(lib_dir, monkeypatch):
    real = taste.write_plan
    monkeypatch.setattr(taste, "write_plan",
                        lambda plan: (_ for _ in ()).throw(OSError(5, "locked")) if plan.path.name == "vocabulary.md"
                        else real(plan))  # fmt: skip
    result = runner.invoke(cli.app, ["library", "taste", "--library", str(lib_dir), "--today", "2026-10-20", "--json"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False and out["written"] == MD_FILES[:3] and "taste/vocabulary.md" in out["error"]
    assert out["added"]["taste/lanes.md"][0].startswith("- [2026-10-20] 100-109 BPM")


def test_write_refuses_an_absolute_source(lib_dir, data):
    for source in ("/Users/dj/collection.xml", "D:/exports/x.xml", "C:\\x.xml", "\\\\nas\\x.xml", ""):
        with pytest.raises(libfolder.LibraryFolderError):
            taste.write(lib_dir, data, source=source, today=D1)
    assert not (lib_dir / "taste" / "lanes.md").exists()


def test_run_refuses_a_folder_without_library_yaml(tmp_path):
    folder = tmp_path / "not-a-library"
    folder.mkdir()
    with pytest.raises(taste.NotALibraryFolder):
        taste.run(folder, xml=fx.SAMPLE_XML, today=D1)
    assert list(folder.iterdir()) == []


def test_analysis_opens_no_write_session(lib_dir, tmp_path, monkeypatch):
    """R-341: no master.db session at all, no backup, nothing written outside taste/ and log.md."""

    def refuse(*args, **kwargs):
        raise AssertionError("analysis touched master.db")

    monkeypatch.setattr(safety, "open_db", refuse)
    monkeypatch.setattr(safety, "backup", refuse)
    before = snapshot(tmp_path)
    taste.run(lib_dir, today=D1)
    after = snapshot(tmp_path)
    changed = {p for p in after if before.get(p) != after[p]}
    assert changed == {f"dj-library/{rel}" for rel in ALL_FILES} | {"dj-library/log.md"}
    assert set(before) <= set(after)  # nothing removed; the export and the DJ's XML untouched


# -- the script and the CLI


def run_script(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=env)  # fmt: skip


def test_script(lib_dir, tmp_path):
    done = run_script("--library", str(lib_dir), "--today", "2026-10-20", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["ok"] is True and out["written"] == ALL_FILES and out["counts"]["lanes"] == 3
    first = out["counts"]["lines_added"]
    assert first == sum(len(v) for v in out["added"].values()) > 0

    again = json.loads(run_script("--library", str(lib_dir), "--today", "2026-10-20", cwd=tmp_path).stdout)
    assert again["counts"]["lines_added"] == 0

    done = run_script("--library", str(lib_dir), "--today", "2026-10-21", "--rebuild", cwd=tmp_path)
    rebuilt = json.loads(done.stdout)
    assert done.returncode == 0 and rebuilt["rebuild"] is True and rebuilt["counts"]["lines_added"] == first
    assert all(line.startswith("- [2026-10-21] ") for lines in rebuilt["added"].values() for line in lines)


def test_script_refuses_and_errors(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    done = run_script("--library", str(plain), cwd=tmp_path)
    assert done.returncode == 2 and json.loads(done.stdout)["ok"] is False
    assert "library.yaml" in json.loads(done.stdout)["refused"] and list(plain.iterdir()) == []

    empty = tmp_path / "dj-library"
    libfolder.scaffold(empty, device="mac", today=D1)
    done = run_script("--library", str(empty), cwd=tmp_path)  # scaffolded, no export yet
    assert done.returncode == 1 and "export" in json.loads(done.stdout)["error"].lower()
    done = run_script("--library", str(empty), "--today", "not-a-date", cwd=tmp_path)
    assert done.returncode == 1 and json.loads(done.stdout)["ok"] is False
    done = run_script(cwd=tmp_path)  # missing --library: an error (1), not a refusal (2)
    assert done.returncode == 1 and "--library" in json.loads(done.stdout)["error"]


def test_script_runs_without_engine_packages(lib_dir, tmp_path):
    code = textwrap.dedent(f"""
        import runpy, sys
        for name in ("pyrekordbox", "rapidfuzz", "httpx", "typer", "mcp"):
            sys.modules[name] = None
        sys.argv = ["taste.py", "--library", {str(lib_dir)!r}, "--today", "2026-10-20"]
        runpy.run_path({str(SCRIPT)!r}, run_name="__main__")
    """)
    env = dict(os.environ, PYTHONUTF8="1")
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=env)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["counts"]["clusters"] == 3


def test_cli_json(lib_dir):
    result = runner.invoke(cli.app, ["library", "taste", "--library", str(lib_dir), "--today", "2026-10-20", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["written"] == ALL_FILES and data["counts"]["lanes"] == 3
    assert data["added"]["taste/lanes.md"][0].startswith("- [2026-10-20] 100-109 BPM")

    text = runner.invoke(cli.app, ["library", "taste", "--library", str(lib_dir), "--today", "2026-10-20"])
    assert text.exit_code == 0 and text.output.startswith("taste: 0 lines added from exports/")

    rebuilt = runner.invoke(cli.app, ["library", "taste", "--library", str(lib_dir), "--rebuild", "--json"])
    assert rebuilt.exit_code == 0 and json.loads(rebuilt.output)["rebuild"] is True


def test_cli_text_caps_lines_and_refuses(lib_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(taste, "LOG_ENTRIES", 9)  # more than the 5 lines the text output shows
    result = runner.invoke(cli.app, ["library", "taste", "--library", str(lib_dir), "--today", "2026-10-20"])
    assert result.exit_code == 0
    assert "taste/labels-artists.md: +9" in result.output
    assert "... 4 more in taste/labels-artists.md" in result.output  # 9 added, 5 shown
    shown = bullets(read(lib_dir / "taste/labels-artists.md"), "## Log")
    assert all(f"  {line}" in result.output for line in shown[:5])  # the diff, as written
    assert shown[5] not in result.output
    plain = tmp_path / "plain"
    plain.mkdir()
    refused = runner.invoke(cli.app, ["library", "taste", "--library", str(plain)])
    assert refused.exit_code == 2
    bad = runner.invoke(cli.app, ["library", "taste", "--library", str(lib_dir), "--today", "20-10-2026"])
    assert bad.exit_code == 1


# -- the skill (R-301, R-332, R-341)

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


def test_skill_md():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    meta, body = yaml.safe_load(m.group(1)), m.group(2)
    assert meta["name"] == "dj-taste" and meta["description"].strip()
    assert "**Requirements:** R-301, R-302, R-331, R-332, R-341." in body
    assert "[shared/voice.md](../../shared/voice.md)" in body and "[shared/adhd.md](../../shared/adhd.md)" in body
    patterns = section(body, "## Patterns I read first")
    for pattern in ("Labels and artists", "BPM lanes per playlist", "Keys", "Co-occurrence",
                    "Ratings and play counts", "The DJ's own words"):  # fmt: skip
        assert pattern in patterns
    for needle in ("scripts/taste.py --library DIR", "dj library taste", "--rebuild", "explicit yes",
                   "never propose:", "never pair:", "key:veto:", "key:pair:", "taste/feedback.md", "R-341"):  # fmt: skip
        assert needle in body, needle
    heads = list(re.finditer(r"^## ", text, re.MULTILINE))
    assert text[heads[-1].start():] == CHECKLIST  # the canonical block, last
