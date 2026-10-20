import sys

import pytest

from dj import safety


@pytest.fixture
def fake_env(db, tmp_path, monkeypatch):
    """A fake DB dir + patched process check, connector and backup verification."""
    db_path = tmp_path / "rb" / "master.db"
    db_path.parent.mkdir()
    db_path.write_bytes(b"not a real database")
    (db_path.parent / safety.PLAYLIST_XML).write_text("<MASTER_PLAYLIST/>")
    state = {"running": False}
    monkeypatch.setattr(safety, "rekordbox_running", lambda: state["running"])
    monkeypatch.setattr(safety, "_connect", lambda path, quiet=False: db)
    monkeypatch.setattr(safety, "_verify_opens", lambda copy: None)
    monkeypatch.setattr(safety, "BACKUP_DIR", tmp_path / "backups")
    # write sessions are Windows-only (test_platform.py); the write mechanics run on every runner
    monkeypatch.setattr(safety, "DB_WRITE_PLATFORMS", (sys.platform,))
    return db_path, state


def test_read_only_never_commits(db, fake_env):
    db_path, _ = fake_env
    with safety.open_db(write=False, db_path=db_path):
        pass
    assert (db.commits, db.rollbacks, db.closes) == (0, 1, 1)
    assert not (db_path.parent.parent / "backups").exists()


def test_write_backs_up_then_commits_exactly_once(db, fake_env, tmp_path):
    db_path, _ = fake_env
    with safety.open_db(write=True, db_path=db_path):
        pass
    assert (db.commits, db.rollbacks, db.closes) == (1, 0, 1)
    copies = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert len(copies) == 2
    assert copies[0].startswith("masterPlaylists6_") and copies[0].endswith(".xml")
    assert copies[1].startswith("master_") and copies[1].endswith(".db")


def test_exception_rolls_back_and_never_commits(db, fake_env):
    db_path, _ = fake_env
    with pytest.raises(KeyError) as info:
        with safety.open_db(write=True, db_path=db_path):
            raise KeyError("boom")
    assert (db.commits, db.rollbacks, db.closes) == (0, 1, 1)
    assert any("unchanged" in note for note in info.value.__notes__)


def test_failure_reports_files_that_changed_anyway(db, fake_env):
    db_path, _ = fake_env
    with pytest.raises(KeyError) as info:
        with safety.open_db(write=True, db_path=db_path):
            db_path.write_bytes(b"half-written")
            raise KeyError("boom")
    assert any("master.db" in note and "Restore" in note for note in info.value.__notes__)


def test_refuses_to_write_while_rekordbox_runs(db, fake_env, tmp_path):
    db_path, state = fake_env
    state["running"] = True
    with pytest.raises(safety.RekordboxRunningError):
        with safety.open_db(write=True, db_path=db_path):
            pytest.fail("must not yield")
    assert (db.commits, db.closes) == (0, 0)
    assert not (tmp_path / "backups").exists()


def test_no_commit_if_rekordbox_starts_mid_run(db, fake_env):
    db_path, state = fake_env
    with pytest.raises(safety.RekordboxRunningError):
        with safety.open_db(write=True, db_path=db_path):
            state["running"] = True
    assert (db.commits, db.rollbacks, db.closes) == (0, 1, 1)


def test_backup_detects_a_bad_copy(fake_env, tmp_path, monkeypatch):
    db_path, _ = fake_env
    monkeypatch.setattr(safety.shutil, "copy2", lambda src, dst: dst.write_bytes(b"truncated"))
    with pytest.raises(safety.BackupError):
        safety.backup(db_path, tmp_path / "bk")


def test_backup_must_open(fake_env, tmp_path, monkeypatch):
    db_path, _ = fake_env

    def broken(path, quiet=False):
        raise RuntimeError("file is not a database")

    monkeypatch.undo()
    monkeypatch.setattr(safety, "_connect", broken)
    with pytest.raises(safety.BackupError, match="does not open"):
        safety.backup(db_path, tmp_path / "bk")


def test_backup_includes_wal_and_shm(fake_env, tmp_path):
    db_path, _ = fake_env
    db_path.with_name("master.db-wal").write_bytes(b"wal")
    bk = safety.backup(db_path, tmp_path / "bk")
    assert sorted(p.name.split("_")[0] + p.suffix for p in bk.files.values()) == [
        "master.db",
        "master.db-wal",
        "masterPlaylists6.xml",
    ]
    assert bk.changed_sources() == []


@pytest.mark.parametrize(
    "stdout, expected",
    [
        ('"rekordbox.exe","1234","Console","1","512,000 K"\n', True),
        ('"Rekordbox.EXE","1234","Console","1","512,000 K"\n', True),
        ("INFO: No tasks are running which match the specified criteria.\n", False),
        ('"rekordboxAgent.exe","99","Console","1","10 K"\n', False),
        ("", False),
    ],
)
def test_rekordbox_running_parses_tasklist(monkeypatch, stdout, expected):
    from types import SimpleNamespace

    monkeypatch.undo()  # the real function, with a fake tasklist
    seen = []
    monkeypatch.setattr(safety.sys, "platform", "win32")
    monkeypatch.setattr(safety.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or SimpleNamespace(stdout=stdout))
    assert safety.rekordbox_running() is expected
    # absolute, not from PATH; separators normalised so the check also runs on a POSIX host
    assert seen[0][0].lower().replace("/", "\\").endswith("system32\\tasklist.exe")


def test_rekordbox_running_refuses_to_guess_off_windows(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(safety.sys, "platform", "linux")
    with pytest.raises(safety.SafetyError):
        safety.rekordbox_running()


def test_find_master_db_override_must_exist(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setenv("DJ_MASTER_DB", str(tmp_path / "nope.db"))
    with pytest.raises(FileNotFoundError):
        safety.find_master_db()


# -- the conftest guard itself: no test reaches the network (CLAUDE.md, Tests) -----------------


def test_the_suite_blocks_dns_connect_ex_and_udp_not_only_connect():
    import socket

    with pytest.raises(AssertionError, match="network"):
        socket.getaddrinfo("api.spotify.com", 443)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(AssertionError, match="network"):
            sock.connect_ex(("192.0.2.1", 443))  # TEST-NET-1: never routed
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with pytest.raises(AssertionError, match="network"):
            sock.sendto(b"x", ("192.0.2.1", 53))
    assert socket.getaddrinfo("127.0.0.1", 80)  # the machine itself still resolves
