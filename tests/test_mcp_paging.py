"""NFR-03: MCP tool results stay under the tool-result limit: counts first, items paginated.

`mcp_server.paginate` keeps every count / summary key (`counts` first), cuts each list that grows
with the library to one page, and says per list {page, pages, page_size, total, from, to}. A page
holds at most page_size items and stops early at PAGE_BUDGET characters, so a page of big items
stays well under 20 000 characters. Every preview / read tool with such a list takes page and
page_size; the preview_id is on every page, and pages 2+ are cut from page 1's run (mcp_server.RUNS).
dj_status pages its nested tree as one row per node, so one big base folder cannot outgrow a page.
Each list's share of the budget follows its need. Tools whose call writes cannot be called again
for page 2: their lists come back as the first page, and `rest_in` names the file with all of it.
"""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace as NS

import pytest
from test_cli import sessions  # noqa: F401  (fixture used by `env`)
from test_tidy_cli import env  # noqa: F401  (fixture)
from test_write_gate import (  # noqa: F401  (rb, spot, tidy_apply, tidy_undo, in_process: fixtures)
    MCP_PAIRS,
    in_process,
    mcp_pair,
    rb,
    spot,
    tidy_apply,
    tidy_undo,
)

from dj import mcp_server as m

PID = "0123456789ab"
LIMIT = 20_000  # "well under" this many characters


def match_item(n: int) -> dict:
    """The size of a real `dj match` AMBIGUOUS item: three local candidates with long paths."""

    def candidate(k: int) -> dict:
        return {"rb_content_id": str(10_000 + 3 * n + k), "title": f"Track {n} (Extended Mix)",
                "artist": "Some Artist feat. Another Artist", "duration_s": 400 + k, "bitrate": 320,
                "path": f"D:/Music/House/Some Artist/Some Album (Deluxe)/{n:04d} - Some Artist - Track {n} "
                        "(Extended Mix).mp3",
                "in_crate": False, "score": 88, "isrc_match": False, "duration_diff_s": 3, "version_ok": False}  # fmt: skip

    return {"spotify_uri": f"spotify:track:{n:022d}", "spotify": f"Some Artist - Track {n}", "duration_s": 401,
            "url": f"https://open.spotify.com/track/{n:022d}", "status": "AMBIGUOUS", "how": "",
            "reasons": ["version differs"], "pick": None, "candidates": [candidate(k) for k in range(3)]}  # fmt: skip


def cli_result(keys, items, **extra) -> dict:
    """A CLI --json result: the lists first (as some commands print them), counts after."""
    return {**{k: list(items) for k in keys}, "preview_id": PID, "counts": {"MATCH": len(items)}, **extra}


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """The CLI answers with `cli.result`; `cli.calls` are the command lines. Tool files exist."""
    state = NS(result={}, calls=[])

    def fake_run(cmd, **kwargs):
        state.calls.append(cmd)
        return NS(returncode=0, stdout=json.dumps(state.result), stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)
    for name in ("bases.yaml", "p.plan.json", "set.txt"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "lib").mkdir()
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path / "lib"))
    return state


# -- paginate ------------------------------------------------------------------------------------


def test_2000_real_sized_items_give_a_page_well_under_the_limit_counts_first(cli):
    items = [match_item(n) for n in range(2000)]
    cli.result = cli_result(("items",), items, spotify="inbox", crate="house_base/0_INBOX")
    text = m.dj_match("inbox")
    assert len(text) < LIMIT * 0.8, len(text)
    result = json.loads(text)["result"]
    assert list(result)[0] == "counts" and result["preview_id"] == PID
    assert list(result)[-1] == "items" and result["spotify"] == "inbox"
    paging = result["paging"]["items"]
    assert paging["total"] == 2000 and paging["page"] == 1 and paging["from"] == 1
    assert result["items"] == items[: paging["to"]] and 1 <= paging["to"] <= m.PAGE_SIZE


