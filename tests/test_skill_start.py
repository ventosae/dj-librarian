"""dj-start: onboarding session 1 (W-13). `dj.onboarding`, the script `start.py`, the SKILL.md text.

R-101 device first, only that OS after (the device given last wins); R-103 scaffold +
library.yaml (device, rekordbox version, date); R-104 the XML export is the first input, 3-step
card; R-105 step counter and time estimate on every reply; R-904 one log.md line per change.
R-104's acceptance ("analysis + report run on the XML alone") is the end-to-end test below: it
runs the step 4 scripts as SKILL.md names them, with the engine packages blocked (W-17).
R-106: W-13 delivers the text constraints (3 DJ moves, no question in steps 4-5, replies under
5 lines); its acceptance, the transcript of the test session, is W-28's. R-102 (engine after the
report) and R-107 (optional Project template) are pointed at here, built later.
The script runs two ways: imported from its path and as a subprocess with this Python.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml
from test_door1_imports import BLOCKED, run_blocked

from dj import onboarding
from dj.libfolder import DIRS, FILES, load_meta, validate_meta
from dj.readers.xml import read_xml

REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "plugin" / "skills" / "dj-start"
SKILL = SKILL_DIR / "SKILL.md"
SCRIPT = SKILL_DIR / "scripts" / "start.py"
DAY = "2026-10-20"
NEXT_DAY = "2026-10-21"
EXPORT = f"exports/{DAY}-collection.xml"

# The canonical block of docs/prompts/plans/v0.1-interfaces.md section 3 (W-19 checks it against
# plugin/shared/adhd.md once that lands).
CHECKLIST = """\
## Pre-send checklist

Before every reply, check:

