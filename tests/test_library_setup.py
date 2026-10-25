"""dj.library_setup and scripts/library_init.py (W-36, D-30): install comes first, so the install
makes the dj-library folder (missing: created; empty: set up; this tool's: kept; other files or a
synced path: refused, nothing touched); dj-start picks the engine path when dj_status is callable;
the handle goes into library.yaml without an export. Everything under tmp_path."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from dj import libfolder
from dj import library_setup as ls

REPO = Path(__file__).resolve().parents[1]
DAY = date(2026, 10, 25)


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_missing_folder_is_made_and_set_up(tmp_path):
    folder = tmp_path / "Music" / "dj-library"
    result = ls.prepare(folder, device="mac", today=DAY)
    assert result["status"] == "created" and Path(result["library"]) == folder.resolve()
    meta = libfolder.load_meta(folder)
    assert meta["device"] == "mac" and meta["created"] == "2026-10-25" and meta["exports"]["latest"] is None
    assert "library.yaml" in result["created"] and " install " in (folder / "log.md").read_text(encoding="utf-8")


def test_an_empty_folder_is_set_up(tmp_path):
    folder = tmp_path / "dj-library"
    folder.mkdir()
    (folder / ".DS_Store").write_bytes(b"")  # an OS file does not make it full
    assert ls.prepare(folder, device="windows", today=DAY)["status"] == "created"
    assert libfolder.load_meta(folder)["device"] == "windows"


def test_a_folder_that_holds_library_yaml_is_used_as_it_is(tmp_path):
    folder = tmp_path / "dj-library"
    libfolder.scaffold(folder, device="windows", today=date(2026, 10, 1), dj_name="DJ Sample")
    before = _tree(folder)
    result = ls.prepare(folder, device="mac", today=DAY)
    assert result["status"] == "existing" and result["device"] == "windows" and result["created"] == []
    assert _tree(folder) == before  # not even log.md


def test_a_folder_with_other_files_is_refused_and_untouched(tmp_path):
    folder = tmp_path / "dj-library"
    folder.mkdir()
    (folder / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(ls.SetupError, match="pick another folder") as refused:
        ls.prepare(folder, device="mac", today=DAY)
    assert refused.value.reason == "not_empty" and _tree(folder) == {"notes.txt": b"mine"}


@pytest.mark.parametrize("cloud", ["OneDrive - Acme", "Dropbox", "iCloud Drive", "Mobile Documents", "Google Drive"])
def test_a_synced_folder_is_refused_and_nothing_is_made(tmp_path, cloud):
    folder = tmp_path / cloud / "dj-library"
    with pytest.raises(ls.SetupError, match="syncs to the cloud") as refused:
        ls.prepare(folder, device="mac", today=DAY)
    assert refused.value.reason == "synced" and not (tmp_path / cloud).exists()


def test_a_relative_path_a_drive_and_a_bad_device_are_refused(tmp_path):
    with pytest.raises(ls.SetupError, match="whole path") as relative:
        ls.prepare("dj-library", device="mac")
    assert relative.value.reason == "usage"
    with pytest.raises(ls.SetupError) as drive:
        ls.prepare(Path(tmp_path.anchor), device="mac")
    assert drive.value.reason == "refused"
    with pytest.raises(ls.SetupError, match="device"):
        ls.prepare(tmp_path / "x", device="linux")


def test_the_offer_is_music_dj_library(tmp_path):
    assert ls.default_folder(tmp_path) == tmp_path / "Music" / "dj-library"


def test_the_script_round_trip(tmp_path):
    script = REPO / "scripts" / "library_init.py"
    folder = tmp_path / "Music" / "dj-library"
    args = [sys.executable, str(script), "--folder", str(folder), "--device", "windows", "--today", "2026-10-25"]
    first = subprocess.run(args, capture_output=True, text=True, timeout=60)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["status"] == "created"
    again = subprocess.run(args, capture_output=True, text=True, timeout=60)
    assert json.loads(again.stdout)["status"] == "existing"
    full = tmp_path / "full"
    full.mkdir()
    (full / "song.mp3").write_bytes(b"")
    refused = subprocess.run([*args[:3], str(full), *args[4:]], capture_output=True, text=True, timeout=60)
    assert refused.returncode == 2 and json.loads(refused.stdout)["reason"] == "not_empty"


@pytest.mark.parametrize(("tools", "path"), [
    (["mcp__dj-librarian__dj_status", "mcp__dj-librarian__dj_pull"], "engine"),
    (["mcp__plugin_dj-librarian_dj-librarian__dj_status"], "engine"),
    (["dj_status"], "engine"),
    (["Read", "Bash", "mcp__other__dj_status_x", "mcp__dj-librarian__dj_pull"], "xml"),
    ([], "xml"),
])  # fmt: skip
def test_dj_start_picks_its_path_from_the_tool_list(tools, path):
    assert ls.session_path(tools) == path


def test_the_handle_goes_into_library_yaml_without_an_export(tmp_path):
    folder = tmp_path / "dj-library"
    ls.prepare(folder, device="mac", today=DAY)
    assert ls.set_handle(folder, "DJ Sample", today=DAY) == "DJ Sample"
    assert ls.set_handle(folder, "skip", today=DAY) == "You"
    start = REPO / "plugin" / "skills" / "dj-start" / "scripts" / "start.py"
    done = subprocess.run([sys.executable, str(start), "handle", "--library", str(folder), "--dj-name", "DJ Two"],
                          capture_output=True, text=True, timeout=60)  # fmt: skip
    assert done.returncode == 0, done.stdout
    assert json.loads(done.stdout) == {"dj_name": "DJ Two"} and libfolder.load_meta(folder)["dj_name"] == "DJ Two"
