"""dj.analysis.proposals (W-17): two or three named restructure proposals (R-404, R-405).

On the synthetic library (tests/xml_fixtures.py) and variants of it that make each family win:
2-3 proposals, valid unique slugs, every `from` a real playlist path of the library (never a
" (2)" name), exact triggers, where every playlist lands, the cost formula, the picking rules,
determinism, and structure/proposals.yaml (create-only copy of an edited file)."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml

from dj import libfolder, safety, treeschema
from dj.analysis import common, profile, structure, taste
from dj.analysis import proposals as P
from dj.model import Library, PlaylistNode, Track
from dj.readers.db import read_db
from dj.readers.xml import read_xml

DAY = date(2026, 10, 20)
EXPORT = "exports/2026-10-20-collection.xml"
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# -- library variants ---------------------------------------------------------------------------


def renamed(spec: dict, names: dict[str, str]) -> dict:
    """A copy of `spec` with tree nodes renamed (old name -> new name, any level)."""
    out = fx.spec_copy(spec)

    def visit(nodes: list[dict]) -> None:
        for node in nodes:
            node["name"] = names.get(node["name"], node["name"])
            visit(node.get("children", []))

    visit(out["tree"])
    return out


def regenred(spec: dict, genres: dict[str, str]) -> dict:
    out = fx.spec_copy(spec)
    for track in out["tracks"]:
        track["genre"] = genres.get(track["id"], track["genre"])
    return out


def facets_spec() -> dict:
    """No genre-named folders, no gig names, 9 genres, the dump and the overlap kept: facets wins."""
    spec = renamed(fx.SPEC, {
        "House": "Crates", "1.1_warm_up": "warm_up", "1.2_peak": "peak", "Deep": "Rollers",
        "deep_rollers": "rollers_a", "Gigs": "Misc", "Gig 2025-03 Warehouse": "Warehouse mix",
        "Gig 2025-11 Rooftop": "Rooftop mix", "funk & disco 78-92": "old stuff",
    })  # fmt: skip
    return regenred(spec, {"5": "Soul", "7": "Soul", "6": "Boogie", "24": "Boogie", "14": "Garage",
                           "15": "Garage", "20": "Electro", "23": "Electro"})  # fmt: skip


def gig_spec() -> dict:
    """Dated and venue-like names almost everywhere: gig-first wins."""
    return renamed(fx.SPEC, {
        "House": "Residencies", "1.1_warm_up": "Fabric 2024-05", "1.2_peak": "Fabric 2024-09",
        "Deep": "Nights", "deep_rollers": "Night @ Rooftop", "empty_ideas": "2023 sets",
        "funk & disco 78-92": "Boiler Room 2022",
    })  # fmt: skip


def with_playlist(spec: dict, playlist: dict, folder: str | None = None) -> dict:
    out = fx.spec_copy(spec)
    if folder is None:
        out["tree"].insert(0, playlist)
    else:
        next(n for n in out["tree"] if n["name"] == folder)["children"].append(playlist)
    return out


def lib_of(spec: dict, tmp_path: Path, name: str = "collection.xml") -> Library:
    return read_xml(fx.write_xml(tmp_path / name, spec))


@pytest.fixture(scope="module")
def lib() -> Library:
    return read_xml(fx.SAMPLE_XML)


@pytest.fixture(scope="module")
def found(lib) -> list[P.Proposal]:
    return P.candidates(lib)


@pytest.fixture
def folder(tmp_path) -> Path:
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac", today=DAY)
    libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=DAY)
    return root


def tree_paths(doc: treeschema.TreeDoc) -> set[str]:
    return {"/".join(path) for path, _node in treeschema.walk(doc)}


# -- the fixture: 2-3 proposals, six parts each (R-404) -------------------------------------------


def test_the_fixture_gets_three_proposals_bases_first(found):
    assert [(p.family, p.name, p.slug) for p in found] == [
        ("bases", "House Bases", "house-bases"),
        ("facets", "Deep Facets", "deep-facets"),
        ("gig-first", "Warehouse Gigs", "warehouse-gigs"),
    ]
    assert [p.score for p in found] == [66, 60, 54]


def test_slugs_are_valid_and_unique_and_triggers_exact(found):
    assert 2 <= len(found) <= 3
    assert len({p.slug for p in found}) == len(found)
    for p in found:
        assert SLUG.match(p.slug), p.slug
        assert p.trigger == f"Build me the {p.name} structure"
        assert p.family in P.FAMILIES
        assert p.principle and "\n" not in p.principle
        assert p.name == p.name.strip() and "\n" not in p.name


def test_every_from_is_a_real_playlist_path_with_tracks(lib, found):
    for p in found:
        for path, node in treeschema.walk(p.tree):
            for source in node.fill_from:
                assert lib.tracks_in(source), (p.slug, path, source)  # resolves and holds tracks
                assert lib.node_at(source).path_str == source
                assert " (2)" not in source


def test_every_non_empty_playlist_lands_once_in_tree_order(lib, found):
    shown = [n.path_str for n in lib.playlists() if any(i in lib.tracks for i in n.track_ids)]
    for p in found:
        assert [row["from"] for row in p.lands] == shown  # empty_ideas is not listed
        targets = tree_paths(p.tree)
        for row in p.lands:
            assert row["to"] == P.STAYS or row["to"] in targets, (p.slug, row)


def test_where_the_fixture_playlists_land(found):
    bases, facets, gigs = ({r["from"]: r["to"] for r in p.lands} for p in found)
    assert bases["House/1.2_peak"] == "house_base/1_CRATES/1.2_peak"
    assert bases["Gigs/Gig 2025-03 Warehouse"] == "house_base/2_SETS/Gig 2025-03 Warehouse"
    assert bases["unsorted dump"] == "funk_base/0_INBOX"  # a dump goes to an inbox, to split
    assert bases["House/1.1_warm_up"] == "deep_house_base/1_CRATES/1.1_warm_up"  # 3 of 4 Deep House
    assert facets["House/Deep/deep_rollers"] == "genres/Deep House"
    assert facets["Gigs/Gig 2025-11 Rooftop"] == "gigs (new)/Gig 2025-11 Rooftop"  # beside the DJ's Gigs
    assert gigs["Gigs/Gig 2025-03 Warehouse"] == "gigs (new)/Warehouse"
    assert gigs["funk & disco 78-92"] == "archive/funk & disco 78-92"
    assert gigs["unsorted dump"] == "0_INBOX"


def test_bases_tree_shape(found):
    bases = found[0].tree
    assert [n.name for n in bases.nodes] == ["house_base", "techno_base", "deep_house_base", "disco_base", "funk_base"]
    for base in bases.nodes:
        assert [(c.kind, c.name) for c in base.children] == [
            ("playlist", P.INBOX), ("folder", P.CRATES), ("folder", P.SETS)]  # fmt: skip
    assert bases.meta == {"name": "House Bases", "family": "bases", "principle": found[0].principle}


def test_facets_has_shelves_gig_crates_and_names_the_my_tag_axes(found):
    facets = found[1]
    assert [n.name for n in facets.tree.nodes] == [P.INBOX, "genres", "gigs (new)"]
    assert [c.name for c in facets.tree.nodes[1].children] == ["House", "Techno", "Deep House", "Disco", "Funk"]
    assert all(axis in facets.principle for axis in ("Role", "Body", "Vibe", "Status"))
    assert facets.principle.startswith("5 shallow genre shelves")


def test_cost_formula(found):
    for p in found:
        kinds = [node.kind for _path, node in treeschema.walk(p.tree)]
        dumps = sum(1 for row in p.lands if row["from"] == "unsorted dump" and row["to"] != P.STAYS)
        want = kinds.count("folder") + math.ceil(kinds.count("playlist") / 2) + 2 * dumps
        assert p.cost_minutes == want and isinstance(p.cost_minutes, int)
    assert [p.cost_minutes for p in found] == [23, 8, 8]
    assert P.cost_of([], 0) == 1


def creates_only(p: P.Proposal, lib: Library) -> list:
    """The rows of the build diff that are not CREATE (dj-build's view: SKIP, CONFLICT, MANUAL)."""
    return [r for r in treeschema.diff(p.tree, treeschema.from_library(lib)) if r.op != treeschema.CREATE]


def colliding_spec() -> dict:
    """The fixture plus top-level names every family wants: a playlist `Genres` (a folder in
    facets), a playlist `0_INBOX`, folders `house_base` and `ARCHIVE `, and `gigs (new)` next to
    `Gigs`, so the first free name is `gigs (new 2)`."""
    spec = with_playlist(fx.SPEC, fx._pl("Genres", [3, 4]))
    spec = with_playlist(spec, fx._pl("0_INBOX", [19, 20]))
    spec["tree"] += [fx._folder("house_base", [fx._pl("old peak", [9, 11])]),
                     fx._folder("ARCHIVE ", []), fx._folder("gigs (new)", [])]  # fmt: skip
    return spec


def test_every_node_of_every_proposal_is_created_never_skipped(lib, found, tmp_path):
    """R-404 with dj-build: the build creates the whole proposal beside the DJ's tree, so nothing
    the report shows is skipped and `lands` and the cost count only new nodes."""
    for p in found:
        assert creates_only(p, lib) == [], p.slug
    for spec in (colliding_spec(), facets_spec(), gig_spec()):
        other = lib_of(spec, tmp_path)
        for p in P.candidates(other):
            assert creates_only(p, other) == [], (p.slug, creates_only(p, other))


def test_a_name_the_dj_already_has_at_the_top_gets_new(tmp_path):
    lib = lib_of(colliding_spec(), tmp_path)
    existing = {treeschema.norm("/".join(path)) for path, _n in treeschema.walk(treeschema.from_library(lib))}
    existing |= {treeschema.norm(n.path_str) for n in lib.walk()}
    by_family = {p.family: p for p in P.candidates(lib)}
    assert set(by_family) == set(P.FAMILIES)
    tops = {f: [n.name for n in p.tree.nodes] for f, p in by_family.items()}
    assert tops["bases"][0] == "house_base (new)"
    assert tops["facets"] == ["0_INBOX (new)", "genres (new)", "gigs (new 2)"]
    assert tops["gig-first"] == ["0_INBOX (new)", "gigs (new 2)", "archive (new)"]
    assert by_family["gig-first"].principle.endswith("new tracks wait in 0_INBOX (new).")
    for p in by_family.values():
        paths = {treeschema.norm("/".join(path)) for path, _n in treeschema.walk(p.tree)}
        assert paths.isdisjoint(existing), (p.slug, paths & existing)
        targets = tree_paths(p.tree)
        assert all(row["to"] == P.STAYS or row["to"] in targets for row in p.lands), p.slug
    lands = {r["from"]: r["to"] for r in by_family["facets"].lands}
    assert lands["unsorted dump"] == "0_INBOX (new)" and lands["Gigs/Gig 2025-03 Warehouse"].startswith("gigs (new 2)/")
    assert lands["0_INBOX"] == "genres (new)/Techno"  # the DJ's own 0_INBOX is a playlist like any other


@pytest.mark.parametrize(("taken", "want"), [
    ((), "gigs"), (("gigs",), "gigs (new)"), (("gigs", "gigs (new)"), "gigs (new 2)"),
    (("gigs", "gigs (new)", "gigs (new 2)"), "gigs (new 3)"),
])  # fmt: skip
def test_free_name(taken, want):
    assert P.free_name("gigs", taken) == want


def test_trees_round_trip_through_the_tree_schema(found):
    for p in found:
        assert treeschema.parse(yaml.safe_load(treeschema.dumps(p.tree))) == p.tree


def test_deterministic_and_the_same_with_or_without_the_facts(lib, found):
    facts = (profile.facts(lib, today=DAY), structure.facts(lib), taste.facts(lib))
    assert P.candidates(lib, *facts) == found
    assert P.candidates(lib) == found
    assert P.candidates(lib, {}, {}, {}) == found


def test_dumps_follow_the_structure_rule(lib):
    by_id = {n.id: n.path_str for n in lib.playlists()}
    assert {by_id[i] for i in P.dump_ids(lib)} == {d["path"] for d in structure.facts(lib)["dumps"]["top"]}


# -- picking rules (R-405) --------------------------------------------------------------------------


def test_scores_on_the_fixture(lib):
    assert P.family_scores(lib) == {
        "bases": {"score": 66, "genre_field": 96, "genre_names": 36},
        "facets": {"score": 60, "shelves": 5, "spread": 25, "overlap": 20, "dumps": 15},
        "gig-first": {"score": 54, "gig_names": 27},
    }


def test_facets_wins_and_two_are_proposed_when_one_family_scores_zero(tmp_path):
    lib = lib_of(facets_spec(), tmp_path)
    scores = P.family_scores(lib)
    assert scores["facets"]["score"] == 75 and scores["bases"]["score"] == 48
    assert scores["gig-first"]["score"] == 0
    found = P.candidates(lib)
    assert [p.family for p in found] == ["facets", "bases"]
    shelves = found[0].tree.nodes[1]
    assert len(shelves.children) == P.MAX_SHELVES  # 9 genres with 2+ tracks, 8 shelves
    assert found[0].principle.startswith("8 shallow genre shelves")


def test_gig_first_wins_and_groups_a_residency_into_one_crate(tmp_path):
    lib = lib_of(gig_spec(), tmp_path)
    assert P.family_scores(lib)["gig-first"]["score"] == 100
    found = P.candidates(lib)
    assert [p.family for p in found] == ["gig-first", "facets", "bases"]
    gigs = found[0]
    assert gigs.name == "Fabric Gigs" and gigs.trigger == "Build me the Fabric Gigs structure"
    crates = {c.name: c.fill_from for c in gigs.tree.nodes[1].children}
    assert crates["Fabric"] == ("Residencies/Fabric 2024-05", "Residencies/Fabric 2024-09")
    assert crates["Rooftop"] == ("Residencies/Nights/Night @ Rooftop", "Gigs/Gig 2025-11 Rooftop")
    assert crates["Boiler Room"] == ("Boiler Room 2022",)


@pytest.mark.parametrize(("scores", "want"), [
    ({"bases": 0, "facets": 0, "gig-first": 0}, ["bases", "facets"]),
    ({"bases": 0, "facets": 0, "gig-first": 9}, ["gig-first", "bases"]),
    ({"bases": 50, "facets": 50, "gig-first": 50}, ["bases", "facets", "gig-first"]),
    ({"bases": 10, "facets": 70, "gig-first": 40}, ["facets", "gig-first", "bases"]),
    ({"bases": 10, "facets": 70, "gig-first": 0}, ["facets", "bases"]),
])  # fmt: skip
def test_pick(scores, want):
    assert P.pick({f: {"score": s} for f, s in scores.items()}) == want


NO_GIG_NAMES = {"Gigs": "Misc", "Gig 2025-03 Warehouse": "Warehouse mix", "Gig 2025-11 Rooftop": "Rooftop mix"}


def test_a_library_without_genres_builds_on_its_bpm_lanes(tmp_path):
    spec = regenred(fx.SPEC, {t["id"]: "" for t in fx.SPEC["tracks"]})
    lib = lib_of(spec, tmp_path)
    scores = P.family_scores(lib)
    assert scores["bases"]["score"] == 0 and scores["facets"]["spread"] == 0
    assert scores["facets"]["score"] == 0  # no genre: no 5 shelves (overlap 20 and dumps 15 do not count)
    found = P.candidates(lib)
    assert [p.family for p in found] == ["gig-first", "bases"]  # 54, then the first of the zeros
    assert [n.name for n in found[1].tree.nodes] == ["122-127_base", "100-109_base", "119-122_base"]
    assert found[1].principle.startswith("One base per BPM lane (122-127, 100-109, 119-122)")

    found = P.candidates(lib_of(renamed(spec, NO_GIG_NAMES), tmp_path, "no-gigs.xml"))
    assert [p.family for p in found] == ["bases", "facets"]  # every family 0: the top 2 anyway
    shelves = found[1].tree.nodes[1]
    assert shelves.name == "shelves" and [c.name for c in shelves.children] == ["122-127", "100-109", "119-122"]
    assert found[1].principle.startswith("3 shallow BPM lane shelves")


def test_facets_scores_zero_below_five_genres_and_counts_its_shelves_right(tmp_path):
    """R-405: facets = 5 to 8 genre buckets. With one genre it is only the forced second of two."""
    one = regenred(fx.SPEC, {t["id"]: "House" for t in fx.SPEC["tracks"]})
    lib = lib_of(one, tmp_path)
    scores = P.family_scores(lib)
    assert scores["facets"] == {"score": 0, "shelves": 1, "spread": 5, "overlap": 20, "dumps": 15}
    assert [p.family for p in P.candidates(lib)] == ["bases", "gig-first"]

    found = P.candidates(lib_of(renamed(one, NO_GIG_NAMES), tmp_path, "one-genre.xml"))
    assert [p.family for p in found] == ["bases", "facets"]
    assert found[1].principle.startswith("1 shallow genre shelf (House);")
    assert "sort inside it later" in found[1].principle


# -- what cannot move stays where it is -------------------------------------------------------------


def test_repeated_names_and_slashes_stay_and_never_appear_as_a_2_name(tmp_path):
    spec = with_playlist(fx.SPEC, fx._pl("1.2_peak", [16, 17]), folder="House")  # a second 1.2_peak
    spec = with_playlist(spec, fx._pl("a/b", [1, 2]))
    lib = lib_of(spec, tmp_path)
    assert "House/1.2_peak (2)" in [n["path"] for n in structure.graph(lib)["nodes"]]
    for p in P.candidates(lib):
        lands = [(r["from"], r["to"]) for r in p.lands]
        assert ("House/1.2_peak", P.STAYS) in lands and lands.count(("House/1.2_peak", P.STAYS)) == 2
        assert ("a/b", P.STAYS) in lands
        sources = [s for _path, node in treeschema.walk(p.tree) for s in node.fill_from]
        assert all("(2)" not in s and s != "a/b" for s in sources)
        assert all(lib.tracks_in(s) for s in sources)


@pytest.fixture
def db_lib(tmp_path, monkeypatch) -> Library:
    live = fx.write_master_files(tmp_path / "Pioneer")
    monkeypatch.setattr(safety, "_connect", lambda db_path, quiet=False: fx.fake_db())
    return read_db(live)


def test_a_smart_playlist_from_master_db_stays_where_it_is(db_lib):
    for p in P.candidates(db_lib):
        assert {"from": "All Techno", "to": P.STAYS} in p.lands
        assert all("All Techno" not in s for _path, n in treeschema.walk(p.tree) for s in n.fill_from)


def test_names_with_markup_and_quotes_survive_the_file(tmp_path, folder):
    name = 'Peak <b>"time" & co\'s: yes'  # no "/" in it, so it can be named and moved
    spec = with_playlist(fx.SPEC, fx._pl(name, [9, 11, 12]))
    lib = lib_of(spec, tmp_path)
    found = P.candidates(lib)
    P.write_proposals(folder, found, DAY, source=EXPORT)
    back = P.load(folder / "structure" / "proposals.yaml")
    assert [b["lands"] for b in back] == [list(p.lands) for p in found]
    assert [b["tree"] for b in back] == [treeschema.TreeDoc(p.tree.nodes) for p in found]
    assert any(r["from"] == name and r["to"] != P.STAYS for r in back[0]["lands"])


# -- small rules ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "gig"), [
    ("Gig 2025-03 Warehouse", True), ("Night @ Rooftop", True), ("2023 sets", True), ("warm-up set", True),
    ("Fabric 2024-05", True), ("funk & disco 78-92", False), ("1.2_peak", False), ("Settings", False),
    ("Nightshift", False), ("unsorted dump", False),
])  # fmt: skip
def test_gig_like(name, gig):
    assert P.gig_like(name) is gig


