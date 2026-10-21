"""Q-18 / R-202: every read-only pass reads master.db from a snapshot copy, never the live file.

`dj tree` dry-run, `dj apply` dry-run, `dj copy` dry-run, `dj push`, `dj match`, `dj plan`, `dj tidy
audit|plan|dupes` and the tree print after `dj tree --apply` go through `dj.readers.db.open_snapshot`:
the live file is copied and only the copy is opened. A spy on `safety.open_db` records the path of
every session: a read must never be the live master.db (or None, which open_db resolves to it);
only a write keeps its live session.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_cli import approve, run, sessions  # noqa: F401  (fixture)
from test_intake import LINK, CrateDB, plan_with
from test_playlist_copy import CopyDB, song
from test_tidy_cli import env  # noqa: F401  (fixture)
from tidy_fixtures import make_audio

from dj import cli, intake, safety, spotify
from dj.model import LibraryError
from dj.readers import db as db_reader


def _snapshot_copy(path, live: Path) -> bool:
    """A session path that is a snapshot copy: a master.db in a dj-snapshot-* temp folder, not the
    live file, and the temp folder is gone once the command is done."""
    return (
        path is not None
        and Path(path) != live
        and Path(path).name == "master.db"
        and Path(path).parent.name.startswith("dj-snapshot-")
        and not Path(path).parent.exists()
    )


def assert_reads_from_snapshots(sessions) -> None:  # noqa: F811
    reads = [p for write, p in zip(sessions.log, sessions.paths) if not write]
    assert reads, "the command read nothing"
    assert all(_snapshot_copy(p, sessions.live) for p in reads), sessions.paths


@pytest.fixture
def links(tmp_path, monkeypatch):
    """The inbox loop in a temp repo layout: links.yaml with the crate of CrateDB, an empty pull."""
    paths = intake.Paths(tmp_path)
    paths.links.write_text(f"- spotify: {LINK.spotify}\n  crate: {LINK.crate}\n", encoding="utf-8")
    paths.inbox.mkdir()
    (paths.inbox / f"{LINK.slug}.json").write_text(json.dumps({"tracks": []}), encoding="utf-8")
    monkeypatch.setattr(cli.intake, "default_paths", lambda: paths)
    return paths


def test_tree_dry_run_reads_a_snapshot(sessions, tmp_path):  # noqa: F811
    tree_file = tmp_path / "tree.yaml"
    tree_file.write_text("- playlist: inbox\n", encoding="utf-8")
    assert run("tree", "--file", tree_file).exit_code == 0
    assert sessions.log == [False]
    assert_reads_from_snapshots(sessions)


def test_tree_apply_writes_live_and_prints_the_final_tree_from_a_snapshot(sessions, tmp_path):  # noqa: F811
    tree_file = tmp_path / "tree.yaml"
    tree_file.write_text("- playlist: inbox\n", encoding="utf-8")
    flags = approve(sessions, "tree", "--file", tree_file)
    sessions.paths.clear()
    result = run("tree", "--file", tree_file, *flags)
    assert result.exit_code == 0, result.output
    assert sessions.log == [False, True, False] and "final tree:" in result.output
    assert sessions.paths[1] is None  # the write session: the live file, behind backup and process check
    assert_reads_from_snapshots(sessions)


def test_apply_and_copy_dry_runs_read_a_snapshot(sessions, tmp_path):  # noqa: F811
    sessions.db = CrateDB()
    plan = tmp_path / "x.plan.json"
    plan.write_text(json.dumps(plan_with(("yes", "1"))), encoding="utf-8")
    assert run("apply", plan, "--json").exit_code == 0
    sessions.db = CopyDB([song("1", 1)])
    assert run("copy", "jazzy", "jazz_base/2.1_jazzy", "--json").exit_code == 0
    assert sessions.log == [False, False]
    assert_reads_from_snapshots(sessions)


def test_push_dry_run_reads_a_snapshot(sessions, monkeypatch):  # noqa: F811
    sessions.db = CrateDB()
    monkeypatch.setattr(spotify, "get_token", lambda scopes: "tok")
    monkeypatch.setattr(spotify, "Spotify", lambda token: object())
    assert run("push", LINK.crate, "--json").exit_code == 0
    assert sessions.log == [False]
    assert_reads_from_snapshots(sessions)


def test_match_and_plan_read_a_snapshot(sessions, links):  # noqa: F811
    sessions.db = CrateDB()
    assert run("match", LINK.spotify, "--json").exit_code == 0
    result = run("plan", LINK.spotify, "--json")
    assert result.exit_code == 0, result.output
    assert sessions.log == [False, False]
    assert_reads_from_snapshots(sessions)


def test_tidy_audit_plan_and_dupes_read_a_snapshot(env):  # noqa: F811
    make_audio(env.root / "Huerta - Low Five.mp3")
    for command in ("audit", "plan", "dupes"):
        result = run("tidy", command, "--folder", env.root, "--config", env.yaml, "--json")
        assert result.exit_code == 0, result.output
    assert env.sessions.log == [False, False, False]
    assert_reads_from_snapshots(env.sessions)


def test_no_read_only_command_opens_the_live_file_through_the_real_open_db(monkeypatch, tmp_path, live_master_db):
    """The spy below is the real safety.open_db's own seam: a connection to the live master.db
    fails the test. Every read-only command connects to a snapshot copy only."""
    connected: list[Path] = []
    db = CrateDB()

    class Tx:
        def rollback(self):
            pass

        def close(self):
            pass

    def connect(path, quiet=False):
        assert Path(path) != live_master_db, "a read-only pass opened the live master.db"
        connected.append(Path(path))
        return NS(**{name: getattr(db, name) for name in ("get_playlist", "get_content")},
                  rollback=Tx().rollback, close=Tx().close)

    monkeypatch.setattr(safety, "_connect", connect)
    plan = tmp_path / "x.plan.json"
    plan.write_text(json.dumps(plan_with(("yes", "1"))), encoding="utf-8")
    assert run("apply", plan, "--json").exit_code == 0
    monkeypatch.setattr(spotify, "get_token", lambda scopes: "tok")
    monkeypatch.setattr(spotify, "Spotify", lambda token: object())
    assert run("push", LINK.crate, "--json").exit_code == 0
    assert len(connected) == 2 and all(p.parent.name.startswith("dj-snapshot-") for p in connected)


def test_open_snapshot_finds_master_db_itself_and_says_when_there_is_none(monkeypatch, live_master_db):
    seen = []

    @contextmanager
    def spy(write=False, db_path=None):
        seen.append((write, db_path, db_path.read_bytes()))
        yield "db"

    monkeypatch.setattr(safety, "open_db", spy)
    with db_reader.open_snapshot() as db:
        assert db == "db"
    ((write, path, copied),) = seen
    assert write is False and path != live_master_db and copied == live_master_db.read_bytes()
    assert not path.parent.exists()  # the copy is cleaned up

    def missing():
        raise FileNotFoundError("master.db not found (looked at: nowhere)")

    monkeypatch.setattr(safety, "find_master_db", missing)
    with pytest.raises(LibraryError, match="master.db not found"):
        with db_reader.open_snapshot():
            pass


def test_a_snapshot_that_cannot_be_taken_is_one_error_line(sessions, monkeypatch, tmp_path):  # noqa: F811
    tree_file = tmp_path / "tree.yaml"
    tree_file.write_text("- playlist: inbox\n", encoding="utf-8")

    def missing():
        raise FileNotFoundError("master.db not found (looked at: nowhere)")

    monkeypatch.setattr(safety, "find_master_db", missing)
    for args in (["tree", "--file", tree_file], ["copy", "a", "b"], ["push", "a"]):
        result = run(*args)
        assert result.exit_code == cli.EXIT_ERROR and "ERROR master.db not found" in result.output, args
        assert "Traceback" not in result.output
    assert sessions.log == []
