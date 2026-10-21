"""Q-19 / R-702: `taste/feedback.md` scores Crate me's picks.

A dated line whose text starts with `+ Artist - Title: note` says the track worked at a gig, `-
Artist - Title: note` that it flopped (`- [2026-10-22] + Ada Arden - Signal 101: packed the floor`).
Crate me adds +1 / -1 to the matched track's score (every copy of the song; the latest line for a
song decides) and never takes a flopped track as a spare. The barber's gig answer writes the lines.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from test_crate import NOW, facts, folder, lib, spec_of  # noqa: F401  (fixtures)

from dj import barber, crate
from dj.model import Track
from dj.taste_files import (
    FLOPPED,
    WORKED,
    GigFeedback,
    Vetoes,
    append_entries,
    feedback_scores,
    read_gig_feedback,
    read_keys,
    signed_feedback,
)

D1, D2 = date(2026, 10, 21), date(2026, 10, 22)


def write_feedback(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Gig feedback\n\n## Log\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


# -- the two line shapes ---------------------------------------------------------------------


@pytest.mark.parametrize("text, want", [
    ("+ Ada Arden - Signal 101: packed the floor", (WORKED, "Ada Arden - Signal 101: packed the floor")),
    ("- Ada Arden - Signal 101: cleared the floor", (FLOPPED, "Ada Arden - Signal 101: cleared the floor")),
    ("+   Ada Arden - Signal 101", (WORKED, "Ada Arden - Signal 101")),
    ("what worked at Gig Rooftop: Ada Arden - Signal 101", None),  # a remark
    ("- not much worked", None),  # a sign but no "Artist - Title"
    ("+Ada Arden - Signal 101", None),  # the sign stands alone
])  # fmt: skip
def test_signed_feedback_reads_the_two_shapes(text, want):
    assert signed_feedback(text) == want


def test_read_gig_feedback_keeps_signed_lines_and_the_latest_line_per_key(tmp_path):
    path = write_feedback(tmp_path / "feedback.md", [
        "- [2026-10-21] + Ada Arden - Signal 101: packed the floor <!-- key:gig:rooftop -->",
        "- [2026-10-21] - Bram Arden - Signal 102: cleared the floor",
        "- [2026-10-21] what worked at Gig Rooftop: the closers <!-- key:gig:warehouse -->",
        "- [2026-10-22] updated: - Ada Arden - Signal 101: second look, too dark <!-- key:gig:rooftop -->",
        "+ Cleo Arden - Signal 103: no date, not read",
    ])  # fmt: skip
    assert read_gig_feedback(path) == [
        GigFeedback(D1, FLOPPED, "Bram Arden - Signal 102: cleared the floor", None),
        GigFeedback(D2, FLOPPED, "Ada Arden - Signal 101: second look, too dark", "gig:rooftop"),
    ]
    assert read_gig_feedback(tmp_path / "missing.md") == []


def test_a_line_typed_with_the_sign_as_its_bullet(tmp_path):
    path = write_feedback(tmp_path / "feedback.md", [
        "+ [2026-10-22] Kestrel Unit - Ballast: packed the floor",  # the `+` bullet: worked
        "- [2026-10-22] Grid Saint - Pressure Vessel: cleared the floor",  # `-` is every line's bullet: a remark
        "+ [2026-10-22] - Okoro Lane - Sunday Sermon: emptied it",  # a sign after the date wins
        "+ [2026-10-22] the rooftop closers",  # no "Artist - Title": a remark
        "* [2026-10-22] Ada Arden - Signal 101: fine",
    ])  # fmt: skip
    assert read_gig_feedback(path) == [
        GigFeedback(D2, WORKED, "Kestrel Unit - Ballast: packed the floor", None),
        GigFeedback(D2, FLOPPED, "Okoro Lane - Sunday Sermon: emptied it", None),
    ]


def test_a_remix_named_only_in_the_remixer_field_is_another_song():
    """As vetoes count copies (`dup_key`): a flop on the original leaves its remix alone."""
    tracks = [Track(id="1", artist="Kestrel Unit", title="Brass Tide"),
              Track(id="2", artist="Kestrel Unit", title="Brass Tide", remixer="Dub Atelier"),
              Track(id="3", artist="KESTREL UNIT", title="Brass Tide (Original Mix)"),
              Track(id="4", artist="Kestrel Unit", title="Brass Tide", remixer="Dub Atelier")]  # fmt: skip
    flop = [GigFeedback(D1, FLOPPED, "Kestrel Unit - Brass Tide: emptied it", None)]
    assert feedback_scores(flop, tracks) == {"1": FLOPPED, "3": FLOPPED}
    assert set(feedback_scores(flop, tracks)) == Vetoes(frozenset({"1"})).with_copies(tracks).never_propose
    remix = [GigFeedback(D1, WORKED, "Kestrel Unit - Brass Tide (Dub Atelier Remix): packed it", None)]
    assert feedback_scores(remix, tracks) == {"2": WORKED, "4": WORKED}
    note = [GigFeedback(D1, WORKED, "Kestrel Unit - Brass Tide: Dub Atelier", None)]  # a note, not a remix
    assert feedback_scores(note, tracks) == {"1": WORKED, "3": WORKED}
    only_remix = [t for t in tracks if t.remixer]  # the original is not in the library
    assert feedback_scores(flop, only_remix) == {}


def test_crate_me_keeps_a_remix_as_a_spare_when_the_original_flopped(lib, facts):  # noqa: F811
    spare = lib.tracks[crate.select(lib, spec_of(), facts).spares[0].id]
    with_remix = replace(lib, tracks={**lib.tracks, spare.id: replace(spare, remixer="Dub Atelier")})
    base = crate.select(with_remix, spec_of(), facts)
    assert spare.id in {p.id for p in base.spares}
    flop = [GigFeedback(D1, FLOPPED, f"{spare.artist} - {spare.title}: emptied it", None)]  # the original
    scores = feedback_scores(flop, with_remix.tracks.values())
    assert spare.id not in scores
    after = crate.select(with_remix, spec_of(), facts, feedback=scores)
    assert [(p.id, p.score) for p in after.spares] == [(p.id, p.score) for p in base.spares]


def test_feedback_scores_match_by_artist_and_title_for_every_copy():
    tracks = [Track(id="1", artist="Ada Arden", title="Signal 101"), Track(id="2", artist="ADA ARDEN", title="Signal 101"),
              Track(id="3", artist="Bjørk Ålund", title="Night: Part 2"), Track(id="4", artist="Gus", title="Other")]  # fmt: skip
    lines = [
        GigFeedback(D1, WORKED, "ada arden - signal 101: packed it", None),
        GigFeedback(D1, FLOPPED, "Bjork Alund - Night: Part 2: emptied it", None),  # a title with ": " in it
        GigFeedback(D1, WORKED, "Nobody - Not In The Library: great", None),
    ]
    assert feedback_scores(lines, tracks) == {"1": WORKED, "2": WORKED, "3": FLOPPED}


def test_the_latest_line_for_a_song_decides():
    tracks = [Track(id="1", artist="Ada Arden", title="Signal 101")]
    later_flop = [GigFeedback(D2, FLOPPED, "Ada Arden - Signal 101: x", None),
                  GigFeedback(D1, WORKED, "Ada Arden - Signal 101: y", None)]  # fmt: skip
    assert feedback_scores(later_flop, tracks) == {"1": FLOPPED}
    same_day = [GigFeedback(D1, FLOPPED, "Ada Arden - Signal 101", None),
                GigFeedback(D1, WORKED, "Ada Arden - Signal 101", None)]  # fmt: skip
    assert feedback_scores(same_day, tracks) == {"1": WORKED}  # same date: the later line


# -- Crate me: +1 / -1, and a flopped track is never a spare -------------------------------------


def _score(result: crate.CrateResult, tid: str) -> tuple[int, str] | None:
    hit = next((p for p in result.picks + result.spares if p.id == tid), None)
    return (hit.score, hit.reason) if hit else None


def test_worked_adds_one_to_the_selection_score(lib, facts):  # noqa: F811
    base = crate.select(lib, spec_of(), facts)
    pick = base.picks[-1]
    after = crate.select(lib, spec_of(), facts, feedback={pick.id: WORKED})
    score, reason = _score(after, pick.id)
    assert score == pick.score + 1 and reason.endswith("worked at a gig")
    assert after.counts["worked"] == 1 and after.counts["flopped"] == 0


def test_flopped_takes_one_off_and_is_never_a_spare(lib, facts):  # noqa: F811
    base = crate.select(lib, spec_of(), facts)
    pick, spare = base.picks[0], base.spares[0]
    after = crate.select(lib, spec_of(), facts, feedback={pick.id: FLOPPED, spare.id: FLOPPED})
    score, reason = _score(after, pick.id)
    assert score == pick.score - 1 and reason.endswith("flopped at a gig")
    assert spare.id not in {p.id for p in after.spares} and len(after.spares) == len(base.spares)
    assert after.counts["flopped"] == 2


def test_no_feedback_changes_nothing(lib, facts):  # noqa: F811
    base = crate.select(lib, spec_of(), facts)
    same = crate.select(lib, spec_of(), facts, feedback={})
    assert [(p.id, p.score, p.reason) for p in same.picks + same.spares] == [
        (p.id, p.score, p.reason) for p in base.picks + base.spares]  # fmt: skip


def test_preview_reads_taste_feedback_md(folder):  # noqa: F811
    first = crate.preview(folder, "sat", now=NOW)
    pick, spare = first.picks[-1], first.spares[0]
    write_feedback(folder.taste / "feedback.md", [
        f"- [2026-10-21] + {pick.track}: packed the floor <!-- key:gig:rooftop -->",
        f"- [2026-10-21] - {spare.track}: cleared the floor",
    ])  # fmt: skip
    p = crate.preview(folder, "sat", now=NOW)
    assert _score(p, pick.id) == (pick.score + 1, pick.reason + " · worked at a gig")
    assert spare.id not in {x.id for x in p.spares}
    assert p.preview_id != first.preview_id  # the feedback is part of what the DJ approves


# -- the barber's gig answer writes them ---------------------------------------------------------


@pytest.fixture
def gig_question() -> barber.Question:
    return barber.Question(n=8, total=8, kind="gig", key="gig:gigs-rooftop", prompt="What worked?", options=(),
                           chips=(), tracks=(), context="", subject="Gig Rooftop", file="taste/feedback.md")  # fmt: skip


def test_a_signed_gig_answer_becomes_signed_lines(tmp_path, gig_question):
    value = barber.parse_answer(gig_question, "+ Ada Arden - Signal 101: packed it ; - Bram Arden - Signal 102: cleared it")
    entries = barber.entries_for(gig_question, value)
    assert [(e.key, e.text) for e in entries] == [
        ("gig:gigs-rooftop", "+ Ada Arden - Signal 101: packed it"),
        ("gig:gigs-rooftop:2", "- Bram Arden - Signal 102: cleared it"),
    ]
    path = tmp_path / "feedback.md"
    added = append_entries(path, "Gig feedback", entries, today=D1)
    assert added[1] == "- [2026-10-21] - Bram Arden - Signal 102: cleared it <!-- key:gig:gigs-rooftop:2 -->"
    tracks = [Track(id="1", artist="Ada Arden", title="Signal 101"), Track(id="2", artist="Bram Arden", title="Signal 102")]
    assert feedback_scores(read_gig_feedback(path), tracks) == {"1": WORKED, "2": FLOPPED}


def _answer(path: Path, q: barber.Question, answer: str, day: date) -> list[str]:
    """What `barber.record` does with a gig answer: its lines, given the keys already in the file."""
    entries = barber.entries_for(q, barber.parse_answer(q, answer), read_keys(path))
    return append_entries(path, "Gig feedback", entries, today=day)


SONGS = [Track(id=str(n), artist=f"Art{n}", title=f"Song{n}") for n in (1, 2, 3)]


def test_a_shorter_re_answer_replaces_the_whole_gig_answer(tmp_path, gig_question):
    path = tmp_path / "feedback.md"
    _answer(path, gig_question, "+ Art1 - Song1: great; - Art2 - Song2: emptied it", D1)
    assert feedback_scores(read_gig_feedback(path), SONGS) == {"1": WORKED, "2": FLOPPED}
    added = _answer(path, gig_question, "+ Art3 - Song3: the one", D2)
    assert added == [
        "- [2026-10-22] updated: + Art3 - Song3: the one <!-- key:gig:gigs-rooftop -->",
        "- [2026-10-22] updated: withdrawn: not in the latest answer about Gig Rooftop <!-- key:gig:gigs-rooftop:2 -->",
    ]  # fmt: skip
    assert feedback_scores(read_gig_feedback(path), SONGS) == {"3": WORKED}  # Song1 and Song2 no longer count
    assert _answer(path, gig_question, "+ Art3 - Song3: the one", D2) == []  # the same answer again: nothing
    _answer(path, gig_question, "+ Art3 - Song3: the one; - Art1 - Song1: too dark", D2)  # :2 comes back
    assert feedback_scores(read_gig_feedback(path), SONGS) == {"3": WORKED, "1": FLOPPED}


def test_a_re_answer_can_withdraw_a_flop_on_a_later_track(tmp_path, gig_question):
    path = tmp_path / "feedback.md"
    _answer(path, gig_question, "+ Art1 - Song1: great; - Art2 - Song2: emptied it; - Art3 - Song3: no", D1)
    _answer(path, gig_question, "+ Art1 - Song1: great", D2)  # the base line is unchanged: no new line for it
    assert read_gig_feedback(path) == [GigFeedback(D1, WORKED, "Art1 - Song1: great", "gig:gigs-rooftop")]
    _answer(path, gig_question, "The rooftop closers worked", D2)  # a remark replaces a signed answer too
    assert read_gig_feedback(path) == []


def test_barber_record_withdraws_what_a_re_answer_leaves_out(folder):  # noqa: F811
    session, _ = barber.start(folder.root, today=D1)
    gig = next(q for q in session.questions if q.kind == "gig")
    barber.record(folder.root, session, gig.n, "+ Art1 - Song1: great; - Art2 - Song2: emptied it", today=D1)
    path = folder.taste / "feedback.md"
    assert feedback_scores(read_gig_feedback(path), SONGS) == {"1": WORKED, "2": FLOPPED}
    added = barber.record(folder.root, session, gig.n, "+ Art1 - Song1: great", today=D1)
    assert len(added) == 1 and added[0].endswith(f"<!-- key:{gig.key}:2 -->") and "withdrawn: " in added[0]
    assert feedback_scores(read_gig_feedback(path), SONGS) == {"1": WORKED}


def test_any_other_gig_answer_stays_a_remark(gig_question):
    for answer in ("The rooftop closers worked", "+ Ada Arden - Signal 101: yes; the rest was fine"):
        (entry,) = barber.entries_for(gig_question, barber.parse_answer(gig_question, answer))
        assert entry.key == "gig:gigs-rooftop" and entry.text.startswith("what worked at Gig Rooftop: ")
        assert signed_feedback(entry.text) is None


def test_the_skills_document_both_shapes():
    skills = Path(__file__).resolve().parents[1] / "plugin" / "skills"
    for name in ("dj-barber", "dj-crate"):
        text = (skills / name / "SKILL.md").read_text(encoding="utf-8")
        assert "+ Artist - Title: note" in text and "- Artist - Title: note" in text, name
        assert "taste/feedback.md" in text, name
