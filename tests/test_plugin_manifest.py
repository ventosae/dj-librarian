"""The plugin's `uv path` option (Q-25, W-30 item 9).

A Mac app started from the Dock gets a short PATH, so a bare `uv` may not start the engine. The
plugin declares `userConfig.uv_path` (default `uv`) and `.mcp.json` starts the engine with it; the
write-gate hook keeps a bare `uv`. The M1 card and the README give the Mac link into
/usr/local/bin, labelled unverified until the first Mac test. `claude plugin validate --strict`
(2.1.299) wants `type`, `title` and `description` on each option and checks every
`${user_config.KEY}` against the declared keys; CI runs it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
MAC_LINK = 'sudo ln -sf "$(command -v uv)" /usr/local/bin/uv'


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_plugin_json_declares_the_uv_path_option():
    option = _json(PLUGIN / ".claude-plugin" / "plugin.json")["userConfig"]["uv_path"]
    assert option["type"] == "string" and option["title"] == "uv path" and option["default"] == "uv"
    assert isinstance(option["description"], str) and "command -v uv" in option["description"]
    assert set(option) <= {"type", "title", "description", "default", "required", "sensitive"}


def test_mcp_json_starts_the_engine_with_the_uv_path_option():
    server = _json(PLUGIN / ".mcp.json")["mcpServers"]["dj-librarian"]
    assert server["type"] == "stdio" and server["command"] == "${user_config.uv_path}"
    assert server["args"] == ["run", "--directory", "${CLAUDE_PLUGIN_ROOT}/..", "--no-sync", "dj-mcp"]


def test_every_user_config_reference_is_declared():
    declared = set(_json(PLUGIN / ".claude-plugin" / "plugin.json")["userConfig"])
    for path in (PLUGIN / ".mcp.json", PLUGIN / "hooks" / "hooks.json"):
        used = set(re.findall(r"\$\{user_config\.([A-Za-z0-9_]+)\}", path.read_text(encoding="utf-8")))
        assert used <= declared, (path.name, used - declared)


def test_the_hook_keeps_a_bare_uv():
    (entry,) = _json(PLUGIN / "hooks" / "hooks.json")["hooks"]["PreToolUse"]
    (hook,) = entry["hooks"]
    assert hook["command"] == "uv" and hook["onFailure"] == "block"


def test_the_mac_card_and_the_readme_give_the_link_and_say_it_is_unverified():
    engine = (PLUGIN / "skills" / "dj-start" / "engine.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    mac, windows = re.findall(r"^(?:Mac|Windows):\n\n```text\n(.*?)\n```", engine, re.MULTILINE | re.DOTALL)
    assert MAC_LINK in mac and MAC_LINK not in windows
    prose = " ".join(engine.split())
    assert "uv path" in prose and "unverified until the first Mac test (Q-25)" in prose
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert MAC_LINK in readme and "unverified until the first Mac test (Q-25)" in readme
    assert "`uv path` option" in readme