- [ ] The first line is the next action or the answer. No preamble, no pleasantries.
- [ ] Where we are is restated in one line (for example "Step 2 of 6").
- [ ] Steps are numbered, with one concrete time estimate.
- [ ] Lists have 5 items or fewer.
- [ ] No tangents: only what this step needs.
- [ ] Finished work is visible: name the file that was written.
- [ ] Errors are stated matter-of-fact: what failed, what happens next.
- [ ] It ends with one action that takes under 2 minutes.
- [ ] Voice: a working DJ talking to a DJ. Blunt, practical, no hype (shared/voice.md).
- [ ] Nothing was written to rekordbox, Spotify or audio files without a preview and an explicit yes.
"""
VOICE_LINE = (
    "**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply "
    "by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this "
    "file before each reply."
)
REQUIREMENTS_LINE = "**Requirements:** R-101, R-102, R-103, R-104, R-105, R-106, R-107, R-1406."
TIME = re.compile(
    r"\b(under|about|around) (a|an|one|two|\d+) (minute|minutes|hour|hours)\b", re.IGNORECASE
)
NUMBERED = re.compile(r"^(\d+)\. ", re.MULTILINE)


# -- running the script ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def start():
    spec = importlib.util.spec_from_file_location("dj_start_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _one_json(stdout: str, stderr: str = "") -> dict:
    lines = stdout.splitlines()
    assert len(lines) == 1, f"expected one JSON line, got {stdout!r} {stderr!r}"
    return json.loads(lines[0])


@pytest.fixture(params=["import", "subprocess"])
def run(request, start, capsys):
    """run(*args) -> (exit code, the JSON object), by import or as a subprocess."""

    def by_import(*args):
        code = start.main([str(a) for a in args])
        return code, _one_json(capsys.readouterr().out)

    def by_subprocess(*args):
        done = subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )  # fmt: skip
        return done.returncode, _one_json(done.stdout, done.stderr)

    return by_import if request.param == "import" else by_subprocess


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    root = tmp_path / "dj-library"
    root.mkdir()
    return root


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    """Every file under root (hidden ones too): relative path -> (bytes, mtime_ns)."""
    return {
        p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def init(run, root: Path, *extra, day: str = DAY):
    return run("init", "--library", root, "--device", "mac", "--today", day, *extra)


# -- init (R-103, R-104, R-904) ----------------------------------------------------------------


def test_init_scaffolds_copies_reads_and_logs(run, lib):
    original = fx.write_xml(lib / "collection.xml")
    before = (original.read_bytes(), original.stat().st_mtime_ns)

    code, out = init(run, lib)

    assert code == 0, out
    assert {"created", "skipped", "export", "rekordbox_version", "counts", "next"} <= set(out)
    for name in DIRS:
        assert (lib / name).is_dir(), name
    for name in FILES:
        assert (lib / name).is_file(), name
    assert out["created"] == [*DIRS, *FILES, EXPORT]
    assert out["skipped"] == []
    assert out["new_export"] is True and out["device_was"] is None

    meta = load_meta(lib)  # R-103: device, rekordbox version, date
    assert validate_meta(meta) == []
    assert meta["device"] == "mac" and out["device"] == "mac"
    assert meta["rekordbox_version"] == "7.2.18" == out["rekordbox_version"]
    assert meta["created"] == DAY
    assert meta["exports"]["latest"] == EXPORT

    assert out["export"] == EXPORT
    export = lib / EXPORT
    assert export.read_bytes() == before[0]  # a copy of the DJ's file ...
    assert not os.path.samefile(export, original)  # ... not a link to it
    assert original.is_file()  # the original stays where the DJ put it, untouched
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before
    assert out["source"] == "collection.xml"

    assert out["counts"] == read_xml(original).counts() == fx.EXPECTED_COUNTS
    assert out["counts"] == read_xml(export).counts()

    line = f"{DAY} {{hm}} start -> 14 created, 0 skipped, 24 tracks; {EXPORT}"
    pattern = re.escape(line).replace(re.escape("{hm}"), r"\d\d:\d\d")
    log_lines = (lib / "log.md").read_text(encoding="utf-8").splitlines()
    assert [ln for ln in log_lines if re.fullmatch(pattern, ln)] == [out["log"]]
    assert out["not_in_xml"]["fields"] and "my_tags" in out["not_in_xml"]["fields"]


def test_init_output_and_folder_hold_no_absolute_paths(run, lib, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    fx.write_xml(desktop / "collection.xml")

    code, out = init(run, lib, "--xml", desktop / "collection.xml")

    assert code == 0, out
    assert out["source"] == "collection.xml"  # outside the folder: the name only
    text = json.dumps(out)
    for absolute in (str(tmp_path), tmp_path.as_posix(), json.dumps(str(tmp_path))[1:-1]):
        assert absolute not in text
    for path in lib.rglob("*"):
        if path.is_file() and path.suffix != ".xml":  # exports/*.xml may hold paths (gitignored)
            body = path.read_text(encoding="utf-8")
            assert str(tmp_path) not in body and tmp_path.as_posix() not in body, path


def test_second_init_creates_nothing_and_overwrites_nothing(run, lib):
    fx.write_xml(lib / "collection.xml")
    assert init(run, lib)[0] == 0
    first = snapshot(lib)

    code, out = init(run, lib, day=NEXT_DAY)  # a later day: still no new dated copy

    assert code == 0, out
    assert out["created"] == []
    assert out["skipped"] == [*DIRS, *FILES, EXPORT]
    assert out["export"] == EXPORT and out["new_export"] is False
    assert out["log"] is None  # log.md holds one line per change; nothing changed
    assert snapshot(lib) == first  # same files, same bytes, same times


def _log_lines(root: Path) -> list[str]:
    return [ln for ln in (root / "log.md").read_text(encoding="utf-8").splitlines() if ln[:1].isdigit()]


def test_reimporting_an_older_export_rewrites_library_yaml_and_logs_it(run, lib, tmp_path):  # R-904
    """An XML identical to an older copy in exports/ copies nothing but makes that copy the
    latest again: library.yaml changes, so log.md gets a line."""
    fx.write_xml(lib / "a.xml")
    newer = dict(fx.SPEC, product=dict(fx.SPEC["product"], Version="7.2.19"))
    fx.write_xml(tmp_path / "b.xml", newer)
    assert init(run, lib, "--xml", lib / "a.xml")[0] == 0
    code, out = init(run, lib, "--xml", tmp_path / "b.xml", day=NEXT_DAY)
    assert code == 0 and out["new_export"] is True
    assert load_meta(lib)["exports"]["latest"] == f"exports/{NEXT_DAY}-collection.xml"
    before = _log_lines(lib)

    code, out = init(run, lib, "--xml", lib / "a.xml", day="2026-10-22")

    assert code == 0, out
    assert out["created"] == [] and out["new_export"] is False and out["export"] == EXPORT
    meta = load_meta(lib)
    assert meta["exports"]["latest"] == EXPORT and meta["rekordbox_version"] == "7.2.18"
    assert meta["updated"] == "2026-10-22"
    after = _log_lines(lib)
    assert after[: len(before)] == before and after[len(before) :] == [out["log"]]
    assert out["log"].startswith("2026-10-22 ") and out["log"].endswith(f"; {EXPORT}")


def test_the_device_given_last_wins_and_is_logged(run, lib):  # R-101, R-904
    fx.write_xml(lib / "collection.xml")
    assert init(run, lib)[0] == 0  # mac
    before = _log_lines(lib)

    code, out = run("init", "--library", lib, "--device", "windows", "--today", NEXT_DAY)

    assert code == 0, out
    assert out["device"] == "windows" and out["device_was"] == "mac"
    meta = load_meta(lib)
    assert meta["device"] == "windows" and meta["updated"] == NEXT_DAY and validate_meta(meta) == []
    assert out["created"] == []
    assert _log_lines(lib) == [*before, out["log"]]
    assert " start, device now windows -> 0 created, 14 skipped, 24 tracks; " in out["log"]

    code, out = run("init", "--library", lib, "--device", "windows", "--today", NEXT_DAY)
    assert code == 0 and out["device_was"] is None and out["log"] is None  # same device: no change


def test_init_takes_the_xml_from_find_xml(run, lib):
    fx.write_xml(lib / "old.xml")
    os.utime(lib / "old.xml", (1_700_000_000, 1_700_000_000))
    (lib / "drop").mkdir()
    fx.write_xml(lib / "drop" / "collection.xml")
    os.utime(lib / "drop" / "collection.xml", (1_700_000_100, 1_700_000_100))

    code, out = init(run, lib)

    assert code == 0, out
    assert out["source"] == "drop/collection.xml"
    assert (lib / "old.xml").is_file() and (lib / "drop" / "collection.xml").is_file()


def test_relative_xml_is_looked_up_in_the_library_first(run, lib, tmp_path, monkeypatch):
    (lib / "drop").mkdir()
    fx.write_xml(lib / "drop" / "collection.xml")
    monkeypatch.chdir(tmp_path)  # tmp_path/drop/collection.xml does not exist

    code, out = init(run, lib, "--xml", "drop/collection.xml")

    assert code == 0, out
    assert out["source"] == "drop/collection.xml"
    assert out["export"] == EXPORT


def test_device_is_case_insensitive_and_recorded(run, lib):
    fx.write_xml(lib / "collection.xml")
    code, out = run("init", "--library", lib, "--device", "Windows", "--today", DAY)
    assert code == 0, out
    assert load_meta(lib)["device"] == "windows" == out["device"]


# -- find-xml ----------------------------------------------------------------------------------


def _xml_at(root: Path, rel: str, mtime: int) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fx.write_xml(path)
    os.utime(path, (mtime, mtime))
    return path


def test_find_xml_picks_the_newest_and_ignores_tool_and_hidden_folders(run, lib):
    t = 1_700_000_000
    _xml_at(lib, "old.xml", t)
    _xml_at(lib, "sub/new.xml", t + 100)
    _xml_at(lib, "exports/2026-10-01-collection.xml", t + 300)  # the tool's own copy
    _xml_at(lib, "proposals/house.xml", t + 400)  # the tool's output
    _xml_at(lib, ".cache/x.xml", t + 500)  # hidden folder
    _xml_at(lib, "._new.xml", t + 600)  # macOS resource file
    _xml_at(lib, "a/b/c/d/too-deep.xml", t + 700)  # deeper than MAX_DEPTH
    notes = lib / "notes.xml"
    notes.write_text("<notes><n>not an export</n></notes>\n", encoding="utf-8")
    os.utime(notes, (t + 800, t + 800))

    code, out = run("find-xml", "--library", lib)

    assert code == 0, out
    assert out == {
        "found": 2,
        "xml": "sub/new.xml",
        "candidates": ["sub/new.xml", "old.xml"],
        "library": None,  # not set up yet
    }


def test_find_xml_skips_tool_folders_in_any_letter_case(run, lib):
    """A case-insensitive disk treats Proposals/ as the tool's proposals/ (scaffold skips it as
    existing), so find-xml must not offer the tool's own XML from it as the collection."""
    t = 1_700_000_000
    _xml_at(lib, "collection.xml", t)
    _xml_at(lib, "Proposals/house.xml", t + 100)
    _xml_at(lib, "EXPORTS/2026-10-01-collection.xml", t + 200)

    code, out = run("find-xml", "--library", lib)

    assert code == 0, out
    assert out["xml"] == "collection.xml" and out["candidates"] == ["collection.xml"]


