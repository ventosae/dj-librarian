"""dj.readers.xml + dj.readers.common: the rekordbox XML export -> Library (R-204, R-104 reader)."""

from dataclasses import fields
from datetime import date

import pytest
import xml_fixtures as fx

from dj.model import LibraryError, Track
from dj.readers import common
from dj.readers.xml import (
    FIELD_ATTRIBUTES,
    XML_FIELDS_CARRIED,
    XML_FIELDS_MISSING,
    XML_NOTES,
    read_xml,
)

READ_AT = "2026-10-20T09:00:00+00:00"


@pytest.fixture
def lib():
    return read_xml(fx.SAMPLE_XML, read_at=READ_AT)


def write(tmp_path, body: str, name="c.xml"):
    path = tmp_path / name
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + body, encoding="utf-8")
    return path


def collection(tracks: str, playlists: str = "") -> str:
    return (f'<DJ_PLAYLISTS Version="1.0.0"><PRODUCT Name="rekordbox" Version="7.2.18" Company="AlphaTheta"/>'
            f'<COLLECTION>{tracks}</COLLECTION><PLAYLISTS><NODE Type="0" Name="ROOT">{playlists}</NODE>'
            f"</PLAYLISTS></DJ_PLAYLISTS>")


# -- the fixture library ---------------------------------------------------------------------


def test_sample_counts_version_and_source(lib):
    assert lib.counts() == fx.EXPECTED_COUNTS
    assert (lib.source, lib.rekordbox_version, lib.read_at) == ("xml", "7.2.18", READ_AT)
    assert lib.source_path.endswith("sample.xml")


def test_committed_sample_xml_is_generated_from_the_spec(tmp_path):
    fresh = fx.write_xml(tmp_path / "fresh.xml")
    assert fx.SAMPLE_XML.read_text(encoding="utf-8") == fresh.read_text(encoding="utf-8"), (
        "tests/fixtures/sample.xml is stale: run `uv run python tests/xml_fixtures.py`")


def test_the_root_node_is_not_a_root_its_children_are(lib):
    assert [n.name for n in lib.roots] == ["House", "Gigs", "unsorted dump", "funk & disco 78-92"]
    assert [n.id for n in lib.walk()][:4] == ["1", "1.1", "1.2", "1.3"]


def test_track_fields_one_by_one(lib):
    t = lib.tracks["9"]
    assert t == Track(
        id="9", artist="Tessa Quorum", title="Open Plan", album="Open Plan EP", duration_s=t.duration_s,
        isrc="", bitrate=1024, location="D:/Music/House/Tessa Quorum - Open Plan.flac", kind="flac",
        bit_depth=0, sample_rate=44100, file_size=t.duration_s * 1024 * 125, bpm=120.0, key="Cm",
        genre="House", label="Low Ceiling Records", remixer="", year=1997, rating=5, colour="Green",
        comment="#peak", date_added=date(2022, 3, 3), play_count=31, my_tags=(), cue_count=8,
        has_artwork=False,
    )
    assert lib.tracks["13"].remixer == "Dub Atelier" and lib.tracks["12"].bpm == 122.5
    assert lib.tracks["24"].year == 0 and lib.tracks["19"].genre == "" and lib.tracks["6"].key == ""


def test_every_field_the_export_carries_is_read_and_the_rest_stays_default(lib):
    names = {f.name for f in fields(Track)}
    assert set(XML_FIELDS_CARRIED) | set(XML_FIELDS_MISSING) == names
    assert not set(XML_FIELDS_CARRIED) & set(XML_FIELDS_MISSING)
    assert set(XML_FIELDS_MISSING) == {"my_tags", "isrc", "bit_depth", "has_artwork"}
    assert any("history" in n for n in XML_NOTES) and any("smart" in n for n in XML_NOTES)
    default = Track()
    for t in lib.tracks.values():
        assert all(getattr(t, f) == getattr(default, f) for f in XML_FIELDS_MISSING)


def test_attribute_names_are_pyrekordbox_rbxml_names():
    from pyrekordbox import rbxml

    assert set(FIELD_ATTRIBUTES.values()) <= set(rbxml.Track.ATTRIBS)
    assert common.URL_PREFIX == rbxml.URL_PREFIX
    assert {int(k): v for k, v in rbxml.RATING_MAPPING.items()} == {r: common.stars_from_rating(r) for r in range(0, 256, 51)}
    assert dict(rbxml.NODE_KEYTYPE_MAPPING) == {"0": "TrackID", "1": "Location"}
    assert (rbxml.Node.FOLDER, rbxml.Node.PLAYLIST) == (0, 1)


def _norm(path: str) -> str:
    """pyrekordbox's decode_path runs os.path.normpath (backslashes on Windows) and drops the
    leading slash of POSIX and network paths; compare without both."""
    return path.replace("\\", "/").lstrip("/")


