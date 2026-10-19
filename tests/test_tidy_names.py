"""Filename parsing and building. Golden cases come from real paths in plans/*.json."""

import pytest

from dj.tidy import names
from dj.tidy.config import NamingRules

RULES = NamingRules()


@pytest.mark.parametrize("stem, artist, title, mix, remixer, confidence", [
    ("berlioz - ode to rahsaan (Original Mix)", "berlioz", "ode to rahsaan", "Original Mix", None, "high"),
    ("Deza, dublon - Evolution (Original Mix)", "Deza, dublon", "Evolution", "Original Mix", None, "high"),
    ("Tour-Maubourg Ensemble - Stay", "Tour-Maubourg Ensemble", "Stay", None, None, "high"),
    ("Massimiliano Pagliara - Avenue Of The Palms (Sunset Mix)", "Massimiliano Pagliara",
     "Avenue Of The Palms", "Sunset Mix", None, "high"),
    ("seb wildblood - vitara 3000 (Central Remix)", "seb wildblood", "vitara 3000", "Central Remix", "Central", "high"),
    ("Simone de Kunovich & Pascal Moscheni - - Stone Island (Fantastic Man Remix)",
     "Simone de Kunovich & Pascal Moscheni", "Stone Island", "Fantastic Man Remix", "Fantastic Man", "high"),
    ("Chaos In The CBD & Jon Sable - Chaos In The CBD & Jon Sable - Mahia Madness",
     "Chaos In The CBD & Jon Sable", "Mahia Madness", None, None, "high"),
    ("Youandewan, Huerta, Sugar Free, Junes, Gene On Earth - Youandewan & Huerta –– Who R U-",
     "Youandewan, Huerta, Sugar Free, Junes, Gene On Earth", "Who R U", None, None, "high"),
    ("Chaos In The CBD - Come Together - Digital Sound - 02 Digital Sound",
     "Chaos In The CBD", "Digital Sound", None, None, "medium"),
    ("Octo Octa - Loops For Healing", "Octo Octa", "Loops For Healing", None, None, "high"),
    ("Palms Trax - Lost Control - Extended Mix", "Palms Trax", "Lost Control", "Extended Mix", None, "medium"),
    ("03 Huerta - Low Five", "Huerta", "Low Five", None, None, "medium"),
    ("A1 Huerta - Low Five", "Huerta", "Low Five", None, None, "medium"),
    ("Huerta_-_Low_Five", "Huerta", "Low Five", None, None, "medium"),
    ("Huerta - Low Five [Free Download]", "Huerta", "Low Five", None, None, "high"),
    ("Huerta - Low Five (Official Audio) [AUS-023]", "Huerta", "Low Five", None, None, "high"),
    ("Huerta - Low Five (Dam Swindle Rework)", "Huerta", "Low Five", "Dam Swindle Rework", "Dam Swindle", "high"),
    ("Huerta - Low Five (Hotmood Edit)", "Huerta", "Low Five", "Hotmood Edit", "Hotmood", "high"),
    ("Huerta - Low Five (Dub)", "Huerta", "Low Five", "Dub", None, "high"),
    ("Huerta - Low Five - Part Two", "Huerta", "Low Five - Part Two", None, None, "medium"),
])
def test_parse_patterns(stem, artist, title, mix, remixer, confidence):
    p = names.parse_filename(stem)
    assert (p.artist, p.title, p.mix, p.remixer) == (artist, title, mix, remixer)
    assert p.confidence == confidence, p


def test_feat_moves_out_of_the_title_and_back_into_the_tag_text():
    p = names.parse_filename("Ben Sun - Sable Sun feat. Jon Sable")
    assert (p.artist, p.title, p.feat) == ("Ben Sun", "Sable Sun", "Jon Sable")
    assert p.title_for_tag == "Sable Sun (feat. Jon Sable)"
    q = names.parse_filename("Ben Sun - Sable Sun (feat. Jon Sable) (Club Mix)")
    assert (q.title, q.feat, q.mix) == ("Sable Sun", "Jon Sable", "Club Mix")


def test_non_version_bracket_stays_in_the_title():
    p = names.parse_filename("Daft Punk - Around The World (Live 1997)")
    assert p.mix == "Live 1997"  # "live" is a version word in dj.match
    q = names.parse_filename("Herbie Hancock - Chameleon (Head Hunters)")
    assert (q.title, q.mix, q.confidence) == ("Chameleon (Head Hunters)", None, "high")


