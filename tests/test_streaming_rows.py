"""Q-34: rekordbox's collection holds the rows it streams (Spotify, Beatport Streaming, ...) next to
the local files. Both readers count them apart (`Library.streaming`) and keep them out of the tracks
and the playlists, so profile, structure, taste, crates and builds see local files only; `dj status`
prints the split (`tracks: 26 · 24 local · 2 streaming`), and the report states it once."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
import xml_fixtures as fx
from typer.testing import CliRunner

from dj import cli, libfolder, library, safety
from dj import mcp_server as m
from dj.analysis import run_all
from dj.readers.common import split_streaming, streaming_service
from dj.readers.db import read_db
from dj.readers.xml import read_xml

DAY = date(2026, 10, 20)
LOCAL = fx.EXPECTED_COUNTS["tracks"]  # 24
runner = CliRunner()


@pytest.mark.parametrize("location, service_id, service", [
    ("spotify:track:4uLU6hMCjMI75M1A2tKUQC", 0, "spotify"),
    ("beatport:tracks:17000026", 3, "beatport"),
    ("file://localhostsoundcloud:tracks:12", None, "soundcloud"),  # an XML Location
    ("file://localhost/tidal:tracks:77", None, "tidal"),
    ("D:/Music/House/a.mp3", 0, ""),
    ("C:\\Music\\a.mp3", 0, ""),
    ("/Users/dj/Music/AC:DC/a.mp3", 0, ""),  # a colon inside a Mac path is not a scheme
    ("//nas/music/a.flac", 0, ""),
    ("file://localhost/D:/Music/a%20b.mp3", 0, ""),
    ("file://localhost/Users/dj/a.mp3", 0, ""),
    ("D:/Music/bought on Beatport.mp3", 4, ""),  # a real file path wins over ServiceID
    ("", 4, "service 4"),
    ("", "7", "service 7"),
    ("", 0, ""),
    (None, None, ""),
])  # fmt: skip
def test_which_row_is_streamed(location, service_id, service):
    assert streaming_service(location, service_id) == service


def test_split_leaves_streamed_ids_out_of_every_playlist_and_keeps_the_rest(tmp_path):
    lib = read_xml_of(fx.without_smart(), tmp_path)
    tracks, streamed, roots = split_streaming(lib.tracks, {"8": "spotify", "nope": "tidal", "9": ""}, lib.roots)
    assert streamed == {"8": "spotify"} and "8" not in tracks and len(tracks) == LOCAL - 1
    assert roots[0].children[0].track_ids == ("21", "10", "11")  # 1.1_warm_up without 8
    assert split_streaming(lib.tracks, {}, lib.roots) == (lib.tracks, {}, lib.roots)


def read_xml_of(spec, folder):
    return read_xml(fx.write_xml(folder / "collection.xml", spec))


def test_the_xml_reader_counts_streamed_rows_apart(tmp_path):
    lib = read_xml_of(fx.with_streaming(), tmp_path)
    assert lib.streaming == fx.STREAMED_SERVICES and not set(fx.STREAMED) & set(lib.tracks)
    assert lib.counts()["tracks"] == LOCAL and lib.counts()["entries"] == fx.EXPECTED_COUNTS["entries"]
    assert lib.node_at("House/1.1_warm_up").track_ids == ("8", "21", "10", "11")
    assert lib.node_at("spotify finds").track_ids == ()  # only streamed rows: empty here
    assert lib.track_split() == {"tracks": LOCAL + 2, "local": LOCAL, "streaming": 2,
                                 "services": {"beatport": 1, "spotify": 1}}  # fmt: skip


@pytest.fixture
def live(tmp_path, monkeypatch):
    """master.db stand-ins whose pyrekordbox rows are the streaming spec (fake db)."""
    db = fx.write_master_files(tmp_path / "Pioneer" / "rekordbox")
    monkeypatch.setattr(safety, "_connect", lambda db_path, quiet=False: fx.fake_db(fx.with_streaming()))
    monkeypatch.setattr(safety, "find_master_db", lambda: db)
    return db


def test_the_db_reader_gives_the_same_split_as_the_xml_reader(live, tmp_path):
    from_db = read_db(live)
    from_xml = read_xml_of(fx.with_streaming(), tmp_path)
    assert from_db.streaming == from_xml.streaming == fx.STREAMED_SERVICES
    assert from_db.tracks.keys() == from_xml.tracks.keys()
    assert from_db.counts() | {"smart": 0} == from_xml.counts()  # the fake db adds one smart playlist
    assert from_db.node_at("spotify finds").track_ids == () and from_db.track_split() == from_xml.track_split()


def test_service_id_names_a_row_without_a_file_path(live, monkeypatch):
    spec = fx.with_streaming()
    spec["tracks"].append(dict(spec["tracks"][0], id="27", location="", service_id=9))
    spec["tracks"].append(dict(spec["tracks"][1], id="28", location="D:/Music/kept.mp3", service_id=5))
    monkeypatch.setattr(safety, "_connect", lambda db_path, quiet=False: fx.fake_db(spec))
    lib = read_db(live)
    assert lib.streaming["27"] == "service 9" and "28" in lib.tracks


def test_library_track_split_reads_the_alive_rows_only():
    split = library.track_split(fx.fake_db(fx.with_streaming()))  # with a soft-deleted ghost row
    assert split == {"tracks": LOCAL + 2, "local": LOCAL, "streaming": 2, "services": {"beatport": 1, "spotify": 1}}


# -- dj status (what the DJ compares with rekordbox's collection) ------------------------------------


@pytest.fixture
def status_env(live, monkeypatch):
    monkeypatch.setattr(cli, "links_data", lambda db, paths: [])
    return live


def test_status_prints_the_split(status_env):
    human = runner.invoke(cli.app, ["status"])
    assert human.exit_code == 0, human.output
    assert f"tracks:        {LOCAL + 2} · {LOCAL} local · 2 streaming" in human.output
    data = json.loads(runner.invoke(cli.app, ["status", "--json"]).output)
    assert data["tracks"] == LOCAL + 2 and data["counts"] == {"local": LOCAL, "streaming": 2}
    assert data["streaming_by"] == {"beatport": 1, "spotify": 1}


def test_dj_status_puts_the_split_with_the_counts(status_env, monkeypatch):
    data = json.loads(runner.invoke(cli.app, ["status", "--json"]).output)
    view = m.status_view(data)
    assert list(view["counts"])[:1] == ["tracks"]
    assert view["counts"]["tracks"] == LOCAL + 2 and view["counts"]["local"] == LOCAL
    assert view["counts"]["streaming"] == 2


# -- analysis: local files only, the split stated once ----------------------------------------------


@pytest.fixture
def lib_dir(tmp_path):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="windows", today=DAY)
    return root


def _facts(root, name):
    return json.loads((root / name / "facts.json").read_text(encoding="utf-8"))


def _measured(root):
    return SimpleNamespace(profile=_facts(root, "profile"), structure=_facts(root, "structure"),
                           taste=_facts(root, "taste"))  # fmt: skip


def _check_local_only(root, result):
    assert result["failed"] == [] and result["counts"]["tracks"] == LOCAL and result["counts"]["streaming"] == 2
    f = _measured(root)
    assert f.profile["size"]["tracks"] == LOCAL
    assert f.profile["streaming"] == {"tracks": 2, "services": {"beatport": 1, "spotify": 1}}
    collection = f.profile["headline"][0]
    assert collection["value"] == f"{LOCAL} tracks" and collection["note"].endswith("; 2 streamed not counted")
    assert f.structure["counts"]["tracks"] == LOCAL
    assert "spotify finds" in f.structure["empty"]["paths"]  # its rows were all streamed
    assert f.taste["tracks"] == LOCAL
    stats = (root / "profile" / "stats.md").read_text(encoding="utf-8")
    assert stats.count("streamed not counted") == 1
    report = next((root / "reports").glob("*.html")).read_text(encoding="utf-8")
    assert report.count("streamed not counted") == 1


def test_analyze_from_master_db_counts_local_files_only(lib_dir, live):
    _check_local_only(lib_dir, run_all.analyze(lib_dir, source="db", today=DAY))


def test_analyze_from_an_export_follows_the_same_rule(lib_dir, tmp_path):
    libfolder.import_export(lib_dir, fx.write_xml(tmp_path / "collection.xml", fx.with_streaming()), today=DAY)
    _check_local_only(lib_dir, run_all.analyze(lib_dir, today=DAY))


def test_no_streamed_rows_change_nothing(lib_dir, tmp_path):
    libfolder.import_export(lib_dir, fx.write_xml(tmp_path / "collection.xml"), today=DAY)
    run_all.analyze(lib_dir, today=DAY)
    f = _measured(lib_dir)
    assert f.profile["streaming"] == {"tracks": 0, "services": {}}
    assert f.profile["headline"][0]["note"] == "2.3 hours, 0.62 GB"
