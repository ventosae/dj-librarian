"""The engine set-up card (M1, R-102), `dj library use`, and the permissions doc (R-1101, R-1105).

engine.md (W-35, D-29): offered only on "set me up" or when a feature needs live data. The engine
installs with `/dj-librarian:install`, typed by the DJ in Claude Code's Code tab (they click Allow;
no terminal of their own): one card for both OSes, three numbered steps in about 5 minutes (type the
command, Allow and the dj-library folder, restart and every write tool on "ask every time"),
dj_status as the proof, the `.mcpb` as the second route. docs/permissions.md: every MCP tool in
exactly one of read / library-text / write, and the write list is what the Claude Code hook matches.
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
MANIFEST = REPO / "mcpb" / "manifest.json"
# The titles of the engine's settings form (mcpb/manifest.json `user_config`), as the DJ sees them.
FORM = {
    "library_folder": "dj-library folder",
    "spotify_client_id": "Spotify client ID",
    "spotify_client_secret": "Spotify client secret",
    "power_mode": "Power mode (Windows)",
}
# What a terminal step looks like: the DJ path holds none of these (D-28). The apps by their names
# (Terminal, PowerShell), so prose may still say that nobody opens a terminal.
TERMINAL = re.compile(
    r"\buv (?:run|sync|tool|pip|add)\b|\bgit clone\b|\bcurl\b|\birm\b|\bsudo\b|\b[Pp]ower[Ss]hell\b|\bTerminal\b"
    r"|\bpip install\b|\bnpx\b|\bclaude (?:plugin|mcp)\b|\bcd \w|\bln -s|uv_path|uv path|\.mcp\.json"
)

runner = CliRunner()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _section(text: str, title: str) -> str:
    m_ = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert m_, f"no section ## {title}"
    return m_.group(1)


def card() -> str:
    """The one card in engine.md's card section."""
    (block,) = re.findall(r"^```text\n(.*?)\n```", _section(_text(ENGINE), "The card"), re.MULTILINE | re.DOTALL)
    return block


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
    # A new task after the form is saved: "set me up" there finds the tools and goes to the proof.
    assert '`dj_status` is already there when the DJ says "set me up": skip the card, go to the proof' in when


def test_the_install_command_is_the_route_and_the_mcpb_the_second():
    top = " ".join(_text(ENGINE).split("\n## ")[0].split())
    assert "`/dj-librarian:install`" in top and "Code tab" in top and "clicks Allow" in top
    assert "opens no terminal of their own" in top and "about 5 minutes" in top
    assert "(Q-32)" in top and "`dj-librarian-engine-<version>.mcpb`" in top and "(Q-31)" in top


def test_no_terminal_command_anywhere_in_the_card_file():  # the DJ types only the slash command
    text = _text(ENGINE)
    assert TERMINAL.findall(text) == []
    assert "git" not in re.findall(r"\b\w+\b", text.lower())


def test_one_card_for_both_oses_and_the_command_is_the_djs_to_type():
    section = " ".join(_section(_text(ENGINE), "The card").split())
    assert "One card for Mac and Windows" in section and "Mac:" not in section
    assert "The command is the DJ's to type: it never runs on its own." in section
    command = _text(REPO / "plugin" / "skills" / "install" / "SKILL.md")
    assert "disable-model-invocation: true" in command.split("---")[1]


def test_the_card_names_the_folder_never_a_cowork_path():
    """In Cowork, Claude sees the folder where Cowork mounts it, not where it sits on the DJ's computer."""
    section = " ".join(_section(_text(ENGINE), "The card").split())
    assert "Never send them a path you see in Cowork" in section
    (folder,) = [s for s in re.findall(r"^\d\. (.+)$", card(), re.MULTILINE) if "dj-library" in s]
    assert "say ok for the one it offers or drag another in" in folder  # W-36: the install makes it


def test_the_card_is_three_numbered_steps_in_about_5_minutes():
    text = card()
    lines = [line for line in text.split("\n") if line.strip()]
    assert lines[0].startswith("Step 1 of 2 · about 5 minutes.")
    assert re.findall(r"^(\d)\. ", text, re.MULTILINE) == ["1", "2", "3"]
    command, allow, permissions = re.findall(r"^\d\. (.+)$", text, re.MULTILINE)
    assert "open the Code tab and type /dj-librarian:install" in command
    assert allow.startswith("Click Allow on each step")
    assert permissions.startswith("Restart Claude") and "Customize > Connectors > dj-librarian" in permissions
    assert re.findall(r"\bdj_[a-z_]+\b", permissions) == []  # adhd.md rule 9: no list of 9 in the card
    write = _write_tools()
    assert f"every tool whose name ends in _apply, _write or _undo to Ask every time ({len(write)} tools)" in permissions
    assert {name for name in _tools() if re.search(r"_(?:apply|write|undo)$", name)} == write
    assert "under a minute" in lines[-1] and lines[-1].startswith("Say set me up in a new Cowork task")
    assert len(lines) <= 5 and text_problems(text) == []
    assert TERMINAL.findall(text) == []


def test_the_card_section_names_the_write_tools_the_keys_and_the_state():
    section = " ".join(_section(_text(ENGINE), "The card").split())
    named = re.search(r"The \d+ write tools are (.+?)\.", section).group(1)
    assert set(re.findall(r"\bdj_[a-z_]+\b", named)) == _write_tools()  # for Claude, if the DJ asks
    assert "a `.env` file in the engine folder" in section and "never the dj-library folder" in section
    assert "Never into the chat" in section
    for title in FORM.values():  # the extension's form, as the manifest names it
        assert title in section, title
    assert "backs that folder up first" in section and "`.cache/engine/`" in section


def test_the_form_titles_match_the_manifest():
    """The bundle's manifest asks for exactly these four fields."""
    config = json.loads(MANIFEST.read_text(encoding="utf-8"))["user_config"]
    assert {key: field["title"] for key, field in config.items()} == FORM


def test_the_proof_is_dj_status_with_the_track_count():
    proof = _section(_text(ENGINE), "The proof")
    assert "call `dj_status`" in proof and "`tracks`" in proof
    (reply,) = re.findall(r"```text\n(.*?)\n```", proof, re.DOTALL)
    assert reply.startswith("Step 2 of 2 · ") and "<tracks> tracks" in reply
    failures = re.findall(r"^- (.+)$", proof, re.MULTILINE)
    assert 1 <= len(failures) <= 5
    no_tools = next(line for line in failures if line.startswith("No `dj_status` tool"))
    assert no_tools.index("Restart Claude") < no_tools.index("/dj-librarian:install")
    stopped = next(line for line in failures if line.startswith("The command stopped"))
    for part in ("whoever gave them the plugin", "`dj-librarian-engine-<version>.mcpb`", "Settings > Extensions",
                 "Install", "(Q-31)"):  # fmt: skip
        assert part in stopped, part
    assert any("no library folder" in line and "`library.yaml`" in line for line in failures)


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
