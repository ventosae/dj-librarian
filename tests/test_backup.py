"""dj.backup (W-37, D-31, R-206): a verified copy of the rekordbox database in <dj-library>/backups/.

Fake db only: the stand-in master.db files are placeholders and `safety._connect` gives the fake
pyrekordbox database (xml_fixtures), with a `session` that answers PRAGMA quick_check. Checks: a fresh
copy (db + wal + shm + playlist XML in one pass), dedupe, a verify failure that is kept and flagged,
nothing deleted, nothing written into the Pioneer folder, the refusals, RESTORE.md per OS, --list
totals, and the CLI and MCP surfaces (no preview id; the write-gate hook does not match dj_backup).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import xml_fixtures as fx
from test_hook_gate import GATE, PREFIXES, matcher, mcp_tools
from typer.testing import CliRunner

from dj import backup as B
from dj import cli, libfolder, safety
from dj import mcp_server as m

NOW = datetime(2026, 10, 25, 14, 32, 5, tzinfo=timezone(timedelta(hours=11)))
runner = CliRunner()


class Session:
    def __init__(self, answer):
        self.answer, self.statements = list(answer), []

    def execute(self, statement):
        self.statements.append(str(statement))
        answer = self.answer
        return type("Result", (), {"scalars": lambda _: type("S", (), {"all": lambda _: answer})()})()


@pytest.fixture
def pioneer(tmp_path, monkeypatch):
    """rekordbox's folder with stand-in files; `check` is what PRAGMA quick_check answers."""
    db = fx.write_master_files(tmp_path / "Pioneer" / "rekordbox", fx.with_streaming())
    state = type("State", (), {"check": ["ok"], "opened": [], "db": db})()

    def connect(db_path, quiet=False):
        state.opened.append(Path(db_path))
        fake = fx.fake_db(fx.with_streaming())
        fake.session = Session(state.check)
        return fake

    monkeypatch.setattr(safety, "_connect", connect)
    monkeypatch.setattr(safety, "find_master_db", lambda: db)
    return state


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "Music" / "dj-library"
    libfolder.scaffold(root, device="windows", today=NOW.date())
    return root


