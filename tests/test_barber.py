"""Style Barber (W-24): a short question session that sharpens taste/ (R-701, R-703) and writes
vetoes and gig feedback in the formats Crate me reads (the writing side of R-702).

R-701 acceptance: a session updates >= 1 taste/ file with dated entries (`test_a_full_session_*`).
R-703 acceptance is a transcript check (W-28); here: at most 8 questions, a progress line with the
minutes left on every question, the skill's one-question-per-reply rules.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import xml_fixtures as fx
import yaml
from reply_checks import reply_problems, text_problems
from typer.testing import CliRunner

from dj import barber, cli, libfolder, safety
from dj import mcp_server as m
from dj.analysis import taste
from dj.analysis.common import NotALibraryFolder
from dj.model import Library, PlaylistNode, Track
from dj.readers.xml import read_xml
from dj.taste_files import (
    Entry,
    Vetoes,
    append_entries,
    read_entries,
    read_feedback,
    read_keys,
    read_vetoes,
)

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "plugin" / "skills" / "dj-barber"
SCRIPT = SKILL / "scripts" / "barber.py"
D0, D1, D2 = date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)
PROGRESS = re.compile(r"^Question (\d+) of (\d+) · about (\d+) minutes? left$")
TASTE_MD = {"taste/anchors.md", "taste/lanes.md", "taste/vetoes.md", "taste/feedback.md"}
runner = CliRunner()

# One valid answer per kind, for a full session.
ANSWERS = {"ab": "A", "name_lane": "Rollers", "veto": "never", "pair": "never", "gig": "The rooftop closers worked"}


@pytest.fixture(scope="module")
def lib() -> Library:
    return read_xml(fx.SAMPLE_XML)


@pytest.fixture(scope="module")
def facts(lib) -> dict:
    return taste.facts(lib, today=D0)


@pytest.fixture
def lib_dir(tmp_path) -> Path:
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="windows", today=D0)
    libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=D0)
    return root


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def run_session(root: Path, day: date = D1) -> dict:
    """Answer every question of today's session with ANSWERS; returns {n: added lines}."""
    session, _ = barber.start(root, today=day)
    out = {}
    for q in session.questions:
        out[q.n] = barber.record(root, session, q.n, ANSWERS[q.kind], today=day)
    return out


def mini(tracks: list[Track], playlists: dict[str, list[str]]) -> Library:
    roots = tuple(PlaylistNode(id=name, kind="playlist", name=name, track_ids=tuple(ids)) for name, ids in playlists.items())
    return Library(source="xml", tracks={t.id: t for t in tracks}, roots=roots)


# -- the plan (R-703: at most 8 questions, deterministic) -----------------------------------


def test_session_holds_at_most_8_questions_and_is_deterministic(lib, facts):
    one = barber.plan_session(lib, facts, today=D1)
    assert 1 <= len(one.questions) <= barber.MAX_QUESTIONS == 8
    assert len(one.questions) == 8  # the fixture has enough for a full session
    again = barber.plan_session(read_xml(fx.SAMPLE_XML), taste.facts(read_xml(fx.SAMPLE_XML)), today=D1)
    assert again.to_json() == one.to_json()  # same library, same date -> the same session
    assert [q.n for q in one.questions] == list(range(1, 9)) and {q.total for q in one.questions} == {8}
    week = {json.dumps(barber.plan_session(lib, facts, today=date(2026, 11, d)).to_json()["questions"]) for d in range(1, 8)}
    assert len(week) > 1  # a new day starts in another place
    for size in (1, 3, 5):
        assert len(barber.plan_session(lib, facts, today=D1, size=size).questions) == size
    for bad in (0, 9, -1, True, "8"):
        with pytest.raises(ValueError):
            barber.plan_session(lib, facts, today=D1, size=bad)


def test_every_kind_appears_on_the_fixture(lib, facts):
    for day in (D1, D2, date(2026, 12, 24)):
        session = barber.plan_session(lib, facts, today=day)
        kinds = [q.kind for q in session.questions]
        assert set(kinds) == set(barber.KINDS), (day, kinds)
        assert kinds[-1] == "gig"  # the free-text, optional one comes last
        assert kinds[:4] == ["name_lane", "ab", "pair", "veto"]  # mixed, never one kind in a row


def test_question_shapes(lib, facts):
    session = barber.plan_session(lib, facts, today=D1)
    for q in session.questions:
        assert q.prompt and "\n" not in q.prompt and len(q.prompt) <= 160
        assert text_problems(q.prompt) == [], q.prompt  # the voice: no pleasantry, no avoided word
        assert q.file in TASTE_MD and q.file == f"taste/{barber.FILES[q.kind][0]}"
        if q.kind in barber.CHOICE_KINDS:
            assert len(q.options) == len(q.chips) == 2 and not q.free_text  # 2 chips at most
        else:
            assert q.options == () and q.chips == () and q.free_text
        assert q.track_ids == tuple(t.id for t in q.tracks)
        assert all(t.id in lib.tracks for t in q.tracks)  # only the DJ's own tracks
    by_kind = {q.kind: q for q in session.questions}
    assert len(by_kind["ab"].tracks) == 2 and by_kind["ab"].options == ("A", "B")
    assert by_kind["ab"].chips == tuple(f"{o}: {t.label}" for o, t in zip("AB", by_kind["ab"].tracks))
    assert 1 <= len(by_kind["name_lane"].tracks) <= 3
    assert by_kind["name_lane"].prompt.startswith("What do you call your ") and "BPM lane?" in by_kind["name_lane"].prompt
    assert len(by_kind["veto"].tracks) == 1 and by_kind["veto"].options == ("keep", "never")
    assert len(by_kind["pair"].tracks) == 2 and by_kind["pair"].options == ("good", "never")
    assert by_kind["gig"].tracks == ()


