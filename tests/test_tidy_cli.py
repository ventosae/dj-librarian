"""`dj tidy` through the command layer: exit codes, which commands open a (read-only) DB
session, and that apply/undo open none at all."""

import functools
import json
import sys
from types import SimpleNamespace

import pytest
from test_cli import sessions  # noqa: F401  (fixture)
from tidy_fixtures import TidyDB, make_audio, playlist, row, song
from typer.testing import CliRunner

from dj import cli
from dj.tidy import tags

runner = CliRunner()

YAML = """
roots: ["{root}"]
profiles:
  - {{name: p, formats: [mp3, flac, wav, aiff], max_bit_depth: 24, sample_rates: [44100, 48000], mp3_min_kbps: 320}}
"""


@pytest.fixture
def env(tmp_path, monkeypatch, sessions):  # noqa: F811
    root = tmp_path / "music"
    root.mkdir()
    yaml_path = tmp_path / "tidy.yaml"
    yaml_path.write_text(YAML.format(root=root.as_posix()), encoding="utf-8")
    monkeypatch.setattr(cli.intake, "Paths", functools.partial(cli.intake.Paths, tmp_path))
    monkeypatch.setattr(cli.safety, "rekordbox_running", lambda: False)
    # tidy writes are Windows-only (test_platform.py); the write mechanics run on every runner
    monkeypatch.setattr(cli.safety, "TIDY_WRITE_PLATFORMS", (sys.platform,))
    sessions.db = TidyDB()
    return SimpleNamespace(root=root, yaml=str(yaml_path), sessions=sessions, tmp=tmp_path)


def run(*args):
    return runner.invoke(cli.app, [str(a) for a in args])


def text(result):
    return result.output + (getattr(result, "stderr", "") or "")


def test_audit_folder_is_one_read_only_session_and_writes_reports(env):
    make_audio(env.root / "Huerta - Low Five.mp3")
    result = run("tidy", "audit", "--folder", env.root, "--config", env.yaml, "--json")
    assert result.exit_code == 0, text(result)
    assert env.sessions.log == [False]
    payload = json.loads(result.output)
    assert payload["kind"] == "tidy-audit" and payload["counts"]["items"] == 1
    assert "TAG_ARTIST_MISSING" in payload["counts"]["by_code"] and "MP3_BITRATE_LOW" in payload["counts"]["by_code"]
    reports = list((env.tmp / "reports" / "tidy").iterdir())
    assert sorted(p.suffix for p in reports) == [".json", ".md"]
    assert payload["reports"] and "items" in payload


def test_audit_brief_and_no_report(env):
    make_audio(env.root / "Huerta - Low Five.mp3")
    result = run("tidy", "audit", "--folder", env.root, "--config", env.yaml, "--json", "--brief", "--no-report")
    payload = json.loads(result.output)
    assert "items" not in payload and "reports" not in payload and payload["counts"]["items"] == 1
    assert not (env.tmp / "reports").exists()


def test_audit_human_output_lists_findings_per_file(env):
    make_audio(env.root / "Huerta - Low Five.mp3")
    result = run("tidy", "audit", "--folder", env.root, "--config", env.yaml)
    assert result.exit_code == 0 and "WARN " in result.output and "ART_MISSING" in result.output
    assert "No file was changed" in result.output


def test_audit_needs_exactly_one_target(env):
    assert run("tidy", "audit", "--config", env.yaml).exit_code == 1
    both = run("tidy", "audit", "x/y", "--all", "--config", env.yaml)
    assert both.exit_code == 1 and "Give one" in text(both)
    assert env.sessions.log == []


def test_audit_crate_uses_the_playlist(env):
    a = make_audio(env.root / "a.mp3")
    env.sessions.db = TidyDB(contents=[row("1", path=a.as_posix(), ArtistName="A", Title="T")],
                             playlists=[playlist("10", "0_INBOX", songs=[song("1")])])
    result = run("tidy", "audit", "0_INBOX", "--config", env.yaml, "--json", "--brief")
    assert result.exit_code == 0, text(result)
    assert json.loads(result.output)["scan"]["files"] == 1 and env.sessions.log == [False]
    missing = run("tidy", "audit", "nope", "--config", env.yaml)
    assert missing.exit_code == 1 and "No rekordbox playlist" in text(missing)


def test_a_positional_after_double_dash_is_a_crate_name_never_an_option(env):
    result = run("tidy", "audit", "--config", env.yaml, "--json", "--", "--all")
    assert result.exit_code == 1 and "'--all'" in text(result)  # looked up as a playlist name