@pytest.mark.parametrize(("name", "event"), [
    ("Gig 2025-03 Warehouse", ("warehouse", "Warehouse")),
    ("Night @ the Rooftop 2024", ("rooftop", "Rooftop")),
    ("Boiler Room 2022", ("boiler room", "Boiler Room")),
    ("2023 sets", ("2023 sets", "2023 sets")),  # nothing left: the whole name
])  # fmt: skip
def test_event_of(name, event):
    assert P.event_of(name) == event


@pytest.mark.parametrize(("name", "slug"), [
    ("House Bases", "house-bases"), ("Søndag Bases", "sondag-bases"), ("Drum & Bass Bases", "drum-bass-bases"),
    ("119-122 Bases", "119-122-bases"), ("Gig-First", "gig-first"), ("夜 Gigs", "gigs"), ("夜", "facets"),
])  # fmt: skip
def test_slug_of(name, slug):
    assert P.slug_of(name, "facets") == slug


@pytest.mark.parametrize(("dominant", "want"), [
    ("word_word", "deep_house_base"), ("Word Word", "Deep House Base"), ("word-word", "deep-house-base"),
    ("Word word", "Deep house base"), ("WORD WORD", "DEEP HOUSE BASE"), ("Word - Word", "Deep House Base"),
])  # fmt: skip
def test_new_folders_follow_the_djs_naming_pattern(dominant, want):
    assert P._styled(["Deep", "House", "base"], P._style({"dominant": dominant})) == want