def test_page_arithmetic_last_page_and_beyond_the_end(cli):
    items = [{"n": n} for n in range(2000)]
    cli.result = cli_result(("items",), items)
    first = json.loads(m.dj_match("l", page=1, page_size=50))["result"]
    assert first["paging"]["items"] == {"page": 1, "pages": 40, "page_size": 50, "total": 2000, "from": 1, "to": 50}
    assert first["items"] == items[:50]
    last = json.loads(m.dj_match("l", page=40, page_size=50))["result"]
    assert last["paging"]["items"] == {"page": 40, "pages": 40, "page_size": 50, "total": 2000, "from": 1951,
                                       "to": 2000}  # fmt: skip
    assert last["items"] == items[1950:]
    beyond = json.loads(m.dj_match("l", page=41, page_size=50))["result"]
    assert beyond["items"] == [] and beyond["counts"] == {"MATCH": 2000} and beyond["preview_id"] == PID
    assert beyond["paging"]["items"] == {"page": 41, "pages": 40, "page_size": 50, "total": 2000, "from": None,
                                         "to": None}  # fmt: skip
    odd = json.loads(m.dj_match("l", page=3, page_size=7))["result"]
    assert odd["items"] == items[14:21] and odd["paging"]["items"]["pages"] == 286


def test_pages_cover_every_item_once_in_order_whatever_the_sizes():
    items = [{"n": n, "pad": "x" * (n * 37 % 3000)} for n in range(300)]
    result = {"counts": {"n": 300}, "items": items}
    pages = m.paginate(result, ("items",), 1, 50)["paging"]["items"]["pages"]
    seen = []
    for page in range(1, pages + 1):
        cut = m.paginate(result, ("items",), page, 50)
        assert len(json.dumps(cut["items"], separators=(",", ":"))) <= m.PAGE_BUDGET or len(cut["items"]) == 1
        seen += cut["items"]
    assert seen == items


def test_an_item_bigger_than_the_budget_gets_a_page_of_its_own():
    items = [{"n": 0}, {"n": 1, "pad": "x" * (m.PAGE_BUDGET + 10)}, {"n": 2}]
    assert m.page_bounds(items, 50) == [(0, 1), (1, 2), (2, 3)]
    assert m.page_bounds([], 50) == []


def test_a_result_without_the_lists_is_left_as_it_is():
    assert m.paginate({"tracks": 24}, ("tree", "links")) == {"tracks": 24}
    assert m.paginate({"tree": "not a list"}, ("tree",)) == {"tree": "not a list"}


def test_two_lists_are_paged_each_and_share_the_budget():
    result = {"tracks": 5, "links": [{"l": n} for n in range(3)], "tree": [{"t": n} for n in range(120)]}
    page = m.paginate(result, ("tree", "links"), 2, 50)
    assert page["tracks"] == 5 and page["links"] == [] and page["tree"] == result["tree"][50:100]
    assert page["paging"]["links"]["pages"] == 1 and page["paging"]["tree"]["pages"] == 3


@pytest.mark.parametrize("bad", [0, -1, m.PAGE_MAX + 1, True, "2", 1.5, None])
def test_a_bad_page_is_refused_before_anything_runs(cli, bad):
    answer = json.loads(m.dj_match("l", page=bad))
    assert answer["ok"] is False and "page must be a whole number" in answer["error"]
    assert cli.calls == []


@pytest.mark.parametrize("bad", [0, m.PAGE_SIZE_MAX + 1, False, "50"])
def test_a_bad_page_size_is_refused_before_anything_runs(cli, bad):
    answer = json.loads(m.dj_status(page_size=bad))
    assert answer["ok"] is False and "page_size must be a whole number" in answer["error"]
    assert cli.calls == []


# -- every listed tool is wired ------------------------------------------------------------------


PAGED = {  # tool -> (call, the CLI's list keys)
    "dj_status": (lambda **kw: m.dj_status(**kw), ("tree", "links")),
    "dj_tree_preview": (lambda **kw: m.dj_tree_preview("bases.yaml", **kw), ("actions",)),
    "dj_library_inspect": (lambda **kw: m.dj_library_inspect(**kw), ("tree",)),
    "dj_match": (lambda **kw: m.dj_match("inbox", **kw), ("items",)),
    "dj_apply_preview": (lambda **kw: m.dj_apply_preview("p.plan.json", **kw), ("adds",)),
    "dj_copy_preview": (lambda **kw: m.dj_copy_preview("a", "b", **kw), ("rows",)),
    "dj_push_preview": (lambda **kw: m.dj_push_preview("p", **kw), ("items",)),
    "dj_build_preview": (lambda **kw: m.dj_build_preview("set.txt", **kw), ("items",)),
    "dj_tidy_audit": (lambda **kw: m.dj_tidy_audit(all_tracks=True, brief=False, **kw), ("items", "duplicates")),
    "dj_tidy_dupes": (lambda **kw: m.dj_tidy_dupes(all_tracks=True, **kw), ("groups",)),
    "dj_tidy_apply_preview": (lambda **kw: m.dj_tidy_apply_preview("p.plan.json", **kw), ("items",)),
    "dj_tidy_undo_preview": (lambda **kw: m.dj_tidy_undo_preview("p.plan.json", **kw), ("items",)),
    "dj_structure_preview": (lambda **kw: m.dj_structure_preview("lanes", **kw), ("rows",)),
    "dj_crate_preview": (lambda **kw: m.dj_crate_preview("saturday", **kw), ("picks", "spares")),
}


