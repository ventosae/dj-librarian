"""How dj-identity reaches the rest (W-31): the DJ's handle in library.yaml and dj-start
(R-1406), the archetype line in Style Barber (R-1405), identity inside `dj library analyze`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import xml_fixtures as fx

from dj import barber, libfolder
from dj import mcp_server as m
from dj.analysis import identity, run_all
from dj.libfolder import LibraryFolderError, load_meta, update_meta, validate_meta

pytestmark = pytest.mark.usefixtures("export_reads")  # the library is read from the export fixture

REPO = Path(__file__).resolve().parents[1]
START = REPO / "plugin" / "skills" / "dj-start"
DAY = date(2026, 10, 20)
D1, D2 = date(2026, 10, 21), date(2026, 10, 22)


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


def test_the_handle_reaches_the_sleeve_through_analyze(tmp_path):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac", today=DAY, dj_name="Selector Okoro")
    libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=DAY)
    run_all.analyze(root, today=DAY)
    data = json.loads((root / identity.IDENTITY_JSON).read_text(encoding="utf-8"))
    assert data["handle"] == "Selector Okoro"
    assert ">Selector Okoro</text>" in (root / identity.SLEEVE_SVG).read_text(encoding="utf-8")


# -- dj-start SKILL.md ------------------------------------------------------------------------


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


# -- W-31 review: the handle for older folders, the archetype line under the question -----------