def test_a_one_word_pattern_takes_the_most_used_separator():
    style = P._style({"dominant": "word", "separators": {"underscore": 1, "hyphen": 0, "space": 4}})
    assert P._styled(["house", "base"], style) == "house base"


def test_an_empty_library_still_gets_two_proposals():
    lib = Library(source="xml", tracks={"1": Track(id="1", artist="A", title="T")})
    found = P.candidates(lib)
    assert [p.family for p in found] == ["bases", "facets"]
    assert all(p.lands == () and p.cost_minutes >= 1 for p in found)
    assert [p.name for p in found] == ["Genre Bases", "Genre Facets"]


def test_a_dump_without_a_main_genre_stays_in_bases():
    tracks = {str(i): Track(id=str(i), artist=f"A{i}", title="T", genre="House" if i < 5 else "") for i in range(1, 21)}
    roots = (PlaylistNode("1", "playlist", "untagged pile", track_ids=tuple(str(i) for i in range(5, 21))),
             PlaylistNode("2", "playlist", "house", track_ids=("1", "2")))  # fmt: skip
    lib = Library(source="xml", tracks=tracks, roots=roots)
    bases = next(p for p in P.candidates(lib) if p.family == "bases")
    assert {"from": "untagged pile", "to": P.STAYS} in bases.lands


