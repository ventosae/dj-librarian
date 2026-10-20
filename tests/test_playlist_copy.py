from types import SimpleNamespace as NS

import pytest

from dj import playlist_copy as pc
from dj.playlist_copy import ADD, SKIP


def content(cid, artist="Artist", title=None, deleted=0):
    return NS(ID=cid, ArtistName=artist, Title=title or f"Track {cid}", AlbumName="", Length=300,
              ISRC="", BitRate=320, FolderPath=f"D:/m/{cid}.mp3", rb_local_deleted=deleted)


def song(cid, no, cont="auto", deleted=0):
    cont = content(cid) if cont == "auto" else cont
    return NS(ContentID=cid, TrackNo=no, Content=cont, rb_local_deleted=deleted)


class CopyDB:
    """Two playlists in a fake rekordbox. add_to_playlist must never get a track_no."""

    def __init__(self, source_songs, target_songs=(), with_target=True):
        self.src = NS(ID="s", Name="jazzy", Attribute=0, ParentID="root", Seq=1, Songs=list(source_songs))
        self.base = NS(ID="f", Name="jazz_base", Attribute=1, ParentID="root", Seq=2, Songs=[])
        self.dst = NS(ID="t", Name="2.1_jazzy", Attribute=0, ParentID="f", Seq=1, Songs=list(target_songs))
        self.rows = [self.src, self.base] + ([self.dst] if with_target else [])
        self.added = []

    def get_playlist(self, ParentID):
        return NS(all=lambda: [r for r in self.rows if r.ParentID == ParentID])

    def add_to_playlist(self, playlist, content, **kwargs):
        assert not kwargs, "append only: never pass track_no"
        assert playlist is self.dst, "only the target may be written"
        playlist.Songs.append(NS(ContentID=content, TrackNo=len(playlist.Songs) + 1,
                                 Content=None, rb_local_deleted=0))
        self.added.append(content)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"the tool called db.{name}, which it must never use")


SRC, DST = "jazzy", "jazz_base/2.1_jazzy"


def test_copies_in_source_order_and_a_second_run_adds_nothing():
    db = CopyDB([song("3", 3), song("1", 1), song("2", 2)])
    assert [r.content_id for r in pc.apply(db, SRC, DST).adds] == ["1", "2", "3"]
    assert db.added == ["1", "2", "3"]
    again = pc.apply(db, SRC, DST)
    assert again.adds == [] and db.added == ["1", "2", "3"]
    assert {r.note for r in again.rows} == {"already in target"}


def test_the_source_is_never_written():
    db = CopyDB([song("1", 1)])
    pc.apply(db, SRC, DST)
    assert len(db.src.Songs) == 1


def test_skips_what_the_target_has_and_a_track_listed_twice():
    db = CopyDB([song("1", 1), song("2", 2), song("2", 3)], target_songs=[song("1", 1)])
    rows = pc.plan(db, SRC, DST).rows
    assert [(r.op, r.note) for r in rows] == [
        (SKIP, "already in target"), (ADD, ""), (SKIP, "twice in source")]


def test_skips_rows_rekordbox_flagged_deleted_and_files_that_left_the_library():
    db = CopyDB([song("1", 1, deleted=1), song("2", 2, cont=None),
                 song("3", 3, cont=content("3", deleted=1)), song("4", 4)])
    planned = pc.plan(db, SRC, DST)
    assert [r.content_id for r in planned.adds] == ["4"]
    assert [r.note for r in planned.rows if r.op == SKIP] == ["not in the library"] * 2


def test_a_track_flagged_deleted_in_the_target_does_not_count_as_there():
    db = CopyDB([song("1", 1)], target_songs=[song("1", 1, deleted=1)])
    assert [r.content_id for r in pc.plan(db, SRC, DST).adds] == ["1"]


def test_missing_target_is_fine_for_a_dry_run_only():
    db = CopyDB([song("1", 1), song("2", 2)], with_target=False)
    planned = pc.plan(db, SRC, DST, allow_missing_target=True)
    assert planned.target_exists is False and len(planned.adds) == 2
    with pytest.raises(pc.CopyError, match="2.1_jazzy"):
        pc.apply(db, SRC, DST)
    assert db.added == []


def test_refuses_the_same_playlist_a_folder_and_an_unknown_source():
    db = CopyDB([song("1", 1)])
    with pytest.raises(pc.CopyError, match="same playlist"):
        pc.plan(db, SRC, SRC)
    with pytest.raises(pc.CopyError, match="folder"):
        pc.plan(db, SRC, "jazz_base")
    with pytest.raises(pc.CopyError, match="nope"):
        pc.plan(db, "nope", DST, allow_missing_target=True)
    assert db.added == []


def test_report_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "REPORT_DIR", tmp_path)
    db = CopyDB([song("1", 1)])
    path = pc.write_report(pc.apply(db, SRC, DST))
    assert path.parent == tmp_path and "copy-jazz_base_2.1_jazzy" in path.name
    assert '"ADD": 1' in path.read_text(encoding="utf-8")


def test_a_second_report_on_the_same_day_never_replaces_the_first(tmp_path, monkeypatch):
    """The report is the only per-track record of what went into master.db: create-only."""
    monkeypatch.setattr(pc, "REPORT_DIR", tmp_path)
    first = pc.write_report(pc.apply(CopyDB([song("1", 1)]), SRC, DST))
    text = first.read_text(encoding="utf-8")
    second = pc.write_report(pc.apply(CopyDB([song("1", 1), song("2", 2)]), SRC, DST))
    assert second != first and second.name == first.name.replace(".report.json", "-2.report.json")
    assert first.read_text(encoding="utf-8") == text
