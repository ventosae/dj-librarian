"""dj.db_write (W-38, D-32, R-504): a previewed proposal or crate straight into master.db.

Fake db only. The real `safety.open_db` runs over `TxDB` (tests/test_direct_write.py): the fixture
library's rows, with the create-only writes staged until commit and dropped on rollback, so "a
rollback leaves the db as it was" is checked on the committed rows themselves. The backup is
recorded, not copied; rekordbox's process check answers what the test says. Nothing live.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import xml_fixtures as fx
from test_build_structure import _make_library
from test_crate import _make_library as _make_crate_library
from test_crate import big_spec, write_spec
from test_direct_write import TxDB
from typer.testing import CliRunner

from dj import build_structure as bs
from dj import cli, db_write, libfolder, safety
from dj import crate as crate_mod
from dj.gate import Gate

runner = CliRunner()


@pytest.fixture
def rb(monkeypatch, tmp_path):
    """The real open_db over a TxDB: rekordbox closed, the backup recorded."""
    live = fx.write_master_files(tmp_path / "Pioneer" / "rekordbox")
    state = NS(db=TxDB(fx.fake_db()), backups=[], running=False, on_backup=None)

    def backup(path, dest=None):
        state.backups.append(path)
        if state.on_backup:
            state.on_backup()
        return safety.Backup(timestamp="test")

    monkeypatch.setattr(safety, "find_master_db", lambda: live)
    monkeypatch.setattr(safety, "rekordbox_running", lambda: state.running)
    monkeypatch.setattr(safety, "backup", backup)
    monkeypatch.setattr(safety, "_connect", lambda path, quiet=False: state.db)
    return state


@pytest.fixture
def folder(tmp_path, rb):
    return _make_library(tmp_path)


def lib_args(folder, *more):
    return ["library", "build", "lanes", "--library", str(folder.root), *more]


def preview_id(folder) -> str:
    done = runner.invoke(cli.app, lib_args(folder, "--json"))
    assert done.exit_code == 0, done.output
    data = json.loads(done.stdout)
    assert data["into_rekordbox"] == db_write.PREVIEW_LINE and data["preview_id"]
    return data["preview_id"]


def write(folder, pid, *more):
    return runner.invoke(cli.app, lib_args(folder, "--apply", "--preview-id", pid, *more))


# -- the preview -----------------------------------------------------------------------------------


def test_the_preview_says_it_writes_into_rekordbox(folder):
    text = runner.invoke(cli.app, lib_args(folder)).stdout
    assert db_write.PREVIEW_LINE in text
    assert "to write:    dj library build lanes --apply --preview-id " in text


# -- the write ---------------------------------------------------------------------------------------


def test_a_build_goes_into_rekordbox_folders_playlists_and_tracks_in_one_commit(folder, rb):
    pid = preview_id(folder)
    plan = bs.checked(folder.root, "lanes", pid, now=None)[2].plan.playlist_tracks()
    done = write(folder, pid)
    assert done.exit_code == 0, done.output
    lines = done.stdout.splitlines()
    assert lines[0].startswith("Wrote into rekordbox: 1 folder(s), 4 playlist(s), ")
    assert "playlist entries, one commit. Backup in " in lines[0] and lines[0].endswith(db_write.backup_dir())
    assert lines[1] == db_write.OPEN_IT
    tree = dict(rb.db.tree())
    lanes = dict(tree["Lanes"])
    assert list(lanes) == ["96-112 funk disco", "118-124 house", "126-132 techno"]  # the smart one is MANUAL
    for name, ids in lanes.items():
        assert ids == plan[f"Lanes/{name}"]
    assert dict(tree["House"])["1.3_closing"] == plan["House/1.3_closing"]  # into the existing folder
    assert rb.db.commits == 1 and len(rb.backups) == 1
    log = [line for line in folder.log.read_text(encoding="utf-8").splitlines() if " build lanes" in line][-1]
    assert log.endswith("; master.db") and "build lanes -> 5 create, 4 skip, 1 manual, " in log
    assert libfolder.load_meta(folder.root)["structure"]["chosen"] == "lanes"
    assert not (folder.proposals / "lanes.xml").exists()  # no XML: it is in rekordbox


def test_the_used_id_writes_nothing_again(folder, rb):
    pid = preview_id(folder)
    rows = list(rb.db.playlists)
    assert write(folder, pid).exit_code == 0
    assert Gate(folder.cache).load(pid).written == "master.db"
    again = write(folder, pid)  # the tree holds the build now: blocked before the id is looked at
    assert again.exit_code == 1 and "Nothing was written" in again.stderr and rb.db.commits == 1
    rb.db.playlists = rows  # as if the DJ deleted it in rekordbox: the content is the preview's again
    used = write(folder, pid)
    assert used.exit_code == 1 and used.stderr.startswith("REFUSED ") and "used" in used.stderr
    assert rb.db.commits == 1 and len(rb.backups) == 1


def test_a_stale_id_is_refused(folder, rb):
    pid = preview_id(folder)
    with pytest.raises(db_write.GateError, match="older than 24 hours"):
        db_write.build(folder.root, "lanes", pid, now=datetime.now() + timedelta(hours=25))
    assert rb.db.commits == 0 and rb.backups == []


def test_rekordbox_running_is_refused_before_the_backup(folder, rb):
    pid = preview_id(folder)
    before = rb.db.state()
    rb.running = True
    done = write(folder, pid)
    assert done.exit_code == 2 and done.stderr.strip() == f"STOP {db_write.CLOSE_FIRST}"
    assert rb.backups == [] and rb.db.state() == before
    rb.running = False
    assert write(folder, pid).exit_code == 0  # the id is still good: close rekordbox, say yes again


def test_a_failure_part_way_rolls_back_and_leaves_rekordbox_as_it_was(folder, rb):
    pid = preview_id(folder)
    before = rb.db.state()
    log_before = folder.log.read_text(encoding="utf-8")
    meta_before = libfolder.load_meta(folder.root)
    rb.db.fail_at = 3  # the third track
    done = write(folder, pid)
    assert done.exit_code == 1
    assert done.stderr.strip() == ("ERROR The write stopped (RuntimeError: database disk image is malformed). "
                                   "Rolled back: nothing written.")  # fmt: skip
    assert rb.db.state() == before and rb.db.commits == 0 and rb.db.rollbacks >= 1
    assert folder.log.read_text(encoding="utf-8") == log_before
    assert libfolder.load_meta(folder.root) == meta_before and not Gate(folder.cache).load(pid).used
    rb.db.fail_at = None
    assert write(folder, pid).exit_code == 0  # nothing was half-written: the same id writes it all


def test_a_tree_changed_inside_the_session_is_refused_and_rolled_back(folder, rb):
    pid = preview_id(folder)
    rb.on_backup = lambda: rb.db.playlists.append(fx._playlist_row("777", "Lanes", 1, "root", 99))
    done = write(folder, pid)
    assert done.exit_code == 1 and db_write.CHANGED in done.stderr and rb.db.commits == 0
    assert [p.Name for p in rb.db.playlists].count("Lanes") == 1  # only the one rekordbox made


def test_a_track_gone_inside_the_session_is_refused(folder, rb):
    pid = preview_id(folder)
    rb.on_backup = lambda: setattr(rb.db.contents[0], "rb_local_deleted", 1)
    done = write(folder, pid)
    assert done.exit_code == 1 and "is not in rekordbox any more" in done.stderr and rb.db.commits == 0


# -- a crate -------------------------------------------------------------------------------------------


@pytest.fixture
def crate_folder(tmp_path, rb):
    rb.db = TxDB(fx.fake_db(big_spec()))
    f = _make_crate_library(tmp_path)
    write_spec(f)
    return f


def test_a_crate_goes_into_rekordbox_with_its_record(crate_folder, rb):
    args = ["library", "crate", "sat", "--library", str(crate_folder.root)]
    data = json.loads(runner.invoke(cli.app, [*args, "--json"]).stdout)
    assert data["export"] == "master.db" and data["into_rekordbox"] == db_write.PREVIEW_LINE
    picks = crate_mod.preview(crate_folder.root, "sat")  # what the DJ saw
    done = runner.invoke(cli.app, [*args, "--apply", "--preview-id", data["preview_id"], "--json"])
    assert done.exit_code == 0, done.output
    result = json.loads(done.stdout)
    tree = dict(rb.db.tree())
    crates = dict(tree["Crates"])
    assert crates["Saturday"] == [p.id for p in picks.picks]
    assert crates.get("Saturday spares", []) == [p.id for p in picks.spares]
    assert result["written"] == "master.db" and result["next"] == db_write.OPEN_IT
    assert result["log_line"].endswith("; master.db") and " crate sat -> 50 picks, " in result["log_line"]
    record = (crate_folder.root / result["record"]).read_text(encoding="utf-8")
    assert "Written into rekordbox: playlists Crates/Saturday" in record and "Import master.db" not in record
    after = crate_mod.preview(crate_folder.root, "sat")
    assert after.preview_id is None and "Crates/Saturday exists in rekordbox already" in after.blocked


# -- after the review (W-38) ------------------------------------------------------------------------------


def test_a_failure_after_the_commit_is_not_called_a_rollback(folder, rb, monkeypatch):
    """pyrekordbox's commit writes master.db, then saves masterPlaylists6.xml: a failure in that save
    comes out of commit() with master.db already written. The DJ hears so, with the backup's folder."""
    live = safety.find_master_db()

    def backup(path, dest=None):  # the real Backup's hashes, so open_db can tell what changed
        rb.backups.append(path)
        return safety.Backup(timestamp="test", hashes={live: safety.sha256(live)})

    def commit_then_fail():
        TxDB.commit(rb.db)
        live.write_bytes(b"SQLite format 3\x00 written by the commit")
        raise PermissionError(13, "Permission denied", "masterPlaylists6.xml")

    monkeypatch.setattr(safety, "backup", backup)
    pid = preview_id(folder)
    monkeypatch.setattr(rb.db, "commit", commit_then_fail)
    done = write(folder, pid)
    err = done.stderr.strip()
    assert done.exit_code == 1 and err.startswith("ERROR The write stopped after rekordbox's files changed (PermissionError")
    assert "nothing written" not in err and "WARNING: changed on disk despite the failure: master.db" in err
    assert db_write.backup_dir() in err and Path(db_write.backup_dir()).is_absolute()
    assert folder.log.read_text(encoding="utf-8").rstrip().endswith("build lanes, stopped after the commit; master.db")


