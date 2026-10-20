"""How dj-identity reaches the rest (W-31): the DJ's handle in library.yaml and dj-start
(R-1406), the archetype line in Style Barber (R-1405), identity inside `dj library analyze`.
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import date
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml

from dj import barber, libfolder
from dj import mcp_server as m
from dj.analysis import identity, run_all
from dj.libfolder import LibraryFolderError, load_meta, update_meta, validate_meta

REPO = Path(__file__).resolve().parents[1]
START = REPO / "plugin" / "skills" / "dj-start"
DAY = date(2026, 10, 20)
D1, D2 = date(2026, 10, 21), date(2026, 10, 22)


@pytest.fixture(scope="module")
def start():
    spec = importlib.util.spec_from_file_location("dj_start_script_w31", START / "scripts" / "start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init(start, capsys, *args) -> tuple[int, dict]:
    code = start.main([str(a) for a in args])
    return code, json.loads(capsys.readouterr().out.strip())


# -- library.yaml dj_name (R-1406) ------------------------------------------------------------


def test_scaffold_writes_dj_name_when_given_and_older_files_stay_valid(tmp_path):
    named, plain = tmp_path / "named", tmp_path / "plain"
    libfolder.scaffold(named, device="mac", today=DAY, dj_name="  Selector   Okoro ")
    libfolder.scaffold(plain, device="mac", today=DAY)
    meta = load_meta(named)
    assert meta["dj_name"] == "Selector Okoro" and list(meta)[-1] == "dj_name"
    assert validate_meta(meta) == []
    assert "dj_name" not in load_meta(plain) and validate_meta(load_meta(plain)) == []  # an older file


@pytest.mark.parametrize("value", ["two\nlines", "x" * 41, 7, "", "bell\x07"])
def test_validate_meta_rejects_a_bad_dj_name(tmp_path, value):
    libfolder.scaffold(tmp_path / "lib", device="mac", today=DAY)
    meta = load_meta(tmp_path / "lib")
    meta["dj_name"] = value
    assert any("dj_name" in e for e in validate_meta(meta)), value


def test_update_meta_sets_and_clears_dj_name(tmp_path):
    root = tmp_path / "lib"
    libfolder.scaffold(root, device="windows", today=DAY)
    assert update_meta(root, today=D1, dj_name="Marlo")["dj_name"] == "Marlo"
    assert update_meta(root, today=D1, dj_name=None)["dj_name"] is None
    assert validate_meta(load_meta(root)) == []
    with pytest.raises(LibraryFolderError, match="dj_name"):
        update_meta(root, today=D1, dj_name="x" * 50)


def test_init_records_the_handle(start, capsys, tmp_path):
    lib = tmp_path / "dj-library"
    lib.mkdir()
    fx.write_xml(lib / "collection.xml")
    code, out = _init(start, capsys, "init", "--library", lib, "--device", "mac", "--today", "2026-10-20",
                      "--dj-name", "Jørn Ébène")  # fmt: skip
    assert code == 0, out
    assert out["dj_name"] == "Jørn Ébène" == load_meta(lib)["dj_name"]
    # a later init without a name keeps it; with another name changes it and logs the change
    code, out = _init(start, capsys, "init", "--library", lib, "--device", "mac", "--today", "2026-10-21")
    assert code == 0 and out["dj_name"] == "Jørn Ébène" and out["log"] is None
    code, out = _init(start, capsys, "init", "--library", lib, "--device", "mac", "--today", "2026-10-21",
                      "--dj-name", "Okoro")  # fmt: skip
    assert code == 0 and out["dj_name"] == "Okoro" and out["log"].startswith("2026-10-21 ")


def test_init_without_a_name_writes_none_and_a_bad_name_creates_nothing(start, capsys, tmp_path):
    lib = tmp_path / "dj-library"
    lib.mkdir()
    fx.write_xml(lib / "collection.xml")
    code, out = _init(start, capsys, "init", "--library", lib, "--device", "mac", "--dj-name", "x" * 41)
    assert code == 1 and out["reason"] == "usage" and "--dj-name" in out["error"]
    assert sorted(p.name for p in lib.iterdir()) == ["collection.xml"]
    code, out = _init(start, capsys, "init", "--library", lib, "--device", "mac")
    assert code == 0 and out["dj_name"] is None and "dj_name" not in load_meta(lib)


def test_the_handle_reaches_the_sleeve_through_analyze(tmp_path):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac", today=DAY, dj_name="Selector Okoro")
    libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=DAY)
    run_all.analyze(root, today=DAY)
    data = json.loads((root / identity.IDENTITY_JSON).read_text(encoding="utf-8"))
    assert data["handle"] == "Selector Okoro"
    assert ">Selector Okoro</text>" in (root / identity.SLEEVE_SVG).read_text(encoding="utf-8")


# -- dj-start SKILL.md ------------------------------------------------------------------------


def _start_md() -> str:
    return (START / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_step_1_asks_the_handle_with_the_device():
    text = _start_md()
    step1 = re.search(r"^### Step 1:.*?(?=^### Step 2:)", text, re.MULTILINE | re.DOTALL).group(0)
    templates = re.findall(r"```text\n(.*?)\n```", step1, re.DOTALL)
    assert len(templates) == 2
    for block in templates:
        assert "Mac or Windows?" in block and "What do they call you in the booth?" in block
    assert "You" in step1 and "--dj-name" in step1 and "optional" in step1
    assert '--dj-name "<name>"' in re.search(r"^### Step 3:.*?(?=^### Step 4:)", text, re.MULTILINE | re.DOTALL).group(0)
    moves = re.search(r"^## Your moves.*?(?=^## )", text, re.MULTILINE | re.DOTALL).group(0)
    assert "in the booth" in moves and len(re.findall(r"^\d+\. ", moves, re.MULTILINE)) == 3


def test_step_4_runs_identity_after_taste_and_claude_writes_the_liner_notes():
    step4 = re.search(r"^### Step 4:.*?(?=^### Step 5:)", _start_md(), re.MULTILINE | re.DOTALL).group(0)
    order = ["taste.py", "identity.py", "profile/habits.md", "profile/identity.md", "report.py"]
    positions = [step4.index(item) for item in order]
    assert positions == sorted(positions)
    assert "Working: profile, structure, taste, identity, report." in step4


# -- Style Barber carries the archetype once (R-1405) -----------------------------------------


@pytest.fixture
def analysed(tmp_path) -> Path:
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac", today=DAY)
    libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=DAY)
    run_all.analyze(root, today=DAY)
    return root


def test_barber_names_the_archetype_once_per_session(analysed):
    first = barber.next_step(analysed, today=D1)
    line = first["archetype_line"]
    assert line == "From your sleeve: The Crate Archaeologist. Decades deep. The old records are where you dig."
    assert "\n" not in line and first["question"]["n"] == 1 and list(first)[:2] == ["counts", "archetype_line"]
    assert barber.next_step(analysed, today=D1)["archetype_line"] is None  # resumed: not again
    barber.answer(analysed, 1, "skip", today=D1)
    assert barber.next_step(analysed, today=D1)["archetype_line"] is None
    assert barber.next_step(analysed, today=D2)["archetype_line"] == line  # a new session, once more


def test_barber_without_identity_has_no_line(analysed):
    (analysed / identity.IDENTITY_JSON).unlink()
    assert barber.next_step(analysed, today=D1)["archetype_line"] is None
    (analysed / identity.IDENTITY_JSON).write_text("{broken", encoding="utf-8")
    assert barber.archetype_line(analysed) is None


def test_barber_skill_says_one_line_once():
    text = (REPO / "plugin" / "skills" / "dj-barber" / "SKILL.md").read_text(encoding="utf-8")
    assert "exactly one line, once per session" in text and "archetype_line" in text
    assert "profile/identity.json" in text


# -- dj library analyze and the MCP tool ------------------------------------------------------


def test_analyze_runs_identity_between_taste_and_the_report(analysed):
    log = [ln for ln in (analysed / "log.md").read_text(encoding="utf-8").splitlines() if ln[:1].isdigit()]
    actions = [ln.split(" ", 3)[2] for ln in log]
    assert actions[-4:] == ["structure", "taste", "identity", "report"]
    data = json.loads((analysed / identity.IDENTITY_JSON).read_text(encoding="utf-8"))
    assert data["archetype"]["slug"] == "crate-archaeologist" and len(data["axes"]) == 6
    assert run_all.STEPS == ("profile", "structure", "taste", "identity", "report")


def test_a_db_read_is_seeded_from_the_measured_counts():
    shape = {"tracks": 1, "bands": [1, 0, 0, 0, 0, 0, 0, 0]}
    assert identity.seed_of_counts(shape) == identity.seed_of_counts(dict(reversed(list(shape.items()))))
    assert identity.seed_of_counts(shape) != identity.seed_of_counts({**shape, "tracks": 2})


def test_mcp_analyze_docstring_names_identity():
    doc = m.dj_library_analyze.__doc__ or ""
    assert "identity.json" in doc and "sleeve.svg" in doc and "after taste" in doc


def test_archetypes_yaml_is_plain_yaml_with_eight_entries():
    data = yaml.safe_load((REPO / "plugin" / "skills" / "dj-identity" / "archetypes.yaml").read_text(encoding="utf-8"))
    assert len(data["archetypes"]) == 8


# -- W-31 review: the handle for older folders, the archetype line under the question -----------


def test_find_xml_names_the_handle_so_an_older_folder_is_asked_once(start, capsys, tmp_path):
    lib = tmp_path / "dj-library"
    lib.mkdir()
    fx.write_xml(lib / "collection.xml")
    assert _init(start, capsys, "init", "--library", lib, "--device", "mac", "--today", "2026-10-20")[0] == 0
    code, out = _init(start, capsys, "find-xml", "--library", lib)
    assert code == 0 and out["library"]["dj_name"] is None  # set up before the handle: dj-start asks
    _init(start, capsys, "init", "--library", lib, "--device", "mac", "--today", "2026-10-21", "--dj-name", "You")
    code, out = _init(start, capsys, "find-xml", "--library", lib)
    assert out["library"]["dj_name"] == "You"  # a skip is recorded: never asked again


def test_the_skill_asks_an_older_folder_for_the_handle_once():
    text = _start_md()
    setup = re.search(r"^Already set up:.*?(?=^## )", text, re.MULTILINE | re.DOTALL).group(0)
    assert "`library.dj_name` is null" in setup and "What do they call you in the booth?" in setup
    assert '`--dj-name "<name>"`' in setup and "`--dj-name You`" in setup and "never comes back" in setup
    step1 = re.search(r"^### Step 1:.*?(?=^### Step 2:)", text, re.MULTILINE | re.DOTALL).group(0)
    assert "A name given in their next message still counts: use it." in step1
    chips = re.findall(r"```text\n(.*?)\n```", step1, re.DOTALL)[0]
    assert chips.index("What do they call you in the booth?") < chips.index("Mac or Windows?")  # the action last
    assert chips.rstrip().endswith('"Mac, DJ Sample".') and "sleeve" not in chips  # no word the DJ has not met yet


def test_the_barber_cli_prints_the_archetype_right_under_the_question(analysed):
    from typer.testing import CliRunner

    from dj import cli

    result = CliRunner().invoke(cli.app, ["library", "barber", "next", "--library", str(analysed), "--today", "2026-10-21"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("From your sleeve: "))
    assert lines[at - 2].startswith("Question 1 of 8") and lines[0].startswith("barber: ")
    skill = (REPO / "plugin" / "skills" / "dj-barber" / "SKILL.md").read_text(encoding="utf-8")
    assert "second line of that first reply" in skill
    example = re.search(r"```text\n(Question 1 of 8.*?)\n```", skill, re.DOTALL).group(1).splitlines()
    assert example[1].startswith("From your sleeve: The Crate Archaeologist.")