def files_of(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def take(lib, minutes=0, **kw):
    return B.take_backup(lib, now=NOW + timedelta(minutes=minutes), **kw)


# -- a fresh backup ----------------------------------------------------------------------------------


def test_a_fresh_backup_copies_the_four_files_verifies_and_describes_them(lib, pioneer):
    before = files_of(pioneer.db.parent)
    result = take(lib)
    folder = lib / "backups" / "rekordbox-2026-10-25-1432"
    assert result.status == "created" and result.verified and result.folder == folder
    names = ["master.db", "master.db-wal", "master.db-shm", "masterPlaylists6.xml"]
    for name in names:
        assert (folder / name).read_bytes() == (pioneer.db.parent / name).read_bytes()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert [f["name"] for f in manifest["files"]] == names
    assert all(f["sha256"] == safety.sha256(folder / f["name"]) and f["size"] == (folder / f["name"]).stat().st_size
               for f in manifest["files"])  # fmt: skip
    assert manifest["verified"] is True and manifest["reason"] is None and manifest["rekordbox"] == "7.2.18"
    assert manifest["date"] == "2026-10-25T14:32:05+11:00" and manifest["taken_from"] == str(pioneer.db.parent)
    assert manifest["tracks"] == {"rows": 27, "tracks": 26, "local": 24, "streaming": 2,
                                  "services": {"beatport": 1, "spotify": 1}}  # one soft-deleted ghost row
    assert "rekordbox_running" in manifest and manifest["tool"] == "dj-librarian"
    assert (folder / "RESTORE.md").is_file() and not (folder / "NOT-VERIFIED.md").exists()
    assert (lib / "backups" / ".gitignore").read_text(encoding="utf-8").splitlines()[-1] == "*"
    assert result.line == f"Backup: backups/rekordbox-2026-10-25-1432 · {B.size_text(result.size)} · verified"
    assert files_of(pioneer.db.parent) == before  # rekordbox's folder is only read


def test_the_copy_is_verified_on_a_scratch_copy_so_its_hashed_bytes_are_never_opened(lib, pioneer):
    take(lib)
    assert pioneer.opened and all(p.parent != lib / "backups" / "rekordbox-2026-10-25-1432" for p in pioneer.opened)
    assert all(not p.exists() for p in pioneer.opened)  # the scratch copy is gone
    assert all(p.parent != pioneer.db.parent for p in pioneer.opened)  # the live file is never opened


def test_without_wal_and_shm_only_the_database_and_the_playlist_xml(lib, pioneer):
    for side in ("master.db-wal", "master.db-shm"):
        (pioneer.db.parent / side).unlink()
    result = take(lib)
    assert sorted(p.name for p in result.folder.iterdir() if p.name.startswith("master")) == [
        "master.db", "masterPlaylists6.xml"]  # fmt: skip


def test_a_snapshot_retry_removes_nothing_in_the_backup_folder(lib, pioneer, monkeypatch):
    """rekordbox checkpoints during the copy and the -wal goes: the snapshot copies again and drops
    its stale -wal copy, in the scratch folder only (hard rule 1 holds under backups/)."""
    import os
    import shutil

    from dj.readers import db as db_reader

    removed = []
    real_unlink, real_remove, real_rmtree = Path.unlink, os.unlink, shutil.rmtree
    stamps = iter([(1, 1), (1, 1), (2, 2), (2, 2)])  # master.db and -wal: changed on the first try

    def stamp(path):
        if path.name == "master.db-wal" and not path.exists():
            return None
        return next(stamps, (3, 3)) if path.parent == pioneer.db.parent else (0, 0)

    real_copy2 = shutil.copy2

    def first_copy_then_checkpoint(src, dst, *a, **k):
        out = real_copy2(src, dst, *a, **k)
        if Path(src).name == "master.db-shm" and (pioneer.db.parent / "master.db-wal").exists():
            real_unlink(pioneer.db.parent / "master.db-wal")  # rekordbox checkpointed the WAL away
        return out

    monkeypatch.setattr(db_reader, "_stamp", stamp)
    monkeypatch.setattr(db_reader.shutil, "copy2", first_copy_then_checkpoint)
    monkeypatch.setattr(db_reader.time, "sleep", lambda s: None)
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (removed.append(self), real_unlink(self, *a, **k))[1])
    monkeypatch.setattr(os, "unlink", lambda p, *a, **k: (removed.append(Path(p)), real_remove(p, *a, **k))[1])
    monkeypatch.setattr(shutil, "rmtree", lambda p, *a, **k: (removed.append(Path(p)), real_rmtree(p, *a, **k))[1])
    result = take(lib)
    assert result.status == "created" and not (result.folder / "master.db-wal").exists()
    assert any(p.name == "master.db-wal" for p in removed)  # the stale copy went, in the scratch folder
    # write_new_text's own create-only temp files (`.<name>.<rand>.tmp`, Q-27) aside, nothing under backups/
    under = [p for p in removed if p.resolve().is_relative_to((lib / "backups").resolve())]
    assert all(p.name.startswith(".") and p.name.endswith(".tmp") for p in under), under


# -- dedupe -------------------------------------------------------------------------------------------


def test_an_unchanged_database_is_not_copied_again(lib, pioneer):
    first = take(lib)
    again = take(lib, minutes=90)
    assert again.status == "unchanged" and again.folder == first.folder and again.verified
    assert again.line == "Backup: unchanged since 2026-10-25 14:32 · backups/rekordbox-2026-10-25-1432"
    assert [p.name for p in (lib / "backups").iterdir() if p.is_dir()] == [first.folder.name]


def test_a_changed_wal_alone_is_a_change(lib, pioneer):
    take(lib)
    (pioneer.db.parent / "master.db-wal").write_bytes(b"wal: rekordbox wrote since")
    assert take(lib, minutes=5).status == "created"


def test_two_changes_in_one_minute_get_their_own_folders_and_nothing_is_deleted(lib, pioneer):
    first = take(lib)
    kept = files_of(first.folder)
    pioneer.db.write_bytes(b"SQLite format 3\x00 changed")
    second = take(lib)
    assert second.folder.name == "rekordbox-2026-10-25-1432-2"
    pioneer.db.write_bytes(b"SQLite format 3\x00 changed again")
    take(lib, minutes=60 * 24 * 40)  # weeks later: still every backup kept
    assert files_of(first.folder) == kept
    assert len([p for p in (lib / "backups").iterdir() if p.is_dir()]) == 3