def test_low_confidence_cases():
    assert names.parse_filename("Loops For Healing").confidence == "low"
    assert names.parse_filename("Loops For Healing").artist is None
    assert names.parse_filename("").pattern == "empty"
    p = names.parse_filename("Extended Mix - Huerta")
    assert p.confidence == "low" and "version word" in " ".join(p.notes)


def test_bandcamp_album_form_records_the_album():
    p = names.parse_filename("Chaos In The CBD - Come Together - Digital Sound - 02 Digital Sound")
    assert p.album == "Come Together - Digital Sound" and p.pattern == "artist-album-track"


@pytest.mark.parametrize("mix, who", [
    ("Original Mix", None), ("Extended Mix", None), ("Sunset Mix", None), ("Club Mix", None),
    ("Fantastic Man Remix", "Fantastic Man"), ("Dr Packer Rework", "Dr Packer"),
    ("Late Nite Tuff Guy Edit", "Late Nite Tuff Guy"), ("Extended Remix", None),
    ("Radio Edit", None), ("Re-Edit", None), ("Dam Swindle Re-Edit", "Dam Swindle"), (None, None),
])
def test_remixer_from_mix(mix, who):
    assert names.remixer_from_mix(mix) == who


def test_swap_suspected():
    p = names.parse_filename("Low Five - Huerta")
    known = frozenset({"huerta", "octo octa"})
    assert names.swap_suspected(p, "", "", known) is True  # title is a known artist, artist is not
    assert names.swap_suspected(p, "Huerta", "", frozenset()) is True  # parsed title == tag artist
    assert names.swap_suspected(p, "", "Low Five", frozenset()) is True  # parsed artist == tag title
    ok = names.parse_filename("Huerta - Low Five")
    assert names.swap_suspected(ok, "Huerta", "Low Five", known) is False
    assert names.swap_suspected(ok, "", "", frozenset()) is False


def test_join_artists():
    assert names.join_artists(["A"], RULES) == "A"
    assert names.join_artists(["A", "B"], RULES) == "A & B"
    assert names.join_artists(["A", "B", "C"], RULES) == "A, B & C"
    assert names.join_artists(["", " "], RULES) == ""


@pytest.mark.parametrize("artist, title, mix, feat, expected", [
    ("berlioz", "ode to rahsaan", "Original Mix", None, "berlioz - ode to rahsaan.mp3"),
    ("Huerta", "Low Five", "Dam Swindle Rework", None, "Huerta - Low Five (Dam Swindle Rework).mp3"),
    ("Ben Sun feat. Jon Sable", "Sable Sun", None, None, "Ben Sun - Sable Sun (feat. Jon Sable).mp3"),
    ("Ben Sun", "Sable Sun (feat. Jon Sable)", None, "Jon Sable", "Ben Sun - Sable Sun (feat. Jon Sable).mp3"),
    ("AC/DC", "T.N.T.", None, None, "AC-DC - T.N.T.mp3"),
    ("Prince", 'Sign "O" The Times: Live?', None, None, "Prince - Sign 'O' The Times - Live.mp3"),
    ("Earth, Wind & Fire", "September", "Original Version", None, "Earth, Wind & Fire - September.mp3"),
    ("Röyksopp", "Eple", None, None, "Röyksopp - Eple.mp3"),
])
def test_build_filename(artist, title, mix, feat, expected):
    assert names.build_filename(artist, title, mix, ".mp3", RULES, feat=feat) == expected


def test_build_filename_normalises_nfc_and_extension_case():
    decomposed = "Röyksopp"  # o + combining diaeresis
    out = names.build_filename(decomposed, "Eple", None, "MP3", RULES)
    assert out == "Röyksopp - Eple.mp3" and out.startswith("Rö")


def test_sanitize_strips_controls_and_trailing_dots():
    assert names.sanitize("bad\x00name. ") == "badname"
    assert names.sanitize("a  <b>  c*") == "a b c"


def test_collision_free_is_casefold_and_counts_up():
    taken = ["Huerta - Low Five.mp3", "huerta - low five [2].MP3"]
    assert names.collision_free("Huerta - Low Five.mp3", taken) == "Huerta - Low Five [3].mp3"
    assert names.collision_free("Other.mp3", taken) == "Other.mp3"
    assert names.collision_free("noext", ["noext"]) == "noext [2]"


def test_same_name_is_nfc_casefold():
    assert names.same_name("Röyksopp.mp3", "röyksopp.MP3")
