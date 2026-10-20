"""R-904: the tool, not Claude, appends the log.md lines of every writing command.

`dj.activity_log.log_write` writes through `libfolder.append_log` into the configured dj-library
folder when it is set up (a valid library.yaml), else into log.md at the top of the repo. Per
writing CLI command: a dry-run adds no line, the write adds exactly one, a refusal adds none.
tests/conftest.py points the repo log at a folder of each test's own and turns the library
folder off; the tests here that need one patch `activity_log.library_root`.
"""

from __future__ import annotations

import functools
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest
from test_cli import sessions  # noqa: F401  (fixture used by `env`)
from test_tidy_cli import env  # noqa: F401  (fixture)
from test_write_gate import (  # noqa: F401  (rb, spot, tidy_apply, tidy_undo, in_process: fixtures)
    db_job,
    dry_run_id,
    gated,
    in_process,
    rb,
    refused,
    run,
    spot,
    tidy_apply,
    tidy_undo,
)

from dj import activity_log, cli, intake, libfolder

REAL_LIBRARY_ROOT = activity_log.library_root  # before conftest's autouse patch
LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} \S.*$")
NOW = datetime(2026, 10, 20, 14, 3)


def log_lines(folder: Path) -> list[str]:
    """The entries of folder/log.md (its title and blank lines left out)."""
    path = folder / "log.md"
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and line != "# Log"]