def test_the_paged_tools_here_are_all_the_tools_with_a_page_argument():
    tools = {t.name: t for t in asyncio.run(m.server.list_tools())}
    with_page = {name for name, t in tools.items() if "page" in t.input_schema["properties"]}
    assert with_page == set(PAGED)
    for name in PAGED:
        props = tools[name].input_schema["properties"]
        assert (props["page"]["default"], props["page_size"]["default"]) == (1, 50), name
        assert "page" not in tools[name].input_schema.get("required", []), name
        assert "paging" in tools[name].description or "pages" in tools[name].description, name


def cli_lists(tool: str, keys, n: int, big: bool = True) -> tuple[dict, dict]:
    """The CLI's lists for `tool`, and what its pages hold: dj_status's nested `tree` comes back
    as one row per node (mcp_server.status_rows); every other list as the CLI printed it."""
    make = match_item if big else (lambda k: {"n": k})
    lists = {key: [make(k) for k in range(n)] for key in keys}
    if tool == "dj_status":
        lists["tree"] = [{"kind": "playlist", "name": f"Some Base/Playlist {k}", "tracks": k} for k in range(n)]
    return lists, lists | ({"tree": m.status_rows(lists["tree"])} if tool == "dj_status" else {})


@pytest.mark.parametrize("tool", sorted(PAGED))
def test_every_listed_tool_pages_its_lists_and_keeps_the_preview_id(cli, tool):
    call, keys = PAGED[tool]
    lists, shown = cli_lists(tool, keys, 2000)
    cli.result = {**lists, "preview_id": PID, "counts": {"MATCH": 2000}}
    text = call()
    assert len(text) < LIMIT, (tool, len(text))
    result = json.loads(text)["result"]
    assert list(result)[0] == "counts" and result["preview_id"] == PID
    for key in keys:
        assert result["paging"][key]["total"] == 2000 and result["paging"][key]["page"] == 1
        assert 1 <= len(result[key]) <= m.PAGE_SIZE and result[key] == shown[key][: len(result[key])]
    lists, shown = cli_lists(tool, keys, 2000, big=False)
    cli.result = {**lists, "preview_id": PID, "counts": {"MATCH": 2000}}
    first = json.loads(call(page_size=10))["result"]  # page 1 runs the command again
    result = json.loads(call(page=2, page_size=10))["result"]  # page 2 is cut from that run
    for key in keys:
        assert result["paging"][key] == {"page": 2, "pages": 200, "page_size": 10, "total": 2000, "from": 11,
                                         "to": 20}  # fmt: skip
        assert first[key] == shown[key][:10] and result[key] == shown[key][10:20]
    assert result["preview_id"] == PID and len(cli.calls) == 2
    answer = json.loads(call(page=0))
    assert answer["ok"] is False and len(cli.calls) == 2  # refused before running


# -- pages 2+ come from page 1's run -------------------------------------------------------------


def test_page_2_is_cut_from_page_1s_run_and_page_1_runs_again(cli):
    cli.result = cli_result(("items",), [{"n": n} for n in range(100)])
    first = json.loads(m.dj_match("l", page_size=10))
    cli.result = cli_result(("items",), [{"m": n} for n in range(100)], preview_id="fedcba987654")
    second = json.loads(m.dj_match("l", page=2, page_size=10))
    assert len(cli.calls) == 1 and second["run_at"] == first["run_at"]  # no second Spotify search or scan
    assert second["result"]["items"] == [{"n": n} for n in range(10, 20)] and second["result"]["preview_id"] == PID
    again = json.loads(m.dj_match("l", page_size=10))  # page 1: a fresh run, its own preview id
    assert len(cli.calls) == 2 and again["result"]["preview_id"] == "fedcba987654"
    json.loads(m.dj_match("other", page=2))  # another command line: its own run
    assert len(cli.calls) == 3


