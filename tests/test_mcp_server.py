import asyncio
import json
from types import SimpleNamespace

import pytest

from dj import mcp_server as m


@pytest.fixture
def calls(monkeypatch):
    """Capture the command line instead of running it."""
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"x": 1}', stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    return seen


def args(calls):
    return calls[-1][0][3:]  # after: python -m dj.cli


PID = "0123456789ab"  # the shape of a preview id


def test_every_call_is_an_argument_list_with_no_shell_and_no_stdin(calls):
    m.dj_match("example_link")
    cmd, kwargs = calls[-1]
    assert cmd[1:3] == ["-m", "dj.cli"] and isinstance(cmd, list)
    assert "shell" not in kwargs and kwargs["stdin"] == m.subprocess.DEVNULL
    assert args(calls) == ["match", "--json", "--", "example_link"]


def test_a_value_can_never_become_an_option(calls):
    m.dj_copy_preview("--apply", "target")
    assert args(calls) == ["copy", "--json", "--", "--apply", "target"]


def test_preview_tools_never_pass_apply(calls):
    m.dj_status()
    m.dj_match("l")
    m.dj_pull("l")
    m.dj_copy_preview("a", "b")
    m.dj_push_preview("p")
    assert all("--apply" not in c[0][: c[0].index("--")] if "--" in c[0] else "--apply" not in c[0] for c in calls)


def test_write_tools_pass_apply(calls):
    m.dj_copy_apply("a", "b", preview_id=PID, power_mode=True)
    assert args(calls) == ["copy", "--apply", "--power-mode", "--preview-id", PID, "--json", "--", "a", "b"]
    m.dj_push_apply("p", preview_id=PID, name="n", include_ambiguous=True)
    assert args(calls) == ["push", "--apply", "--preview-id", PID, "--name", "n", "--include-ambiguous", "--json",
                           "--", "p"]


def test_file_arguments_must_be_inside_the_repo(calls, tmp_path, monkeypatch):
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)
    (tmp_path / "bases.yaml").write_text("[]")
    (tmp_path / "secret.env").write_text("x")
    outside = tmp_path.parent / "evil.yaml"
    outside.write_text("[]")

    assert json.loads(m.dj_tree_preview("bases.yaml"))["ok"] is True
    for bad in (str(outside), "../evil.yaml", "secret.env", "missing.yaml"):
        answer = json.loads(m.dj_tree_apply(file=bad, preview_id=PID, power_mode=True))
        assert answer["ok"] is False and "error" in answer
    assert len(calls) == 1  # only the good one ran


def test_exit_code_2_tells_the_agent_to_wait_not_to_work_around(monkeypatch):
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **k: SimpleNamespace(
        returncode=2, stdout="", stderr="[x] WARNING - Rekordbox is running!\nSTOP rekordbox.exe is running."))
    answer = json.loads(m.dj_copy_apply("a", "b", preview_id=PID, power_mode=True))
    assert (answer["ok"], answer["exit_code"]) == (False, 2)
    assert "close it" in answer["hint"] and answer["stderr"] == ["STOP rekordbox.exe is running."]


NOT_SET_UP = ("REFUSED plain is not a dj-library folder (no library.yaml). Set it up with dj-start first. "
              "Nothing was written.")  # fmt: skip


def test_exit_code_2_from_a_folder_not_set_up_is_not_rekordbox(monkeypatch):
    """`dj library analyze` refuses a folder without library.yaml with exit 2: closing rekordbox
    and retrying cannot fix that, so the hint must not say so."""
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **k: SimpleNamespace(returncode=2, stdout="", stderr=NOT_SET_UP))
    answer = json.loads(m.dj_library_analyze())
    assert (answer["ok"], answer["exit_code"]) == (False, 2)
    assert answer["hint"] == m.NO_LIBRARY and "close it" not in answer["hint"] and "dj-start" in answer["hint"]


@pytest.mark.parametrize(("stderr", "hint"), [
    (["STOP rekordbox.exe is running."], "rekordbox is open"),
    ([], "rekordbox is open"),
    ([NOT_SET_UP], "not set up"),
    (["INFO reading", "REFUSED plain: library.yaml is not valid (device). Run dj-start on the folder first."], "not set up"),
    (["REFUSED C:\\ is a whole drive, not a library folder. Nothing was written."], "Refused, see stderr"),
])  # fmt: skip
def test_refusal_hint_names_the_cause(stderr, hint):
    assert hint in m.refusal_hint(stderr)


def test_timeout_is_reported(monkeypatch):
    def slow(cmd, **k):
        raise m.subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(m.subprocess, "run", slow)
    assert json.loads(m.dj_status())["ok"] is False


