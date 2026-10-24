"""docs/install.md, the one install doc (W-34, W-35; D-28, D-29).

Door 1 is the plugin zip. Door 2 is the engine in three routes, in this order: `/dj-librarian:install`
in Claude Code (the DJ types one line and clicks Allow; no terminal of their own), the `.mcpb`
dragged onto Settings → Extensions, and by hand from a clone (developers). Every write tool on Ask
every time, where the Spotify keys and the state live for each route, the light zip for Door 1 only,
and an honest status table (Q-31, Q-32).
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


def _routes() -> dict[str, str]:
    return {title: _flat(body) for title, body in _sections(_door2(), "###").items()}


def test_three_routes_in_order_with_no_terminal_for_the_dj():
    titles = list(_sections(_door2(), "###"))
    assert titles[:3] == ["1. The install command (first choice)", "2. The desktop extension (second choice)",
                          "3. By hand (third choice)"]  # fmt: skip
    for title in titles[:2]:  # the DJ's routes: no command for them to type in a terminal
        assert TERMINAL.findall(_sections(_door2(), "###")[title]) == [], title
    assert "```" not in _door2()


def test_the_install_command_route():
    cmd = _routes()["1. The install command (first choice)"]
    assert "**Code** tab" in cmd and "**`/dj-librarian:install`**" in cmd and "**Allow**" in cmd
    assert "asks once for your dj-library folder" in cmd and "a backup of the config first" in cmd
    assert "Restart Claude Desktop" in cmd and "**Customize → Connectors → dj-librarian**" in cmd
    assert "say **set me up**" in cmd and "`dj_status`" in cmd
    assert "`/dj-librarian:uninstall`" in cmd and "(Q-32)" in cmd


def test_the_desktop_extension_route():
    ext = _routes()["2. The desktop extension (second choice)"]
    assert "`dj-librarian-engine-<version>.mcpb`" in ext and "**Settings → Extensions**" in ext and "**Install**" in ext
    for title in FORM.values():
        assert f"**{title}**" in ext, title
    assert "Unverified (Q-31)" in ext and "install one route only" in ext


def test_by_hand_sends_developers_to_the_readme_and_contributing():
    hand = _routes()["3. By hand (third choice)"]
    assert "(../README.md#install)" in hand and "(../CONTRIBUTING.md)" in hand


def test_every_write_tool_on_ask_every_time():
    perms = _sections(_door2(), "###")["Permissions: every write tool on Ask every time"]
    listed = re.findall(r"^\| `(dj_[a-z_]+)` \|", perms, re.MULTILINE)
    assert len(listed) == len(set(listed)) and set(listed) == WRITE_TOOLS
    assert "**Ask every time**" in perms and "Read tools can stay on Allow" in perms
    assert "[permissions.md](permissions.md)" in perms


def test_spotify_keys_per_route():
    spotify = _routes()["Spotify keys"]
    assert "a `.env` file in the engine folder" in spotify and "never the dj-library folder" in spotify
    assert "its settings form" in spotify
    assert "Never paste the keys into the chat" in spotify and "Spotify Premium" in spotify and "dj-spotify" in spotify


def test_where_the_engine_keeps_its_state_per_route():
    state = _routes()["Where the engine keeps its state"]
    assert "`dj-librarian` in your home folder" in state and "`dj-librarian.bak-<date>`" in state
    assert "under `.cache/engine/`" in state and "master.db backups" in state
    assert "`.dj-librarian/.cache/` in your home folder, never in the dj-library folder" in state


def test_the_three_artifacts_and_which_door_each_serves():
    text = _flat(_text())
    assert "`dj-librarian-plugin-<version>.zip`" in text
    assert "`dj-librarian-plugin-<version>-no-engine.zip`" in text and "Door 1 only" in text
    assert "`dj-librarian-engine-<version>.mcpb`" in text
    assert "**Customize → Plugins → Add → Upload plugin**" in text


def test_the_status_table_is_honest():
    status = _sections(_text())["Status of each route"]
    rows = re.findall(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \|$", status, re.MULTILINE)
    assert [c.strip() for c in rows[0]] == ["Route", "Mac", "Windows"]
    routes = [r[0].strip() for r in rows[1:]]
    assert len(routes) == 4
    assert any("`/dj-librarian:install`" in r for r in routes) and any("`.mcpb`" in r for r in routes)
    flat = _flat(status)
    assert "Q-32 stays open until the install command has run on a Mac" in flat
    assert "on Windows, on a Mac, and inside a Cowork session" in flat


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
