"""Direct write into rekordbox on every OS: the one chain, on a Mac and on Windows.

    preview id -> rekordbox not running -> verified backup -> one transaction, rollback on failure

Fake db only. `sys.platform` is patched to "darwin" and to "win32", so both paths run on every
runner. What is real: `safety.open_db`, the process check up to its `subprocess.run` (`pgrep -x
rekordbox` on a Mac, `tasklist ... rekordbox.exe` on Windows), and `safety.backup` (copies onto
tmp_path, hashes, opens the copy). What is fake: the process list, and the pyrekordbox connection
(`TxDB`: the fixture rows, writes staged until commit; `FileDB` also rewrites the stand-in
master.db on commit, as a real commit changes the file). Nothing live.
"""

from __future__ import annotations

import json
import sys
from itertools import count
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import xml_fixtures as fx
from test_build_structure import DAY, _make_library
from typer.testing import CliRunner

from dj import cli, db_write, libfolder, safety
from dj.gate import Gate

runner = CliRunner()
PROCESS = {"darwin": "rekordbox", "win32": "rekordbox.exe"}


class TxDB(fx.SpecDB):
    """The fixture rows, plus create_playlist_folder / create_playlist / add_to_playlist staged until
    commit. `fail_at`: the add_to_playlist call (1-based) that raises, as a failing database would."""

    def __init__(self, base: fx.SpecDB):
        super().__init__(base.contents, base.playlists)
        self.new_rows: list = []
        self.new_songs: list = []
        self.commits, self.adds, self.fail_at = 0, 0, None
        self._ids = count(90_000)

    def get_playlist(self, **kwargs):
        assert set(kwargs) == {"ParentID"}
        return fx.Query([p for p in self.playlists + self.new_rows if p.ParentID == kwargs["ParentID"]])

    def _create(self, attribute: int, name: str, parent, kwargs) -> NS:
        assert not kwargs, f"only name/parent, never {sorted(kwargs)} (no seq=)"
        parent_id = "root" if parent is None else (parent.ID if hasattr(parent, "ID") else str(parent))
        seq = sum(p.ParentID == parent_id for p in self.playlists + self.new_rows) + 1
        row = fx._playlist_row(str(next(self._ids)), name, attribute, parent_id, seq)
        self.new_rows.append(row)
        return row

    def create_playlist_folder(self, name, parent=None, **kwargs):
        return self._create(1, name, parent, kwargs)

    def create_playlist(self, name, parent=None, **kwargs):
        return self._create(0, name, parent, kwargs)

    def add_to_playlist(self, playlist, content, **kwargs):
        assert not kwargs, "append only: never track_no"
        assert playlist.Attribute == 0, "tracks go into a normal playlist"
        self.adds += 1
        if self.fail_at == self.adds:
            raise RuntimeError("database disk image is malformed")
        self.new_songs.append((playlist, fx._song(str(content), len(playlist.Songs) + 1)))

    def commit(self):
        self.commits += 1
        self.playlists += self.new_rows
        for playlist, song in self.new_songs:
            playlist.Songs.append(song)
        self.new_rows, self.new_songs = [], []

    def rollback(self):
        self.rollbacks += 1
        self.new_rows, self.new_songs = [], []

    def state(self) -> str:
        """The committed rows, as text: what rekordbox would read back."""
        rows = [[p.ID, p.Name, p.Attribute, p.ParentID, p.Seq, [s.ContentID for s in p.Songs]] for p in self.playlists]
        return json.dumps(rows)

    def tree(self, parent: str = "root") -> list:
        kids = sorted((p for p in self.playlists if p.ParentID == parent and not p.rb_local_deleted), key=lambda p: p.Seq)
        return [(p.Name, [s.ContentID for s in p.Songs] if p.Attribute != 1 else self.tree(p.ID)) for p in kids]


class FileDB(TxDB):
    """A TxDB whose commit also rewrites the stand-in master.db, as a real commit changes the file."""

    def __init__(self, base: fx.SpecDB, live: Path):
        super().__init__(base)
        self.live = live

    def commit(self):
        super().commit()
        self.live.write_bytes(b"SQLite format 3\x00 " + self.state().encode("utf-8"))


