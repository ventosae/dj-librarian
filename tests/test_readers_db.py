"""dj.readers.db: master.db -> Library from a snapshot copy only (R-202, R-204, R-201 read path)."""

import logging
import shutil
from contextlib import contextmanager
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import xml_fixtures as fx

from dj import safety
from dj.model import LibraryError, Track
from dj.readers import db as db_mod
from dj.readers.common import MAX_TREE_DEPTH
from dj.readers.db import DB_NOTES, read_db
from dj.readers.xml import XML_FIELDS_MISSING, read_xml

READ_AT = "2026-10-20T09:00:00+00:00"


class Spy:
    """Stands in for safety._connect: records the path pyrekordbox would open, and what
    the snapshot folder held at that moment."""

    def __init__(self, db_factory):
        self.db_factory = db_factory
        self.paths, self.listings, self.dbs = [], [], []

    def __call__(self, db_path, quiet=False):
        self.paths.append(db_path)
        self.listings.append(sorted(p.name for p in db_path.parent.iterdir()))
        db = self.db_factory()
        self.dbs.append(db)
        return db


@pytest.fixture
def live(tmp_path):
    return fx.write_master_files(tmp_path / "Pioneer" / "rekordbox")


@pytest.fixture
def spy(monkeypatch):
    s = Spy(fx.fake_db)
    monkeypatch.setattr(safety, "_connect", s)
    return s


@pytest.fixture
def sessions(monkeypatch):
    """Wraps safety.open_db (still the real one) and records (write, db_path) per session."""
    real, log = safety.open_db, []

    @contextmanager
    def recording(write=False, db_path=None):
        log.append((write, db_path))
        with real(write=write, db_path=db_path) as db:
            yield db

    monkeypatch.setattr(safety, "open_db", recording)
    return log


def test_only_the_snapshot_copy_is_opened_and_its_folder_is_removed(live, spy, sessions):
    before = {p.name: p.read_bytes() for p in live.parent.iterdir()}
    lib = read_db(live, read_at=READ_AT)
    (opened,) = spy.paths
    assert opened != live and opened.name == "master.db" and opened.parent != live.parent
    assert spy.listings == [["master.db", "master.db-shm", "master.db-wal", "masterPlaylists6.xml"]]
    assert not opened.parent.exists()  # the temp folder is gone
    assert sessions == [(False, opened)]  # one read-only session, on the copy
    assert {p.name: p.read_bytes() for p in live.parent.iterdir()} == before  # live files untouched
    assert (lib.source, lib.source_path, lib.read_at) == ("db", live.as_posix(), READ_AT)
    assert (spy.dbs[0].rollbacks, spy.dbs[0].closes) == (1, 1)  # never commits (SpecDB.commit raises)


def test_reads_while_rekordbox_runs_because_it_never_asks(live, spy, monkeypatch):
    def running():
        raise AssertionError("a read must not depend on the rekordbox process check")

    monkeypatch.setattr(safety, "rekordbox_running", running)
    assert read_db(live).counts()["tracks"] == 24


def test_no_argument_finds_master_db_through_safety(live, spy, monkeypatch):
    monkeypatch.setattr(safety, "find_master_db", lambda: live)
    assert read_db().counts()["tracks"] == 24
    assert spy.paths[0] != live


def test_the_snapshot_folder_is_removed_on_error_too(live, monkeypatch):
    seen = []

    class Broken(fx.SpecDB):
        def get_content(self, **kwargs):
            raise RuntimeError("disk on fire")

    def connect(db_path, quiet=False):
        seen.append(db_path)
        return Broken([], [])

    monkeypatch.setattr(safety, "_connect", connect)
    with pytest.raises(LibraryError, match="disk on fire") as info:
        read_db(live)
    assert isinstance(info.value.__cause__, RuntimeError)
    assert seen and not seen[0].parent.exists()


@pytest.mark.parametrize("error", [
    # what SQLAlchemy raises on a torn or wrong-key copy: the cause, then the whole SELECT
    RuntimeError("(sqlite3.DatabaseError) file is not a database\n[SQL: SELECT \"djmdContent\".\"ID\" "
                 "FROM \"djmdContent\" WHERE k = '402fd482c38817c35ffa8ffb8c7d93143b749e7d315df7a8']\n"
                 "(Background on this error at: https://sqlalche.me/e/20/4xp6)"),
    RuntimeError("cipher: 402fd482c38817c35ffa8ffb8c7d93143b749e7d315df7a8 rejected"),
    ImportError("No module named 'sqlcipher3'"),
])
def test_an_unreadable_snapshot_is_one_short_library_error(live, monkeypatch, error):
    def connect(db_path, quiet=False):
        raise error

    monkeypatch.setattr(safety, "_connect", connect)
    with pytest.raises(LibraryError) as info:
        read_db(live)
    message = str(info.value)
    assert message.startswith("The master.db snapshot could not be read (") and type(error).__name__ in message
    assert "\n" not in message and "SELECT" not in message and "402fd482c388" not in message
    assert len(message) < 300 and info.value.__cause__ is error


