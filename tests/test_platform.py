"""Per-OS behaviour: the Mac port (R-203, R-1302) and the read path on both OS (R-201).

sys.platform is monkeypatched, so every OS branch runs on every CI runner. No test runs a real
pgrep or tasklist (subprocess.run is replaced), opens a real master.db (safety._connect is a
fake) or looks outside tmp_path (Path.home and the env are replaced).
"""

import functools
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
import xml_fixtures as fx
from test_cli import sessions  # noqa: F401  (fixture used by `env`)
from test_intake import CrateDB, plan_with
from test_playlist_copy import CopyDB, song
from test_tidy_cli import _planned, env  # noqa: F401  (fixture)
from tidy_fixtures import make_audio
from typer.testing import CliRunner

from dj import cli, safety
from dj import mcp_server as m
from dj.readers import db as db_reader
from dj.readers.db import read_db
from dj.tidy import tags

# conftest replaces find_master_db with a refusal in every test; these are the real ones
REAL_FIND_MASTER_DB = safety.find_master_db
REAL_RUNNING = safety.rekordbox_running
REAL_OPEN_DB = safety.open_db  # test_cli's `sessions` fixture replaces it
RUNNING_CSV = '"rekordbox.exe","1234","Console","1","512,000 K"\n'
NOT_RUNNING_CSV = "INFO: No tasks are running which match the specified criteria.\n"
WINDOWS_KEYS = ("ProgramFiles", "SystemRoot", "APPDATA", "LOCALAPPDATA", "USERPROFILE")

runner = CliRunner()


def on(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)


class FakeRun:
    """Stands in for subprocess.run: records every command, answers with one exit code."""

    def __init__(self, returncode=0, stdout="", raises=None):
        self.returncode, self.stdout, self.raises = returncode, stdout, raises
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="")


@pytest.fixture
def fake_run(monkeypatch):
    def install(**kwargs):
        run = FakeRun(**kwargs)
        monkeypatch.setattr(safety.subprocess, "run", run)
        return run

    return install


# -- process check (R-203) ---------------------------------------------------------------


def test_mac_process_name():
    assert safety.MAC_PROCESS_NAME == "rekordbox" and safety.PROCESS_NAME == "rekordbox.exe"
    assert safety.PGREP == "/usr/bin/pgrep"


@pytest.mark.parametrize("code, expected", [(0, True), (1, False)])
def test_darwin_asks_pgrep_by_absolute_path(monkeypatch, fake_run, code, expected):
    on(monkeypatch, "darwin")
    run = fake_run(returncode=code)
    assert safety.rekordbox_running() is expected
    ((cmd, kwargs),) = run.calls
    assert cmd == ["/usr/bin/pgrep", "-x", "rekordbox"]
    assert PurePosixPath(cmd[0]).is_absolute()  # never from PATH
    assert isinstance(cmd, list) and not kwargs.get("shell")


@pytest.mark.parametrize("code", [2, 3, 127, -9])
def test_darwin_pgrep_any_other_exit_code_is_a_safety_error(monkeypatch, fake_run, code):
    on(monkeypatch, "darwin")
    fake_run(returncode=code)
    with pytest.raises(safety.SafetyError, match=f"exited with {code}"):
        safety.rekordbox_running()


@pytest.mark.parametrize("error", [
    FileNotFoundError(2, "No such file or directory", "/usr/bin/pgrep"),
    PermissionError(13, "Permission denied"),
    subprocess.TimeoutExpired(["/usr/bin/pgrep"], 30),
])  # fmt: skip
def test_darwin_pgrep_that_cannot_run_is_a_safety_error(monkeypatch, fake_run, error):
    on(monkeypatch, "darwin")
    fake_run(raises=error)
    with pytest.raises(safety.SafetyError, match="Cannot tell whether rekordbox runs"):
        safety.rekordbox_running()


