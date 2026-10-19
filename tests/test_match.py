import pytest

from dj import match
from dj.match import AMBIGUOUS, MATCH, MISSING, Candidate, Local


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Beyoncé", "beyonce"),
        ("Simon & Garfunkel", "simon and garfunkel"),
        ("Sable Sun feat. Jon Sable", "sable sun"),
        ("Track ft Someone Else", "track"),
        ("Song (Live at Wembley) [2019]", "song"),
        ("  What's   Going -- On?! ", "what s going on"),
        (None, ""),
    ],
)
def test_normalise(text, expected):
    assert match.normalise(text) == expected


@pytest.mark.parametrize(
    "title, artist, expected",
    [
        ("Avenue Of The Palms (Sunset Mix)", "", ("avenue of the palms", "sunset mix")),
        ("Avenue of the Palms - Sunset Mix", "", ("avenue of the palms", "sunset mix")),
        ("vitara 3000 (Central Remix)", "", ("vitara 3000", "central remix")),
        ("Come Together", "", ("come together", "")),
        ("Come Together (Original Mix)", "", ("come together", "")),
        ("Song [2011 Remaster]", "", ("song", "2011 remaster")),
        ("Love - Part Two", "", ("love part two", "")),
        ("Chaos In The CBD & Jon Sable - Mahia Madness", "Chaos In The CBD & Jon Sable", ("mahia madness", "")),
        ("Youandewan & Huerta \u2013\u2013 Who R U?", "Youandewan, Huerta, Sugar Free, Junes", ("who r u", "")),
    ],
)
def test_parse_title_keeps_version_words_separately(title, artist, expected):
    assert match.parse_title(title, artist) == expected


def test_primary_artist():
    assert match.primary_artist("Chaos In The CBD & Jon Sable") == "chaos in the cbd"
    assert match.primary_artist("Youandewan, Huerta") == "youandewan"
    assert match.primary_artist("Simone de Kunovich & Pascal Moscheni -") == "simone de kunovich"


LOCAL = Local("1", "Massimiliano Pagliara", "Avenue Of The Palms (Sunset Mix)", duration_s=527, isrc="DECY62000003")


def cand(title, artists=("Massimiliano Pagliara",), ms=527_000, isrc="", uri=None):
    return Candidate(uri or f"spotify:track:{title}", title, list(artists), duration_ms=ms, isrc=isrc)


def test_confident_match():
    r = match.decide(LOCAL, [cand("Avenue of the Palms - Sunset Mix")])
    assert r.status == MATCH and r.pick.score >= 90


def test_isrc_match_wins_over_a_better_looking_title():
    r = match.decide(LOCAL, [cand("Avenue of the Palms - Sunset Mix"), cand("Avenue Palms - Sunset Mix", isrc="decy62000003")])
    assert r.status == MATCH and r.pick.isrc_match


def test_original_vs_local_version_is_ambiguous_never_a_match():
    r = match.decide(LOCAL, [cand("Avenue of the Palms")])
    assert r.status == AMBIGUOUS and "version differs" in r.reasons


def test_extended_mix_vs_local_original_is_ambiguous():
    local = Local("2", "Octo Octa", "Loops For Healing", duration_s=327)
    r = match.decide(local, [cand("Loops For Healing - Extended Mix", ["Octo Octa"], ms=327_000)])
    assert r.status == AMBIGUOUS


def test_different_remixers_do_not_match():
    local = Local("3", "seb wildblood", "vitara 3000 (Central Remix)", duration_s=439)
    r = match.decide(local, [cand("vitara 3000 - Other Guy Remix", ["Seb Wildblood"], ms=439_000)])
    assert r.status == AMBIGUOUS


def test_duration_off_is_ambiguous():
    r = match.decide(LOCAL, [cand("Avenue of the Palms - Sunset Mix", ms=540_000)])
    assert r.status == AMBIGUOUS and any("duration" in x for x in r.reasons)


def test_same_artist_other_track_is_missing():
    local = Local("4", "Chaos In The CBD", "Come Together", duration_s=393)
    r = match.decide(local, [cand("Digital Sound", ["Chaos In The CBD"], ms=380_000)])
    assert r.status == MISSING and r.pick is None


def test_score_thresholds(monkeypatch):
    local = Local("5", "A", "B", duration_s=100)
    for value, status in [(90, MATCH), (89, AMBIGUOUS), (75, AMBIGUOUS), (74, MISSING)]:
        monkeypatch.setattr(match.fuzz, "token_set_ratio", lambda a, b, v=value: v)
        assert match.decide(local, [cand("B", ["A"], ms=100_000)]).status == status


def test_no_candidates_is_missing():
    assert match.decide(LOCAL, []).status == MISSING


def test_compilation_artist_list_still_matches():
    local = Local("6", "Youandewan, Huerta, Sugar Free, Junes, Gene On Earth", "Youandewan & Huerta \u2013\u2013 Who R U?", duration_s=344)
    r = match.decide(local, [cand("Who R U?", ["Youandewan", "Huerta"], ms=344_186)])
    assert r.status == MATCH
