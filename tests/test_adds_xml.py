"""Q-22 / R-802: the XML route for inbox adds and copies (`dj apply --xml`, `dj copy --xml`).

The dry-run writes nothing and its preview id serves both write modes. `--apply --xml` with that id
writes `proposals/<crate-slug>-adds-<date>.xml` (one playlist, the approved tracks in order, their
file locations from the library), never opens a master.db write session (no backup, no process
check), records the decisions and one log.md line, and hands back the import card ending in the one
drag into the crate. pyrekordbox reads the file back. db mode stays Windows power mode. The MCP
write tools take `mode`. Design: docs/prompts/plans/W-30.md.
"""

from __future__ import annotations

import functools
import json
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pyrekordbox.rbxml import RekordboxXml
from test_cli import approve, run, sessions  # noqa: F401  (fixture)
from test_intake import CrateDB, plan_with
from test_playlist_copy import CopyDB, song

from dj import activity_log, cli, intake, libfolder, safety, write_gate
from dj import mcp_server as m
from dj import playlist_copy as copy_mod
from dj.gate import Gate
from dj.model import Track
from dj.writers import adds_xml

TODAY = date.today().isoformat()
CRATE = "funk_base/funk_crate"
XML = f"proposals/funk_base_funk_crate-adds-{TODAY}.xml"
COPY_XML = f"proposals/jazz_base_2.1_jazzy-adds-{TODAY}.xml"
NO_SUCH_ID = "0" * 12
REAL_PATHS = intake.Paths  # xml_env replaces intake.Paths with the temp repo layout


class XmlCrateDB(CrateDB):
    """CrateDB whose content rows carry a file location, BPM and key, as rekordbox's rows do."""

    def get_content(self, **kwargs):
        assert not kwargs, "read all content and filter alive rows in Python"

        def row(cid, deleted):
            return NS(ID=cid, ArtistName="Artist", Title=f"Track {cid}", AlbumName="", Length=200, ISRC="",
                      BitRate=320, FolderPath=f"D:/Music/Track {cid}.mp3", FileType=1, BPM=12400,
                      KeyName="8A", rb_local_deleted=deleted)  # fmt: skip

        rows = [row(i, 0) for i in sorted(self.library_ids)] + [row(i, 1) for i in sorted(self.deleted_ids)]
        return NS(all=lambda: rows)


class XmlCopyDB(CopyDB):
    """CopyDB that also answers the content read the XML needs."""

    def get_content(self, **kwargs):
        assert not kwargs
        rows = [s.Content for s in self.src.Songs + self.dst.Songs if s.Content is not None]
        return NS(all=lambda: rows)


def boom(*args, **kwargs):
    raise AssertionError("an --xml write must not run anything of a master.db write session")


