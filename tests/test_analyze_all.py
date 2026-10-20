"""dj.analysis.run_all (W-17): the one-shot analysis, `dj library analyze` and the MCP tool
dj_library_analyze. Reads the library once (XML export or a master.db snapshot), writes every
analysis file and the report inside the library folder, nothing anywhere else, and opens no
write session on master.db (R-104, R-202, R-341, R-401 ... R-406)."""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import xml_fixtures as fx
from typer.testing import CliRunner

from dj import cli, libfolder, safety
from dj import mcp_server as m
from dj.analysis import common, run_all, taste
from dj.analysis import proposals as P

DAY = date(2026, 10, 20)
EXPORT = "exports/2026-10-20-collection.xml"
REPORT = "reports/2026-10-20-library.html"
WRITTEN = [
    "profile/stats.md", "profile/facts.json",
    "structure/analysis.md", "structure/graph.json", "structure/facts.json", "structure/current-tree.yaml",
    "taste/lanes.md", "taste/labels-artists.md", "taste/anchors.md", "taste/vocabulary.md",
    "taste/facts.json", "taste/cooccurrence.json",
    "structure/proposals.yaml", REPORT,
]  # fmt: skip
runner = CliRunner()


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def lib_dir(tmp_path) -> Path:
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="windows", today=DAY)
    libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=DAY)
    return root


@pytest.fixture
def sessions(monkeypatch):
    """Every safety.open_db session as (write, db_path); the real open_db still runs."""
    real, log = safety.open_db, []

    @contextmanager
    def recording(write=False, db_path=None):
        log.append((write, db_path))
        with real(write=write, db_path=db_path) as db:
            yield db

    monkeypatch.setattr(safety, "open_db", recording)
    return log


@pytest.fixture
def live(tmp_path, monkeypatch) -> Path:
    """Stand-in master.db files; pyrekordbox's connect gives the fake db of the fixture spec."""
    db = fx.write_master_files(tmp_path / "Pioneer" / "rekordbox")
    monkeypatch.setattr(safety, "_connect", lambda db_path, quiet=False: fx.fake_db())
    monkeypatch.setattr(safety, "find_master_db", lambda: db)
    return db


# -- from the XML export ------------------------------------------------------------------------------


