"""R-803: the shopping list. Offline: a plan + the pulled inbox -> wishlist/<crate>.shopping.md.

No network (the links are built, never fetched), no rekordbox, files only under tmp_path.
"""

from __future__ import annotations

import asyncio
import functools
import json
import socket
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from dj import cli, intake, libfolder, shopping
from dj import mcp_server as m

runner = CliRunner()
REAL_PATHS = intake.Paths
TODAY = date(2026, 10, 20)
CRATE = "House/1.1_warm_up"
SLUG = "House_1.1_warm_up"


def plan_item(uri, text, status):
    return {"spotify_uri": uri, "spotify": text, "status": status, "url": "https://open.spotify.com/track/x",
            "decision": None, "pick": None, "candidates": []}


PLAN = {
    "spotify": "warmup_inbox",
    "crate": CRATE,
    "items": [
        plan_item("spotify:track:p1", "Tessa Quorum - Open Plan", "PROPOSE"),
        plan_item("spotify:track:m1", "Fennel Arcade - Quiet Machinery", "MISSING"),
        plan_item("spotify:track:m2", "Rook & Ash, Vey - Two/Three (Dub?)", "MISSING"),
        plan_item("spotify:track:m3", "Pale | Pipe - Ditto", "MISSING"),
        plan_item("spotify:track:m1", "Fennel Arcade - Quiet Machinery", "MISSING"),  # listed twice
        plan_item("spotify:track:d1", "Someone - Declined", "DECLINED"),
    ],
}
INBOX = {
    "tracks": [
        {"uri": "spotify:track:m1", "title": "Quiet Machinery", "artists": ["Fennel Arcade"],
         "label": "Harbour Light Records"},
        {"uri": "spotify:track:m2", "title": "Two/Three (Dub?)", "artists": ["Rook & Ash", "Vey"],
         "label": None},
        {"uri": "spotify:track:p1", "title": "Open Plan", "artists": ["Tessa Quorum"], "label": "Low Ceiling"},
    ]
}


