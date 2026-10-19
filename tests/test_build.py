from pathlib import Path

import pytest
from test_push import FakeSpotify, item

from dj import build, match
from dj.match import AMBIGUOUS, MATCH, MISSING, Local

TEXT = """Tracklisting
Acapella - Doug Willis 'You Can Do It' Pt. 1
01. Jason Hersco - I Was Young (Justinique Remix)
[12:30] Nicky Night Time – A History
3) Mark Broom - Midnight

# a comment
just chatter without a dash
Inner City - Pennies From Heaven
"""


def test_parse_keeps_track_lines_and_reports_the_rest():
    tracks, skipped = build.parse_tracklist(TEXT)
    assert [(t.artist, t.title) for t in tracks] == [
        ("Acapella", "Doug Willis 'You Can Do It' Pt. 1"),
        ("Jason Hersco", "I Was Young (Justinique Remix)"),
        ("Nicky Night Time", "A History"),
        ("Mark Broom", "Midnight"),
        ("Inner City", "Pennies From Heaven"),
    ]
    assert [t.content_id for t in tracks] == ["2", "3", "4", "5", "9"]
    assert skipped == ["Tracklisting", "just chatter without a dash"]


def test_load_tracklist_errors(tmp_path):
    with pytest.raises(build.BuildError, match="not found"):
        build.load_tracklist(tmp_path / "nope.txt")
    empty = tmp_path / "empty.txt"
    empty.write_text("Tracklisting\n\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match="No 'Artist - Title'"):
        build.load_tracklist(empty)


def test_default_name_and_key():
    assert build.default_name(Path("tracklists/moderna_jazz_house.txt")) == "moderna jazz house"
    assert build.key("Moderna Jazz House") == build.key("moderna jazz house") == "build:moderna_jazz_house"


def test_text_tracks_match_without_a_duration():
    """No duration on a text line: a confident title + artist is a MATCH, not AMBIGUOUS."""
    api = FakeSpotify([item("Midnight", "Mark Broom", 421_000)])
    local = Local("1", "Mark Broom", "Midnight")
    assert build.match_all(api, [local])[0].status == MATCH
    # the plain matcher still checks the length (dj push relies on it)
    assert match.decide(local, []).status == MISSING
    cand = match.Candidate(uri="u", title="Midnight", artists=["Mark Broom"], duration_ms=421_000)
    assert match.decide(local, [cand]).status == AMBIGUOUS
    assert match.decide(local, [cand], ignore_duration=True).status == MATCH


def test_a_different_version_is_still_ambiguous():
    api = FakeSpotify([item("I Was Young - Original Mix", "Jason Hersco", 400_000)])
    local = Local("1", "Jason Hersco", "I Was Young (Justinique Remix)")
    r = build.match_all(api, [local])[0]
    assert r.status == AMBIGUOUS and "version differs" in r.reasons


def test_apply_creates_once_under_its_own_state_and_description(tmp_path):
    api, state = FakeSpotify(), tmp_path / "state" / "build.json"
    first = build.apply(api, "Moderna Jazz House", ["u1", "u2"], state)
    again = build.apply(api, "moderna jazz house", ["u1", "u2", "u3"], state)
    assert (first["created"], first["added"]) == (True, 2)
    assert (again["created"], again["added"]) == (False, 1)
    assert api.created == ["Moderna Jazz House"] and api.playlists["pl1"] == ["u1", "u2", "u3"]
    assert "build:moderna_jazz_house" in state.read_text(encoding="utf-8")
