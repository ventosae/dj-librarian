"""The engine set-up card (M1, R-102), `dj library use`, and the permissions doc (R-1101, R-1105).

engine.md (W-34, D-28): offered only on "set me up" or when a feature needs live data. The engine
comes inside the plugin zip or as the `.mcpb` on its own, so the card holds no terminal command:
one card for both OSes, three numbered steps in about 3 minutes (the dj-library folder in the
engine settings, the optional Spotify keys in the same form, every write tool on "ask every time"),
dj_status as the proof, a new task and then the `.mcpb` as the fallback; no card in Claude Code,
which refuses the bundle inside a plugin (Q-31). docs/permissions.md: every MCP tool in exactly
one of read / library-text / write, and the write list is what the Claude Code hook matches. Both
name only the tools the engine has today.
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
# `<engine settings>` per way the engine came in. The plugin's own settings place is unverified
# (Q-31), so its row says "not there? say so". Claude Code gets no card: 2.1.299 refuses the bundle.
SETTINGS = {
    "Inside the plugin zip": "Settings > Extensions > dj-librarian engine (not there? say so)",
    "The `.mcpb` on its own": "Settings > Extensions > dj-librarian engine",
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


def test_the_engine_comes_in_the_zip_or_as_the_mcpb_and_needs_no_terminal():
    top = " ".join(_text(ENGINE).split("\n## ")[0].split())
    assert "inside the plugin zip" in top and "`dj-librarian-engine-<version>.mcpb`" in top
    assert "installs nothing and never opens a terminal" in top
    assert "about 3 minutes" in top
    assert "unverified until it has run once (Q-31)" in top and "the `.mcpb` is the fallback" in top


def test_no_terminal_command_anywhere_in_the_card_file():  # D-28: no clone, no uv, no terminal
    text = _text(ENGINE)
    assert TERMINAL.findall(text) == []
    assert "git" not in re.findall(r"\b\w+\b", text.lower())


def test_one_card_for_both_oses_with_the_settings_per_way_the_engine_came_in():
    section = _section(_text(ENGINE), "The card")
    assert "One card for Mac and Windows, in the Claude desktop app and in Cowork" in section
    assert "Mac:" not in section and "Windows:\n" not in section
    rows = dict(re.findall(r"^\| ([^|]+?) \| ([^|]+?) \|$", section, re.MULTILINE))
    assert rows.pop("How the engine came in") == "`<engine settings>`"
    assert rows == SETTINGS
    prose = " ".join(section.split())
    assert "inside the plugin zip unless the DJ says they installed the `.mcpb`" in prose
    assert "Where a plugin's own engine settings show is unverified (Q-31)" in prose
    assert "Settings > Extensions is where the fallback puts them" in prose
    assert "Configure" not in section  # Claude Code's plugin Configure page exists only for a bundle it takes


def test_claude_code_gets_no_card():
    """Claude Code 2.1.299 refuses a `uv` bundle inside a plugin (Q-31): no settings to point at."""
    prose = " ".join(_section(_text(ENGINE), "The card").split())
    assert "Claude Code: send no card. Claude Code 2.1.299 does not start this engine from the plugin (Q-31)." in prose
    assert "the report, builds and crates keep running on the XML" in prose


def test_the_card_names_the_folder_never_a_cowork_path():
    """In Cowork, Claude sees the folder where Cowork mounts it, not where it sits on the DJ's computer."""
    section = _section(_text(ENGINE), "The card")
    assert "<your dj-library folder>" not in section and "full path" not in section
    assert "Never send them a path you see in Cowork" in " ".join(section.split())
    (folder,) = re.findall(r"^1\. (.+)$", card(), re.MULTILINE)
    assert "your dj-library folder there, the one you connected in Cowork (library.yaml is in it)" in folder


def test_the_card_is_three_numbered_steps_in_about_3_minutes():
    text = card()
    lines = [line for line in text.split("\n") if line.strip()]
    assert lines[0].startswith("Step 1 of 2 · about 3 minutes. The engine is already in.")
    assert re.findall(r"^(\d)\. ", text, re.MULTILINE) == ["1", "2", "3"]
    folder, spotify, permissions = re.findall(r"^\d\. (.+)$", text, re.MULTILINE)
    assert folder.startswith("Open <engine settings> and pick your dj-library folder")
    assert "Leave Power mode off" in folder
    assert spotify.startswith("Spotify client ID and secret") and "leave both empty" in spotify
    assert "Ask every time" in permissions and "Read tools can stay on Allow" in permissions
    assert re.findall(r"\bdj_[a-z_]+\b", permissions) == []  # adhd.md rule 9: no list of 9 in the card
    write = _write_tools()
    assert f"every tool whose name ends in _apply, _write or _undo to Ask every time ({len(write)} tools)" in permissions
    assert {name for name in _tools() if re.search(r"_(?:apply|write|undo)$", name)} == write
    assert "under a minute" in lines[-1] and lines[-1].startswith("Say done")
    assert len(lines) <= 5 and text_problems(text) == []
    assert TERMINAL.findall(text) == []


def test_the_card_names_the_settings_form_the_way_the_manifest_does():
    section = " ".join(_section(_text(ENGINE), "The card").split())
    for title in FORM.values():
        assert title in section, title
    assert "never into the chat or a `.env`" in section
    assert "`.cache/engine/`" in section  # state outlives an engine update
    named = re.search(r"The \d+ write tools are (.+?)\.", section).group(1)
    assert set(re.findall(r"\bdj_[a-z_]+\b", named)) == _write_tools()  # for Claude, if the DJ asks


def test_the_form_titles_match_the_manifest():
    """The bundle's own manifest (W-34 item 1) asks for exactly these four fields."""
    if not MANIFEST.is_file():
        pytest.skip("mcpb/manifest.json is built by the engine bundle stream")
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
    for part in ("the fallback", "`dj-librarian-engine-<version>.mcpb`", "Settings > Extensions",
                 "Install", "from the release or from whoever is testing with them"):  # fmt: skip
        assert part in no_tools, part
    # A new task (or a restart) first: a second engine next to the first shows every tool twice.
    new_task = "Saved: the DJ opens a new Cowork task (or restarts Claude) and says set me up there."
    assert new_task in no_tools and no_tools.index(new_task) < no_tools.index("the fallback")
    assert any("no library folder" in line and "<engine settings>" in line for line in failures)
    assert any("(Q-31)" in line for line in failures)
    assert not any("Configure" in line for line in failures)


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