@pytest.fixture
def xml_env(sessions, tmp_path, monkeypatch):  # noqa: F811
    """The inbox loop in the repo layout (a temp folder), a plan with two yes picks (3, then 1) and a
    no. Nothing of a write session (backup, process check) may run."""
    sessions.db = XmlCrateDB()
    monkeypatch.setattr(cli.intake, "Paths", functools.partial(cli.intake.Paths, tmp_path))
    monkeypatch.setattr(activity_log, "REPO_DIR", tmp_path)  # the temp folder is the repo: log.md there
    monkeypatch.setattr(copy_mod, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(safety, "backup", boom)
    monkeypatch.setattr(safety, "rekordbox_running", boom)
    plan = tmp_path / "x.plan.json"
    plan.write_text(json.dumps(plan_with(("yes", "3"), ("yes", "1"), ("no", "2"))), encoding="utf-8")
    return NS(root=tmp_path, plan=plan, sessions=sessions)


def xml_flags(sessions, *dry_run):  # noqa: F811
    """The flags of an --xml write after the DJ's yes to the dry-run (no --power-mode)."""
    return [*approve(sessions, *dry_run, power_mode=False), "--xml"]


def refused(result) -> str:
    assert result.exit_code == cli.EXIT_ERROR, result.output
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(lines) == 1 and lines[0].startswith("REFUSED "), result.stderr
    return lines[0]


def used(pid: str) -> bool:
    return bool(Gate(write_gate.STATE_DIR).load(pid).used)


def log_lines() -> list[str]:
    path = Path(activity_log.REPO_DIR) / "log.md"
    return [line for line in path.read_text(encoding="utf-8").splitlines()[1:] if line.strip()] if path.exists() else []


# -- dj apply ------------------------------------------------------------------------------


def test_apply_dry_run_writes_nothing_with_or_without_xml(xml_env):
    for extra in ([], ["--xml"]):
        data = json.loads(run("apply", xml_env.plan, *extra, "--json").output)
        assert (data["applied"], data["would_add"]) == (False, 2) and data["preview_id"]
    text = run("apply", xml_env.plan).stdout
    assert "--apply --xml --preview-id" in text and "--apply --power-mode --preview-id" in text
    assert xml_env.sessions.log == [False, False, False]
    assert not (xml_env.root / "proposals").exists() and not (xml_env.root / "state").exists()
    assert not (xml_env.root / "reports").exists() and log_lines() == []


def test_apply_xml_writes_the_file_and_never_opens_a_write_session(xml_env):
    flags = xml_flags(xml_env.sessions, "apply", xml_env.plan)
    pid = flags[flags.index("--preview-id") + 1]
    result = run("apply", xml_env.plan, *flags, "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert (data["applied"], data["mode"], data["added"], data["in_xml"], data["xml"]) == (True, "xml", 0, 2, XML)
    assert (xml_env.root / XML).is_file() and used(pid)
    assert xml_env.sessions.log == [False] and xml_env.sessions.db.added == []  # one snapshot read, no write
    steps = data["import_steps"]
    assert len(steps) == 3 and "rekordbox xml" in steps[0] and XML in steps[0] and "dj-librarian folder" in steps[0]
    assert f"funk_crate adds {TODAY}" in steps[2] and f"onto {CRATE}" in steps[2]
    report = json.loads(Path(data["report"]).read_text(encoding="utf-8"))
    assert (report["mode"], report["xml"], report["counts"]["in_xml"], report["counts"]["added"]) == ("xml", XML, 2, 0)
    assert [i["rb_content_id"] for i in report["in_xml"]] == ["3", "1"] and report["added"] == []
    state = xml_env.root / "state"
    assert json.loads((state / "match_cache.json").read_text(encoding="utf-8")) == {"u0": "3", "u1": "1"}
    assert [d["spotify_uri"] for d in json.loads((state / "declined.json").read_text(encoding="utf-8"))] == ["u2"]
    (line,) = log_lines()
    assert line.endswith(f"apply {CRATE} as XML -> 2 in XML, 1 no, 0 pending; {XML}") and data["log"] == line


def test_pyrekordbox_reads_the_approved_tracks_back_in_order(xml_env):
    assert run("apply", xml_env.plan, *xml_flags(xml_env.sessions, "apply", xml_env.plan)).exit_code == 0
    rb = RekordboxXml(xml_env.root / XML)
    playlist = rb.get_playlist(f"funk_crate adds {TODAY}")
    assert playlist.get_tracks() == [3, 1] and rb.num_tracks == 2
    track = rb.get_track(TrackID=3)
    assert track.Name == "Track 3" and track.AverageBpm == 124.0 and track.Tonality == "8A"
    rb.tostring()  # pyrekordbox's own consistency check passes
    raw = {t.get("TrackID"): t.get("Location") for t in ET.parse(xml_env.root / XML).iter("TRACK") if t.get("TrackID")}
    assert raw == {"3": "file://localhost/D:/Music/Track%203.mp3", "1": "file://localhost/D:/Music/Track%201.mp3"}


def test_apply_xml_text_output_gives_the_import_card(xml_env):
    result = run("apply", xml_env.plan, *xml_flags(xml_env.sessions, "apply", xml_env.plan))
    assert result.exit_code == 0, result.output
    assert f"WROTE {XML}: 2 track(s)" in result.stdout and "master.db untouched" in result.stdout
    assert "\n3. Open " in result.stdout and "that one drag adds them" in result.stdout


@pytest.mark.parametrize("case", ["missing", "unknown", "changed"])
def test_apply_xml_refusals_write_nothing(xml_env, case):
    pid = approve(xml_env.sessions, "apply", xml_env.plan, power_mode=False)[-1]
    if case == "missing":
        give, words = [], "No preview id"
    elif case == "unknown":
        give, words = ["--preview-id", NO_SUCH_ID], "No preview with id"
    else:
        xml_env.plan.write_text(json.dumps(plan_with(("yes", "3"), ("yes", "2"))), encoding="utf-8")
        give, words = ["--preview-id", pid], "The plan changed"
    assert words in refused(run("apply", xml_env.plan, "--apply", "--xml", *give))
    assert True not in xml_env.sessions.log and xml_env.sessions.db.added == []
    assert not (xml_env.root / "proposals").exists() and not (xml_env.root / "state").exists()
    assert log_lines() == [] and not used(pid)


def test_xml_and_power_mode_together_are_refused_before_anything(xml_env):
    pid = approve(xml_env.sessions, "apply", xml_env.plan)[-1]
    assert "pick one" in refused(run("apply", xml_env.plan, "--apply", "--xml", "--power-mode", "--preview-id", pid))
    assert xml_env.sessions.log == [] and not (xml_env.root / "proposals").exists()


def test_db_mode_is_unchanged_and_writes_no_xml(xml_env, monkeypatch):
    monkeypatch.setattr(safety, "rekordbox_running", lambda: False)  # the fake session needs no check
    flags = approve(xml_env.sessions, "apply", xml_env.plan)
    xml_env.sessions.paths.clear()
    result = run("apply", xml_env.plan, *flags)
    assert result.exit_code == 0, result.output
    assert xml_env.sessions.log == [False, True] and xml_env.sessions.db.added == ["3", "1"]
    assert xml_env.sessions.paths[1] is None  # the live write session
    assert not (xml_env.root / "proposals").exists() and "APPLIED. Added 2" in result.stdout


def test_one_preview_id_serves_one_write_in_either_mode(xml_env):
    flags = xml_flags(xml_env.sessions, "apply", xml_env.plan)
    pid = flags[flags.index("--preview-id") + 1]
    assert run("apply", xml_env.plan, *flags).exit_code == 0
    assert "already used" in refused(run("apply", xml_env.plan, "--apply", "--power-mode", "--preview-id", pid))
    assert "already used" in refused(run("apply", xml_env.plan, *flags))
    assert xml_env.sessions.db.added == []


def test_a_second_xml_the_same_day_never_replaces_the_first(xml_env):
    assert run("apply", xml_env.plan, *xml_flags(xml_env.sessions, "apply", xml_env.plan)).exit_code == 0
    first = (xml_env.root / XML).read_bytes()
    again = run("apply", xml_env.plan, *xml_flags(xml_env.sessions, "apply", xml_env.plan), "--json")
    assert again.exit_code == 0, again.output
    assert json.loads(again.stdout)["xml"] == XML.replace(".xml", "-2.xml")
    assert (xml_env.root / XML).read_bytes() == first


def test_apply_xml_in_the_library_folder_uses_its_proposals_and_device(xml_env, tmp_path, monkeypatch):
    lib = tmp_path / "dj-library"
    libfolder.scaffold(lib, device="mac", today=date(2026, 10, 20))
    monkeypatch.setattr(cli.intake, "default_paths", lambda: REAL_PATHS(lib, library=True))
    result = run("apply", xml_env.plan, *xml_flags(xml_env.sessions, "apply", xml_env.plan), "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert (lib / XML).is_file() and not (xml_env.root / "proposals").exists()
    assert data["device"] == "mac" and "rekordbox menu > Preferences" in data["import_steps"][0]
    assert "your dj-library folder" in data["import_steps"][0]
    assert Path(data["report"]).parent == lib / "reports" / "apply"


def test_a_pick_without_a_file_location_is_left_out_and_said(xml_env, monkeypatch):
    rows = XmlCrateDB().get_content().all()
    rows[0].FolderPath = ""  # track 1 has no file
    monkeypatch.setattr(xml_env.sessions.db, "get_content", lambda: NS(all=lambda: rows))
    data = json.loads(run("apply", xml_env.plan, *xml_flags(xml_env.sessions, "apply", xml_env.plan), "--json").stdout)
    assert (data["in_xml"], data["unplaced"]) == (1, ["1"])
    report = json.loads(Path(data["report"]).read_text(encoding="utf-8"))
    assert [i["rb_content_id"] for i in report["left_out"]] == ["1"] and report["counts"]["yes_already_in_crate"] == 0
    assert RekordboxXml(xml_env.root / XML).get_playlist(f"funk_crate adds {TODAY}").get_tracks() == [3]


# -- dj copy -------------------------------------------------------------------------------


@pytest.fixture
def copy_env(xml_env):
    xml_env.sessions.db = XmlCopyDB([song("3", 1), song("1", 2), song("2", 3)], target_songs=[song("2", 1)])
    return xml_env


def test_copy_dry_run_writes_nothing(copy_env):
    data = json.loads(run("copy", "jazzy", "jazz_base/2.1_jazzy", "--xml", "--json").output)
    assert data["applied"] is False and data["counts"] == {"ADD": 2, "SKIP": 1}
    assert not (copy_env.root / "proposals").exists() and not (copy_env.root / "reports").exists()


def test_copy_xml_writes_the_target_adds_in_source_order_without_a_write_session(copy_env):
    dry = ("copy", "jazzy", "jazz_base/2.1_jazzy")
    result = run(*dry, *xml_flags(copy_env.sessions, *dry), "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert (data["mode"], data["xml"], data["in_xml"], data["added"]) == ("xml", COPY_XML, 2, 0)
    assert copy_env.sessions.log == [False] and copy_env.sessions.db.added == []
    assert RekordboxXml(copy_env.root / COPY_XML).get_playlist(f"2.1_jazzy adds {TODAY}").get_tracks() == [3, 1]
    assert "onto jazz_base/2.1_jazzy" in data["import_steps"][2]
    report = json.loads(Path(data["report"]).read_text(encoding="utf-8"))
    assert (report["mode"], report["xml"], report["in_xml"]) == ("xml", COPY_XML, ["3", "1"])
    (line,) = log_lines()
    assert line.endswith(f"copy jazzy to jazz_base/2.1_jazzy as XML -> 2 in XML, 1 skipped; {COPY_XML}")


def test_copy_xml_refuses_without_the_preview_id_and_writes_nothing(copy_env):
    result = run("copy", "jazzy", "jazz_base/2.1_jazzy", "--apply", "--xml", "--preview-id", NO_SUCH_ID)
    assert "No preview with id" in refused(result)
    assert True not in copy_env.sessions.log and not (copy_env.root / "proposals").exists()


# -- the module ----------------------------------------------------------------------------


def track(tid: str, location: str = "D:/Music/x.mp3") -> Track:
    return Track(id=tid, artist="A", title=f"T{tid}", location=location and location.replace("x", tid))


def test_playlist_name_is_the_crate_leaf_and_the_date():
    assert adds_xml.playlist_name("house_base/1.1 warm up", date(2026, 10, 21)) == "1.1 warm up adds 2026-10-21"
    assert adds_xml.playlist_name("inbox", date(2026, 10, 21)) == "inbox adds 2026-10-21"


def test_write_refuses_when_no_track_has_a_location(tmp_path):
    with pytest.raises(adds_xml.BuildError, match="nothing to import"):
        adds_xml.write(tmp_path, slug="c", crate="c", tracks=[track("1", "")], day=date(2026, 10, 21),
                       device="mac", library=True)  # fmt: skip
    assert not (tmp_path / "proposals").exists()
    with pytest.raises(adds_xml.BuildError, match="one file-name part"):
        adds_xml.write(tmp_path, slug="a/b", crate="c", tracks=[track("1")], day=date(2026, 10, 21),
                       device="mac", library=True)  # fmt: skip


def test_device_comes_from_library_yaml_else_this_computer(tmp_path):
    lib = tmp_path / "lib"
    libfolder.scaffold(lib, device="mac", today=date(2026, 10, 20))
    assert adds_xml.device_for(lib) == "mac"
    assert adds_xml.device_for(None) == ("mac" if sys.platform == "darwin" else "windows")
    assert adds_xml.device_for(tmp_path / "not-a-library") == adds_xml.device_for(None)


def test_the_repo_root_xml_is_gitignored():
    lines = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/proposals/" in lines


# -- MCP: dj_apply_write / dj_copy_apply take mode -----------------------------------------------


PID = "0123456789ab"


@pytest.fixture
def calls(monkeypatch, tmp_path):
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return NS(returncode=0, stdout=json.dumps({"counts": {}}), stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)
    (tmp_path / "p.plan.json").write_text("{}", encoding="utf-8")
    return seen


def _options(cmd: list[str]) -> list[str]:
    return cmd[3:cmd.index("--")] if "--" in cmd else cmd[3:]


@pytest.mark.parametrize("tool", ["apply", "copy"])
def test_mcp_mode_picks_the_write_path(calls, tool):
    write = (functools.partial(m.dj_apply_write, "p.plan.json") if tool == "apply"
             else functools.partial(m.dj_copy_apply, "a", "b"))  # fmt: skip
    write(preview_id=PID)  # no mode, no power_mode: the default path, an XML
    write(preview_id=PID, mode="xml")
    write(preview_id=PID, power_mode=True)  # no mode, power_mode: master.db as before
    write(preview_id=PID, mode="db", power_mode=True)
    flags = [[o for o in _options(cmd) if o in ("--xml", "--power-mode")] for cmd in calls]
    assert flags == [["--xml"], ["--xml"], ["--power-mode"], ["--power-mode"]]
    assert all(_options(cmd)[_options(cmd).index("--preview-id") + 1] == PID for cmd in calls)


@pytest.mark.parametrize("tool", ["apply", "copy"])
@pytest.mark.parametrize("args, words", [
    ({"mode": "db"}, "power_mode=true"),
    ({"mode": "xml", "power_mode": True}, "needs no power_mode"),
    ({"mode": "both"}, "mode must be one of"),
    ({"mode": "xml", "preview_id": ""}, "No preview_id"),
])  # fmt: skip
def test_mcp_mode_refusals_run_nothing(calls, tool, args, words):
    kwargs = {"preview_id": PID} | args
    write = m.dj_apply_write if tool == "apply" else m.dj_copy_apply
    answer = json.loads(write("p.plan.json", **kwargs) if tool == "apply" else write("a", "b", **kwargs))
    assert answer["ok"] is False and words in answer["error"] and calls == []


def test_mcp_preview_then_xml_write_end_to_end(xml_env, monkeypatch):
    """dj_apply_preview -> its preview_id -> dj_apply_write (default mode) writes the XML in this
    process; no write session opens."""

    def in_process(cmd, **kwargs):
        result = cli_runner.invoke(cli.app, cmd[3:])
        return NS(returncode=result.exit_code, stdout=result.stdout, stderr=result.stderr)

    from typer.testing import CliRunner

    cli_runner = CliRunner()
    monkeypatch.setattr(m.subprocess, "run", in_process)
    monkeypatch.setattr(m, "REPO_ROOT", xml_env.root)
    pid = json.loads(m.dj_apply_preview(str(xml_env.plan)))["result"]["preview_id"]
    done = json.loads(m.dj_apply_write(str(xml_env.plan), preview_id=pid))
    assert done["ok"] is True and done["result"]["xml"] == XML and len(done["result"]["import_steps"]) == 3
    assert (xml_env.root / XML).is_file() and True not in xml_env.sessions.log and used(pid)