# -- a copy that does not verify ---------------------------------------------------------------------


def test_a_failed_quick_check_keeps_the_copy_and_flags_it(lib, pioneer):
    pioneer.check = ["*** in database main ***", "Page 5 is never used"]
    result = take(lib)
    assert result.status == "unverified" and not result.verified and result.folder.is_dir()
    manifest = json.loads((result.folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["verified"] is False and manifest["reason"].startswith("quick_check: *** in database main")
    assert (result.folder / "NOT-VERIFIED.md").is_file() and not (result.folder / "RESTORE.md").exists()
    assert result.line.endswith("Close rekordbox, then run the backup again.") and "NOT verified" in result.line
    pioneer.check = ["ok"]
    retry = take(lib, minutes=1)  # an unverified copy never counts as "unchanged"
    assert retry.status == "created" and result.folder.is_dir()


def test_a_copy_that_does_not_open_is_kept_and_flagged(lib, pioneer, monkeypatch):
    def broken(db_path, quiet=False):
        raise RuntimeError("file is not a database " + "ab" * 40)  # a long hex run is blanked (the key)

    monkeypatch.setattr(safety, "_connect", broken)
    result = take(lib)
    assert result.status == "unverified" and "it does not open: RuntimeError: file is not a database" in result.reason
    assert "abab" not in result.reason and (result.folder / "master.db").is_file()


# -- refusals ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("cloud", ["OneDrive", "Dropbox", "iCloud Drive", "Google Drive"])
def test_a_library_in_a_synced_folder_is_refused_and_nothing_is_written(tmp_path, pioneer, cloud):
    root = tmp_path / cloud / "dj-library"
    libfolder.scaffold(root, device="mac", today=NOW.date())
    with pytest.raises(B.BackupError, match="syncs to the cloud") as caught:
        take(root)
    assert caught.value.reason == "synced" and not (root / "backups").exists()


def test_a_folder_that_is_not_a_dj_library_is_refused(tmp_path, pioneer):
    (tmp_path / "plain").mkdir()
    with pytest.raises(B.BackupError, match="not a dj-library") as caught:
        take(tmp_path / "plain")
    assert caught.value.reason == "not_library" and not (tmp_path / "plain" / "backups").exists()


def test_a_library_inside_rekordbox_folder_is_refused(pioneer):
    root = pioneer.db.parent / "dj-library"
    libfolder.scaffold(root, device="mac", today=NOW.date())
    with pytest.raises(B.BackupError, match="rekordbox's own folder") as caught:
        take(root)
    assert caught.value.reason == "pioneer" and not (root / "backups").exists()


def test_no_master_db_is_an_error_not_a_refusal(lib, monkeypatch):
    monkeypatch.setattr(safety, "find_master_db", lambda: (_ for _ in ()).throw(FileNotFoundError("master.db not found")))
    with pytest.raises(B.BackupError, match="master.db not found") as caught:
        take(lib)
    assert caught.value.reason == "no_db"


# -- RESTORE.md ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("platform, close, find", [
    ("win32", "File > Exit", "%APPDATA%\\Pioneer\\rekordbox"),
    ("darwin", "rekordbox > Quit rekordbox", "~/Library/Pioneer/rekordbox"),
])  # fmt: skip
def test_restore_steps_name_the_real_folder_for_each_os(lib, pioneer, platform, close, find):
    result = take(lib, platform=platform)
    text = (result.folder / "RESTORE.md").read_text(encoding="utf-8")
    assert text.startswith("# Restore rekordbox from this backup\n")
    assert close in text and find in text and f"`{pioneer.db.parent}`" in text
    for name in ("master.db", "master.db-wal", "master.db-shm", "masterPlaylists6.xml"):
        assert f"   - `{name}`" in text
    steps = re.findall(r"^(\d)\. ", text, flags=re.MULTILINE)
    assert steps == ["1", "2", "3", "4", "5"] and "Move `master.db`" in text  # today's files aside first
    assert "26 tracks (24 local, 2 streaming)" in text and B.ALSO in text