def test_cross_check_against_pyrekordbox_rekordboxxml(lib):
    from pyrekordbox.rbxml import RekordboxXml, decode_path

    rb = RekordboxXml(fx.SAMPLE_XML)
    theirs = {str(t.TrackID): t for t in rb.get_tracks()}
    assert sorted(theirs) == sorted(lib.tracks)
    for tid, t in theirs.items():
        mine = lib.tracks[tid]
        assert (t.Name, t.Artist, t.Rating, t.AverageBpm) == (mine.title, mine.artist, mine.rating, mine.bpm)
        assert _norm(t.Location) == _norm(mine.location)
        assert len(t.marks) == mine.cue_count
    by_location = {_norm(t.Location): tid for tid, t in theirs.items()}

    def walk(node, prefix=()):
        for child in node.get_playlists():
            path = prefix + (child.name,)
            if child.is_folder:
                yield path, "folder", ()
                yield from walk(child, path)
            elif child.key_type == "TrackID":
                yield path, "playlist", tuple(str(k) for k in child.get_tracks())
            else:
                yield path, "playlist", tuple(by_location[_norm(decode_path(k))] for k in child.get_tracks())

    assert list(walk(rb.get_playlist())) == [(n.path, n.kind, n.track_ids) for n in lib.walk()]
    assert rb.get_playlist("House", "Deep", "deep_rollers").key_type == "Location"


def test_tracks_in_orphans_and_the_overlap_the_analysis_will_find(lib):
    assert [t.id for t in lib.orphans()] == fx.ORPHAN_IDS
    gig = lib.tracks_in("Gigs/Gig 2025-03 Warehouse")
    assert [t.id for t in gig] == ["11", "12", "13", "14", "15", "16", "17", "18"]
    assert lib.tracks_in("House/Deep/empty_ideas") == []
    a, b = (set(lib.node_at(p).track_ids) for p in ("House/1.2_peak", "Gigs/Gig 2025-03 Warehouse"))
    assert len(a & b) / len(a | b) >= 0.5


def test_location_keys_resolve_to_track_ids(lib, tmp_path):
    assert lib.node_at("House/Deep/deep_rollers").track_ids == ("10", "21", "22", "14")
    body = collection(
        '<TRACK TrackID="7" Name="a" Location="file://localhost/D:/Music/A%20b.mp3"/>'
        '<TRACK TrackID="8" Name="b" Location="file://localhost/D:/Music/c.mp3"/>',
        '<NODE Name="p" Type="1" KeyType="1" Entries="4"><TRACK Key="D:\\Music\\A b.mp3"/>'
        '<TRACK Key="file://localhost/d:/music/C.mp3"/><TRACK Key="file://localhost/D:/gone.mp3"/></NODE>',
    )
    small = read_xml(write(tmp_path, body))
    assert small.node_at("p").track_ids == ("7", "8")  # plain path, case-insensitive match, unknown dropped


def test_a_duplicate_track_id_is_an_error(tmp_path):
    body = collection('<TRACK TrackID="1" Name="a" Location="file://localhost/D:/a.mp3"/>'
                      '<TRACK TrackID="1" Name="b" Location="file://localhost/D:/b.mp3"/>')
    with pytest.raises(LibraryError, match="TrackID '1' appears twice"):
        read_xml(write(tmp_path, body))


@pytest.mark.parametrize("body, message", [
    ("<DJ_PLAYLISTS><COLLECTION>", "not readable XML"),
    ("<NML/>", "not a rekordbox XML"),
    ('<DJ_PLAYLISTS Version="1.0.0"><PLAYLISTS/></DJ_PLAYLISTS>', "no COLLECTION"),
    (collection('<TRACK Name="no id"/>'), "no TrackID"),
])
def test_anything_that_is_not_a_collection_export_is_a_clean_error(tmp_path, body, message):
    with pytest.raises(LibraryError, match=message):
        read_xml(write(tmp_path, body))


@pytest.mark.parametrize("raw, number", [
    ("320", 320), ("44100.0", 44100), (None, 0), ("", 0), ("x", 0), ("inf", 0), ("-inf", 0), ("nan", 0),
    ("1e999", 0), (float("inf"), 0), (True, 0),
])
def test_to_int_never_raises(raw, number):
    assert common.to_int(raw) == number


@pytest.mark.parametrize("raw, number", [("122.50", 122.5), ("inf", 0.0), ("nan", 0.0), ("1e999", 0.0), (None, 0.0)])
def test_to_float_is_finite(raw, number):
    assert common.to_float(raw) == number


