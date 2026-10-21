"""The command layer: exit codes, and that a write session only opens when it must."""

import functools
import json
import sys
from contextlib import contextmanager

import pytest
from test_intake import CrateDB, plan_with
from typer.testing import CliRunner

from dj import cli, safety, spotify

runner = CliRunner()


@pytest.fixture
def sessions(monkeypatch, db, live_master_db):
    """Replaces safety.open_db. sessions.log holds the `write` flag of every session, sessions.paths
    the db_path each one was opened with (a read: the snapshot copy; a write: None, the live file)."""

    class Sessions:
        log: list[bool] = []
        paths: list = []
        running = False
        db = None

    s = Sessions()
    s.log, s.paths, s.db = [], [], db
    s.live = live_master_db

    @contextmanager
    def fake_open_db(write=False, db_path=None):
        if write and s.running:
            raise safety.RekordboxRunningError("rekordbox.exe is running.")
        s.log.append(write)
        s.paths.append(db_path)
        yield s.db

    monkeypatch.setattr(safety, "open_db", fake_open_db)
    # master.db writes are Windows-only (test_platform.py); the gate mechanics run on every runner
    monkeypatch.setattr(safety, "DB_WRITE_PLATFORMS", (sys.platform,))
    return s


@pytest.fixture
def tree_file(tmp_path):
    path = tmp_path / "tree.yaml"
    path.write_text("- playlist: inbox\n- folder: sets\n  children:\n    - playlist: a\n")
    return path


def run(*args):
    return runner.invoke(cli.app, [str(a) for a in args])


NO_SUCH_ID = "0" * 12  # the shape of a preview id, never recorded


def approve(sessions, *dry_run, power_mode=True):
    """The flags of a write the DJ said yes to: the dry-run's preview id (R-1102), and
    --power-mode for master.db (R-205). The dry-run's read session is cleared from the log."""
    pid = json.loads(run(*dry_run, "--json").output)["preview_id"]
    sessions.log.clear()
    return ["--apply", *(["--power-mode"] if power_mode else []), "--preview-id", pid]


def test_tree_dry_run_never_opens_a_write_session(sessions, tree_file):
    result = run("tree", "--file", tree_file)
    assert result.exit_code == 0 and "DRY-RUN" in result.output
    assert sessions.log == [False] and sessions.db.calls == []


def test_tree_apply_writes_in_one_session_then_is_idempotent(sessions, tree_file):
    assert run("tree", "--file", tree_file, *approve(sessions, "tree", "--file", tree_file)).exit_code == 0
    assert sessions.log == [False, True, False] and len(sessions.db.calls) == 3
    sessions.log.clear()
    again = run("tree", "--file", tree_file, *approve(sessions, "tree", "--file", tree_file))
    assert "Nothing to create" in again.output and sessions.log == [False]


def test_tree_apply_stops_with_exit_2_while_rekordbox_runs(sessions, tree_file):
    flags = approve(sessions, "tree", "--file", tree_file)
    sessions.running = True
    result = run("tree", "--file", tree_file, *flags)
    assert result.exit_code == cli.EXIT_REKORDBOX_RUNNING and sessions.db.calls == []


def test_tree_conflict_is_exit_1_and_writes_nothing(sessions, tree_file):
    flags = approve(sessions, "tree", "--file", tree_file)  # a valid id, from before the conflict
    sessions.db.seed("playlist", "sets")
    result = run("tree", "--file", tree_file, *flags)
    assert result.exit_code == cli.EXIT_ERROR and sessions.log == [False]
    assert "CONFLICT found. Nothing written." in result.output and "REFUSED" not in result.output


def test_tree_json_is_dry_run_only(sessions, tree_file):
    data = json.loads(run("tree", "--file", tree_file, "--json").output)
    assert data["counts"]["CREATE"] == 3
    assert run("tree", "--file", tree_file, "--json", "--apply").exit_code == cli.EXIT_ERROR
    assert True not in sessions.log


def test_bad_tree_file_is_a_clean_error(sessions, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- playlist: x\n  children: []\n")
    result = run("tree", "--file", bad)
    assert result.exit_code == cli.EXIT_ERROR and sessions.log == []


@pytest.fixture
def plan_file(tmp_path, sessions):
    sessions.db = CrateDB()
    path = tmp_path / "x.plan.json"
    path.write_text(json.dumps(plan_with(("yes", "1"), ("no", "2"), ("pending", "3"))))
    return path


def test_apply_dry_run_reads_only(sessions, plan_file):
    data = json.loads(run("apply", plan_file, "--json").output)
    assert (data["applied"], data["would_add"]) == (False, 1)
    assert sessions.log == [False] and sessions.db.added == []


def test_apply_dry_run_shows_the_local_track_each_add_puts_in_the_crate(sessions, plan_file):
    """The DJ's yes covers the local file, not only the Spotify label: show it from the library."""
    data = json.loads(run("apply", plan_file, "--json").output)
    assert data["adds"] == [{"spotify": "t0", "rb_content_id": "1", "local": "A - t1"}]
    assert "ADD  t0  -> 1 A - t1" in run("apply", plan_file).output


def test_apply_writes_once_and_a_second_apply_opens_no_write_session(sessions, plan_file, tmp_path, monkeypatch):
    monkeypatch.setattr(cli.intake, "Paths", functools.partial(cli.intake.Paths, tmp_path))
    assert run("apply", plan_file, *approve(sessions, "apply", plan_file)).exit_code == 0
    assert sessions.log == [False, True] and sessions.db.added == ["1"]
    sessions.log.clear()
    assert run("apply", plan_file, *approve(sessions, "apply", plan_file)).exit_code == 0
    assert sessions.log == [False] and sessions.db.added == ["1"]
    assert json.loads((tmp_path / "state" / "declined.json").read_text())[0]["spotify_uri"] == "u1"


def test_apply_exit_2_while_rekordbox_runs(sessions, plan_file):
    flags = approve(sessions, "apply", plan_file)
    sessions.running = True
    assert run("apply", plan_file, *flags).exit_code == cli.EXIT_REKORDBOX_RUNNING
    assert sessions.db.added == []


def test_apply_rejects_a_pick_the_tool_never_offered(sessions, tmp_path):
    plan = plan_with(("yes", "1"))
    plan["items"][0]["candidates"] = [{"rb_content_id": "2"}]
    path = tmp_path / "p.json"
    path.write_text(json.dumps(plan))
    result = run("apply", path, "--apply", "--power-mode", "--preview-id", NO_SUCH_ID)
    assert result.exit_code == cli.EXIT_ERROR and "not one of the candidates" in result.output


def test_push_dry_run_asks_for_read_scopes_only(sessions, monkeypatch):
    sessions.db = CrateDB()
    asked = []
    monkeypatch.setattr(spotify, "get_token", lambda scopes: asked.append(scopes) or "tok")
    monkeypatch.setattr(spotify, "Spotify", lambda token: object())
    result = run("push", "funk_base/funk_crate")
    assert result.exit_code == 0 and asked == [spotify.READ_SCOPES] and sessions.log == [False]


def test_missing_env_is_a_clean_error_not_a_traceback(sessions, monkeypatch, tmp_path):
    sessions.db = CrateDB()
    monkeypatch.setattr(spotify, "REPO_ROOT", tmp_path)
    result = run("push", "funk_base/funk_crate")
    assert result.exit_code == cli.EXIT_ERROR and ".env not found" in result.output
    assert "Traceback" not in result.output


def test_tracebacks_never_show_local_variables():
    assert cli.app.pretty_exceptions_show_locals is False