def _tool_xml(path: Path, mtime: int) -> Path:
    """An XML this tool writes (contract section 6): PRODUCT dj-librarian, referenced tracks only."""
    spec = dict(fx.SPEC, product={"Name": "dj-librarian", "Version": "0.1.0", "Company": "dj-librarian"})
    fx.write_xml(path, spec)
    os.utime(path, (mtime, mtime))
    return path


def test_find_xml_and_init_skip_xml_another_program_wrote(run, lib):
    t = 1_700_000_000
    _xml_at(lib, "collection.xml", t)
    _tool_xml(lib / "house.xml", t + 100)  # newest, moved out of proposals/ by the DJ

    code, out = run("find-xml", "--library", lib)
    assert code == 0 and out["xml"] == "collection.xml" and out["found"] == 1

    code, out = init(run, lib, "--xml", "house.xml")
    assert code == 1 and out["reason"] == "xml", out
    assert "dj-librarian" in out["error"] and "not exported by rekordbox" in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == ["collection.xml", "house.xml"]

    code, out = init(run, lib)  # without --xml: the rekordbox export, not the newer tool file
    assert code == 0 and out["source"] == "collection.xml"


def test_init_refuses_an_export_without_tracks(run, lib):
    fx.write_xml(lib / "collection.xml", dict(fx.SPEC, tracks=[], tree=[]))

    code, out = init(run, lib)

    assert code == 1 and out["reason"] == "xml", out
    assert "holds no tracks" in out["error"] and "\n" not in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == ["collection.xml"]


def test_find_xml_reports_a_set_up_folder(run, lib):
    fx.write_xml(lib / "collection.xml")
    assert init(run, lib)[0] == 0
    code, out = run("find-xml", "--library", lib)
    assert code == 0, out
    assert out["library"] == {"device": "mac", "dj_name": None, "latest_export": EXPORT, "latest_report": None}

    (lib / "reports" / f"{DAY}-library.html").write_text("<html></html>\n", encoding="utf-8")
    (lib / "reports" / "2026-09-01-library.html").write_text("<html></html>\n", encoding="utf-8")
    code, out = run("find-xml", "--library", lib)
    assert out["library"]["latest_report"] == f"reports/{DAY}-library.html"

    for name in (f"{DAY}-library-2.html", f"{DAY}-library-10.html", "2026-09-01-library-30.html", "notes.html"):
        (lib / "reports" / name).write_text("<html></html>\n", encoding="utf-8")  # dj-report's -N names
    code, out = run("find-xml", "--library", lib)
    assert out["library"]["latest_report"] == f"reports/{DAY}-library-10.html"  # -10 after -2


