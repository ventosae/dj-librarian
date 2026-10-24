"""The plugin's manifest and how it starts the engine (W-34, D-28, Q-31; replaces W-30's `uv path`
option, Q-25).

plugin.json names the engine bundle, `"mcpServers": "./engine.mcpb"` (a build product of
scripts/build_mcpb.py --plugin, gitignored, inside the plugin zip by default), and declares no
userConfig: the bundle carries its own settings (mcpb/manifest.json's user_config), which the
host asks for when it loads the bundle. The old `.mcp.json` (`uv run --directory
${CLAUDE_PLUGIN_ROOT}/..`, which needed a clone) and the `uv path` option are gone. The write-gate
hook still starts a bare `uv` (a known gap, logged with Q-31). `claude plugin validate --strict`
(2.1.299) checks every `${user_config.KEY}` against the declared keys; CI builds the bundle and
then runs it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
PLUGIN_JSON = PLUGIN / ".claude-plugin" / "plugin.json"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_plugin_json_names_the_engine_bundle():
    assert _json(PLUGIN_JSON)["mcpServers"] == "./engine.mcpb"


def test_plugin_json_declares_no_options():
    """The bundle's own user_config (library folder, Spotify keys, power mode) is the one settings
    form; the `uv path` option went with the uv-on-PATH install."""
    assert "userConfig" not in _json(PLUGIN_JSON)


def test_there_is_no_mcp_json_and_no_clone_relative_command():
    assert not (PLUGIN / ".mcp.json").exists()
    for path in (PLUGIN_JSON, HOOKS_JSON):
        text = path.read_text(encoding="utf-8")
        assert "uv_path" not in text and "${CLAUDE_PLUGIN_ROOT}/.." not in text, path.name


def test_the_bundle_is_the_plugins_server():
    """The bundle's name is the server key, so tool names and the write-gate matcher stay
    mcp__plugin_dj-librarian_dj-librarian__* and mcp__dj-librarian__*."""
    plugin = _json(PLUGIN_JSON)
    bundle = _json(REPO / "mcpb" / "manifest.json")
    assert bundle["name"] == plugin["name"] == "dj-librarian"
    assert bundle["version"] == plugin["version"]


def test_every_user_config_reference_is_declared():
    declared = set(_json(PLUGIN_JSON).get("userConfig", {}))
    for path in (PLUGIN_JSON, HOOKS_JSON):
        used = set(re.findall(r"\$\{user_config\.([A-Za-z0-9_]+)\}", path.read_text(encoding="utf-8")))
        assert used <= declared, (path.name, used - declared)


def test_the_hook_keeps_a_bare_uv():
    (entry,) = _json(HOOKS_JSON)["hooks"]["PreToolUse"]
    (hook,) = entry["hooks"]
    assert hook["command"] == "uv" and hook["onFailure"] == "block"


def test_the_engine_bundle_in_plugin_is_never_tracked():
    """plugin/engine.mcpb is built, not committed: the zip and CI build it fresh."""
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    done = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", "plugin/engine.mcpb", "plugin/.mcpb-cache"],
                          capture_output=True, text=True, timeout=60)  # fmt: skip
    assert done.returncode == 0 and done.stdout.strip() == ""
    ignored = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "plugin/engine.mcpb"], timeout=60)
    assert ignored.returncode == 0
