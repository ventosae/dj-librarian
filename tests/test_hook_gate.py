"""The Claude Code PreToolUse write gate (R-1105, C-10): plugin/hooks/hooks.json + gate.py.

gate.py runs as a subprocess with sample hook payloads: a write tool without a valid preview_id is
denied (the documented `hookSpecificOutput.permissionDecision: "deny"` output), a valid one and
every other tool pass silently, unreadable input is denied unless it names a non-write tool. The
matcher in hooks.json is checked with `re` against the full tool names Claude Code uses: the
plugin's server (`mcp__plugin_dj-librarian_dj-librarian__*`) and a server registered by hand as
`dj-librarian` (`mcp__dj-librarian__*`).
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dj import mcp_server as m

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
GATE = PLUGIN / "hooks" / "gate.py"
PREFIXES = ("mcp__plugin_dj-librarian_dj-librarian__", "mcp__dj-librarian__")

# Every tool that writes to rekordbox, Spotify, audio files or a rekordbox XML, by name; W-23's
# dj_crate_write is covered by the same name pattern before it exists.
WRITE_TOOLS = {"dj_tree_apply", "dj_apply_write", "dj_copy_apply", "dj_push_apply", "dj_build_apply",
               "dj_tidy_apply", "dj_tidy_undo", "dj_structure_write", "dj_crate_write"}  # fmt: skip
FUTURE_WRITE_TOOLS: set[str] = set()  # dj_crate_write landed with W-23
PID = "0123456789ab"


def gate(payload, *, raw: str | None = None) -> subprocess.CompletedProcess:
    text = raw if raw is not None else json.dumps(payload)
    return subprocess.run([sys.executable, str(GATE)], input=text.encode("utf-8"), capture_output=True,
                          timeout=60)  # fmt: skip


def call(tool: str, tool_input, prefix: str = PREFIXES[0]) -> dict:
    return {
        "session_id": "s",
        "hook_event_name": "PreToolUse",
        "tool_name": prefix + tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_1",
    }


def denied(done: subprocess.CompletedProcess) -> str:
    """The deny reason; fails unless the output is exactly one documented deny object."""
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.decode("utf-8"))
    assert set(out) == {"hookSpecificOutput"}
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse" and spec["permissionDecision"] == "deny"
    assert spec["permissionDecisionReason"].startswith("dj-librarian write gate: ")
    return spec["permissionDecisionReason"]


def allowed(done: subprocess.CompletedProcess) -> None:
    assert done.returncode == 0, done.stderr
    assert done.stdout == b"", done.stdout


def hooks() -> dict:
    return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))


def matcher() -> str:
    (entry,) = hooks()["hooks"]["PreToolUse"]
    return entry["matcher"]


def mcp_tools() -> dict:
    return {t.name: t for t in asyncio.run(m.server.list_tools())}


# -- gate.py ---------------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("tool", sorted(WRITE_TOOLS | FUTURE_WRITE_TOOLS))
def test_a_write_tool_without_a_preview_id_is_denied(tool, prefix):
    reason = denied(gate(call(tool, {"plan_file": "plans/x.plan.json"}, prefix)))
    assert tool in reason and "preview_id" in reason and "yes" in reason


@pytest.mark.parametrize("value", ["", "   ", None])
def test_an_empty_preview_id_is_denied(value):
    assert "needs the preview_id" in denied(gate(call("dj_copy_apply", {"preview_id": value})))


@pytest.mark.parametrize("value", ["0123456789AB", "0123456789a", "0123456789abc", "g123456789ab",
                                   " 0123456789ab", "0123456789ab\n", "preview", 123456789012,
                                   ["0123456789ab"]])  # fmt: skip
def test_a_malformed_preview_id_is_denied(value):
    assert "is not a preview id" in denied(gate(call("dj_tidy_undo", {"plan_file": "p.json", "preview_id": value})))


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("tool", sorted(WRITE_TOOLS | FUTURE_WRITE_TOOLS))
def test_a_write_tool_with_a_valid_preview_id_passes_silently(tool, prefix):
    allowed(gate(call(tool, {"preview_id": PID, "power_mode": True}, prefix)))


@pytest.mark.parametrize("name", [
    "Bash", "Read", "mcp__plugin_dj-librarian_dj-librarian__dj_status",
    "mcp__plugin_dj-librarian_dj-librarian__dj_tidy_apply_preview", "mcp__dj-librarian__dj_structure_preview",
    "mcp__other__dj_tree_apply", "mcp__plugin_other_dj-librarian__dj_tree_apply",
])  # fmt: skip
def test_other_tools_are_ignored(name):
    allowed(gate({"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": {}}))


@pytest.mark.parametrize("raw", ["", "{bad", "[]", "null", '"text"', "\xff\xfe"])
def test_unreadable_input_is_denied(raw):
    assert "could not be read" in denied(gate(None, raw=raw))


def test_unreadable_input_naming_a_non_write_tool_passes():
    allowed(gate(None, raw='{"tool_name": "mcp__dj-librarian__dj_status", "tool_input": {'))


def test_unreadable_input_naming_a_write_tool_is_denied():
    raw = '{"tool_name": "mcp__dj-librarian__dj_tree_apply", "tool_input": {"preview_id": "0123456789ab"'
    assert "could not be read" in denied(gate(None, raw=raw))


@pytest.mark.parametrize("payload", [
    {"tool_input": {"preview_id": PID}},  # no tool_name
    {"tool_name": 7, "tool_input": {"preview_id": PID}},
])  # fmt: skip
def test_a_call_without_a_tool_name_is_denied(payload):
    assert "could not be read" in denied(gate(payload))


@pytest.mark.parametrize("tool_input", [None, [], "0123456789ab"])
def test_a_write_tool_whose_input_is_not_a_mapping_is_denied(tool_input):
    assert "needs the preview_id" in denied(gate(call("dj_push_apply", tool_input)))


def test_gate_imports_the_standard_library_only():
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_gate_and_the_engine_agree_on_the_shape_of_a_preview_id():
    from dj.gate import ID_PATTERN, valid_id

    source = GATE.read_text(encoding="utf-8")
    assert 'PREVIEW_ID = re.compile(r"^[0-9a-f]{12}$")' in source and "PREVIEW_ID.fullmatch(value)" in source
    assert ID_PATTERN.pattern == "^[0-9a-f]{12}$"
    for value in (PID, "0123456789ab\n", "0123456789ab\r\n", "\n0123456789ab", "0123456789AB", "0123456789a"):
        hook_allows = gate(call("dj_tree_apply", {"preview_id": value})).stdout == b""
        assert hook_allows == valid_id(value) == (value == PID), repr(value)


# -- hooks.json ------------------------------------------------------------------------------


def test_hooks_json_registers_one_pretooluse_command_that_fails_closed():
    data = hooks()
    assert set(data) == {"description", "hooks"} and set(data["hooks"]) == {"PreToolUse"}
    (entry,) = data["hooks"]["PreToolUse"]
    (hook,) = entry["hooks"]
    assert hook["type"] == "command"
    # exec form through uv: no shell, no system Python (docs/prompts/plans/W-21.md)
    assert hook["command"] == "uv"
    assert hook["args"][:2] == ["run", "--no-project"] and hook["args"][-2:] == [
        "python", "${CLAUDE_PLUGIN_ROOT}/hooks/gate.py"]
    assert hook["onFailure"] == "block"  # no uv, a crash or a timeout blocks the write
    assert 0 < hook["timeout"] <= 120


@pytest.mark.parametrize("prefix", PREFIXES)
def test_the_matcher_catches_every_write_tool_and_nothing_else(prefix):
    pattern = re.compile(matcher())  # Claude Code tests it unanchored (RegExp.test); it anchors itself
    names = set(mcp_tools())
    assert WRITE_TOOLS <= names
    for name in names | FUTURE_WRITE_TOOLS | {"dj_crate_preview", "dj_barber_record"}:
        full = prefix + name
        expected = name in WRITE_TOOLS | FUTURE_WRITE_TOOLS
        assert bool(pattern.search(full)) is expected, full


@pytest.mark.parametrize("name", [
    "Bash", "mcp__other__dj_tree_apply", "mcp__plugin_dj-librarian_other__dj_tree_apply",
    "mcp__dj-librarian__dj_tree_apply_preview", "xmcp__dj-librarian__dj_tree_apply",
    "mcp__dj-librarian__dj_tree_apply2",
])  # fmt: skip
def test_the_matcher_ignores_look_alikes(name):
    assert not re.search(matcher(), name)


def test_the_matcher_and_gate_py_name_the_same_tools():
    source = GATE.read_text(encoding="utf-8")
    namespace: dict = {}
    exec(compile(source, str(GATE), "exec"), namespace)  # noqa: S102  (our own file, no __main__)
    for name in mcp_tools().keys() | FUTURE_WRITE_TOOLS:
        for prefix in PREFIXES:
            assert namespace["is_write_tool"](prefix + name) is bool(re.search(matcher(), prefix + name))


def test_every_write_tool_requires_a_preview_id():
    tools = mcp_tools()
    for name in WRITE_TOOLS:
        schema = tools[name].input_schema
        assert "preview_id" in schema["properties"] and "preview_id" in schema.get("required", []), name
        assert not tools[name].annotations.read_only_hint, name


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_the_hook_command_runs_through_uv_outside_any_project(tmp_path):
    """The exact hooks.json command, from a folder that is no project: denies, then allows.
    Offline, no Python download: uv takes an interpreter it already has."""
    (entry,) = hooks()["hooks"]["PreToolUse"]
    (hook,) = entry["hooks"]
    argv = [shutil.which(hook["command"])] + [a.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN)) for a in hook["args"]]
    env = dict(os.environ, UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never", CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    for payload, expect_deny in ((call("dj_tree_apply", {}), True), (call("dj_tree_apply", {"preview_id": PID}), False)):
        done = subprocess.run(argv, input=json.dumps(payload).encode(), capture_output=True, cwd=tmp_path,
                              env=env, timeout=120)  # fmt: skip
        if expect_deny:
            denied(done)
        else:
            allowed(done)