def test_a_track_is_asked_about_once_and_two_tracks_are_never_duplicates(lib, facts):
    for day in (D1, D2, date(2027, 1, 1)):
        session = barber.plan_session(lib, facts, today=day)
        # ab, veto and pair ask about their tracks; a lane's anchors are context and may repeat
        ids = [i for q in session.questions if q.kind != "name_lane" for i in q.track_ids]
        assert len(ids) == len(set(ids))
        for q in session.questions:
            if len(q.tracks) >= 2:
                idents = [(lib.tracks[i].artist, lib.tracks[i].title) for i in q.track_ids]
                assert len(idents) == len(set(idents)), q.key


def test_name_lane_shows_3_anchors_whenever_the_lane_has_3(lib, facts):
    """The brief: a name_lane question shows the lane's BPM range and 3 anchor tracks."""
    lanes = {lane["key"].split(":", 1)[1]: lane for lane in facts["lanes"]}
    seen = 0
    for day in [D1, D2, date(2026, 12, 24)] + [date(2027, 1, d) for d in range(1, 15)]:
        for q in barber.plan_session(lib, facts, today=day).questions:
            if q.kind != "name_lane":
                continue
            seen += 1
            lane = lanes[q.subject]
            inside = {
                (t.artist, t.title) for path in lane["playlists"] for node in lib.playlists() if node.path_str == path
                for t in (lib.tracks[i] for i in node.track_ids if i in lib.tracks)
                if t.bpm > 0 and lane["lo"] <= int(t.bpm + 0.5) <= lane["hi"]
            }  # fmt: skip
            assert len(inside) >= 3, q.subject  # every fixture lane has 3 or more
            assert len(q.tracks) == 3, (day, q.n, q.subject, [t.label for t in q.tracks])
            assert f"{lane['lo']}-{lane['hi']} BPM" in q.prompt  # the BPM range is shown
    assert seen >= 2 * 17  # two lane questions a day: the later one too gets its 3 anchors


def test_progress_line_format():
    assert barber.progress_line(3, 8) == "Question 3 of 8 · about 6 minutes left"
    assert barber.progress_line(1, 8) == "Question 1 of 8 · about 8 minutes left"
    assert barber.progress_line(8, 8) == "Question 8 of 8 · about 1 minute left"
    assert barber.progress_line(2, 5) == "Question 2 of 5 · about 4 minutes left"


def test_every_question_states_progress_and_a_session_stays_under_10_minutes(lib, facts):
    session = barber.plan_session(lib, facts, today=D1)
    minutes = []
    for q in session.questions:
        m_ = PROGRESS.match(q.progress)
        assert m_, q.progress
        assert (int(m_.group(1)), int(m_.group(2))) == (q.n, q.total)
        minutes.append(int(m_.group(3)))
        assert q.to_dict()["progress"] == q.progress
    assert minutes == sorted(minutes, reverse=True) and minutes[0] <= 10 and minutes[-1] == 1


def test_lane_questions_come_from_the_taste_lanes(lib, facts):
    session = barber.plan_session(lib, facts, today=D1, size=8)
    lanes = {lane["key"].split(":", 1)[1]: lane for lane in facts["lanes"]}
    for q in session.questions:
        if q.kind == "name_lane":
            lane = lanes[q.subject]
            assert q.key == f"lane-name:{q.subject}"
            assert lane["label"] in q.prompt and lane["label"] in q.context
            assert all(lane["lo"] <= int(t.bpm + 0.5) <= lane["hi"] for t in q.tracks)  # inside the range
        if q.kind == "ab":
            assert q.key == "ab:" + ",".join(sorted(q.track_ids, key=int))


def test_veto_candidates_sit_oddly_in_their_lane(lib, facts):
    planner = barber._Planner(lib, facts, D1, (), Vetoes())
    odd = planner.odd_tracks()
    # funk & disco 78-92 is the 100-109 lane: 96 BPM (Pocket Change) and 112 BPM (Glass Elevator)
    assert [track_id for track_id, _why in odd] == ["5", "6"]
    assert odd[0][1] == "96 BPM in funk & disco 78-92, a 100-109 BPM lane"
    # no BPM oddity: a 1-star track that still sits in a playlist is the fallback
    tracks = [Track(id=str(i), artist=f"A{i}", title=f"T{i}", bpm=120.0, rating=1 if i == 3 else 4) for i in range(1, 5)]
    small = mini(tracks, {"p": ["1", "2", "3", "4"]})
    small_facts = taste.facts(small)
    out = barber._Planner(small, small_facts, D1, (), Vetoes()).odd_tracks()
    assert out == [("3", "rated 1 star, in 1 playlist")]


