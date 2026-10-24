"""plugin/commands/install.md and uninstall.md (W-35, D-29): the commands Claude Code follows to
install the engine on a DJ's Mac or Windows PC, one shell command per step, the DJ clicking Allow."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMMANDS = REPO / "plugin" / "commands"


def _text(name: str) -> str:
    return (COMMANDS / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def _front(name: str) -> str:
    return _text(name).split("---")[1]


def _steps(name: str) -> dict[str, str]:
    """{step title: its text}, from the `N. **Title.** ...` items in order."""
    items = re.findall(r"^(\d)\. \*\*(.+?)\.\*\* (.+?)(?=^\d\. \*\*|\Z)", _text(name), re.MULTILINE | re.DOTALL)
    assert [int(n) for n, _t, _b in items] == list(range(1, len(items) + 1))
    return {title: " ".join(body.split()) for _n, title, body in items}


def test_both_commands_are_the_djs_to_type():
    for name in ("install.md", "uninstall.md"):
        front = _front(name)
        assert re.search(r"^description: .+", front, re.MULTILINE), name
        assert "disable-model-invocation: true" in front, name  # never runs on its own


def test_install_is_eight_steps_in_the_briefs_order():
    assert list(_steps("install.md")) == ["Which computer", "uv", "The engine folder", "Dependencies", "The proof",
                                          "The dj-library folder", "Claude Desktop's config", "Restart"]  # fmt: skip
    text = " ".join(_text("install.md").split())
    assert "Step N of 8 · <what>" in text and "send this line to whoever gave you the plugin" in text
    assert "never change anything in it except `mcpServers[\"dj-librarian\"]`" in text
    assert '`& "<uv>" sync ...`' in text and "`UV_PROJECT_ENVIRONMENT` unset" in text  # PowerShell, own venv


def test_install_detects_the_os_and_stops_elsewhere():
    step = _steps("install.md")["Which computer"]
    assert "`uname -s`" in step and "`$env:OS`" in step
    assert "This installs on a Mac or a Windows PC only." in step and "stop" in step


def test_install_finds_or_installs_uv_and_keeps_its_absolute_path():
    step = _steps("install.md")["uv"]
    assert "`command -v uv || ~/.local/bin/uv --version`" in step
    assert "`curl -LsSf https://astral.sh/uv/install.sh | sh`" in step
    assert '`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`' in step
    assert "never a bare `uv`" in step


def test_install_copies_the_engine_out_of_synced_folders_with_a_backup_first():
    step = _steps("install.md")["The engine folder"]
    assert "`~/dj-librarian`" in step and "`%USERPROFILE%\\dj-librarian`" in step
    assert "`${CLAUDE_PLUGIN_ROOT}/engine/`" in step and "This copy of the plugin has no engine inside" in step
    for synced in ("OneDrive", "Dropbox", "iCloud", "`~/Library/dj-librarian`", "`%LOCALAPPDATA%\\dj-librarian`"):
        assert synced in step, synced
    assert step.index("back it up first") < step.index("Then copy")
    assert "dj-librarian.bak-<YYYY-MM-DD>" in step and "Never over an existing backup" in step
    assert "`BUILD.txt` is the same as the source's: copy nothing" in step  # idempotent, even under one version
    assert "it is not an engine folder. Say so and stop." in step


def test_install_syncs_proves_and_stops_before_the_config_on_failure():
    steps = _steps("install.md")
    assert '`"<uv>" sync --directory "<engine folder>" --no-dev`' in steps["Dependencies"]
    proof = steps["The proof"]
    assert '`"<uv>" run --directory "<engine folder>" --no-sync dj status`' in proof
    assert "Do not go on to the config." in proof


def test_install_asks_for_the_library_once_and_writes_it_as_dj_library():
    ask = _steps("install.md")["The dj-library folder"]
    assert "Ask once" in ask and "`library.yaml`" in ask and "stop" in ask
    merge = _steps("install.md")["Claude Desktop's config"]
    assert '"<engine folder>/scripts/merge_desktop_config.py" merge --uv "<uv>" --folder "<engine folder>" ' \
           '--library "<dj-library folder>"' in merge  # fmt: skip
    assert "`DJ_LIBRARY`" in merge and "claude_desktop_config.json.bak-<date>" in merge
    assert "keeps every other key" in merge


def test_install_ends_with_the_restart_and_the_set_me_up_line():
    step = _steps("install.md")["Restart"]
    assert "Restart Claude Desktop." in step and "Customize → Connectors → dj-librarian" in step
    assert "`_apply`, `_write`, `_undo`" in step and "Ask every time" in step
    assert 'End with one line: `say "set me up" in a Cowork task to check it`.' in step


def test_uninstall_removes_only_our_entry_and_keeps_the_folder():
    steps = _steps("uninstall.md")
    assert list(steps) == ["uv", "The config", "Restart"]
    assert '"<engine folder>/scripts/merge_desktop_config.py" remove' in steps["The config"]
    assert "`${CLAUDE_PLUGIN_ROOT}/engine/scripts/merge_desktop_config.py`" in steps["The config"]
    assert "backs the config up" in steps["The config"] and "only the `dj-librarian` entry" in steps["The config"]
    assert "untouched" in steps["Restart"] and "delete no folder" in _text("uninstall.md")