def files(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


@pytest.fixture(params=sorted(PROCESS))
def rb(request, monkeypatch, tmp_path):
    """rekordbox on this OS: its folder on disk, the fake connection, the process list."""
    monkeypatch.setattr(sys, "platform", request.param)
    live = fx.write_master_files(tmp_path / "Pioneer" / "rekordbox")
    state = NS(platform=request.param, live=live, db=FileDB(fx.fake_db(), live), backups=tmp_path / "engine-backups",
               running=False, check_fails=False, checks=[])  # fmt: skip

    def process_list(cmd, **kwargs):
        cmd = [str(part) for part in cmd]
        state.checks.append(cmd)
        if state.check_fails:
            raise OSError(2, "No such file or directory", cmd[0])
        if request.param == "win32":
            assert Path(cmd[0]).name == "tasklist.exe" and "IMAGENAME eq rekordbox.exe" in cmd
            out = '"rekordbox.exe","4242","Console","1","300,000 K"\n' if state.running else "INFO: No tasks are running.\n"
            return NS(returncode=0, stdout=out, stderr="")
        assert cmd == ["/usr/bin/pgrep", "-x", "rekordbox"]
        return NS(returncode=0 if state.running else 1, stdout="4242\n" if state.running else "", stderr="")

    monkeypatch.setattr(safety.subprocess, "run", process_list)
    monkeypatch.setattr(safety, "find_master_db", lambda: live)
    monkeypatch.setattr(safety, "_connect", lambda path, quiet=False: state.db)
    monkeypatch.setattr(safety, "BACKUP_DIR", state.backups)
    return state


@pytest.fixture
def folder(tmp_path, rb):
    f = _make_library(tmp_path)
    libfolder.update_meta(f.root, today=DAY, source="db")
    return f


def args(folder, *more):
    return ["library", "build", "lanes", "--library", str(folder.root), *more]


def preview_id(folder) -> str:
    done = runner.invoke(cli.app, args(folder, "--json"))
    assert done.exit_code == 0, done.output
    data = json.loads(done.stdout)
    assert data["into_rekordbox"] == db_write.PREVIEW_LINE and data["preview_id"]
    return data["preview_id"]


def write(folder, pid):
    return runner.invoke(cli.app, args(folder, "--apply", "--preview-id", pid))


def test_it_writes_after_the_process_check_and_a_verified_backup_in_one_commit(folder, rb):
    pid = preview_id(folder)
    before = files(rb.live.parent)
    rb.checks.clear()
    done = write(folder, pid)
    assert done.exit_code == 0, done.output
    assert done.stdout.startswith("Wrote into rekordbox: 1 folder(s), 4 playlist(s), ")
    assert rb.checks and all(PROCESS[rb.platform] in " ".join(cmd) for cmd in rb.checks)  # this OS's process name
    assert "Lanes" in dict(rb.db.tree()) and rb.db.commits == 1
    assert rb.live.read_bytes() != before["master.db"]  # the commit changed the file
    backup = {p.name.split("_")[0] + p.suffix: p.read_bytes() for p in rb.backups.iterdir()}
    assert backup["master.db"] == before["master.db"] and len(backup) == len(before)  # the copy is the file as it was
    assert Gate(folder.cache).load(pid).written == "master.db"


def test_a_failure_mid_write_rolls_back_and_leaves_the_db_file_byte_identical(folder, rb):
    pid = preview_id(folder)
    before, rows = files(rb.live.parent), rb.db.state()
    rb.db.fail_at = 3  # the third track
    done = write(folder, pid)
    assert done.exit_code == 1
    assert done.stderr.strip() == ("ERROR The write stopped (RuntimeError: database disk image is malformed). "
                                   "Rolled back: nothing written.")  # fmt: skip
    assert files(rb.live.parent) == before  # master.db, -wal, -shm, masterPlaylists6.xml: byte for byte
    assert rb.db.state() == rows and rb.db.commits == 0 and rb.db.rollbacks >= 1
    assert not Gate(folder.cache).load(pid).used  # nothing was written: the id is still good


def test_it_refuses_while_rekordbox_runs_and_when_the_check_cannot_run(folder, rb):
    pid = preview_id(folder)
    before, rows = files(rb.live.parent), rb.db.state()
    rb.running = True
    done = write(folder, pid)
    assert done.exit_code == 2 and done.stderr.strip() == f"STOP {db_write.CLOSE_FIRST}"
    rb.running, rb.check_fails = False, True
    blind = write(folder, pid)
    assert blind.exit_code == 1 and "Cannot tell whether rekordbox runs" in blind.stderr
    assert not rb.backups.exists() and files(rb.live.parent) == before  # refused before the backup
    assert rb.db.state() == rows and rb.db.commits == 0
    rb.check_fails = False
    assert write(folder, pid).exit_code == 0  # rekordbox closed: the same id writes


def test_it_refuses_a_used_preview_id(folder, rb):
    pid = preview_id(folder)
    rows = list(rb.db.playlists)
    assert write(folder, pid).exit_code == 0
    rb.db.playlists = rows  # as if the DJ deleted it in rekordbox: the content is the preview's again
    again = write(folder, pid)
    assert again.exit_code == 1 and again.stderr.startswith("REFUSED ") and "used" in again.stderr
    none = write(folder, "")
    assert none.exit_code == 1 and none.stderr.startswith("REFUSED ")
    assert rb.db.commits == 1 and len(list(rb.backups.iterdir())) == len(files(rb.live.parent))  # one backup
