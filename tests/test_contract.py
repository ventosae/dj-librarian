"""The fakes in this suite mirror pyrekordbox. If an upgrade changes what they assume,
these fail first - before a real write goes wrong. No database is opened."""

import inspect

from pyrekordbox import Rekordbox6Database
from pyrekordbox.db6 import tables
from pyrekordbox.db6.smartlist import Operator, Property, SmartList


def params(func):
    return inspect.signature(func).parameters


def test_create_methods_append_when_seq_is_left_out():
    for name in ("create_playlist", "create_playlist_folder", "create_smart_playlist"):
        p = params(getattr(Rekordbox6Database, name))
        assert {"name", "parent", "seq"} <= set(p)
        assert p["parent"].default is None and p["seq"].default is None
    assert "smart_list" in params(Rekordbox6Database.create_smart_playlist)


def test_add_to_playlist_appends_when_track_no_is_left_out():
    p = params(Rekordbox6Database.add_to_playlist)
    assert list(p)[1:3] == ["playlist", "content"] and p["track_no"].default is None


def test_commit_rollback_close_exist():
    assert "autoinc" in params(Rekordbox6Database.commit)
    for name in ("rollback", "close", "get_playlist", "get_content"):
        assert callable(getattr(Rekordbox6Database, name))


def test_columns_the_tool_reads():
    for col in ("ID", "Name", "Attribute", "ParentID", "Seq", "SmartList", "Songs", "rb_local_deleted"):
        assert hasattr(tables.DjmdPlaylist, col)
    for col in ("ID", "Title", "Length", "ISRC", "BitRate", "FolderPath", "ArtistName", "AlbumName"):
        assert hasattr(tables.DjmdContent, col)
    # dj tidy reads these too (library.TrackInfo)
    for col in ("FileNameL", "FileType", "BitDepth", "SampleRate", "FileSize", "ImagePath", "Analysed",
                "BPM", "KeyName", "GenreName", "LabelName", "RemixerName", "ReleaseYear", "Rating",
                "Commnt", "Subtitle", "Cues", "rb_local_deleted"):
        assert hasattr(tables.DjmdContent, col)
    assert hasattr(tables.DjmdKey, "ScaleName") and hasattr(tables.DjmdCue, "rb_local_deleted")
    for col in ("ContentID", "TrackNo", "Content"):
        assert hasattr(tables.DjmdSongPlaylist, col)


def test_columns_the_master_db_reader_adds():
    # dj.readers.db reads these on top of library.TrackInfo (date added, plays, colour, My Tags)
    for col in ("StockDate", "DJPlayCount", "ColorName", "MyTagNames", "MyTags", "ImagePath"):
        assert hasattr(tables.DjmdContent, col)
    assert hasattr(tables.DjmdColor, "Commnt")
    assert hasattr(tables.DjmdSongMyTag, "MyTagName") and hasattr(tables.DjmdSongMyTag, "rb_local_deleted")
    # a live link can point at a soft-deleted tag: the reader checks DjmdSongMyTag.MyTag too
    assert hasattr(tables.DjmdSongMyTag, "MyTag") and hasattr(tables.DjmdMyTag, "rb_local_deleted")
    # dj.readers.db disposes this instance attribute so the snapshot folder can be removed
    assert "self.engine = engine" in inspect.getsource(Rekordbox6Database.__init__)


def test_file_type_enum_values_tidy_relies_on():
    ft = tables.FileType
    assert (ft.MP3, ft.M4A, ft.FLAC, ft.WAV, ft.AIFF) == (1, 4, 5, 11, 12)


def test_smartlist_enums_and_signature():
    assert (Operator.CONTAINS, Operator.IN_RANGE, Operator.IN_LAST, Operator.GREATER) == (8, 5, 6, 3)
    assert {Property.GENRE.value, Property.COMMENTS.value, Property.BPM.value,
            Property.RATING.value, Property.STOCK_DATE.value} == {"genre", "comments", "bpm", "rating", "stockDate"}
    assert list(params(SmartList.add_condition))[1:] == ["prop", "operator", "value_left", "value_right", "unit"]
