import json
from types import SimpleNamespace as NS

import pytest

from dj import intake
from dj.intake import AMBIGUOUS, DECLINED, IN_CRATE, MISSING, PROPOSE, Link, Paths
from dj.match import Local

LINK = Link("funk_109_bpm", "funk_base/funk_crate")


def sp(title, artist, s, isrc=None, uri=None):
    return {"uri": uri or "spotify:track:" + title.replace(" ", "_"), "title": title,
            "artists": [artist], "album": "Album", "duration_ms": s * 1000, "isrc": isrc,
            "added_at": "2026-09-01T00:00:00Z"}


LIB = [
    Local("1", "Huerta", "Low Five", duration_s=413, bitrate=320, path="D:/m/low five.mp3"),
    Local("2", "Octo Octa", "Loops For Healing (Extended Mix)", duration_s=500),
    Local("3", "Anthony Naples", "Scanners", duration_s=337, isrc="USYBL2500011"),
    Local("4", "Palms Trax", "Lost Control", duration_s=334, path="D:/m/a.mp3"),
    Local("5", "Palms Trax", "Lost Control", duration_s=334, path="D:/m/b.wav"),
]


def one(track, in_crate=(), cache=None, declined=()):
    return intake.match_one(track, LINK.crate, LIB, set(in_crate), cache or {}, list(declined))


def test_confident_match_is_proposed_or_in_crate():
    assert one(sp("Low Five", "Huerta", 413)).status == PROPOSE
    item = one(sp("Low Five", "Huerta", 413), in_crate={"1"})
    assert (item.status, item.pick.content_id) == (IN_CRATE, "1")


def test_isrc_match_even_if_titles_disagree():
    item = one(sp("Scanners - 2025 Something", "A. Naples", 337, isrc="usybl2500011"))
    assert (item.status, item.how, item.pick.content_id) == (PROPOSE, "isrc", "3")


def test_spotify_original_vs_local_extended_mix_is_ambiguous_never_proposed():
    item = one(sp("Loops For Healing", "Octo Octa", 327))
    assert item.status == AMBIGUOUS and item.pick is None
    assert [l.content_id for l, _ in item.top] == ["2"]


def test_two_local_files_of_the_same_track_are_ambiguous():
    item = one(sp("Lost Control", "Palms Trax", 334))
    assert item.status == AMBIGUOUS and "2 local files match" in item.reasons


def test_nothing_above_75_is_missing():
    assert one(sp("Trojan Force", "Fantastic Man", 329)).status == MISSING


def test_cache_decides_before_any_scoring():
    track = sp("Loops For Healing", "Octo Octa", 327)
    item = one(track, cache={track["uri"]: "2"})
    assert (item.status, item.how, item.pick.content_id) == (PROPOSE, "cache", "2")
    assert one(track, cache={track["uri"]: "2"}, in_crate={"2"}).status == IN_CRATE


def test_cache_entry_for_a_file_that_left_the_library_is_ignored():
    track = sp("Low Five", "Huerta", 413)
    assert one(track, cache={track["uri"]: "999"}).how != "cache"


def test_declined_is_never_reproposed_but_only_for_that_crate():
    track = sp("Low Five", "Huerta", 413)
    assert one(track, declined=[{"crate": LINK.crate, "spotify_uri": track["uri"]}]).status == DECLINED
    assert one(track, declined=[{"crate": "other", "spotify_uri": track["uri"]}]).status == PROPOSE


def test_flatten_accepts_item_and_track_and_skips_episodes():
    rows = [
        {"item": {"uri": "u1", "name": "A", "artists": [{"name": "X"}], "type": "track"}, "added_at": "d"},
        {"track": {"uri": "u2", "name": "B", "artists": []}},
        {"item": {"uri": "u3", "type": "episode"}},
        {"item": None},
    ]
    assert [t["uri"] for t in intake.flatten(rows)] == ["u1", "u2"]


def test_links_resolve_by_spotify_or_crate(tmp_path):
    paths = Paths(tmp_path)
    paths.links.write_text("- spotify: funk_109_bpm\n  crate: funk_base/funk_crate\n- spotify: other\n  crate: x\n")
    assert intake.resolve_link("FUNK_109_BPM", paths).crate == "funk_base/funk_crate"
    assert intake.resolve_link("funk_base/funk_crate", paths).spotify == "funk_109_bpm"
    with pytest.raises(intake.IntakeError):
        intake.resolve_link("nope", paths)


# -- plan / apply ------------------------------------------------------------------------