def test_a_kept_run_expires_and_a_failed_run_is_not_kept(cli, monkeypatch):
    cli.result = cli_result(("items",), [{"n": n} for n in range(100)])
    m.dj_match("l")
    monkeypatch.setattr(m, "RUN_KEEP_S", 0)
    m.dj_match("l", page=2)
    assert len(cli.calls) == 2  # too old: ran again
    monkeypatch.setattr(m, "RUN_KEEP_S", 600)
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **kw: cli.calls.append(cmd) or NS(
        returncode=2, stdout="", stderr="STOP rekordbox is running"))  # fmt: skip
    m.dj_status()
    m.dj_status(page=2)
    assert len(cli.calls) == 4


def test_at_most_run_keep_runs_are_kept(cli):
    cli.result = cli_result(("items",), [{"n": 1}])
    for n in range(m.RUN_KEEP + 1):
        m.dj_match(f"link{n}")
    m.dj_match(f"link{m.RUN_KEEP}", page=2)  # the newest is kept
    assert len(cli.calls) == m.RUN_KEEP + 1
    m.dj_match("link0", page=2)  # the oldest went first
    assert len(cli.calls) == m.RUN_KEEP + 2


def test_a_tool_whose_call_writes_is_never_kept(cli):
    cli.result = {"items": [{"n": 1}], "plan": "plans/x.plan.json", "counts": {}}
    m.dj_tidy_plan(all_tracks=True)
    m.dj_tidy_plan(all_tracks=True)
    assert len(cli.calls) == 2 and len(m.RUNS._runs) == 0


def test_the_descriptions_say_later_pages_come_from_page_1s_run():
    tools = {t.name: " ".join(t.description.split()) for t in asyncio.run(m.server.list_tools())}
    for name in ("dj_push_preview", "dj_build_preview"):
        assert "pages 2+ are cut from that run" in tools[name] and "a different one means" in tools[name], name
    assert "pages 2+ are cut from that scan" in tools["dj_tidy_audit"]
    text = " ".join(m.server.instructions.split())
    assert "Pages 2+ are cut from page 1's run" in text and "a different preview_id means the plan changed" in text


# -- dj_status: the nested tree as rows ----------------------------------------------------------


SMART_XML = ('<NODE Id="123456789" LogicalOperator="1" AutomaticUpdate="0"><CONDITION PropertyName="genre" '
             'Operator="1" ValueUnit="" ValueLeft="Deep House" ValueRight=""/><CONDITION PropertyName="bpm" '
             'Operator="5" ValueUnit="" ValueLeft="118" ValueRight="124"/></NODE>') * 2


def big_base(subfolders: int = 12, playlists: int = 60, smart: int = 20) -> dict:
    """One top-level base folder that holds most of the library, as `dj status --json` nests it."""
    def folder(i: int) -> dict:
        kids = [{"kind": "playlist", "name": f"{i:02d}.{k:02d} some long playlist name for the crate", "tracks": k}
                for k in range(playlists)]
        kids += [{"kind": "smart", "name": f"{i:02d} smart {k}", "smart_xml": SMART_XML} for k in range(smart)]
        return {"kind": "folder", "name": f"{i:02d}_sub folder of the base", "children": kids}

    return {"kind": "folder", "name": "house_base", "children": [folder(i) for i in range(subfolders)]}


def status_result() -> dict:
    tree = [big_base(), {"kind": "playlist", "name": "loose", "tracks": 3}, {"kind": "folder", "name": "empty",
                                                                             "children": []}]  # fmt: skip
    links = [{"spotify": "inbox", "crate": "house_base/0_INBOX", "counts": {"PROPOSE": 2}, "last_pull": None,
              "last_apply": None}]  # fmt: skip
    return {"master_db": "C:/x/master.db", "rekordbox": "7.2.2", "pyrekordbox": "0.4.1", "running": False,
            "tracks": 48211, "links": links, "tree": tree}  # fmt: skip


def all_pages(call, key: str, **kw) -> tuple[list, list[int]]:
    """Every page of `key`, and the size of each result."""
    rows, sizes, page = [], [], 1
    while True:
        text = call(page=page, **kw)
        result = json.loads(text)["result"]
        sizes.append(len(text))
        rows += result[key]
        if page >= result["paging"][key]["pages"]:
            return rows, sizes
        page += 1