def test_numbers_out_of_range_read_as_zero_not_a_crash(tmp_path):
    body = collection('<TRACK TrackID="1" Name="a" BitRate="inf" Year="1e999" AverageBpm="nan" '
                      'Rating="1e400" PlayCount="-inf" TotalTime="1e400" Size="9e999"/>')
    t = read_xml(write(tmp_path, body)).tracks["1"]
    assert (t.bitrate, t.year, t.bpm, t.rating, t.play_count, t.duration_s, t.file_size) == (0, 0, 0.0, 0, 0, 0, 0)


@pytest.mark.parametrize("head", [
    '<?xml version="1.0" encoding="x-nonexistent"?>',  # LookupError inside the parser
    '<?xml version="1.0" encoding="UTF-16"?>',  # a multi-byte encoding expat refuses on UTF-8 bytes
])
def test_an_unreadable_encoding_is_a_library_error(tmp_path, head):
    path = tmp_path / "enc.xml"
    path.write_bytes((head + "\n" + collection("")).encode("utf-8"))
    with pytest.raises(LibraryError, match="not readable XML"):
        read_xml(path)


def _nested(levels: int) -> str:
    """`levels` nodes deep: levels - 1 folders around one playlist."""
    return "".join(f'<NODE Type="0" Name="f{i}">' for i in range(levels - 1)) + (
        '<NODE Type="1" Name="p" KeyType="0" Entries="1"><TRACK Key="1"/></NODE>' + "</NODE>" * (levels - 1))


def test_a_tree_nested_too_deep_is_a_library_error_not_a_recursion_error(tmp_path):
    from dj.readers.common import MAX_TREE_DEPTH

    ok = read_xml(write(tmp_path, collection('<TRACK TrackID="1" Name="a"/>', _nested(MAX_TREE_DEPTH)), "ok.xml"))
    assert len(ok.walk()) == MAX_TREE_DEPTH and ok.orphans() == []
    for levels in (MAX_TREE_DEPTH + 1, 1200):
        path = write(tmp_path, collection('<TRACK TrackID="1" Name="a"/>', _nested(levels)), f"deep{levels}.xml")
        with pytest.raises(LibraryError, match="nested deeper"):
            read_xml(path)


def test_a_missing_file_is_a_library_error(tmp_path):
    with pytest.raises(LibraryError, match="cannot read"):
        read_xml(tmp_path / "nope.xml")


def test_unknown_node_type_and_missing_playlists_are_tolerated(tmp_path):
    body = collection('<TRACK TrackID="1" Name="a"/>',
                      '<NODE Name="f" Type="7"><NODE Name="p" Type="1"><TRACK Key="1"/></NODE></NODE>'
                      '<NODE Name="q" Type="9"><TRACK Key="1"/></NODE>')
    small = read_xml(write(tmp_path, body))
    assert [(n.kind, n.path_str) for n in small.walk()] == [("folder", "f"), ("playlist", "f/p"), ("playlist", "q")]
    bare = read_xml(write(tmp_path, '<DJ_PLAYLISTS><PRODUCT Name="dj-librarian" Version="0.1.0"/>'
                                     '<COLLECTION/></DJ_PLAYLISTS>', "bare.xml"))
    assert bare.roots == () and bare.rekordbox_version is None  # not a rekordbox-made file


def test_a_mac_export_reads_to_posix_paths(tmp_path):
    mac = read_xml(fx.write_xml(tmp_path / "mac.xml", fx.as_mac()), read_at=READ_AT)
    assert mac.tracks["1"].location == "/Users/dj/Music/Funk/Okoro Lane - Sunday Sermon.mp3"
    assert mac.tracks["2"].location == "/Volumes/nas/vinyl rips/Funk/The Velvet Ferrymen - Brass Tide.flac"
    assert mac.node_at("House/Deep/deep_rollers").track_ids == ("10", "21", "22", "14")
    assert mac.counts() == fx.EXPECTED_COUNTS


def test_non_ascii_names_and_paths_survive(lib):
    t = lib.tracks["4"]
    assert t.artist == "Jørn Ébène" and t.location == "D:/Music/Disco/Jørn Ébène - Søndag på Taget.aiff"
    assert lib.tracks["2"].location.startswith("//nas/vinyl rips/")


# -- common helpers ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw, stars", [(0, 0), (51, 1), (102, 2), (153, 3), (204, 4), (255, 5),
                                        ("204", 4), (None, 0), ("", 0), (3, 3), (230, 5), (-1, 0),
                                        ("inf", 0), ("1e400", 0), ("nan", 0)])
def test_rating_to_stars(raw, stars):
    assert common.stars_from_rating(raw) == stars


