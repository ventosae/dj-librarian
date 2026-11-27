"""dj.catalog (D-37): the track catalog, `dj library query` / `note` and their MCP tools.

Built from the fixture library read through the fake master.db (xml_fixtures), with two streamed rows.
Every file under tmp_path; no real database, no network."""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
import xml_fixtures as fx
from typer.testing import CliRunner

from dj import catalog, cli, libfolder, mcp_catalog, safety
from dj import mcp_server as m
from dj.readers.db import read_db

DAY = date(2026, 10, 20)
runner = CliRunner()


@pytest.fixture
def live(tmp_path, monkeypatch) -> Path:
    """Stand-in master.db files; pyrekordbox's connect gives the fake db (24 local rows, 2 streamed)."""
    db = fx.write_master_files(tmp_path / "Pioneer" / "rekordbox")
    monkeypatch.setattr(safety, "_connect", lambda db_path, quiet=False: fx.fake_db(fx.with_streaming()))
    monkeypatch.setattr(safety, "find_master_db", lambda: db)
    return db


@pytest.fixture
def root(tmp_path, live) -> Path:
    folder = tmp_path / "dj-library"
    libfolder.scaffold(folder, device="windows", today=DAY)
    return folder


def rows(root: Path, sql: str, *args) -> list[tuple]:
    with closing(sqlite3.connect(root / catalog.DB)) as con:
        return con.execute(sql, args).fetchall()


def test_row_counts_match_the_library(root, live):
    lib = read_db()
    made = catalog.ensure(root, lib, today=DAY)
    assert {k: made[k] for k in ("db", "csv", "tracks", "rebuilt")} == {
        "db": "catalog/catalog.db", "csv": "catalog/tracks.csv", "tracks": 26, "rebuilt": True}  # fmt: skip
    assert rows(root, "SELECT count(*), sum(local) FROM tracks") == [(26, len(lib.tracks))] and len(lib.tracks) == 24
    assert rows(root, "SELECT id FROM tracks WHERE local = 0 ORDER BY id") == [("25",), ("26",)]
    assert rows(root, "SELECT count(*) FROM playlists") == [(len(lib.walk()),)]
    assert rows(root, "SELECT count(*) FROM playlist_tracks") == [(lib.counts()["entries"],)]
    peak = lib.node_at("House/1.2_peak")
    assert rows(root, "SELECT kind, parent FROM playlists WHERE path = ?", "House/1.2_peak") == [
        ("playlist", lib.node_at("House").id)]  # fmt: skip
    in_order = rows(root, "SELECT track_id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position", peak.id)
    assert tuple(t for (t,) in in_order) == peak.track_ids
    assert rows(root, "SELECT artist, bpm, key, camelot, my_tags, date_added, has_artwork FROM tracks WHERE id = '9'") == [
        ("Tessa Quorum", 120.0, "Cm", "5A", "Peak", "2022-03-03", 1)]  # fmt: skip
    assert dict(rows(root, "SELECT key, value FROM meta"))["db_sha256"] == safety.sha256(live)
    assert catalog.ensure(root, lib)["rebuilt"] is False  # master.db hashes as stored: kept
    assert "catalog -> 26 tracks" in (root / "log.md").read_text(encoding="utf-8")