# -- structure/proposals.yaml -----------------------------------------------------------------------


def test_write_and_load(folder, found):
    paths = P.write_proposals(folder, found, DAY, source=EXPORT)
    path = folder / "structure" / "proposals.yaml"
    assert paths == [path]
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    assert lines[0] == f"# Restructure proposals for your library, generated from {EXPORT} on 2026-10-20."
    assert re.match(r"^# fingerprint: [0-9a-f]{12}$", lines[3])
    data = yaml.safe_load(text)
    assert [list(entry) for entry in data] == [list(P.WRITTEN_KEYS)] * 3
    assert [entry["slug"] for entry in data] == [p.slug for p in found]
    assert {entry["source"] for entry in data} == {EXPORT}  # Q-17: what dj-build checks
    back = P.load(path)
    assert {b["source"] for b in back} == {EXPORT}
    assert [b["tree"] for b in back] == [treeschema.TreeDoc(p.tree.nodes) for p in found]
    assert [(b["name"], b["trigger"], b["cost_minutes"]) for b in back] == [
        (p.name, p.trigger, p.cost_minutes) for p in found]  # fmt: skip
    assert not P.edited(text)


def test_the_file_holds_no_absolute_path(folder, found, tmp_path):
    P.write_proposals(folder, found, DAY, source=EXPORT)
    text = (folder / "structure" / "proposals.yaml").read_text(encoding="utf-8")
    assert str(tmp_path) not in text and tmp_path.as_posix() not in text
    assert "D:/" not in text and "file://" not in text
    with pytest.raises(ValueError):
        P.write_proposals(folder, found, DAY, source=str(tmp_path / "x.xml"))


