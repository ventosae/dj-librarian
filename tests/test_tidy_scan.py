"""Targets, the folder walk, cross-referencing files and rows, hashing."""

import pytest
from tidy_fixtures import TidyDB, make_audio, playlist, row, song

from dj.library import to_track_info
from dj.tidy import TidyError, scan
from dj.tidy import config as cfg_mod

YAML = """
roots: ["{root}"]
profiles:
  - {{name: p, formats: [mp3, flac, wav, aiff], max_bit_depth: 24, sample_rates: [44100, 48000]}}
"""


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "music"
    (root / "crate").mkdir(parents=True)
    (tmp_path / "tidy.yaml").write_text(YAML.format(root=root.as_posix()), encoding="utf-8")
    return root


@pytest.fixture
def cfg(tmp_path, music):
    return cfg_mod.load_config(tmp_path / "tidy.yaml")


def test_resolve_target_exactly_one_and_roots(cfg, music, tmp_path):
    with pytest.raises(TidyError, match="Give one"):
        scan.resolve_target(None, None, False, cfg)
    with pytest.raises(TidyError, match="Give one"):
        scan.resolve_target("a/b", str(music), False, cfg)
    assert scan.resolve_target(None, None, True, cfg) == scan.Target("all", "", "all")
    assert scan.resolve_target("house_base/0_INBOX", None, False, cfg).slug == "house_base_0_INBOX"
    t = scan.resolve_target(None, str(music / "crate"), False, cfg)
    assert t.kind == "folder" and t.slug == "crate" and t.value == str((music / "crate").resolve())
    with pytest.raises(TidyError, match="not a directory"):
        scan.resolve_target(None, str(music / "nope"), False, cfg)
    (tmp_path / "outside").mkdir()
    with pytest.raises(TidyError, match="outside"):
        scan.resolve_target(None, str(tmp_path / "outside"), False, cfg)


def test_walk_folder_skips_non_audio_hidden_and_temp(music):
    make_audio(music / "crate" / "b.mp3")
    make_audio(music / "crate" / "A.flac")
    (music / "crate" / "cover.jpg").write_bytes(b"x")
    (music / "crate" / ".b.mp3.tidy-tmp").write_bytes(b"x")
    (music / "crate" / "notes.txt").write_text("x")
    (music / "crate" / "deep").mkdir()
    make_audio(music / "crate" / "deep" / "c.wav")
    names = [p.name for p in scan.walk_folder(music)]
    assert names == ["A.flac", "b.mp3", "c.wav"]


def test_file_facts_never_raises(music):
    good = scan.file_facts(make_audio(music / "a.mp3"))
    assert good.exists and good.container == "mp3" and good.read_error is None and good.sha256 is None
    hashed = scan.file_facts(music / "a.mp3", want_hash=True)
    assert hashed.sha256 and len(hashed.sha256) == 64
    (music / "junk.mp3").write_bytes(b"\x00" * 50)
    bad = scan.file_facts(music / "junk.mp3")
    assert bad.exists and bad.read_error and bad.tags is None
    assert scan.file_facts(music / "missing.mp3").exists is False


def test_folder_mode_cross_references_rows_case_and_slash_insensitively(cfg, music):
    a = make_audio(music / "crate" / "Huerta - Low Five.mp3")
    make_audio(music / "crate" / "Orphan - Track.mp3")
    db = TidyDB(contents=[
        row("1", path=a.as_posix().upper().replace("MP3", "mp3")),  # different case, forward slashes
        row("2", path="C:/elsewhere/x.mp3"),
        row("3", path=a.as_posix(), rb_local_deleted=1),
    ])
    target = scan.resolve_target(None, str(music / "crate"), False, cfg)
    items, meta, known = scan.items_for(target, db, cfg, "none")
    assert [it.file.name for it in items] == ["Huerta - Low Five.mp3", "Orphan - Track.mp3"]
    assert items[0].rb is not None and items[0].rb.content_id == "1" and items[1].rb is None
    assert meta["files"] == 2 and meta["not_in_rekordbox"] == 1 and meta["rb_rows"] == 2
    assert known == frozenset({"artist"}) and items[0].parsed.artist == "Huerta"
    assert all(it.in_roots for it in items) and items[0].crate is None


def test_crate_mode_follows_playlist_order_and_reports_missing_files(cfg, music):
    b = make_audio(music / "crate" / "b.mp3")
    a = make_audio(music / "crate" / "a.mp3")
    pl = playlist("10", "0_INBOX", parent="root", songs=[song("2", 1), song("1", 2), song("9", 3), song("1", 4)])
    db = TidyDB(
        contents=[row("1", path=a.as_posix()), row("2", path=b.as_posix()),
                  row("9", path=(music / "crate" / "gone.mp3").as_posix())],
        playlists=[pl],
    )
    target = scan.resolve_target("0_INBOX", None, False, cfg)
    items, meta, _ = scan.items_for(target, db, cfg, "none")
    assert [it.file.name for it in items] == ["b.mp3", "a.mp3", "gone.mp3"]
    assert meta["missing_files"] == 1 and items[2].file.exists is False and items[0].crate == "0_INBOX"


def test_all_mode_and_hash_collisions_only(cfg, music):
    a = make_audio(music / "a.mp3", frames=40)
    b = make_audio(music / "b.mp3", frames=40)  # same bytes as a
    c = make_audio(music / "c.mp3", frames=41)
    db = TidyDB(contents=[row("1", path=a.as_posix()), row("2", path=b.as_posix()), row("3", path=c.as_posix())])
    items, meta, _ = scan.items_for(scan.Target("all", "", "all"), db, cfg, "collisions")
    hashes = {it.file.name: it.file.sha256 for it in items}
    assert hashes["a.mp3"] == hashes["b.mp3"] and hashes["c.mp3"] is None
    items_all, _, _ = scan.items_for(scan.Target("all", "", "all"), db, cfg, "all")
    assert all(it.file.sha256 for it in items_all)
    with pytest.raises(TidyError, match="--hash"):
        scan.hash_items(items, "sometimes")


def test_local_art_is_found_next_to_the_file(cfg, music):
    a = make_audio(music / "a.mp3")
    (music / "cover.jpg").write_bytes(b"x")
    item = scan.make_item(a, None, None, cfg)
    assert item.local_art is not None and item.local_art.name == "cover.jpg"
    missing = scan.make_item(music / "nope.mp3", to_track_info(row("1", path="x")), None, cfg)
    assert missing.local_art is None and missing.file.exists is False