def test_the_first_of_two_same_named_folders_counts_as_the_tree_writer_takes_it():
    from dj.model import PlaylistNode
    from dj.write_plan import PlannedNode

    roots = (PlaylistNode("1", "folder", "Gigs", children=(PlaylistNode("2", "playlist", "new"),)),
             PlaylistNode("3", "folder", "Gigs"))  # rekordbox allows both: an XML imported twice  # fmt: skip
    plan = (PlannedNode("folder", "Gigs", ("Gigs",), children=(PlannedNode("playlist", "new", ("Gigs", "new")),)),)
    assert db_write.expected(plan, roots) == set()  # the first Gigs holds it, as tree.walk sees it
    assert db_write.expected(plan, tuple(reversed(roots))) == {("gigs", "new")}


def test_written_then_removed_in_rekordbox_gets_a_fresh_id(folder, rb):
    """One preview, one write: the used id stays refused, but once the DJ removed the build in rekordbox
    a new preview gets a fresh id (as `dj tree` does since W-21), not a block."""
    rows = list(rb.db.playlists)
    pid = preview_id(folder)
    assert write(folder, pid).exit_code == 0
    rb.db.playlists = rows
    fresh = preview_id(folder)
    assert fresh != pid
    assert write(folder, pid).stderr.startswith("REFUSED ")
    assert write(folder, fresh).exit_code == 0 and rb.db.commits == 2


def test_the_result_counts_tracks_as_the_preview_does_and_names_entries_apart(folder, rb):
    data = json.loads(runner.invoke(cli.app, lib_args(folder, "--json")).stdout)
    done = write(folder, data["preview_id"], "--json")
    result = json.loads(done.stdout)
    assert result["counts"]["tracks"] == data["counts"]["tracks"]  # unique tracks, as the preview counts
    assert result["into_rekordbox"]["entries"] >= result["counts"]["tracks"]
    assert Path(result["backup"]).is_absolute()  # the engine's folder, never the dj-library's backups/