def test_an_unchanged_file_is_rewritten_without_a_copy(folder, found):
    P.write_proposals(folder, found, DAY, source=EXPORT)
    assert P.write_proposals(folder, found, date(2026, 10, 21), source=EXPORT) == [
        folder / "structure" / "proposals.yaml"]  # fmt: skip
    assert sorted(p.name for p in (folder / "structure").iterdir()) == ["proposals.yaml"]


def test_an_edited_file_is_kept_first_create_only(folder, found):
    path = folder / "structure" / "proposals.yaml"
    P.write_proposals(folder, found, DAY, source=EXPORT)
    edited = path.read_text(encoding="utf-8").replace("House Bases", "Telepathy Bases")
    path.write_text(edited, encoding="utf-8", newline="\n")
    assert P.edited(edited)
    paths = P.write_proposals(folder, found, DAY, source=EXPORT)
    kept = folder / "structure" / "proposals.edited-2026-10-20.yaml"
    assert paths == [path, kept]
    assert kept.read_text(encoding="utf-8") == edited
    assert "House Bases" in path.read_text(encoding="utf-8")

    path.write_text(edited + "# my note\n", encoding="utf-8", newline="\n")
    again = P.write_proposals(folder, found, DAY, source=EXPORT)
    assert again[1].name == "proposals.edited-2026-10-20-2.yaml"
    assert kept.read_text(encoding="utf-8") == edited  # the first copy is never overwritten


