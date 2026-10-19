"""`dj library inspect` and the MCP tool dj_library_inspect: read-only, JSON shape (R-204)."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import xml_fixtures as fx
from typer.testing import CliRunner

from dj import cli, safety
from dj import mcp_server as m
from dj.readers.db import DB_NOTES

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]


def run(*args):
    return runner.invoke(cli.app, [str(a) for a in args])


@pytest.fixture
def sessions(monkeypatch):
    """Wraps safety.open_db (the real one) and records the `write` flag of every session."""
    real, log = safety.open_db, []

    @contextmanager
    def recording(write=False, db_path=None):
        log.append(write)
        with real(write=write, db_path=db_path) as db:
            yield db

    monkeypatch.setattr(safety, "open_db", recording)
    return log


def test_inspect_xml_json_shape(sessions):
    result = run("library", "inspect", fx.SAMPLE_XML, "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert {"source", "counts", "tree", "fields_missing"} <= set(data)
    assert data["source"] == "xml" and data["counts"] == fx.EXPECTED_COUNTS
    assert data["fields_missing"] == ["isrc", "bit_depth", "my_tags", "has_artwork"]
    assert data["tree"][0] == {"kind": "folder", "name": "House", "children": ["1.1_warm_up", "1.2_peak", "Deep"]}
    assert data["tree"][2] == {"kind": "playlist", "name": "unsorted dump", "tracks": 16, "children": []}
    assert all(set(n) >= {"kind", "name", "children"} for n in data["tree"])
    assert data["snapshot_path"] is None and data["tree_more"] == 0
    assert sessions == []  # the XML path never opens master.db


def test_inspect_without_xml_reads_a_master_db_snapshot_read_only(sessions, monkeypatch, tmp_path):
    live = fx.write_master_files(tmp_path / "rb")
    opened = []
    monkeypatch.setattr(safety, "find_master_db", lambda: live)
    monkeypatch.setattr(safety, "_connect", lambda path, quiet=False: opened.append(path) or fx.fake_db())
    result = run("library", "inspect", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["source"] == "db" and data["fields_missing"] == [] and data["counts"]["smart"] == 1
    assert data["rekordbox_version"] == "7.2.18" and data["source_path"] == live.as_posix()
    assert sessions == [False] and opened and opened[0] != live
    # R-202 "snapshot path logged": on stderr in a real run, and in the JSON
    assert data["snapshot_path"] == opened[0].as_posix()
    assert f"reading master.db snapshot {opened[0]}" in result.stderr
    # smart members are not stored in master.db: no `tracks` for the smart node, and a note says so
    smart = next(n for n in data["tree"] if n["kind"] == "smart")
    assert smart == {"kind": "smart", "name": "All Techno", "children": []}
    assert data["notes"] == list(DB_NOTES)


def test_inspect_db_text_output_shows_the_snapshot_and_the_notes(monkeypatch, tmp_path):
    live = fx.write_master_files(tmp_path / "rb")
    monkeypatch.setattr(safety, "find_master_db", lambda: live)
    monkeypatch.setattr(safety, "_connect", lambda path, quiet=False: fx.fake_db())
    result = run("library", "inspect")
    assert result.exit_code == 0, result.output
    assert "snapshot:" in result.stdout and "[smart] All Techno\n" in result.stdout
    assert "smart playlists: master.db stores their rules" in result.stdout


def test_inspect_db_failure_is_exit_1_with_one_error_line(monkeypatch, tmp_path):
    live = fx.write_master_files(tmp_path / "rb")
    monkeypatch.setattr(safety, "find_master_db", lambda: live)

    class Torn(fx.SpecDB):
        def get_content(self, **kwargs):
            raise RuntimeError("(sqlite3.DatabaseError) file is not a database\n[SQL: SELECT ...]")

    monkeypatch.setattr(safety, "_connect", lambda path, quiet=False: Torn([], []))
    result = run("library", "inspect", "--json")
    assert result.exit_code == 1 and isinstance(result.exception, SystemExit)  # not a traceback
    errors = [line for line in result.stderr.splitlines() if line.startswith("ERROR")]
    assert errors == ["ERROR The master.db snapshot could not be read (RuntimeError: (sqlite3.DatabaseError) "
                      "file is not a database)."]
    assert result.stdout == ""


def _big_spec(names: int = 20) -> dict:
    """40 folders x 60 playlists plus 50 top-level playlists, every name `names` chars or more."""
    spec = fx.spec_copy()
    pad = "x" * names
    spec["tree"] = [
        {"kind": "folder", "name": f"folder {f:02d} {pad}", "children": [
            {"kind": "playlist", "name": f"{f:02d}.{p:02d}_playlist {pad}", "tracks": ["1"]} for p in range(60)]}
        for f in range(40)
    ] + [{"kind": "playlist", "name": f"top {i} {pad}", "tracks": []} for i in range(50)]
    return spec


@pytest.mark.parametrize("pad", [10, 300])
def test_inspect_json_stays_small_for_a_huge_tree(tmp_path, pad):
    from dj.commands.library import CHILD_LIMIT, NAME_LIMIT, TOP_LIMIT

    xml = fx.write_xml(tmp_path / "big.xml", _big_spec(pad))
    result = run("library", "inspect", xml, "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["counts"]["playlists"] == 40 * 60 + 50 and data["counts"]["folders"] == 40
    assert len(data["tree"]) == TOP_LIMIT and data["tree_more"] == 90 - TOP_LIMIT
    first = data["tree"][0]
    assert len(first["children"]) == CHILD_LIMIT and first["more_children"] == 60 - CHILD_LIMIT
    assert all(len(n["name"]) <= NAME_LIMIT and all(len(c) <= NAME_LIMIT for c in n["children"]) for n in data["tree"])
    # what the MCP tool hands the agent (run_dj re-wraps the result with indent=2)
    wrapped = json.dumps({"ok": True, "exit_code": 0, "result": data}, indent=2, ensure_ascii=False)
    assert len(result.stdout.encode()) < 60_000 and len(wrapped.encode()) < 60_000
    text = run("library", "inspect", xml)
    assert f"... {60 - CHILD_LIMIT} more" in text.stdout and f"... {90 - TOP_LIMIT} more at the top" in text.stdout


def test_inspect_text_output_names_what_the_xml_lacks():
    result = run("library", "inspect", fx.SAMPLE_XML)
    assert result.exit_code == 0, result.output
    assert "24 tracks, 3 folders, 8 playlists, 0 smart, 2 orphans, 51 entries" in result.output
    assert "[folder] House" in result.output and "not in the XML export: isrc" in result.output


def test_inspect_bad_input_is_exit_1_not_a_traceback(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<nope/>", encoding="utf-8")
    for target in (bad, tmp_path / "missing.xml"):
        result = run("library", "inspect", target, "--json")
        assert result.exit_code == 1 and "ERROR" in result.output


def test_dj_library_inspect_command_line_prints_json():
    """The acceptance line: `dj library inspect tests/fixtures/sample.xml --json`."""
    env = dict(os.environ, PYTHONUTF8="1")
    done = subprocess.run(
        [sys.executable, "-m", "dj.cli", "library", "inspect", "tests/fixtures/sample.xml", "--json"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=120, env=env,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert {"source", "counts", "tree", "fields_missing"} <= set(json.loads(done.stdout))


# -- MCP ----------------------------------------------------------------------------------------


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stdout='{"source": "xml"}', stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    return seen


@pytest.fixture
def folders(tmp_path, monkeypatch):
    repo, library = tmp_path / "repo", tmp_path / "dj-library"
    (repo / "tests").mkdir(parents=True)
    (library / "exports").mkdir(parents=True)
    monkeypatch.setattr(m, "REPO_ROOT", repo)
    monkeypatch.setenv("DJ_LIBRARY", str(library))
    return repo, library


def test_mcp_inspect_without_xml_reads_master_db(calls):
    assert json.loads(m.dj_library_inspect())["ok"] is True
    assert calls[-1][3:] == ["library", "inspect", "--json"]


def test_mcp_inspect_accepts_an_xml_in_the_library_folder_or_the_repo(calls, folders):
    repo, library = folders
    export = fx.write_xml(library / "exports" / "2026-10-20-collection.xml")
    in_repo = fx.write_xml(repo / "tests" / "sample.xml")
    m.dj_library_inspect("exports/2026-10-20-collection.xml")
    assert calls[-1][3:] == ["library", "inspect", "--json", "--", str(export.resolve())]
    m.dj_library_inspect(str(in_repo))
    assert calls[-1][-1] == str(in_repo.resolve())


def test_mcp_inspect_refuses_paths_outside_and_wrong_types(calls, folders, tmp_path):
    repo, library = folders
    outside = fx.write_xml(tmp_path / "elsewhere.xml")
    (library / "notes.txt").write_text("x", encoding="utf-8")
    for bad in (str(outside), "../elsewhere.xml", "notes.txt", "exports/missing.xml"):
        answer = json.loads(m.dj_library_inspect(bad))
        assert answer["ok"] is False and "error" in answer, bad
    assert calls == []


def test_library_root_defaults_to_the_repo_dj_library_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("DJ_LIBRARY", raising=False)
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)
    assert m.library_root() == tmp_path / "dj-library"


def test_the_default_library_folder_is_gitignored():
    """Rule 7: a DJ who keeps the default <repo>/dj-library must not see exports in git status."""
    lines = {line.strip() for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert "dj-library/" in lines


def test_mcp_inspect_is_a_read_tool():
    import asyncio

    tools = {t.name: t for t in asyncio.run(m.server.list_tools())}
    tool = tools["dj_library_inspect"]
    assert tool.annotations.read_only_hint is True and not tool.annotations.destructive_hint
    assert "xml" in tool.input_schema["properties"]