def test_a_snapshot_taken_while_rekordbox_writes_is_taken_again(tmp_path, monkeypatch):
    live = fx.write_master_files(tmp_path / "rb")
    wal = live.with_name("master.db-wal")
    real_copy, copied = shutil.copy2, []

    def copy2(src, dst, **kwargs):
        copied.append(Path(src).name)
        if copied.count("master.db") == 1 and Path(src).name == "master.db-wal":
            wal.write_bytes(b"wal placeholder + a frame rekordbox appended meanwhile")
        return real_copy(src, dst, **kwargs)

    monkeypatch.setattr(shutil, "copy2", copy2)
    dest = tmp_path / "snap"
    dest.mkdir()
    copy = db_mod.snapshot(live, dest, pause_s=0)
    assert copied.count("master.db") == 2  # the first copy was not consistent, so it was taken again
    assert (dest / "master.db-wal").read_bytes() == wal.read_bytes() and copy == dest / "master.db"


def test_a_snapshot_that_never_settles_is_a_library_error(tmp_path, monkeypatch):
    live = fx.write_master_files(tmp_path / "rb")
    wal, real_copy, grown = live.with_name("master.db-wal"), shutil.copy2, []

    def copy2(src, dst, **kwargs):
        if Path(src).name == "master.db":  # rekordbox appends to the WAL during every copy
            grown.append(1)
            wal.write_bytes(b"frame" * len(grown))
        return real_copy(src, dst, **kwargs)

    monkeypatch.setattr(shutil, "copy2", copy2)
    dest = tmp_path / "snap"
    dest.mkdir()
    with pytest.raises(LibraryError, match="kept changing"):
        db_mod.snapshot(live, dest, tries=2, pause_s=0)
    assert len(grown) == 2


def test_a_side_file_gone_on_the_retry_does_not_linger_in_the_snapshot(tmp_path, monkeypatch):
    live = fx.write_master_files(tmp_path / "rb")
    wal = live.with_name("master.db-wal")
    real_copy, calls = shutil.copy2, []

    def copy2(src, dst, **kwargs):
        calls.append(Path(src).name)
        result = real_copy(src, dst, **kwargs)
        if Path(src).name == "master.db-wal":
            wal.unlink()  # rekordbox checkpointed and closed: the WAL is gone
        return result

    monkeypatch.setattr(shutil, "copy2", copy2)
    dest = tmp_path / "snap"
    dest.mkdir()
    db_mod.snapshot(live, dest, pause_s=0)
    assert calls.count("master.db") == 2
    assert sorted(p.name for p in dest.iterdir()) == ["master.db", "master.db-shm", "masterPlaylists6.xml"]


def test_the_snapshot_path_is_logged(live, spy, caplog):
    caplog.set_level(logging.INFO, logger="dj.readers.db")
    read_db(live)
    assert str(spy.paths[0]) in caplog.text and "snapshot" in caplog.text


def test_missing_master_db_is_a_library_error(tmp_path, monkeypatch):
    with pytest.raises(LibraryError, match="not found"):
        read_db(tmp_path / "nowhere" / "master.db")

    def not_found():
        raise FileNotFoundError("master.db not found (looked at: x)")

    monkeypatch.setattr(safety, "find_master_db", not_found)
    with pytest.raises(LibraryError, match="not found"):
        read_db()


def test_counts_equal_the_xml_reader_for_the_same_library(live, monkeypatch, tmp_path):
    xml_lib = read_xml(fx.write_xml(tmp_path / "c.xml"))
    monkeypatch.setattr(safety, "_connect", Spy(lambda: fx.fake_db(fx.without_smart())))
    assert read_db(live).counts() == xml_lib.counts() == fx.EXPECTED_COUNTS
    # with the smart playlist the XML cannot carry, only `smart` differs
    monkeypatch.setattr(safety, "_connect", Spy(fx.fake_db))
    assert read_db(live).counts() == dict(fx.EXPECTED_COUNTS, smart=1)


def test_tracks_and_tree_equal_the_xml_reader_except_the_fields_xml_lacks(live, monkeypatch, tmp_path):
    xml_lib = read_xml(fx.write_xml(tmp_path / "c.xml"))
    monkeypatch.setattr(safety, "_connect", Spy(lambda: fx.fake_db(fx.without_smart())))
    db_lib = read_db(live)
    defaults = {f.name: f.default for f in fields(Track) if f.name in XML_FIELDS_MISSING}
    assert {i: replace(t, **defaults) for i, t in db_lib.tracks.items()} == xml_lib.tracks
    shape = lambda lib: [(n.kind, n.path, n.track_ids) for n in lib.walk()]
    assert shape(db_lib) == shape(xml_lib)