def test_notes_survive_a_rebuild(root, live):
    def run(*args):
        done = runner.invoke(cli.app, ["library", *args, "--library", str(root), "--json"])
        return done.exit_code, (json.loads(done.stdout) if done.exit_code == 0 else done.output)

    code, noted = run("note", "9", "energy", "peak, hands up")  # builds the catalog first
    assert code == 0 and noted["counts"] == {"notes": 1} and noted["track"] == "Tessa Quorum - Open Plan"
    assert noted["note"]["date"] == date.today().isoformat() and noted["note"]["source"] == "dj"
    code, refused = run("note", "999", "energy", "x")
    assert code == 1 and "No track with id 999" in refused

    built = dict(rows(root, "SELECT key, value FROM meta"))["db_sha256"]
    live.write_bytes(live.read_bytes() + b" rekordbox wrote")  # master.db changed: the next read rebuilds
    code, found = run("query", "SELECT track_id, field, value, source FROM notes")
    assert code == 0 and found == {"counts": {"rows": 1, "page": 1, "pages": 1},
                                   "columns": ["track_id", "field", "value", "source"],
                                   "rows": [["9", "energy", "peak, hands up", "dj"]]}  # fmt: skip
    assert dict(rows(root, "SELECT key, value FROM meta"))["db_sha256"] not in ("", built)
    assert rows(root, "SELECT count(*) FROM tracks") == [(26,)]


def test_csv_rows_are_the_tracks(root):
    catalog.ensure(root)
    with open(root / catalog.CSV, encoding="utf-8-sig", newline="") as fh:
        table = list(csv.reader(fh))
    assert tuple(table[0]) == catalog.COLUMNS and table[0][-2:] == ["camelot", "local"]
    assert len(table) - 1 == rows(root, "SELECT count(*) FROM tracks")[0][0] == 26
    by_id = {row[0]: dict(zip(table[0], row)) for row in table[1:]}
    assert by_id["4"]["artist"] == "Jørn Ébène" and by_id["4"]["camelot"] == "8B" and by_id["25"]["local"] == "0"


@pytest.mark.parametrize("sql", [
    "INSERT INTO notes VALUES ('9', 'a', 'b', 'c', 'd')",
    "DROP TABLE tracks",
    "PRAGMA table_info(tracks)",
    "SELECT 1; DELETE FROM tracks",
    "ATTACH DATABASE 'other.db' AS other",
    "WITH gone AS (SELECT 1) DELETE FROM notes",
])  # fmt: skip
def test_query_refuses_anything_but_one_select(root, sql):
    catalog.ensure(root)
    before = (root / catalog.DB).read_bytes()
    with pytest.raises(catalog.CatalogError, match="Only one SELECT statement is allowed") as caught:
        catalog.query(root, sql)
    assert "\n" not in str(caught.value) and (root / catalog.DB).read_bytes() == before
    assert not (root / "other.db").exists() and not (root / "catalog" / "other.db").exists()
    done = runner.invoke(cli.app, ["library", "query", sql, "--library", str(root)])
    assert done.exit_code == 1 and "ERROR Only one SELECT" in done.output


def test_a_select_comes_back_in_pages_counts_first_and_the_tools_pass_a_list(root, monkeypatch):
    catalog.ensure(root)
    found = catalog.query(root, "SELECT p.path, t.title FROM playlist_tracks pt JOIN playlists p ON p.id = "
                                "pt.playlist_id JOIN tracks t ON t.id = pt.track_id ORDER BY p.path, pt.position;")
    assert list(found) == ["counts", "columns", "rows"] and found["counts"] == {"rows": 51, "page": 1, "pages": 1}
    monkeypatch.setattr(catalog, "PAGE_ROWS", 20)
    second = catalog.query(root, "SELECT id FROM tracks ORDER BY CAST(id AS INTEGER)", page=2)
    assert second["counts"] == {"rows": 26, "page": 2, "pages": 2} and second["rows"] == [[str(i)] for i in (21, 22, 23, 24, 25, 26)]

    calls = []
    monkeypatch.setattr(m, "run_dj_data", lambda options, positionals=(): calls.append((options, positionals)) or {"ok": True})
    mcp_catalog.dj_query("SELECT 1 --apply", page=2)
    mcp_catalog.dj_note("9", "energy", "--json")
    assert calls == [(["library", "query", "--page", "2"], ("SELECT 1 --apply",)),
                     (["library", "note", "--source", "dj"], ("9", "energy", "--json"))]  # fmt: skip
    assert json.loads(mcp_catalog.dj_query(""))["ok"] is False and len(calls) == 2
