"""The engine install card (M1, R-102), `dj library use`, and the permissions doc (R-1101, R-1105).

engine.md: offered only on "set me up" or when a feature needs live data, about 10 minutes, three
numbered steps per OS with only that OS shown, every write tool on "ask every time", dj_status as
the proof. docs/permissions.md: every MCP tool in exactly one of read / library-text / write, and
the write list is what the Claude Code hook matches. Both name only the tools the engine has today
(W-23's dj_crate_write joins them when it ships; the hook already matches its name).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from reply_checks import text_problems
from test_hook_gate import PREFIXES, WRITE_TOOLS, matcher
from typer.testing import CliRunner

from dj import cli, libfolder
from dj import mcp_server as m

REPO = Path(__file__).resolve().parents[1]
START = REPO / "plugin" / "skills" / "dj-start"
ENGINE = START / "engine.md"
PERMISSIONS = REPO / "docs" / "permissions.md"
UV_MAC = "curl -LsSf https://astral.sh/uv/install.sh | sh"
UV_WINDOWS = 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'

runner = CliRunner()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _section(text: str, title: str) -> str:
    m_ = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert m_, f"no section ## {title}"
    return m_.group(1)


def cards() -> dict[str, str]:
    """{"Mac": card, "Windows": card} from engine.md's card section."""
    section = _section(_text(ENGINE), "The card")
    blocks = re.findall(r"^(Mac|Windows):\n\n```text\n(.*?)\n```", section, re.MULTILINE | re.DOTALL)
    return dict(blocks)


def _tools() -> dict:
    return {t.name: t for t in asyncio.run(m.server.list_tools())}


def _write_tools() -> set[str]:
    """The write tools the engine has today: the server's tools the hook matches."""
    found = {name for name in _tools() if re.search(matcher(), PREFIXES[0] + name)}
    assert found == WRITE_TOOLS
    return found


# -- engine.md (R-102) -----------------------------------------------------------------------


def test_dj_start_step_6_links_the_engine_card():
    step6 = _text(START / "SKILL.md").split("### Step 6:")[1]
    assert "[engine.md](engine.md)" in step6
    assert ENGINE.is_file()


def test_offered_only_when_asked_or_when_a_feature_needs_live_data():
    when = _section(_text(ENGINE), "When to offer it")
    assert '"set me up"' in when
    for need in ("My Tags", "Spotify", "dj tidy"):
        assert need in when, need
    assert "Never before the first report (R-102)" in when
    assert "Play history" in when and "Never promise it" in when  # Q-13: the engine does not read it


def test_one_card_per_os_and_only_that_os_is_shown():
    section = _section(_text(ENGINE), "The card")
    assert "Show only the block for that device, never both" in section
    found = cards()
    assert list(found) == ["Mac", "Windows"]
    assert "Windows" not in found["Mac"] and "PowerShell" not in found["Mac"]
    assert "Mac" not in found["Windows"] and "Terminal" not in found["Windows"]
    assert UV_MAC in found["Mac"] and UV_WINDOWS in found["Windows"]
    assert UV_WINDOWS not in found["Mac"] and UV_MAC not in found["Windows"]


@pytest.mark.parametrize("device", ["Mac", "Windows"])
def test_the_card_is_three_numbered_steps_in_about_10_minutes(device):
    card = cards()[device]
    lines = [line for line in card.split("\n") if line.strip()]
    assert lines[0].startswith("Step 1 of 2 · about 10 minutes.")
    assert re.findall(r"^(\d)\. ", card, re.MULTILINE) == ["1", "2", "3"]
    install, engine, permissions = re.findall(r"^\d\. (.+)$", card, re.MULTILINE)
    assert install.startswith("Install uv:")
    assert engine.startswith("Get the engine:")
    for part in ("uv sync", "uv run dj library use <your dj-library folder>", "Customize > Plugins",
                 "claude plugin marketplace add ./ then claude plugin install dj-librarian@dj-librarian",
                 "restart Claude", "git clone"):  # fmt: skip
        assert part in engine, part
    # Claude Code loads a plugin from a marketplace added from a local folder in place, so the
    # plugin's .mcp.json (`uv run --directory <plugin folder>/..`) finds the clone (Q-08)
    assert engine.index("claude plugin marketplace add ./") < engine.index("claude plugin install")
    assert "Ask every time" in permissions and "Read tools can stay on Allow" in permissions
    named = set(re.findall(r"\bdj_[a-z_]+\b", permissions))
    assert named == _write_tools()  # only tools the DJ can find in the connector today
    assert "under a minute" in lines[-1]
    assert len(lines) <= 5 and text_problems(card) == []


def test_the_proof_is_dj_status_with_the_track_count():
    proof = _section(_text(ENGINE), "The proof")
    assert "call `dj_status`" in proof and "`tracks`" in proof
    (reply,) = re.findall(r"```text\n(.*?)\n```", proof, re.DOTALL)
    assert reply.startswith("Step 2 of 2 · ") and "<tracks> tracks" in reply
    failures = re.findall(r"^- ", proof, re.MULTILINE)
    assert 1 <= len(failures) <= 5
    assert re.search(r"^- `dj-mcp` not found, or no `pyproject.toml`: .*\(Q-08\)", proof, re.MULTILINE)