def test_fields_only_master_db_carries(live, spy):
    lib = read_db(live)
    t1, t9 = lib.tracks["1"], lib.tracks["9"]
    # dropped: the soft-deleted "Old Tag" link, and "Gone Tag" (a live link to a soft-deleted DjmdMyTag)
    assert t1.my_tags == ("Warm Up", "Vocal")
    assert t9.isrc == "ZZA011700009" and t9.bit_depth == 16 and t9.has_artwork is True
    assert lib.tracks["14"].bit_depth == 24 and lib.tracks["5"].has_artwork is False
    assert lib.tracks["4"].my_tags == ("Vocal", "Closer") and lib.tracks["24"].my_tags == ()
    assert (t9.bpm, t9.rating, t9.colour, t9.play_count) == (120.0, 5, "Green", 31)
    assert lib.tracks["2"].location == "//nas/vinyl rips/Funk/The Velvet Ferrymen - Brass Tide.flac"


def test_soft_deleted_rows_are_ignored(live, spy):
    lib = read_db(live)
    assert "99" not in lib.tracks
    assert [n.name for n in lib.node_at("House").children] == ["1.1_warm_up", "1.2_peak", "Deep"]
    assert lib.node_at("House/1.1_warm_up").track_ids == ("8", "21", "10", "11")
    assert lib.tracks["1"].cue_count == 3


def test_smart_playlists_keep_their_raw_rules_and_list_no_members(live, spy):
    """master.db stores smart rules, not members (DB_NOTES). The fixture rule matches orphan 23
    (genre Techno); the reader does not evaluate rules, so 23 stays an orphan on the db side."""
    lib = read_db(live)
    smart = lib.node_at("All Techno")
    assert smart.kind == "smart" and smart.track_ids == ()
    assert smart.rules == ({"raw": fx.SMART_RAW},)
    assert lib.tracks["23"].genre == "Techno" and "23" in fx.SMART_MATCHES
    assert [t.id for t in lib.orphans()] == fx.ORPHAN_IDS == ["23", "24"]
    assert any("smart playlists" in n and "orphan" in n for n in DB_NOTES)
    assert any("history" in n for n in DB_NOTES)


def test_a_smart_row_with_song_rows_still_lists_no_members(live, monkeypatch):
    """Even if a smart row came with DjmdSongPlaylist rows, they are not its members."""

    def connect(db_path, quiet=False):
        db = fx.fake_db()
        smart = next(p for p in db.playlists if p.Attribute == 4)
        smart.Songs = [SimpleNamespace(ContentID="23", TrackNo=1, rb_local_deleted=0)]
        return db

    monkeypatch.setattr(safety, "_connect", connect)
    lib = read_db(live)
    assert lib.node_at("All Techno").track_ids == () and lib.counts() == dict(fx.EXPECTED_COUNTS, smart=1)


def test_a_tree_nested_too_deep_is_a_library_error(live, monkeypatch):
    rows = [SimpleNamespace(ID=f"f{i}", Name=f"level {i}", Attribute=1, ParentID=f"f{i - 1}" if i else "root",
                            Seq=1, Songs=[], SmartList=None, rb_local_deleted=0) for i in range(MAX_TREE_DEPTH + 2)]
    monkeypatch.setattr(safety, "_connect", lambda db_path, quiet=False: fx.SpecDB([], rows))
    with pytest.raises(LibraryError, match="nested deeper"):
        read_db(live)


def test_rekordbox_version_comes_from_the_copied_playlist_xml(live, spy):
    assert read_db(live).rekordbox_version == "7.2.18"
    (live.parent / "masterPlaylists6.xml").unlink()
    (live.parent / "master.db-wal").unlink()
    assert read_db(live).rekordbox_version is None
    assert spy.listings[-1] == ["master.db", "master.db-shm"]


def test_the_engine_is_disposed_so_the_snapshot_can_be_removed(live, monkeypatch):
    disposed = []

    def connect(db_path, quiet=False):
        db = fx.fake_db()
        db.__dict__["engine"] = type("Engine", (), {"dispose": lambda self: disposed.append(db_path)})()
        return db

    monkeypatch.setattr(safety, "_connect", connect)
    read_db(live)
    assert len(disposed) == 1 and not disposed[0].parent.exists()


def test_the_field_list_of_this_reader_covers_every_model_field_with_a_real_column():
    from pyrekordbox.db6 import tables

    from dj.readers.db import FIELD_COLUMNS

    assert set(FIELD_COLUMNS) == {f.name for f in fields(Track)}
    assert all(hasattr(tables.DjmdContent, col) for col in FIELD_COLUMNS.values())


def test_mac_paths_read_the_same_through_the_db(live, monkeypatch):
    monkeypatch.setattr(safety, "_connect", Spy(lambda: fx.fake_db(fx.as_mac())))
    lib = read_db(live)
    assert lib.tracks["1"].location == "/Users/dj/Music/Funk/Okoro Lane - Sunday Sermon.mp3"
    assert lib.tracks["1"].kind == "mp3" and lib.tracks["4"].kind == "aiff"