@pytest.mark.parametrize(("names", "want"), [
    ([], None),
    (["2026-10-20-library.html", "2026-10-20-library-2.html"], "2026-10-20-library-2.html"),
    (["2026-10-20-library-9.html", "2026-10-20-library-10.html"], "2026-10-20-library-10.html"),
    (["2026-10-21-library.html", "2026-10-20-library-7.html"], "2026-10-21-library.html"),
    (["2026-10-20-library-0.html", "x-library.html", "2026-10-20-library.htm"], None),
])  # fmt: skip
def test_newest_report(names, want):
    found = onboarding.newest_report(Path("reports") / n for n in names)
    assert (found.name if found else None) == want


def test_find_xml_reaches_max_depth(run, lib):
    assert onboarding.MAX_DEPTH == 3
    _xml_at(lib, "a/b/c/deep.xml", 1_700_000_000)
    code, out = run("find-xml", "--library", lib)
    assert code == 0 and out["xml"] == "a/b/c/deep.xml"


def test_find_xml_shows_at_most_5_newest_first_ties_by_path(run, lib):
    t = 1_700_000_000
    for i in range(7):
        _xml_at(lib, f"export-{i}.xml", t + i * 10)
    _xml_at(lib, "b-tie.xml", t + 1000)
    _xml_at(lib, "a-tie.xml", t + 1000)

    code, out = run("find-xml", "--library", lib)

    assert code == 0, out
    assert out["found"] == 9
    assert out["candidates"] == ["a-tie.xml", "b-tie.xml", "export-6.xml", "export-5.xml", "export-4.xml"]
    assert out["xml"] == "a-tie.xml"


def test_find_xml_with_nothing_there(run, lib):
    code, out = run("find-xml", "--library", lib)
    assert code == 0
    assert out == {"found": 0, "xml": None, "candidates": [], "library": None}


def test_find_xml_on_a_missing_folder_is_an_error(run, tmp_path):
    code, out = run("find-xml", "--library", tmp_path / "nowhere")
    assert code == 1 and out["reason"] == "folder" and "\n" not in out["error"]


# -- errors and refusals -----------------------------------------------------------------------


def test_no_xml_exits_1_with_one_line_and_creates_nothing(run, lib):
    (lib / "notes.xml").write_text("<notes/>\n", encoding="utf-8")  # not a rekordbox export

    code, out = init(run, lib)

    assert code == 1
    assert out == {"error": onboarding.NO_XML, "reason": "no_xml"}
    assert out["error"].startswith("No rekordbox XML") and "\n" not in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == ["notes.xml"]


def test_bad_device_exits_1_and_creates_nothing(run, lib):
    fx.write_xml(lib / "collection.xml")
    code, out = run("init", "--library", lib, "--device", "linux", "--today", DAY)
    assert code == 1 and out["reason"] == "usage"
    assert "device" in out["error"] and "\n" not in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == ["collection.xml"]


def test_a_foreign_library_yaml_exits_1_and_creates_nothing(run, lib):
    (lib / "library.yaml").write_text("my: own settings\n", encoding="utf-8")
    fx.write_xml(lib / "c.xml")

    for command in (("find-xml", "--library", lib), ("init", "--library", lib, "--device", "mac")):
        code, out = run(*command)
        assert code == 1 and out["reason"] == "folder", out
        assert "library.yaml" in out["error"] and "Nothing was created" in out["error"]
        assert "\n" not in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == ["c.xml", "library.yaml"]
    assert (lib / "library.yaml").read_text(encoding="utf-8") == "my: own settings\n"


def test_a_file_where_a_tool_folder_goes_exits_1_and_creates_nothing(run, lib):
    fx.write_xml(lib / "collection.xml")
    (lib / "reports").write_text("my notes\n", encoding="utf-8")

    code, out = init(run, lib)

    assert code == 1 and out["reason"] == "folder", out
    assert "reports" in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == ["collection.xml", "reports"]


