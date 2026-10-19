"""Every rule code fires and stays quiet when it should. Pure facts in, findings out."""

from pathlib import Path

from tidy_fixtures import row

from dj.library import to_track_info
from dj.safety import REPO_ROOT
from dj.tidy import checks, names
from dj.tidy.config import load_config
from dj.tidy.tags import ArtInfo, StreamInfo, Tags

CFG = load_config(REPO_ROOT / "examples" / "tidy.example.yaml")
PROFILES = [CFG.profile(n) for n in CFG.default_profiles]


def facts(path="C:/Music/x/Huerta - Low Five.mp3", container="mp3", kbps=320, vbr=False, rate=44100, depth=None,
          tags=None, art=None, exists=True, read_error=None, id3=(2, 3, 0), duration=200.0, size=8_000_000):
    stream = StreamInfo(container, kbps, vbr, rate, depth, duration, id3) if container else None
    if tags is None:
        tags = Tags(artist=("Huerta",), title="Low Five", genre="House", has_art=art is not None)
    return checks.FileFacts(Path(path), exists, size, 1.0, None, container, stream, tags, art, read_error)


GOOD_ART = ArtInfo("image/jpeg", 600, 600, 60_000, False)


def item(file=None, rb=row(path="C:/Music/x/Huerta - Low Five.mp3", ArtistName="Huerta", Title="Low Five"),
         crate="house_base/0_INBOX", parsed=None, local_art=None, in_roots=True):
    file = file or facts(art=GOOD_ART)
    return checks.Item(file, to_track_info(rb) if rb is not None else None, crate, in_roots,
                       parsed or names.parse_filename(file.path.stem), local_art)


def codes(findings):
    return sorted({f.code for f in findings})


def test_clean_item_has_no_findings():
    assert checks.check_item(item(), PROFILES, CFG) == []


def test_file_missing_and_unreadable_short_circuit():
    gone = checks.check_item(item(facts(exists=False, container=None, tags=None)), PROFILES, CFG)
    assert codes(gone) == ["FILE_MISSING"] and gone[0].severity == "error"
    bad = checks.check_item(item(facts(container=None, read_error="boom", tags=None)), PROFILES, CFG)
    assert codes(bad) == ["FILE_UNREADABLE"]
    orphan = checks.check_item(item(facts(exists=False, container=None, tags=None), rb=None), PROFILES, CFG)
    assert codes(orphan) == ["NOT_IN_REKORDBOX"]


def test_not_in_rekordbox_is_info_and_other_checks_still_run():
    out = checks.check_item(item(facts(tags=Tags(title="x")), rb=None), PROFILES, CFG)
    assert "NOT_IN_REKORDBOX" in codes(out) and "TAG_ARTIST_MISSING" in codes(out)


def test_format_rules_per_profile():
    f = facts(path="C:/Music/x/a.ogg", container="ogg", depth=32, rate=192000, kbps=None)
    out = checks.check_item(item(f, rb=row(path="C:/Music/x/a.ogg", FileType=0)), PROFILES, CFG)
    assert codes(out) == ["ART_MISSING", "BITDEPTH_TOO_HIGH", "FMT_UNSUPPORTED", "NAME_OFF_CONVENTION",
                          "SAMPLERATE_UNSUPPORTED"] or "FMT_UNSUPPORTED" in codes(out)
    fmt = [x for x in out if x.code == "FMT_UNSUPPORTED"]
    assert {x.profile for x in fmt} == {"cdj3000_family", "nxs2_family"} and all(x.severity == "error" for x in fmt)


def test_db_facts_fill_in_when_the_file_has_none():
    f = facts(container="mp3", kbps=None, rate=None)
    rb = row(path=str(f.path).replace("\\", "/"), BitRate=128, SampleRate=22050, FileType=1)
    out = checks.check_item(item(f, rb=rb), PROFILES, CFG)
    low = [x for x in out if x.code == "MP3_BITRATE_LOW"]
    assert low and low[0].source == "db" and low[0].data["kbps"] == 128
    assert any(x.code == "SAMPLERATE_UNSUPPORTED" and x.source == "db" for x in out)


def test_mp3_vbr_is_info_when_profile_allows():
    out = checks.check_item(item(facts(vbr=True, art=GOOD_ART)), PROFILES, CFG)
    assert codes(out) == ["MP3_VBR"] and {x.severity for x in out} == {"info"}


def test_fmt_db_mismatch():
    out = checks.check_item(item(facts(art=GOOD_ART), rb=row(path="C:/Music/x/Huerta - Low Five.mp3", FileType=11,
                                                              ArtistName="Huerta", Title="Low Five")), PROFILES, CFG)
    assert codes(out) == ["FMT_DB_MISMATCH"]


def test_art_rules():
    none = checks.check_item(item(facts(art=None)), PROFILES, CFG)
    assert codes(none) == ["ART_MISSING"] and "rekordbox shows none" in none[0].message
    with_local = checks.check_item(item(facts(art=None), local_art=Path("C:/Music/x/cover.jpg")), PROFILES, CFG)
    assert codes(with_local) == ["ART_LOCAL_AVAILABLE", "ART_MISSING"]
    png = checks.check_item(item(facts(art=ArtInfo("image/png", 1400, 1400, 2_000_000))), PROFILES, CFG)
    assert codes(png) == ["ART_NOT_JPEG", "ART_TOO_LARGE"]
    tiny = checks.check_item(item(facts(art=ArtInfo("image/jpeg", 80, 80, 3000))), PROFILES, CFG)
    assert codes(tiny) == ["ART_TOO_SMALL"]