def _write_entries(folder: Path, entries: list) -> Path:
    path = folder / "structure" / "proposals.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(("change", "message"), [
    (lambda e: e.update(slug="House Bases"), "slug"),
    (lambda e: e.update(name="Telepathy Bases"), "trigger must be exactly"),
    (lambda e: e.update(extra=1), "unknown extra"),
    (lambda e: e.pop("lands"), "missing lands"),
    (lambda e: e.update(cost_minutes="ten"), "cost_minutes"),
    (lambda e: e.update(family="vibes"), "family"),
    (lambda e: e.update(tree=[{"folder": "a", "colour": "red"}]), "unexpected key"),
    (lambda e: e.update(lands=[{"from": "a"}]), "lands"),
    (lambda e: e.update(principle="two\nlines"), "principle"),
])  # fmt: skip
def test_load_names_what_is_wrong(folder, found, change, message):
    entries = [p.data() for p in found]
    change(entries[0])
    with pytest.raises(P.ProposalsError, match=message):
        P.load(_write_entries(folder, entries))


def test_load_refuses_more_than_three_and_duplicate_slugs(folder, found):
    entries = [p.data() for p in found]
    with pytest.raises(P.ProposalsError, match="4 proposals; the report shows 2 or 3"):
        P.load(_write_entries(folder, entries + [entries[0]]))
    with pytest.raises(P.ProposalsError, match="unique"):
        P.load(_write_entries(folder, [entries[0], entries[0]]))
    (folder / "structure" / "proposals.yaml").write_text("- [unclosed\n", encoding="utf-8")
    with pytest.raises(P.ProposalsError, match="not valid YAML"):
        P.load(folder / "structure" / "proposals.yaml")


