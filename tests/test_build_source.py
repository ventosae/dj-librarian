"""Q-17: structure/proposals.yaml records the library read it was made from (`source`), and dj-build
refuses to build from an export that cannot hold the proposal's `from` playlists.

`source` is the export, relative to the library folder, or `master.db (snapshot read <time>)` for a
master.db read. The build reads the latest export; it is blocked (no preview id; apply refuses,
nothing written) when the named export is gone, when the export it reads is older than the named
export, or older than the master.db snapshot. The line: "Export again, then say the trigger
prompt." An entry without `source` is not checked.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timezone

import pytest
import xml_fixtures as fx
import yaml
from test_build_structure import DAY, NOW, PROPOSALS, _make_library, _snapshot
from typer.testing import CliRunner

from dj import build_structure as bs
from dj import cli, libfolder
from dj.analysis import proposals as P
from dj.analysis import run_all

EXPORT = "exports/2026-10-20-collection.xml"
LINE = "Export again, then say the trigger prompt."
runner = CliRunner()


def set_source(folder, source: str | None) -> None:
    entries = [dict(e) | ({"source": source} if source else {}) for e in PROPOSALS]
    (folder.root / "structure" / "proposals.yaml").write_text(
        yaml.safe_dump(entries, sort_keys=False, allow_unicode=True), encoding="utf-8")


def set_mtime(path, when: datetime) -> None:
    os.utime(path, (when.timestamp(), when.timestamp()))


@pytest.fixture
def folder(tmp_path):
    return _make_library(tmp_path)


def test_the_export_the_proposals_name_builds(folder):
    set_source(folder, EXPORT)
    p = bs.preview(folder, "lanes", today=DAY, now=NOW)
    assert p.blocked is None and p.preview_id
    assert bs.apply(folder, "lanes", p.preview_id, today=DAY, now=NOW).xml_file == "proposals/lanes.xml"


def test_a_missing_named_export_blocks_the_preview_and_the_apply(folder):
    set_source(folder, "exports/2026-10-19-collection.xml")
    p = bs.preview(folder, "lanes", today=DAY, now=NOW)
    assert p.preview_id is None and p.blocked.endswith(LINE)
    assert "exports/2026-10-19-collection.xml" in p.blocked
    before = _snapshot(folder.root)
    with pytest.raises(bs.BuildError, match=LINE):
        bs.apply(folder, "lanes", "0123456789ab", today=DAY, now=NOW)
    assert _snapshot(folder.root) == before


def test_an_export_older_than_the_named_one_blocks_the_build(folder, tmp_path):
    spec = dict(fx.SPEC) | {"product": {"Name": "rekordbox", "Version": "7.2.19", "Company": "AlphaTheta"}}
    newer = libfolder.import_export(folder.root, fx.write_xml(tmp_path / "newer.xml", spec), today=DAY)
    newer_rel = libfolder.relative(folder.root, newer)
    assert newer_rel != EXPORT
    libfolder.update_meta(folder.root, today=DAY, exports={"latest": EXPORT})  # the build reads the older one
    set_mtime(folder.root / EXPORT, datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc))
    set_mtime(newer, datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc))
    set_source(folder, newer_rel)
    p = bs.preview(folder, "lanes", today=DAY, now=NOW)
    assert p.preview_id is None and p.blocked.endswith(LINE) and f"export dj-build reads ({EXPORT})" in p.blocked
    set_source(folder, EXPORT)  # made from the export the build reads: fine
    assert bs.preview(folder, "lanes", today=DAY, now=NOW).preview_id


def test_a_db_source_needs_an_export_at_least_as_new_as_the_snapshot(folder):
    set_mtime(folder.root / EXPORT, datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc))
    set_source(folder, P.db_source("2026-10-20T12:00:00+00:00"))
    p = bs.preview(folder, "lanes", today=DAY, now=NOW)
    assert p.preview_id is None and p.blocked.endswith(LINE) and "made from master.db" in p.blocked
    with pytest.raises(bs.BuildError, match=LINE):
        bs.apply(folder, "lanes", "0123456789ab", today=DAY, now=NOW)
    set_mtime(folder.root / EXPORT, datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc))  # exported again
    assert bs.preview(folder, "lanes", today=DAY, now=NOW).preview_id


def test_an_old_export_imported_late_still_reads_as_old(folder, tmp_path):
    """The import keeps the time rekordbox wrote the export, not the time of the copy."""
    spec = dict(fx.SPEC) | {"product": {"Name": "rekordbox", "Version": "7.2.19", "Company": "AlphaTheta"}}
    source = fx.write_xml(tmp_path / "old.xml", spec)
    written = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    set_mtime(source, written)
    imported = libfolder.import_export(folder.root, source, today=DAY)
    assert libfolder.latest_export(folder.root) == imported
    assert imported.stat().st_mtime_ns == source.stat().st_mtime_ns == int(written.timestamp()) * 10**9
    set_source(folder, P.db_source("2026-10-20T12:00:00+00:00"))  # master.db read after that export
    p = bs.preview(folder, "lanes", today=DAY, now=NOW)
    assert p.preview_id is None and p.blocked.endswith(LINE) and "made from master.db" in p.blocked


def test_a_db_source_without_its_time_is_not_trusted(folder):
    set_source(folder, "master.db")
    assert bs.preview(folder, "lanes", today=DAY, now=NOW).blocked.endswith(LINE)


def test_a_proposal_without_a_source_is_not_checked(folder):
    set_source(folder, None)
    set_mtime(folder.root / EXPORT, datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert bs.preview(folder, "lanes", today=DAY, now=NOW).preview_id


def test_a_source_outside_the_folder_counts_as_missing(folder):
    for bad in ("../elsewhere.xml", str(folder.root / EXPORT)):
        set_source(folder, bad)
        assert bs.preview(folder, "lanes", today=DAY, now=NOW).blocked.endswith(LINE), bad


def test_the_cli_says_the_line_and_refuses_the_write(folder):
    set_source(folder, "exports/gone.xml")
    dry = runner.invoke(cli.app, ["library", "build", "lanes", "--library", str(folder.root), "--json"])
    assert dry.exit_code == 0 and json.loads(dry.stdout)["blocked"].endswith(LINE)
    wet = runner.invoke(cli.app, ["library", "build", "lanes", "--library", str(folder.root), "--apply",
                                  "--preview-id", "0123456789ab"])  # fmt: skip
    assert wet.exit_code == 1 and LINE in wet.output and not (folder.proposals / "lanes.xml").exists()


# -- where `source` comes from -------------------------------------------------------------------


def test_db_source_and_parse_source_round_trip():
    text = P.db_source("2026-10-20T12:00:00+00:00")
    assert text == "master.db (snapshot read 2026-10-20T12:00:00+00:00)"
    assert P.parse_source(text) == ("db", datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc))
    assert P.parse_source("master.db") == ("db", None)
    assert P.parse_source(EXPORT) == ("export", EXPORT)


def test_an_analysis_records_its_export_and_a_db_analysis_its_snapshot(folder, monkeypatch):
    run_all.analyze(folder.root, today=DAY)
    entries = P.load(folder.root / P.PROPOSALS_YAML)
    assert {e["source"] for e in entries} == {EXPORT}
    real = run_all.read_library

    def from_db(folder_, *, source="xml", xml=None):
        lib, _label = real(folder_)
        return replace(lib, source="db", read_at="2026-10-20T12:00:00+00:00"), run_all.DB_SOURCE

    monkeypatch.setattr(run_all, "read_library", from_db)
    run_all.analyze(folder.root, source="db", today=DAY)
    text = (folder.root / P.PROPOSALS_YAML).read_text(encoding="utf-8")
    assert {e["source"] for e in P.load(folder.root / P.PROPOSALS_YAML)} == {
        "master.db (snapshot read 2026-10-20T12:00:00+00:00)"}
    assert "generated from master.db (snapshot read 2026-10-20T12:00:00+00:00) on 2026-10-20." in text
    assert not P.edited(text)


def test_a_proposals_file_from_before_still_reads(folder):
    path = folder.root / "structure" / "two.yaml"
    path.write_text(yaml.safe_dump(PROPOSALS[:2], sort_keys=False), encoding="utf-8")
    assert all("source" not in e for e in P.load(path))  # written before `source` existed
    bad = [dict(PROPOSALS[0]) | {"source": "two\nlines"}, PROPOSALS[1]]
    path.write_text(yaml.safe_dump(bad, sort_keys=False), encoding="utf-8")
    with pytest.raises(P.ProposalsError, match="`source` must be one line"):
        P.load(path)


# -- W-36: a library analysed from master.db builds from master.db ---------------------------------------


@pytest.fixture
def live(tmp_path, monkeypatch):
    from dj import safety

    db = fx.write_master_files(tmp_path / "Pioneer" / "rekordbox")
    monkeypatch.setattr(safety, "_connect", lambda db_path, quiet=False: fx.fake_db())
    monkeypatch.setattr(safety, "find_master_db", lambda: db)
    return db


def _db_made(folder, when: str) -> None:
    path = folder.root / "structure" / "proposals.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for entry in data:
        entry["source"] = P.db_source(datetime.fromisoformat(when))
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_a_db_library_builds_from_master_db_even_with_an_older_export(folder, live):
    """Q-17 for the engine path: proposals made from master.db after the newest export are blocked
    on the export, but build from a fresh snapshot when library.yaml says source: db."""
    _db_made(folder, "2099-01-01T00:00:00+00:00")  # newer than any export
    assert bs.preview(folder, "lanes", today=DAY, now=NOW).blocked  # the XML read: blocked as before
    libfolder.update_meta(folder.root, today=DAY, source="db")
    found = bs.preview(folder, "lanes", today=DAY, now=NOW)
    assert found.export == "master.db" and found.blocked is None and found.preview_id
    result = bs.apply(folder, "lanes", found.preview_id, today=DAY, now=NOW)
    assert result.xml_path.is_file() and result.xml_file == "proposals/lanes.xml"


def test_the_cli_takes_source_db_and_refuses_another(folder, live):
    done = CliRunner().invoke(cli.app, ["library", "build", "lanes", "--library", str(folder.root), "--source", "db",
                                        "--today", "2026-10-20", "--json"])  # fmt: skip
    assert done.exit_code == 0, done.output
    assert json.loads(done.output[done.output.index("{"):])["export"] == "master.db"
    bad = CliRunner().invoke(cli.app, ["library", "build", "lanes", "--library", str(folder.root), "--source", "web"])
    assert bad.exit_code != 0 and "source must be one of xml, db" in bad.output