def test_tool_list_and_which_ones_are_read_only():
    tools = {t.name: t for t in asyncio.run(m.server.list_tools())}
    assert set(tools) == {
        "dj_status", "dj_tree_preview", "dj_pull", "dj_match", "dj_plan", "dj_apply_preview",
        "dj_copy_preview", "dj_push_preview", "dj_build_preview", "dj_tree_apply", "dj_apply_write",
        "dj_copy_apply", "dj_push_apply", "dj_build_apply",
        "dj_tidy_audit", "dj_tidy_dupes", "dj_tidy_plan", "dj_tidy_apply_preview", "dj_tidy_apply",
        "dj_tidy_undo_preview", "dj_tidy_undo",
        "dj_library_inspect", "dj_library_analyze", "dj_structure_preview", "dj_structure_write",
        "dj_crate_preview", "dj_crate_write", "dj_barber_next", "dj_barber_record", "dj_wishlist_shop",
    }
    writers = {n for n, t in tools.items() if not t.annotations.read_only_hint}
    assert writers == {"dj_plan", "dj_tree_apply", "dj_apply_write", "dj_copy_apply", "dj_push_apply",
                       "dj_build_apply", "dj_tidy_audit", "dj_tidy_plan", "dj_tidy_apply", "dj_tidy_undo",
                       "dj_library_analyze",
                       "dj_structure_preview", "dj_structure_write", "dj_crate_write", "dj_barber_next",
                       "dj_barber_record", "dj_wishlist_shop"}
    assert not any(t.annotations.destructive_hint for t in tools.values())
    assert "file" in tools["dj_tree_apply"].input_schema["properties"]  # schema survives @guarded


def test_there_is_no_generic_command_tool():
    names = [t.name for t in asyncio.run(m.server.list_tools())]
    assert not any(w in n for n in names for w in ("exec", "shell", "run", "command"))


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """tidy.yaml roots = tmp_path/music, without reading the real file."""
    from dj.tidy import config as cfg_mod

    music = tmp_path / "music"
    music.mkdir()
    (tmp_path / "tidy.yaml").write_text(
        f'roots: ["{music.as_posix()}"]\nprofiles:\n  - {{name: p, formats: [mp3], max_bit_depth: 24, sample_rates: [44100]}}\n')
    real = cfg_mod.load_config
    monkeypatch.setattr(m.tidy_config, "load_config", lambda path=None: real(tmp_path / "tidy.yaml"))
    return music


def test_tidy_target_is_exactly_one(calls):
    for bad in (dict(), dict(crate="a", all_tracks=True), dict(crate="a", folder="b")):
        answer = json.loads(m.dj_tidy_audit(**bad))
        assert answer["ok"] is False and "exactly one" in answer["error"]
    assert calls == []


def test_tidy_all_and_folder_go_before_the_double_dash_and_a_crate_after(calls, roots):
    m.dj_tidy_audit(all_tracks=True)
    assert args(calls) == ["tidy", "audit", "--all", "--brief", "--json"]
    m.dj_tidy_audit(crate="--all", brief=False, profiles="cdj3000_family, nxs2_family")
    assert args(calls) == ["tidy", "audit", "--profile", "cdj3000_family", "--profile", "nxs2_family", "--json", "--", "--all"]
    m.dj_tidy_dupes(folder=str(roots))
    assert args(calls) == ["tidy", "dupes", "--folder", str(roots.resolve()), "--json"]


def test_tidy_folder_must_be_a_directory_inside_a_root(calls, roots, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (roots / "a.mp3").write_bytes(b"x")
    for bad in (str(outside), str(roots / "a.mp3"), str(roots / "missing")):
        answer = json.loads(m.dj_tidy_plan(folder=bad))
        assert answer["ok"] is False and "error" in answer
    assert calls == []
    assert json.loads(m.dj_tidy_plan(folder=str(roots), rename=True))["ok"] is True
    assert args(calls) == ["tidy", "plan", "--folder", str(roots.resolve()), "--rename", "--art", "local", "--json"]


def test_tidy_plan_flags_and_art_whitelist(calls):
    m.dj_tidy_plan(crate="x/y", rename_imported=True, art="online")
    assert args(calls) == ["tidy", "plan", "--rename-imported", "--art", "local", "--json", "--", "x/y"]


def test_tidy_preview_and_write_tools(calls, tmp_path, monkeypatch):
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)
    plan = tmp_path / "p.plan.json"
    plan.write_text("{}")
    m.dj_tidy_apply_preview("p.plan.json")
    assert args(calls) == ["tidy", "apply", "--json", "--", str(plan.resolve())]
    m.dj_tidy_apply_preview("p.plan.json", strict=True)
    assert args(calls) == ["tidy", "apply", "--strict", "--json", "--", str(plan.resolve())]
    m.dj_tidy_apply("p.plan.json", preview_id=PID, strict=True)
    assert args(calls) == ["tidy", "apply", "--apply", "--preview-id", PID, "--strict", "--json", "--",
                           str(plan.resolve())]
    m.dj_tidy_undo_preview("p.plan.json")
    assert args(calls) == ["tidy", "undo", "--json", "--", str(plan.resolve())]
    m.dj_tidy_undo("p.plan.json", preview_id=PID)
    assert args(calls) == ["tidy", "undo", "--apply", "--preview-id", PID, "--json", "--", str(plan.resolve())]
    assert json.loads(m.dj_tidy_apply("../outside.json", preview_id=PID))["ok"] is False


def test_a_stripped_environment_is_filled_in(calls, monkeypatch):
    monkeypatch.setattr(m.sys, "platform", "win32")  # the Windows defaults; other OS: test_platform.py
    for key in ("ProgramFiles", "PROGRAMFILES", "APPDATA", "SystemRoot", "SYSTEMROOT"):
        monkeypatch.delenv(key, raising=False)
    m.dj_status()
    env = {k.upper(): v for k, v in calls[-1][1]["env"].items()}
    assert env["PROGRAMFILES"] and env["APPDATA"].endswith("Roaming") and env["SYSTEMROOT"]
    assert env["PYTHONUTF8"] == "1"