@pytest.fixture
def no_sockets(monkeypatch):
    """Stronger than conftest: creating any socket at all fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("the shopping list tried to open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def write_case(root, plan=PLAN, inbox=INBOX, day="2026-10-20"):
    paths = REAL_PATHS(root, library=True)
    paths.plans.mkdir(parents=True, exist_ok=True)
    (paths.plans / f"{day}-{SLUG}.plan.json").write_text(json.dumps(plan), encoding="utf-8")
    if inbox is not None:
        paths.inbox.mkdir(parents=True, exist_ok=True)
        (paths.inbox / f"{SLUG}.json").write_text(json.dumps(inbox), encoding="utf-8")
    return paths


def shop(paths, **kw):
    return shopping.shop(paths.root, plans=paths.plans, inbox=paths.inbox / f"{SLUG}.json",
                         wishlist=paths.wishlist, crate=CRATE, spotify="warmup_inbox", slug=SLUG,
                         library=paths.library, today=TODAY, now=datetime(2026, 10, 20, 21, 5), **kw)


# -- rows and links ------------------------------------------------------------------------


def test_rows_are_the_missing_items_once_in_plan_order_enriched_from_the_inbox():
    rows = shopping.rows(PLAN, INBOX)
    assert [r.line for r in rows] == ["Fennel Arcade - Quiet Machinery", "Rook & Ash, Vey - Two/Three (Dub?)",
                                      "Pale | Pipe - Ditto"]
    assert [r.label for r in rows] == ["Harbour Light Records", "", ""]


def test_without_the_inbox_rows_come_from_the_plan_text():
    rows = shopping.rows(PLAN, None)
    assert (rows[1].artist, rows[1].title) == ("Rook & Ash, Vey", "Two/Three (Dub?)")
    assert all(r.label == "" for r in rows)


def test_search_links_are_url_encoded_and_use_the_first_artist():
    row = shopping.rows(PLAN, INBOX)[1]
    assert row.query == "Rook & Ash Two/Three (Dub?)"
    assert shopping.beatport_url(row) == "https://www.beatport.com/search?q=Rook+%26+Ash+Two%2FThree+%28Dub%3F%29"
    assert shopping.bandcamp_url(row) == "https://bandcamp.com/search?q=Rook+%26+Ash+Two%2FThree+%28Dub%3F%29"


def test_an_artist_with_a_comma_in_the_name_stays_whole_when_the_inbox_lists_it():
    plan = {"items": [plan_item("spotify:track:k1", "Salt, Pepper & Co, Vey - Brine", "MISSING")]}
    inbox = {"tracks": [{"uri": "spotify:track:k1", "title": "Brine", "artists": ["Salt, Pepper & Co", "Vey"]}]}
    assert shopping.rows(plan, inbox)[0].query == "Salt, Pepper & Co Brine"
    assert shopping.rows(plan, None)[0].query == "Salt Brine"  # plan text only: best effort


def test_newest_plan_for_exactly_this_crate_wins(tmp_path):
    for name in ("2026-10-01-House_1.1_warm_up.plan.json", "2026-10-19-House_1.1_warm_up.plan.json",
                 "2026-10-25-x-House_1.1_warm_up.plan.json", "2026-10-26-tidy-House.plan.json", "notes.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert shopping.latest_plan(tmp_path, SLUG).name == "2026-10-19-House_1.1_warm_up.plan.json"
    assert shopping.latest_plan(tmp_path, "nope") is None
    assert shopping.latest_plan(tmp_path / "missing", SLUG) is None


def test_a_plan_is_found_after_the_crate_case_changed(tmp_path):
    # Windows / macOS: the DJ fixes 'House/...' to 'house/...' in links.yaml and runs `dj plan`
    # the same day; write_plan writes into the existing file, which keeps its old name.
    (tmp_path / "2026-10-19-HOUSE_1.1_WARM_UP.plan.json").write_text("{}", encoding="utf-8")
    (tmp_path / f"2026-10-20-{SLUG}.plan.json").write_text("{}", encoding="utf-8")
    assert shopping.latest_plan(tmp_path, SLUG.lower()).name == f"2026-10-20-{SLUG}.plan.json"
    assert shopping.latest_plan(tmp_path, SLUG.upper()).name == f"2026-10-20-{SLUG}.plan.json"


def test_on_one_date_the_exact_case_wins_where_both_names_can_exist(tmp_path):
    names = (f"2026-10-20-{SLUG}.plan.json", f"2026-10-20-{SLUG.lower()}.plan.json")
    for name in names:
        (tmp_path / name).write_text(json.dumps({"name": name}), encoding="utf-8")
    on_disk = sorted(p.name for p in tmp_path.iterdir())
    if len(on_disk) == 1:  # case-insensitive filesystem: one file, whatever its name
        assert shopping.latest_plan(tmp_path, SLUG.lower()).name == on_disk[0]
        assert shopping.latest_plan(tmp_path, SLUG).name == on_disk[0]
    else:  # Linux: both exist, the exact one wins, on every run
        assert shopping.latest_plan(tmp_path, SLUG.lower()).name == names[1]
        assert shopping.latest_plan(tmp_path, SLUG).name == names[0]


def test_the_cli_finds_the_plan_after_a_case_fix_in_links_yaml(library, no_sockets):
    write_case(library.resolve())  # plan named after 'House/1.1_warm_up'
    (library / "links.yaml").write_text(f"- spotify: warmup_inbox\n  crate: {CRATE.lower()}\n",
                                        encoding="utf-8")
    result = runner.invoke(cli.app, ["wishlist", "shop", "warmup_inbox", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["plan"] == f"plans/2026-10-20-{SLUG}.plan.json"


# -- the last pull against the plan --------------------------------------------------------


@pytest.mark.parametrize(("created", "pulled_at", "expected"), [
    ("2026-10-20T10:00:00", "2026-10-20T11:30:00", True),  # pulled after the plan
    ("2026-10-20T10:00:00", "2026-10-20T09:00:00", False),  # plan from the last pull
    ("2026-10-20T10:00:00", None, False),  # nothing to compare
    (None, "2026-10-20T11:30:00", False),
    ("2026-10-20T10:00:00", "not a time", False),
])
def test_stale_compares_the_last_pull_with_the_plan(created, pulled_at, expected):
    plan = {"created": created} if created else {}
    inbox = {"pulled_at": pulled_at} if pulled_at else {}
    assert shopping.stale(plan, inbox) is expected


def test_a_pull_newer_than_the_plan_is_flagged_in_file_and_json(tmp_path):
    plan = dict(PLAN, created="2026-10-20T10:00:00")
    paths = write_case(tmp_path, plan=plan, inbox=dict(INBOX, pulled_at="2026-10-20T11:30:00"))
    result = shop(paths)
    assert result["stale_plan"] is True
    text = (tmp_path / "wishlist" / f"{SLUG}.shopping.md").read_text(encoding="utf-8")
    summary = text.split("## Summary\n\n")[1].split("\n\n")[0].splitlines()
    assert len(summary) <= 5
    assert any("Out of date" in line and "`dj plan`" in line for line in summary)

    write_case(tmp_path, plan=plan, inbox=dict(INBOX, pulled_at="2026-10-20T09:00:00"))
    assert shop(paths)["stale_plan"] is False
    assert "Out of date" not in (tmp_path / "wishlist" / f"{SLUG}.shopping.md").read_text(encoding="utf-8")


def test_the_cli_text_warns_about_a_stale_plan(library):
    write_case(library.resolve(), plan=dict(PLAN, created="2026-10-20T10:00:00"),
               inbox=dict(INBOX, pulled_at="2026-10-20T11:30:00"))
    result = runner.invoke(cli.app, ["wishlist", "shop", "warmup_inbox"])
    assert result.exit_code == 0, result.output
    assert "OUT OF DATE" in result.output and "dj plan" in result.output


# -- the file ------------------------------------------------------------------------------


def test_file_content(tmp_path, no_sockets):
    paths = write_case(tmp_path)
    result = shop(paths)
    text = (tmp_path / "wishlist" / f"{SLUG}.shopping.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == f"# Shopping list: {CRATE}"
    assert lines[2] == f"> Measured by code: dj.shopping from plans/2026-10-20-{SLUG}.plan.json, 2026-10-20."
    assert "Generated file: every `dj wishlist shop` rewrites it" in lines[4]

    summary = text.split("## Summary\n\n")[1].split("\n\n")[0].splitlines()
    assert 1 <= len(summary) <= 5 and all(s.startswith("- ") for s in summary)
    assert summary[0] == "- 3 track(s) on Spotify `warmup_inbox` have no local file."
    assert summary[1] == "- Top labels: Harbour Light Records (1)."
    assert text.count("no audio features") == 1  # said once

    table = [line for line in lines if line.startswith("| ")]
    assert table[0] == "| Artist - Title | Beatport | Bandcamp | Label | BPM | Key |"
    assert len(table) == 1 + 3
    assert table[1] == ("| Fennel Arcade - Quiet Machinery | [search](https://www.beatport.com/search?q=Fennel+Arcade+Quiet+Machinery) | "
                        "[search](https://bandcamp.com/search?q=Fennel+Arcade+Quiet+Machinery) | Harbour Light Records | - | - |")
    assert table[2].endswith("| - | - | - |")  # no label from Spotify -> "-"
    assert table[3].startswith("| Pale \\| Pipe - Ditto |")  # a pipe in a name cannot break the table
    assert "Tessa Quorum" not in text and "Declined" not in text and "D:/" not in text

    assert result["missing"] == 3 and result["file"] == f"wishlist/{SLUG}.shopping.md"
    assert result["labels"] == [{"label": "Harbour Light Records", "tracks": 1}]


def test_log_line_in_a_library_folder(tmp_path):
    libfolder.scaffold(tmp_path, device="mac", today=TODAY)
    result = shop(write_case(tmp_path))
    line = f"2026-10-20 21:05 wishlist shop {CRATE} -> 3 missing; wishlist/{SLUG}.shopping.md"
    assert result["log"] == line
    assert (tmp_path / "log.md").read_text(encoding="utf-8").splitlines()[-1] == line


def test_repo_layout_writes_no_log_line(tmp_path):
    write_case(tmp_path, inbox=None)  # plans/ sits at the root in both layouts
    paths = REAL_PATHS(tmp_path)  # repo layout: inbox/ at the root too, no .cache/
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / f"{SLUG}.json").write_text(json.dumps(INBOX), encoding="utf-8")
    result = shop(paths)
    assert result["log"] is None and not (tmp_path / "log.md").exists()
    assert (tmp_path / "wishlist" / f"{SLUG}.shopping.md").is_file()


def test_each_run_regenerates_the_file_and_leaves_no_temp_file(tmp_path):
    paths = write_case(tmp_path)
    shop(paths)
    target = tmp_path / "wishlist" / f"{SLUG}.shopping.md"
    target.write_text("my own edit\n", encoding="utf-8")
    fewer = dict(PLAN, items=PLAN["items"][:2])
    write_case(tmp_path, plan=fewer, day="2026-10-21")
    assert shop(paths)["missing"] == 1
    text = target.read_text(encoding="utf-8")
    assert "my own edit" not in text and "- 1 track(s)" in text
    assert [p.name for p in target.parent.iterdir()] == [target.name]


def test_nothing_missing_says_so(tmp_path):
    paths = write_case(tmp_path, plan=dict(PLAN, items=PLAN["items"][:1]))
    assert shop(paths)["missing"] == 0
    text = (tmp_path / "wishlist" / f"{SLUG}.shopping.md").read_text(encoding="utf-8")
    assert "Nothing to buy" in text and "## Tracks" not in text


def test_no_plan_is_a_clear_error_and_writes_nothing(tmp_path):
    with pytest.raises(shopping.ShoppingError, match="dj plan"):
        shop(REAL_PATHS(tmp_path, library=True))
    assert not (tmp_path / "wishlist").exists()


# -- CLI and MCP ---------------------------------------------------------------------------


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="windows", today=TODAY)
    (root / "links.yaml").write_text(f"- spotify: warmup_inbox\n  crate: {CRATE}\n", encoding="utf-8")
    monkeypatch.setenv("DJ_LIBRARY", str(root))
    return root


def test_cli_shop_json_in_the_library(library, no_sockets):
    write_case(library.resolve())
    result = runner.invoke(cli.app, ["wishlist", "shop", "warmup_inbox", "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert list(out)[:2] == ["missing", "labels"]  # counts first
    assert out["missing"] == 3 and out["file"] == f"wishlist/{SLUG}.shopping.md"
    assert "wishlist shop" in (library / "log.md").read_text(encoding="utf-8")


def test_cli_shop_text_and_errors(library, tmp_path, monkeypatch):
    result = runner.invoke(cli.app, ["wishlist", "shop", "warmup_inbox"])
    assert result.exit_code == cli.EXIT_ERROR and "dj plan" in result.output
    result = runner.invoke(cli.app, ["wishlist", "shop", "unknown_link"])
    assert result.exit_code == cli.EXIT_ERROR and "Known: warmup_inbox" in result.output
    write_case(library.resolve())
    result = runner.invoke(cli.app, ["wishlist", "shop", CRATE])
    assert result.exit_code == 0 and "3 missing" in result.output and "Harbour Light Records (1)" in result.output


def test_cli_shop_falls_back_to_the_repo_without_library_links(tmp_path, monkeypatch):
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path / "no-library"))
    repo = tmp_path / "repo"
    monkeypatch.setattr(intake, "Paths", functools.partial(REAL_PATHS, repo))
    (repo / "plans").mkdir(parents=True)
    (repo / "links.yaml").write_text(f"- spotify: warmup_inbox\n  crate: {CRATE}\n", encoding="utf-8")
    (repo / "plans" / f"2026-10-20-{SLUG}.plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
    result = runner.invoke(cli.app, ["wishlist", "shop", "warmup_inbox", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["log"] is None
    assert (repo / "wishlist" / f"{SLUG}.shopping.md").is_file()


def test_mcp_tool_runs_the_fixed_command_and_is_a_non_destructive_writer(monkeypatch):
    seen = []
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **k: seen.append(cmd) or
                        SimpleNamespace(returncode=0, stdout="{}", stderr=""))
    m.dj_wishlist_shop("--apply")
    assert seen[-1][3:] == ["wishlist", "shop", "--json", "--", "--apply"]
    tool = {t.name: t for t in asyncio.run(m.server.list_tools())}["dj_wishlist_shop"]
    assert tool.annotations.read_only_hint is False and tool.annotations.destructive_hint is False
    assert list(tool.input_schema["properties"]) == ["link"]