def test_the_card_says_where_the_plugin_must_run_from_and_that_cowork_is_open():
    """The plugin starts the engine from the folder above it, so it must run from the clone.
    For Cowork that is unverified (Q-08): the manual registration from the README is the way out."""
    text = " ".join(_text(ENGINE).split())
    assert ".mcp.json" in text and "loads in place" in text and "unverified (Q-08)" in text
    assert "The engine on Windows and macOS" in text
    mcp = json.loads((REPO / "plugin" / ".mcp.json").read_text(encoding="utf-8"))
    assert "${CLAUDE_PLUGIN_ROOT}/.." in mcp["mcpServers"]["dj-librarian"]["args"]


def test_engine_card_passes_the_mechanical_checklist():
    text = _text(ENGINE)
    assert "../../shared/voice.md" in text and "../../shared/adhd.md" in text
    assert re.search(r"R-102\b", text) and "R-1101" in text and "R-1105" in text
    assert text_problems(text) == []


# -- docs/permissions.md (R-1101, R-1105) ------------------------------------------------------


def _table_tools(section: str) -> list[str]:
    return re.findall(r"^\| `(dj_[a-z_]+)` \|", section, re.MULTILINE)


def test_permissions_doc_puts_every_tool_in_exactly_one_group():
    text = _text(PERMISSIONS)
    read = _table_tools(_section(text, "Read tools: Allow (or Ask, your call)"))
    library_text = _table_tools(_section(text, "Library-text tools: Allow or Ask"))
    write = _table_tools(_section(text, "Write tools: Ask every time"))
    listed = read + library_text + write
    assert len(listed) == len(set(listed)), "a tool is listed twice"
    tools = _tools()
    assert set(read) == {n for n, t in tools.items() if t.annotations.read_only_hint}
    assert set(write) == _write_tools()
    assert set(library_text) == {n for n, t in tools.items() if not t.annotations.read_only_hint} - WRITE_TOOLS
    assert set(listed) == set(tools)  # only tools the engine has today


def test_permissions_doc_names_both_gates_and_the_hook_pattern():
    text = _text(PERMISSIONS)
    gates = _section(text, "The two gates")
    assert "Ask every time" in gates and "import" in gates and "PreToolUse hook" in gates
    assert "C-10" in gates and "Q-03" in gates and "power_mode=true" in gates
    assert f"`{matcher()}`" in _section(text, "The hook (Claude Code)")


def test_permissions_doc_claude_code_settings_ask_for_every_write_tool():
    where = _section(_text(PERMISSIONS), "Where to set it")
    (block,) = re.findall(r"```json\n(.*?)\n```", where, re.DOTALL)
    ask = json.loads(block)["permissions"]["ask"]
    prefix = "mcp__plugin_dj-librarian_dj-librarian__"
    assert all(name.startswith(prefix) for name in ask)
    assert {name[len(prefix):] for name in ask} == _write_tools()
    assert all(re.search(matcher(), name) for name in ask)


# -- dj library use <folder> -------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    home = tmp_path / "home" / "someone"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(libfolder, "REPO_ROOT", repo)
    monkeypatch.delenv("DJ_LIBRARY", raising=False)
    return repo


def _library(path: Path) -> Path:
    path.mkdir(parents=True)
    libfolder.scaffold(path, device="mac")
    return path


def use(*args):
    return runner.invoke(cli.app, ["library", "use", *[str(a) for a in args]])


def test_use_stores_the_folder_and_prints_it(fake_repo, tmp_path):
    lib = _library(tmp_path / "Music Stuff" / "dj-library")
    result = use(lib)
    assert result.exit_code == 0, result.output
    stored = lib.resolve()
    assert result.output.splitlines()[0] == f"Library folder: {stored}"
    assert (fake_repo / "state" / "library-path.txt").read_text(encoding="utf-8") == f"{stored}\n"
    assert libfolder.configured_root() == stored


def test_use_json_and_the_env_var_still_wins(fake_repo, tmp_path, monkeypatch):
    lib = _library(tmp_path / "dj-library")
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path / "elsewhere"))
    data = json.loads(use(lib, "--json").output)
    assert data == {"library": str(lib.resolve()), "stored_in": "state/library-path.txt",
                    "in_use": str((tmp_path / "elsewhere").resolve())}  # fmt: skip
    assert "DJ_LIBRARY is set and wins" in use(lib).output


def test_use_refuses_a_missing_folder(fake_repo, tmp_path):
    result = use(tmp_path / "nope")
    assert result.exit_code == 1 and "is not a folder" in result.output
    assert not (fake_repo / "state").exists()


def test_use_refuses_a_folder_that_is_not_set_up(fake_repo, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = use(plain)
    assert result.exit_code == 2 and "REFUSED" in result.output and "no library.yaml" in result.output
    assert not (fake_repo / "state").exists()


def test_use_stores_nothing_when_dj_library_is_unusable(fake_repo, tmp_path, monkeypatch):
    """An unusable DJ_LIBRARY (here the home folder) is refused before the folder is stored."""
    lib = _library(tmp_path / "dj-library")
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path / "home" / "someone"))
    result = use(lib)
    assert result.exit_code == 2 and "REFUSED DJ_LIBRARY" in result.output and "Nothing was stored" in result.output
    assert not (fake_repo / "state" / "library-path.txt").exists()


def test_use_refuses_the_home_folder_even_with_a_library_yaml(fake_repo, tmp_path):
    home = tmp_path / "home" / "someone"
    (home / "library.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    result = use(home)
    assert result.exit_code == 2 and "not a library folder" in result.output
    assert not (fake_repo / "state" / "library-path.txt").exists()