def test_load_refuses_fewer_than_two(folder, found):
    """R-404: the report shows 2 or 3 proposals; an empty file is not 'missing'."""
    entries = [p.data() for p in found]
    with pytest.raises(P.ProposalsError, match="1 proposals; the report shows 2 or 3"):
        P.load(_write_entries(folder, entries[:1]))
    path = folder / "structure" / "proposals.yaml"
    for text in ("", "# only a comment\n", "[]\n"):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(P.ProposalsError, match="0 proposals; the report shows 2 or 3"):
            P.load(path)
    assert len(P.load(_write_entries(folder, entries[:2]))) == 2


def test_load_refuses_a_name_or_trigger_used_twice(folder, found):
    entries = [p.data() for p in found]
    entries[1].update(name=entries[0]["name"], trigger=entries[0]["trigger"])
    with pytest.raises(P.ProposalsError, match="proposal 2: name 'House Bases' is also proposal 1's"):
        P.load(_write_entries(folder, entries))
    entries[1].update(name="house bases", trigger="Build me the house bases structure")  # case only
    with pytest.raises(P.ProposalsError, match="proposal 2: name 'house bases' is also proposal 1's"):
        P.load(_write_entries(folder, entries))


# -- run ----------------------------------------------------------------------------------------------


def test_run_writes_the_file_and_one_log_line(folder, monkeypatch):
    monkeypatch.setattr(libfolder, "_wall_clock", lambda: datetime(2026, 10, 21, 13, 20))  # Q-28: the wall clock
    result = P.run(folder, today=DAY)
    assert list(result) == ["counts", "source", "proposals", "written", "kept", "log"]
    assert result["counts"] == {"proposals": 3, "files": 1}
    assert result["written"] == ["structure/proposals.yaml"] and result["source"] == EXPORT
    assert result["log"] == "2026-10-20 13:20 proposals -> 3 proposals; structure/proposals.yaml"
    assert (folder / "log.md").read_text(encoding="utf-8").endswith(result["log"] + "\n")
    assert json.loads(json.dumps(result)) == result


def test_run_refuses_a_folder_that_is_not_a_library(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(common.NotALibraryFolder):
        P.run(plain, xml=fx.SAMPLE_XML, today=DAY)
    assert list(plain.iterdir()) == []
