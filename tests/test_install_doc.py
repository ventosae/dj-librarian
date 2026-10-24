"""docs/install.md, the one install doc (W-34 item 5, D-28).

Door 1 is the plugin zip. Door 2 is the engine, with no terminal anywhere: one upload (the plugin
zip carries the engine; "set me up" points it at the dj-library folder through the engine's
settings form) and the fallback (the `.mcpb` dragged onto Settings → Extensions). Every write tool
on Ask every time, the Spotify keys in the settings form, the engine's state under
`<dj-library>/.cache/engine/`, the light zip for Door 1 only, and an honest status table (Q-31).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from test_engine_card import FORM, TERMINAL
from test_hook_gate import WRITE_TOOLS

REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "docs" / "install.md"


def _text() -> str:
    return INSTALL.read_text(encoding="utf-8").replace("\r\n", "\n")


def _sections(text: str, level: str = "##") -> dict[str, str]:
    parts = re.split(rf"^{level} (.+)$", text, flags=re.MULTILINE)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}


def _door2() -> str:
    (title,) = [t for t in _sections(_text()) if t.startswith("Door 2")]
    return _sections(_text())[title]


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_two_doors_and_a_status_table():
    titles = list(_sections(_text()))
    assert titles[0].startswith("Door 1") and titles[1].startswith("Door 2")
    assert titles[2] == "Status of each route"
    assert "no terminal" in _text().split("\n## ")[0]


def test_door_2_holds_no_terminal_command():  # D-28: no clone, no uv, no terminal
    door2 = _door2()
    developers = [line for line in door2.split("\n") if line.startswith("Developers:")]
    assert len(developers) == 1  # the one line that sends a developer elsewhere
    dj_path = door2.replace(developers[0], "")
    assert TERMINAL.findall(dj_path) == []
    assert "```" not in door2  # no command block at all
    assert "claude_desktop_config.json" not in _text()


def test_one_upload_set_me_up_and_the_settings_form():
    one = _flat(_sections(_door2(), "###")["One upload: it's already in"])
    assert "The Door 1 zip carries the engine" in one
    assert "Say **set me up** and point Claude at your dj-library folder" in one
    for title in FORM.values():
        assert f"**{title}**" in one, title
    assert "(required)" in one and "(optional)" in one and "leave it off" in one
    assert "`dj_status`" in one and "track count" in one
    assert "**Settings → Extensions → dj-librarian engine**" in one
    assert "unverified (Q-31)" in one
    assert "not a path Claude shows you from Cowork" in one  # Cowork's mount path is not the DJ's


def test_the_one_upload_is_marked_unverified_up_front():
    """Q-31: the route reads as untested from its first line, and the intro says so too."""
    one = _sections(_door2(), "###")["One upload: it's already in"]
    first = next(line for line in one.split("\n") if line.strip())
    assert first == "Unverified until tested (Q-31): if no dj-librarian tools show up, use the fallback below."
    intro = _flat(_text().split("\n## ")[0])
    assert "Whether the engine starts from inside the zip is unverified (Q-31)" in intro


def test_claude_code_has_no_configure_page_for_this_engine():
    """Claude Code 2.1.299 refuses a `uv` bundle inside a plugin; its Configure page appeared only for
    a bundle relabelled `python` (design note), so no doc sends a DJ there."""
    one = _flat(_sections(_door2(), "###")["One upload: it's already in"])
    assert "Configure" not in _text()
    assert "| Claude Code | None yet: Claude Code 2.1.299 does not start this engine from the plugin (Q-31)." in one


def test_no_tools_after_done_means_a_new_task_before_the_fallback():
    """Two engines side by side show every tool twice: a new task (or a restart) comes first."""
    one = _flat(_sections(_door2(), "###")["One upload: it's already in"])
    assert "No dj-librarian tools yet: open a new Cowork task (or restart Claude) and say **set me up** there." in one
    fallback = _flat(_sections(_door2(), "###")["Fallback: the engine on its own"])
    assert fallback.startswith("When no dj-librarian tools show up after the upload, even in a new Cowork task or "
                               "after a restart of Claude")  # fmt: skip


def test_the_fallback_is_the_mcpb_dragged_onto_settings_extensions():
    fallback = _sections(_door2(), "###")["Fallback: the engine on its own"]
    steps = dict(re.findall(r"^(\d)\. (.+)$", fallback, re.MULTILINE))
    assert list(steps) == ["1", "2", "3", "4"]
    assert "`dj-librarian-engine-<version>.mcpb`" in steps["1"] and "Don't unzip it" in steps["1"]
    assert "**Settings → Extensions**" in steps["2"] and "drag the `.mcpb`" in steps["2"]
    assert "**Install**" in steps["2"]
    assert "same four fields" in steps["3"] and "**Ask every time**" in steps["4"]


def test_every_write_tool_on_ask_every_time():
    perms = _sections(_door2(), "###")["Permissions: every write tool on Ask every time"]
    listed = re.findall(r"^\| `(dj_[a-z_]+)` \|", perms, re.MULTILINE)
    assert len(listed) == len(set(listed)) and set(listed) == WRITE_TOOLS
    assert "**Ask every time**" in perms and "Read tools can stay on Allow" in perms
    assert "[permissions.md](permissions.md)" in perms


def test_spotify_keys_go_in_the_settings_form_not_a_dot_env():
    spotify = _flat(_sections(_door2(), "###")["Spotify keys"])
    assert "the engine's settings form" in spotify and "not in a `.env` file, never in the chat" in spotify
    assert "Spotify Premium" in spotify and "dj-spotify" in spotify


def test_where_the_engine_keeps_its_state():
    state = _flat(_sections(_door2(), "###")["Where the engine keeps its state"])
    assert "under `.cache/engine/`" in state
    for kept in ("preview records", "master.db backups"):
        assert kept in state, kept
    assert "Spotify login token stays on this computer, in `.dj-librarian/.cache/`" in state
    assert "nothing is lost" in state and "`.dj-librarian` in your home folder" in state


def test_the_three_artifacts_and_which_door_each_serves():
    text = _flat(_text())
    assert "`dj-librarian-plugin-<version>.zip`" in text
    assert "`dj-librarian-plugin-<version>-no-engine.zip`, is Door 1 only" in text
    assert "`dj-librarian-engine-<version>.mcpb`" in text
    assert "**Customize → Plugins → Add → Upload plugin**" in text


def test_the_status_table_is_honest_about_q31():
    status = _sections(_text())["Status of each route"]
    rows = re.findall(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \|$", status, re.MULTILINE)
    assert [c.strip() for c in rows[0]] == ["Route", "Mac", "Windows"]
    routes = [r[0].strip() for r in rows[1:]]
    assert len(routes) == 4
    assert any("inside the plugin zip" in r for r in routes) and any("`.mcpb`" in r for r in routes)
    flat = _flat(status)
    assert "Claude Code 2.1.299 refuses it" in flat
    assert "the Claude desktop app on Windows, on a Mac, and inside a Cowork session" in flat
    assert "fails closed" in flat  # the known gap: the hook starts uv


def test_developers_are_sent_to_the_readme_and_contributing():
    (line,) = [ln for ln in _door2().split("\n") if ln.startswith("Developers:")]
    assert "(../README.md#install)" in line and "(../CONTRIBUTING.md)" in line


def test_relative_links_resolve():
    for target in re.findall(r"\]\((?!https?:)([^)#]+)(?:#[^)]*)?\)", _text()):
        assert (INSTALL.parent / target).exists(), target


@pytest.fixture(scope="module")
def personal_names() -> list[str]:
    spec = importlib.util.spec_from_file_location("check_personal", REPO / "scripts" / "check_personal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.names()


@pytest.mark.parametrize("rel", ["docs/install.md", "docs/handout/README.md", "docs/handout/dj-librarian-a6.html"])
def test_no_real_names_in_the_dj_docs(rel, personal_names):  # R-1206: these sit outside the grep's paths
    text = (REPO / rel).read_text(encoding="utf-8").casefold()
    for n, name in enumerate(personal_names, start=1):
        assert name.casefold() not in text, f"{rel}: a real name ({n})"