def test_the_gig_question_names_the_latest_gig_playlist(lib, facts):
    gig = barber.plan_session(lib, facts, today=D1).questions[-1]
    assert gig.subject == "Gig 2025-11 Rooftop" and "(Gig 2025-11 Rooftop)" in gig.prompt
    assert gig.key == "gig:gigs-gig-2025-11-rooftop"  # the gig, not the day: answered once, asked once
    assert barber.plan_session(lib, facts, today=D2).questions[-1].key == gig.key
    plain = mini([Track(id="1", artist="A", title="T", bpm=120.0)], {"warm": ["1"]})
    q = barber.plan_session(plain, taste.facts(plain), today=D1).questions[-1]
    assert q.kind == "gig" and q.prompt == "What worked at your last gig? One line, or skip." and q.subject == ""
    assert q.key == "gig:2026-10-21"  # no gig playlist: the session date


def test_an_answered_gig_is_not_asked_again(lib, facts):
    answered = barber.plan_session(lib, facts, today=D2, skip={"gig:gigs-gig-2025-11-rooftop"})
    assert "gig" not in {q.kind for q in answered.questions}
    assert len(answered.questions) == 8  # the gig's slot goes to another question
    one = barber.plan_session(lib, facts, today=D2, size=1, skip={"gig:gigs-gig-2025-11-rooftop"})
    assert [q.kind for q in one.questions] == ["name_lane"]
    # everything answered: an empty session, done at once
    empty = Library(source="xml")
    none_left = barber.plan_session(empty, taste.facts(empty), today=D1, skip={"gig:2026-10-21"})
    assert none_left.questions == () and none_left.done and none_left.counts()["questions"] == 0


def test_an_empty_library_gets_only_the_gig_question():
    empty = Library(source="xml")
    session = barber.plan_session(empty, taste.facts(empty), today=D1)
    assert [q.kind for q in session.questions] == ["gig"]
    assert session.questions[0].progress == "Question 1 of 1 · about 1 minute left"


def test_vetoed_tracks_and_answered_keys_are_left_out(lib, facts):
    first = barber.plan_session(lib, facts, today=D1)
    shown = {i for q in first.questions for i in q.track_ids}
    vetoes = Vetoes(frozenset(shown))
    second = barber.plan_session(lib, facts, today=D1, vetoes=vetoes)
    assert not shown & {i for q in second.questions for i in q.track_ids}
    keys = {q.key for q in first.questions if q.kind != "gig"}
    third = barber.plan_session(lib, facts, today=D1, skip=keys)
    assert not keys & {q.key for q in third.questions}
    # a skip key in another spelling still matches (canonical keys, as taste_files compares them)
    pair = next(q for q in first.questions if q.kind == "pair")
    a, b = pair.track_ids
    respelled = barber.plan_session(lib, facts, today=D1, skip={f"pair: {b} , {a}"})
    assert pair.key not in {q.key for q in respelled.questions}


# -- answers ----------------------------------------------------------------------------------


def test_parse_answer(lib, facts):
    session = barber.plan_session(lib, facts, today=D1)
    by_kind = {q.kind: q for q in session.questions}
    ab, veto, pair, name, gig = (by_kind[k] for k in ("ab", "veto", "pair", "name_lane", "gig"))
    for given in ("A", "a", " a ", "1", ab.chips[0], ab.chips[0].upper(), ab.tracks[0].label):
        assert barber.parse_answer(ab, given) == "A"
    assert barber.parse_answer(ab, "2") == "B"
    for given in ("never", "NEVER", "2", "Never"):
        assert barber.parse_answer(veto, given) == "never"
    assert barber.parse_answer(veto, "Keep proposing") == "keep"
    assert barber.parse_answer(pair, "good pair") == "good" and barber.parse_answer(pair, "Never pair") == "never"
    assert barber.parse_answer(name, "  Peak   hour ") == "Peak hour"
    assert barber.parse_answer(gig, "Skip") == barber.SKIP == barber.parse_answer(ab, "skip")
    for bad_q, bad in ((ab, "C"), (ab, "3"), (veto, "maybe"), (pair, "yes"), (ab, ""), (ab, None), (name, "x" * 61),
                       (gig, "y" * 301), (name, "   ")):  # fmt: skip
        with pytest.raises(barber.BarberError):
            barber.parse_answer(bad_q, bad)