def test_an_empty_library_argument_is_refused(run, tmp_path, monkeypatch):
    """An unfilled <folder> would resolve to the current folder: nothing is created there."""
    fx.write_xml(tmp_path / "c.xml")
    monkeypatch.chdir(tmp_path)
    for blank in ("", "  "):
        for command in (("find-xml",), ("init", "--device", "mac")):
            code, out = run(command[0], "--library", blank, *command[1:])
            assert code == 1 and out["reason"] == "usage", out
            assert "--library" in out["error"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c.xml"]


@pytest.mark.parametrize("name", ["Desktop", "Documents", "downloads", "Music"])
def test_a_user_folder_is_refused_with_exit_2(run, tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    fx.write_xml(folder / "collection.xml")

    for command in (("find-xml", "--library", folder), ("init", "--library", folder, "--device", "mac")):
        code, out = run(*command)
        assert code == 2 and out["reason"] == "refused", out
        assert name in out["error"] and "Nothing was created" in out["error"]
    assert sorted(p.name for p in folder.iterdir()) == ["collection.xml"]


def test_a_busy_folder_is_refused_with_exit_2(run, lib):
    fx.write_xml(lib / "collection.xml")
    for i in range(onboarding.CROWDED):  # up to CROWDED entries of the DJ's own: fine
        (lib / f"note-{i}.txt").write_text("x\n", encoding="utf-8")
    (lib / ".hidden").mkdir()  # hidden entries and XML do not count
    fx.write_xml(lib / "other.xml")
    assert run("find-xml", "--library", lib)[0] == 0

    (lib / "one-more").mkdir()
    before = sorted(p.name for p in lib.iterdir())
    code, out = init(run, lib)

    assert code == 2 and out["reason"] == "refused", out
    assert f"holds {onboarding.CROWDED + 1} files and folders" in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == before


def test_a_set_up_folder_is_never_refused_as_busy(run, lib):
    fx.write_xml(lib / "collection.xml")
    assert init(run, lib)[0] == 0
    for i in range(onboarding.CROWDED + 5):
        (lib / f"set-{i}.txt").write_text("x\n", encoding="utf-8")
    code, out = init(run, lib)
    assert code == 0 and out["created"] == [], out


def test_the_plugin_folder_and_folders_holding_it_are_refused(run):
    """Read-only find-xml on the plugin and the repo: the same check guards init."""
    for folder in (SKILL_DIR, REPO / "plugin", REPO):
        code, out = run("find-xml", "--library", folder)
        assert code == 2 and out["reason"] == "refused", (folder, out)
        assert "plugin" in out["error"]


def test_library_root_keep_out(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "skills").mkdir(parents=True)
    for folder in (plugin, plugin / "skills", tmp_path):
        with pytest.raises(onboarding.OnboardingError) as caught:
            onboarding.library_root(folder, keep_out=[plugin])
        assert caught.value.code == 2 and caught.value.reason == "refused"
    beside = tmp_path / "dj-library"
    assert onboarding.library_root(beside, keep_out=[plugin]) == beside.resolve()


def test_missing_device_and_bad_date_exit_1(run, lib):
    fx.write_xml(lib / "collection.xml")
    code, out = run("init", "--library", lib)
    assert code == 1 and "--device" in out["error"]
    code, out = run("init", "--library", lib, "--device", "mac", "--today", "20-10-2026")
    assert code == 1 and "YYYY-MM-DD" in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == ["collection.xml"]


def test_a_broken_export_exits_1_and_creates_nothing(run, lib):
    text = fx.to_xml()
    (lib / "collection.xml").write_text(text[: len(text) // 2], encoding="utf-8")  # cut mid-export

    code, out = init(run, lib)

    assert code == 1
    assert "not readable XML" in out["error"] and "\n" not in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == ["collection.xml"]


def test_missing_xml_file_exits_1(run, lib):
    code, out = init(run, lib, "--xml", "nope.xml")
    assert code == 1 and "nope.xml" in out["error"]
    assert list(lib.iterdir()) == []


def test_home_folder_or_above_is_refused_with_exit_2(run, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    fx.write_xml(home / "collection.xml")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    for root in (home, tmp_path):
        code, out = init(run, root, "--xml", home / "collection.xml")
        assert code == 2, out
        assert "home folder" in out["error"]
    assert sorted(p.name for p in home.iterdir()) == ["collection.xml"]


# -- runs where the plugin runs ------------------------------------------------------------------


def test_script_runs_without_engine_packages(tmp_path):
    """Door 1: start.py runs in Cowork's sandbox, without pyrekordbox, rapidfuzz, httpx, typer, mcp."""
    root = tmp_path / "lib"
    root.mkdir()
    fx.write_xml(root / "collection.xml")
    argv = [str(SCRIPT), "init", "--library", str(root), "--device", "mac", "--today", DAY]
    done = run_blocked(f"""
        import json, runpy
        sys.argv = {argv!r}
        try:
            runpy.run_path({str(SCRIPT)!r}, run_name="__main__")
        except SystemExit as exc:
            code = exc.code
        leaked = [n for n in {BLOCKED!r} if sys.modules.get(n) is not None]
        print(json.dumps({{"code": code, "leaked": leaked}}))
    """)
    assert done.returncode == 0, done.stderr
    result, status = (json.loads(line) for line in done.stdout.splitlines())
    assert status == {"code": 0, "leaked": []}
    assert result["counts"] == fx.EXPECTED_COUNTS


def test_import_shim_finds_src_when_dj_is_not_installed(tmp_path):
    """Without site-packages processing (-S) `import dj` fails; the shim adds the repo's src/."""
    site = Path(yaml.__file__).resolve().parents[1]
    if (site / "dj").exists():
        pytest.skip("dj is installed as a package here; the shim branch is not reachable")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(site)  # PyYAML only: .pth files there are not processed
    probe = subprocess.run([sys.executable, "-S", "-c", "import dj"], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=120)
    assert probe.returncode != 0, "dj is importable without the shim"

    root = tmp_path / "lib"
    root.mkdir()
    fx.write_xml(root / "collection.xml")
    done = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), "init", "--library", str(root), "--device", "mac",
         "--today", DAY],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert _one_json(done.stdout, done.stderr)["counts"] == fx.EXPECTED_COUNTS


def test_without_the_core_the_script_still_prints_one_json_object(tmp_path):
    """Installed from the marketplace without the dj core (Q-06): no traceback, one JSON error."""
    site = Path(yaml.__file__).resolve().parents[1]
    if (site / "dj").exists():
        pytest.skip("dj is installed as a package here; the missing-core branch is not reachable")
    cached = tmp_path / "cache" / "dj-librarian" / "0.1.0" / "skills" / "dj-start" / "scripts"
    cached.mkdir(parents=True)
    script = cached / "start.py"
    script.write_bytes(SCRIPT.read_bytes())
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(site)  # PyYAML only, no dj: neither installed nor a clone of the repo
    root = tmp_path / "lib"
    root.mkdir()

    for command in (["find-xml", "--library", str(root)],
                    ["init", "--library", str(root), "--device", "mac"]):
        done = subprocess.run([sys.executable, "-S", str(script), *command], cwd=tmp_path, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert done.returncode == 1, done.stderr
        assert "Traceback" not in done.stderr
        out = _one_json(done.stdout, done.stderr)
        assert out["reason"] == "core" and "dj-librarian core" in out["error"]
        assert "\n" not in out["error"]
    assert list(root.iterdir()) == []


def test_the_script_is_thin():
    """Contract section 0: argument parsing + a call into dj.*. The rules live in dj.onboarding."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "from dj import onboarding" in text
    for logic in ("os.walk", "import_export", "scaffold(", "append_log", "read_xml", "_library_root"):
        assert logic not in text, logic


# -- R-104 acceptance: analysis + report on the XML alone ------------------------------------------

STEP4_SCRIPT = re.compile(r"`python3 (\.\./dj-[\w-]+/scripts/[\w-]+\.py) --library <folder>`")


def _run_script_blocked(path: Path, *args: str) -> tuple[int, dict]:
    """Run a skill script as Cowork's sandbox would: pyrekordbox, rapidfuzz, httpx, typer and
    mcp cannot be imported. Returns (exit code, its one JSON object); fails if one leaked in."""
    argv = [str(path), *map(str, args)]
    done = run_blocked(f"""
        import json, runpy
        sys.argv = {argv!r}
        code = 0
        try:
            runpy.run_path({str(path)!r}, run_name="__main__")
        except SystemExit as exc:
            code = exc.code or 0
        leaked = [n for n in {BLOCKED!r} if sys.modules.get(n) is not None]
        print(json.dumps({{"code": code, "leaked": leaked}}))
    """)
    assert done.returncode == 0, done.stderr
    *out, status = done.stdout.splitlines()
    status = json.loads(status)
    assert status["leaked"] == [], (path.name, status)
    assert len(out) == 1, (path.name, done.stdout, done.stderr)
    return status["code"], json.loads(out[0])


def test_analysis_and_report_run_on_the_xml_alone(tmp_path):
    """R-104: init on the synthetic export, then every step 4 script exactly as SKILL.md names it,
    each with --library only and the engine packages blocked: the HTML report exists, with its
    four sections and the proposals. No master.db, no engine, no network."""
    scripts = STEP4_SCRIPT.findall(_step(4))
    assert [Path(s).parts[1] for s in scripts] == ["dj-profile", "dj-structure", "dj-taste", "dj-identity", "dj-report"]

    lib = tmp_path / "dj-library"
    lib.mkdir()
    fx.write_xml(lib / "collection.xml")
    code, out = _run_script_blocked(SCRIPT, "init", "--library", lib, "--device", "mac")
    assert code == 0 and out["counts"] == fx.EXPECTED_COUNTS, out
    results = {}
    for script in scripts:
        code, out = _run_script_blocked((SKILL_DIR / script).resolve(), "--library", lib)
        assert code == 0 and out["ok"] is True, (script, out)
        results[Path(script).parts[1]] = out
    reports = list((lib / "reports").glob("*-library.html"))
    assert len(reports) == 1
    assert results["dj-report"]["report"] == f"reports/{reports[0].name}"
    page = reports[0].read_text(encoding="utf-8")
    for section in ("who", "structure", "proposals", "next"):
        assert f'<section id="{section}">' in page
    assert "http://" not in page and "https://" not in page
    triggers = [p["trigger"] for p in results["dj-report"]["proposals"]]
    assert 2 <= len(triggers) <= 3 and all(t in page for t in triggers)
    assert (lib / "structure" / "proposals.yaml").is_file()


# -- SKILL.md ----------------------------------------------------------------------------------


def _text() -> str:
    return SKILL.read_text(encoding="utf-8").replace("\r\n", "\n")


def _frontmatter() -> tuple[dict, str]:
    m = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", _text(), re.DOTALL)
    assert m, "SKILL.md starts with a YAML frontmatter block"
    return yaml.safe_load(m.group(1)), m.group(2)


def _section(level: str, title: str) -> str:
    """The body under the heading `<level> <title>...` up to the next heading of that level or higher."""
    body = _frontmatter()[1]
    stop = "|".join(re.escape("#" * n + " ") for n in range(1, len(level) + 1))
    m = re.search(rf"^{re.escape(level)} {re.escape(title)}.*?\n(.*?)(?=^(?:{stop})|\Z)", body,
                  re.MULTILINE | re.DOTALL)
    assert m, f"no section {level} {title}"
    return m.group(1)


def _step(n: int) -> str:
    return _section("###", f"Step {n}:")


def _templates(section: str) -> list[str]:
    return re.findall(r"```text\n(.*?)\n```", section, re.DOTALL)


def _lines(block: str) -> list[str]:
    return [line for line in block.split("\n") if line.strip()]


def test_frontmatter_names_the_skill_and_its_triggers():
    meta, _ = _frontmatter()
    assert meta["name"] == SKILL_DIR.name == "dj-start"
    description = meta["description"]
    for trigger in ("hello", "sort my library", '"start"', "analyse my library"):
        assert trigger in description, trigger
    assert "engine" not in description.lower()


def test_header_lines_voice_and_requirements():
    _, body = _frontmatter()
    top = body.split("\n## ")[0]  # before the first section
    assert VOICE_LINE in top.split("\n")
    assert REQUIREMENTS_LINE in top.split("\n")
    for ref in ("../../shared/voice.md", "../../shared/adhd.md"):
        assert ref in top


def test_ends_with_the_canonical_checklist():
    text = _text()
    last = text[[m.start() for m in re.finditer(r"^## ", text, re.MULTILINE)][-1] :]
    assert last.rstrip("\n") == CHECKLIST.rstrip("\n")


def test_your_moves_are_exactly_three_dj_actions():  # R-106, NFR-07
    moves = _section("##", "Your moves")
    items = NUMBERED.findall(moves)
    assert items == ["1", "2", "3"]
    text = moves.lower()
    assert "mac or windows" in text and "export" in text and "xml" in text
    assert "connect a folder" in text and "drop the xml" in text


def test_six_steps_in_order():
    _, body = _frontmatter()
    heads = re.findall(r"^### Step (\d+): ", body, re.MULTILINE)
    assert heads == ["1", "2", "3", "4", "5", "6"]


@pytest.mark.parametrize("n", range(1, 7))
def test_every_reply_template_has_counter_and_time(n):  # R-105
    templates = _templates(_step(n))
    assert templates, f"step {n} has no reply template"
    for block in templates:
        first = _lines(block)[0]
        assert first.startswith(f"Step {n} of 6 · "), first
        assert TIME.search(first), f"step {n}: no time estimate in {first!r}"
        assert len(NUMBERED.findall(block)) <= 5  # lists of 5 or fewer


@pytest.mark.parametrize("n", range(1, 6))
def test_chat_stays_under_5_lines_until_the_report(n):  # R-106
    for block in _templates(_step(n)):
        assert len(_lines(block)) < 5, block


def test_step_1_asks_mac_or_windows_as_two_options():  # R-101, Q-05
    step = _step(1)
    assert "two chips" in step and "**Mac**" in step and "**Windows**" in step
    templates = _templates(step)
    assert len(templates) == 2
    assert all("Mac or Windows?" in block for block in templates)
    chips, numbered = templates
    assert NUMBERED.findall(chips) == []
    assert re.findall(r"^\d+\. (.+)$", numbered, re.MULTILINE) == ["Mac", "Windows"]
    assert "only that OS" in step


def test_step_2_has_one_export_card_per_os_and_shows_only_one():  # R-101, R-104
    step = _step(2)
    assert re.search(r"Show only the block for the DJ's device,\s+never both", step)
    blocks = re.findall(r"^(Mac|Windows):\n\n```text\n(.*?)\n```", step, re.MULTILINE | re.DOTALL)
    assert [os_name for os_name, _ in blocks] == ["Mac", "Windows"]
    for os_name, block in blocks:
        other = "Windows" if os_name == "Mac" else "Mac"
        assert other not in block, f"the {os_name} card mentions {other}"
        assert NUMBERED.findall(block) == ["1", "2", "3"]
        assert "Export Collection in xml format" in block
        assert "about 2 minutes" in _lines(block)[0]
        assert "Save" in block
    assert blocks[0][1] != blocks[1][1]


def test_later_steps_show_no_os_names():  # R-101: from step 3 on, only the DJ's OS
    for n in range(3, 7):
        for block in _templates(_step(n)):
            assert "Mac" not in block and "Windows" not in block, block


def test_step_3_runs_find_xml_then_init_and_keeps_the_original():  # R-103
    step = _step(3)
    find = step.index("scripts/start.py find-xml --library <folder>")
    init_at = step.index("scripts/start.py init --library <folder> --device <mac|windows>")
    assert find < init_at
    assert "original stays where the DJ put it" in step
    assert "library.yaml" in step and "log.md" in step
    done = [b for b in _templates(step) if "Created <n>" in b]
    assert len(done) == 1 and len(_lines(done[0])) == 1  # what was created, in one line


def test_skill_commands_parse_with_the_script(start):
    """Every `start.py` command line in SKILL.md is one the script accepts."""
    commands = re.findall(r"`python3 (scripts/start\.py (?:init|find-xml) [^`]+)`", _text())
    assert len(commands) == 2
    fill = {"<folder>": "dj-library", "<mac|windows>": "mac", "<xml>": "collection.xml", '"<name>"': "Selector"}
    for command in commands:
        for placeholder, value in fill.items():
            command = command.replace(placeholder, value)
        args = start._parser().parse_args(command.split()[1:])
        assert args.run in (start.cmd_find_xml, start.cmd_init)


def test_step_4_runs_the_analysis_in_order_without_questions():  # R-106, NFR-07
    step = _step(4)
    assert "?" not in step
    assert "Go make a coffee" in step and "about 5 minutes" in step
    tasks = re.findall(r"^\d+\. (\w[\w ]*?):", step, re.MULTILINE)
    assert tasks == ["Profile", "Structure", "Taste", "Identity", "Report"]  # the task list stays at 5
    order = [
        "../dj-profile/scripts/profile.py --library <folder>",
        "../dj-structure/scripts/structure.py --library <folder>",
        "../dj-taste/scripts/taste.py --library <folder>",
        "../dj-identity/scripts/identity.py --library <folder>",
        "profile/habits.md",
        "profile/identity.md",
        "../dj-report/scripts/report.py --library <folder>",
    ]
    positions = [step.index(item) for item in order]
    assert positions == sorted(positions)
    assert "../dj-profile/SKILL.md" in step and "../dj-identity/SKILL.md" in step
    assert "keep its one-line error for step 6" in step


def test_step_5_delivers_the_report_without_questions():  # R-106
    step = _step(5)
    assert "?" not in step
    assert "reports/<date>-library.html" in step and "file card" in step


def test_steps_5_and_6_go_out_as_one_reply():
    """The reply with the report ends with step 6's action under 2 minutes; the DJ never has to
    write to see it (pre-send checklist: it ends with one action that takes under 2 minutes)."""
    assert re.search(r"Step 6 goes out in the same\s+reply", _step(5))
    assert "Sent in the same reply as step 5" in _step(6)
    for block in _templates(_step(6)):
        assert TIME.search(_lines(block)[0])


ENGINE_OFFER = "To add it: in the Code tab type /dj-librarian:install and click Allow, then say set me up."


def test_step_6_never_promises_play_history_from_the_engine():  # Q-13: DjmdHistory is not read
    step = _step(6)
    offers = [ln for b in _templates(step) for ln in _lines(b) if "/dj-librarian:install" in ln]
    assert len(offers) == 2
    for line in offers:
        assert "the engine reads your My Tags" in line
        assert not re.search(r"engine reads[^.;]*history", line), line
        assert line.endswith(ENGINE_OFFER)
        assert _lines(next(b for b in _templates(step) if line in b))[-1] == line  # the last line
    assert "never promise" in step


def test_step_6_offers_the_install_command():  # W-35, D-29
    """The engine installs from Claude Code: the offer names the command and set me up, no
    terminal and no install time; engine.md holds the card."""
    step = _step(6)
    assert "Install the engine" not in step and "about 10 minutes" not in step
    prose = " ".join(step.split())
    assert "with /dj-librarian:install (D-29)" in prose and "engine.md has the card" in prose


def test_already_set_up_covers_every_case():  # R-101 device from library.yaml; a new export
    text = _section("##", "How to run the scripts")
    rule = text[text.index("Already set up") :]
    assert "find-xml" in rule and "init" in rule and "library.device" in rule and "skip step 1" in rule
    branches = re.findall(r"^- (.+?): step (\d)", rule, re.MULTILINE | re.DOTALL)
    assert [n for _, n in branches] == ["2", "4", "6"]
    assert "new_export" in rule and "library.latest_report" in rule and "library.latest_export" in rule
    assert any("No new export since your last report" in b for b in _templates(_step(6)))
    assert "Already set up" in _step(3)  # a folder set up earlier, connected only at step 3


def test_step_3_has_a_reply_for_every_error_reason():  # matter-of-fact, with the next action
    step = _step(3)
    for reason in (*onboarding.REASONS, "core", "disk", "internal"):
        assert f"`{reason}`" in step, reason
    replies = [b for b in _templates(step) if "<error>" in b]
    assert len(replies) == 4
    assert len({_lines(b)[0].split("<error>")[1] for b in replies}) == 4  # each its own next action
    assert sum("Export it again (step 2)" in b for b in replies) == 1  # only the XML problem
    assert "device_was" in step


def test_the_engine_is_offered_only_in_step_6():  # R-102
    text, step = _text().lower(), _step(6).lower()
    for phrase in ("engine", "set me up"):
        assert step.count(phrase) > 0, phrase
        assert text.count(phrase) == step.count(phrase), f"{phrase!r} appears outside step 6"
    assert ENGINE_OFFER in _step(6)


def test_step_6_offers_the_proposals_and_says_what_was_missing():  # R-102, Q-01
    step = _step(6)
    assert "Build me the <name> structure" in step and "not yet" in step
    assert "My Tags" in step and "play history" in step
    assert "one action under 2 minutes" in step
    numbered = re.findall(r"^\d+\. (.+)$", _templates(step)[1], re.MULTILINE)
    assert numbered[-1] == "Not yet" and len(numbered) == 4


def test_rules_section():  # R-105, R-106
    rules = _section("##", "Rules")
    assert len(re.findall(r"^- ", rules, re.MULTILINE)) <= 5
    for phrase in (
        "At most 3 DJ actions before the work phase",
        "No questions between step 3 and step 5",
        "under 5 lines",
        "step counter and a time estimate",
        "matter-of-fact",
    ):
        assert phrase in rules, phrase


def test_project_template_is_optional():  # R-107
    lines = [line for line in _text().split("\n") if "templates/project/instructions.md" in line]
    assert lines and all("optional" in line for line in lines)
    assert any("nothing in this skill depends on it" in line for line in lines)