def test_analyze_xml_writes_every_file_and_only_inside_the_library(lib_dir, tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("an XML analysis touched master.db")

    monkeypatch.setattr(safety, "open_db", refuse)
    monkeypatch.setattr(safety, "backup", refuse)
    reads = []
    real_read = run_all.read_xml
    monkeypatch.setattr(run_all, "read_xml", lambda path: reads.append(path) or real_read(path))
    before = snapshot(tmp_path)
    result = run_all.analyze(lib_dir, today=DAY)
    after = snapshot(tmp_path)

    assert len(reads) == 1  # the library is read once
    assert list(result)[0] == "counts"
    assert result["counts"] == {"tracks": 24, "playlists": 8, "folders": 3, "proposals": 3, "files": 14, "failed": 0}
    assert (result["source"], result["read"], result["report"]) == ("xml", EXPORT, REPORT)
    assert result["written"] == WRITTEN and result["kept"] == [] and result["failed"] == []
    assert [line.split(" ", 3)[2] for line in result["log"]] == ["profile", "structure", "taste", "report"]
    changed = {p for p in after if before.get(p) != after[p]}
    assert changed == {f"dj-library/{rel}" for rel in WRITTEN} | {"dj-library/log.md"}
    assert set(before) <= set(after)  # nothing removed; the export and the DJ's XML untouched


def test_the_files_hold_no_absolute_path(lib_dir, tmp_path):
    run_all.analyze(lib_dir, today=DAY)
    for rel in WRITTEN + ["log.md"]:
        text = (lib_dir / rel).read_text(encoding="utf-8")
        assert str(tmp_path) not in text and tmp_path.as_posix() not in text, rel


def test_a_second_run_keeps_what_the_dj_edited(lib_dir):
    run_all.analyze(lib_dir, today=DAY)
    path = lib_dir / "structure" / "proposals.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("House Bases", "Telepathy Bases"), encoding="utf-8")
    result = run_all.analyze(lib_dir, today=DAY)
    assert result["kept"] == ["structure/proposals.edited-2026-10-20.yaml"]
    assert result["report"] == "reports/2026-10-20-library-2.html"
    assert result["counts"]["files"] == 15


def test_a_step_that_fails_is_named_and_the_report_still_renders(lib_dir, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(taste, "write", broken)
    result = run_all.analyze(lib_dir, today=DAY)
    assert result["failed"] == [{"step": "taste", "error": "disk full"}]
    assert result["counts"]["failed"] == 1 and result["report"] == REPORT
    assert not (lib_dir / "taste" / "facts.json").exists()
    done = runner.invoke(cli.app, ["library", "analyze", "--library", str(lib_dir), "--today", "2026-10-20"])
    assert done.exit_code == 1 and "FAILED taste: disk full" in done.output


def test_bad_arguments(lib_dir):
    with pytest.raises(ValueError, match="source"):
        run_all.analyze(lib_dir, source="cloud", today=DAY)
    with pytest.raises(ValueError, match="--xml goes with --source xml"):
        run_all.analyze(lib_dir, source="db", xml=EXPORT, today=DAY)


def test_a_folder_that_is_not_a_library_is_refused(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(common.NotALibraryFolder):
        run_all.analyze(plain, xml=fx.SAMPLE_XML, today=DAY)
    assert list(plain.iterdir()) == []


# -- from master.db (Door 2) ------------------------------------------------------------------------


def test_analyze_db_reads_one_snapshot_and_db_data_reaches_every_file(lib_dir, live, sessions, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))  # where read_db takes its snapshot
    live_before = snapshot(live.parent)
    outside_before = {k: v for k, v in snapshot(tmp_path).items() if not k.startswith("dj-library/")}

    result = run_all.analyze(lib_dir, source="db", today=DAY)

    assert len(sessions) == 1 and sessions[0][0] is False  # one read-only session ...
    assert sessions[0][1] != live and sessions[0][1].name == "master.db"  # ... on the snapshot copy
    assert list(scratch.iterdir()) == []  # the snapshot folder is gone
    assert snapshot(live.parent) == live_before
    outside_after = {k: v for k, v in snapshot(tmp_path).items() if not k.startswith("dj-library/")}
    assert outside_after == outside_before  # nothing written outside the library folder

    assert result["read"] == "master.db" and result["failed"] == []
    assert result["counts"]["playlists"] == 9  # 8 plain + the smart one the XML cannot carry
    profile = json.loads((lib_dir / "profile" / "facts.json").read_text(encoding="utf-8"))
    assert profile["fields"]["my_tags"] is not None and profile["not_in_source"] == []
    assert profile["provenance"]["source"] == "master.db"
    structure = json.loads((lib_dir / "structure" / "facts.json").read_text(encoding="utf-8"))
    assert structure["counts"]["smart"] == 1
    assert "rules_raw" in (lib_dir / "structure" / "current-tree.yaml").read_text(encoding="utf-8")
    assert "from master.db, 2026-10-20" in (lib_dir / "taste" / "lanes.md").read_text(encoding="utf-8")
    for entry in P.load(lib_dir / "structure" / "proposals.yaml"):
        assert {"from": "All Techno", "to": P.STAYS} in entry["lands"]
    page = (lib_dir / result["report"]).read_text(encoding="utf-8")
    assert "read from master.db" in page and "Not in this source" not in page
    for rel in result["written"] + ["log.md"]:
        text = (lib_dir / rel).read_text(encoding="utf-8")
        assert live.parent.as_posix() not in text and str(live.parent) not in text, rel


def test_cli_analyze_db(lib_dir, live, sessions):
    done = runner.invoke(cli.app, ["library", "analyze", "--library", str(lib_dir), "--source", "db",
                                   "--today", "2026-10-20", "--json"])  # fmt: skip
    assert done.exit_code == 0, done.output
    data = json.loads(done.output[done.output.index("{"):])
    assert data["read"] == "master.db" and data["counts"]["playlists"] == 9
    assert all(write is False for write, _path in sessions)


# -- CLI and MCP --------------------------------------------------------------------------------------


def test_cli_analyze_json_and_text(lib_dir):
    done = runner.invoke(cli.app, ["library", "analyze", "--library", str(lib_dir), "--today", "2026-10-20", "--json"])
    assert done.exit_code == 0, done.output
    data = json.loads(done.output)
    assert data["written"] == WRITTEN and data["report"] == REPORT
    text = runner.invoke(cli.app, ["library", "analyze", "--library", str(lib_dir), "--today", "2026-10-20"])
    assert text.exit_code == 0
    assert text.output.startswith(f"analyze: read {EXPORT} (24 tracks, 8 playlists, 3 folders)")
    assert "report: reports/2026-10-20-library-2.html" in text.output
    assert "Nothing was written to rekordbox." in text.output


def test_cli_analyze_refuses_and_errors(lib_dir, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    done = runner.invoke(cli.app, ["library", "analyze", "--library", str(plain)])
    assert done.exit_code == 2 and "REFUSED" in done.output and list(plain.iterdir()) == []
    done = runner.invoke(cli.app, ["library", "analyze", "--library", str(lib_dir), "--source", "cloud"])
    assert done.exit_code == 1 and "ERROR source must be one of xml, db" in done.output


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"x": 1}', stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    return seen


def test_mcp_tool_runs_one_fixed_command(calls):
    assert json.loads(m.dj_library_analyze())["ok"] is True
    assert calls[-1][0][3:] == ["library", "analyze", "--source", "xml", "--json"]
    m.dj_library_analyze("db")
    assert calls[-1][0][3:] == ["library", "analyze", "--source", "db", "--json"]
    assert "shell" not in calls[-1][1]


def test_mcp_tool_refuses_another_source_without_running(calls):
    for bad in ("cloud", "--apply", "xml; rm"):
        answer = json.loads(m.dj_library_analyze(bad))
        assert answer["ok"] is False and "source must be one of" in answer["error"]
    assert calls == []


def test_mcp_tool_on_a_folder_not_set_up_runs_the_real_cli_and_never_blames_rekordbox(tmp_path, monkeypatch):
    """The real `python -m dj.cli library analyze` subprocess on a configured folder without a
    library.yaml: exit 2 (refused), nothing written, and a hint that points at dj-start."""
    plain = tmp_path / "plainlib"
    plain.mkdir()
    monkeypatch.setenv("DJ_LIBRARY", str(plain))
    answer = json.loads(m.dj_library_analyze())
    assert (answer["ok"], answer["exit_code"]) == (False, 2), answer
    assert any(line.startswith("REFUSED plainlib is not a dj-library folder") for line in answer["stderr"])
    assert answer["hint"] == m.NO_LIBRARY and "rekordbox is open" not in answer["hint"]
    assert list(plain.iterdir()) == []


def test_mcp_tool_writes_text_files_only():
    import asyncio

    tool = {t.name: t for t in asyncio.run(m.server.list_tools())}["dj_library_analyze"]
    assert tool.annotations.read_only_hint is False and tool.annotations.destructive_hint is False
    assert "source" in tool.input_schema["properties"]
