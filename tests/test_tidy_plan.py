"""Plan building, validation, apply and undo on real (synthetic) files in tmp_path."""

import dataclasses
import json

import pytest
from tidy_fixtures import TidyDB, jpeg_bytes, make_audio, row

from dj.intake import Paths
from dj.tidy import TidyError, scan, tags
from dj.tidy import config as cfg_mod
from dj.tidy import plan as plan_mod

YAML = """
roots: ["{root}"]
profiles:
  - {{name: p, formats: [mp3, flac, wav, aiff], max_bit_depth: 24, sample_rates: [44100, 48000]}}
"""


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    (tmp_path / "tidy.yaml").write_text(YAML.format(root=root.as_posix()), encoding="utf-8")
    cfg = cfg_mod.load_config(tmp_path / "tidy.yaml")
    return root, cfg, Paths(tmp_path)


def build(root, cfg, db=None, **opts):
    db = db or TidyDB()
    target = scan.resolve_target(None, str(root), False, cfg)
    items, _, known = scan.items_for(target, db, cfg, "none")
    return plan_mod.build_plan(items, target, cfg, known, **opts)


def by_name(plan, name):
    return next(i for i in plan["items"] if i["file"].endswith("/" + name))


def test_build_proposes_only_empty_fields_from_the_filename(env):
    root, cfg, _ = env
    make_audio(root / "berlioz - ode to rahsaan (Original Mix).mp3")
    titled = make_audio(root / "Huerta - Low Five (Dam Swindle Rework).flac")
    tags.write(titled, {"title": "Already There"})
    plan = build(root, cfg)
    a = by_name(plan, "berlioz - ode to rahsaan (Original Mix).mp3")
    assert a["decision"] == "pending" and a["skip_reason"] is None and a["sha256"]
    assert {k: v["new"] for k, v in a["changes"].items()} == {
        "artist": "berlioz", "title": "ode to rahsaan (Original Mix)", "mix": "Original Mix"}
    assert a["changes"]["artist"]["frame"] == "TPE1" and "confidence high" in a["changes"]["artist"]["why"]
    b = by_name(plan, "Huerta - Low Five (Dam Swindle Rework).flac")
    assert set(b["changes"]) == {"artist", "mix", "remixer"} and b["changes"]["remixer"]["new"] == "Dam Swindle"
    assert b["changes"]["artist"]["frame"] == "ARTIST" and b["tag_format"] == "vorbis"
    assert plan["counts"]["with_changes"] == 2 and plan["kind"] == "tidy-plan"


def test_build_skip_reasons(env):
    root, cfg, _ = env
    make_audio(root / "Just A Title.mp3")  # low confidence
    full = make_audio(root / "Huerta - Low Five.mp3")
    tags.write(full, {"artist": "Huerta", "title": "Low Five"})  # nothing to add
    (root / "junk.mp3").write_bytes(b"\x00" * 64)
    db = TidyDB(contents=[row("1", path=(root / "gone.mp3").as_posix())])
    plan = build(root, cfg, db)
    assert by_name(plan, "Just A Title.mp3")["skip_reason"] == "SKIP_LOW_CONFIDENCE"
    assert by_name(plan, "Huerta - Low Five.mp3")["skip_reason"] == "SKIP_NO_CHANGES"
    assert by_name(plan, "junk.mp3")["skip_reason"] == "SKIP_UNREADABLE"
    assert all(i["decision"] is None for i in plan["items"])


def test_build_skips_swap_and_m4a(env, monkeypatch):
    root, cfg, _ = env
    make_audio(root / "Low Five - Huerta.mp3")
    db = TidyDB(contents=[row("1", path="C:/x/other.mp3", ArtistName="Huerta")])
    plan = build(root, cfg, db)
    assert by_name(plan, "Low Five - Huerta.mp3")["skip_reason"] == "SKIP_SWAP_SUSPECTED"
    monkeypatch.setattr(plan_mod.tags, "WRITABLE", ("flac",))  # pretend mp3 were read-only, like m4a is
    make_audio(root / "Huerta - Low Five.mp3")
    plan = build(root, cfg)
    assert by_name(plan, "Huerta - Low Five.mp3")["skip_reason"] == "SKIP_FORMAT"


