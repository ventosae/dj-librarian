"""dj.writers.rekordbox_xml: tree + library -> a rekordbox XML pyrekordbox reads back (R-502, R-503).

Everything is built from the synthetic library in tests/xml_fixtures.py; files only in tmp_path.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import xml_fixtures as fx
from pyrekordbox.rbxml import RekordboxXml

from dj import treeschema
from dj.model import Library, PlaylistNode, Track
from dj.readers.common import location_url, posix_location
from dj.readers.xml import XML_FIELDS_CARRIED, read_xml
from dj.writers.rekordbox_xml import (
    BuildError,
    build_xml,
    plan_xml,
    track_attributes,
    track_id_map,
    write_xml,
)

VERSION = "0.1.0"


def _library(tmp_path: Path, spec: dict | None = None, name: str = "collection.xml") -> Library:
    return read_xml(fx.write_xml(tmp_path / name, spec))


def _mirror(lib: Library) -> treeschema.TreeDoc:
    """The library's own tree as a proposal: every playlist filled `from` itself."""

    def node(n: PlaylistNode) -> dict:
        if n.kind == "folder":
            return {"folder": n.name, "children": [node(c) for c in n.children]}
        return {"playlist": n.name, "from": [n.path_str]}

    return treeschema.parse([node(n) for n in lib.roots])


def _write(tmp_path: Path, text: str, name: str = "out.xml") -> Path:
    return write_xml(text, tmp_path / name)


@pytest.fixture
def lib(tmp_path):
    return _library(tmp_path)


def _rb_tree(node) -> list:
    """pyrekordbox's view of a NODE subtree: (type, name, keys | children)."""
    out = []
    for child in node.get_playlists():
        if child.is_folder:
            out.append(("folder", child.name, child.count, _rb_tree(child)))
        else:
            out.append(("playlist", child.name, child.entries, child.get_tracks()))
    return out


def _lib_tree(nodes) -> list:
    out = []
    for n in nodes:
        if n.kind == "folder":
            out.append(("folder", n.name, len(n.children), _lib_tree(n.children)))
        else:
            out.append(("playlist", n.name, len(n.track_ids), [int(i) for i in n.track_ids]))
    return out


# -- read back by pyrekordbox (R-502) ------------------------------------------------------


def test_pyrekordbox_reads_back_the_same_folders_playlists_and_track_keys(lib, tmp_path):
    path = _write(tmp_path, build_xml(_mirror(lib), lib, product_version=VERSION))
    rb = RekordboxXml(path)
    assert (rb.frmt_version, rb.product_name, rb.product_version) == ("1.0.0", "dj-librarian", VERSION)
    root = rb.get_playlist()
    assert root.name == "ROOT" and root.count == len(lib.roots)
    assert _rb_tree(root) == _lib_tree(lib.roots)
    # the KeyType=1 playlist of the export comes out keyed by TrackID, same tracks, same order
    deep = rb.get_playlist("House", "Deep", "deep_rollers")
    assert deep.key_type == "TrackID" and deep.get_tracks() == [10, 21, 22, 14]
    # only referenced tracks: the two orphans stay out
    assert rb.num_tracks == len(rb.get_tracks()) == 22
    assert sorted(rb.get_track_ids()) == list(range(1, 23))
    rb.tostring()  # pyrekordbox's own consistency check (Entries == TRACK count) passes


def test_our_reader_reads_back_every_field_the_export_carries(lib, tmp_path):
    path = _write(tmp_path, build_xml(_mirror(lib), lib, product_version=VERSION))
    back = read_xml(path)
    assert set(back.tracks) == set(lib.tracks) - set(fx.ORPHAN_IDS)
    fields = [f for f in XML_FIELDS_CARRIED if f != "cue_count"]  # cues are not written
    for tid, track in back.tracks.items():
        source = lib.tracks[tid]
        assert {f: getattr(track, f) for f in fields} == {f: getattr(source, f) for f in fields}, tid
    assert back.counts()["entries"] == lib.counts()["entries"]


@pytest.mark.parametrize("spec", [fx.SPEC, fx.as_mac()], ids=["windows", "mac"])
def test_locations_round_trip(tmp_path, spec):
    lib = _library(tmp_path, spec)
    path = _write(tmp_path, build_xml(_mirror(lib), lib, product_version=VERSION))
    raw = {el.get("TrackID"): el.get("Location") for el in ET.parse(path).iter("TRACK") if el.get("TrackID")}
    for tid, url in raw.items():
        assert url == location_url(lib.tracks[tid].location)
        assert posix_location(url) == lib.tracks[tid].location
    rb = RekordboxXml(path)
    assert {str(t.TrackID) for t in rb.get_tracks()} == set(raw)
    if spec is fx.SPEC:
        assert raw["4"] == "file://localhost/D:/Music/Disco/J%C3%B8rn%20%C3%89b%C3%A8ne%20-%20S%C3%B8ndag%20p%C3%A5%20Taget.aiff"
        assert raw["2"].startswith("file://localhost///nas/vinyl%20rips/Funk/")
        assert raw["7"] == "file://localhost/D:/Music/Funk/Halvard%20%26%20Nim%20-%20Slow%20Burn%20Social.wav"
        assert raw["13"].endswith("Brass%20Tide%20%28Dub%20Atelier%20Club%20Edit%29.mp3")
    else:
        assert raw["1"] == "file://localhost/Users/dj/Music/Funk/Okoro%20Lane%20-%20Sunday%20Sermon.mp3"
        assert lib.tracks["2"].location == "/Volumes/nas/vinyl rips/Funk/The Velvet Ferrymen - Brass Tide.flac"
        assert raw["2"] == location_url(lib.tracks["2"].location)


