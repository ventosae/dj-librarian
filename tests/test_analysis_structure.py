"""dj.analysis.structure and treeschema.from_library: dj-structure (R-321, R-322, R-301, R-302, R-341).

Every number asserted here was worked out by hand from tests/xml_fixtures.py (24 tracks, 3 folders,
8 playlists; the overlapping pair 1.2_peak / Gig 2025-03 Warehouse with Jaccard 5/9; the dump
"unsorted dump" with 16 tracks; the empty House/Deep/empty_ideas; orphans 23 and 24).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from itertools import combinations
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml
from typer.testing import CliRunner

from dj import cli, safety, treeschema
from dj import tree as tree_mod
from dj.analysis import structure as st
from dj.libfolder import LibraryFolder, LibraryFolderError, import_export, scaffold
from dj.model import Library, PlaylistNode, Track
from dj.readers.xml import read_xml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugin" / "skills" / "dj-structure" / "scripts" / "structure.py"
SKILL = REPO / "plugin" / "skills" / "dj-structure" / "SKILL.md"
TODAY = date(2026, 10, 20)
READ_AT = "2026-10-20T09:00:00+00:00"
EXPORT = "exports/2026-10-20-collection.xml"
PAIR = {"a": "House/1.2_peak", "b": "Gigs/Gig 2025-03 Warehouse", "jaccard": round(5 / 9, 3), "shared": 5}
REVEALS = [
    "8 playlists in 3 folders, 3 levels deep at most.",
    "3 of 8 playlist names share one pattern: word_word.",  # 1.2_peak is `word`: its number is left out
    "unsorted dump holds 16 tracks, 67% of the collection: a dump.",
    "House/1.2_peak and Gigs/Gig 2025-03 Warehouse share 5 tracks (overlap 0.56).",
    "2 tracks (8%) sit in no playlist; 1 playlist is empty (House/Deep/empty_ideas).",
]
SECTIONS = ["Shape", "Naming", "Sizes", "Overlap", "Orphans and empty", "Dumps", "What it reveals"]

runner = CliRunner()


@pytest.fixture(scope="module")
def lib() -> Library:
    return read_xml(fx.SAMPLE_XML, read_at=READ_AT)


@pytest.fixture(scope="module")
def facts(lib) -> dict:
    return st.facts(lib, today=TODAY)


@pytest.fixture
def folder(tmp_path) -> Path:
    """A scaffolded dj-library folder holding the fixture export as exports/2026-10-20-collection.xml."""
    root = tmp_path / "dj-library"
    scaffold(root, device="windows", today=TODAY)
    import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=TODAY)
    return root


@pytest.fixture
def sessions(monkeypatch):
    """Records every master.db session (write flag); the real open_db stays underneath."""
    real, log = safety.open_db, []

    @contextmanager
    def recording(write=False, db_path=None):
        log.append(write)
        with real(write=write, db_path=db_path) as db:
            yield db

    monkeypatch.setattr(safety, "open_db", recording)
    return log


def _db_library(tmp_path, monkeypatch, spec=None) -> Library:
    """The fixture as a master.db Library: read_db on a snapshot of stand-in files, with
    pyrekordbox replaced by tests/xml_fixtures.fake_db (as in tests/test_readers_db.py)."""
    from dj.readers.db import read_db

    live = fx.write_master_files(tmp_path / "Pioneer" / "rekordbox", spec)
    snapshots = tmp_path / "tmp"
    snapshots.mkdir(exist_ok=True)
    monkeypatch.setattr(tempfile, "tempdir", str(snapshots))  # the snapshot copy stays in tmp_path
    monkeypatch.setattr(safety, "_connect", lambda path, quiet=False: fx.fake_db(spec))
    return read_db(live, read_at=READ_AT)


def _structure_files(root: Path) -> dict[str, bytes]:
    return {name: (root / "structure" / name).read_bytes() for name in st.FILES}


def _section(md: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", md, re.MULTILINE | re.DOTALL)
    assert match, f"no section {title}"
    return match.group(1)


# -- facts on the fixture (R-321) --------------------------------------------------------------


def test_fixture_is_what_the_tests_assume(lib):
    assert lib.counts() == fx.EXPECTED_COUNTS
    assert [t.id for t in lib.orphans()] == fx.ORPHAN_IDS == ["23", "24"]


def test_depth_and_width(facts):
    assert facts["depth"] == {
        "max": 3,
        "mean": 2.0,  # (2 + 2 + 3 + 3 + 2 + 2 + 1 + 1) / 8
        "playlists_by_level": {"1": 2, "2": 4, "3": 2},
        "deepest": ["House/Deep/deep_rollers", "House/Deep/empty_ideas"],
    }
    # House holds 3, Deep 2, Gigs 2; four nodes at the top
    assert facts["width"] == {"top": 4, "folders": 3, "max": 3, "max_path": "House", "mean": 2.33}


def test_sizes(facts):
    sizes = facts["sizes"]
    assert (sizes["playlists"], sizes["min"], sizes["median"], sizes["max"]) == (8, 0, 6.0, 16)
    assert sizes["buckets"] == {"0": 1, "1-25": 7, "26-100": 0, "101-300": 0, "300+": 0}
    assert sizes["largest"][0] == {"path": "unsorted dump", "tracks": 16}
    assert len(sizes["largest"]) == 5


def test_empty_and_orphans(facts):
    assert facts["empty"] == {
        "count": 1, "paths": ["House/Deep/empty_ideas"], "folders": 0, "folder_paths": [],
        "dead": 0, "dead_paths": [],
    }  # fmt: skip
    orphans = facts["orphans"]
    assert (orphans["count"], orphans["share"], orphans["ids"]) == (2, round(2 / 24, 3), ["23", "24"])
    assert orphans["examples"] == [
        {"id": "23", "track": "Grid Saint - Pressure Vessel"},
        {"id": "24", "track": "Saffi Wren - Tape Hiss Lullaby"},
    ]


def test_overlap_pair_with_jaccard_five_ninths(facts):
    overlap = facts["overlap"]
    assert overlap["top"] == [PAIR]
    assert (overlap["count"], overlap["pairs_checked"], overlap["min_jaccard"]) == (1, 21, 0.5)  # 7 non-empty: 7*6/2
    assert overlap["near_duplicates"] == {"min_jaccard": 0.8, "count": 0, "top": []}
    # funk & disco 78-92 (tracks 1-7) sits entirely inside unsorted dump
    assert overlap["contained"] == {
        "count": 1, "pairs": 1, "top": [{"inner": "funk & disco 78-92", "outer": "unsorted dump", "tracks": 7}],
    }  # fmt: skip


def _ranges(lists: list[tuple[str, int, int]], tracks: int) -> Library:
    """Plain playlists holding tracks first..last, in a collection of tracks 1..tracks."""
    return Library(
        source="xml",
        tracks={str(i): Track(id=str(i)) for i in range(1, tracks + 1)},
        roots=tuple(
            PlaylistNode(f"p{k}", "playlist", name, track_ids=tuple(str(i) for i in range(first, last + 1)))
            for k, (name, first, last) in enumerate(lists)
        ),
    )


def test_a_playlist_inside_two_bigger_ones_counts_once():
    lib = _ranges([("warm", 1, 3), ("house crate", 1, 10), ("all", 1, 20), ("other", 30, 40)], 40)
    contained = st.facts(lib)["overlap"]["contained"]
    assert (contained["count"], contained["pairs"]) == (2, 3)  # warm and house crate; warm sits in both
    assert contained["top"] == [
        {"inner": "house crate", "outer": "all", "tracks": 10},
        {"inner": "warm", "outer": "all", "tracks": 3},
        {"inner": "warm", "outer": "house crate", "tracks": 3},
    ]
    md = st.render(st.facts(lib), source=EXPORT, today=TODAY)
    assert "2 playlists sit entirely inside a bigger one, for example house crate inside all." in md


def test_overlap_matches_a_brute_force_count(lib, facts):
    sets = {n.path_str: set(n.track_ids) for n in lib.playlists() if n.track_ids}
    brute = []
    for (a, sa), (b, sb) in combinations(sets.items(), 2):
        j = len(sa & sb) / len(sa | sb)
        if j >= 0.5:
            brute.append((a, b, round(j, 3), len(sa & sb)))
    assert brute == [(p["a"], p["b"], p["jaccard"], p["shared"]) for p in st.graph(lib)["overlaps"]]
    assert facts["overlap"]["pairs_checked"] == len(list(combinations(sets, 2)))


def test_the_dump(facts):
    dumps = facts["dumps"]
    assert dumps["count"] == 1
    assert dumps["top"] == [{"path": "unsorted dump", "tracks": 16, "distinct": 16, "share": round(16 / 24, 3)}]
    for part in ("300", "half", "25%", "median", "counted once"):
        assert part in dumps["rule"], part
    # Gig 2025-03 Warehouse (8 = 33%) and funk & disco 78-92 (7 = 29%) are over 25%, but not over
    # twice the median of the other playlists that hold tracks (6): no dumps


def test_naming(facts):
    naming = facts["naming"]
    # the leading number is left out: 1.1_warm_up -> word_word, 1.2_peak -> word
    assert (naming["names"], naming["dominant"], naming["dominant_count"], naming["dominant_share"]) == (
        8, "word_word", 3, 0.375,
    )  # fmt: skip
    assert naming["patterns"] == [
        {"pattern": "word_word", "count": 3, "example": "1.1_warm_up"},
        {"pattern": "Word Word", "count": 2, "example": "Gig 2025-03 Warehouse"},
        {"pattern": "word word", "count": 2, "example": "unsorted dump"},
        {"pattern": "word", "count": 1, "example": "1.2_peak"},
    ]
    assert naming["separators"] == {"underscore": 3, "dash": 0, "hyphen": 0, "space": 4, "none": 1}
    assert naming["cases"] == {"lower": 6, "Title": 2, "UPPER": 0, "Sentence": 0, "mixed": 0, "none": 0}
    assert naming["numbered"] == {"count": 2, "examples": ["1.1_warm_up", "1.2_peak"]}
    assert naming["dated"] == {"count": 2, "examples": ["Gig 2025-03 Warehouse", "Gig 2025-11 Rooftop"]}
    assert naming["top_tokens"] == [
        {"token": "deep", "count": 2}, {"token": "gig", "count": 2}, {"token": "disco", "count": 1},
        {"token": "dump", "count": 1}, {"token": "empty", "count": 1},
    ]  # fmt: skip
    assert naming["folders"] == {"names": 3, "dominant": "Word", "dominant_share": 1.0}
    assert naming["duplicates_renamed"] == []


@pytest.mark.parametrize(("name", "shape"), [
    ("1.1_warm_up", "word_word"),
    ("1.2_peak", "word"),  # a leading number is not a word
    ("01 Intro", "Word"),
    ("01 - Deep House", "Word Word"),
    ("3) closers", "word"),
    ("2025-03-14 Rooftop", "Word"),  # nor is a leading date
    ("1.1_", "123"),
    ("2000s house", "word word"),
    ("Gig 2025-03 Warehouse", "Word Word"),
    ("House", "Word"),
    ("techno", "word"),
    ("TECHNO BANGERS", "WORD WORD"),
    ("Deep house rollers", "Word word"),
    ("deep-house", "word-word"),
    ("House - Deep", "Word - Word"),
    ("DJ Sets", "Word Word"),
    ("DeepHouse", "wOrd"),
    ("2024", "123"),
    ("  Søndag på taget  ", "Word word"),
    ("Søndag på Taget", "wOrd wOrd"),
])  # fmt: skip
def test_name_patterns(name, shape):
    assert st.pattern(name) == shape


@pytest.mark.parametrize(("name", "numbered", "dated"), [
    ("1.1_warm_up", True, False),
    ("01 Intro", True, False),
    ("3) closers", True, False),
    ("Gig 2025-03 Warehouse", False, True),
    ("2025-03-14 Rooftop", False, True),
    ("Summer 2019", False, True),
    ("2000s house", False, False),
    ("funk & disco 78-92", False, False),
    ("100% vinyl", False, False),
])  # fmt: skip
def test_numbered_and_dated_names(name, numbered, dated):
    lib = Library(source="xml", roots=(PlaylistNode("1", "playlist", name),))
    naming = st.facts(lib)["naming"]
    assert (naming["numbered"]["count"], naming["dated"]["count"]) == (int(numbered), int(dated))


def test_smart_vs_plain_on_an_xml_export(facts):
    assert facts["smart_vs_plain"] == {
        "plain": 8, "smart": 0, "smart_share": 0.0, "smart_paths": [], "smart_tracks_listed": 0,
    }  # fmt: skip
    assert facts["notes"] == ["An XML export carries no smart playlists, so none are counted here."]


def test_facts_are_json_and_carry_no_location(facts):
    text = json.dumps(facts, ensure_ascii=False)
    assert json.loads(text) == facts
    assert "D:/" not in text and "//nas" not in text and "file://" not in text


# -- reveals (R-302: built only from the facts) -------------------------------------------------


def test_reveals_on_the_fixture(facts):
    assert facts["reveals"] == REVEALS
    assert st.reveals(facts) == REVEALS


def _busy_library() -> Library:
    """Every kind of reveal at once: folders, a near-copy, a dump, orphans, an empty playlist
    and a smart playlist read from master.db (rules, no tracks)."""
    tracks = {str(i): Track(id=str(i), artist="A", title=f"T{i}") for i in range(1, 41)}
    roots = (
        PlaylistNode("f", "folder", "Sets", children=(
            PlaylistNode("p1", "playlist", "warm", track_ids=("1", "2", "3", "4", "5")),
            PlaylistNode("p2", "playlist", "warm copy", track_ids=("1", "2", "3", "4", "5")),
            PlaylistNode("p3", "playlist", "nothing yet"),
        )),
        PlaylistNode("p4", "playlist", "everything", track_ids=tuple(str(i) for i in range(1, 31))),
        PlaylistNode("s1", "smart", "auto", rules=({"raw": "<NODE/>"},)),
    )  # fmt: skip
    return Library(source="db", tracks=tracks, roots=roots)


def test_reveals_never_exceed_five():
    f = st.facts(_busy_library())
    assert len(f["reveals"]) == 5
    assert f["reveals"][:2] == ["5 playlists (1 smart) in 1 folder, 2 levels deep at most.",
                                "3 of 5 playlist names follow one pattern: word."]
    assert all(isinstance(line, str) and 0 < len(line) <= 160 and "\n" not in line for line in f["reveals"])
    assert f["reveals"][2] == "everything holds 30 tracks, 75% of the collection: a dump."
    assert f["reveals"][3] == "1 pair of playlists is nearly the same: Sets/warm and Sets/warm copy share 5 tracks."
    assert f["notes"] and "smart" in f["notes"][0]


def test_an_empty_library(tmp_path):
    lib = Library(source="xml", tracks={"1": Track(id="1", title="Only")})
    f = st.facts(lib, today=TODAY)
    assert f["reveals"] == ["No playlists yet: all 1 track sit in the collection only."]
    assert f["sizes"]["median"] is None and f["depth"]["max"] == 0 and f["width"]["mean"] is None
    md = st.render(f, source=EXPORT, today=TODAY)
    assert md.startswith("# Structure\n") and "No playlist names yet." in md
    doc = treeschema.from_library(lib, today=TODAY)
    assert doc.nodes == () and treeschema.parse(yaml.safe_load(treeschema.dumps(doc))) == doc


# -- dumps: the rule ---------------------------------------------------------------------------


def _sized(sizes: list[int], tracks: int) -> Library:
    all_tracks = {str(i): Track(id=str(i)) for i in range(1, tracks + 1)}
    roots = tuple(
        PlaylistNode(f"p{k}", "playlist", f"list {k}", track_ids=tuple(str(i) for i in range(1, size + 1)))
        for k, size in enumerate(sizes)
    )
    return Library(source="xml", tracks=all_tracks, roots=roots)


@pytest.mark.parametrize(("sizes", "tracks", "dumps"), [
    ([301, 50, 50, 50], 1000, ["list 0"]),  # more than 300 tracks: a dump at any share
    ([300, 200, 200, 200], 1000, []),  # 300 is not more than 300, nor more than 2 x median 200
    ([30, 10, 10, 10], 100, ["list 0"]),  # 30% of the collection and more than 2 x median 10
    ([30, 20, 20, 20], 100, []),  # 30% of the collection, but not more than 2 x median 20
    ([25, 5, 5, 5], 100, []),  # exactly 25% is not more than 25%
    # small libraries: more than half the collection is always a dump
    ([200, 10], 250, ["list 0"]),  # 80%, though the median of both is 105
    ([280, 150, 140], 290, ["list 0", "list 1"]),  # 97% and 52%; 140 is 48%
    ([250], 280, ["list 0"]),  # the only playlist, 89%
    ([150], 300, []),  # exactly half is not more than half, and there is nothing to compare with
    ([30], 100, []),  # 30%, nothing to compare with
    # the median is over the OTHER playlists that hold tracks: empty ones do not pull it down
    ([30, 16, 0, 0, 0, 0], 100, []),  # 30 is not more than 2 x 16 (all six: median 0)
    ([26, 12, 0, 0], 100, ["list 0"]),  # 26% and more than 2 x 12
    ([290, 0, 0, 0], 300, ["list 0"]),  # 97%
])  # fmt: skip
def test_dump_rule(sizes, tracks, dumps):
    assert [d["path"] for d in st.facts(_sized(sizes, tracks))["dumps"]["top"]] == dumps


def test_a_dump_share_counts_each_collection_track_once():
    tracks = {str(i): Track(id=str(i)) for i in range(1, 11)}
    loop = PlaylistNode("p1", "playlist", "loop", track_ids=("1", "2") * 10)  # 20 entries, 2 tracks
    others = (PlaylistNode("p2", "playlist", "x", track_ids=("3",)), PlaylistNode("p3", "playlist", "y", track_ids=("4",)))
    assert st.facts(Library(source="xml", tracks=tracks, roots=(loop, *others)))["dumps"]["count"] == 0  # 20%

    # a real catch-all with repeats and an entry the collection lost: 25 entries, 8 of 10 tracks
    big = PlaylistNode("p1", "playlist", "big", track_ids=tuple(str(i) for i in range(1, 9)) * 3 + ("99",))
    f = st.facts(Library(source="xml", tracks=tracks, roots=(big, *others)))
    assert f["dumps"]["top"] == [{"path": "big", "tracks": 25, "distinct": 8, "share": 0.8}]
    assert "big holds 25 tracks, 80% of the collection: a dump." in f["reveals"]
    assert all(d["share"] <= 1 for d in f["dumps"]["top"])


# -- graph -------------------------------------------------------------------------------------


def test_graph_is_consistent_with_the_tree(lib, facts):
    g = st.graph(lib)
    assert set(g) == {"nodes", "edges", "overlaps"}
    nodes = {n["id"]: n for n in g["nodes"]}
    assert [n["id"] for n in g["nodes"]] == [n.path_str for n in lib.walk()]  # tree order, ids = paths
    assert all(n["id"] == n["path"] and n["depth"] == len(n["path"].split("/")) for n in g["nodes"])
    expected_edges = [
        {"source": "/".join(n.path[:-1]), "target": n.path_str} for n in lib.walk() if len(n.path) > 1
    ]
    assert g["edges"] == expected_edges
    assert len(g["edges"]) == len(g["nodes"]) - len(lib.roots)
    assert all(nodes[e["source"]]["kind"] == "folder" for e in g["edges"])
    for node in lib.walk():
        if node.kind == "playlist":
            assert nodes[node.path_str]["tracks"] == len(node.track_ids)
    # distinct tracks under each folder
    assert (nodes["House"]["tracks"], nodes["House/Deep"]["tracks"], nodes["Gigs"]["tracks"]) == (10, 4, 12)
    assert g["overlaps"] == [PAIR] == facts["overlap"]["top"]
    assert json.loads(json.dumps(g)) == g


# -- current-tree.yaml (R-322) -----------------------------------------------------------------


def test_from_library_on_the_xml_fixture(lib):
    doc = treeschema.from_library(lib, today=TODAY)
    assert doc.meta == {"source": "xml", "generated": "2026-10-20"}
    assert [(path, node.kind) for path, node in treeschema.walk(doc)] == [(n.path, n.kind) for n in lib.walk()]
    assert all(node.fill_from == () and node.rules is None for _, node in treeschema.walk(doc))
    assert treeschema.from_library(lib) == doc  # no today: the date the Library was read
    assert treeschema.from_library(lib, today=date(2027, 1, 2)).meta["generated"] == "2027-01-02"


def test_current_tree_yaml_round_trips(folder, lib):
    st.run(folder, today=TODAY)
    path = folder / "structure" / "current-tree.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.startswith(
        f"# Your rekordbox tree as code, generated from {EXPORT} on 2026-10-20.\n"
        "# Edit freely: dj never writes this file back to rekordbox.\n"
    )
    assert treeschema.load(path) == treeschema.from_library(lib, today=TODAY)


def test_current_tree_yaml_also_feeds_dj_tree(folder, lib, tmp_path):
    # The file uses the mapping form ({source, generated, tree}), which dj.tree.load_tree does not
    # read (it takes the bare-list bases shape). So: through treeschema.to_tree_nodes, and through
    # load_tree on the file's own `tree:` list.
    st.run(folder, today=TODAY)
    path = folder / "structure" / "current-tree.yaml"
    via_schema = treeschema.to_tree_nodes(treeschema.load(path))
    bare = tmp_path / "bare-tree.yaml"
    bare.write_text(yaml.safe_dump(yaml.safe_load(path.read_text(encoding="utf-8"))["tree"]), encoding="utf-8")
    via_tree = tree_mod.load_tree(bare)

    def shape(nodes):
        return [(n.kind, n.name, shape(n.children)) for n in nodes]

    assert shape(via_schema) == shape(via_tree)
    assert [kind for kind, _, _ in shape(via_tree)] == ["folder", "folder", "playlist", "playlist"]


def test_from_library_on_a_master_db_library_keeps_smart_rules_raw(tmp_path, monkeypatch):
    lib = _db_library(tmp_path, monkeypatch)
    assert lib.source == "db" and lib.counts()["smart"] == 1
    doc = treeschema.from_library(lib, today=TODAY)
    smart = [node for _, node in treeschema.walk(doc) if node.kind == "smart"]
    assert [(n.name, n.rules_raw, n.rules) for n in smart] == [("All Techno", fx.SMART_RAW, None)]
    assert doc.meta == {"source": "db", "generated": "2026-10-20"}
    assert treeschema.parse(yaml.safe_load(treeschema.dumps(doc))) == doc
    out = tmp_path / "current-tree.yaml"
    treeschema.dump(doc, out)
    assert treeschema.load(out) == doc
    with pytest.raises(treeschema.TreeSchemaError, match="rules_raw only"):
        treeschema.to_tree_nodes(doc)  # dj tree cannot create it: v1 rules cannot say it


def test_facts_on_a_master_db_library(tmp_path, monkeypatch):
    f = st.facts(_db_library(tmp_path, monkeypatch))
    assert f["smart_vs_plain"]["smart"] == 1 and f["smart_vs_plain"]["smart_paths"] == ["All Techno"]
    assert f["smart_vs_plain"]["smart_tracks_listed"] == 0
    assert f["sizes"]["playlists"] == 8  # the smart playlist lists no tracks: not sized
    assert f["orphans"]["ids"] == ["23", "24"]  # 23 only matches the smart rule (DB_NOTES)
    assert "smart" in f["notes"][0] and "orphan" in f["notes"][0]
    assert f["reveals"][:2] == [
        "9 playlists (1 smart) in 3 folders, 3 levels deep at most.",
        "3 of 9 playlist names share one pattern: word_word.",  # ties with Word Word: first in the tree
    ]
    nodes = {n["id"]: n for n in st.graph(_db_library(tmp_path, monkeypatch))["nodes"]}
    assert nodes["All Techno"] == {
        "id": "All Techno", "path": "All Techno", "name": "All Techno", "kind": "smart", "tracks": None, "depth": 1,
    }  # fmt: skip


def test_empty_smart_rules_still_round_trip():
    lib = Library(source="db", roots=(PlaylistNode("s", "smart", "blank", rules=({"raw": ""},)),))
    doc = treeschema.from_library(lib, today=TODAY)
    assert doc.nodes[0].rules_raw == treeschema.NO_RULES
    assert treeschema.parse(yaml.safe_load(treeschema.dumps(doc))) == doc


# -- same-name siblings ------------------------------------------------------------------------


@pytest.mark.parametrize(("names", "expected"), [
    (["a", "b"], ["a", "b"]),
    (["Warm", "Warm"], ["Warm", "Warm (2)"]),
    (["Warm", "warm", " Warm ", "Warm (2)"], ["Warm", "warm (3)", "Warm (4)", "Warm (2)"]),
    (["", "  ", "x"], ["(unnamed)", "(unnamed) (2)", "x"]),
    ([" Deep ", "deep"], ["Deep", "deep (2)"]),
])  # fmt: skip
def test_level_names(names, expected):
    assert treeschema.level_names(names) == expected
    assert treeschema.level_names(names) == treeschema.level_names(list(names))  # deterministic


def _spec_with_duplicates() -> dict:
    spec = fx.spec_copy()
    house = spec["tree"][0]["children"]
    house.append({"kind": "playlist", "name": "1.2_peak", "tracks": ["9", "11", "12", "13", "14", "15"]})
    house.append({"kind": "playlist", "name": "deep", "tracks": ["10"]})  # same as the folder "Deep"
    return spec


def test_duplicate_sibling_names_are_made_unique(tmp_path):
    xml = fx.write_xml(tmp_path / "dupes.xml", _spec_with_duplicates())
    lib = read_xml(xml, read_at=READ_AT)
    doc = treeschema.from_library(lib, today=TODAY)
    house = [node.name for node in doc.nodes[0].children]
    assert house == ["1.1_warm_up", "1.2_peak", "Deep", "1.2_peak (2)", "deep (2)"]
    assert treeschema.parse(yaml.safe_load(treeschema.dumps(doc))) == doc

    f = st.facts(lib)
    assert f["naming"]["duplicates_renamed"] == [
        {"path": "House/1.2_peak", "renamed": "House/1.2_peak (2)"},
        {"path": "House/deep", "renamed": "House/deep (2)"},
    ]
    # the copy is a near-duplicate of the original, and both overlap the gig set
    assert f["overlap"]["near_duplicates"]["top"] == [
        {"a": "House/1.2_peak", "b": "House/1.2_peak (2)", "jaccard": 1.0, "shared": 6},
    ]
    assert [(p["a"], p["b"]) for p in f["overlap"]["top"]] == [
        ("House/1.2_peak", "House/1.2_peak (2)"),
        ("House/1.2_peak", "Gigs/Gig 2025-03 Warehouse"),
        ("House/1.2_peak (2)", "Gigs/Gig 2025-03 Warehouse"),
    ]
    ids = [n["id"] for n in st.graph(lib)["nodes"]]
    assert len(ids) == len(set(ids)) and "House/1.2_peak (2)" in ids


def test_duplicates_round_trip_through_run(tmp_path):
    root = tmp_path / "dj-library"
    scaffold(root, device="mac", today=TODAY)
    import_export(root, fx.write_xml(tmp_path / "dupes.xml", _spec_with_duplicates()), today=TODAY)
    st.run(root, today=TODAY)
    lib = read_xml(root / EXPORT, read_at=READ_AT)
    assert treeschema.load(root / "structure" / "current-tree.yaml") == treeschema.from_library(lib, today=TODAY)
    md = (root / "structure" / "analysis.md").read_text(encoding="utf-8")
    assert "| Same name twice | 2, written as House/1.2_peak (2) in current-tree.yaml |" in md


def test_a_slash_in_a_name_cannot_collide_two_paths():
    roots = (
        PlaylistNode("1", "playlist", "A/B", track_ids=("1",)),
        PlaylistNode("2", "folder", "A", children=(PlaylistNode("3", "playlist", "B", track_ids=("1",)),)),
    )
    lib = Library(source="xml", tracks={"1": Track(id="1")}, roots=roots)
    ids = [n["id"] for n in st.graph(lib)["nodes"]]
    assert ids == ["A/B", "A", "A/B #2"]


# -- write and run -----------------------------------------------------------------------------


def test_run_writes_the_four_files_and_one_log_line(folder):
    result = st.run(folder, today=TODAY)
    assert result["written"] == [
        "structure/analysis.md", "structure/graph.json", "structure/facts.json", "structure/current-tree.yaml",
    ]  # fmt: skip
    assert result["kept"] == [] and result["source"] == EXPORT
    assert result["counts"] == fx.EXPECTED_COUNTS and result["reveals"] == REVEALS
    assert (result["depth"], result["overlaps"], result["dumps"], result["orphans"], result["empty"]) == (3, 1, 1, 2, 1)
    log = (folder / "log.md").read_text(encoding="utf-8").splitlines()
    assert log[-1] == result["log"]
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} structure -> 8 playlists, 3 folders, 4 files; structure/analysis\.md",
        log[-1],
    )
    assert json.loads((folder / "structure" / "facts.json").read_text(encoding="utf-8")) == {"export": EXPORT} | st.facts(
        read_xml(folder / EXPORT), today=TODAY
    )
    assert json.loads((folder / "structure" / "graph.json").read_text(encoding="utf-8")) == st.graph(
        read_xml(folder / EXPORT)
    )


def test_analysis_md(folder):
    st.run(folder, today=TODAY)
    md = (folder / "structure" / "analysis.md").read_text(encoding="utf-8")
    lines = md.split("\n")
    assert lines[0] == "# Structure" and lines[1] == ""
    assert lines[2] == f"> Measured by code: dj.analysis.structure from {EXPORT}, 2026-10-20."
    assert re.findall(r"^## (.+)$", md, re.MULTILINE) == SECTIONS
    for title in SECTIONS:
        body = _section(md, title)
        rows = [line for line in body.split("\n") if line.startswith("| ") and not line.startswith("| Measure")]
        table_rows = [r for r in rows if not re.match(r"^\| (Tracks|Playlist) \|", r)]
        bullets = [line for line in body.split("\n") if re.match(r"^\s*(?:[-*+]|\d+[.)])\s", line)]
        assert len(table_rows) <= 5 and len(bullets) <= 5, title
    assert "| House/1.2_peak | Gigs/Gig 2025-03 Warehouse | 5 | 0.56 |" in _section(md, "Overlap")
    assert "| unsorted dump | 16 | 67% |" in _section(md, "Dumps")
    assert "| Empty playlists | 1: House/Deep/empty_ideas |" in _section(md, "Orphans and empty")
    assert "| Tracks in no playlist | 2 (8%) |" in _section(md, "Orphans and empty")
    assert "word_word: 3 of 8 playlist names (38%)" in _section(md, "Naming")
    assert "| Most used separators and case | space 4, underscore 3; lower 6, Title 2 |" in _section(md, "Naming")
    assert "| Depth | 3 levels at most; playlists sit 2 deep on average |" in _section(md, "Shape")
    assert [line[2:] for line in _section(md, "What it reveals").split("\n") if line.startswith("- ")] == REVEALS
    for word in ("node", "schema", "payload", "amazing", "seamless", "simply"):
        assert not re.search(rf"\b{word}\b", md, re.IGNORECASE), word


def test_naming_row_shows_the_two_most_used_separators_and_cases():
    names = ["a_b", "c - d", "e-f", "g h", "i j", "K L", "MN OP", "Qr st", "aBc", "x", "2024", "u v"]
    roots = tuple(PlaylistNode(f"p{k}", "playlist", name, track_ids=("1",)) for k, name in enumerate(names))
    f = st.facts(Library(source="xml", tracks={"1": Track(id="1")}, roots=roots))
    md = st.render(f, source=EXPORT, today=TODAY)
    row = next(line for line in md.split("\n") if line.startswith("| Most used separators and case |"))
    assert row == "| Most used separators and case | space 6, none 3; lower 7, Title 1 |"  # 4 items, not 11
    # the full counts stay in facts.json
    assert f["naming"]["separators"] == {"underscore": 1, "dash": 1, "hyphen": 1, "space": 6, "none": 3}
    assert f["naming"]["cases"] == {"lower": 7, "Title": 1, "UPPER": 1, "Sentence": 1, "mixed": 1, "none": 1}


def test_a_line_break_in_a_name_stays_inside_its_line():
    # an XML Name attribute can hold &#10;: a name must never start a new MD line
    roots = (
        PlaylistNode("p1", "playlist", "big\n## Fake section\n- bullet", track_ids=tuple(str(i) for i in range(1, 20))),
        PlaylistNode("p2", "playlist", "e\nf"),
        PlaylistNode("p3", "playlist", "small\r\nset", track_ids=("1", "2")),
    )  # fmt: skip
    lib = Library(source="xml", tracks={str(i): Track(id=str(i)) for i in range(1, 25)}, roots=roots)
    f = st.facts(lib)
    assert f["dumps"]["count"] == 1 and f["overlap"]["contained"]["count"] == 1 and f["empty"]["count"] == 1
    assert all("\n" not in line and "\r" not in line for line in f["reveals"])
    assert "big ## Fake section - bullet holds 19 tracks, 79% of the collection: a dump." in f["reveals"]
    assert "small set sits entirely inside big ## Fake section - bullet." in f["reveals"]
    md = st.render(f, source=EXPORT, today=TODAY)
    assert re.findall(r"^## (.+)$", md, re.MULTILINE) == SECTIONS
    assert not re.search(r"^(?:- bullet|f|set)$", md, re.MULTILINE)
    reveals = [line for line in _section(md, "What it reveals").split("\n") if line.startswith("- ")]
    assert len(reveals) == len(f["reveals"]) <= 5
    assert "largest 19 tracks (big ## Fake section - bullet)." in _section(md, "Sizes")


def test_two_runs_are_byte_identical(folder, tmp_path):
    st.run(folder, today=TODAY)
    first = _structure_files(folder)
    st.run(folder, today=TODAY)
    assert _structure_files(folder) == first
    # the same export in another folder elsewhere: the same bytes (nothing machine-specific)
    other = tmp_path / "elsewhere" / "lib"
    scaffold(other, device="mac", today=TODAY)
    import_export(other, folder / EXPORT, today=TODAY)
    st.run(other, today=TODAY)
    assert _structure_files(other) == first
    assert all(text.endswith(b"\n") and b"\r\n" not in text for text in first.values())


def test_no_absolute_paths_in_written_files(folder, tmp_path):
    (tmp_path / "outside").mkdir()
    xml_outside = fx.write_xml(tmp_path / "outside" / "my export.xml")
    st.run(folder, xml=xml_outside, today=TODAY)
    for name, data in _structure_files(folder).items():
        text = data.decode("utf-8")
        for needle in (str(tmp_path), tmp_path.as_posix(), "D:/", "/Users/", "//nas", "file://", "C:\\"):
            assert needle not in text, (name, needle)
    tree_text = (folder / "structure" / "current-tree.yaml").read_text(encoding="utf-8")
    assert "generated from my export.xml on" in tree_text  # outside the folder: the file name only
    log = (folder / "log.md").read_text(encoding="utf-8")
    assert str(tmp_path) not in log and tmp_path.as_posix() not in log


def test_source_label(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    assert st.source_label(root, root / "exports" / "a.xml") == "exports/a.xml"
    assert st.source_label(root, tmp_path / "elsewhere" / "b.xml") == "b.xml"
    assert st.source_label(root, "exports/c.xml") == "exports/c.xml"
    assert st.source_label(root, "D:/Music/export.xml") == "export.xml"  # Windows path, any OS
    assert st.source_label(root, "/Users/dj/export.xml") == "export.xml"


def test_write_turns_an_absolute_source_into_a_relative_one(folder, lib):
    paths = st.write(
        LibraryFolder(folder), st.facts(lib), st.graph(lib), treeschema.from_library(lib, today=TODAY),
        source=str((folder / EXPORT).resolve()), today=TODAY,
    )  # fmt: skip
    assert [p.name for p in paths] == list(st.FILES)
    md = (folder / "structure" / "analysis.md").read_text(encoding="utf-8")
    assert f"from {EXPORT}, 2026-10-20." in md


def test_an_edited_tree_is_kept_before_the_next_run(folder):
    tree = folder / "structure" / "current-tree.yaml"
    st.run(folder, today=TODAY)
    generated = tree.read_bytes()
    edited = tree.read_text(encoding="utf-8").replace("playlist: unsorted dump", "playlist: to sort")
    assert edited.encode("utf-8") != generated
    tree.write_text(edited, encoding="utf-8", newline="\n")

    result = st.run(folder, today=TODAY)
    assert result["kept"] == ["structure/current-tree.edited-2026-10-20.yaml"]
    assert (folder / result["kept"][0]).read_text(encoding="utf-8") == edited
    assert tree.read_bytes() == generated
    assert re.search(r"structure -> 8 playlists, 3 folders, 5 files;", result["log"])

    assert st.run(folder, today=TODAY)["kept"] == []  # untouched since: no copy
    sketch = "- playlist: my own sketch\r\n- playlist: café\r\n".encode("cp1252")  # hand-made: CRLF, not UTF-8
    tree.write_bytes(sketch)
    assert st.run(folder, today=TODAY)["kept"] == ["structure/current-tree.edited-2026-10-20-2.yaml"]
    assert (folder / "structure" / "current-tree.edited-2026-10-20-2.yaml").read_bytes() == sketch  # byte for byte
    assert (folder / "structure" / "current-tree.edited-2026-10-20.yaml").read_text(encoding="utf-8") == edited


@pytest.mark.parametrize("edit", [
    lambda text: "# my notes: split the dump by decade\n" + text,  # a comment on top
    lambda text: text.replace("# Edit freely", "# Edit freely (I did)", 1),  # a header line changed
    lambda text: text.replace("\n", "\r\n"),  # saved by an editor with CRLF line ends
    lambda text: text.replace(  # a note in the first line, which keeps the line's shape
        f"generated from {EXPORT} on", "generated from MY NOTE: split Deep into Sunday sets on", 1
    ),
])  # fmt: skip
def test_any_change_to_the_tree_file_counts_as_an_edit(folder, edit):
    st.run(folder, today=TODAY)
    tree = folder / "structure" / "current-tree.yaml"
    edited = edit(tree.read_bytes().decode("utf-8")).encode("utf-8")
    tree.write_bytes(edited)
    result = st.run(folder, today=TODAY)
    assert result["kept"] == ["structure/current-tree.edited-2026-10-20.yaml"]
    assert (folder / result["kept"][0]).read_bytes() == edited


def test_a_note_in_the_first_line_is_kept(folder):
    # the first line keeps its shape, so only the fingerprint (header and body) can tell
    st.run(folder, today=TODAY)
    tree = folder / "structure" / "current-tree.yaml"
    lines = tree.read_text(encoding="utf-8").split("\n")
    lines[0] = "# Your rekordbox tree as code, generated from MY NOTE: split Deep into Sunday sets on 2026-10-20."
    assert st._HEADER_FIRST.match(lines[0])
    tree.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    result = st.run(folder, today=TODAY)
    assert result["kept"] == ["structure/current-tree.edited-2026-10-20.yaml"]
    assert "MY NOTE: split Deep" in (folder / result["kept"][0]).read_text(encoding="utf-8")
    assert "MY NOTE" not in tree.read_text(encoding="utf-8")


def test_a_new_export_is_not_mistaken_for_an_edit(folder, tmp_path):
    st.run(folder, today=TODAY)
    spec = fx.spec_copy()
    spec["tree"] = [n for n in spec["tree"] if n["name"] != "funk & disco 78-92"]
    result = st.run(folder, xml=fx.write_xml(tmp_path / "newer.xml", spec), today=TODAY)
    assert result["kept"] == []
    names = [node.name for node in treeschema.load(folder / "structure" / "current-tree.yaml").nodes]
    assert "funk & disco 78-92" not in names


def test_run_errors(tmp_path):
    with pytest.raises(LibraryFolderError, match="not found"):
        st.run(tmp_path / "missing", today=TODAY)
    root = tmp_path / "lib"
    scaffold(root, device="mac", today=TODAY)
    with pytest.raises(LibraryFolderError, match="No export"):
        st.run(root, today=TODAY)
    assert not (root / "structure" / "analysis.md").exists()


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_folder_that_is_not_a_library_is_refused_and_left_alone(tmp_path):
    # a wrong --library with --xml: no structure/, no log.md line, nothing of the DJ's overwritten
    music = tmp_path / "Music"
    (music / "structure").mkdir(parents=True)
    (music / "my-notes.txt").write_text("mine", encoding="utf-8")
    (music / "log.md").write_text("my own notes", encoding="utf-8")
    (music / "structure" / "analysis.md").write_text("my essay on structure", encoding="utf-8")
    before = _files(music)
    xml = fx.write_xml(tmp_path / "collection.xml")

    with pytest.raises(LibraryFolderError, match="not a dj-library folder .*dj-start"):
        st.run(music, xml=xml, today=TODAY)
    lib = read_xml(xml)
    with pytest.raises(LibraryFolderError, match="not a dj-library folder"):
        st.write(music, st.facts(lib), st.graph(lib), treeschema.from_library(lib), source="collection.xml", today=TODAY)
    cli_result = runner.invoke(cli.app, ["library", "structure", "--library", str(music), "--xml", str(xml)])
    assert cli_result.exit_code == 1 and "not a dj-library folder" in cli_result.stderr
    done = _script("--library", str(music), "--xml", str(xml), cwd=tmp_path)
    assert done.returncode == 1 and "not a dj-library folder" in json.loads(done.stdout)["error"]
    assert _files(music) == before


def test_an_invalid_library_yaml_is_refused(folder):
    (folder / "library.yaml").write_text("device: toaster\n", encoding="utf-8")
    before = _files(folder)
    with pytest.raises(LibraryFolderError, match="library.yaml is not valid"):
        st.run(folder, today=TODAY)
    assert _files(folder) == before


# -- R-341: analysis never writes to rekordbox -------------------------------------------------


def test_analysis_opens_no_db_session(folder, sessions, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("dj-structure looked for rekordbox")

    monkeypatch.setattr(safety, "rekordbox_running", refuse)
    st.run(folder, today=TODAY)
    result = runner.invoke(cli.app, ["library", "structure", "--library", str(folder), "--today", "2026-10-20"])
    assert result.exit_code == 0, result.output
    assert sessions == []  # no master.db session at all, read or write


def test_structure_module_has_no_write_calls():
    source = (REPO / "src" / "dj" / "analysis" / "structure.py").read_text(encoding="utf-8")
    for call in ("open_db", "commit(", "create_playlist", "add_to_playlist", "mutagen", "spotify", "pyrekordbox"):
        assert call not in source, call


# -- CLI and script ----------------------------------------------------------------------------


def test_cli_json(folder):
    result = runner.invoke(
        cli.app, ["library", "structure", "--library", str(folder), "--today", "2026-10-20", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["written"][0] == "structure/analysis.md" and data["reveals"] == REVEALS
    assert data["source"] == EXPORT


def test_cli_text_and_the_configured_folder(folder, monkeypatch):
    monkeypatch.setenv("DJ_LIBRARY", str(folder))
    result = runner.invoke(cli.app, ["library", "structure", "--today", "2026-10-20"])
    assert result.exit_code == 0, result.output
    assert "structure/current-tree.yaml" in result.stdout
    assert "Nothing was written to rekordbox." in result.stdout
    assert REVEALS[0] in result.stdout


def test_cli_errors(folder, tmp_path):
    bad_date = runner.invoke(cli.app, ["library", "structure", "--library", str(folder), "--today", "20-10-2026"])
    assert bad_date.exit_code == 1 and "ERROR" in bad_date.stderr
    no_export = tmp_path / "empty-lib"
    scaffold(no_export, device="mac", today=TODAY)
    missing = runner.invoke(cli.app, ["library", "structure", "--library", str(no_export)])
    assert missing.exit_code == 1 and "No export" in missing.stderr


def _script(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        timeout=120,
    )  # fmt: skip


def test_script_by_subprocess(folder, tmp_path):
    done = _script("--library", str(folder), "--today", "2026-10-20", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.strip().split("\n")
    assert len(lines) == 1  # one JSON object
    data = json.loads(lines[0])
    assert data["ok"] is True and data["reveals"] == REVEALS and data["source"] == EXPORT
    assert all((folder / path).is_file() for path in data["written"])


def test_script_errors_are_one_json_object_and_exit_1(tmp_path):
    root = tmp_path / "lib"
    scaffold(root, device="mac", today=TODAY)
    done = _script("--library", str(root), cwd=tmp_path)
    assert done.returncode == 1
    assert json.loads(done.stdout) == {"ok": False, "error": json.loads(done.stdout)["error"]}
    assert "No export" in json.loads(done.stdout)["error"]
    usage = _script(cwd=tmp_path)  # --library missing
    assert usage.returncode == 1 and json.loads(usage.stdout)["ok"] is False


def test_script_shim_points_at_the_repo_src():
    assert (SCRIPT.resolve().parents[4] / "src" / "dj" / "analysis" / "structure.py").is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "    import dj  # noqa: F401\n" in text  # an importable dj first (engine venv or PyPI)
    assert '(_here / "../../../../src", _here / "../../../vendor")' in text  # then the clone, then the zip (D-22)


def test_script_runs_without_the_engine_packages(folder):
    # Door 1: the script and everything it imports work with pyrekordbox, typer & co. blocked.
    from test_door1_imports import run_blocked

    done = run_blocked(f"""
        import runpy, sys
        sys.argv = ["structure.py", "--library", {str(folder)!r}, "--today", "2026-10-20"]
        try:
            runpy.run_path({str(SCRIPT)!r}, run_name="__main__")
        except SystemExit as exc:
            assert exc.code == 0, exc.code
        leaked = [n for n in ("pyrekordbox", "rapidfuzz", "httpx", "typer", "mcp") if sys.modules.get(n)]
        assert not leaked, leaked
    """)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.strip().split("\n")[-1])["ok"] is True


# -- the skill ---------------------------------------------------------------------------------


def test_skill_md():
    text = SKILL.read_text(encoding="utf-8").replace("\r\n", "\n")
    meta = yaml.safe_load(re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL).group(1))
    assert meta["name"] == "dj-structure" and meta["description"].strip()
    assert "**Requirements:** R-301, R-302, R-321, R-322, R-341." in text
    assert "](../../shared/voice.md)" in text and "](../../shared/adhd.md)" in text
    patterns = _section(text, "Patterns I read first")
    for topic in ("Depth and width", "Naming conventions", "sizes", "Overlap", "Orphans", "dumps", "smart vs plain"):
        assert topic in patterns, topic
    assert "scripts/structure.py --library" in text and "dj library structure" in text
    assert "current-tree.yaml" in text and "R-341" in _section(text, "Never")
    assert re.findall(r"^## (.+)$", text, re.MULTILINE)[-1] == "Pre-send checklist"
    assert text.rstrip("\n").endswith(
        "- [ ] Nothing was written to rekordbox, Spotify or audio files without a preview and an explicit yes."
    )