@pytest.mark.parametrize("stdout, expected", [
    ('"rekordbox.exe","1234","Console","1","512,000 K"\n', True),
    ("INFO: No tasks are running which match the specified criteria.\n", False),
])  # fmt: skip
def test_win32_still_asks_tasklist_exactly_as_before(monkeypatch, fake_run, stdout, expected):
    on(monkeypatch, "win32")
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    run = fake_run(stdout=stdout)
    assert safety.rekordbox_running() is expected
    ((cmd, kwargs),) = run.calls
    assert cmd[0].replace("/", "\\").lower().endswith("system32\\tasklist.exe")
    assert cmd[1:] == ["/FI", "IMAGENAME eq rekordbox.exe", "/FO", "CSV", "/NH"]
    assert kwargs == {"capture_output": True, "text": True, "check": True}
    assert "pgrep" not in " ".join(cmd)


@pytest.mark.parametrize("error", [
    subprocess.CalledProcessError(1, ["tasklist.exe"]),
    FileNotFoundError(2, "No such file or directory"),
    PermissionError(13, "Access is denied"),
])  # fmt: skip
def test_win32_tasklist_that_fails_is_a_safety_error(monkeypatch, fake_run, error):
    """Like pgrep: a check that cannot answer refuses (SafetyError), never a raw traceback."""
    on(monkeypatch, "win32")
    fake_run(raises=error)
    with pytest.raises(safety.SafetyError, match="Cannot tell whether rekordbox runs: tasklist failed") as info:
        safety.rekordbox_running()
    assert info.value.__cause__ is error


@pytest.mark.parametrize("platform", ["linux", "cygwin", "freebsd14"])
def test_any_other_os_raises_and_runs_nothing(monkeypatch, fake_run, platform):
    on(monkeypatch, platform)
    run = fake_run(returncode=1)
    with pytest.raises(safety.SafetyError, match=platform):
        safety.rekordbox_running()
    assert run.calls == []


@pytest.mark.parametrize("platform, name", [("darwin", "rekordbox"), ("win32", "rekordbox.exe")])
def test_messages_name_the_process_of_this_os(monkeypatch, platform, name):
    on(monkeypatch, platform)
    assert safety.process_name() == name


# -- master.db discovery (R-203) ---------------------------------------------------------


def put(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"placeholder, never opened")
    return path


@pytest.fixture
def discovery(monkeypatch, tmp_path):
    """The real find_master_db with a fake home, a fake %APPDATA% and no pyrekordbox config."""
    home, appdata = tmp_path / "home", tmp_path / "appdata"
    home.mkdir()
    appdata.mkdir()
    monkeypatch.setattr(safety, "find_master_db", REAL_FIND_MASTER_DB)
    monkeypatch.delenv("DJ_MASTER_DB", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(safety, "_db_path_from_pyrekordbox", lambda: None)
    return SimpleNamespace(
        home=home,
        mac=home / "Library" / "Pioneer" / "rekordbox" / "master.db",
        win=appdata / "Pioneer" / "rekordbox" / "master.db",
    )


def test_darwin_default_is_under_library_pioneer(monkeypatch, discovery):
    on(monkeypatch, "darwin")
    put(discovery.mac)
    put(discovery.win)  # %APPDATA% means nothing on a Mac
    assert safety.find_master_db() == discovery.mac


def test_win32_default_is_appdata_as_before(monkeypatch, discovery):
    on(monkeypatch, "win32")
    put(discovery.mac)
    put(discovery.win)
    assert safety.find_master_db() == discovery.win


def test_win32_without_appdata_finds_nothing_as_before(monkeypatch, discovery):
    on(monkeypatch, "win32")
    put(discovery.mac)
    monkeypatch.delenv("APPDATA")
    with pytest.raises(FileNotFoundError):
        safety.find_master_db()


def test_darwin_missing_names_the_place_it_looked(monkeypatch, discovery):
    on(monkeypatch, "darwin")
    with pytest.raises(FileNotFoundError) as info:
        safety.find_master_db()
    assert str(discovery.mac) in str(info.value)


def test_linux_has_no_default(monkeypatch, discovery):
    on(monkeypatch, "linux")
    put(discovery.mac)
    put(discovery.win)
    with pytest.raises(FileNotFoundError, match="looked at: None"):
        safety.find_master_db()


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_dj_master_db_override_comes_first(monkeypatch, discovery, tmp_path, platform):
    on(monkeypatch, platform)
    put(discovery.mac)
    put(discovery.win)
    chosen = put(tmp_path / "elsewhere" / "master.db")
    monkeypatch.setenv("DJ_MASTER_DB", str(chosen))

    def never():
        raise AssertionError("the override must win before pyrekordbox is asked")

    monkeypatch.setattr(safety, "_db_path_from_pyrekordbox", never)
    assert safety.find_master_db() == chosen


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_pyrekordbox_config_comes_before_the_default(monkeypatch, discovery, tmp_path, platform):
    on(monkeypatch, platform)
    put(discovery.mac)
    put(discovery.win)
    configured = put(tmp_path / "configured" / "master.db")
    monkeypatch.setattr(safety, "_db_path_from_pyrekordbox", lambda: configured)
    assert safety.find_master_db() == configured


# -- MCP host environment (R-203) --------------------------------------------------------


def test_win32_host_env_fills_the_windows_defaults(monkeypatch):
    on(monkeypatch, "win32")
    for key in WINDOWS_KEYS:
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.upper(), raising=False)
    out = {k.upper(): v for k, v in m.host_env().items()}
    assert out["PROGRAMFILES"] == r"C:\Program Files" and out["SYSTEMROOT"] == r"C:\Windows"
    assert out["APPDATA"].endswith("Roaming") and out["LOCALAPPDATA"].endswith("Local")
    assert out["USERPROFILE"] == str(Path.home())