def test_a_full_session_updates_taste_files_with_dated_entries(lib_dir):
    """R-701: a session updates >= 1 taste/ file with dated entries; they parse back."""
    added = run_session(lib_dir)
    session = barber.load_session(lib_dir, today=D1)
    assert session.done and session.counts() == {"questions": 8, "answered": 8, "skipped": 0, "left": 0}
    assert all(len(lines) == 1 for lines in added.values())
    assert all(line.startswith("- [2026-10-21] ") for lines in added.values() for line in lines)
    assert set(session.files()) == TASTE_MD

    by_kind: dict[str, list] = {}
    for q in session.questions:
        by_kind.setdefault(q.kind, []).append(q)
    for kind, name in (("ab", "anchors.md"), ("name_lane", "lanes.md"), ("gig", "feedback.md")):
        entries = read_entries(lib_dir / "taste" / name)
        assert {e.key for e in entries} == {q.key for q in by_kind[kind]}
        assert all(e.date == D1 for e in entries)
    lanes = read_entries(lib_dir / "taste/lanes.md")
    assert all(re.fullmatch(r"named lane [\w-]+: Rollers", e.text) for e in lanes)
    ab = by_kind["ab"][0]
    anchors = {e.key: e.text for e in read_entries(lib_dir / "taste/anchors.md")}
    assert anchors[ab.key] == f"prefers {ab.tracks[0].label} over {ab.tracks[1].label} for {ab.subject}"
    feedback = read_feedback(lib_dir / "taste/feedback.md")
    gig_line = "what worked at Gig 2025-11 Rooftop: The rooftop closers worked"
    assert feedback == [(D1, gig_line, "gig:gigs-gig-2025-11-rooftop")]

    # veto and pair answers are Vetoes entries, exactly in the read_vetoes format (R-702)
    vetoes = read_vetoes(lib_dir / "taste/vetoes.md")
    assert vetoes.never_propose == {q.track_ids[0] for q in by_kind["veto"]}
    assert vetoes.never_pair == {frozenset(q.track_ids) for q in by_kind["pair"]}
    text = read(lib_dir / "taste/vetoes.md")
    veto = by_kind["veto"][0]
    assert f"never propose: {veto.tracks[0].label} <!-- key:veto:{veto.track_ids[0]} -->" in text
    pair = by_kind["pair"][0]
    a, b = pair.tracks
    ids = ",".join(sorted(pair.track_ids, key=int))
    assert f"never pair: {a.label} + {b.label} <!-- key:pair:{ids} -->" in text
    # a file the barber creates: title, the section-0 provenance line (the export its tracks came from), Log
    provenance = "> Measured by code: dj.barber from exports/2026-10-20-collection.xml, 2026-10-21."
    assert text.startswith(f"# Vetoes\n\n{provenance}\n\n## Log\n\n- [")
    for name in ("anchors.md", "lanes.md", "feedback.md"):
        lines = read(lib_dir / "taste" / name).splitlines()
        assert lines[0].startswith("# ") and lines[1:4] == ["", provenance, ""], name


def test_keep_and_good_answers_lift_an_earlier_veto(lib_dir, lib, facts):
    session, _ = barber.start(lib_dir, today=D1)
    veto = next(q for q in session.questions if q.kind == "veto")
    pair = next(q for q in session.questions if q.kind == "pair")
    barber.record(lib_dir, session, veto.n, "never", today=D1)
    barber.record(lib_dir, session, pair.n, "never", today=D1)
    path = lib_dir / "taste/vetoes.md"
    assert read_vetoes(path).blocks(veto.track_ids[0]) and read_vetoes(path).blocks_pair(*pair.track_ids)
    added = barber.record(lib_dir, session, veto.n, "keep", today=D2)  # the DJ changed their mind
    assert added == [f"- [2026-10-22] updated: keep proposing: {veto.tracks[0].label} <!-- key:{veto.key} -->"]
    barber.record(lib_dir, session, pair.n, "Good pair", today=D2)
    assert read_vetoes(path) == Vetoes()


def test_recording_the_same_answer_again_adds_nothing(lib_dir):
    session, _ = barber.start(lib_dir, today=D1)
    q = session.questions[0]
    first = barber.record(lib_dir, session, q.n, ANSWERS[q.kind], today=D1)
    assert len(first) == 1
    before = snapshot(lib_dir)
    for again in (ANSWERS[q.kind], f"  {ANSWERS[q.kind]}  "):
        assert barber.record(lib_dir, session, q.n, again, today=D1) == []
    assert barber.record(lib_dir, session, q.n, ANSWERS[q.kind], today=D2) == []  # another day: still nothing
    assert snapshot(lib_dir) == before  # taste files, state and log.md byte for byte
    ab = next(q for q in session.questions if q.kind == "ab")
    barber.record(lib_dir, session, ab.n, "1", today=D1)
    assert barber.record(lib_dir, session, ab.n, "A", today=D1) == []  # "1" and "A" are one answer


def test_an_unknown_answer_adds_nothing(lib_dir):
    session, _ = barber.start(lib_dir, today=D1)
    before = snapshot(lib_dir)
    for q in session.questions:
        bad = "maybe" if q.options else "z" * 400
        with pytest.raises(barber.BarberError):
            barber.record(lib_dir, session, q.n, bad, today=D1)
    for n in (0, 9, -1):
        with pytest.raises(barber.BarberError):
            barber.record(lib_dir, session, n, "A", today=D1)
    assert snapshot(lib_dir) == before
    assert session.answers == {} and barber.load_session(lib_dir, today=D1).answers == {}


def test_skip_records_no_line_and_moves_on(lib_dir):
    session, _ = barber.start(lib_dir, today=D1)
    taste_before = {k: v for k, v in snapshot(lib_dir).items() if k.startswith("taste/")}
    assert barber.record(lib_dir, session, 1, "skip", today=D1) == []
    assert {k: v for k, v in snapshot(lib_dir).items() if k.startswith("taste/")} == taste_before
    stored = barber.load_session(lib_dir, today=D1)
    assert stored.answers[1]["status"] == "skipped" and stored.next_question().n == 2
    assert stored.counts() == {"questions": 8, "answered": 0, "skipped": 1, "left": 7}


def test_an_existing_taste_file_keeps_every_line(lib_dir):
    taste.run(lib_dir, today=D0)  # dj-taste first: anchors.md and lanes.md exist
    old = {name: read(lib_dir / "taste" / name) for name in ("anchors.md", "lanes.md")}
    run_session(lib_dir)
    for name, text in old.items():
        new = read(lib_dir / "taste" / name)
        assert new.startswith(text), name  # appended only: every old byte where it was
        added = new[len(text):].splitlines()
        assert added and all(line.startswith("- [2026-10-21] ") for line in added)
        assert "dj.barber" not in new and new.count("> Measured by code:") == 1  # an existing file keeps its head
    # a later dj-taste run keeps the barber's lines
    taste.run(lib_dir, today=D2)
    assert "named lane " in read(lib_dir / "taste/lanes.md")