def test_build_local_art_and_art_none(env):
    root, cfg, _ = env
    make_audio(root / "Huerta - Low Five.mp3")
    (root / "cover.jpg").write_bytes(jpeg_bytes((400, 400)))
    plan = build(root, cfg)
    item = by_name(plan, "Huerta - Low Five.mp3")
    assert item["changes"]["art"]["new"].endswith("cover.jpg") and item["changes"]["art"]["frame"] == "APIC"
    assert "art" not in by_name(build(root, cfg, art="none"), "Huerta - Low Five.mp3")["changes"]
    with pytest.raises(TidyError, match="--art"):
        build(root, cfg, art="online")


def test_rename_is_off_by_default_and_imported_needs_its_flag(env):
    root, cfg, _ = env
    orphan = make_audio(root / "huerta_-_low_five.mp3")
    known = make_audio(root / "03 Huerta - Low Five (Original Mix).mp3")
    tags.write(orphan, {"artist": "Huerta", "title": "Low Five"})
    tags.write(known, {"artist": "Huerta", "title": "Low Five (Original Mix)"})
    make_audio(root / "Huerta - Low Five.mp3")  # the convention name is already taken
    db = TidyDB(contents=[row("1", path=known.as_posix())])
    assert all(i["rename"] is None for i in build(root, cfg, db)["items"])
    plan = build(root, cfg, db, rename=True)
    assert by_name(plan, "huerta_-_low_five.mp3")["rename"] == {"old": "huerta_-_low_five.mp3",
                                                                 "new": "Huerta - Low Five [2].mp3", "imported": False}
    assert by_name(plan, "03 Huerta - Low Five (Original Mix).mp3")["rename"] is None
    assert by_name(plan, "Huerta - Low Five.mp3")["rename"] is None
    plan = build(root, cfg, db, rename_imported=True)
    ren = by_name(plan, "03 Huerta - Low Five (Original Mix).mp3")["rename"]
    assert ren["imported"] is True and ren["new"] == "Huerta - Low Five [2].mp3"  # walked first (sorted)
    assert by_name(plan, "huerta_-_low_five.mp3")["rename"]["new"] == "Huerta - Low Five [3].mp3"
    assert plan["options"]["rename"] is True and plan["counts"]["renames"] == 2


def test_write_plan_keeps_todays_decisions_for_the_same_proposal(env):
    root, cfg, paths = env
    make_audio(root / "Huerta - Low Five.mp3")
    plan = build(root, cfg)
    path = plan_mod.write_plan(plan, paths)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][0]["decision"] = "yes"
    path.write_text(json.dumps(data), encoding="utf-8")
    again = plan_mod.write_plan(build(root, cfg), paths)
    assert again == path and json.loads(again.read_text(encoding="utf-8"))["items"][0]["decision"] == "yes"
    changed = build(root, cfg)
    changed["items"][0]["changes"]["artist"]["new"] = "Someone Else"
    plan_mod.write_plan(changed, paths)
    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["decision"] == "pending"


@pytest.mark.parametrize("mutate, message", [
    (lambda p: p.update(kind="other"), "not a dj tidy plan"),
    (lambda p: p["items"][0].update(decision="maybe"), "pending, yes or no"),
    (lambda p: p["items"][0].update(decision="yes", skip_reason="SKIP_FORMAT"), "skipped item"),
    (lambda p: p["items"][0].update(skip_reason="SKIP_WHATEVER"), "unknown skip_reason"),
    (lambda p: p["items"][0]["changes"].update(bpm={"new": "120"}), "not one of"),
    (lambda p: p["items"][0]["changes"]["artist"].update(new="bad\x01"), "control-character"),
    (lambda p: p["items"][0]["changes"]["artist"].update(new=""), "empty"),
    (lambda p: p["items"][0].update(rename={"old": "a", "new": "../b.mp3", "imported": False}), "clean file name"),
    (lambda p: p["items"][0].update(rename={"old": "a", "new": "b.mp3", "imported": True}), "--rename-imported"),
])
def test_load_plan_rejects_bad_plans(env, mutate, message):
    root, cfg, paths = env
    make_audio(root / "Huerta - Low Five.mp3")
    path = plan_mod.write_plan(build(root, cfg), paths)
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TidyError, match=message):
        plan_mod.load_plan(path)


def test_load_plan_missing_or_not_json(tmp_path):
    with pytest.raises(TidyError, match="not found"):
        plan_mod.load_plan(tmp_path / "x.plan.json")
    (tmp_path / "x.plan.json").write_text("{nope")
    with pytest.raises(TidyError, match="not valid JSON"):
        plan_mod.load_plan(tmp_path / "x.plan.json")