def test_rating_and_bpm_encodings(lib, tmp_path):
    path = _write(tmp_path, build_xml(_mirror(lib), lib, product_version=VERSION))
    rows = {el.get("TrackID"): el for el in ET.parse(path).iter("TRACK") if el.get("TrackID")}
    for tid, el in rows.items():
        stars = lib.tracks[tid].rating
        assert el.get("Rating") == (str(stars * 51) if stars else None)
        assert el.get("AverageBpm") == f"{lib.tracks[tid].bpm:.2f}"
    assert rows["2"].get("AverageBpm") == "101.50" and rows["12"].get("AverageBpm") == "122.50"
    assert rows["9"].get("Rating") == "255" and rows["5"].get("Rating") == "102"
    rb = RekordboxXml(path)
    assert rb.get_track(TrackID=9).Rating == 5 and rb.get_track(TrackID=6).get("Rating", 0) == 0
    assert rb.get_track(TrackID=2).AverageBpm == 101.5


def test_colour_date_and_kind_use_rekordbox_codes(lib):
    attrs = track_attributes(lib.tracks["3"], 3)
    assert attrs["Colour"] == "0xFF007F" and attrs["DateAdded"] == "2019-09-30" and attrs["Kind"] == "MP3 File"
    assert track_attributes(replace(lib.tracks["3"], colour="0xabcdef"), 3)["Colour"] == "0xABCDEF"
    assert "Colour" not in track_attributes(replace(lib.tracks["3"], colour="Mauve"), 3)


def test_empty_values_are_left_out():
    bare = Track(id="1", title="Only A Title", location="D:/x/a b.mp3")
    assert track_attributes(bare, 1) == {"TrackID": "1", "Name": "Only A Title",
                                         "Location": "file://localhost/D:/x/a%20b.mp3"}  # fmt: skip


def test_characters_xml_cannot_carry_are_dropped_and_the_file_parses(tmp_path):
    tracks = {"1": Track(id="1", title="Tab\there", comment="bell\x07 & <tag>", location="D:/a.mp3")}
    lib = Library(source="xml", tracks=tracks, roots=(PlaylistNode("1", "playlist", "p", track_ids=("1",)),))
    path = _write(tmp_path, build_xml(treeschema.parse([{"playlist": "q", "from": ["p"]}]), lib,
                                      product_version=VERSION))  # fmt: skip
    el = next(e for e in ET.parse(path).iter("TRACK") if e.get("TrackID"))
    assert el.get("Comments") == "bell & <tag>" and el.get("Name") == "Tab\there"


# -- what goes in --------------------------------------------------------------------------


def test_a_playlist_is_the_union_of_its_from_playlists_in_order_each_track_once(lib, tmp_path):
    doc = treeschema.parse([{"folder": "New", "children": [
        {"playlist": "mix", "from": ["House/1.1_warm_up", "House/1.2_peak", "House/1.1_warm_up"]},
        {"playlist": "empty"},
    ]}])  # fmt: skip
    rb = RekordboxXml(_write(tmp_path, build_xml(doc, lib, product_version=VERSION)))
    assert rb.get_playlist("New", "mix").get_tracks() == [8, 21, 10, 11, 9, 12, 13, 14, 15]
    assert rb.get_playlist("New", "empty").get_tracks() == []
    assert rb.num_tracks == 9


def test_an_unknown_from_path_is_named(lib):
    doc = treeschema.parse([{"folder": "New", "children": [{"playlist": "x", "from": ["Nope/missing"]}]}])
    with pytest.raises(BuildError, match="Nope/missing.*New/x"):
        build_xml(doc, lib, product_version=VERSION)


def test_a_folder_as_from_is_refused(lib):
    with pytest.raises(BuildError, match="`from: House`.*folder"):
        build_xml(treeschema.parse([{"playlist": "x", "from": ["House"]}]), lib, product_version=VERSION)


def test_smart_playlists_are_left_out_and_reported(lib, tmp_path):
    doc = treeschema.parse([{"folder": "New", "children": [
        {"smart": "all techno", "rules": [{"genre_contains": "Techno"}]},
        {"playlist": "keep", "from": ["Gigs/Gig 2025-03 Warehouse"]},
    ]}])  # fmt: skip
    plan = plan_xml(doc, lib)
    assert plan.manual == (("New", "all techno"),)
    path = _write(tmp_path, build_xml(doc, lib, product_version=VERSION))
    new = RekordboxXml(path).get_playlist("New")
    assert [n.name for n in new.get_playlists()] == ["keep"] and new.count == 1
    assert "all techno" not in path.read_text(encoding="utf-8")