def make_items():
    tracks = [sp("Low Five", "Huerta", 413), sp("Loops For Healing", "Octo Octa", 327),
              sp("Trojan Force", "Fantastic Man", 329), sp("Scanners", "Anthony Naples", 337)]
    return [one(t) for t in tracks]


def test_plan_defaults_to_pending_and_keeps_decisions_on_replan(tmp_path):
    paths = Paths(tmp_path)
    path = intake.write_plan(LINK, make_items(), set(), paths)
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert [i["decision"] for i in plan["items"]] == ["pending", "pending", None, "pending"]
    assert plan["items"][1]["pick"] is None  # AMBIGUOUS: the human picks

    plan["items"][0]["decision"] = "yes"
    plan["items"][1] |= {"decision": "yes", "pick": "2"}
    path.write_text(json.dumps(plan), encoding="utf-8")
    again = json.loads(intake.write_plan(LINK, make_items(), set(), paths).read_text(encoding="utf-8"))
    assert again["items"][0]["decision"] == "yes"
    assert (again["items"][1]["decision"], again["items"][1]["pick"]) == ("yes", "2")


def test_wishlist_groups_missing_by_artist(tmp_path):
    text = intake.write_wishlist(LINK, make_items(), Paths(tmp_path)).read_text(encoding="utf-8")
    assert "## Fantastic Man" in text and "open.spotify.com/track/Trojan_Force" in text
    assert "Huerta" not in text


def test_yes_without_pick_is_rejected(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"crate": "c", "items": [{"spotify": "x", "decision": "yes", "pick": None}]}))
    with pytest.raises(intake.IntakeError, match="pick is empty"):
        intake.load_plan(path)


class CrateDB:
    """A crate inside a fake rekordbox. add_to_playlist must never get a track_no."""

    def __init__(self, library_ids=("1", "2", "3")):
        self.crate = NS(ID="p", Name="funk_crate", Attribute=0, ParentID="f", Seq=1, Songs=[])
        self.rows = [NS(ID="f", Name="funk_base", Attribute=1, ParentID="root", Seq=1, Songs=[]), self.crate]
        self.library_ids, self.added = set(library_ids), []

    def get_playlist(self, ParentID):
        return NS(all=lambda: [r for r in self.rows if r.ParentID == ParentID])

    def get_content(self, ID):
        return NS(ID=ID) if ID in self.library_ids else None

    def add_to_playlist(self, playlist, content, **kwargs):
        assert not kwargs, "append only: never pass track_no"
        playlist.Songs.append(NS(ContentID=content))
        self.added.append(content)


def plan_with(*decisions):
    return {"spotify": "funk_109_bpm", "crate": LINK.crate, "items": [
        {"spotify": f"t{n}", "spotify_uri": f"u{n}", "decision": d, "pick": pick}
        for n, (d, pick) in enumerate(decisions)]}


def test_apply_adds_only_yes_and_a_second_apply_adds_nothing():
    db = CrateDB()
    plan = plan_with(("yes", "1"), ("no", "2"), ("pending", "3"), (None, None))
    assert [i["pick"] for i in intake.add_to_crate(db, plan)] == ["1"]
    assert intake.add_to_crate(db, plan) == []
    assert db.added == ["1"]


def test_apply_adds_a_local_file_once_even_if_two_spotify_tracks_pick_it():
    db = CrateDB()
    intake.add_to_crate(db, plan_with(("yes", "1"), ("yes", "1")))
    assert db.added == ["1"]


def test_apply_checks_every_pick_before_the_first_write():
    db = CrateDB()
    with pytest.raises(intake.IntakeError, match="not in the library"):
        intake.add_to_crate(db, plan_with(("yes", "1"), ("yes", "404")))
    assert db.added == []


def test_record_updates_cache_declined_and_report(tmp_path):
    paths = Paths(tmp_path)
    plan = plan_with(("yes", "1"), ("no", "2"), ("pending", "3"))
    added = [plan["items"][0]]
    report = intake.record(plan, tmp_path / "p.plan.json", added, paths)
    intake.record(plan, tmp_path / "p.plan.json", [], paths)  # again: no duplicates
    assert json.loads(paths.cache.read_text()) == {"u0": "1"}
    declined = json.loads(paths.declined.read_text())
    assert [(d["crate"], d["spotify_uri"]) for d in declined] == [(LINK.crate, "u1")]
    assert json.loads(report.read_text())["counts"]["still_pending"] == 1
    assert intake.last_report(LINK, paths) is not None


def test_soft_deleted_songs_are_not_in_the_crate():
    from dj import library

    crate = NS(Songs=[NS(ContentID="1"), NS(ContentID="2", rb_local_deleted=1)])
    assert library.crate_content_ids(crate) == {"1"}
