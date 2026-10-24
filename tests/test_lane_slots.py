"""Q-30 (D-27, W-32): the four biggest lanes get a colour, the rest are Other. Slots are assigned
once, in profile/identity.json, and every chart reads them: the sleeve, the crate wall and the
proposal cards' mini sleeves never re-derive or re-fold a slot.

A synthetic export with 6 lanes built from the tests/xml_fixtures.py helpers: the biggest lane is
the fastest, and the two smallest are the slowest and one in the middle, so the W-30 rule (slots
by BPM, lanes past slot 4 folded into Other) would have greyed out the DJ's biggest lane. Through
the whole chain (dj library analyze, then one render), each lane wears the same slot in
identity.json, profile/sleeve.svg, the hero sleeve, the crate wall and the mini sleeves. Ties and
determinism too. No network, no master.db, nothing outside tmp_path.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
import xml_fixtures as fx

from dj import design, libfolder, report, report_charts, sleeve
from dj.analysis import identity as identity_mod
from dj.analysis import proposals as P
from dj.analysis import run_all
from dj.treeschema import TreeNode

DAY = date(2026, 10, 20)
# (letter, BPM centre, tracks, genre, playlist), slowest first. Sizes 3 5 9 4 7 12: the four
# biggest are b, c, e and f, so f (the fastest, slot 6 by the old rule) is in colour and d (in the
# middle) is not.
LANES = (
    ("a", 90, 3, "Funk", "funk_classics"),
    ("b", 105, 5, "Disco", "disco_edits"),
    ("c", 114, 9, "Deep House", "deep_house_rollers"),
    ("d", 120, 4, "House", "house_grooves"),
    ("e", 126, 7, "Tech House", "tech_house_drive"),
    ("f", 140, 12, "Techno", "techno_hard"),
)
SIZES = [size for _l, _c, size, _g, _p in LANES]
EXPECTED = [None, 1, 2, None, 3, 4]  # the slots in BPM order: the 4 biggest, numbered slowest first
OTHER = design.OTHER["dark"]
CELL = re.compile(r'<path d="M[^"]*Z" fill="(#[0-9a-f]{6})" fill-opacity="[\d.]+"/>')


def six_lane_spec() -> dict:
    """Six playlists, one per top-level folder ("Crate A" ... "Crate F"), each a tight BPM cluster
    (centre - 1, centre, centre + 1), so each is one lane; every track has a year and a genre."""
    tracks, tree, n = [], [], 0
    for letter, centre, size, genre, name in LANES:
        ids = []
        for k in range(size):
            n += 1
            ids.append(n)
            row = (str(n), f"Lane Artist {letter.upper()}{k}", f"Invented Title {n}", genre, "", 1975 + (n * 7) % 50,
                   float(centre + (k % 3) - 1), "Am", "mp3", 320, 3, "", "", f"202{n % 6}-0{1 + n % 9}-1{n % 9}",
                   n % 5, 0, ())  # fmt: skip
            tracks.append(fx._track(row))
        tree.append(fx._folder(f"Crate {letter.upper()}", [fx._pl(name, ids)]))
    return {"product": dict(fx.SPEC["product"]), "tracks": tracks, "tree": tree}


def make_library(root: Path) -> Path:
    libfolder.scaffold(root, device="windows", today=DAY, dj_name="DJ Six")
    libfolder.import_export(root, fx.write_xml(root.parent / "collection.xml", six_lane_spec()), today=DAY)
    result = run_all.analyze(root, today=DAY)
    assert result["failed"] == []
    return root


@pytest.fixture(scope="module")
def lib(tmp_path_factory) -> Path:
    return make_library(tmp_path_factory.mktemp("lanes") / "dj-library")


@pytest.fixture(scope="module")
def identity(lib) -> dict:
    return json.loads((lib / identity_mod.IDENTITY_JSON).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def taste(lib) -> dict:
    return json.loads((lib / "taste" / "facts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page(lib) -> str:
    return report.render(lib, today=DAY).read_text(encoding="utf-8")


def slot_of(identity: dict) -> dict[str, int | None]:
    """lane label -> its slot in identity.json."""
    return {lane["label"]: lane["slot"] for lane in identity["lanes"]}


def label_of(identity: dict) -> dict[str, str]:
    """playlist path -> the label of its lane."""
    return {path: lane["label"] for lane in identity["lanes"] for path in lane["playlists"]}


def hex_of(slot: int | None) -> str:
    return design.slot_hex(slot, "dark")


def band_colours(svg: str, identity: dict) -> dict[str, set[str]]:
    """The colours a sleeve or mini sleeve draws in each BPM band, over the cells that hold
    tracks (cells come ring by ring, band by band; dj.sleeve._disc)."""
    fp = identity["fingerprint"]
    names = [b["band"] for b in fp["bands"]]
    drawn = CELL.findall(svg)
    assert len(drawn) == len(fp["rings"]) * len(names)
    out: dict[str, set[str]] = {}
    for i, colour in enumerate(drawn):
        ring, band = divmod(i, len(names))
        if fp["counts"][ring][band]:
            out.setdefault(names[band], set()).add(colour)
    return out


# -- identity.json: the slots are assigned once, by size ------------------------------------------


def test_the_four_biggest_lanes_take_slots_1_to_4_in_bpm_order(identity):
    lanes = identity["lanes"]
    assert [lane["tracks"] for lane in lanes] == SIZES
    assert [lane["lo"] for lane in lanes] == sorted(lane["lo"] for lane in lanes)  # the list stays in BPM order
    assert [lane["slot"] for lane in lanes] == EXPECTED
    coloured = [lane for lane in lanes if lane["slot"]]
    assert sorted(lane["tracks"] for lane in coloured) == sorted(SIZES)[-4:]  # exactly the 4 biggest
    assert [lane["slot"] for lane in coloured] == [1, 2, 3, 4]  # numbered by BPM, never by rank
    assert max(lanes, key=lambda lane: lane["tracks"])["slot"] == 4  # the biggest, the fastest: in colour
    assert sum(1 for lane in lanes if lane["slot"] is None) == 2  # the 2 others are "Other"
    assert identity["counts"]["lanes"] == 6


def test_every_band_carries_the_slot_of_the_lane_that_owns_it(identity):
    slots = slot_of(identity)
    bands = identity["fingerprint"]["bands"]
    for band in bands:
        assert band["slot"] == (slots[band["lane"]] if band["lane"] else None), band
    assert {b["slot"] for b in bands} == {None, 1, 2, 3, 4}
    assert any(b["lane"] and b["slot"] is None for b in bands)  # a band of an Other lane is grey too


# -- the sleeve, the crate wall and the cards read them ------------------------------------------


def test_the_sleeve_file_and_the_hero_sleeve_wear_the_identity_slots(lib, page, identity):
    hero = re.search(r'<div class="sleeve-wrap">(<svg viewBox="0 0 1000 1000".*?</svg>)', page, re.DOTALL).group(1)
    sleeve_file = (lib / identity_mod.SLEEVE_SVG).read_text(encoding="utf-8")
    for svg in (sleeve_file, hero, sleeve.sleeve_svg(identity)):
        for band in identity["fingerprint"]["bands"]:
            if band["tracks"]:
                assert band_colours(svg, identity)[band["band"]] == {hex_of(band["slot"])}, band
        assert not set(CELL.findall(svg)) & set(design.CATEGORICAL["dark"][4:])  # 4 colours at most
    # the lane notes (the sleeve's legend): the three biggest lanes, each in its identity slot
    biggest = sorted(identity["lanes"], key=lambda lane: -lane["tracks"])[:3]
    notes = re.findall(r'font-size="24" font-weight="700" fill="#[0-9a-f]{6}">([^<]+)</text>', sleeve_file)
    assert notes == [f"{lane['label']} BPM" for lane in biggest]
    swatches = re.findall(r'<rect x="[\d.]+" y="\d+" width="16" height="16" rx="3" fill="(#[0-9a-f]{6})"/>', sleeve_file)
    assert swatches == [hex_of(lane["slot"]) for lane in biggest] == [hex_of(4), hex_of(2), hex_of(3)]
    assert "Other" not in "".join(notes)  # the three biggest always have a colour


def test_the_crate_wall_rows_wear_the_identity_slots(page, identity):
    slots, labels = slot_of(identity), label_of(identity)
    for cls in ("wall chart wall-wide", "wall chart wall-narrow"):
        wall = re.search(rf'<svg class="{cls}".*?</svg>', page, re.DOTALL).group(0)
        bars = re.findall(r'data-kind="(?:playlist|dump)" data-tip="\d+ tracks? · ([^"]+?) · [^"]*"><path class="mark lane (s\d)"', wall)
        assert len(bars) == 6
        for path, colour in bars:
            assert colour == report_charts.slot_class(slots[labels[path]]), path
        assert [c for _p, c in bars] == ["s0", "s1", "s2", "s0", "s3", "s4"]  # Crate A ... F
        assert 'data-tip="3 tracks · Crate A/funk_classics · lane 90-91 BPM"' in wall  # an Other lane is named
    legend = re.search(r'<div class="legend".*?</div>', page, re.DOTALL).group(0)
    for lane in identity["lanes"]:
        if lane["slot"]:
            assert f'<span class="sw s{lane["slot"]}"></span>{lane["label"]} BPM' in legend
    assert '<span class="sw s0"></span>Other (2 lanes)' in legend


def test_the_proposal_cards_wear_the_identity_slots(lib, page, identity, taste):
    slots_by_lane = slot_of(identity)
    cards = re.findall(r'<article class="proposal card.*?</article>', page, re.DOTALL)
    entries = P.load(lib / "structure" / "proposals.yaml")
    assert cards and len(cards) == len(entries)
    laned = 0
    for card, entry in zip(cards, entries):
        slots, branches = report_charts.proposal_colours(list(entry["tree"].nodes), identity, taste)
        mini = re.search(r'<div class="mini"><div class="sleeve-wrap">(<svg .*?</svg>)', card, re.DOTALL).group(1)
        drawn = band_colours(mini, identity)
        for name, colours in drawn.items():
            assert colours <= {hex_of(slots[name]), design.TEXT["dark"]}, name
        for b in branches[:5]:
            if b.lane:
                laned += 1
                assert b.slot == slots_by_lane[b.lane], b  # the lane's identity.json slot
            if b.bands:
                name = f"{b.name}/" if b.kind == "folder" else b.name
                assert f'<span class="sw {report_charts.slot_class(b.slot)}"></span><span class="branch"><strong>{name}' in card
                for band in b.bands:
                    assert drawn.get(band, {hex_of(b.slot)}) == {hex_of(b.slot)}, band
    assert laned  # at least one branch wears a lane


def test_an_other_lane_gives_an_other_branch(identity, taste):
    """One base per lane: each base wears its lane's identity.json slot; a base filled by an Other
    lane is Other (grey swatch, "(Other)" after its lane) and so are the bands that land in it."""
    nodes = [TreeNode("folder", f"{lane['label']}_base",
                      children=(TreeNode("playlist", "p", fill_from=tuple(lane["playlists"])),))
             for lane in identity["lanes"]]  # fmt: skip
    slots, branches = report_charts.proposal_colours(nodes, identity, taste)
    assert [b.slot for b in branches] == EXPECTED
    assert [b.lane for b in branches] == [lane["label"] for lane in identity["lanes"]]
    mini, _branches = report._mini(1, nodes, identity, taste)
    drawn = band_colours(mini, identity)
    for band in identity["fingerprint"]["bands"]:
        if band["tracks"] and band["lane"]:
            assert drawn[band["band"]] == {hex_of(band["slot"])}, band  # the hero sleeve's colour
    tree = report._tree_part(branches, True)
    other = identity["lanes"][0]["label"]
    assert f'<span class="sw s0"></span><span class="branch"><strong>{other}_base/' in tree
    assert f"lane {other} BPM (Other)" in tree
    assert re.findall(r'<span class="sw (s\d)">', tree) == ["s0", "s1", "s2", "s0", "s3"]  # a list shows 5 at most
    tip = report._owner(branches[0])
    assert tip == f"{other}_base (lane {other} BPM, Other: not one of your four biggest)"


def test_a_chart_showing_some_lanes_never_renumbers_them(identity, taste):
    """A slot belongs to the lane: a crate wall with only two of the six lanes, or a proposal that
    takes only the fastest lane, still draws those lanes in their identity.json slots."""
    graph = {"nodes": [], "edges": []}
    for n, letter in ((1, "c"), (2, "f")):
        lane = next(lane for lane in identity["lanes"] if lane["playlists"][0].startswith(f"Crate {letter.upper()}/"))
        graph["nodes"] += [{"id": f"f{n}", "name": f"Crate {letter.upper()}", "path": f"Crate {letter.upper()}",
                            "kind": "folder", "depth": 1, "tracks": lane["tracks"]},
                           {"id": f"p{n}", "name": "x", "path": lane["playlists"][0], "kind": "playlist", "depth": 2,
                            "tracks": lane["tracks"]}]  # fmt: skip
        graph["edges"].append({"source": f"f{n}", "target": f"p{n}"})
    wall = report_charts.crate_wall(graph, {}, identity)
    assert re.findall(r'class="mark lane (s\d)"', wall.svg.split("wall-narrow")[0]) == ["s2", "s4"]
    assert [k for k, _label in wall.legend if k.startswith("s")] == ["s2", "s4"]
    fastest = identity["lanes"][-1]
    slots, branches = report_charts.proposal_colours(
        [TreeNode("folder", "techno", children=(TreeNode("playlist", "p", fill_from=tuple(fastest["playlists"])),))],
        identity, taste)  # fmt: skip
    assert branches[0].slot == fastest["slot"] == 4 and set(slots.values()) <= {4, None}
    # loose playlists at the top level wear their own lane's slot, never their BPM position (c is
    # third by BPM but slot 2; f is sixth but slot 4)
    loose = {"nodes": [], "edges": []}
    for n, letter in ((1, "c"), (2, "f")):
        lane = next(lane for lane in identity["lanes"] if lane["playlists"][0].startswith(f"Crate {letter.upper()}/"))
        loose["nodes"].append({"id": f"p{n}", "name": f"loose {letter}", "path": lane["playlists"][0],
                               "kind": "playlist", "depth": 1, "tracks": lane["tracks"]})  # fmt: skip
    wall = report_charts.crate_wall(loose, {}, identity)
    assert re.findall(r'class="mark lane (s\d)"', wall.svg.split("wall-narrow")[0]) == ["s2", "s4"]
    assert [k for k, _label in wall.legend if k.startswith("s")] == ["s2", "s4"]


def test_the_hero_caption_names_grey_lanes_only_when_the_sleeve_draws_them(identity):
    assert "your smaller lanes" in report._sleeve_figure(identity)  # lanes a and d own grey bands
    # an Other lane can own no band (a neighbour overlaps each band more): then the disc has no
    # grey from lanes, and the caption must not claim any
    coloured = next(lane for lane in identity["lanes"] if lane["slot"])
    none_grey = json.loads(json.dumps(identity))
    for band in none_grey["fingerprint"]["bands"]:
        if band["lane"] and band["slot"] is None:
            band["lane"], band["slot"] = coloured["label"], coloured["slot"]
    caption = report._sleeve_figure(none_grey)
    assert "grey for tracks outside your lanes;" in caption
    assert "smaller lanes" not in caption and report.OTHER_LANES not in caption


# -- the rule itself -----------------------------------------------------------------------------


def lane(label: str, lo: int, hi: int, tracks: int) -> dict:
    return {"label": label, "lo": lo, "hi": hi, "tracks": tracks}


def test_ties_go_to_the_slower_lane_then_the_label():
    rows = [lane("130-134", 130, 134, 5), lane("100-104", 100, 104, 5), lane("120-124", 120, 124, 9),
            lane("126-128", 126, 128, 5), lane("110-114", 110, 114, 5)]  # fmt: skip
    out = identity_mod.lanes({"lanes": rows})
    assert [(r["label"], r["slot"]) for r in out] == [("100-104", 1), ("110-114", 2), ("120-124", 3),
                                                      ("126-128", 4), ("130-134", None)]  # fmt: skip
    # the same low end: the narrower lane is the slower; the same range: the label decides
    same = [lane("b", 120, 122, 2), lane("a", 120, 122, 2), lane("120-125", 120, 125, 2), lane("120-121", 120, 121, 2),
            lane("90-95", 90, 95, 8), lane("96-99", 96, 99, 8)]  # fmt: skip
    out = identity_mod.lanes({"lanes": same})
    assert [(r["label"], r["slot"]) for r in out] == [("90-95", 1), ("96-99", 2), ("120-121", 3), ("a", 4),
                                                      ("b", None), ("120-125", None)]  # fmt: skip
    for order in (list(reversed(same)), same[2:] + same[:2]):  # the input order never matters
        assert identity_mod.lanes({"lanes": order}) == out


def test_the_sleeve_lane_notes_are_coloured_lanes_even_on_a_tie():
    # sleeve.py cannot import identity (identity imports sleeve), so it keeps its own copy of
    # size_key; ties on track count must still pick three of the coloured four
    tied = [lane("b", 120, 122, 2), lane("a", 120, 122, 2), lane("120-125", 120, 125, 2), lane("120-121", 120, 121, 2),
            lane("118-119", 118, 119, 2), lane("90-95", 90, 95, 2)]  # fmt: skip
    for order in (tied, list(reversed(tied))):
        notes = sleeve._lane_lines({"lanes": identity_mod.lanes({"lanes": order})})
        assert len(notes) == 3 and all(note["slot"] for note in notes), notes


def test_fewer_than_five_lanes_are_all_in_colour():
    assert [r["slot"] for r in identity_mod.lanes({"lanes": []})] == []
    three = [lane("122-127", 122, 127, 9), lane("100-109", 100, 109, 7), lane("119-122", 119, 122, 6)]
    assert [(r["label"], r["slot"]) for r in identity_mod.lanes({"lanes": three})] == [
        ("100-109", 1), ("119-122", 2), ("122-127", 3)]  # fmt: skip
    ten = [lane(f"{80 + 10 * n}-{84 + 10 * n}", 80 + 10 * n, 84 + 10 * n, n % 4) for n in range(10)]
    slots = [r["slot"] for r in identity_mod.lanes({"lanes": ten})]
    assert sum(1 for s in slots if s) == identity_mod.COLOURED == design.MAX_SLOTS_PER_CHART == 4
    assert [s for s in slots if s] == [1, 2, 3, 4]


def test_the_same_export_gives_the_same_identity_and_sleeve_bytes(lib, tmp_path):
    files = (identity_mod.IDENTITY_JSON, identity_mod.SLEEVE_SVG)
    first = {rel: (lib / rel).read_bytes() for rel in files}
    copy = tmp_path / "copy" / "dj-library"
    shutil.copytree(lib, copy)
    identity_mod.run(copy, today=DAY)
    identity_mod.run(copy, today=DAY)
    again = make_library(tmp_path / "again" / "dj-library")
    for rel in files:
        assert (copy / rel).read_bytes() == first[rel], rel
        assert (again / rel).read_bytes() == first[rel], rel
