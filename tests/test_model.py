"""dj.model: the one track/tree model both readers fill (R-204)."""

from dataclasses import fields

import pytest

from dj.model import COUNT_KEYS, Library, LibraryError, PlaylistNode, Track, id_sort_key


def pl(name, ids=(), node_id=None, kind="playlist"):
    return PlaylistNode(node_id or name, kind, name, track_ids=tuple(ids))


def folder(name, *children):
    return PlaylistNode(name, "folder", name, children=tuple(children))


@pytest.fixture
def lib():
    tracks = {i: Track(id=i, artist=f"A{i}", title=f"T{i}") for i in ("1", "2", "3", "10", "b")}
    roots = (
        folder("Sets", pl("warm", ["2", "1", "404"]), folder("Old", pl("AC/DC night", ["3"]))),
        pl("dump", ["1", "2", "3"]),
        PlaylistNode("s1", "smart", "Top", rules=({"raw": "<NODE/>"},)),
    )
    return Library(source="xml", source_path="x.xml", read_at="2026-10-20T00:00:00+00:00", tracks=tracks, roots=roots)


def test_every_track_field_has_a_safe_default():
    t = Track()
    defaults = {f.name: getattr(t, f.name) for f in fields(Track)}
    assert defaults["id"] == "" and defaults["kind"] == "unknown" and defaults["date_added"] is None
    assert defaults["my_tags"] == () and defaults["has_artwork"] is False and defaults["bpm"] == 0.0
    assert all(v in ("", 0, 0.0, None, (), False, "unknown") for v in defaults.values())


def test_label_line_is_artist_dash_title_or_the_title_alone():
    assert Track(artist="Okoro Lane", title="Sunday Sermon").label_line == "Okoro Lane - Sunday Sermon"
    assert Track(title="Untitled").label_line == "Untitled"


def test_bad_kinds_are_refused():
    with pytest.raises(LibraryError):
        Track(kind="ogg")
    with pytest.raises(LibraryError):
        PlaylistNode("1", "crate", "x")
    with pytest.raises(LibraryError):
        PlaylistNode("1", "playlist", "x", children=(pl("y"),))
    with pytest.raises(LibraryError):
        PlaylistNode("1", "folder", "x", track_ids=("1",))
    with pytest.raises(LibraryError):
        Library(source="csv")
    assert issubclass(LibraryError, ValueError)


def test_library_fills_paths_from_the_top(lib):
    node = lib.node_at(("Sets", "Old", "AC/DC night"))
    assert node.path == ("Sets", "Old", "AC/DC night") and node.path_str == "Sets/Old/AC/DC night"
    assert lib.roots[0].children[0].path == ("Sets", "warm")


def test_walk_is_depth_first_in_tree_order(lib):
    assert [n.name for n in lib.walk()] == ["Sets", "warm", "Old", "AC/DC night", "dump", "Top"]
    assert [n.name for n in lib.playlists()] == ["warm", "AC/DC night", "dump", "Top"]
    assert [n.name for n in lib.folders()] == ["Sets", "Old"]


def test_node_at_takes_a_string_or_a_tuple_and_falls_back_to_case_insensitive(lib):
    assert lib.node_at("Sets/warm").id == "warm"
    assert lib.node_at(" sets / WARM ").id == "warm"
    assert lib.node_at(["Sets", "Old"]).kind == "folder"
    for bad in ("Sets/nope", "", "Sets/Old/AC/DC night"):  # a '/' in a name needs the tuple form
        with pytest.raises(LibraryError):
            lib.node_at(bad)


def test_node_at_refuses_an_ambiguous_path():
    """rekordbox allows siblings with the same name, also names that differ only by case."""
    roots = (
        folder("Sets", pl("Dupe", ["1"], "d1"), pl("Dupe", ["2"], "d2"), pl("House", ["1"], "h1"),
               pl("house", [], "h2"), pl("Techno", ["3"], "t1")),
    )
    lib = Library(source="db", roots=roots)
    for bad in ("Sets/Dupe", "Sets/HOUSE", "Sets/dupe"):
        with pytest.raises(LibraryError, match="Ambiguous: 2 nodes in 'Sets'"):
            lib.tracks_in(bad)
    assert lib.node_at("Sets/House").id == "h1" and lib.node_at("Sets/house").id == "h2"  # exact wins
    assert lib.node_at("Sets/techno").id == "t1"  # one case-insensitive match is fine
    two_tops = Library(source="xml", roots=(pl("x", [], "a"), pl("x", [], "b")))
    with pytest.raises(LibraryError, match="the top level"):
        two_tops.node_at("x")


def test_tracks_in_keeps_playlist_order_and_skips_unknown_ids(lib):
    assert [t.id for t in lib.tracks_in("Sets/warm")] == ["2", "1"]  # "404" is not in the collection
    assert lib.tracks_in("Top") == []
    with pytest.raises(LibraryError, match="folder"):
        lib.tracks_in("Sets")


def test_orphans_are_tracks_in_no_playlist_sorted_by_id(lib):
    assert [t.id for t in lib.orphans()] == ["10", "b"]
    assert sorted(["b", "10", "2", "1"], key=id_sort_key) == ["1", "2", "10", "b"]


def test_counts_keys_and_what_they_count(lib):
    counts = lib.counts()
    assert tuple(counts) == COUNT_KEYS
    assert counts == {"tracks": 5, "folders": 2, "playlists": 3, "smart": 1, "orphans": 2, "entries": 7}


def test_an_empty_library_counts_zero():
    assert Library(source="db").counts() == dict.fromkeys(COUNT_KEYS, 0)
