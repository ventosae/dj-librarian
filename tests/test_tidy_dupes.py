"""Duplicate groups and the keeper suggestion. Report only."""

from pathlib import Path

from tidy_fixtures import row

from dj.library import to_track_info
from dj.tidy import dupes
from dj.tidy.checks import FileFacts, Item
from dj.tidy.tags import StreamInfo, Tags


def it(name, artist="Huerta", title="Low Five", mix="", container="mp3", kbps=320, dur=300.0, sha=None, rb=True,
       cues=0, rating=0, art=True, size=1000):
    stream = StreamInfo(container, kbps, False, 44100, 16 if container != "mp3" else None, dur)
    tags = Tags(artist=(artist,) if artist else (), title=title, mix=mix, has_art=art)
    path = Path(f"C:/Music/x/{name}")
    f = FileFacts(path, True, size, 1.0, sha, container, stream, tags, None)
    info = to_track_info(row(cid=name, path=path.as_posix(), ArtistName=artist, Title=title, Cues=[object()] * cues,
                             Rating=rating)) if rb else None
    return Item(f, info, None, True)


def test_exact_groups_by_hash():
    a, b, c = it("a.mp3", sha="h1"), it("b.mp3", sha="h1"), it("c.mp3", sha="h2")
    groups = dupes.exact_groups([a, b, c])
    assert len(groups) == 1 and groups[0].kind == "exact" and set(groups[0].members) == {a, b}
    assert groups[0].as_dict()["members"][0]["sha256"] == "h1"


def test_fuzzy_groups_match_on_artist_title_and_duration():
    a = it("Huerta - Low Five.mp3", dur=300)
    b = it("huerta - low five (1).mp3", dur=301.5)
    far = it("Huerta - Low Five (long).mp3", dur=330)
    other = it("Octo Octa - Loops.mp3", artist="Octo Octa", title="Loops")
    groups = dupes.fuzzy_groups([a, b, far, other], tolerance_s=2)
    assert len(groups) == 1 and set(groups[0].members) == {a, b}


def test_fuzzy_keeps_versions_apart_but_treats_original_mix_as_the_original():
    orig = it("a.mp3", title="Low Five")
    orig_mix = it("b.mp3", title="Low Five (Original Mix)")
    ext = it("c.mp3", title="Low Five", mix="Extended Mix")
    groups = dupes.fuzzy_groups([orig, orig_mix, ext])
    assert len(groups) == 1 and set(groups[0].members) == {orig, orig_mix}


def test_fuzzy_falls_back_to_rekordbox_row_then_filename():
    no_tags = it("Huerta - Low Five.mp3")
    no_tags = Item(FileFacts(no_tags.file.path, True, 1, 1.0, None, "mp3", no_tags.file.stream, Tags(), None),
                   no_tags.rb, None, True)
    assert dupes.fuzzy_key(no_tags) == ("huerta", "low five", "")
    orphan = Item(no_tags.file, None, None, True, parsed=None)
    assert dupes.fuzzy_key(orphan) is None
    from dj.tidy import names

    parsed = Item(no_tags.file, None, None, True, parsed=names.parse_filename("Huerta - Low Five (Dub)"))
    assert dupes.fuzzy_key(parsed) == ("huerta", "low five", "dub")


def test_fuzzy_skips_groups_that_are_already_exact():
    a, b = it("a.mp3", sha="h"), it("b.mp3", sha="h")
    exact = dupes.exact_groups([a, b])
    assert dupes.fuzzy_groups([a, b], skip=exact) == []
    assert len(dupes.fuzzy_groups([a, b])) == 1


def test_keeper_ranking():
    flac = it("a.flac", container="flac", kbps=None, rb=False)
    mp3_320_rb = it("b.mp3", cues=3)
    mp3_128 = it("c.mp3", kbps=128, cues=9)
    keeper, reason = dupes.suggest_keeper([mp3_128, mp3_320_rb, flac])
    assert keeper is flac and reason.startswith("lossless flac")
    keeper, reason = dupes.suggest_keeper([mp3_128, mp3_320_rb])
    assert keeper is mp3_320_rb and "3 cue(s)" in reason and "in rekordbox" in reason
    a, b = it("a.mp3", cues=1), it("b.mp3", cues=2)
    assert dupes.suggest_keeper([a, b])[0] is b
    assert dupes.suggest_keeper([])[0] is None
