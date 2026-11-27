"""The plugin's manifest and how the engine reaches a DJ.

plugin.json names no MCP server and declares no userConfig: `/dj-librarian:install` copies the
engine's source (engine/ in the zip) to ~/dj-librarian and registers it in Claude Desktop's config.
The old `.mcp.json` (`uv run --directory ${CLAUDE_PLUGIN_ROOT}/..`) and the `uv path` option stay
gone. The write-gate hook still starts a bare `uv`. `claude plugin validate --strict` checks every
`${user_config.KEY}` against the declared keys.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
PLUGIN_JSON = PLUGIN / ".claude-plugin" / "plugin.json"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_plugin_json_names_no_mcp_server():
    assert "mcpServers" not in _json(PLUGIN_JSON)  # the install command registers the engine


def test_plugin_json_declares_no_options():
    assert "userConfig" not in _json(PLUGIN_JSON)


def test_there_is_no_mcp_json_and_no_clone_relative_command():
    assert not (PLUGIN / ".mcp.json").exists()
    for path in (PLUGIN_JSON, HOOKS_JSON):
        text = path.read_text(encoding="utf-8")
        assert "uv_path" not in text and "${CLAUDE_PLUGIN_ROOT}/.." not in text, path.name


def test_the_plugin_is_named_dj_librarian():
    """The name is the server key, so tool names and the write-gate matcher stay
    mcp__plugin_dj-librarian_dj-librarian__* and mcp__dj-librarian__*."""
    assert _json(PLUGIN_JSON)["name"] == "dj-librarian"


def test_every_user_config_reference_is_declared():
    declared = set(_json(PLUGIN_JSON).get("userConfig", {}))
    for path in (PLUGIN_JSON, HOOKS_JSON):
        used = set(re.findall(r"\$\{user_config\.([A-Za-z0-9_]+)\}", path.read_text(encoding="utf-8")))
        assert used <= declared, (path.name, used - declared)


def test_the_hook_keeps_a_bare_uv():
    (entry,) = _json(HOOKS_JSON)["hooks"]["PreToolUse"]
    (hook,) = entry["hooks"]
    assert hook["command"] == "uv" and hook["onFailure"] == "block"