def test_barber_first_then_dj_taste_leaves_one_provenance_line(lib_dir):
    """Contract section 0: `# <Title>`, then one provenance line, also when the barber made the file."""
    run_session(lib_dir, D1)  # no dj-taste yet: the barber creates anchors.md and lanes.md
    barber_lines = {name: [e.text for e in read_entries(lib_dir / "taste" / name)] for name in ("anchors.md", "lanes.md")}
    taste.run(lib_dir, today=D2)
    for name, kept in barber_lines.items():
        lines = read(lib_dir / "taste" / name).splitlines()
        head = lines[: next(i for i, line in enumerate(lines) if line.startswith("## "))]
        provenance = [line for line in head if line.startswith(">")]
        assert provenance == ["> Measured by code: dj.analysis.taste from exports/2026-10-20-collection.xml, 2026-10-22."], name
        assert head[:3] == [head[0], "", provenance[0]] and head[0].startswith("# "), head
        texts = [e.text for e in read_entries(lib_dir / "taste" / name)]
        assert all(text in texts for text in kept), name  # the barber's answers are still there


# -- state: resume, new day, stop -------------------------------------------------------------


def test_resume_on_the_same_day_and_a_new_plan_on_a_new_day(lib_dir):
    session, resumed = barber.start(lib_dir, today=D1)
    assert resumed is False and (lib_dir / ".cache" / "barber.json").is_file()
    barber.record(lib_dir, session, 1, ANSWERS[session.questions[0].kind], today=D1)
    barber.record(lib_dir, session, 2, "skip", today=D1)
    # the DJ stops here; later the same day
    again, resumed = barber.start(lib_dir, today=D1)
    assert resumed is True and again.to_json() == session.to_json()
    step = barber.next_step(lib_dir, today=D1)
    assert step["resumed"] is True and step["question"]["n"] == 3
    assert step["counts"] == {"questions": 8, "answered": 1, "skipped": 1, "left": 6}
    assert list(step)[:1] == ["counts"]  # counts first (NFR-03)
    # a new day: a new plan, and the question answered yesterday is not asked again
    fresh, resumed = barber.start(lib_dir, today=D2)
    assert resumed is False and fresh.day == D2 and fresh.answers == {}
    assert session.questions[0].key not in {q.key for q in fresh.questions}
    assert json.loads(read(lib_dir / ".cache/barber.json"))["date"] == "2026-10-22"


def test_a_full_session_then_next_says_done(lib_dir):
    run_session(lib_dir)
    step = barber.next_step(lib_dir, today=D1)
    assert step["done"] is True and step["question"] is None and step["counts"]["left"] == 0
    assert set(step["files"]) == TASTE_MD


def test_a_second_session_asks_nothing_already_answered(lib_dir):
    run_session(lib_dir, D1)
    day1 = barber.load_session(lib_dir, today=D1)
    fresh, _ = barber.start(lib_dir, today=D2)
    answered = {q.key for q in day1.questions}
    assert "gig:gigs-gig-2025-11-rooftop" in answered
    assert not answered & {q.key for q in fresh.questions}
    assert "gig" not in {q.kind for q in fresh.questions}  # the same gig is not asked about again
    vetoed = {q.track_ids[0] for q in day1.questions if q.kind == "veto"}
    assert not vetoed & {i for q in fresh.questions for i in q.track_ids}
    for q in fresh.questions:
        barber.record(lib_dir, fresh, q.n, ANSWERS[q.kind], today=D2)
    assert len(read_feedback(lib_dir / "taste/feedback.md")) == 1  # one gig, one line


def test_an_undated_hand_written_line_counts_as_answered(lib_dir, lib, facts):
    """vetoes.md lines may be undated (taste_files); read_vetoes honours them, so the barber does too."""
    (lib_dir / "taste").mkdir(exist_ok=True)
    (lib_dir / "taste/vetoes.md").write_bytes(
        b"# Vetoes\n\n- lifted: Lumen Sato - Glass Elevator <!-- key:veto:6 -->\n"
        b"good pair: Marlo Venn - Stairwell Echo + Odelia Strand - Last Train Social <!-- key:pair: 15 , 11 -->\n"
    )
    assert read_keys(lib_dir / "taste/vetoes.md") == {"veto:6", "pair:11,15"}  # canonical keys
    assert {"veto:6", "pair:11,15"} <= barber.known_keys(libfolder.LibraryFolder(lib_dir))
    assert read_entries(lib_dir / "taste/vetoes.md") == []  # the dated-line reader would miss both
    plain = barber.plan_session(lib, facts, today=D1)
    assert {"veto:6", "pair:11,15"} <= {q.key for q in plain.questions}  # asked when nothing is known
    session, _ = barber.start(lib_dir, today=D1)
    assert not {"veto:6", "pair:11,15"} & {q.key for q in session.questions}


def test_a_broken_state_file_starts_a_new_plan(lib_dir):
    (lib_dir / ".cache").mkdir(exist_ok=True)
    for junk in (b"{not json", b'{"schema": 99}', b"\xff\xfe", b'{"schema": 1, "date": "2026-10-21"}'):
        (lib_dir / ".cache/barber.json").write_bytes(junk)
        assert barber.load_session(lib_dir, today=D1) is None
        session, resumed = barber.start(lib_dir, today=D1)
        assert resumed is False and len(session.questions) == 8