def test_win32_host_env_keeps_what_is_there(monkeypatch):
    on(monkeypatch, "win32")
    monkeypatch.setenv("APPDATA", "X:/roaming")
    assert {k.upper(): v for k, v in m.host_env().items()}["APPDATA"] == "X:/roaming"


def test_darwin_host_env_gets_home_and_a_path_with_usr_bin_and_bin(monkeypatch, tmp_path):
    on(monkeypatch, "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for key in ("HOME", "PATH", *WINDOWS_KEYS):
        monkeypatch.delenv(key, raising=False)
    out = m.host_env()
    assert out["HOME"] == str(tmp_path)
    assert out["PATH"] == "/usr/bin:/bin"
    assert not {k.upper() for k in out} & {k.upper() for k in WINDOWS_KEYS}  # no Windows defaults


@pytest.mark.parametrize("given, expected", [
    ("/opt/homebrew/bin", "/opt/homebrew/bin:/usr/bin:/bin"),
    ("/bin:/usr/bin:/usr/local/bin", "/bin:/usr/bin:/usr/local/bin"),
    ("/usr/local/bin:/usr/bin", "/usr/local/bin:/usr/bin:/bin"),
])  # fmt: skip
def test_darwin_host_env_appends_only_what_path_lacks(monkeypatch, given, expected):
    on(monkeypatch, "darwin")
    monkeypatch.setenv("HOME", "/Users/dj")
    monkeypatch.setenv("PATH", given)
    out = m.host_env()
    assert out["PATH"] == expected and out["HOME"] == "/Users/dj"


@pytest.mark.parametrize("platform", ["linux", "freebsd14"])
def test_other_os_host_env_is_the_environment_unchanged(monkeypatch, platform):
    on(monkeypatch, platform)
    for key in WINDOWS_KEYS:
        monkeypatch.delenv(key, raising=False)
    assert m.host_env() == dict(os.environ)


def test_darwin_tools_run_with_that_environment(monkeypatch):
    on(monkeypatch, "darwin")
    monkeypatch.setenv("PATH", "/opt/homebrew/bin")
    seen = []
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **kw: seen.append(kw) or SimpleNamespace(
        returncode=0, stdout='{"tracks": 24}', stderr=""))
    assert json.loads(m.dj_status())["result"] == {"tracks": 24}
    passed = seen[0]["env"]
    assert passed["PATH"] == "/opt/homebrew/bin:/usr/bin:/bin" and passed["PYTHONUTF8"] == "1"


# -- the read path on both OS (R-201) ----------------------------------------------------