# -- --list ------------------------------------------------------------------------------------------


def test_list_gives_every_backup_newest_first_and_the_total(lib, pioneer):
    first = take(lib)
    pioneer.db.write_bytes(b"SQLite format 3\x00 changed")
    pioneer.check = ["bad page"]
    second = take(lib, minutes=3)
    listing = B.list_backups(lib)
    assert listing["count"] == 2 and listing["verified"] == 1
    assert listing["total_size"] == first.size + second.size
    assert [r["folder"] for r in listing["backups"]] == [str(second.folder), str(first.folder)]
    assert listing["line"] == f"2 backups · 1 verified · {B.size_text(first.size + second.size)} in all"


def test_list_of_a_library_without_backups(lib):
    assert B.list_backups(lib) == {"count": 0, "verified": 0, "total_size": 0, "line": "No backups yet.", "backups": []}


# -- the CLI ------------------------------------------------------------------------------------------


def test_dj_backup_prints_the_line_and_logs_only_a_change(lib, pioneer):
    done = runner.invoke(cli.app, ["backup", "--library", str(lib)])
    assert done.exit_code == 0, done.output
    assert re.fullmatch(r"Backup: backups/rekordbox-\d{4}-\d\d-\d\d-\d{4} · [\d.]+ (B|KB) · verified\n", done.output)
    again = json.loads(runner.invoke(cli.app, ["backup", "--library", str(lib), "--json"]).output)
    assert again["status"] == "unchanged" and again["log"] is None
    log = (lib / "log.md").read_text(encoding="utf-8")
    assert log.count(" backup -> 4 files; backups/rekordbox-") == 1


def test_dj_backup_list_and_json(lib, pioneer):
    runner.invoke(cli.app, ["backup", "--library", str(lib)])
    listing = json.loads(runner.invoke(cli.app, ["backup", "--library", str(lib), "--list", "--json"]).output)
    assert listing["count"] == 1 and listing["backups"][0]["verified"] is True and listing["backups"][0]["tracks"] == 26
    human = runner.invoke(cli.app, ["backup", "--library", str(lib), "--list"]).output
    assert human.startswith("1 backups · 1 verified · ") and "verified" in human.splitlines()[1]


def test_dj_backup_follows_dj_library_when_no_folder_is_given(lib, pioneer, monkeypatch):
    monkeypatch.setenv("DJ_LIBRARY", str(lib))
    assert runner.invoke(cli.app, ["backup"]).exit_code == 0
    assert (lib / "backups").is_dir()


def test_dj_backup_refusal_is_exit_2_with_refused(tmp_path, pioneer):
    root = tmp_path / "OneDrive" / "dj-library"
    libfolder.scaffold(root, device="windows", today=NOW.date())
    done = runner.invoke(cli.app, ["backup", "--library", str(root)])
    assert done.exit_code == 2 and done.stderr.startswith("REFUSED ") and not (root / "backups").exists()


# -- MCP and the write-gate hook ----------------------------------------------------------------------


def test_dj_backup_tool_runs_the_fixed_command_without_a_preview_id(monkeypatch):
    calls = []
    monkeypatch.setattr(m, "run_dj_data", lambda options, positionals=(), as_json=True: calls.append(options) or {"ok": True})
    json.loads(m.dj_backup())
    json.loads(m.dj_backup(list_backups=True))
    assert calls == [["backup"], ["backup", "--list"]]
    tool = mcp_tools()["dj_backup"]
    assert set(tool.input_schema["properties"]) == {"list_backups"}  # no path, no preview_id
    assert tool.annotations.read_only_hint is False and tool.annotations.destructive_hint is False


@pytest.mark.parametrize("prefix", PREFIXES)
def test_the_write_gate_hook_does_not_match_dj_backup(prefix):
    assert not re.search(matcher(), prefix + "dj_backup")
    namespace: dict = {}
    exec(compile(GATE.read_text(encoding="utf-8"), str(GATE), "exec"), namespace)  # noqa: S102  (our own file)
    assert namespace["is_write_tool"](prefix + "dj_backup") is False