def test_session_json_round_trip(lib, facts):
    session = barber.plan_session(lib, facts, today=D1, source="exports/2026-10-20-collection.xml")
    session.answers[1] = {"status": "answered", "answer": "Rollers", "added": ["- [2026-10-21] x <!-- key:y -->"]}
    data = json.loads(json.dumps(session.to_json()))
    back = barber.Session.from_json(data)
    assert back.to_json() == session.to_json() and back.questions == session.questions
    with pytest.raises(barber.BarberError):
        barber.Session.from_json({**data, "questions": data["questions"][::-1]})


def test_record_without_a_session_today_is_refused(lib_dir):
    barber.start(lib_dir, today=D1)
    before = snapshot(lib_dir)
    with pytest.raises(barber.BarberError, match="barber next"):
        barber.answer(lib_dir, 1, "A", today=D2)  # yesterday's session
    assert snapshot(lib_dir) == before


# -- what is written, and what never is -----------------------------------------------------------


def test_nothing_written_outside_taste_cache_and_log(lib_dir, tmp_path):
    before = snapshot(tmp_path)
    run_session(lib_dir)
    barber.next_step(lib_dir, today=D1)
    after = snapshot(tmp_path)
    changed = {p for p in after if before.get(p) != after[p]}
    assert changed and all(
        p.startswith(("dj-library/taste/", "dj-library/.cache/")) or p == "dj-library/log.md" for p in changed
    ), changed
    assert set(before) <= set(after)  # nothing removed: the export and the DJ's XML untouched
    log = read(lib_dir / "log.md")
    assert log.startswith(before["dj-library/log.md"].decode("utf-8"))  # appended only (R-904)
    barber_lines = [line for line in log.splitlines() if " barber -> " in line]
    assert len(barber_lines) == 8 and barber_lines[0].startswith("2026-10-21 00:00 barber -> 1 line added; taste/")
    assert not list(tmp_path.rglob("*.tmp"))


def test_no_absolute_paths_in_the_library_folder(lib_dir, tmp_path):
    run_session(lib_dir)
    for rel in ("taste/anchors.md", "taste/lanes.md", "taste/vetoes.md", "taste/feedback.md", ".cache/barber.json", "log.md"):
        text = read(lib_dir / rel)
        assert str(tmp_path) not in text and tmp_path.as_posix() not in text, rel
        assert "D:/Music" not in text, rel  # track locations stay in the export
    state = json.loads(read(lib_dir / ".cache/barber.json"))
    assert state["source"] == "exports/2026-10-20-collection.xml"