def test_folder_outside_roots_is_refused(env, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    result = run("tidy", "audit", "--folder", outside, "--config", env.yaml)
    assert result.exit_code == 1 and "outside" in text(result)


def test_dupes_command(env):
    make_audio(env.root / "a.mp3", frames=30)
    make_audio(env.root / "b.mp3", frames=30)
    result = run("tidy", "dupes", "--folder", env.root, "--config", env.yaml, "--json")
    assert result.exit_code == 0 and len(json.loads(result.output)["groups"]) == 1
    human = run("tidy", "dupes", "--folder", env.root, "--config", env.yaml)
    assert "DUPE 1 (exact)" in human.output and "nothing is deleted" in human.output


def test_plan_writes_a_plan_file_and_refuses_overwrite(env):
    make_audio(env.root / "berlioz - ode to rahsaan (Original Mix).mp3")
    result = run("tidy", "plan", "--folder", env.root, "--config", env.yaml, "--json")
    assert result.exit_code == 0, text(result)
    payload = json.loads(result.output)
    plan_path = env.tmp / "plans" / payload["plan"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    assert plan_path.is_file() and payload["counts"]["with_changes"] == 1
    assert payload["items"][0]["changes"]["artist"]["new"] == "berlioz"
    assert env.sessions.log == [False]
    human = run("tidy", "plan", "--folder", env.root, "--config", env.yaml)
    assert "PENDING" in human.output and "artist '' -> 'berlioz'" in human.output
    assert run("tidy", "plan", "--folder", env.root, "--config", env.yaml, "--overwrite").exit_code == 1


def _planned(env, decision="yes"):
    result = run("tidy", "plan", "--folder", env.root, "--config", env.yaml, "--json")
    plan_path = env.tmp / "plans" / json.loads(result.output)["plan"].replace("\\", "/").rsplit("/", 1)[-1]
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    for item in data["items"]:
        if item["decision"]:
            item["decision"] = decision
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    env.sessions.log.clear()
    return plan_path


def test_apply_dry_run_opens_no_db_session(env):
    a = make_audio(env.root / "Huerta - Low Five.mp3")
    before = a.read_bytes()
    plan_path = _planned(env)
    result = run("tidy", "apply", plan_path, "--config", env.yaml)
    assert result.exit_code == 0, text(result)
    assert "DRY-RUN" in result.output and "WOULD" in result.output
    assert env.sessions.log == [] and a.read_bytes() == before


def test_apply_refuses_while_rekordbox_runs(env, monkeypatch):
    a = make_audio(env.root / "Huerta - Low Five.mp3")
    before = a.read_bytes()
    plan_path = _planned(env)
    monkeypatch.setattr(cli.safety, "rekordbox_running", lambda: True)
    result = run("tidy", "apply", plan_path, "--apply", "--config", env.yaml)
    assert result.exit_code == 2 and "STOP" in text(result) and a.read_bytes() == before
    assert run("tidy", "apply", plan_path, "--config", env.yaml).exit_code == 0  # dry-run is fine


def test_apply_then_undo_round_trip(env):
    a = make_audio(env.root / "Huerta - Low Five.mp3")
    plan_path = _planned(env)
    result = run("tidy", "apply", plan_path, "--apply", "--config", env.yaml, "--json")
    assert result.exit_code == 0, text(result)
    payload = json.loads(result.output)
    assert payload["counts"]["applied"] == 1 and payload["undo"] and env.sessions.log == []
    assert tags.read(a)[0].artist == ("Huerta",)
    human = run("tidy", "apply", plan_path, "--apply", "--config", env.yaml)
    assert "Reload Tag" in human.output and "0 written" in human.output and "1 applied earlier" in human.output

    dry = run("tidy", "undo", plan_path, "--config", env.yaml)
    assert dry.exit_code == 0 and "DRY-RUN" in dry.output and tags.read(a)[0].artist == ("Huerta",)
    undone = run("tidy", "undo", plan_path, "--apply", "--config", env.yaml)
    assert undone.exit_code == 0 and "UNDONE" in undone.output and tags.read(a)[0] == tags.Tags()


def test_apply_exit_code_1_when_an_item_fails(env, monkeypatch):
    make_audio(env.root / "Huerta - Low Five.mp3")
    plan_path = _planned(env)

    def boom(*a, **k):
        raise cli.TidyError("simulated")

    monkeypatch.setattr(cli.tidy_plan.tags, "write", boom)
    result = run("tidy", "apply", plan_path, "--apply", "--config", env.yaml)
    assert result.exit_code == 1 and "FAILED" in result.output


def test_apply_strict_blocks_everything(env):
    a = make_audio(env.root / "Huerta - Low Five.mp3")
    b = make_audio(env.root / "Octo Octa - Loops.mp3")
    plan_path = _planned(env)
    b.write_bytes(b.read_bytes() + b"\x00")
    result = run("tidy", "apply", plan_path, "--apply", "--strict", "--config", env.yaml)
    assert result.exit_code == 1 and "STRICT" in result.output and tags.read(a)[0] == tags.Tags()


def test_bad_plan_file_is_an_error(env, tmp_path):
    bad = tmp_path / "x.plan.json"
    bad.write_text('{"kind": "other"}')
    result = run("tidy", "apply", bad, "--config", env.yaml)
    assert result.exit_code == 1 and "not a dj tidy plan" in text(result)
    assert run("tidy", "undo", tmp_path / "missing.plan.json", "--config", env.yaml).exit_code == 1


def test_show_locals_stays_off_for_the_sub_app():
    assert cli.tidy_app.pretty_exceptions_show_locals is False
