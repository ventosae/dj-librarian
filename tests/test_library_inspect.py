"""`dj library inspect` and the MCP tool dj_library_inspect: read-only, JSON shape (R-204)."""

import json
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
def test_inspect_json_stays_small_for_a_huge_tree(tmp_path, pad, monkeypatch):
    from dj.commands.library import CHILD_LIMIT, NAME_LIMIT, TOP_LIMIT

    live = fx.write_master_files(tmp_path / "rb")
    monkeypatch.setattr(safety, "find_master_db", lambda: live)
    monkeypatch.setattr(safety, "_connect", lambda path, quiet=False: fx.fake_db(_big_spec(pad), deleted=False))
    result = run("library", "inspect", "--json")
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
    text = run("library", "inspect")
    assert f"... {60 - CHILD_LIMIT} more" in text.stdout and f"... {90 - TOP_LIMIT} more at the top" in text.stdout


# -- MCP ----------------------------------------------------------------------------------------


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stdout='{"source": "xml"}', stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    return seen


def test_mcp_inspect_without_xml_reads_master_db(calls):
    assert json.loads(m.dj_library_inspect())["ok"] is True
    assert calls[-1][3:] == ["library", "inspect", "--json"]


def test_library_root_defaults_to_the_repo_dj_library_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("DJ_LIBRARY", raising=False)
    monkeypatch.setattr(m.libfolder, "REPO_ROOT", tmp_path)
    assert m.library_root() == (tmp_path / "dj-library").resolve()


def test_the_default_library_folder_is_gitignored():
    """Rule 7: a DJ who keeps the default <repo>/dj-library must not see exports in git status."""
    lines = {line.strip() for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert "dj-library/" in lines


def test_mcp_inspect_is_a_read_tool():
    import asyncio

    tools = {t.name: t for t in asyncio.run(m.server.list_tools())}
    tool = tools["dj_library_inspect"]
    assert tool.annotations.read_only_hint is True and not tool.annotations.destructive_hint
    assert set(tool.input_schema["properties"]) == {"page", "page_size"}  # master.db only: no file argument