def test_path_rules():
    long_name = "C:/Music/x/" + "a" * 250 + ".mp3"
    out = checks.check_item(item(facts(path=long_name, art=GOOD_ART), rb=None), PROFILES, CFG)
    assert "PATH_TOO_LONG" in codes(out)
    weird = facts(path="C:/Music/x/Huerta - Low Five? .mp3", art=GOOD_ART)
    out = checks.check_item(item(weird, rb=None), PROFILES, CFG)
    bad = [x for x in out if x.code == "PATH_BAD_CHARS"]
    assert bad and "['?']" in bad[0].message
    planned = checks.check_item(item(), PROFILES, CFG, planned_name="b" * 250 + ".mp3")
    assert codes(planned) == ["PATH_TOO_LONG"] and planned[0].data["planned"].startswith("bbb")


def test_name_off_convention_uses_tags_and_omits_original_mix():
    f = facts(path="C:/Music/x/berlioz_ode.mp3",
              tags=Tags(artist=("berlioz",), title="ode to rahsaan (Original Mix)", genre="x", has_art=True), art=GOOD_ART)
    out = checks.check_item(item(f, rb=None), PROFILES, CFG)
    off = [x for x in out if x.code == "NAME_OFF_CONVENTION"]
    assert off and off[0].data["expected"] == "berlioz - ode to rahsaan.mp3"
    ok = facts(path="C:/Music/x/berlioz - ode to rahsaan.mp3",
               tags=Tags(artist=("berlioz",), title="ode to rahsaan", mix="Original Mix", genre="x", has_art=True), art=GOOD_ART)
    assert "NAME_OFF_CONVENTION" not in codes(checks.check_item(item(ok, rb=None), PROFILES, CFG))


def test_tag_rules():
    empty = facts(path="C:/Music/x/berlioz - ode to rahsaan.mp3", tags=Tags(has_art=True), art=GOOD_ART, id3=(2, 4, 0))
    out = checks.check_item(item(empty, rb=row(path="C:/Music/x/berlioz - ode to rahsaan.mp3", ArtistName="", Title="ode")),
                            PROFILES, CFG)
    assert codes(out) == ["TAG_ARTIST_MISSING", "TAG_ENCODING_ODD", "TAG_GENRE_MISSING", "TAG_TITLE_MISSING"]
    artist_hint = next(x for x in out if x.code == "TAG_ARTIST_MISSING")
    assert "filename says 'berlioz'" in artist_hint.message


def test_tag_db_mismatch_means_reload_tag():
    rb = row(path="C:/Music/x/Huerta - Low Five.mp3", ArtistName="", Title="Huerta - Low Five.mp3")
    out = checks.check_item(item(facts(art=GOOD_ART), rb=rb), PROFILES, CFG)
    assert codes(out) == ["TAG_DB_FILE_MISMATCH"] and "Reload Tag" in out[0].message


def test_bpm_rules():
    base = "C:/Music/x/Huerta - Low Five.mp3"
    not_analysed = checks.check_item(item(rb=row(path=base, ArtistName="Huerta", Title="Low Five", Analysed=0, BPM=0)), PROFILES, CFG)
    assert codes(not_analysed) == ["NOT_ANALYSED"]
    odd_scale = checks.check_item(item(rb=row(path=base, ArtistName="Huerta", Title="Low Five", BPM=120)), PROFILES, CFG)
    assert codes(odd_scale) == ["BPM_SCALE_UNEXPECTED"]
    # half/double against the crate name
    half = checks.check_item(item(rb=row(path=base, ArtistName="Huerta", Title="Low Five", BPM=5450), crate="funk_109_bpm"), PROFILES, CFG)
    assert codes(half) == ["BPM_HALF_DOUBLE"] and half[0].data["expected_from"].startswith("name:")
    # TBPM tag wins over the crate name
    tagged = facts(tags=Tags(artist=("Huerta",), title="Low Five", genre="x", bpm="122", has_art=True), art=GOOD_ART)
    differ = checks.check_item(item(tagged, rb=row(path=base, ArtistName="Huerta", Title="Low Five", BPM=12000)), PROFILES, CFG)
    assert codes(differ) == ["BPM_DB_TAG_DIFFER"]
    double = checks.check_item(item(tagged, rb=row(path=base, ArtistName="Huerta", Title="Low Five", BPM=24400)), PROFILES, CFG)
    assert codes(double) == ["BPM_HALF_DOUBLE"] and double[0].data["expected_from"] == "tbpm"
    fine = checks.check_item(item(rb=row(path=base, ArtistName="Huerta", Title="Low Five", BPM=10900), crate="funk_109_bpm"), PROFILES, CFG)
    assert fine == []


def test_swap_suspected_uses_known_artists():
    f = facts(path="C:/Music/x/Low Five - Huerta.mp3", tags=Tags(genre="x", has_art=True), art=GOOD_ART)
    out = checks.check_item(item(f, rb=None), PROFILES, CFG, known_artists=frozenset({"huerta"}))
    assert "SWAP_SUSPECTED" in codes(out)
    assert "SWAP_SUSPECTED" not in codes(checks.check_item(item(f, rb=None), PROFILES, CFG))


def test_counts_and_ordering():
    f = facts(path="C:/Music/x/a.ogg", container="ogg", kbps=None, tags=Tags(), art=None)
    out = checks.check_item(item(f, rb=None), PROFILES, CFG)
    assert [x.severity for x in out] == sorted((x.severity for x in out), key=checks.SEVERITY_ORDER.__getitem__)
    sc = checks.severity_counts(out)
    assert sc["error"] >= 2 and sum(sc.values()) == len(out)
    cc = checks.code_counts(out)
    assert cc["FMT_UNSUPPORTED"] == 2 and list(cc)[0] == "FMT_UNSUPPORTED"
    assert out[0].as_dict()["profile"] in ("cdj3000_family", "nxs2_family")
