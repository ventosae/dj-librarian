"""mutagen round trips on hand-built files. Every write must be temp + atomic replace."""


import pytest
from mutagen.id3 import ID3
from tidy_fixtures import jpeg_bytes, make_audio, png_bytes

from dj.tidy import TidyError, tags


@pytest.mark.parametrize("ext", [".mp3", ".wav", ".aiff", ".flac"])
def test_round_trip_write_read(tmp_path, ext):
    path = make_audio(tmp_path / f"a{ext}")
    before, stream, art = tags.read(path)
    assert before == tags.Tags() and art is None
    assert stream.sample_rate == 44100 and stream.duration_s and 0.9 < stream.duration_s < 1.2
    assert stream.container == ext.lstrip(".")

    tags.write(path, {"artist": "berlioz", "title": "ode to rahsaan (Original Mix)", "mix": "Original Mix"})
    after, stream2, _ = tags.read(path)
    assert after.artist == ("berlioz",) and after.title == "ode to rahsaan (Original Mix)" and after.mix == "Original Mix"
    assert after.remixer == "" and after.has_art is False
    assert abs(stream.duration_s - stream2.duration_s) < 0.01
    assert not list(tmp_path.glob("*.tidy-tmp")) and not list(tmp_path.glob(".*"))
    if ext != ".flac":
        assert stream2.id3_version == (2, 3, 0)
    if ext == ".mp3":
        assert ID3(path).version == (2, 3, 0)


def test_mp3_stream_facts(tmp_path):
    _, stream, _ = tags.read(make_audio(tmp_path / "a.mp3"))
    assert (stream.container, stream.bitrate_kbps, stream.bit_depth) == ("mp3", 128, None)
    assert stream.vbr in (False, None)


def test_wav_and_flac_report_bit_depth(tmp_path):
    _, w, _ = tags.read(make_audio(tmp_path / "a.wav", bits=24))
    _, f, _ = tags.read(make_audio(tmp_path / "a.flac", bits=24, rate=96000))
    assert (w.bit_depth, f.bit_depth, f.sample_rate) == (24, 24, 96000)


def test_art_is_resized_to_baseline_jpeg_and_embedded(tmp_path):
    for ext in (".mp3", ".flac"):
        path = make_audio(tmp_path / f"a{ext}")
        art = tags.prepare_art(jpeg_bytes((1400, 1400), progressive=True), max_px=800)
        tags.write(path, {"artist": "x"}, art=art)
        got, _, info = tags.read(path)
        assert got.has_art and info is not None
        assert (info.format, info.width, info.height, info.progressive) == ("jpeg", 800, 800, False)
    assert tags.prepare_art(png_bytes((300, 200)))[:3] == b"\xff\xd8\xff"
    with pytest.raises(TidyError, match="not an image"):
        tags.prepare_art(b"not an image")


def test_write_refuses_unknown_fields_and_m4a(tmp_path, monkeypatch):
    path = make_audio(tmp_path / "a.mp3")
    with pytest.raises(TidyError, match="not writable"):
        tags.write(path, {"bpm": "120"})
    monkeypatch.setattr(tags, "container_of", lambda p: "m4a")
    with pytest.raises(TidyError, match="not in v1"):
        tags.write(path, {"artist": "x"})
    assert tags.read(path)[0] == tags.Tags()


def test_failed_write_leaves_original_untouched_and_no_temp(tmp_path, monkeypatch):
    path = make_audio(tmp_path / "a.mp3")
    original = path.read_bytes()

    def boom(src, dst):
        raise OSError("disk says no")

    monkeypatch.setattr(tags.os, "replace", boom)
    with pytest.raises(TidyError, match="original untouched"):
        tags.write(path, {"artist": "x"})
    assert path.read_bytes() == original and list(tmp_path.iterdir()) == [path]


def test_verification_failure_is_a_tidy_error(tmp_path, monkeypatch):
    path = make_audio(tmp_path / "a.mp3")
    original = path.read_bytes()
    monkeypatch.setattr(tags, "_set_id3", lambda f, name, values, v: None)  # pretend the write did nothing
    with pytest.raises(TidyError, match="read back"):
        tags.write(path, {"artist": "x"})
    assert path.read_bytes() == original and list(tmp_path.iterdir()) == [path]


def test_stale_temp_file_blocks_the_write(tmp_path):
    path = make_audio(tmp_path / "a.mp3")
    (tmp_path / ".a.mp3.tidy-tmp").write_bytes(b"x")
    with pytest.raises(TidyError, match="previous run"):
        tags.write(path, {"artist": "x"})


@pytest.mark.parametrize("ext", [".mp3", ".flac", ".wav"])
def test_snapshot_and_restore_round_trip(tmp_path, ext):
    path = make_audio(tmp_path / f"a{ext}")
    container = tags.container_of(path)
    tags.write(path, {"title": "kept title"})
    before, _, _ = tags.read(path)
    snap = tags.snapshot(before, container)
    assert snap[tags.frame_name(container, "title")] == ["kept title"]
    assert snap[tags.frame_name(container, "artist")] == []

    tags.write(path, {"artist": "added", "mix": "Original Mix"}, art=tags.prepare_art(jpeg_bytes((400, 400))))
    tags.restore(path, snap, drop_art=True)
    after, _, art = tags.read(path)
    assert (after.artist, after.title, after.mix, after.has_art) == ((), "kept title", "", False) and art is None


def test_container_of_sniffs_content_not_extension(tmp_path):
    path = make_audio(tmp_path / "a.flac")
    renamed = path.rename(tmp_path / "a.bin")  # mutagen sniffs the header; the extension is only a hint
    assert tags.container_of(renamed) == "flac"
    (tmp_path / "junk.mp3").write_bytes(b"\x00" * 100)
    assert tags.container_of(tmp_path / "junk.mp3") is None
    with pytest.raises(TidyError):
        tags.read(tmp_path / "junk.mp3")


def test_find_local_art(tmp_path):
    path = make_audio(tmp_path / "Artist - Title.mp3")
    assert tags.find_local_art(path, ["cover.jpg", "{stem}.jpg"]) is None
    (tmp_path / "Artist - Title.jpg").write_bytes(jpeg_bytes((50, 50)))
    assert tags.find_local_art(path, ["cover.jpg", "{stem}.jpg"]).name == "Artist - Title.jpg"
    (tmp_path / "cover.jpg").write_bytes(jpeg_bytes((50, 50)))
    assert tags.find_local_art(path, ["cover.jpg", "{stem}.jpg"]).name == "cover.jpg"


def test_sha256_matches_hashlib(tmp_path):
    import hashlib

    path = make_audio(tmp_path / "a.mp3")
    assert tags.sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_frame_names_per_format():
    assert tags.frame_name("mp3", "mix") == "TIT3" and tags.frame_name("wav", "remixer") == "TPE4"
    assert tags.frame_name("flac", "artist") == "ARTIST" and tags.frame_name("m4a", "title") == "\xa9nam"
    assert tags.tag_format(None) is None