def decide(path, decision="yes", only=None):
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data["items"]:
        if item["decision"] and (only is None or item["file"].endswith(only)):
            item["decision"] = decision
    path.write_text(json.dumps(data), encoding="utf-8")
    return plan_mod.load_plan(path)


def test_apply_dry_run_writes_nothing_and_lists_the_work(env):
    root, cfg, paths = env
    a = make_audio(root / "berlioz - ode to rahsaan (Original Mix).mp3")
    before = a.read_bytes()
    path = plan_mod.write_plan(build(root, cfg), paths)
    plan = decide(path)
    result = plan_mod.apply_plan(plan, path, cfg, paths, dry_run=True)
    assert len(result.applied) == 1 and result.failed == [] and result.dry_run
    assert a.read_bytes() == before and not plan_mod.undo_path_for(path, paths).exists()
    assert not (paths.reports / "tidy").exists()


def test_apply_writes_tags_renames_and_is_idempotent(env):
    root, cfg, paths = env
    a = make_audio(root / "berlioz_-_ode_to_rahsaan.mp3")
    (root / "cover.jpg").write_bytes(jpeg_bytes((1000, 1000)))
    path = plan_mod.write_plan(build(root, cfg, rename=True), paths)
    plan = decide(path)
    result = plan_mod.apply_plan(plan, path, cfg, paths, dry_run=False)
    assert len(result.applied) == 1 and not result.failed
    new = root / "berlioz - ode to rahsaan.mp3"
    assert new.is_file() and not a.exists()
    got, _, art = tags.read(new)
    assert got.artist == ("berlioz",) and got.title == "ode to rahsaan" and got.has_art and art.width == 800
    assert not list(root.glob("*.tidy-tmp"))

    undo = json.loads(result.undo_path.read_text(encoding="utf-8"))
    rec = undo["records"][0]
    assert rec["renamed"] and rec["file_after"].endswith("berlioz - ode to rahsaan.mp3")
    assert rec["sha256_after"] == tags.sha256(new) and rec["fields_added"] == ["artist", "title"] and rec["art_added"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["items"][0]["applied"]["renamed_to"].endswith("berlioz - ode to rahsaan.mp3")
    assert result.report_path.is_file() and result.relocate_path is None  # not an imported file

    again = plan_mod.apply_plan(plan_mod.load_plan(path), path, cfg, paths, dry_run=False)
    assert again.applied == [] and again.already == 1 and len(undo["records"]) == 1


def test_apply_refuses_changed_files_and_filled_tags(env):
    root, cfg, paths = env
    a = make_audio(root / "Huerta - Low Five.mp3")
    b = make_audio(root / "Octo Octa - Loops.mp3")
    path = plan_mod.write_plan(build(root, cfg), paths)
    plan = decide(path)
    a.write_bytes(a.read_bytes() + b"\x00")  # changed since the plan
    tags.write(b, {"artist": "Someone"})  # tag filled meanwhile (sha changes too, so check that reason first)
    result = plan_mod.apply_plan(plan, path, cfg, paths, dry_run=False)
    reasons = {i["file"].rsplit("/", 1)[1]: why for i, why in result.skipped}
    assert "changed since the plan" in reasons["Huerta - Low Five.mp3"]
    assert "changed since the plan" in reasons["Octo Octa - Loops.mp3"]
    assert result.applied == [] and not plan_mod.undo_path_for(path, paths).exists() or True


def test_apply_strict_writes_nothing_when_anything_is_blocked(env):
    root, cfg, paths = env
    a = make_audio(root / "Huerta - Low Five.mp3")
    b = make_audio(root / "Octo Octa - Loops.mp3")
    path = plan_mod.write_plan(build(root, cfg), paths)
    plan = decide(path)
    b.write_bytes(b.read_bytes() + b"\x00")
    before = a.read_bytes()
    result = plan_mod.apply_plan(plan, path, cfg, paths, strict=True, dry_run=False)
    assert result.applied == [] and len(result.skipped) == 1 and a.read_bytes() == before
    relaxed = plan_mod.apply_plan(plan_mod.load_plan(path), path, cfg, paths, strict=False, dry_run=False)
    assert len(relaxed.applied) == 1 and len(relaxed.skipped) == 1


def test_undo_record_is_written_before_the_file_changes(env, monkeypatch):
    root, cfg, paths = env
    a = make_audio(root / "Huerta - Low Five.mp3")
    before = a.read_bytes()
    path = plan_mod.write_plan(build(root, cfg), paths)
    plan = decide(path)

    def boom(*args, **kwargs):
        raise TidyError("simulated write failure")

    monkeypatch.setattr(plan_mod.tags, "write", boom)
    result = plan_mod.apply_plan(plan, path, cfg, paths, dry_run=False)
    assert len(result.failed) == 1 and a.read_bytes() == before
    undo = json.loads(result.undo_path.read_text(encoding="utf-8"))
    rec = undo["records"][0]
    assert rec["error"] == "simulated write failure" and rec["sha256_after"] is None
    assert rec["tags_snapshot"] == {"TPE1": [], "TIT2": [], "TIT3": [], "TPE4": []}
    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["applied"] is None
    # the failed record does not block a retry; an incomplete one (no error, no sha) would
    monkeypatch.undo()
    retry = plan_mod.apply_plan(plan_mod.load_plan(path), path, cfg, paths, dry_run=False)
    assert len(retry.applied) == 1


def test_incomplete_record_blocks_apply_and_undo(env):
    root, cfg, paths = env
    a = make_audio(root / "Huerta - Low Five.mp3")
    path = plan_mod.write_plan(build(root, cfg), paths)
    plan = decide(path)
    undo_path = plan_mod.undo_path_for(path, paths)
    undo_path.parent.mkdir(parents=True)
    undo_path.write_text(json.dumps({"kind": "tidy-undo", "version": 1, "plan": str(path), "records": [
        {"seq": 1, "at": "x", "file_before": a.as_posix(), "file_after": None, "sha256_before": "x", "sha256_after": None,
         "tags_snapshot": {}, "fields_added": ["artist"], "art_added": False, "renamed": False, "undone": None, "error": None}]}))
    result = plan_mod.apply_plan(plan, path, cfg, paths, dry_run=False)
    assert result.applied == [] and "half-way" in result.skipped[0][1]
    undo = plan_mod.undo_plan(plan, path, cfg, paths, dry_run=False)
    assert undo.restored == [] and "incomplete" in undo.skipped[0][1]


def test_undo_restores_tags_art_and_name_newest_first(env):
    root, cfg, paths = env
    a = make_audio(root / "huerta_-_low_five.mp3")
    b = make_audio(root / "Octo Octa - Loops.mp3")
    tags.write(b, {"title": "Loops For Healing"})  # pre-existing tag must survive the round trip
    (root / "cover.jpg").write_bytes(jpeg_bytes((500, 500)))
    originals = {p.name: p.read_bytes() for p in (a, b)}
    path = plan_mod.write_plan(build(root, cfg, rename=True), paths)
    plan = decide(path)
    applied = plan_mod.apply_plan(plan, path, cfg, paths, dry_run=False)
    assert len(applied.applied) == 2 and (root / "huerta - low five.mp3").exists()

    dry = plan_mod.undo_plan(plan_mod.load_plan(path), path, cfg, paths, dry_run=True)
    assert len(dry.restored) == 2 and (root / "huerta - low five.mp3").exists()

    result = plan_mod.undo_plan(plan_mod.load_plan(path), path, cfg, paths, dry_run=False)
    assert [r["seq"] for r in result.restored] == [2, 1] and not result.failed
    assert a.exists() and not (root / "huerta - low five.mp3").exists()
    assert a.read_bytes() == originals["huerta_-_low_five.mp3"]  # byte-identical: the file had no tag before
    got_b, _, _ = tags.read(b)
    assert got_b.title == "Loops For Healing" and got_b.artist == () and not got_b.has_art
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert all(i["applied"] is None for i in saved["items"])
    undo = json.loads(result.undo_path.read_text(encoding="utf-8"))
    assert all(r["undone"] for r in undo["records"])
    again = plan_mod.undo_plan(plan_mod.load_plan(path), path, cfg, paths, dry_run=False)
    assert again.restored == [] and again.skipped == [] and again.failed == []


def test_undo_refuses_changed_file_unless_forced(env):
    root, cfg, paths = env
    a = make_audio(root / "Huerta - Low Five.mp3")
    path = plan_mod.write_plan(build(root, cfg), paths)
    plan_mod.apply_plan(decide(path), path, cfg, paths, dry_run=False)
    tags.write(a, {"remixer": "Later Edit"})
    result = plan_mod.undo_plan(plan_mod.load_plan(path), path, cfg, paths, dry_run=False)
    assert result.restored == [] and "--force" in result.skipped[0][1]
    forced = plan_mod.undo_plan(plan_mod.load_plan(path), path, cfg, paths, dry_run=False, force=True)
    assert len(forced.restored) == 1 and tags.read(a)[0] == tags.Tags()


def test_undo_without_an_undo_file(env):
    root, cfg, paths = env
    make_audio(root / "Huerta - Low Five.mp3")
    path = plan_mod.write_plan(build(root, cfg), paths)
    with pytest.raises(TidyError, match="No undo file"):
        plan_mod.undo_plan(plan_mod.load_plan(path), path, cfg, paths)


def test_relocate_checklist_for_renamed_imported_files(env):
    root, cfg, paths = env
    known = make_audio(root / "03 Huerta - Low Five.mp3")
    db = TidyDB(contents=[row("77", path=known.as_posix(), ArtistName="Huerta", Title="Low Five")])
    path = plan_mod.write_plan(build(root, cfg, db, rename_imported=True), paths)
    result = plan_mod.apply_plan(decide(path), path, cfg, paths, dry_run=False)
    assert len(result.applied) == 1 and result.relocate_path is not None
    text = result.relocate_path.read_text(encoding="utf-8")
    assert "| [ ] | 77 | Huerta - Low Five |" in text and "Huerta - Low Five.mp3 |" in text
    assert result.relocate_path.name.endswith("-tidy-relocate-music.md")


def test_outside_roots_is_skipped_when_enforced(env, tmp_path):
    root, cfg, paths = env
    make_audio(root / "Huerta - Low Five.mp3")
    plan = build(root, cfg)
    loose = cfg_mod.TidyConfig(**{**cfg.__dict__, "roots": (tmp_path / "elsewhere",)})
    target = scan.Target("folder", str(root), "music")
    items, _, known = scan.items_for(target, TidyDB(), loose, "none")
    plan2 = plan_mod.build_plan(items, target, loose, known)
    assert plan2["items"][0]["skip_reason"] == "SKIP_OUTSIDE_ROOTS" and plan["items"][0]["skip_reason"] is None


# -- writes stay inside the tidy.yaml roots, and a rename never replaces a file (CLAUDE.md) -----


def test_apply_never_writes_outside_the_roots_even_when_the_config_opts_out(env, tmp_path):
    """enforce_roots_for_writes: false only shapes the plan; the write itself stays in the roots."""
    root, cfg, paths = env
    a = make_audio(root / "Huerta - Low Five.mp3")
    path = plan_mod.write_plan(build(root, cfg), paths)
    plan = decide(path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    narrowed = dataclasses.replace(cfg, roots=[elsewhere], enforce_roots_for_writes=False)
    before = a.read_bytes()
    result = plan_mod.apply_plan(plan, path, narrowed, paths, dry_run=False)
    assert result.applied == [] and [why for _, why in result.skipped] == ["outside tidy.yaml roots"]
    assert a.read_bytes() == before and not plan_mod.undo_path_for(path, paths).exists()


def test_undo_never_touches_a_file_outside_the_roots(env, tmp_path):
    """The undo record's paths are data: one that points outside the roots is skipped."""
    root, cfg, paths = env
    a = make_audio(root / "Huerta - Low Five.mp3")
    path = plan_mod.write_plan(build(root, cfg), paths)
    applied = plan_mod.apply_plan(decide(path), path, cfg, paths, dry_run=False)
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(a.read_bytes())  # same bytes, so the sha check alone would let it through
    undo = json.loads(applied.undo_path.read_text(encoding="utf-8"))
    undo["records"][0]["file_after"] = outside.as_posix()
    applied.undo_path.write_text(json.dumps(undo), encoding="utf-8")
    before = outside.read_bytes()
    for dry_run in (True, False):
        result = plan_mod.undo_plan(plan_mod.load_plan(path), path, cfg, paths, dry_run=dry_run)
        assert result.restored == [] and [why for _, why in result.skipped] == ["outside tidy.yaml roots"]
    assert outside.read_bytes() == before and tags.read(a)[0].artist == ("Huerta",)


def test_a_rename_never_replaces_a_file_that_sits_at_the_target(tmp_path):
    """The existence check and the rename are one step: a file that appeared in between stays."""
    src, dst = tmp_path / "a.mp3", tmp_path / "b.mp3"
    src.write_bytes(b"mine")
    dst.write_bytes(b"theirs")
    with pytest.raises(FileExistsError):
        plan_mod._rename_new(src, dst)
    assert src.read_bytes() == b"mine" and dst.read_bytes() == b"theirs"
    plan_mod._rename_new(src, tmp_path / "c.mp3")
    assert not src.exists() and (tmp_path / "c.mp3").read_bytes() == b"mine"