def test_no_write_session_to_master_db(lib_dir, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("Style Barber touched master.db")

    monkeypatch.setattr(safety, "open_db", refuse)
    monkeypatch.setattr(safety, "backup", refuse)
    run_session(lib_dir)
    barber.next_step(lib_dir, today=D1)


def test_a_folder_that_is_not_a_library_is_refused(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    for call in (lambda: barber.next_step(plain, today=D1), lambda: barber.answer(plain, 1, "A", today=D1)):
        with pytest.raises(NotALibraryFolder):
            call()
    assert list(plain.iterdir()) == []


# -- the CLI ------------------------------------------------------------------------------------


def invoke(*args: str):
    return runner.invoke(cli.app, ["library", "barber", *args])


def test_cli_next_and_record_json(lib_dir):
    result = invoke("next", "--library", str(lib_dir), "--today", "2026-10-21", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert list(data)[0] == "counts" and data["counts"]["questions"] == 8 and data["resumed"] is False
    q = data["question"]
    assert q["n"] == 1 and q["progress"] == "Question 1 of 8 · about 8 minutes left"
    answer = ANSWERS[q["kind"]]
    rec = invoke("record", str(q["n"]), answer, "--library", str(lib_dir), "--today", "2026-10-21", "--json")
    assert rec.exit_code == 0, rec.output
    out = json.loads(rec.output)
    assert list(out)[0] == "counts" and out["counts"]["lines_added"] == 1
    assert out["recorded"] == {"n": 1, "kind": q["kind"], "answer": answer, "status": "answered", "file": q["file"]}
    assert out["added"][q["file"]][0].startswith("- [2026-10-21] ")
    assert out["log"].startswith("2026-10-21 00:00 barber -> 1 line added; taste/")
    assert out["next"]["n"] == 2 and out["done"] is False


def test_cli_text_output_and_done(lib_dir):
    text = invoke("next", "--library", str(lib_dir), "--today", "2026-10-21")
    assert text.exit_code == 0
    lines = text.output.splitlines()
    assert lines[0] == "barber: 0 answered, 0 skipped, 8 left of 8"
    assert lines[1] == "Question 1 of 8 · about 8 minutes left"
    assert "answer: dj library barber record 1 <text|skip>" in text.output
    session = barber.load_session(lib_dir, today=D1)
    for q in session.questions[:-1]:
        assert invoke("record", str(q.n), ANSWERS[q.kind], "--library", str(lib_dir), "--today", "2026-10-21").exit_code == 0
    last = invoke("record", "8", "skip", "--library", str(lib_dir), "--today", "2026-10-21")
    assert last.exit_code == 0 and "question 8 skipped (skip) -> 0 lines added to no file" in last.output
    assert "done for today: taste/" in last.output
    again = invoke("next", "--library", str(lib_dir), "--today", "2026-10-21")
    assert "(resumed)" in again.output and "done for today" in again.output


def test_cli_errors_and_refusals(lib_dir, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert invoke("next", "--library", str(plain)).exit_code == 2
    assert invoke("record", "1", "A", "--library", str(plain)).exit_code == 2
    no_session = invoke("record", "1", "A", "--library", str(lib_dir), "--today", "2026-10-21")
    assert no_session.exit_code == 1 and "barber next" in no_session.output
    invoke("next", "--library", str(lib_dir), "--today", "2026-10-21")
    before = snapshot(lib_dir)
    session = barber.load_session(lib_dir, today=D1)
    ab = next(q for q in session.questions if q.kind == "ab")
    bad = invoke("record", str(ab.n), "Z", "--library", str(lib_dir), "--today", "2026-10-21")
    assert bad.exit_code == 1 and "not an answer" in bad.output and "A (1) or B (2), or skip" in bad.output
    assert invoke("record", "12", "A", "--library", str(lib_dir), "--today", "2026-10-21").exit_code == 1
    assert invoke("next", "--library", str(lib_dir), "--today", "21-10-2026").exit_code == 1
    assert snapshot(lib_dir) == before
    empty = tmp_path / "empty-library"
    libfolder.scaffold(empty, device="mac", today=D0)
    no_export = invoke("next", "--library", str(empty), "--today", "2026-10-21")
    assert no_export.exit_code == 1 and "export" in no_export.output.lower()


def test_cli_takes_the_mcp_argument_shape(lib_dir, monkeypatch):
    """The MCP server runs `dj library barber record --json -- <n> <answer>` in the configured folder."""
    monkeypatch.setenv(libfolder.ENV_VAR, str(lib_dir))
    assert invoke("next", "--today", "2026-10-21", "--json").exit_code == 0
    session = barber.load_session(lib_dir, today=D1)
    veto = next(q for q in session.questions if q.kind == "veto")
    done = invoke("record", "--today", "2026-10-21", "--json", "--", str(veto.n), "Never")
    assert done.exit_code == 0, done.output
    assert read_vetoes(lib_dir / "taste/vetoes.md").blocks(veto.track_ids[0])
    ab = next(q for q in session.questions if q.kind == "ab")
    dash = invoke("record", "--today", "2026-10-21", "--json", "--", str(ab.n), "--apply")
    assert dash.exit_code == 1 and "not an answer" in dash.output  # a value, never an option


# -- the MCP tools --------------------------------------------------------------------------------


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"x": 1}', stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    return seen


def test_mcp_tools_are_fixed_argument_lists(calls):
    m.dj_barber_next()
    cmd, kwargs = calls[-1]
    assert cmd[3:] == ["library", "barber", "next", "--json"] and isinstance(cmd, list) and "shell" not in kwargs
    m.dj_barber_record(3, "A")
    assert calls[-1][0][3:] == ["library", "barber", "record", "--json", "--", "3", "A"]
    m.dj_barber_record(1, "  Peak hour ")
    assert calls[-1][0][-1] == "Peak hour"
    m.dj_barber_record(2, "--apply")
    assert calls[-1][0][-3:] == ["--", "2", "--apply"]  # after `--`: never an option


def test_mcp_record_checks_its_input(calls):
    for n, answer in ((0, "A"), (9, "A"), (True, "A"), (1, ""), (1, "   "), (1, "x" * 401), (1, "a\nb")):
        out = json.loads(m.dj_barber_record(n, answer))
        assert out["ok"] is False and out["exit_code"] == 1
    assert calls == []


def test_mcp_refusal_says_not_a_library_folder_never_rekordbox(tmp_path, monkeypatch):
    """Exit code 2 from `dj library barber` means "not a dj-library folder" (the real CLI, no mock)."""
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv(libfolder.ENV_VAR, str(plain))
    for call in (m.dj_barber_next, lambda: m.dj_barber_record(1, "A")):
        out = json.loads(call())
        assert (out["ok"], out["exit_code"]) == (False, 2), out
        assert any("not a dj-library folder" in line for line in out["stderr"]), out
        assert out["hint"] == m.NO_LIBRARY and "dj-start" in out["hint"], out["hint"]  # never "close rekordbox"
    assert list(plain.iterdir()) == []
    assert "dj-start" in m.server.instructions  # what a not-set-up library folder needs


def test_mcp_exit_2_hint_follows_the_refusal(monkeypatch):
    """Exit code 2 is read from stderr (mcp_server.refusal_hint): the barber's REFUSED line about a
    missing library.yaml means "run dj-start"; the rekordbox check's STOP line means rekordbox is open."""
    not_library = "REFUSED plain is not a dj-library folder (no library.yaml). Run dj-start first."
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **k: SimpleNamespace(returncode=2, stdout="", stderr=not_library))
    assert json.loads(m.dj_barber_next())["hint"] == m.NO_LIBRARY
    assert json.loads(m.dj_barber_record(1, "A"))["hint"] == m.NO_LIBRARY
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **k: SimpleNamespace(
        returncode=2, stdout="", stderr="STOP rekordbox.exe is running. Close it, then retry."))
    assert json.loads(m.dj_barber_next())["hint"] == m.REKORDBOX_OPEN


def test_mcp_annotations():
    import asyncio

    tools = {t.name: t for t in asyncio.run(m.server.list_tools())}
    for name in ("dj_barber_next", "dj_barber_record"):
        ann = tools[name].annotations
        assert ann.read_only_hint is False and ann.destructive_hint is False
    assert set(tools["dj_barber_record"].input_schema["properties"]) == {"n", "answer"}
    assert tools["dj_barber_next"].input_schema.get("properties", {}) == {}


# -- the skill script -----------------------------------------------------------------------------


def run_script(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=env)  # fmt: skip


def test_script_next_and_record(lib_dir, tmp_path):
    done = run_script("next", "--library", str(lib_dir), "--today", "2026-10-21", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["ok"] is True and out["question"]["n"] == 1 and out["counts"]["left"] == 8
    q = out["question"]
    rec = run_script("record", "1", ANSWERS[q["kind"]], "--library", str(lib_dir), "--today", "2026-10-21", cwd=tmp_path)
    assert rec.returncode == 0, rec.stderr
    data = json.loads(rec.stdout)
    assert data["ok"] is True and data["counts"]["lines_added"] == 1 and data["next"]["n"] == 2
    bad = run_script("record", "2", "nope", "--library", str(lib_dir), "--today", "2026-10-21", cwd=tmp_path)
    assert bad.returncode == 1 and "not an answer" in json.loads(bad.stdout)["error"]


def test_script_refuses_and_errors(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    done = run_script("next", "--library", str(plain), cwd=tmp_path)
    assert done.returncode == 2 and "library.yaml" in json.loads(done.stdout)["refused"]
    assert list(plain.iterdir()) == []
    for args in ((), ("next",), ("record", "1", "--library", str(plain)), ("record", "x", "A", "--library", str(plain))):
        done = run_script(*args, cwd=tmp_path)
        assert done.returncode == 1 and json.loads(done.stdout)["ok"] is False, args


def test_script_runs_without_engine_packages(lib_dir, tmp_path):
    code = textwrap.dedent(f"""
        import runpy, sys
        for name in ("pyrekordbox", "rapidfuzz", "httpx", "typer", "mcp"):
            sys.modules[name] = None
        sys.argv = ["barber.py", "next", "--library", {str(lib_dir)!r}, "--today", "2026-10-21"]
        runpy.run_path({str(SCRIPT)!r}, run_name="__main__")
    """)
    env = dict(os.environ, PYTHONUTF8="1")
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=env)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["counts"]["questions"] == 8


# -- the skill (R-701, R-702, R-703) --------------------------------------------------------------


def _skill_text() -> tuple[dict, str]:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    m_ = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    return yaml.safe_load(m_.group(1)), m_.group(2)


def test_skill_md():
    meta, body = _skill_text()
    assert meta["name"] == "dj-barber" and meta["description"].strip()
    assert "**Requirements:** R-701, R-702, R-703, R-1405." in body
    assert "[shared/voice.md](../../shared/voice.md)" in body and "[shared/adhd.md](../../shared/adhd.md)" in body
    for needle in (
        "one question", "never ask two in one reply", "Question 3 of 8 · about 6 minutes left",
        "under 10 minutes", "stop at any moment", "A / B", "numbered version", "Reply 1 or 2",
        "scripts/barber.py next --library DIR", "scripts/barber.py record N ANSWER --library DIR",
        "dj library barber next", "dj library barber record", "dj_barber_next()", "dj_barber_record(n, answer)",
        "taste/anchors.md", "taste/lanes.md", "taste/vetoes.md", "taste/feedback.md",
        "never propose", "never pair", "Crate me never picks that track", "read_vetoes", "skip",
        "a gig\n  answered once is not asked about again",
    ):  # fmt: skip
        assert needle in body, needle
    # nothing in the codebase makes the structure proposals honour vetoes: the skill must not promise it
    assert "proposals leave it out" not in body and "do not read vetoes" in body


def test_skill_example_replies_follow_the_rules():
    """The shared chat-reply checker (the one W-28's transcript check runs) passes every example."""
    _, body = _skill_text()
    examples = re.findall(r"```text\n(.*?)\n```", body, re.DOTALL)
    assert len(examples) >= 3
    for reply in examples:
        lines = [line for line in reply.split("\n") if line.strip()]
        assert reply_problems(reply) == [], reply
        assert any(f"taste/{name}" in reply for name in ("anchors.md", "lanes.md", "vetoes.md", "feedback.md"))
        assert PROGRESS.match(re.split(r"\. ", next(line for line in lines if line.startswith("Question")))[0])
        assert sum(line.count("?") for line in lines) == 1, reply  # one question per reply
        assert re.search(r"\((under|about) (a|\d+) minutes?\)\.?$", lines[-1]), lines[-1]  # ends with < 2 min


def test_vetoes_md_from_the_barber_reads_like_a_hand_written_one(tmp_path):
    """The barber's lines and the format dj-taste documents parse the same way."""
    path = tmp_path / "vetoes.md"
    append_entries(path, "Vetoes", [Entry("veto:16", "never propose: Kestrel Unit - Ferrous")], today=D1)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("- [2026-10-21] never pair: Grid Saint - Pressure Vessel + Okoro Lane - Sunday Sermon <!-- key:pair:17,1 -->\n")
    assert read_vetoes(path) == Vetoes(frozenset({"16"}), frozenset({frozenset({"1", "17"})}))