@pytest.mark.parametrize("page_size", [7, 50, m.PAGE_SIZE_MAX])
@pytest.mark.parametrize("smart_xml", [False, True])
def test_status_with_one_big_nested_folder_stays_under_the_limit_on_every_page(cli, page_size, smart_xml):
    cli.result = status_result()
    assert len(json.dumps(cli.result["tree"][0])) > 3 * LIMIT  # one top-level node, far over the limit
    rows, sizes = all_pages(lambda **kw: m.dj_status(**kw), "tree", page_size=page_size, smart_xml=smart_xml)
    assert max(sizes) < LIMIT, max(sizes)
    assert rows == m.status_rows(cli.result["tree"], smart_xml) and len(rows) == 1 + 12 + 12 * 80 + 2
    assert rows[0] == {"path": "house_base", "kind": "folder", "children": 12}
    assert rows[2] == {"path": "house_base/00_sub folder of the base/00.00 some long playlist name for the crate",
                       "kind": "playlist", "tracks": 0}  # fmt: skip
    assert all(("smart_xml" in r) is (smart_xml and r["kind"] == "smart") for r in rows)
    assert len(cli.calls) == 1  # every later page came from page 1's run


def test_status_counts_come_first_and_keep_the_track_count(cli):
    cli.result = status_result()
    result = json.loads(m.dj_status())["result"]
    assert list(result)[0] == "counts" and result["tracks"] == 48211
    assert result["counts"] == {"tracks": 48211, "folders": 14, "playlists": 721, "smart": 240, "links": 1}
    assert result["paging"]["links"]["total"] == 1 and result["links"] == cli.result["links"]
    assert result["paging"]["tree"]["total"] == 1 + 12 + 12 * 80 + 2


def test_status_rows_from_the_real_cli_tree(monkeypatch):
    from dj import cli as dj_cli

    rows = [NS(ID="1", Name="house_base", Attribute=1, ParentID="root", Seq=1, Songs=[], SmartList=None),
            NS(ID="2", Name="0_INBOX", Attribute=0, ParentID="1", Seq=1, Songs=[1, 2], SmartList=None),
            NS(ID="3", Name="deep", Attribute=4, ParentID="1", Seq=2, Songs=[], SmartList="<NODE/>")]  # fmt: skip
    tree = {"root": [rows[0]], "1": rows[1:]}
    monkeypatch.setattr(dj_cli, "children_of", lambda _db, parent: tree.get(parent, []))
    nested = dj_cli.tree_data(NS())
    assert m.status_rows(nested) == [
        {"path": "house_base", "kind": "folder", "children": 2},
        {"path": "house_base/0_INBOX", "kind": "playlist", "tracks": 2},
        {"path": "house_base/deep", "kind": "smart"},
    ]
    assert m.status_rows(nested, smart_xml=True)[2]["smart_xml"] == "<NODE/>"


# -- the budget is shared by need ----------------------------------------------------------------


