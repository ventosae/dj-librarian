"""dj.build_structure, `dj library build`, the MCP tools and the skill script (R-501..R-505).

The dj-library folder, `structure/current-tree.yaml` and `structure/proposals.yaml` are built
here from the synthetic library in tests/xml_fixtures.py (private helpers below; the real
generators are dj-structure and dj-report). Files only in tmp_path.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml
from typer.testing import CliRunner

from dj import build_structure as bs
from dj import cli, libfolder, treeschema
from dj import mcp_server as m
from dj.gate import Gate
from dj.libfolder import LibraryFolder
from dj.model import PlaylistNode
from dj.readers.xml import read_xml

pytestmark = pytest.mark.usefixtures("export_reads")  # the library is read from the export fixture

DAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 14, 5)
REPO = Path(__file__).resolve().parents[1]
runner = CliRunner()

LANES_TREE = [
    {"folder": "Lanes", "children": [
        {"playlist": "96-112 funk disco", "from": ["funk & disco 78-92", "Gigs/Gig 2025-11 Rooftop"]},
        {"playlist": "118-124 house", "from": ["House/1.1_warm_up", "House/1.2_peak"]},
        {"playlist": "126-132 techno", "from": ["Gigs/Gig 2025-03 Warehouse"]},
        {"smart": "all techno", "rules": [{"genre_contains": "Techno"}]},
    ]},
    {"folder": "House", "children": [
        {"playlist": "1.1_warm_up"},
        {"playlist": "1.3_closing", "from": ["unsorted dump"]},
        {"folder": "Deep", "children": [{"playlist": "deep_rollers"}]},
    ]},
]  # fmt: skip

PROPOSALS = [
    {
        "slug": "lanes", "name": "Lanes", "family": "facets",
        "principle": "One folder per tempo lane.", "cost_minutes": 20,
        "trigger": "Build me the Lanes structure",
        "lands": [{"from": "House/1.1_warm_up", "to": "Lanes/118-124 house"}],
        "tree": LANES_TREE,
    },
    {
        "slug": "gig-first", "name": "Gig First", "family": "gig-first",
        "principle": "Gigs on top.", "cost_minutes": 5, "trigger": "Build me the Gig First structure",
        "lands": [], "tree": [{"folder": "Gigs", "children": [{"playlist": "Gig 2025-03 Warehouse"}]}],
    },
    {
        "slug": "clash", "name": "Clash", "family": "bases", "principle": "A name taken by a folder.",
        "cost_minutes": 5, "trigger": "Build me the Clash structure", "lands": [],
        "tree": [{"playlist": "House"}, {"playlist": "brand new"}],
    },
    {
        "slug": "broken-from", "name": "Broken From", "family": "bases", "principle": "Bad source.",
        "cost_minutes": 5, "trigger": "Build me the Broken From structure", "lands": [],
        "tree": [{"folder": "New", "children": [{"playlist": "x", "from": ["Nope/missing"]}]}],
    },
]  # fmt: skip

LANES_ROWS = [
    ("CREATE", "Lanes"), ("CREATE", "Lanes/96-112 funk disco"), ("CREATE", "Lanes/118-124 house"),
    ("CREATE", "Lanes/126-132 techno"), ("MANUAL", "Lanes/all techno"), ("SKIP", "House"),
    ("SKIP", "House/1.1_warm_up"), ("CREATE", "House/1.3_closing"), ("SKIP", "House/Deep"),
    ("SKIP", "House/Deep/deep_rollers"),
]  # fmt: skip


# -- private fixture helpers (dj-structure / dj-report build these for real) ---------------


def _tree_from_library(nodes: tuple[PlaylistNode, ...]) -> list[dict]:
    out = []
    for n in nodes:
        if n.kind == "folder":
            out.append({"folder": n.name, "children": _tree_from_library(n.children)})
        elif n.kind == "smart":
            out.append({"smart": n.name, "rules_raw": "kept by rekordbox"})
        else:
            out.append({"playlist": n.name})
    return out


def _write_current_tree(root: Path, export: Path) -> None:
    """structure/current-tree.yaml from one export (what dj-structure does for real)."""
    lib = read_xml(export)
    current = treeschema.TreeDoc(treeschema.parse(_tree_from_library(lib.roots)).nodes,
                                 {"source": libfolder.relative(root, export), "generated": DAY.isoformat()})
    (root / "structure" / "current-tree.yaml").write_text(treeschema.dumps(current), encoding="utf-8")


def _make_library(tmp_path: Path, *, device: str = "windows", spec: dict | None = None) -> LibraryFolder:
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device=device, today=DAY)
    export = libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml", spec), today=DAY)
    _write_current_tree(root, export)
    (root / "structure" / "proposals.yaml").write_text(
        yaml.safe_dump(PROPOSALS, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return LibraryFolder(root)


@pytest.fixture
def folder(tmp_path):
    return _make_library(tmp_path)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _build_lines(folder: LibraryFolder) -> list[str]:
    return [line for line in folder.log.read_text(encoding="utf-8").splitlines() if " build " in line]


def _rows(preview) -> list[tuple[str, str]]:
    return [(r.op, "/".join(r.path)) for r in preview.rows]


# -- find_proposal -------------------------------------------------------------------------


@pytest.mark.parametrize("ref", [
    "lanes", "LANES", "Lanes", "Build me the Lanes structure", "build me the lanes structure.",
    '"Build me the Lanes structure"', "  Build   me the  Lanes structure ",
])  # fmt: skip
def test_find_proposal_by_slug_name_or_trigger(folder, ref):
    found = bs.find_proposal(folder, ref)
    assert (found.slug, found.name, found.source, found.exists) == ("lanes", "Lanes", "structure/proposals.yaml", False)
    assert found.cost_minutes == 20 and found.family == "facets"
    assert found.yaml_path == folder.proposals / "lanes.yaml"


def test_find_proposal_prefers_the_djs_yaml(folder):
    edited = treeschema.TreeDoc(treeschema.parse([{"playlist": "only mine"}]).nodes, {"name": "Lanes"})
    (folder.proposals / "lanes.yaml").write_text(treeschema.dumps(edited), encoding="utf-8")
    found = bs.find_proposal(folder, "Build me the Lanes structure")
    assert found.exists and found.source == "proposals/lanes.yaml"
    assert [n.name for n in found.doc.nodes] == ["only mine"]


def test_find_proposal_matches_the_name_of_a_hand_made_file(folder):
    mine = treeschema.TreeDoc(treeschema.parse([{"playlist": "x"}]).nodes, {"name": "My Tree"})
    (folder.proposals / "my-tree.yaml").write_text(treeschema.dumps(mine), encoding="utf-8")
    assert bs.find_proposal(folder, "Build me the my tree structure").slug == "my-tree"


def test_find_proposal_unknown_names_what_exists(folder):
    with pytest.raises(bs.BuildError, match="No proposal matches 'Disco Lanes'.*Known: .*Lanes"):
        bs.find_proposal(folder, "Disco Lanes")
    with pytest.raises(bs.BuildError, match="Name the proposal"):
        bs.find_proposal(folder, "  ")


@pytest.mark.parametrize("slug", ["../evil", "Lanes", "a b", "", None])
def test_find_proposal_refuses_an_unsafe_slug(folder, slug):
    bad = [dict(PROPOSALS[0], slug=slug)]
    (folder.structure / "proposals.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(bs.BuildError, match="slug"):
        bs.find_proposal(folder, "Lanes")


# -- preview (R-501) -----------------------------------------------------------------------


def test_preview_lists_create_skip_manual_per_node(folder):
    p = bs.preview(folder, "Build me the Lanes structure", today=DAY, now=NOW)
    assert _rows(p) == LANES_ROWS
    assert p.counts == {"create": 5, "skip": 4, "conflict": 0, "manual": 1, "tracks": 22}
    assert re.fullmatch(r"[0-9a-f]{12}", p.preview_id) and p.blocked is None
    assert p.yaml_created and p.yaml_path == folder.proposals / "lanes.yaml"
    assert p.export == "exports/2026-10-20-collection.xml"
    assert {"from": "House/1.1_warm_up", "to": "Lanes/118-124 house", "tracks": 4} in p.lands
    data = p.to_dict(folder)
    assert list(data)[0] == "counts" and data["written"] == "Nothing written yet."
    assert data["yaml"] == "proposals/lanes.yaml" and data["rows"][0] == {"op": "CREATE", "kind": "folder", "path": "Lanes"}


def test_preview_writes_only_the_proposal_yaml_and_the_preview_record(folder):
    before = _snapshot(folder.root)
    p = bs.preview(folder, "lanes", today=DAY, now=NOW)
    after = _snapshot(folder.root)
    assert set(after) - set(before) == {"proposals/lanes.yaml", f".cache/previews/{p.preview_id}.json"}
    assert {k: v for k, v in after.items() if k in before} == before  # log.md, library.yaml untouched
    assert [x.parent for x in folder.root.rglob("*.xml")] == [folder.exports]  # only the DJ's export
    doc = treeschema.load(folder.proposals / "lanes.yaml")
    assert doc.meta == {"name": "Lanes", "family": "facets", "principle": "One folder per tempo lane.",
                        "source": "structure/proposals.yaml", "generated": "2026-10-20"}  # fmt: skip
    assert doc.nodes == treeschema.parse(LANES_TREE).nodes


def test_preview_reads_the_djs_edits_and_never_overwrites_them(folder):
    bs.preview(folder, "lanes", today=DAY, now=NOW)
    path = folder.proposals / "lanes.yaml"
    edited = path.read_text(encoding="utf-8").replace("1.3_closing", "1.4_after_hours") + "# mine\n"
    path.write_text(edited, encoding="utf-8")
    again = bs.preview(folder, "lanes", today=DAY, now=NOW)
    assert ("CREATE", "House/1.4_after_hours") in _rows(again) and not again.yaml_created
    assert path.read_text(encoding="utf-8") == edited


def test_preview_needs_the_current_tree(folder):
    (folder.structure / "current-tree.yaml").unlink()
    with pytest.raises(bs.BuildError, match="run the analysis first"):
        bs.preview(folder, "lanes", today=DAY)
    assert not (folder.proposals / "lanes.yaml").exists() and not folder.cache.exists()


def test_preview_names_an_unknown_from_path(folder):
    with pytest.raises(bs.BuildError, match="Nope/missing"):
        bs.preview(folder, "broken-from", today=DAY)
    assert not folder.cache.exists()


def test_preview_id_is_stable_for_the_same_content(folder):
    a = bs.preview(folder, "lanes", today=DAY, now=NOW).preview_id
    assert bs.preview(folder, "Lanes", today=DAY, now=NOW).preview_id == a


def test_only_smart_nodes_left_is_nothing_to_create_and_says_they_are_made_by_hand(folder):
    smart = treeschema.TreeDoc(treeschema.parse([
        {"folder": "House", "children": [{"smart": "house 120+", "rules": [{"bpm_range": [120, 130]}]}]},
    ]).nodes, {"name": "Smart Only"})  # fmt: skip
    (folder.proposals / "smart-only.yaml").write_text(treeschema.dumps(smart), encoding="utf-8")
    p = bs.preview(folder, "smart-only", today=DAY, now=NOW)
    assert _rows(p) == [("SKIP", "House"), ("MANUAL", "House/house 120+")]
    assert p.preview_id is None and "1 smart playlist(s) are made by hand" in p.blocked


# -- apply refusals (R-1102) ---------------------------------------------------------------


# -- apply (R-502, R-503, R-505) -----------------------------------------------------------


# -- the current tree must match the export the tracks come from (hard rule 5) -------------


def _newer_export_with_lanes(folder: LibraryFolder, tmp_path: Path) -> Path:
    """The DJ made Lanes/118-124 house in rekordbox and exported again; current-tree is older."""
    spec = fx.spec_copy()
    spec["tree"].append({"kind": "folder", "name": "Lanes", "children": [
        {"kind": "playlist", "name": "118-124 house", "tracks": ["8", "9"]},
    ]})  # fmt: skip
    newer = libfolder.import_export(folder.root, fx.write_xml(tmp_path / "newer.xml", spec), today=DAY)
    assert libfolder.latest_export(folder.root) == newer
    return newer


def test_a_current_tree_with_a_node_the_export_lacks_blocks_the_build(folder):
    current = folder.structure / "current-tree.yaml"
    doc = treeschema.load(current)
    lanes = treeschema.TreeNode("folder", "Lanes")
    current.write_text(treeschema.dumps(treeschema.TreeDoc(doc.nodes + (lanes,), doc.meta)), encoding="utf-8")
    p = bs.preview(folder, "lanes", today=DAY, now=NOW)
    assert p.preview_id is None and "for Lanes it says SKIP, rekordbox says CREATE" in p.blocked


def test_smart_playlists_the_export_cannot_carry_are_not_a_stale_tree(folder):
    # A current tree read from master.db knows smart playlists; the XML export shows one as a
    # plain playlist or leaves it out. Neither blocks the build, and both stay SKIP.
    current = folder.structure / "current-tree.yaml"
    doc = treeschema.load(current)
    nodes = tuple(
        treeschema.TreeNode("smart", n.name, rules_raw="kept by rekordbox") if n.name == "funk & disco 78-92" else n
        for n in doc.nodes
    ) + (treeschema.TreeNode("smart", "All Techno", rules_raw="genre contains Techno"),)
    current.write_text(treeschema.dumps(treeschema.TreeDoc(nodes, doc.meta)), encoding="utf-8")
    mine = treeschema.TreeDoc(treeschema.parse([
        {"smart": "all techno", "rules": [{"genre_contains": "Techno"}]},
        {"smart": "Funk & Disco 78-92", "rules_raw": "genre is Funk"},
        {"playlist": "brand new", "from": ["unsorted dump"]},
    ]).nodes, {"name": "Smart Kept"})  # fmt: skip
    (folder.proposals / "smart-kept.yaml").write_text(treeschema.dumps(mine), encoding="utf-8")
    p = bs.preview(folder, "smart-kept", today=DAY, now=NOW)
    assert p.blocked is None and p.preview_id
    assert _rows(p) == [("SKIP", "All Techno"), ("SKIP", "funk & disco 78-92"), ("CREATE", "brand new")]


# -- structure/proposals.yaml problems -----------------------------------------------------


@pytest.mark.parametrize(("second", "match"), [
    ({"slug": "lanes", "name": "Other"}, "slug 'lanes' is also entry 1"),
    ({"slug": "other", "name": " LANES "}, "name 'LANES' is also entry 1"),
])  # fmt: skip
def test_two_proposals_with_one_slug_or_name_are_refused(folder, second, match):
    entries = [PROPOSALS[0], dict(PROPOSALS[1], **second)]
    (folder.structure / "proposals.yaml").write_text(yaml.safe_dump(entries), encoding="utf-8")
    for ref in ("Lanes", "Other", "lanes"):
        with pytest.raises(bs.BuildError, match=match):
            bs.find_proposal(folder, ref)


def test_cli_preview_prints_warnings(folder):
    bs.preview(folder, "lanes", today=DAY, now=NOW)
    (folder.structure / "proposals.yaml").write_text("- slug: [unclosed\n", encoding="utf-8")
    result = _cli("lanes", "--library", folder.root)
    assert result.exit_code == 0 and "WARNING structure/proposals.yaml is not valid YAML" in result.stdout


# -- log.md and library.yaml (R-505) -------------------------------------------------------


# -- master.db is never opened (R-504) -----------------------------------------------------


# -- CLI -----------------------------------------------------------------------------------


def _cli(*args):
    return runner.invoke(cli.app, ["library", "build", *[str(a) for a in args]])


def test_cli_preview_shows_rows_counts_nothing_written_and_the_id(folder):
    result = _cli("Build me the Lanes structure", "--library", folder.root, "--today", "2026-10-20")
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    for text in ("CREATE   folder   Lanes", "SKIP     playlist House/1.1_warm_up", "MANUAL   smart    Lanes/all techno",
                 "5 create, 4 skip, 0 conflict, 1 manual, 22 tracks", "Nothing written yet.",
                 "House/1.1_warm_up -> Lanes/118-124 house (4 tracks)"):  # fmt: skip
        assert text in out
    pid = re.search(r"preview id:\s+([0-9a-f]{12})", out).group(1)
    assert (folder.cache / "previews" / f"{pid}.json").is_file()
    assert not list(folder.proposals.glob("*.xml"))


def test_cli_apply_without_preview_id_refuses_before_anything_runs(folder, monkeypatch):
    for name in ("preview", "checked", "find_proposal"):
        monkeypatch.setattr(bs, name, lambda *a, **k: pytest.fail("ran before refusing"))
    monkeypatch.setattr(libfolder, "configured_root", lambda: pytest.fail("ran before refusing"))
    for extra in ([], ["--preview-id", "  "]):
        result = _cli("lanes", "--apply", *extra)
        assert result.exit_code == 1
        lines = result.stderr.strip().splitlines()
        assert len(lines) == 1 and lines[0].startswith("REFUSED --apply needs --preview-id")


def test_cli_preview_rows_limit_caps_the_json_rows_and_0_gives_every_row(folder):
    """NFR-03: the CLI caps `rows` at ROWS_LIMIT and counts the rest; the MCP tool asks for every
    row (--rows-limit 0) and pages them itself, so no row is out of reach."""
    capped = json.loads(_cli("lanes", "--library", folder.root, "--rows-limit", "3", "--json").stdout)
    assert len(capped["rows"]) == 3 and capped["rows_more"] == len(LANES_ROWS) - 3
    every = json.loads(_cli("lanes", "--library", folder.root, "--rows-limit", "0", "--json").stdout)
    assert [(r["op"], r["path"]) for r in every["rows"]] == LANES_ROWS and every["rows_more"] == 0
    assert json.loads(_cli("lanes", "--library", folder.root, "--json").stdout)["rows"] == every["rows"]
    page = m.paginate(capped, ("rows",), 1, 50, more={"rows": "rows_more"})
    assert page["paging"]["rows"]["total"] == len(LANES_ROWS) and page["paging"]["rows"]["listed"] == 3
    assert _cli("lanes", "--library", folder.root, "--rows-limit", "-1").exit_code != 0


def test_cli_blocked_preview_has_no_id(folder):
    result = _cli("clash", "--library", folder.root)
    assert result.exit_code == 0 and "BLOCKED 1 conflict(s): House" in result.stdout
    assert "preview id" not in result.stdout


@pytest.mark.parametrize(("args", "fragment"), [
    (["lanes", "--today", "20-10-2026"], "--today"),
    (["nope"], "No proposal matches"),
])  # fmt: skip
def test_cli_errors_are_one_line_exit_1(folder, args, fragment):
    result = _cli(*args, "--library", folder.root)
    assert result.exit_code == 1 and result.stderr.startswith("ERROR") and fragment in result.stderr


def test_cli_missing_library_folder_is_an_error(tmp_path):
    result = _cli("lanes", "--library", tmp_path / "nope")
    assert result.exit_code == 1 and "not a folder" in result.stderr


# -- MCP -----------------------------------------------------------------------------------


@pytest.fixture
def calls(monkeypatch, tmp_path):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return type("Done", (), {"returncode": 0, "stdout": '{"x": 1}', "stderr": ""})()

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path / "dj-library"))
    return seen


def test_mcp_structure_preview_passes_the_library_and_the_proposal_as_a_value(calls, tmp_path):
    answer = json.loads(m.dj_structure_preview("Build me the Lanes structure"))
    assert answer["ok"] is True
    root = str((tmp_path / "dj-library").resolve())
    assert calls[-1][3:] == ["library", "build", "--library", root, "--rows-limit", "0", "--json", "--",
                             "Build me the Lanes structure"]  # fmt: skip
    m.dj_structure_preview("--apply")
    assert calls[-1][3:] == ["library", "build", "--library", root, "--rows-limit", "0", "--json", "--", "--apply"]


@pytest.mark.parametrize("pid", ["", "   ", "--apply", "xyz", "0123456789AB", "0123456789ab --x"])
def test_mcp_structure_write_refuses_without_a_valid_preview_id_without_running(calls, pid):
    answer = json.loads(m.dj_structure_write("lanes", pid))
    assert answer["ok"] is False and "preview" in answer["error"]
    assert calls == []


def test_mcp_structure_write_refuses_an_empty_proposal_without_running(calls):
    assert json.loads(m.dj_structure_write(" ", "0123456789ab"))["ok"] is False
    assert json.loads(m.dj_structure_preview(""))["ok"] is False
    assert calls == []


def test_mcp_structure_write_passes_apply_and_the_preview_id(calls, tmp_path):
    m.dj_structure_write("lanes", " 0123456789ab ")
    root = str((tmp_path / "dj-library").resolve())
    assert calls[-1][3:] == ["library", "build", "--library", root, "--apply", "--preview-id", "0123456789ab",
                             "--json", "--", "lanes"]  # fmt: skip


def test_mcp_structure_tools_annotations():
    import asyncio

    tools = {t.name: t for t in asyncio.run(m.server.list_tools())}
    preview, write = tools["dj_structure_preview"].annotations, tools["dj_structure_write"].annotations
    assert (preview.read_only_hint, preview.destructive_hint) == (False, False)
    assert write == m.WRITE
    assert set(tools["dj_structure_write"].input_schema["required"]) == {"proposal", "preview_id"}


# -- the skill script (Door 1 entry point) -------------------------------------------------


def test_the_gate_record_lives_in_the_library_cache(folder):
    pid = bs.preview(folder, "lanes", today=DAY, now=NOW).preview_id
    assert Gate(folder.cache).load(pid).args == {"proposal": "lanes"}
    assert ".cache/" in folder.gitignore.read_text(encoding="utf-8")
