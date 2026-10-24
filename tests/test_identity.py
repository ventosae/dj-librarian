"""dj.analysis.identity, the dj-identity skill script and `dj library identity` (W-31).

R-1401: six axes 0-100 from the facts in profile/, structure/, taste/, each with its inputs and
formula. R-1402: a deterministic archetype from the two strongest axes, picked by code from
plugin/skills/dj-identity/archetypes.yaml (8 archetypes, every one of the 15 axis pairs exactly
once; the table test runs all 30 ordered pairs). R-1403: profile/identity.json and the sleeve.
The synthetic library only (tests/xml_fixtures.py); no network, no master.db.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml
from reply_checks import avoided_words
from typer.testing import CliRunner

from dj import cli, libfolder, sleeve
from dj.analysis import identity, profile, structure, taste
from dj.analysis.common import NotALibraryFolder
from dj.model import Library, PlaylistNode, Track

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "plugin" / "skills" / "dj-identity"
SCRIPT = SKILL / "scripts" / "identity.py"
DAY = date(2026, 10, 20)
EXPORT = "exports/2026-10-20-collection.xml"
FIXTURE_SCORES = {"depth": 94, "selectivity": 57, "discipline": 66, "breadth": 81, "momentum": 69, "memory": 75}
runner = CliRunner()


def _measured_library(root: Path, tmp: Path) -> Path:
    libfolder.scaffold(root, device="mac", today=DAY)
    libfolder.import_export(root, fx.write_xml(tmp / "collection.xml"), today=DAY)
    profile.run(root, today=DAY)
    structure.run(root, today=DAY)
    taste.run(root, today=DAY)
    return root


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> Path:
    """A library folder with the three facts files, ready for identity (built once)."""
    tmp = tmp_path_factory.mktemp("identity")
    return _measured_library(tmp / "dj-library", tmp)


@pytest.fixture
def lib_dir(measured, tmp_path) -> Path:
    """A fresh copy of the measured library folder for a test that writes."""
    root = tmp_path / "dj-library"
    shutil.copytree(measured, root)
    return root


@pytest.fixture(scope="module")
def table():
    return identity.load_archetypes(SKILL / "archetypes.yaml")


def _read(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


# -- the fixture library ----------------------------------------------------------------------


def test_run_writes_identity_and_sleeve_and_one_log_line(lib_dir, monkeypatch):
    monkeypatch.setattr(libfolder, "_wall_clock", lambda: datetime(2026, 10, 21, 13, 20))  # Q-28: the wall clock
    before = (lib_dir / "log.md").read_text(encoding="utf-8").splitlines()
    result = identity.run(lib_dir, today=DAY)
    assert list(result)[0] == "counts"
    assert result["counts"] == {"tracks": 24, "axes": 6, "lanes": 3, "decades": 6, "bands": 8}
    assert result["written"] == ["profile/identity.json", "profile/sleeve.svg"]
    assert result["source"] == EXPORT and result["handle"] == "You"
    after = (lib_dir / "log.md").read_text(encoding="utf-8").splitlines()
    assert after[: len(before)] == before and after[len(before):] == [result["log"]]
    assert result["log"] == "2026-10-20 13:20 identity -> 6 axes, 3 lanes; profile/identity.json"


def test_fixture_scores_and_archetype(lib_dir):
    result = identity.run(lib_dir, today=DAY)
    assert result["scores"] == FIXTURE_SCORES
    assert result["top"] == ["depth", "breadth"]
    assert result["archetype"] == {"slug": "crate-archaeologist", "name": "The Crate Archaeologist"}


def test_identity_json_keys_and_axes(lib_dir):
    identity.run(lib_dir, today=DAY)
    data = _read(lib_dir, identity.IDENTITY_JSON)
    assert set(data) == {"schema", "by", "date", "source", "seed", "handle", "counts", "order", "axes", "top",
                         "archetype", "lanes", "fingerprint"}  # fmt: skip
    assert data["schema"] == 1 and data["by"] == "dj.analysis.identity" and data["date"] == "2026-10-20"
    assert data["order"] == list(identity.AXES)
    for axis in identity.AXES:
        entry = data["axes"][axis]
        assert set(entry) == {"name", "score", "inputs", "formula"}
        assert isinstance(entry["score"], int) and 0 <= entry["score"] <= 100
        assert entry["inputs"] and entry["formula"]
    assert set(data["archetype"]) == {"slug", "name", "meaning", "booth_line"}
    text = (lib_dir / identity.IDENTITY_JSON).read_text(encoding="utf-8")
    assert text == json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"  # sorted keys


def test_seed_is_the_sha256_of_the_export(lib_dir):
    identity.run(lib_dir, today=DAY)
    seed = _read(lib_dir, identity.IDENTITY_JSON)["seed"]
    assert seed == hashlib.sha256((lib_dir / EXPORT).read_bytes()).hexdigest()


def test_reproducible_same_facts_same_bytes(lib_dir):
    identity.run(lib_dir, today=DAY)
    first = [(lib_dir / rel).read_bytes() for rel in (identity.IDENTITY_JSON, identity.SLEEVE_SVG)]
    identity.run(lib_dir)  # no date: the axes are measured at the facts' date
    second = [(lib_dir / rel).read_bytes() for rel in (identity.IDENTITY_JSON, identity.SLEEVE_SVG)]
    assert first == second


def test_no_absolute_path_in_the_files(lib_dir, tmp_path):
    identity.run(lib_dir, today=DAY)
    for rel in (identity.IDENTITY_JSON, identity.SLEEVE_SVG):
        text = (lib_dir / rel).read_text(encoding="utf-8")
        assert str(tmp_path) not in text and tmp_path.as_posix() not in text, rel


def test_memory_averages_only_what_the_xml_carries(lib_dir):
    identity.run(lib_dir, today=DAY)
    memory = _read(lib_dir, identity.IDENTITY_JSON)["axes"]["memory"]
    assert memory["inputs"] == {"rating": 83, "colour": 71, "comment": 71, "my_tags": None, "carried": 3}
    assert memory["score"] == 75  # (83 + 71 + 71) / 3


def test_three_lanes_all_take_a_slot_in_bpm_order(lib_dir):
    """Q-30 (D-27): the four biggest lanes get a colour, numbered by BPM; the fixture has three."""
    identity.run(lib_dir, today=DAY)
    lanes = _read(lib_dir, identity.IDENTITY_JSON)["lanes"]
    assert [(lane["label"], lane["slot"]) for lane in lanes] == [("100-109", 1), ("119-122", 2), ("122-127", 3)]


def test_fingerprint_rings_bands_and_owners(lib_dir):
    identity.run(lib_dir, today=DAY)
    fp = _read(lib_dir, identity.IDENTITY_JSON)["fingerprint"]
    assert [r["decade"] for r in fp["rings"]] == ["1970s", "1980s", "1990s", "2000s", "2010s", "2020s"]
    assert [b["band"] for b in fp["bands"]] == list(identity.BANDS)
    assert [b["slot"] for b in fp["bands"]] == [1, 1, None, 2, 3, 3, None, None]
    assert len(fp["counts"]) == len(fp["rings"]) and all(len(row) == 8 for row in fp["counts"])
    assert fp["placed"] == 23 and fp["no_year"] == 1 and fp["no_bpm"] == 0
    assert sum(map(sum, fp["counts"])) == fp["placed"]
    assert abs(sum(map(sum, fp["shares"])) - 1) < 0.01
    assert sum(b["tracks"] for b in fp["bands"]) == 24


@pytest.mark.parametrize(("bpm", "band"), [(0, None), (-1, None), (60, 0), (99.9, 0), (100, 1), (117.9, 2),
                                           (118, 3), (124.99, 4), (125, 5), (128, 6), (134.9, 6), (135, 7),
                                           (174, 7)])  # fmt: skip
def test_band_edges(bpm, band):
    assert identity.band_of(bpm) == band


def test_band_owner_widens_lane_ends_by_half_a_bpm():
    lanes = identity.lanes({"lanes": [{"label": "124-124", "lo": 124, "hi": 124}, {"label": "100-109", "lo": 100, "hi": 109}]})
    assert [lane["label"] for lane in lanes] == ["100-109", "124-124"]
    owner = identity.owner(lanes, identity.BANDS.index("122-125"))
    assert owner["label"] == "124-124"  # a one-BPM lane still owns its band
    assert identity.owner(lanes, identity.BANDS.index("135+")) is None


def test_band_slots_for_the_mini_sleeve(lib_dir):
    identity.run(lib_dir, today=DAY)
    data = _read(lib_dir, identity.IDENTITY_JSON)
    own = identity.band_slots(data["lanes"])
    assert own == {b["band"]: b["slot"] for b in data["fingerprint"]["bands"]}
    other = identity.band_slots([{"lo": 126, "hi": 133, "slot": 5}, {"lo": 108, "hi": 116, "slot": 4}])
    assert other["128-135"] == 5 and other["110-118"] == 4 and other["<100"] is None
    svg = sleeve.mini_sleeve_svg(data, other, uid="card1")
    assert "#c98500" in svg and 'id="card1mini-title"' in svg  # slot 4 in its Booth value
    assert "#d55181" not in svg  # slot 5 is not one a chart draws: the guard of the 4-colour cap (D-26)


def test_lanes_past_the_four_biggest_are_other():
    """Q-30 (D-27; was "past eight fold into Other" before W-32): ten lanes of the same size, so
    the ties go to the slower lanes: the four slowest take slots 1-4, the other six are Other."""
    rows = [{"label": f"{80 + 10 * n}-{84 + 10 * n}", "lo": 80 + 10 * n, "hi": 84 + 10 * n} for n in range(10)]
    slots = [lane["slot"] for lane in identity.lanes({"lanes": list(reversed(rows))})]
    assert slots == [1, 2, 3, 4, None, None, None, None, None, None]


def test_handle_comes_from_library_yaml(lib_dir):
    libfolder.update_meta(lib_dir, today=DAY, dj_name="Selector  Okoro")
    result = identity.run(lib_dir, today=DAY)
    assert result["handle"] == "Selector Okoro"
    assert "Selector Okoro" in (lib_dir / identity.SLEEVE_SVG).read_text(encoding="utf-8")
    assert identity.handle_of({"dj_name": "x" * 60}) == "x" * identity.HANDLE_MAX
    assert identity.handle_of({"dj_name": "   "}) == identity.handle_of(None) == "You"


# -- the archetype table (R-1402) -------------------------------------------------------------


def test_the_table_has_8_archetypes_and_covers_each_pair_once(table):
    assert len(table) == identity.ARCHETYPE_COUNT == 8
    owned = [tuple(p) for entry in table for p in entry["pairs"]]
    assert len(owned) == len(set(owned)) == 15 == len(identity.PAIRS)
    assert set(owned) == set(identity.PAIRS)
    assert all(entry["pairs"] for entry in table)


@pytest.mark.parametrize(("first", "second"), list(itertools.permutations(identity.AXES, 2)))
def test_every_ordered_pair_picks_its_archetype(table, first, second):
    scores = {axis: 10 + n for n, axis in enumerate(identity.AXES)}
    scores[first], scores[second] = 90, 80
    pair, archetype = identity.pick(scores, table)
    assert set(pair) == {first, second}
    owner = next(e for e in table if sorted(pair, key=identity.AXES.index) in e["pairs"])
    assert archetype["slug"] == owner["slug"]
    swapped = dict(scores, **{first: 80, second: 90})
    assert identity.pick(swapped, table)[1] == archetype  # the pair is unordered


def test_every_archetype_is_reachable(table):
    reached = set()
    for a, b in identity.PAIRS:
        scores = dict.fromkeys(identity.AXES, 0) | {a: 50, b: 50}
        reached.add(identity.pick(scores, table)[1]["slug"])
    assert reached == {e["slug"] for e in table}


def test_ties_go_to_the_earlier_axis(table):
    assert identity.top_two(dict.fromkeys(identity.AXES, 40)) == ("depth", "selectivity")
    scores = dict.fromkeys(identity.AXES, 10) | {"memory": 70, "momentum": 70, "breadth": 70}
    assert identity.top_two(scores) == ("breadth", "momentum")


def test_names_are_affectionate_one_line_and_in_the_voice(table):
    banned = set(avoided_words()) | {"lazy", "messy", "hoarder", "noob", "slob", "lame", "basic"}
    for entry in table:
        assert entry["name"].startswith("The ")
        for field in ("name", "meaning", "booth_line"):
            text = entry[field]
            assert "\n" not in text and len(text) <= 120 and "?" not in text, (entry["slug"], field)
            assert not banned & set(text.lower().replace(".", " ").replace(",", " ").split()), (entry["slug"], text)


@pytest.mark.parametrize(("change", "message"), [
    (lambda d: d["archetypes"].pop(), "expected 8"),
    (lambda d: d["archetypes"][0]["pairs"].append(["memory", "momentum"]), "belongs to"),
    (lambda d: d["archetypes"][2]["pairs"].clear(), "owns no pair"),
    (lambda d: d["archetypes"][2]["pairs"].__setitem__(0, ["depth", "taste"]), "not a pair"),
    (lambda d: d["archetypes"][3].__setitem__("meaning", "two\nlines"), "one line"),
    (lambda d: d["archetypes"][4].__setitem__("slug", "Bad Slug"), "slug"),
])  # fmt: skip
def test_a_broken_table_is_refused(tmp_path, change, message):
    data = yaml.safe_load((SKILL / "archetypes.yaml").read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "archetypes.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(identity.IdentityError, match=message):
        identity.load_archetypes(path)


def test_a_missing_pair_is_refused():
    data = yaml.safe_load((SKILL / "archetypes.yaml").read_text(encoding="utf-8"))
    data["archetypes"][0]["pairs"] = data["archetypes"][0]["pairs"][:1]  # drops depth + momentum
    with pytest.raises(identity.IdentityError, match="no archetype for depth \\+ momentum"):
        identity.check_archetypes(data)


def test_the_default_table_ships_with_the_package_and_equals_the_skill_copy():
    """`dj library analyze` finds the table in any install (the packaged copy); the skill script
    passes its own; the two files are the same bytes."""
    assert identity.ARCHETYPES_YAML == Path(identity.__file__).with_name("archetypes.yaml")
    assert identity.SKILL_ARCHETYPES_YAML == SKILL / "archetypes.yaml"
    assert identity.ARCHETYPES_YAML.read_bytes() == (SKILL / "archetypes.yaml").read_bytes(), (
        "src/dj/analysis/archetypes.yaml and plugin/skills/dj-identity/archetypes.yaml differ: copy the skill's file")
    assert identity.load_archetypes() == identity.load_archetypes(SKILL / "archetypes.yaml")


# -- edge libraries: every axis stays in 0..100 -----------------------------------------------


def _track(n: int, **fields) -> Track:
    return Track(id=str(n), artist=f"Artist {n}", title=f"Title {n}", **fields)


def _edge_libraries() -> dict[str, Library]:
    many = {str(n): _track(n, year=1900 + (n * 7) % 200, bpm=60 + (n * 3) % 140, kind="flac", bitrate=1411,
                           rating=5, colour="Red", comment="x", genre=f"G{n % 40}", label=f"L{n % 9}",
                           date_added=date(2026, 10, 1 + n % 19)) for n in range(1, 401)}  # fmt: skip
    rough = {str(n): _track(n, kind="mp3", bitrate=96) for n in range(1, 31)}
    dumped = {str(n): _track(n, year=2020, bpm=124, kind="mp3", bitrate=320, date_added=date(2010, 1, 1))
              for n in range(1, 51)}  # fmt: skip
    return {
        "empty": Library(source="xml"),
        "no tags at all": Library(source="xml", tracks=rough),
        "one dump at the top": Library(source="xml", tracks=dumped, roots=(
            PlaylistNode(id="1", kind="playlist", name="everything", track_ids=tuple(dumped)),)),
        "maxed out": Library(source="xml", tracks=many, roots=(PlaylistNode(id="1", kind="folder", name="F", children=tuple(
            PlaylistNode(id=f"1.{k}", kind="playlist", name=f"p{k}", track_ids=tuple(str(n) for n in range(k, 401, 20)))
            for k in range(1, 21))),)),
        "db with my tags": Library(source="db", tracks={"1": _track(1, my_tags=("Peak",), rating=3, year=1999, bpm=128)}),
    }  # fmt: skip


@pytest.mark.parametrize("name", list(_edge_libraries()))
def test_axes_stay_in_bounds_for_edge_libraries(name, table):
    lib = _edge_libraries()[name]
    p, s, t, shape = profile.facts(lib, today=DAY), structure.facts(lib, today=DAY), taste.facts(lib), identity.measure(lib)
    measured = identity.axes(p, s, t, shape, today=DAY)
    assert list(measured) == list(identity.AXES)
    for axis, entry in measured.items():
        assert isinstance(entry["score"], int) and 0 <= entry["score"] <= 100, (name, axis, entry)
    again = identity.build(p, s, t, shape, seed="ab" * 32, source=EXPORT, today=DAY, table=table)
    assert again == identity.build(p, s, t, shape, seed="ab" * 32, source=EXPORT, today=DAY, table=table)
    svg = sleeve.sleeve_svg(again)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    if name == "empty":
        assert all(entry["score"] == 0 for entry in measured.values())
    if name == "maxed out":
        assert measured["selectivity"]["score"] == 100 and measured["memory"]["score"] == 100
    if name == "db with my tags":
        assert measured["memory"]["inputs"]["my_tags"] == 100 and measured["memory"]["inputs"]["carried"] == 4


def test_measure_counts_genres_case_insensitively():
    lib = Library(source="xml", tracks={
        "1": _track(1, genre="House", year=1995, bpm=122), "2": _track(2, genre="house", year=1995, bpm=122),
        "3": _track(3, genre="HOUSE", bpm=0), "4": _track(4, genre=""),
    })  # fmt: skip
    shape = identity.measure(lib)
    assert shape["genres"] == {"HOUSE": 3}  # one group; a tie of spellings goes to the first in sort order
    assert shape["no_bpm"] == 2 and shape["no_year"] == 2 and shape["cells"] == {"1990s": [0, 0, 0, 0, 2, 0, 0, 0]}
    assert shape["bands"] == [0, 0, 0, 0, 2, 0, 0, 0]  # 122 BPM sits in 122-125


# -- refusals and errors: nothing written -----------------------------------------------------


def test_missing_facts_are_an_error_and_nothing_is_written(lib_dir):
    (lib_dir / "taste" / "facts.json").unlink()
    log = (lib_dir / "log.md").read_bytes()
    with pytest.raises(identity.IdentityError, match="taste/facts.json not found"):
        identity.run(lib_dir, today=DAY)
    assert not (lib_dir / identity.IDENTITY_JSON).exists() and not (lib_dir / identity.SLEEVE_SVG).exists()
    assert (lib_dir / "log.md").read_bytes() == log


def test_facts_from_another_export_are_refused(lib_dir, tmp_path):
    newer = dict(fx.SPEC, product=dict(fx.SPEC["product"], Version="7.2.19"))
    libfolder.import_export(lib_dir, fx.write_xml(tmp_path / "newer.xml", newer), today=date(2026, 10, 21))
    with pytest.raises(identity.IdentityError, match="another export"):
        identity.run(lib_dir, today=DAY)
    assert not (lib_dir / identity.IDENTITY_JSON).exists()


def test_a_folder_that_is_not_a_library_is_refused(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(NotALibraryFolder):
        identity.run(plain, today=DAY)
    assert list(plain.iterdir()) == []


# -- the skill script and the CLI -------------------------------------------------------------


def _script(*args) -> tuple[int, dict]:
    done = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)  # fmt: skip
    lines = done.stdout.splitlines()
    assert len(lines) == 1, (done.stdout, done.stderr)
    return done.returncode, json.loads(lines[0])


def test_the_script_prints_one_json_and_uses_its_own_table(lib_dir):
    code, out = _script("--library", lib_dir, "--today", "2026-10-20")
    assert code == 0 and out["ok"] is True
    assert out["scores"] == FIXTURE_SCORES and out["archetype"]["slug"] == "crate-archaeologist"
    assert out["written"] == ["profile/identity.json", "profile/sleeve.svg"]


def test_the_script_refuses_and_errors_with_exit_codes(lib_dir, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    code, out = _script("--library", plain)
    assert code == 2 and out["ok"] is False and "refused" in out
    (lib_dir / "profile" / "facts.json").unlink()
    code, out = _script("--library", lib_dir)
    assert code == 1 and "profile/facts.json not found" in out["error"]
    code, out = _script("--library", lib_dir, "--today", "20/10/2026")
    assert code == 1 and "YYYY-MM-DD" in out["error"]
    code, out = _script("--nope")
    assert code == 1 and out["error"].startswith("usage:")


def test_cli_identity_json_and_text(lib_dir, tmp_path):
    done = runner.invoke(cli.app, ["library", "identity", "--library", str(lib_dir), "--today", "2026-10-20", "--json"])
    assert done.exit_code == 0, done.output
    data = json.loads(done.output)
    assert list(data)[0] == "counts" and data["scores"] == FIXTURE_SCORES
    text = runner.invoke(cli.app, ["library", "identity", "--library", str(lib_dir), "--today", "2026-10-20"])
    assert text.exit_code == 0
    assert text.output.startswith("identity: The Crate Archaeologist (depth + breadth) for You")
    assert "wrote profile/sleeve.svg" in text.output and "Nothing was written to rekordbox." in text.output
    plain = tmp_path / "plain"
    plain.mkdir()
    refused = runner.invoke(cli.app, ["library", "identity", "--library", str(plain)])
    assert refused.exit_code == 2 and "REFUSED" in refused.output


def test_skill_md_documents_the_axes_the_run_and_the_liner_notes():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "**Requirements:** R-1401, R-1402, R-1403, R-1404, R-1405, R-1406." in text
    for needle in ("python3 scripts/identity.py --library", "--today", "uv run dj library identity",
                   "profile/identity.md", "120 words", "identity.json", "# Liner notes",
                   "> Words by Claude, from profile/identity.json.", "archetypes.yaml"):  # fmt: skip
        assert needle in text, needle
    for axis in identity.AXIS_NAMES.values():
        assert f"| {axis} |" in text, axis


def test_structure_facts_of_another_export_are_refused_too(lib_dir):
    """structure/facts.json names the export it measured (`export`), so stale structure facts are
    caught like stale profile and taste facts; an older file without `export` is not judged."""
    facts = _read(lib_dir, "structure/facts.json")
    assert facts["export"] == EXPORT
    (lib_dir / "structure" / "facts.json").write_text(json.dumps({**facts, "export": "exports/2026-01-01-collection.xml"}),
                                                     encoding="utf-8")  # fmt: skip
    with pytest.raises(identity.IdentityError, match=r"structure/facts.json \(exports/2026-01-01-collection.xml\)"):
        identity.run(lib_dir, today=DAY)
    assert not (lib_dir / identity.IDENTITY_JSON).exists()
    del facts["export"]
    (lib_dir / "structure" / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    assert identity.run(lib_dir, today=DAY)["archetype"]["slug"] == "crate-archaeologist"


# What a meaning may claim: each phrase names the axes that measure it. A phrase that more than
# one axis can stand behind ("you know your way around": filed folders or marked tracks) names
# all of them. Used to check that every meaning is true for every pair its archetype owns.
CLAIMS = {
    r"\bdecades?\b|\bold records?\b|\bdeep\b|\bcatalogue\b|\boriginals?\b|\bback through\b": {"depth"},
    r"\blossless\b|\b320\b|\bquality\b|\bfiles?\b|\bcop(?:y|ies)\b|\bmaster\b|\brip\b|\bpicky\b": {"selectivity"},
    r"\bfiled\b|\bfolders?\b|\btidy\b|\bwhere it sits\b|\bwhere every record is\b": {"discipline"},
    r"\bstyles?\b|\bgenres?\b|\bwide\b|\bevery direction\b|\bcorners?\b|\bwhatever room\b|\bacross\b": {"breadth"},
    r"\bnew\b|\bstill\b|\bkeep (?:adding|buying)\b|\bsteady flow\b|\bweek(?:ly)?\b|\bstale\b|\binbox\b": {"momentum"},
    r"\bmarked\b|\btag(?:s|ged)?\b|\bratings?\b|\bcolours?\b|\bcomments?\b": {"memory"},
    r"\blooked after\b|\bkeep up with it\b|\bput your hand on\b|\bknow your way around\b": {"discipline", "memory"},
}
NUMBER_WORDS = r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen|hundred)\b"


def claims(text: str) -> list[set[str]]:
    return [axes for pattern, axes in CLAIMS.items() for _ in re.findall(pattern, text.lower())]


def test_every_meaning_is_true_for_every_pair_its_archetype_owns(table):
    """A meaning only says what the two top axes measured, whichever owned pair picked it: each
    phrase it uses names an axis of that pair (voice.md: if the tool did not measure it, I do not
    say it). The old lines failed this ("still digging" for a Momentum of 0)."""
    for entry in table:
        found = claims(entry["meaning"])
        assert found, (entry["slug"], "the meaning names nothing the axes measure")
        for pair in entry["pairs"]:
            for axes in found:
                assert axes & set(pair), (entry["slug"], pair, entry["meaning"], sorted(axes))


def test_the_old_meanings_would_have_failed():
    old = {"crate-archaeologist": ("You dig back through the decades and across styles, and you are still digging.",
                                   [["depth", "momentum"]]),
           "archivist": ("A long catalogue, filed and marked.", [["discipline", "memory"]])}  # fmt: skip
    for meaning, pairs in old.values():
        assert any(not (axes & set(pair)) for pair in pairs for axes in claims(meaning)), meaning


def test_no_count_in_a_meaning_or_a_booth_line(table):
    """The liner notes quote both word for word, and every count there comes from identity.json:
    no digit count and no spelled-out count ("Five genres") in a meaning; booth lines name no
    count of the DJ's own tracks either (times of day and formats like 320 are not counts)."""
    for entry in table:
        assert not re.search(NUMBER_WORDS, entry["meaning"].lower()), entry["slug"]
        assert not re.search(r"\b(?:five|\d+) (?:genres|tracks|records|crates)\b", entry["booth_line"].lower()), entry["slug"]
    names = {e["slug"]: e["name"] for e in table}
    assert names["weekly-ritual"] == "The Tuesday Digger"  # a person, like the other seven; the slug stays