def repo_lines() -> list[str]:
    return log_lines(Path(activity_log.REPO_DIR))


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A set-up dj-library folder the CLI logs into."""
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac")
    monkeypatch.setattr(activity_log, "library_root", lambda: root.resolve())
    return root


# -- the helper ---------------------------------------------------------------------------------


def test_no_library_folder_logs_to_the_repo_log():
    plans = Path(activity_log.REPO_DIR) / "plans"
    plans.mkdir()
    logged = activity_log.log_write("plan funk_base/funk_crate", {"proposed": 2, "missing": 1}, plans / "a.plan.json",
                                    now=NOW)  # fmt: skip
    assert logged.warning is None and logged.log == Path(activity_log.REPO_DIR) / "log.md"
    assert logged.line == "2026-10-20 14:03 plan funk_base/funk_crate -> 2 proposed, 1 missing; plans/a.plan.json"
    assert repo_lines() == [logged.line]


def test_a_set_up_library_folder_gets_the_line_and_the_repo_log_none(library):
    logged = activity_log.log_write("tree", {"playlists": 3}, library / "proposals" / "x.yaml", now=NOW)
    assert logged.log == library.resolve() / "log.md"
    assert log_lines(library) == ["2026-10-20 14:03 tree -> 3 playlists; proposals/x.yaml"]
    assert repo_lines() == []


@pytest.mark.parametrize("state", ["missing", "no library.yaml", "invalid library.yaml"])
def test_a_folder_that_is_not_set_up_falls_back_to_the_repo_log(tmp_path, monkeypatch, state):
    root = tmp_path / "plain"
    if state != "missing":
        root.mkdir()
    if state == "invalid library.yaml":
        (root / "library.yaml").write_text("device: amiga\n", encoding="utf-8")
    monkeypatch.setattr(activity_log, "library_root", lambda: root)
    logged = activity_log.log_write("copy a to b", {"added": 1}, now=NOW)
    assert logged.line == "2026-10-20 14:03 copy a to b -> 1 added" and len(repo_lines()) == 1
    assert not (root / "log.md").exists()


def test_the_real_library_root_is_the_configured_folder(tmp_path, monkeypatch):
    monkeypatch.setenv(libfolder.ENV_VAR, str(tmp_path / "dj-library"))
    assert REAL_LIBRARY_ROOT() == (tmp_path / "dj-library").resolve()
    monkeypatch.setenv(libfolder.ENV_VAR, str(Path.home()))  # refused by configured_root
    assert REAL_LIBRARY_ROOT() is None


def test_files_are_relative_to_the_log_folder_then_the_repo_never_absolute(library, tmp_path):
    repo = Path(activity_log.REPO_DIR)
    root = library.resolve()
    assert activity_log.file_text(root, library / "crates" / "a.md") == "crates/a.md"
    assert activity_log.file_text(root, repo / "plans" / "b.plan.json") == "plans/b.plan.json"
    assert activity_log.file_text(root, tmp_path / "elsewhere" / "set.txt") == "set.txt"
    assert activity_log.file_text(root, None) is None
    logged = activity_log.log_write("build Spotify playlist x", {"added": 2}, tmp_path / "elsewhere" / "r.json")
    assert logged.line.endswith("; r.json") and str(tmp_path) not in log_lines(library)[0]


def test_a_log_that_cannot_be_written_is_a_warning_never_an_error():
    (Path(activity_log.REPO_DIR) / "log.md").mkdir()  # a folder where log.md should be
    logged = activity_log.log_write("tree", {"playlists": 1})
    assert logged.line is None and "log.md line not written" in logged.warning


def test_a_library_yaml_that_is_not_utf8_falls_back_to_the_repo_log(tmp_path, monkeypatch):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac")
    (root / "library.yaml").write_bytes("chosen: \u00c9lectro\n".encode("cp1252"))
    monkeypatch.setattr(activity_log, "library_root", lambda: root.resolve())
    assert activity_log.is_library(root) is False
    logged = activity_log.log_write("copy a to b", {"added": 1}, now=NOW)
    assert logged.warning is None and repo_lines() == [logged.line]


def _undecodable(*args, **kwargs):
    raise UnicodeDecodeError("utf-8", b"\xc9", 0, 1, "invalid continuation byte")


@pytest.mark.parametrize("where", ["log_root", "append_log"])
def test_any_error_while_logging_is_a_warning(monkeypatch, where):
    monkeypatch.setattr(activity_log if where == "log_root" else libfolder, where, _undecodable)
    logged = activity_log.log_write("tree", {"playlists": 1})
    assert logged.line is None and "UnicodeDecodeError" in logged.warning
    assert "the write itself is done" in logged.warning


def test_the_real_library_root_survives_an_unreadable_stored_path(monkeypatch):
    monkeypatch.delenv(libfolder.ENV_VAR, raising=False)
    monkeypatch.setattr(libfolder, "configured_root", _undecodable)
    assert REAL_LIBRARY_ROOT() is None


def test_a_command_whose_log_fails_still_succeeds_and_names_what_it_wrote(tmp_path, monkeypatch):
    from test_intake import LINK, make_items

    monkeypatch.setattr(cli.intake, "Paths", functools.partial(intake.Paths, tmp_path))
    monkeypatch.setattr(cli, "_match", lambda link: (LINK, make_items(), set()))
    monkeypatch.setattr(activity_log, "log_root", _undecodable)
    result = run("plan", "funk_109_bpm", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["log"] is None and Path(data["plan"]).is_file()
    assert "WARNING log.md line not written (UnicodeDecodeError" in result.stderr


def test_an_action_with_line_breaks_stays_one_line():
    logged = activity_log.log_write("copy a\nb to c\r\nd", {"added": 1}, now=NOW)
    assert logged.line == "2026-10-20 14:03 copy a b to c d -> 1 added" and LINE.match(repo_lines()[0])


# -- master.db commands: dj tree, dj apply, dj copy ---------------------------------------------


@pytest.mark.parametrize("name", ["tree", "apply", "copy"])
def test_db_command_dry_run_adds_no_line_the_write_adds_one_a_refusal_none(name, rb, tmp_path, db):  # noqa: F811
    job = db_job(name, tmp_path, db)
    rb.db = job.db
    pid = dry_run_id(job.dry)
    assert run(*job.dry).exit_code == 0 and repo_lines() == []  # dry-runs (json and text)
    refused(run(*job.dry, *gated(pid)))  # no --power-mode
    refused(run(*job.dry, *gated(None, "--power-mode")))  # no preview id
    refused(run(*job.dry, *gated("0" * 12, "--power-mode")))  # an unknown id
    assert repo_lines() == []
    result = run(*job.dry, *gated(pid, "--power-mode"))
    assert result.exit_code == 0, result.output
    (line,) = repo_lines()
    assert LINE.match(line) and f"log.md: {line}" in result.stdout
    expected = {
        "tree": " tree -> 2 playlists, 1 folders; tree.yaml",
        "apply": " apply funk_base/funk_crate -> 1 added, 1 no, 0 pending; ",
        "copy": " copy jazzy to jazz_base/2.1_jazzy -> 2 added, 0 skipped; ",
    }[name]
    assert expected in line, line
    refused(run(*job.dry, *gated(pid, "--power-mode")))  # the used id: refused, no second line
    assert len(repo_lines()) == 1


def test_a_write_with_nothing_to_do_adds_no_line(rb, tmp_path, db):  # noqa: F811
    job = db_job("copy", tmp_path, db)
    rb.db = job.db
    assert run(*job.dry, *gated(dry_run_id(job.dry), "--power-mode")).exit_code == 0
    again = dry_run_id(job.dry)  # everything is in the target now
    result = run(*job.dry, *gated(again, "--power-mode"))
    assert "Nothing to add" in result.stdout and len(repo_lines()) == 1


def test_apply_json_carries_the_line(rb, tmp_path, db):  # noqa: F811
    job = db_job("apply", tmp_path, db)
    rb.db = job.db
    data = json.loads(run(*job.dry, *gated(dry_run_id(job.dry), "--power-mode"), "--json").stdout)
    assert data["applied"] is True and data["log"] == repo_lines()[0]


# -- Spotify: dj push, dj build -----------------------------------------------------------------


@pytest.mark.parametrize("kind", ["push", "build"])
def test_spotify_command_dry_run_adds_no_line_the_write_adds_one_a_refusal_none(kind, spot, tmp_path):  # noqa: F811
    if kind == "push":
        dry = ["push", "jazzy"]
    else:
        tracklist = tmp_path / "set.txt"
        tracklist.write_text("Artist - Track 1\nArtist - Track 2\n", encoding="utf-8")
        dry = ["build", tracklist]
    pid = dry_run_id(dry)
    assert run(*dry).exit_code == 0
    refused(run(*dry, *gated(None)))
    refused(run(*dry, *gated("0" * 12)))
    assert repo_lines() == []
    data = json.loads(run(*dry, *gated(pid), "--json").stdout)
    (line,) = repo_lines()
    assert data["log"] == line and "-> 2 added, 0 already there, 0 missing; " in line
    action = "push jazzy to Spotify" if kind == "push" else "build Spotify playlist set"
    assert f" {action} -> " in line and line.endswith(".report.json")


# -- dj plan, dj tidy plan ----------------------------------------------------------------------


def test_dj_plan_adds_one_line_per_run_and_none_on_an_error(tmp_path, monkeypatch):
    from test_intake import LINK, make_items

    monkeypatch.setattr(cli.intake, "Paths", functools.partial(intake.Paths, tmp_path))
    monkeypatch.setattr(cli, "_match", lambda link: (LINK, make_items(), set()))
    data = json.loads(run("plan", "funk_109_bpm", "--json").stdout)
    (line,) = repo_lines()
    assert data["log"] == line
    assert " plan funk_base/funk_crate -> 0 in crate, 2 proposed, 1 ambiguous, 1 missing, 0 declined; " in line
    assert line.endswith(".plan.json")

    def broken(link):
        raise intake.IntakeError("0 links match 'nope'.")

    monkeypatch.setattr(cli, "_match", broken)
    assert run("plan", "nope").exit_code == cli.EXIT_ERROR and len(repo_lines()) == 1


def test_dj_tidy_plan_adds_one_line_and_never_an_absolute_path(env):  # noqa: F811
    from tidy_fixtures import make_audio

    make_audio(env.root / "Huerta - Low Five.mp3")
    result = run("tidy", "plan", "--folder", env.root, "--config", env.yaml)
    assert result.exit_code == 0, result.output
    (line,) = repo_lines()
    assert " tidy plan folder music -> 1 files, 1 with proposals, 0 renames; " in line, line
    assert str(env.root) not in line and env.root.as_posix() not in line


# -- audio files: dj tidy apply, dj tidy undo ---------------------------------------------------


def test_tidy_apply_dry_run_adds_no_line_the_write_adds_one_a_refusal_none(tidy_apply):  # noqa: F811
    before = len(repo_lines())  # the fixture's `dj tidy plan` logged its own line
    pid = dry_run_id(tidy_apply.dry)
    assert run(*tidy_apply.dry).exit_code == 0
    refused(run(*tidy_apply.dry, *gated(None)))
    refused(run(*tidy_apply.dry, *gated("0" * 12)))
    assert len(repo_lines()) == before
    data = json.loads(run(*tidy_apply.dry, *gated(pid), "--json").stdout)
    assert len(repo_lines()) == before + 1
    line = repo_lines()[-1]
    assert data["log"] == line and " tidy apply folder music -> 1 written, 0 failed, 0 cannot run; " in line
    assert line.endswith(".undo.json")


def test_tidy_undo_dry_run_adds_no_line_the_write_adds_one_a_refusal_none(tidy_undo):  # noqa: F811
    before = len(repo_lines())  # plan + apply
    pid = dry_run_id(tidy_undo.dry)
    refused(run(*tidy_undo.dry, *gated(None)))
    assert len(repo_lines()) == before
    result = run(*tidy_undo.dry, *gated(pid))
    assert result.exit_code == 0 and "UNDONE" in result.stdout, result.output
    assert len(repo_lines()) == before + 1
    assert " tidy undo folder music -> 1 restored, 0 failed, 0 skipped; " in repo_lines()[-1]


def test_dj_tidy_plan_refusals_add_no_line(env):  # noqa: F811
    from tidy_fixtures import make_audio

    make_audio(env.root / "Huerta - Low Five.mp3")
    overwrite = run("tidy", "plan", "--folder", env.root, "--config", env.yaml, "--overwrite")
    assert overwrite.exit_code == cli.EXIT_ERROR and "--overwrite is not in v1" in overwrite.stderr
    outside = env.tmp / "elsewhere"
    outside.mkdir()
    refused_folder = run("tidy", "plan", "--folder", outside, "--config", env.yaml)
    assert refused_folder.exit_code == cli.EXIT_ERROR and "outside" in refused_folder.stderr
    assert repo_lines() == []


# -- dj tidy audit: its reports are a write ------------------------------------------------------


def test_dj_tidy_audit_logs_its_report_and_no_report_logs_nothing(env):  # noqa: F811
    from tidy_fixtures import make_audio

    make_audio(env.root / "Huerta - Low Five.mp3")
    assert run("tidy", "audit", "--folder", env.root, "--config", env.yaml, "--no-report").exit_code == 0
    assert repo_lines() == []
    data = json.loads(run("tidy", "audit", "--folder", env.root, "--config", env.yaml, "--json", "--brief").stdout)
    (line,) = repo_lines()
    c = data["counts"]
    assert data["log"] == line and line.endswith(".audit.md") and str(env.root) not in line
    assert (f" tidy audit folder music -> {c['items']} files, {c['error']} errors, {c['warn']} warnings, "
            f"{c['duplicate_groups']} dupe groups; ") in line  # fmt: skip
    text = run("tidy", "audit", "--folder", env.root, "--config", env.yaml)
    assert f"log.md: {repo_lines()[-1]}" in text.stdout and len(repo_lines()) == 2


def test_a_kept_audit_run_logs_once_whatever_the_pages(env, in_process):  # noqa: F811
    """dj_tidy_audit(brief=false) pages its items; pages 2+ come from page 1's scan, so the files
    are scanned once and log.md gets one line."""
    from tidy_fixtures import make_audio

    from dj import mcp_server as m

    for n in range(3):
        make_audio(env.root / f"Huerta - Low Five {n}.mp3")
    in_process += ["--config", env.yaml]

    def page(n: int) -> dict:
        return json.loads(m.run_paged(["tidy", "audit", "--folder", str(env.root)], keys=("items", "duplicates"),
                                      page=n, page_size=1))  # fmt: skip

    first = page(1)
    assert first["ok"] is True and first["result"]["paging"]["items"]["pages"] == 3
    for n in (2, 3):
        later = page(n)
        assert later["run_at"] == first["run_at"] and later["result"]["log"] == first["result"]["log"]
    assert repo_lines() == [first["result"]["log"]]


# -- nothing to add, a failed item, a run stopped by an error ------------------------------------


def test_dj_apply_with_every_yes_already_in_the_crate_logs_0_added(rb, tmp_path, db):  # noqa: F811
    """dj apply --apply records the decisions (match cache, declined, report) even with nothing to
    add: that is a write, so it logs one line."""
    job = db_job("apply", tmp_path, db)
    rb.db = job.db
    job.change()  # the yes track is in the crate already
    result = run(*job.dry, *gated(dry_run_id(job.dry), "--power-mode"))
    assert result.exit_code == 0, result.output
    (line,) = repo_lines()
    assert " apply funk_base/funk_crate -> 0 added, 1 no, 0 pending; " in line and job.db.added == []


def test_dj_apply_logs_the_commit_when_the_report_after_it_fails(rb, tmp_path, db, monkeypatch):  # noqa: F811
    job = db_job("apply", tmp_path, db)
    rb.db = job.db
    pid = dry_run_id(job.dry)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cli.intake, "record", broken)
    result = run(*job.dry, *gated(pid, "--power-mode"))
    assert result.exit_code != 0 and job.db.added == ["1"]
    (line,) = repo_lines()
    assert line.endswith(" apply funk_base/funk_crate, stopped by an error -> 1 added")


def _two_files_planned(env):  # noqa: F811
    from test_tidy_cli import _planned
    from tidy_fixtures import make_audio

    make_audio(env.root / "Huerta - Low Five.mp3")
    make_audio(env.root / "Octo Octa - Loops For Healing.mp3")
    plan = _planned(env)
    return plan, ["tidy", "apply", plan, "--config", env.yaml]


def test_tidy_apply_with_a_failed_item_logs_one_line_with_it(env, monkeypatch):  # noqa: F811
    from dj.tidy import TidyError
    from dj.tidy import plan as tidy_plan

    plan, dry = _two_files_planned(env)
    before = len(repo_lines())  # the plan's own line
    pid = dry_run_id(dry)
    real_write = tidy_plan.tags.write

    def write(path, *args, **kwargs):
        if "Octo Octa" in str(path):
            raise TidyError("file is locked")
        return real_write(path, *args, **kwargs)

    monkeypatch.setattr(tidy_plan.tags, "write", write)
    result = run(*dry, *gated(pid), "--json")
    assert result.exit_code == cli.EXIT_ERROR  # a failed item fails the run, after its line
    data = json.loads(result.stdout)
    assert len(repo_lines()) == before + 1
    line = repo_lines()[-1]
    assert data["log"] == line and " tidy apply folder music -> 1 written, 1 failed, 0 cannot run; " in line


def test_tidy_apply_stopped_by_an_error_logs_what_it_wrote(env, monkeypatch):  # noqa: F811
    from dj.tidy import plan as tidy_plan

    plan, dry = _two_files_planned(env)
    before = len(repo_lines())
    pid = dry_run_id(dry)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(tidy_plan, "write_apply_report", broken)
    result = run(*dry, *gated(pid))
    assert result.exit_code == cli.EXIT_ERROR and "ERROR disk full" in result.stderr
    assert len(repo_lines()) == before + 1
    line = repo_lines()[-1]
    assert " tidy apply folder music, stopped by an error -> 2 written, 0 failed; " in line
    assert line.endswith(".undo.json") and f"log.md: {line}" in result.stderr


def test_tidy_apply_that_fails_before_its_first_write_logs_nothing(env, monkeypatch):  # noqa: F811
    from dj.tidy import TidyError
    from dj.tidy import plan as tidy_plan

    plan, dry = _two_files_planned(env)
    before = len(repo_lines())
    pid = dry_run_id(dry)

    real_read = tidy_plan.tags.read

    def read(path, *args, **kwargs):  # the write's own read of the first file, before its undo record
        if sys._getframe(1).f_code.co_name == "_write_ready":
            raise TidyError("cannot read")
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(tidy_plan.tags, "read", read)
    result = run(*dry, *gated(pid))
    assert result.exit_code == cli.EXIT_ERROR and "ERROR cannot read" in result.stderr
    assert len(repo_lines()) == before


def test_tidy_undo_stopped_by_an_error_logs_what_it_did(tidy_undo, monkeypatch):  # noqa: F811
    from dj.tidy import plan as tidy_plan

    before = len(repo_lines())
    pid = dry_run_id(tidy_undo.dry)
    real = tidy_plan._write_json_atomic

    def write(path, data):
        if str(path).endswith(".plan.json"):
            raise OSError("plan file is held open")
        return real(path, data)

    monkeypatch.setattr(tidy_plan, "_write_json_atomic", write)
    result = run(*tidy_undo.dry, *gated(pid))
    assert result.exit_code == cli.EXIT_ERROR and "plan file is held open" in result.stderr
    assert len(repo_lines()) == before + 1
    assert " tidy undo folder music, stopped by an error -> 0 restored, 1 failed; " in repo_lines()[-1]


@pytest.mark.parametrize("kind", ["push", "build"])
def test_a_spotify_write_stopped_after_the_playlist_exists_logs_it(kind, spot, tmp_path):  # noqa: F811
    from dj.spotify import SpotifyError

    if kind == "push":
        dry, action = ["push", "jazzy"], "push jazzy to Spotify"
    else:
        tracklist = tmp_path / "set.txt"
        tracklist.write_text("Artist - Track 1\nArtist - Track 2\n", encoding="utf-8")
        dry, action = ["build", tracklist], "build Spotify playlist set"
    pid = dry_run_id(dry)

    def broken(playlist_id, uris):
        raise SpotifyError("Spotify 502 on adding items")

    spot.api.add_items = broken
    result = run(*dry, *gated(pid))
    assert result.exit_code == cli.EXIT_ERROR and "ERROR Spotify 502 on adding items" in result.stderr
    (line,) = repo_lines()
    assert line.endswith(f" {action}, stopped by an error -> 1 playlists created, 0 added, 2 not added")
    assert f"log.md: {line}" in result.stderr and len(spot.api.created) == 1


def test_push_apply_says_what_it_wrote_before_an_error(tmp_path):
    from test_push import FakeSpotify

    from dj import push
    from dj.spotify import SpotifyError

    api, state = FakeSpotify(), tmp_path / "push.json"
    calls = []

    def add_items(pid, uris):
        calls.append(list(uris))
        if len(calls) == 2:
            raise SpotifyError("Spotify 500")
        api.playlists[pid] += uris

    api.add_items = add_items
    uris = [f"u{n}" for n in range(250)]
    with pytest.raises(push.PushInterrupted) as stopped:
        push.apply(api, "rb1", "deep", uris, state)
    assert str(stopped.value) == "Spotify 500" and isinstance(stopped.value, SpotifyError)
    assert (stopped.value.created, stopped.value.added, stopped.value.left) == (True, 100, 150)
    assert [len(c) for c in calls] == [100, 100] and json.loads(state.read_text())["rb1"]["spotify_id"] == "pl1"

    def refuse_all(pid, uris):
        raise SpotifyError("Spotify 500")

    api.add_items = refuse_all  # the playlist exists, nothing gets added: nothing was written
    with pytest.raises(SpotifyError) as plain:
        push.apply(api, "rb1", "deep", uris, state)
    assert type(plain.value) is SpotifyError


# -- library folder vs repo, through a command ---------------------------------------------------


def test_a_command_logs_into_the_set_up_library_folder(rb, tmp_path, db, library):  # noqa: F811
    job = db_job("copy", tmp_path, db)
    rb.db = job.db
    assert run(*job.dry, *gated(dry_run_id(job.dry), "--power-mode")).exit_code == 0
    (line,) = log_lines(library)
    assert " copy jazzy to jazz_base/2.1_jazzy -> 2 added" in line and repo_lines() == []


def test_the_library_commands_log_once_themselves(tmp_path, monkeypatch, library):
    """dj library profile (like build, analyze, structure, taste, report and start.py) appends its own
    line through libfolder.append_log; activity_log adds none on top."""
    import xml_fixtures as fx

    libfolder.import_export(library, fx.write_xml(tmp_path / "collection.xml"))
    before = log_lines(library)
    assert run("library", "profile", "--library", library).exit_code == 0
    added = log_lines(library)[len(before):]
    assert len(added) == 1 and " profile -> " in added[0] and repo_lines() == []


# -- the skills: Claude reads log.md, never writes it ---------------------------------------------


@pytest.mark.parametrize("skill", ["dj-sync", "dj-tidy"])
def test_the_skills_leave_log_md_to_the_tool(skill):
    text = (Path(__file__).resolve().parents[1] / "plugin" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert "append one line to log.md" not in flat.lower()
    assert "The tool writes log.md, never you (R-904)." in flat and "never write log.md yourself" in flat
    assert "read log.md" in flat and "## Log line" in text and "R-904" in flat
