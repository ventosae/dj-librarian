"""dj.crate, `dj library crate`, the MCP tools and the skill script (R-601..R-604, R-702), plus
R-702 for dj-build (vetoed tracks stay out of playlists filled from `from`).

The library here is bigger than tests/xml_fixtures.py's 24 tracks: 120 generated tracks (ids 101
to 220, built with the fixture's own track helper) in three lanes (deep house 116-122, house
120-126, techno 126-134) plus a second copy (221) of track 101. Every name is invented. Files
only in tmp_path.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml
from typer.testing import CliRunner

from dj import cli, crate, libfolder, safety
from dj import mcp_server as m
from dj.analysis import taste as taste_analysis
from dj.gate import Gate
from dj.libfolder import LibraryFolder
from dj.model import Library
from dj.readers.xml import read_xml
from dj.taste_files import Vetoes
from dj.write_plan import plan_tree

pytestmark = pytest.mark.usefixtures("export_reads")  # the library is read from the export fixture

DAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 14, 5)
REPO = Path(__file__).resolve().parents[1]
runner = CliRunner()

GENRES = (("Deep House", 116, 122, "Quiet Hours"), ("House", 120, 126, "Glass Floor"),
          ("Techno", 126, 134, "Iron Cellar"))  # fmt: skip
KEYS = ("Am", "Em", "Bm", "F#m", "C#m", "G#m", "D#m", "Bbm", "Fm", "Cm", "Gm", "Dm", "C", "G", "F")
FIRST = ("Ada", "Bram", "Cleo", "Dov", "Esme", "Fen", "Gus")
LAST = ("Arden", "Birch", "Cobalt", "Dune", "Ember", "Flint", "Grove", "Harrow", "Isle")
N = 120
COPY = "221"  # a second copy (FLAC) of track 101: same artist and title


def _row(i: int) -> tuple:
    genre, lo, hi, label = GENRES[i % 3]
    bpm = lo + (i * 7 % ((hi - lo) * 2 + 1)) / 2  # half-BPM steps inside the genre's range
    return (str(101 + i), f"{FIRST[i % 7]} {LAST[(i // 7) % 9]}", f"Signal {101 + i}", genre, label,
            2000 + i % 25, float(bpm), KEYS[i % len(KEYS)], "mp3", 320, (i * 7) % 6, "", "",
            f"202{i % 6}-0{1 + i % 9}-1{i % 9}", (i * 11) % 40, 0, ())  # fmt: skip


def big_spec(extra_tree: list[dict] | None = None) -> dict:
    rows = [_row(i) for i in range(N)]
    first = rows[0]
    rows.append((COPY, *first[1:8], "flac", 900, 0, "", "", "2026-01-01", 0, 0, ()))
    tracks = [fx._track(r) for r in rows]
    tree = []
    for genre, *_ in GENRES:
        ids = [int(t["id"]) for t in tracks if t["genre"] == genre and t["id"] != COPY]
        tree.append(fx._folder(genre, [
            fx._pl(f"{genre} A", ids[0:15]), fx._pl(f"{genre} B", ids[5:20]), fx._pl(f"{genre} C", ids[10:25]),
        ]))  # fmt: skip
    tree.append(fx._pl("Gig Rooftop", [101, 104, 107, 110, 113, 102, 105]))
    return {"product": fx.SPEC["product"], "tracks": tracks, "tree": tree + (extra_tree or [])}


@pytest.fixture(scope="module")
def lib(tmp_path_factory) -> Library:
    return read_xml(fx.write_xml(tmp_path_factory.mktemp("big") / "big.xml", big_spec()))


@pytest.fixture(scope="module")
def facts(lib):
    return taste_analysis.facts(lib)


def spec_of(**fields) -> crate.CrateSpec:
    return crate.parse_spec({"name": "Saturday", "size": 50, "brief": "rooftop, sunset into the night", **fields})


def _make_library(tmp_path: Path, *, device: str = "windows", spec: dict | None = None,
                  taste: bool = False) -> LibraryFolder:  # fmt: skip
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device=device, today=DAY)
    libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml", spec or big_spec()), today=DAY)
    if taste:
        taste_analysis.run(root, today=DAY)
    return LibraryFolder(root)


def write_spec(folder: LibraryFolder, slug: str = "sat", **fields) -> Path:
    data = {"name": "Saturday", "size": 50, "brief": "rooftop, sunset into the night", **fields}
    path = folder.crates / f"{slug}.spec.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def folder(tmp_path):
    f = _make_library(tmp_path)
    write_spec(f)
    return f


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _crate_lines(folder: LibraryFolder) -> list[str]:
    return [line for line in folder.log.read_text(encoding="utf-8").splitlines() if " crate " in line]


def _vetoes_md(folder: LibraryFolder, lines: list[str]) -> None:
    folder.taste.mkdir(exist_ok=True)
    (folder.taste / "vetoes.md").write_text("# Vetoes\n\n## Log\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


# -- keys and genres -----------------------------------------------------------------------


@pytest.mark.parametrize(("key", "code"), [
    ("Am", "8A"), ("8A", "8A"), ("08a", "8A"), ("1m", "8A"), ("C", "8B"), ("1d", "8B"), ("F#m", "11A"),
    ("Bbm", "3A"), ("A#m", "3A"), ("Abm", "1A"), ("Db", "3B"), ("E", "12B"), ("C#m", "12A"), ("6m", "1A"),
    ("Ebmin", "2A"), ("", None), ("H", None), ("13A", None),
])  # fmt: skip
def test_camelot_reads_classic_camelot_and_open_key(key, code):
    assert crate.camelot(key) == code


def test_key_fit_same_key_neighbours_and_the_relative_key():
    assert crate.neighbours("12A") == ("1A", "11A", "12B") and crate.neighbours("1B") == ("2B", "12B", "1A")
    assert crate.key_fit("Am", ("8A",)) == (2, "8A")
    assert [crate.key_fit(k, ("8A",))[0] for k in ("Em", "Dm", "C", "Bm", "")] == [1, 1, 1, 0, 0]


def test_genre_fit_whole_words_any_case():
    assert crate.genre_fit("Deep House", ["deep house"]) == 2
    assert crate.genre_fit("Deep House", ["House"]) == 1
    assert crate.genre_fit("Warehouse", ["House"]) == 0 and crate.genre_fit("", ["House"]) == 0
    assert crate.genre_fit("Hip-Hop", ["hip hop"]) == 2


# -- the spec ------------------------------------------------------------------------------


def test_load_spec_reads_every_field(tmp_path):
    path = tmp_path / "sat.spec.yaml"
    path.write_text(
        "name: Saturday Rooftop\nsize: 70\nbrief: |\n  rooftop,\n  sunset\nbpm: [118, 124.5]\n"
        "lanes: [118-124]\ngenres: [House, house, Deep House]\nexclude_genres: Techno\nkeys: [Am, 8A, 1d]\n"
        "anchors: [9, '13']\nmy_tags: [Vocal]\nmin_rating: 3\ncurve: peak\n", encoding="utf-8")  # fmt: skip
    spec = crate.load_spec(path)
    assert spec == crate.CrateSpec(
        name="Saturday Rooftop", size=70, brief="rooftop, sunset", bpm=(118.0, 124.5), lanes=("118-124",),
        genres=("House", "Deep House"), exclude_genres=("Techno",), keys=("8A", "8B"), anchors=("9", "13"),
        my_tags=("Vocal",), min_rating=3, curve="peak",
    )  # fmt: skip
    assert spec.spares == 14
    assert spec.to_dict()["bpm"] == [118, 124.5] and list(spec.to_dict())[:3] == ["name", "size", "brief"]
    assert crate.parse_spec(spec.to_dict()) == spec


def test_load_spec_explains_every_problem_in_one_line_each(tmp_path):
    path = tmp_path / "bad.spec.yaml"
    path.write_text("name: ''\nsize: 40\nbpm: [130, 120]\nkeys: [H]\ncurve: wave\nmin_rating: 7\nvibe: x\n",
                    encoding="utf-8")  # fmt: skip
    with pytest.raises(crate.CrateSpecError) as caught:
        crate.load_spec(path)
    errors = caught.value.errors
    assert len(errors) == 8 and all("\n" not in e for e in errors)
    for fragment in ("unknown key(s) vibe", "`name`", "`brief` is missing", "`size` must be 30, 50 or 70, got 40",
                     "`bpm`", "'H' is not a key", "`curve`", "`min_rating`"):  # fmt: skip
        assert any(fragment in e for e in errors), fragment
    assert "\n" not in str(caught.value) and str(caught.value).startswith("bad.spec.yaml: ")


@pytest.mark.parametrize(("name", "fragment"), [
    ("\x01", "control character"), ("Sat\x07urday", "control character"), ("​", "you can see"),
    ("​ ‍", "you can see"), ("Night\x85", None),  # NEL is whitespace: collapsed away
])  # fmt: skip
def test_a_name_rekordbox_cannot_carry_or_nobody_can_see_is_a_spec_error(name, fragment):
    if fragment is None:
        assert spec_of(name=name).name == "Night"
        return
    with pytest.raises(crate.CrateSpecError, match=f"`name` .*{fragment}"):
        spec_of(name=name)
    assert spec_of(name="Sunset \U0001f469‍\U0001f3a4").name.startswith("Sunset ")  # a joiner in a name is fine


@pytest.mark.parametrize("text", ["- just\n- a list\n", "name: [unclosed\n", ""])
def test_a_spec_that_is_not_a_mapping_or_not_yaml_is_one_error(tmp_path, text):
    path = tmp_path / "x.spec.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(crate.CrateSpecError) as caught:
        crate.load_spec(path)
    assert len(caught.value.errors) == 1


def test_spec_path_by_slug_or_path_and_never_outside_crates(folder):
    path = folder.crates / "sat.spec.yaml"
    for ref in ("sat", "crates/sat.spec.yaml", str(path), "  'sat' "):
        assert crate.spec_path(folder, ref) == ("sat", path)
    (folder.exports / "evil.spec.yaml").write_text("{}", encoding="utf-8")
    for bad, fragment in (("../evil.spec.yaml", "outside the library folder"),
                          ("exports/evil.spec.yaml", "a spec is crates/<slug>.spec.yaml"),
                          ("crates/Sat Night.spec.yaml", "a spec is crates/<slug>.spec.yaml"),
                          ("nope", "crates/nope.spec.yaml not found"), ("  ", "Name the crate")):  # fmt: skip
        with pytest.raises(crate.CrateError, match=re.escape(fragment)):
            crate.spec_path(folder, bad)


# -- selection (R-601, R-602, R-604) -------------------------------------------------------


@pytest.mark.parametrize("size", [30, 50, 70])
def test_exactly_n_owned_picks_with_one_reason_each_and_spares_apart(lib, facts, size):
    result = crate.select(lib, spec_of(size=size), facts)
    assert len(result.picks) == size and result.counts["picks"] == size
    assert len(result.spares) == math.ceil(0.2 * size) == result.counts["spares"]
    ids = [p.id for p in result.picks] + [p.id for p in result.spares]
    assert len(set(ids)) == len(ids)  # spares are listed apart from the picks, never twice
    for p in result.picks + result.spares:
        assert p.id in lib.tracks and lib.tracks[p.id].location  # owned, with a file
        assert p.reason.strip() and "\n" not in p.reason
    assert not any(p.spare for p in result.picks) and all(p.spare for p in result.spares)


def test_spares_spread_over_three_energy_tiers(lib, facts):
    result = crate.select(lib, spec_of(size=50), facts)
    tiers = [p.tier for p in result.spares]
    assert {t: tiers.count(t) for t in crate.TIERS} == {"low": 3, "mid": 4, "high": 3}
    assert tiers == sorted(tiers, key=crate.TIERS.index)  # listed low, mid, high
    low, high = result.tiers
    for p in result.spares:
        assert (p.bpm <= low) == (p.tier == "low") and (p.bpm > high) == (p.tier == "high")
    assert crate.select(lib, spec_of(size=70), facts).counts["spares"] == 14


def test_same_spec_same_library_same_crate_whatever_the_order(lib, facts):
    spec = spec_of(size=70, curve="peak")
    first, again = crate.select(lib, spec, facts), crate.select(lib, spec, facts)
    assert first == again
    items = list(lib.tracks.items())
    random.Random(7).shuffle(items)
    shuffled = Library(source="xml", source_path=lib.source_path, tracks=dict(items), roots=lib.roots)
    assert list(shuffled.tracks) != list(lib.tracks)
    assert crate.select(shuffled, spec, taste_analysis.facts(shuffled)) == first


def test_a_never_propose_track_is_never_picked_or_spared(lib, facts):
    spec = spec_of(size=50)
    before = crate.select(lib, spec, facts)
    banned = {before.picks[0].id, before.spares[0].id}
    after = crate.select(lib, spec, facts, Vetoes(never_propose=frozenset(banned)))
    assert banned.isdisjoint(p.id for p in after.picks + after.spares)
    assert after.counts["vetoed"] == 2 and len(after.picks) == 50


def test_a_never_pair_is_never_both_in_one_crate(lib, facts):
    spec = spec_of(size=50)
    before = crate.select(lib, spec, facts)
    a, b = before.picks[0].id, before.picks[1].id
    spare = before.spares[0].id
    pairs = frozenset({frozenset((a, b)), frozenset((a, spare))})
    after = crate.select(lib, spec, facts, Vetoes(never_pair=pairs))
    crate_ids = {p.id for p in after.picks + after.spares}
    assert a in crate_ids and b not in crate_ids and spare not in crate_ids
    assert after.counts["never_pair"] == 2 and len(after.picks) == 50


def test_a_second_copy_of_a_track_never_joins_it(lib, facts):
    result = crate.select(lib, spec_of(size=70, anchors=[COPY]), facts)
    ids = {p.id for p in result.picks + result.spares}
    assert COPY in ids and "101" not in ids and result.counts["duplicates"] == 1
    other_way = crate.select(lib, spec_of(size=30, anchors=["101"]), facts)
    assert COPY not in {p.id for p in other_way.picks + other_way.spares}


def test_not_enough_tracks_names_the_count_and_the_filter_to_widen(lib, facts):
    with pytest.raises(crate.NotEnoughTracks) as caught:
        crate.select(lib, spec_of(size=70, bpm=[120, 124], genres=["House"]), facts)
    error = caught.value
    assert error.needed == 70 and 0 < error.found < 70 and error.widen == "bpm"
    text = str(error)
    assert f"Only {error.found} tracks fit this spec" in text and "needs 70" in text and "Widen `bpm`" in text
    assert "\n" not in text


def test_not_enough_tracks_counts_what_the_vetoes_and_copies_took(lib, facts):
    spec = spec_of(size=30, bpm=[116, 118])  # 101 (116 BPM) and its copy 221 are in the window
    with pytest.raises(crate.NotEnoughTracks) as plain:
        crate.select(lib, spec, facts)
    assert "(1 never-pair partners or second copies left out)" in str(plain.value)
    with pytest.raises(crate.NotEnoughTracks) as vetoed:
        crate.select(lib, spec, facts, Vetoes(never_propose=frozenset({"101"})))
    # the veto takes the song: 101 and its copy 221 both stay out, so one track fewer fits
    assert "(2 vetoed left out)" in str(vetoed.value) and vetoed.value.found == plain.value.found - 1
    assert vetoed.value.widen == "bpm"


@pytest.mark.parametrize("vetoed", ["101", COPY])
def test_a_veto_holds_for_every_copy_of_the_track(lib, facts, vetoed):
    spec = spec_of(size=30, bpm=[115, 120])
    plain = crate.select(lib, spec, facts)
    in_plain = {p.id for p in plain.picks + plain.spares}
    assert "101" in in_plain and COPY not in in_plain  # 101 is in, its copy held back as a second copy
    result = crate.select(lib, spec, facts, Vetoes(never_propose=frozenset({vetoed})))
    ids = {p.id for p in result.picks + result.spares}
    assert "101" not in ids and COPY not in ids and len(result.picks) == 30
    anchored = crate.select(lib, spec_of(size=30, anchors=[COPY if vetoed == "101" else "101"]), facts,
                            Vetoes(never_propose=frozenset({vetoed})))  # fmt: skip
    assert {"101", COPY}.isdisjoint(p.id for p in anchored.picks + anchored.spares)
    assert any("is a copy of a track vetoed in taste/vetoes.md: left out" in w for w in anchored.warnings)


def test_a_never_pair_holds_for_every_copy_of_either_side(lib, facts):
    spec = spec_of(size=30, bpm=[115, 120], anchors=["104"])
    plain = crate.select(lib, spec, facts)
    assert "101" in {p.id for p in plain.picks + plain.spares}
    result = crate.select(lib, spec, facts, Vetoes(never_pair=frozenset({frozenset(("101", "104"))})))
    ids = {p.id for p in result.picks + result.spares}
    assert "104" in ids and "101" not in ids and COPY not in ids and len(result.picks) == 30
    with pytest.raises(crate.CrateError, match=r"Anchors .*\(104\) and .*\(221\) are a never-pair"):
        crate.select(lib, spec_of(size=30, anchors=["104", COPY]), facts,
                     Vetoes(never_pair=frozenset({frozenset(("101", "104"))})))  # fmt: skip


def test_two_anchors_that_are_copies_of_one_track_put_one_in(lib, facts):
    result = crate.select(lib, spec_of(size=30, anchors=["101", COPY]), facts)
    ids = {p.id for p in result.picks + result.spares}
    assert "101" in ids and COPY not in ids and len(result.picks) == 30
    assert any(f"({COPY}) is a second copy of anchor 101: left out" in w for w in result.warnings)


def test_preview_keeps_a_copy_of_a_vetoed_track_out(folder):
    write_spec(folder, "copies", size=30, bpm=[115, 120])
    plain = crate.preview(folder, "copies", today=DAY)
    assert "101" in {x.id for x in plain.picks + plain.spares}
    _vetoes_md(folder, [f"- [2026-10-21] never propose: Ada Arden - Signal 101 <!-- key:veto:{COPY} -->"])
    p = crate.preview(folder, "copies", today=DAY)
    assert {"101", COPY}.isdisjoint(x.id for x in p.picks + p.spares) and p.counts["vetoed"] == 2


def test_the_filters_hold_for_every_pick(lib, facts):
    spec = spec_of(size=50, bpm=[116, 126], exclude_genres=["Techno"], min_rating=1, genres=["House"])
    result = crate.select(lib, spec, facts)
    for p in result.picks + result.spares:
        t = lib.tracks[p.id]
        assert 116 <= t.bpm <= 126 and "Techno" not in t.genre and t.rating >= 1 and "House" in t.genre
    keyed = crate.select(lib, spec_of(size=30, keys=["Am"]), facts)
    assert all(crate.key_fit(lib.tracks[p.id].key, ("8A",))[0] for p in keyed.picks)
    assert any("key 8A" in p.reason for p in keyed.picks) and any("next to 8A" in p.reason for p in keyed.picks)


def test_lanes_filter_by_the_djs_lanes_and_an_unknown_lane_is_named(lib, facts):
    label = facts["lanes"][0]["label"]  # the deep house lane
    lo, hi = facts["lanes"][0]["lo"], facts["lanes"][0]["hi"]
    result = crate.select(lib, spec_of(size=30, lanes=[label]), facts)
    assert all(lo <= math.floor(p.bpm + 0.5) <= hi for p in result.picks)
    assert all(p.reason.startswith(f"lane {label}") for p in result.picks)
    path_named = crate.select(lib, spec_of(size=30, lanes=["Deep House/Deep House A"]), facts)
    assert path_named.picks == result.picks
    with pytest.raises(crate.CrateError, match=r"no lane '90-95'.*Lanes in taste/lanes.md: " + re.escape(label)):
        crate.select(lib, spec_of(size=30, lanes=["90-95"]), facts)


def test_anchors_are_always_in_and_draw_their_playlist_mates(lib, facts):
    result = crate.select(lib, spec_of(size=30, anchors=["133", "200"], bpm=[126, 134]), facts)
    by_id = {p.id: p for p in result.picks}  # 133: techno, in three playlists; 200: deep house
    assert "133" in by_id and by_id["133"].anchor and by_id["133"].reason.startswith("anchor you named")
    assert "200" in by_id  # a deep house anchor outside the bpm window: in, with a warning
    assert any("Anchor" in w and "(200)" in w and "bpm" in w for w in result.warnings)
    assert any("plays with" in p.reason for p in result.picks if not p.anchor)


def test_anchor_problems(lib, facts):
    with pytest.raises(crate.CrateError, match="`anchors`: 999 not in the library"):
        crate.select(lib, spec_of(size=30, anchors=["999"]), facts)
    vetoed = crate.select(lib, spec_of(size=30, anchors=["116"]), facts, Vetoes(never_propose=frozenset({"116"})))
    assert "116" not in {p.id for p in vetoed.picks + vetoed.spares}
    assert any("(116) is vetoed" in w for w in vetoed.warnings)
    with pytest.raises(crate.CrateError, match="never-pair"):
        crate.select(lib, spec_of(size=30, anchors=["116", "119"]), facts,
                     Vetoes(never_pair=frozenset({frozenset(("116", "119"))})))  # fmt: skip


def test_the_curve_orders_the_picks(lib, facts):
    flat = crate.select(lib, spec_of(size=50), facts).picks
    assert [p.score for p in flat] == sorted((p.score for p in flat), reverse=True)
    warm = crate.select(lib, spec_of(size=50, curve="warmup"), facts).picks
    assert [p.bpm for p in warm] == sorted(p.bpm for p in warm)
    peak = [p.bpm for p in crate.select(lib, spec_of(size=50, curve="peak"), facts).picks]
    top = peak.index(max(peak))
    assert top == 39 and peak[: top + 1] == sorted(peak[: top + 1])  # rising to the top ...
    assert peak[top:] == sorted(peak[top:], reverse=True) and len(peak[top + 1 :]) == 10  # ... easing a fifth
    assert {p.id for p in flat} == {p.id for p in crate.select(lib, spec_of(size=50, curve="peak"), facts).picks}


def test_my_tags_score_where_the_library_has_them_and_the_xml_says_it_has_none(lib, facts):
    tagged = {tid for tid in list(lib.tracks)[60:75]}
    with_tags = Library(source="db", tracks={tid: replace(t, my_tags=("Vocal",) if tid in tagged else ())
                                             for tid, t in lib.tracks.items()}, roots=lib.roots)  # fmt: skip
    result = crate.select(with_tags, spec_of(size=30, my_tags=["vocal"]), facts)
    untagged_run = crate.select(with_tags, spec_of(size=30), facts)
    assert len(tagged & {p.id for p in result.picks}) > len(tagged & {p.id for p in untagged_run.picks})
    assert any("My Tag vocal" in p.reason for p in result.picks) and not result.warnings
    plain = crate.select(lib, spec_of(size=30, my_tags=["Vocal"]), facts)
    assert any("No track in the library carries a My Tag" in w for w in plain.warnings)


def test_tracks_without_a_file_or_a_bpm_are_never_candidates(lib, facts):
    tracks = dict(lib.tracks)
    tracks["150"] = replace(tracks["150"], location="")
    tracks["151"] = replace(tracks["151"], bpm=0.0)
    result = crate.select(Library(source="xml", tracks=tracks, roots=lib.roots), spec_of(size=70), facts)
    assert {"150", "151"}.isdisjoint(p.id for p in result.picks + result.spares)
    assert (result.counts["no_file"], result.counts["no_bpm"]) == (1, 1)


def test_select_reads_the_taste_facts_as_files_or_as_measured(lib, facts):
    from_files = {"lanes": facts["lanes"], "anchors": facts["anchors"], "pairs": facts["cooccurrence"]["pairs"]}
    assert crate.select(lib, spec_of(), from_files) == crate.select(lib, spec_of(), facts)
    with pytest.raises(crate.CrateError, match="Run dj-taste again"):
        crate.select(lib, spec_of(), {"lanes": [{"label": "x"}]})


# -- the XML writer for explicit lists -----------------------------------------------------


# -- preview (writes only the gate record) -------------------------------------------------


def test_preview_writes_nothing_but_the_gate_record(folder):
    before = _snapshot(folder.root)
    p = crate.preview(folder, "sat", today=DAY, now=NOW)
    after = _snapshot(folder.root)
    assert set(after) - set(before) == {f".cache/previews/{p.preview_id}.json"}
    assert {k: v for k, v in after.items() if k in before} == before  # log.md, library.yaml, spec untouched
    assert not list(folder.proposals.glob("*.xml")) and not list(folder.crates.glob("*.md"))
    assert re.fullmatch(r"[0-9a-f]{12}", p.preview_id) and p.blocked is None
    assert (len(p.picks), len(p.spares)) == (50, 10)
    data = p.to_dict()
    assert list(data)[0] == "counts" and data["written"] == "Nothing written yet."
    assert len(data["picks"]) == crate.PICKS_LIMIT and data["picks_more"] == 20 and len(data["spares"]) == 10
    assert data["playlists"] == ["Crates/Saturday", "Crates/Saturday spares"]
    assert data["spec"] == "crates/sat.spec.yaml" and data["export"] == "exports/2026-10-20-collection.xml"
    assert Gate(folder.cache).load(p.preview_id).args == {"crate": "sat"}


def test_preview_measures_taste_when_dj_taste_has_not_run_and_reads_it_when_it_has(tmp_path):
    bare = _make_library(tmp_path / "a")
    write_spec(bare)
    p = crate.preview(bare, "sat", now=NOW)
    assert p.taste == "measured now from exports/2026-10-20-collection.xml"
    assert any("taste/facts.json is missing" in w for w in p.warnings)
    measured = _make_library(tmp_path / "b", taste=True)
    write_spec(measured)
    q = crate.preview(measured, "sat", now=NOW)
    assert q.taste == "taste/facts.json and taste/cooccurrence.json" and not q.warnings
    assert [x.id for x in q.picks] == [x.id for x in p.picks]  # the same facts, either way


def test_preview_honours_taste_vetoes_md(folder):
    first = crate.preview(folder, "sat", now=NOW)
    top, mate, other = first.picks[0], first.picks[1], first.picks[2]
    _vetoes_md(folder, [
        f"- [2026-10-21] never propose: {top.track} <!-- key:veto:{top.id} -->",
        f"- [2026-10-21] never pair: {mate.track} + {other.track} <!-- key:pair:{mate.id},{other.id} -->",
    ])  # fmt: skip
    p = crate.preview(folder, "sat", now=NOW)
    ids = {x.id for x in p.picks + p.spares}
    assert top.id not in ids and not {mate.id, other.id} <= ids
    assert p.counts["vetoed"] == 1 and p.counts["never_pair"] >= 1 and p.preview_id != first.preview_id


def test_preview_errors_are_crate_errors(folder):
    write_spec(folder, "big", size=70, bpm=[120, 124], genres=["House"])
    with pytest.raises(crate.NotEnoughTracks, match="Widen `bpm`"):
        crate.preview(folder, "big", now=NOW)
    (folder.crates / "bad.spec.yaml").write_text("name: x\nsize: 40\nbrief: b\n", encoding="utf-8")
    with pytest.raises(crate.CrateSpecError, match=r"crates/bad.spec.yaml: `size`"):
        crate.preview(folder, "bad", now=NOW)
    assert not folder.cache.exists()


# -- apply refusals (R-1102): before any file is written -----------------------------------


@pytest.fixture
def no_writes(monkeypatch):
    """Fail the test if a refusal got as far as writing anything."""

    def boom(*args, **kwargs):
        raise AssertionError("wrote before refusing")

    monkeypatch.setattr(crate, "write_xml", boom)
    monkeypatch.setattr(crate, "_write_new", boom)
    monkeypatch.setattr(crate.libfolder, "append_log", boom)
    for name in ("open_db", "backup"):
        monkeypatch.setattr(safety, name, boom)


# -- apply writes (R-603) ------------------------------------------------------------------


def test_a_top_level_playlist_named_crates_blocks_the_crate(tmp_path):
    folder = _make_library(tmp_path, spec=big_spec([fx._pl("Crates", [101])]))
    write_spec(folder)
    p = crate.preview(folder, "sat", now=NOW)
    assert p.preview_id is None and "A playlist named 'Crates'" in p.blocked


def _write(folder: LibraryFolder, slug: str = "sat"):
    return crate.apply(folder, slug, crate.preview(folder, slug, now=NOW).preview_id, today=DAY, now=NOW)


def test_a_file_in_proposals_that_is_not_a_crate_xml_is_not_a_crate(folder):
    (folder.proposals / "crate-notes.xml").write_text("my notes, not XML", encoding="utf-8")
    p = crate.preview(folder, "sat", now=NOW)
    assert p.preview_id and p.blocked is None and p.playlists == ("Crates/Saturday", "Crates/Saturday spares")


def test_structure_current_tree_counts_as_the_djs_tree(folder):
    tree = folder.root / "structure" / "current-tree.yaml"
    tree.parent.mkdir(exist_ok=True)
    tree.write_text(yaml.safe_dump({"tree": [{"folder": "CRATES", "children": [{"playlist": "Friday"}]}]}),
                    encoding="utf-8")  # fmt: skip
    p = crate.preview(folder, "sat", now=NOW)
    assert p.blocked is None and p.playlists == ("CRATES/Saturday", "CRATES/Saturday spares")
    tree.write_text(yaml.safe_dump({"tree": [{"folder": "Crates", "children": [{"playlist": "saturday"}]}]}),
                    encoding="utf-8")  # fmt: skip
    p = crate.preview(folder, "sat", now=NOW)
    assert p.preview_id is None
    assert "Crates/saturday exists in rekordbox already (structure/current-tree.yaml lists it)" in p.blocked
    tree.write_text("tree: [", encoding="utf-8")
    p = crate.preview(folder, "sat", now=NOW)
    assert p.preview_id and any(w.startswith("structure/current-tree.yaml cannot be read") for w in p.warnings)


# -- R-702 for dj-build: vetoed tracks stay out of playlists filled from `from` -------------


def test_plan_tree_leaves_vetoed_tracks_out_and_lists_them(lib):
    from dj import treeschema

    doc = treeschema.parse([{"playlist": "new", "from": ["Gig Rooftop", "House/House A"]}])
    plan = plan_tree(doc, lib, vetoed={"104", "999"})
    assert "104" not in plan.playlist_tracks()["new"] and plan.vetoed == ("104",)
    assert "104" in plan_tree(doc, lib).playlist_tracks()["new"]


# -- CLI -----------------------------------------------------------------------------------


def _cli(*args):
    return runner.invoke(cli.app, ["library", "crate", *[str(a) for a in args]])


def test_cli_apply_without_preview_id_refuses_before_anything_runs(folder, monkeypatch):
    for name in ("preview", "checked", "spec_path"):
        monkeypatch.setattr(crate, name, lambda *a, **k: pytest.fail("ran before refusing"))
    monkeypatch.setattr(libfolder, "configured_root", lambda: pytest.fail("ran before refusing"))
    for extra in ([], ["--preview-id", "  "]):
        result = _cli("sat", "--apply", *extra)
        assert result.exit_code == 1
        lines = result.stderr.strip().splitlines()
        assert len(lines) == 1 and lines[0].startswith("REFUSED --apply needs --preview-id")


def test_cli_preview_text_shows_every_pick_and_the_id(folder):
    result = _cli("sat", "--library", folder.root, "--today", "2026-10-20")
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    for text in ("crate:       Saturday (sat), 50 picks + 10 spares, curve flat", "picks:", "spares:",
                 " 50. ", "Nothing written yet.", "Crates/Saturday, Crates/Saturday spares"):  # fmt: skip
        assert text in out
    pid = re.search(r"preview id:\s+([0-9a-f]{12})", out).group(1)
    assert (folder.cache / "previews" / f"{pid}.json").is_file() and not list(folder.proposals.glob("*.xml"))


@pytest.mark.parametrize(("args", "fragment"), [
    (["sat", "--today", "20-10-2026"], "--today"),
    (["nope"], "crates/nope.spec.yaml not found"),
    (["../outside.spec.yaml"], "outside the library folder"),
])  # fmt: skip
def test_cli_errors_are_one_line_exit_1(folder, args, fragment):
    result = _cli(*args, "--library", folder.root)
    assert result.exit_code == 1 and result.stderr.startswith("ERROR") and fragment in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1


def test_cli_not_enough_tracks_is_an_error_naming_the_filter(folder):
    write_spec(folder, "big", size=70, bpm=[120, 124], genres=["House"])
    result = _cli("big", "--library", folder.root)
    assert result.exit_code == 1 and "Widen `bpm`" in result.stderr


# -- MCP -----------------------------------------------------------------------------------


@pytest.fixture
def calls(monkeypatch, tmp_path):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return type("Done", (), {"returncode": 0, "stdout": '{"x": 1}', "stderr": ""})()

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path / "dj-library"))
    return seen


def test_mcp_crate_preview_passes_the_library_and_the_spec_as_a_value(calls, tmp_path):
    assert json.loads(m.dj_crate_preview("saturday-rooftop"))["ok"] is True
    root = str((tmp_path / "dj-library").resolve())
    assert calls[-1][3:] == ["library", "crate", "--library", root, "--picks-limit", "0", "--json", "--",
                             "saturday-rooftop"]  # every pick; the MCP tool pages them (NFR-03)


def test_mcp_crate_spec_path_must_be_a_yaml_inside_the_library(calls, tmp_path):
    crates = tmp_path / "dj-library" / "crates"
    crates.mkdir(parents=True)
    (crates / "sat.spec.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "evil.spec.yaml").write_text("{}", encoding="utf-8")
    m.dj_crate_preview("crates/sat.spec.yaml")
    assert calls[-1][-1] == str((crates / "sat.spec.yaml").resolve())
    for bad in (str(tmp_path / "evil.spec.yaml"), "../evil.spec.yaml", "--apply", "crates/missing.spec.yaml", " "):
        answer = json.loads(m.dj_crate_preview(bad))
        assert answer["ok"] is False and "error" in answer
    assert len(calls) == 1


@pytest.mark.parametrize("pid", ["", "   ", "--apply", "xyz", "0123456789AB", "0123456789ab --x", None])
def test_mcp_crate_write_refuses_without_a_valid_preview_id_without_running(calls, pid):
    answer = json.loads(m.dj_crate_write("sat", pid))
    assert answer["ok"] is False and "preview" in answer["error"]
    assert calls == []


def test_mcp_crate_write_passes_apply_and_the_preview_id(calls, tmp_path):
    m.dj_crate_write("sat", " 0123456789ab ")
    root = str((tmp_path / "dj-library").resolve())
    assert calls[-1][3:] == ["library", "crate", "--library", root, "--apply", "--preview-id", "0123456789ab",
                             "--json", "--", "sat"]  # fmt: skip
    assert json.loads(m.dj_crate_write(" ", "0123456789ab"))["ok"] is False and len(calls) == 1


def test_mcp_crate_tools_annotations():
    import asyncio

    tools = {t.name: t for t in asyncio.run(m.server.list_tools())}
    preview, write = tools["dj_crate_preview"].annotations, tools["dj_crate_write"].annotations
    assert preview == m.READ and preview.read_only_hint is True
    assert write == m.WRITE and write.read_only_hint is False and not write.destructive_hint
    assert set(tools["dj_crate_write"].input_schema["required"]) == {"spec", "preview_id"}
    assert set(tools["dj_crate_preview"].input_schema["required"]) == {"spec"}


# -- the skill script and SKILL.md ---------------------------------------------------------