def test_a_short_list_takes_what_it_needs_and_the_long_one_the_rest():
    links = [{"spotify": "inbox", "crate": "house_base/0_INBOX"}]
    tree = [{"path": f"house_base/{n:04d} a long playlist name that takes room", "kind": "playlist", "tracks": n}
            for n in range(2000)]  # fmt: skip
    result = {"links": links, "tree": tree}
    share = m.shares(result, ["tree", "links"], m.PAGE_SIZE_MAX)
    assert share["links"] == m._page_need(links, m.PAGE_SIZE_MAX) and share["tree"] == m.PAGE_BUDGET - share["links"]
    page = m.paginate(result, ("tree", "links"), 1, m.PAGE_SIZE_MAX)
    shown = len(json.dumps(page["tree"], separators=(",", ":")))
    assert shown > m.PAGE_BUDGET * 0.9 and page["links"] == links
    both_long = m.shares({"a": tree, "b": tree}, ["a", "b"], m.PAGE_SIZE_MAX)
    assert both_long == {"a": m.PAGE_BUDGET // 2, "b": m.PAGE_BUDGET // 2}


# -- lists the CLI caps, lists next to the matches, text results ---------------------------------


def test_inspect_paging_counts_the_top_nodes_the_sample_leaves_out(cli):
    cli.result = {"counts": {"tracks": 9}, "tree": [{"name": f"n{k}", "children": []} for k in range(30)],
                  "tree_more": 170}  # fmt: skip
    result = json.loads(m.dj_library_inspect(page_size=20))["result"]
    assert result["paging"]["tree"] == {"page": 1, "pages": 2, "page_size": 20, "total": 200, "from": 1, "to": 20,
                                        "listed": 30}  # fmt: skip
    assert result["tree_more"] == 170


def test_structure_preview_asks_for_every_row_and_counts_any_the_cli_left_out(cli):
    cli.result = {"counts": {"create": 3}, "preview_id": PID, "rows": [{"op": "CREATE"}] * 60, "rows_more": 140}
    result = json.loads(m.dj_structure_preview("lanes"))["result"]
    assert cli.calls[-1][cli.calls[-1].index("--rows-limit") + 1] == "0"
    assert result["paging"]["rows"]["total"] == 200 and result["paging"]["rows"]["listed"] == 60


def test_build_pages_the_skipped_lines_too(cli):
    skipped = [f"[{n:03d}:00] Label Records presents - a long line without a dash separator, number {n}"
               for n in range(400)]  # fmt: skip
    cli.result = {"counts": {"MATCH": 400}, "preview_id": PID, "skipped_lines": skipped,
                  "items": [match_item(n) for n in range(400)]}  # fmt: skip
    for size in (1, 50, m.PAGE_SIZE_MAX):
        text = m.dj_build_preview("set.txt", page_size=size)
        assert len(text) < LIMIT, (size, len(text))
        paging = json.loads(text)["result"]["paging"]
        assert paging["skipped_lines"]["total"] == 400 and paging["items"]["total"] == 400
    cli.result |= {"report": "reports/x.report.json", "log": "line"}
    text = m.dj_build_apply("set.txt", preview_id=PID)
    result = json.loads(text)["result"]
    assert len(text) < LIMIT and result["paging"]["skipped_lines"]["rest_in"] == "reports/x.report.json"


def tree_apply_text(nodes: int) -> str:
    actions = [f"CREATE playlist  house_base / {n:04d} a playlist with a fairly long name" for n in range(nodes)]
    tree = [f"  [playlist] {n:04d} a playlist with a fairly long name  (0 tracks)" for n in range(nodes)]
    return "\n".join([*actions, "", f"{nodes} CREATE, 0 HOLD, 0 SKIP, 0 CONFLICT",
                      f"APPLIED. Created {nodes} node(s) in one commit. Backup in backups/.",
                      f"log.md: 2026-10-20 14:03 tree -> {nodes} playlists; bases.yaml", "", "final tree:",
                      "[folder] house_base", *tree])  # fmt: skip


def test_tree_apply_keeps_the_summary_of_a_long_text_and_leaves_the_final_tree_out(cli, monkeypatch):
    text = tree_apply_text(3000)
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **kw: NS(returncode=0, stdout=text, stderr=""))
    answer = m.dj_tree_apply(preview_id=PID, file="bases.yaml", power_mode=True)
    assert len(answer) < LIMIT, len(answer)
    output = json.loads(answer)["output"]
    assert output.startswith("CREATE playlist  house_base / 0000 a playlist")
    for line in ("3000 CREATE, 0 HOLD, 0 SKIP, 0 CONFLICT", "APPLIED. Created 3000 node(s) in one commit.",
                 "log.md: 2026-10-20 14:03 tree -> 3000 playlists; bases.yaml",
                 "final tree: 3001 line(s) left out; dj_status pages the tree."):  # fmt: skip
        assert line in output, line
    assert re.search(r"\.\.\. \d+ more node line\(s\), as dj_tree_preview showed them", output)
    assert "[playlist]" not in output
    assert m.short_tree_output(tree_apply_text(3)) == tree_apply_text(3)


WRITTEN = {  # tool -> (call, list key, the key naming the file with the full list)
    "dj_apply_write": (lambda: m.dj_apply_write("p.plan.json", preview_id=PID, power_mode=True), "adds", "report"),
    "dj_copy_apply": (lambda: m.dj_copy_apply("a", "b", preview_id=PID, power_mode=True), "rows", "report"),
    "dj_push_apply": (lambda: m.dj_push_apply("p", preview_id=PID), "items", "report"),
    "dj_build_apply": (lambda: m.dj_build_apply("set.txt", preview_id=PID), "items", "report"),
    "dj_tidy_apply": (lambda: m.dj_tidy_apply("p.plan.json", preview_id=PID), "items", "report"),
    "dj_tidy_undo": (lambda: m.dj_tidy_undo("p.plan.json", preview_id=PID), "items", "undo"),
    "dj_tidy_plan": (lambda: m.dj_tidy_plan(all_tracks=True), "items", "plan"),
}