def test_only_keeps_the_given_nodes_and_their_ancestors(lib, tmp_path):
    doc = treeschema.parse([
        {"folder": "House", "children": [
            {"playlist": "1.1_warm_up", "from": ["House/1.1_warm_up"]},
            {"playlist": "1.3_closing", "from": ["funk & disco 78-92"]},
        ]},
        {"playlist": "elsewhere", "from": ["unsorted dump"]},
    ])  # fmt: skip
    only = {("House",), ("House", "1.3_closing")}
    rb = RekordboxXml(_write(tmp_path, build_xml(doc, lib, only=only, product_version=VERSION)))
    assert _rb_tree(rb.get_playlist()) == [("folder", "House", 1, [("playlist", "1.3_closing", 7, [1, 2, 3, 4, 5, 6, 7])])]
    assert rb.num_tracks == 7
    assert plan_xml(doc, lib, only=["House", "House/1.3_closing"]).playlist_tracks() == {
        "House/1.3_closing": ["1", "2", "3", "4", "5", "6", "7"]}


def test_a_track_without_a_location_stays_out(tmp_path):
    tracks = {"1": Track(id="1", title="Here", location="D:/a.mp3"), "2": Track(id="2", title="Nowhere")}
    lib = Library(source="xml", tracks=tracks, roots=(PlaylistNode("1", "playlist", "p", track_ids=("1", "2")),))
    plan = plan_xml(treeschema.parse([{"playlist": "q", "from": ["p"]}]), lib)
    assert plan.unplaced == ("2",) and [t.id for t in plan.tracks] == ["1"]


def test_track_ids_keep_positive_integers_and_map_the_rest_after_them(tmp_path):
    ids = ["5", "b", "007", "0", "a"]
    tracks = {i: Track(id=i, title=f"t{i}", location=f"D:/m/{i}.mp3") for i in ids}
    lib = Library(source="db", tracks=tracks, roots=(PlaylistNode("1", "playlist", "p", track_ids=tuple(ids)),))
    assert track_id_map(lib) == {"5": 5, "0": 6, "007": 7, "a": 8, "b": 9}
    rb = RekordboxXml(_write(tmp_path, build_xml(treeschema.parse([{"playlist": "q", "from": ["p"]}]), lib,
                                                 product_version=VERSION)))  # fmt: skip
    assert rb.get_playlist("q").get_tracks() == [5, 9, 7, 6, 8]
    assert {t.TrackID: t.Name for t in rb.get_tracks()} == {5: "t5", 9: "tb", 7: "t007", 6: "t0", 8: "ta"}


def test_output_is_deterministic_and_plain(lib):
    a = build_xml(_mirror(lib), lib, product_version=VERSION)
    assert a == build_xml(_mirror(lib), lib, product_version=VERSION)
    assert a.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<DJ_PLAYLISTS Version="1.0.0">')
    assert "\r" not in a and a.endswith("\n")


@pytest.mark.parametrize("bad", ["", "  ", None])
def test_a_product_version_is_required(lib, bad):
    with pytest.raises(BuildError, match="product_version"):
        build_xml(_mirror(lib), lib, product_version=bad)


# -- writing (create-only) -----------------------------------------------------------------


def test_write_xml_never_overwrites(tmp_path):
    target = tmp_path / "proposals" / "lanes.xml"
    first = write_xml("<a/>\n", target)
    assert first == target and target.read_text(encoding="utf-8") == "<a/>\n"
    second = write_xml("<b/>\n", target)
    third = write_xml("<c/>\n", target)
    assert (second.name, third.name) == ("lanes-2.xml", "lanes-3.xml")
    assert target.read_text(encoding="utf-8") == "<a/>\n"
    assert second.read_text(encoding="utf-8") == "<b/>\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["lanes-2.xml", "lanes-3.xml", "lanes.xml"]


def test_write_xml_keeps_a_file_that_appears_mid_write(tmp_path, monkeypatch):
    from dj import libfolder

    target = tmp_path / "lanes.xml"
    real = libfolder._place_new

    def racing(tmp, dest):
        if dest == target and not target.exists():
            target.write_text("someone else's", encoding="utf-8")
        return real(tmp, dest)

    monkeypatch.setattr(libfolder, "_place_new", racing)
    written = write_xml("<a/>\n", target)
    assert written.name == "lanes-2.xml"
    assert target.read_text(encoding="utf-8") == "someone else's"


def test_the_written_file_is_utf8_and_dates_stay_dates(lib, tmp_path):
    path = _write(tmp_path, build_xml(_mirror(lib), lib, product_version=VERSION))
    assert path.read_bytes().decode("utf-8").count("Jørn Ébène") == 1
    assert read_xml(path).tracks["4"].date_added == date(2020, 2, 2)