@pytest.mark.parametrize("raw, posix", [
    ("file://localhost/D:/Music/A%20b%20(Edit).mp3", "D:/Music/A b (Edit).mp3"),
    ("file://localhost/C:/M%C3%BCsik/%C3%98ya.flac", "C:/Müsik/Øya.flac"),
    ("file://localhost/Users/dj/Music/a%20b.mp3", "/Users/dj/Music/a b.mp3"),
    ("file://localhost//Users/dj/Music/a.mp3", "/Users/dj/Music/a.mp3"),
    ("file://localhost//Volumes/USB/a.mp3", "/Volumes/USB/a.mp3"),
    ("file://localhost//nas/share/a.mp3", "//nas/share/a.mp3"),
    ("file://localhost///nas/share/a.mp3", "//nas/share/a.mp3"),  # pyrekordbox encode_path of a share
    ("file://localhost////nas/share/a.mp3", "//nas/share/a.mp3"),
    ("file://localhost//media/music/a.mp3", "//media/music/a.mp3"),  # a share named like a Unix root
    ("file://localhost//home/x/a.mp3", "//home/x/a.mp3"),
    ("file://localhost///Users/share/a.mp3", "//Users/share/a.mp3"),  # 3 slashes: always a share
    ("file://nas/share/a.mp3", "//nas/share/a.mp3"),
    ("file:///Users/dj/a.mp3", "/Users/dj/a.mp3"),
    ("FILE://LOCALHOST/E:/x.wav", "E:/x.wav"),
    ("C:\\Music\\Sub Folder\\a.mp3", "C:/Music/Sub Folder/a.mp3"),
    ("\\\\nas\\share\\a.mp3", "//nas/share/a.mp3"),
    ("D:/Music/100% hits.mp3", "D:/Music/100% hits.mp3"),  # a plain path is not percent-decoded
    ("", ""),
    (None, ""),
])
def test_posix_location(raw, posix):
    assert common.posix_location(raw) == posix


@pytest.mark.parametrize("path", [
    "D:/Music/a b (c) & d.mp3", "/Users/dj/Ø ü.flac", "/Volumes/USB/a.mp3", "//nas/share/x y.wav",
    "//media/music/a.mp3", "//home/x/a.mp3", "//mnt/a.mp3", "//Users/share/a.mp3", "//Volumes/share/a.mp3",
])
def test_location_url_round_trips(path):
    url = common.location_url(path)
    assert url.startswith("file://localhost/") and " " not in url
    assert common.posix_location(url) == path


@pytest.mark.parametrize("windows_path, posix", [
    ("\\\\media\\music\\a b.mp3", "//media/music/a b.mp3"),
    ("\\\\nas\\share\\a.mp3", "//nas/share/a.mp3"),
    ("D:\\Music\\a.mp3", "D:/Music/a.mp3"),
])
def test_xml_and_db_agree_on_shares_and_drives(windows_path, posix):
    """master.db FolderPath (plain) and the XML Location (as pyrekordbox and our writer encode
    it) read to the same POSIX path, also for a share whose host is named like a Unix folder."""
    from pyrekordbox.rbxml import encode_path

    assert common.posix_location(windows_path) == posix
    assert common.posix_location(encode_path(windows_path)) == posix
    assert common.posix_location(common.location_url(posix)) == posix


def test_pyrekordbox_mac_paths_read_back_as_mac_paths():
    from pyrekordbox.rbxml import encode_path

    for path in ("/Users/dj/Music/a b.mp3", "/Volumes/USB/a.mp3"):
        assert encode_path(path).startswith("file://localhost//")  # one slash too many
        assert common.posix_location(encode_path(path)) == path


@pytest.mark.parametrize("kind_text, location, kind", [
    ("MP3 File", "", "mp3"), ("M4A File", "", "m4a"), ("AAC File", "", "m4a"), ("FLAC File", "", "flac"),
    ("WAV File", "", "wav"), ("AIFF File", "", "aiff"), ("", "D:/a.AIF", "aiff"), (None, "/x/y.m4a", "m4a"),
    ("", "file://localhost/D:/a%20b.flac", "flac"), ("", "D:/a.ogg", "unknown"), ("Video", "D:/a", "unknown"),
])
def test_kind_from(kind_text, location, kind):
    assert common.kind_from(kind_text, location) == kind


@pytest.mark.parametrize("raw, expected", [
    ("2021-03-14", date(2021, 3, 14)), ("2021-03-14 10:22:01", date(2021, 3, 14)),
    ("2021/03/14", date(2021, 3, 14)), ("", None), (None, None), ("0000-00-00", None), ("soon", None),
])
def test_parse_date(raw, expected):
    assert common.parse_date(raw) == expected


def test_colour_names():
    assert common.colour_name("0xFF007F") == "Pink" and common.colour_name("#25fde9") == "Aqua"
    assert common.colour_name("0x123456") == "0x123456" and common.colour_name(None) == ""
    assert common.colour_name("Purple") == "Purple"
    assert set(common.COLOUR_NAMES.values()) == {"Pink", "Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple"}


def test_bpm_scale_matches_the_rules_module_without_importing_it():
    from dj.rules import BPM_SCALE

    assert common.BPM_SCALE == BPM_SCALE == 100