@pytest.mark.parametrize("tool", sorted(WRITTEN))
def test_a_tool_whose_call_writes_returns_the_first_page_and_names_the_full_file(cli, tool):
    call, key, rest = WRITTEN[tool]
    items = [match_item(n) for n in range(2000)]
    cli.result = {key: items, rest: "reports/2026-10-20-x.json", "counts": {"added": 2000}, "log": "line"}
    text = call()
    assert len(text) < LIMIT, (tool, len(text))
    result = json.loads(text)["result"]
    assert list(result)[0] == "counts" and result["log"] == "line"
    assert result["paging"][key]["page"] == 1 and result["paging"][key]["total"] == 2000
    assert result["paging"][key]["rest_in"] == "reports/2026-10-20-x.json"
    assert result[key] == items[: len(result[key])] and len(cli.calls) == 1


def test_a_short_written_list_has_no_rest_in(cli):
    cli.result = {"items": [{"n": 1}], "report": "r.json", "counts": {}}
    result = json.loads(m.dj_tidy_apply("p.plan.json", preview_id=PID))["result"]
    assert result["paging"]["items"]["pages"] == 1 and "rest_in" not in result["paging"]["items"]


def test_tree_apply_prints_text_and_is_left_as_it_is(cli, monkeypatch):
    text = "APPLIED. Created 2 node(s) in one commit. Backup in backups/."
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **kw: NS(returncode=0, stdout=text, stderr=""))
    answer = json.loads(m.dj_tree_apply(preview_id=PID, file="bases.yaml", power_mode=True))
    assert answer == {"ok": True, "exit_code": 0, "output": text}


# -- the real CLI names the list keys the tools page ---------------------------------------------


PAIR_KEYS = {"tree": "actions", "apply": "adds", "copy": "rows", "push": "items", "push_named": "items",
             "build": "items", "build_named": "items", "tidy_apply": "items", "tidy_apply_strict": "items",
             "tidy_undo": "items"}  # fmt: skip


@pytest.mark.parametrize("name", MCP_PAIRS)
def test_the_preview_tools_page_the_lists_the_real_cli_prints(name, request, tmp_path, in_process):  # noqa: F811
    pair = mcp_pair(name, request, tmp_path, in_process)
    answer = json.loads(pair.preview())
    assert answer["ok"] is True, answer
    result, key = answer["result"], PAIR_KEYS[name]
    assert isinstance(result[key], list) and result[key], result
    assert result["paging"][key]["total"] == len(result[key]) and result["preview_id"]


def test_the_tidy_read_tools_page_the_lists_the_real_cli_prints(env, monkeypatch):  # noqa: F811
    from test_tidy_cli import run
    from tidy_fixtures import make_audio

    make_audio(env.root / "Huerta - Low Five.mp3")
    make_audio(env.root / "Huerta - Low Five (copy).mp3")
    audit = json.loads(run("tidy", "audit", "--folder", env.root, "--config", env.yaml, "--json").output)
    dupes = json.loads(run("tidy", "dupes", "--folder", env.root, "--config", env.yaml, "--json").output)
    assert isinstance(audit["items"], list) and isinstance(audit["duplicates"], list)
    assert isinstance(dupes["groups"], list)
    assert m.paginate(audit, ("items", "duplicates"))["paging"]["items"]["total"] == 2
    assert "groups" in m.paginate(dupes, ("groups",))["paging"]


def test_inspect_pages_the_tree_the_real_cli_prints(tmp_path):
    import xml_fixtures as fx
    from typer.testing import CliRunner

    from dj import cli

    xml = fx.write_xml(tmp_path / "collection.xml")
    data = json.loads(CliRunner().invoke(cli.app, ["library", "inspect", str(xml), "--json"]).stdout)
    page = m.paginate(data, ("tree",), 1, 1)
    assert page["paging"]["tree"]["total"] == len(data["tree"]) and len(page["tree"]) == 1
    assert list(page)[0] == "counts"