class Connect:
    """Stands in for safety._connect: a synthetic library, never a real database."""

    def __init__(self, spec=None, deleted=True):
        self.spec, self.deleted, self.paths = spec, deleted, []

    def __call__(self, db_path, quiet=False):
        self.paths.append(Path(db_path))
        return fx.fake_db(self.spec, deleted=self.deleted)


def no_process_check(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a read must never run the rekordbox process check")

    monkeypatch.setattr(safety.subprocess, "run", refuse)
    monkeypatch.setattr(safety, "rekordbox_running", refuse)


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_read_db_never_calls_the_process_check(monkeypatch, tmp_path, platform):
    live = fx.write_master_files(tmp_path / "Pioneer" / "rekordbox")
    connect = Connect()
    monkeypatch.setattr(safety, "_connect", connect)
    on(monkeypatch, platform)
    no_process_check(monkeypatch)
    lib = read_db(live, read_at="2026-10-20T09:00:00+00:00")
    assert lib.counts()["tracks"] == fx.EXPECTED_COUNTS["tracks"]
    assert connect.paths and connect.paths[0] != live  # the snapshot copy, not the live file


def test_darwin_read_db_finds_master_db_under_library_and_keeps_mac_paths(monkeypatch, discovery):
    on(monkeypatch, "darwin")
    live = fx.write_master_files(discovery.mac.parent, fx.as_mac())
    assert live == discovery.mac
    connect = Connect(fx.as_mac())
    monkeypatch.setattr(safety, "_connect", connect)
    no_process_check(monkeypatch)
    lib = read_db()
    assert lib.source_path == live.as_posix() and lib.counts()["tracks"] == fx.EXPECTED_COUNTS["tracks"]
    assert connect.paths[0].parent != live.parent
    locations = [t.location for t in lib.tracks.values()]
    assert any(loc.startswith("/Users/dj/Music/") for loc in locations)
    assert any(loc.startswith("/Volumes/") for loc in locations)
    assert not any("\\" in loc or loc.startswith("D:/") for loc in locations)


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_master_db_writes_stay_windows_only(monkeypatch, platform):
    on(monkeypatch, platform)

    def untouched(*args, **kwargs):
        raise AssertionError("nothing may run before the platform refusal")

    for name in ("find_master_db", "rekordbox_running", "backup", "_connect"):
        monkeypatch.setattr(safety, name, untouched)
    with pytest.raises(safety.SafetyError, match="Windows-only"):
        with safety.open_db(write=True):
            pytest.fail("must not yield")


def test_windows_is_the_db_write_platform():
    assert safety.DB_WRITE_PLATFORMS == ("win32",)


@pytest.fixture
def db_write_cli(monkeypatch, tmp_path):
    """The read pass sees a fake db; the write session is the real open_db, so its platform
    refusal runs. Nothing behind the refusal (backup, process check, connect) may run."""
    state = SimpleNamespace(db=None, sessions=[])

    @contextmanager
    def open_db(write=False, db_path=None):
        state.sessions.append(write)
        if write:
            with REAL_OPEN_DB(write=True, db_path=db_path) as real:
                yield real
        else:
            yield state.db

    def untouched(*args, **kwargs):
        raise AssertionError("nothing may run before the platform refusal")

    monkeypatch.setattr(safety, "open_db", open_db)
    for name in ("find_master_db", "rekordbox_running", "backup", "_connect"):
        monkeypatch.setattr(safety, name, untouched)
    monkeypatch.setattr(cli.intake, "Paths", functools.partial(cli.intake.Paths, tmp_path))
    return state


def db_write_jobs(tmp_path, db):
    """(fake db, dry-run arguments) for `dj tree`, `dj apply` and `dj copy`."""
    tree_file = tmp_path / "tree.yaml"
    tree_file.write_text("- playlist: inbox\n", encoding="utf-8")
    plan = tmp_path / "x.plan.json"
    plan.write_text(json.dumps(plan_with(("yes", "1"))), encoding="utf-8")
    crate, copy_db = CrateDB(), CopyDB([song("1", 1)])
    return [
        (db, ["tree", "--file", str(tree_file)]),
        (crate, ["apply", str(plan)]),
        (copy_db, ["copy", "jazzy", "jazz_base/2.1_jazzy"]),
    ]


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_db_write_commands_refuse_off_windows_in_one_line(monkeypatch, db_write_cli, db, tmp_path, platform):
    """R-205 / R-203: `dj tree|apply|copy --apply --power-mode` on a Mac end in one REFUSED line
    (exit 1), not a traceback, before any read, preview check or backup; nothing is written."""
    jobs = db_write_jobs(tmp_path, db)
    on(monkeypatch, platform)
    for fake, args in jobs:
        db_write_cli.db, db_write_cli.sessions = fake, []
        result = runner.invoke(cli.app, [*args, "--apply", "--power-mode", "--preview-id", "0" * 12])
        assert result.exit_code == cli.EXIT_ERROR, tidy_text(result)
        assert isinstance(result.exception, SystemExit), repr(result.exception)  # a clean exit, no traceback
        assert f"REFUSED master.db writes are power mode, Windows only; this is {platform}" in tidy_text(result)
        assert db_write_cli.sessions == [], args
    assert db.calls == [] and all(fake.added == [] for fake, _ in jobs[1:])
    assert not (tmp_path / "state").exists() and not (tmp_path / "reports").exists()


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_open_db_refusal_off_windows_is_one_line_too(monkeypatch, db_write_cli, db, tmp_path, platform):
    """The second wall: were the up-front check gone, safety.open_db(write=True) still refuses off
    Windows (DB_WRITE_PLATFORMS), and the command prints that as one ERROR line, not a traceback."""
    jobs = db_write_jobs(tmp_path, db)
    on(monkeypatch, platform)
    monkeypatch.setattr(cli.write_gate, "require_power_mode", lambda power_mode: None)
    for fake, args in jobs:
        db_write_cli.db, db_write_cli.sessions = fake, []
        pid = json.loads(runner.invoke(cli.app, [*args, "--json"]).output)["preview_id"]
        result = runner.invoke(cli.app, [*args, "--apply", "--power-mode", "--preview-id", pid])
        assert result.exit_code == cli.EXIT_ERROR, tidy_text(result)
        assert isinstance(result.exception, SystemExit), repr(result.exception)
        assert f"ERROR Direct master.db writes are Windows-only power mode; this is {platform}" in tidy_text(result)
        assert db_write_cli.sessions == [False, False, True], args  # dry-run, read pass, write refused
    assert db.calls == [] and all(fake.added == [] for fake, _ in jobs[1:])
    assert not (tmp_path / "state").exists() and not (tmp_path / "reports").exists()


# -- dj status with rekordbox running, per OS (R-201), from a snapshot (R-202) -----------


@pytest.fixture
def status_env(monkeypatch, tmp_path):
    live = fx.write_master_files(tmp_path / "rb")
    connect = Connect(deleted=False)
    monkeypatch.setattr(safety, "find_master_db", lambda: live)
    monkeypatch.setattr(safety, "_connect", connect)
    monkeypatch.setattr(safety, "rekordbox_running", REAL_RUNNING)
    monkeypatch.setattr(cli, "links_data", lambda db, paths: [])
    return SimpleNamespace(live=live, connect=connect)


def status_json(*extra):
    result = runner.invoke(cli.app, ["status", "--json", *extra])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def read_a_snapshot(status_env):
    """R-202: SQLite opened a copy in a temporary folder, never the live master.db, and the
    copy is gone afterwards."""
    paths = status_env.connect.paths
    assert paths, "status opened no database"
    assert all(p != status_env.live and p.parent != status_env.live.parent for p in paths)
    assert all(p.name == status_env.live.name for p in paths)
    assert not any(p.exists() for p in paths)


@pytest.mark.parametrize("platform, run_kwargs", [
    ("darwin", {"returncode": 0}),
    ("win32", {"stdout": RUNNING_CSV}),
])  # fmt: skip
def test_status_counts_on_both_os_while_rekordbox_runs(monkeypatch, fake_run, status_env, platform, run_kwargs):
    on(monkeypatch, platform)
    run = fake_run(**run_kwargs)
    data = status_json()
    assert data["running"] is True and data["tracks"] == fx.EXPECTED_COUNTS["tracks"]
    assert [entry["name"] for entry in data["tree"]] == [n["name"] for n in fx.SPEC["tree"]]
    assert data["master_db"] == str(status_env.live)  # names the live file; reads the copy
    assert len(run.calls) == 1
    read_a_snapshot(status_env)


@pytest.mark.parametrize("platform, answer", [
    ("darwin", SimpleNamespace(returncode=0, stdout="", stderr="")),
    ("win32", SimpleNamespace(returncode=0, stdout=RUNNING_CSV, stderr="")),
])  # fmt: skip
def test_mcp_dj_status_returns_counts_on_both_os_while_rekordbox_runs(monkeypatch, status_env, platform, answer):
    """R-201 as written: the MCP tool `dj_status`, end to end. The server's `python -m dj.cli`
    call runs the CLI in-process; the process check gets the answer "rekordbox runs"."""
    on(monkeypatch, platform)
    checks, dj_calls = [], []

    def run(cmd, **kwargs):
        if cmd[:3] == [sys.executable, "-m", "dj.cli"]:
            dj_calls.append(cmd[3:])
            done = runner.invoke(cli.app, cmd[3:])
            return SimpleNamespace(returncode=done.exit_code, stdout=done.stdout, stderr=done.stderr)
        checks.append(cmd)
        return answer

    monkeypatch.setattr(subprocess, "run", run)
    out = json.loads(m.dj_status())
    assert out["ok"] is True and out["exit_code"] == 0, out
    assert out["result"]["running"] is True
    assert out["result"]["tracks"] == fx.EXPECTED_COUNTS["tracks"]
    assert dj_calls == [["status", "--json"]] and len(checks) == 1
    assert ("pgrep" in checks[0][0]) is (platform == "darwin")
    read_a_snapshot(status_env)


@pytest.mark.parametrize("platform, run_kwargs", [
    ("darwin", {"returncode": 3}),
    ("linux", {}),
    ("win32", {"raises": subprocess.CalledProcessError(1, ["tasklist.exe"])}),
    ("win32", {"raises": FileNotFoundError(2, "No such file or directory")}),
])  # fmt: skip
def test_status_reads_even_when_the_process_check_cannot_answer(monkeypatch, fake_run, status_env, platform,
                                                                run_kwargs):
    on(monkeypatch, platform)
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    fake_run(**run_kwargs)
    data = status_json()
    assert data["running"] is None and data["tracks"] == fx.EXPECTED_COUNTS["tracks"]
    human = runner.invoke(cli.app, ["status"])
    assert human.exit_code == 0 and "running:       unknown" in human.output
    read_a_snapshot(status_env)


@pytest.mark.parametrize("error, message", [
    (db_reader.LibraryError("master.db kept changing while it was copied (3 tries)"), "kept changing"),
    (PermissionError(13, "Permission denied"), "Could not copy master.db for a snapshot"),
])  # fmt: skip
def test_status_whose_snapshot_fails_is_one_error_line_and_opens_nothing(monkeypatch, fake_run, status_env,
                                                                         error, message):
    on(monkeypatch, "darwin")
    fake_run(returncode=1)

    def fails(master_db, dest, **kwargs):
        raise error

    monkeypatch.setattr(db_reader, "snapshot", fails)
    result = runner.invoke(cli.app, ["status", "--json"])
    assert result.exit_code == cli.EXIT_ERROR and isinstance(result.exception, SystemExit)
    assert "ERROR" in tidy_text(result) and message in tidy_text(result)
    assert status_env.connect.paths == []  # neither the live file nor a copy was opened


# -- dj tidy writes stay Windows-only (R-1303 is v0.2); on Windows through safety (R-203) --


def tidy_text(result):
    return result.output + (getattr(result, "stderr", "") or "")


def tidy(command, plan_path, env, *extra):  # noqa: F811
    return runner.invoke(cli.app, ["tidy", command, str(plan_path), *extra, "--config", env.yaml])


def test_tidy_writes_are_windows_only():
    assert safety.TIDY_WRITE_PLATFORMS == ("win32",)


@pytest.mark.parametrize("platform, run_kwargs", [
    ("darwin", {"returncode": 1}),  # rekordbox closed: still no tidy write on a Mac in v0.1
    ("darwin", {"returncode": 0}),
    ("linux", {}),
])  # fmt: skip
def test_tidy_writes_refuse_off_windows_before_the_process_check(env, monkeypatch, fake_run,  # noqa: F811
                                                                 platform, run_kwargs):
    a = make_audio(env.root / "Huerta - Low Five.mp3")
    before = a.read_bytes()
    plan_path = _planned(env)
    monkeypatch.setattr(safety, "TIDY_WRITE_PLATFORMS", ("win32",))  # the rule; `env` opens it for the mechanics
    monkeypatch.setattr(cli.safety, "rekordbox_running", REAL_RUNNING)
    on(monkeypatch, platform)
    run = fake_run(**run_kwargs)
    for command in ("apply", "undo"):
        result = tidy(command, plan_path, env, "--apply")
        out = tidy_text(result)
        assert result.exit_code == cli.EXIT_ERROR and isinstance(result.exception, SystemExit), out
        assert ("ERROR dj tidy writes audio files on Windows only in v0.1 (macOS: R-1303, v0.2); "
                f"this is {platform}") in out
        assert "STOP" not in out
    assert run.calls == []  # refused before pgrep is asked
    assert a.read_bytes() == before and not list(env.tmp.rglob("*.undo.json"))
    dry = tidy("apply", plan_path, env)
    assert dry.exit_code == 0 and "DRY-RUN" in dry.output and a.read_bytes() == before  # dry-runs only read


def windows_tidy(monkeypatch):
    monkeypatch.setattr(safety, "TIDY_WRITE_PLATFORMS", ("win32",))
    monkeypatch.setattr(cli.safety, "rekordbox_running", REAL_RUNNING)
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    on(monkeypatch, "win32")


def test_tidy_on_windows_asks_tasklist_through_safety(env, monkeypatch, fake_run):  # noqa: F811
    a = make_audio(env.root / "Huerta - Low Five.mp3")
    before = a.read_bytes()
    plan_path = _planned(env)
    windows_tidy(monkeypatch)
    run = fake_run(stdout=RUNNING_CSV)
    stopped = tidy("apply", plan_path, env, "--apply")
    assert stopped.exit_code == cli.EXIT_REKORDBOX_RUNNING, tidy_text(stopped)
    assert "STOP rekordbox.exe is running" in tidy_text(stopped) and a.read_bytes() == before
    run.stdout = NOT_RUNNING_CSV
    pid = json.loads(tidy("apply", plan_path, env, "--json").output)["preview_id"]  # the dry-run (R-1102)
    done = tidy("apply", plan_path, env, "--apply", "--preview-id", pid)
    assert done.exit_code == 0 and "APPLIED" in done.output, tidy_text(done)
    assert tags.read(a)[0].artist == ("Huerta",) and list(env.tmp.rglob("*.undo.json"))
    assert len(run.calls) == 2 and all(cmd[0].lower().endswith("tasklist.exe") for cmd, _ in run.calls)


@pytest.mark.parametrize("error", [
    subprocess.CalledProcessError(1, ["tasklist.exe"]),
    FileNotFoundError(2, "No such file or directory"),
])  # fmt: skip
def test_tidy_on_windows_refuses_when_tasklist_cannot_answer(env, monkeypatch, fake_run, error):  # noqa: F811
    a = make_audio(env.root / "Huerta - Low Five.mp3")
    before = a.read_bytes()
    plan_path = _planned(env)
    windows_tidy(monkeypatch)
    fake_run(raises=error)
    for command in ("apply", "undo"):
        result = tidy(command, plan_path, env, "--apply")
        out = tidy_text(result)
        assert result.exit_code == cli.EXIT_ERROR and isinstance(result.exception, SystemExit), out
        assert "ERROR Cannot tell whether rekordbox runs: tasklist failed" in out
    assert a.read_bytes() == before and not list(env.tmp.rglob("*.undo.json"))
