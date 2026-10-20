from types import SimpleNamespace as NS

import pytest

from dj import push
from dj.match import AMBIGUOUS, MATCH, MISSING, Local
from dj.spotify import SpotifyError


def item(name, artist, ms, isrc=None, uri=None):
    return {
        "uri": uri or f"spotify:track:{name}".replace(" ", "_"),
        "name": name,
        "artists": [{"name": artist}],
        "album": {"name": "Album"},
        "duration_ms": ms,
        "external_ids": {"isrc": isrc} if isrc else {},
        "external_urls": {"spotify": "https://open.spotify.com/track/x"},
    }


class FakeSpotify:
    def __init__(self, catalogue=()):
        self.catalogue = list(catalogue)
        self.searches, self.playlists, self.created = [], {}, []

    def search_tracks(self, query, limit=10):
        self.searches.append(query)
        if query.startswith("isrc:"):
            code = query[5:]
            return [i for i in self.catalogue if i["external_ids"].get("isrc") == code]
        words = set(query.replace("track:", "").replace("artist:", "").split())
        return [i for i in self.catalogue if words & set(i["name"].lower().split())]

    def create_playlist(self, name, description=""):
        pid = f"pl{len(self.playlists) + 1}"
        self.playlists[pid] = []
        self.created.append(name)
        return {"id": pid, "external_urls": {"spotify": f"https://open.spotify.com/playlist/{pid}"}}

    def playlist_item_uris(self, pid):
        if getattr(self, "down", None):
            raise SpotifyError(self.down)
        if pid not in self.playlists:
            raise SpotifyError(f"GET https://api.spotify.com/v1/playlists/{pid}/items -> 404 not found")
        return list(self.playlists[pid])

    def add_items(self, pid, uris):
        self.playlists[pid] += uris


def test_queries_go_from_precise_to_loose():
    local = Local("1", "Seb Wildblood & Friend", "vitara 3000 (Central Remix)", isrc="GBKQU2301020")
    assert push.queries(local) == [
        "isrc:GBKQU2301020",
        "track:vitara 3000 artist:seb wildblood",
        "seb wildblood vitara 3000 central remix",
    ]


def test_match_track_stops_at_the_isrc_hit():
    api = FakeSpotify([item("Scanners", "Anthony Naples", 337_000, isrc="USYBL2500011")])
    r = push.match_track(api, Local("1", "Anthony Naples", "Scanners", duration_s=337, isrc="USYBL2500011"))
    assert r.status == MATCH and api.searches == ["isrc:USYBL2500011"]


def test_match_track_falls_back_to_text_search():
    api = FakeSpotify([item("Low Five", "Huerta", 413_332)])
    r = push.match_track(api, Local("1", "Huerta", "Low Five", duration_s=413))
    assert r.status == MATCH


def test_missing_when_spotify_has_nothing():
    r = push.match_track(FakeSpotify(), Local("1", "Huerta", "Low Five", duration_s=413))
    assert r.status == MISSING


def results(api):
    tracks = [
        Local("1", "Huerta", "Low Five", duration_s=413),
        Local("2", "Octo Octa", "Loops For Healing", duration_s=327),
        Local("3", "Nobody", "Unfindable", duration_s=100),
    ]
    return [push.match_track(api, t) for t in tracks]


CATALOGUE = [item("Low Five", "Huerta", 413_000), item("Loops For Healing - Extended Mix", "Octo Octa", 327_000)]


def test_only_matches_are_selected_unless_asked():
    rs = results(FakeSpotify(CATALOGUE))
    assert [r.status for r in rs] == [MATCH, AMBIGUOUS, MISSING]
    assert push.selected_uris(rs, include_ambiguous=False) == ["spotify:track:Low_Five"]
    assert len(push.selected_uris(rs, include_ambiguous=True)) == 2


def test_apply_creates_once_and_second_apply_adds_nothing(tmp_path):
    api, state = FakeSpotify(CATALOGUE), tmp_path / "state" / "push.json"
    uris = ["spotify:track:a", "spotify:track:b"]
    first = push.apply(api, "rb1", "deep", uris, state)
    assert (first["created"], first["added"]) == (True, 2)
    second = push.apply(api, "rb1", "deep", uris, state)
    assert (second["created"], second["added"], second["already_there"]) == (False, 0, 2)
    assert api.created == ["deep"] and api.playlists["pl1"] == uris


def test_apply_only_adds_what_is_new_and_keeps_order(tmp_path):
    api, state = FakeSpotify(), tmp_path / "push.json"
    push.apply(api, "rb1", "deep", ["u1", "u2"], state)
    push.apply(api, "rb1", "deep", ["u1", "u3", "u2", "u4"], state)
    assert api.playlists["pl1"] == ["u1", "u2", "u3", "u4"]


def test_apply_makes_a_new_playlist_if_the_old_one_is_gone(tmp_path):
    api, state = FakeSpotify(), tmp_path / "push.json"
    push.apply(api, "rb1", "deep", ["u1"], state)
    api.playlists.clear()
    again = push.apply(api, "rb1", "deep", ["u1"], state)
    assert again["created"] and again["added"] == 1


@pytest.mark.parametrize("error", [
    "GET https://api.spotify.com/v1/playlists/pl1/items -> 502 bad gateway",
    "GET https://api.spotify.com/v1/playlists/pl1/items -> 429 slow down",
    "GET https://api.spotify.com/v1/playlists/pl1/items failed: ConnectError",
])  # fmt: skip
def test_apply_never_makes_a_second_playlist_when_spotify_does_not_answer(tmp_path, error):
    """Only 404/403 means gone. Any other error reading the remembered playlist is raised before
    anything is created, and state/push.json still points at the first playlist."""
    api, state = FakeSpotify(), tmp_path / "push.json"
    push.apply(api, "rb1", "deep", ["u1"], state)
    before = state.read_text(encoding="utf-8")
    api.down = error
    with pytest.raises(SpotifyError, match="pl1/items"):
        push.apply(api, "rb1", "deep", ["u1", "u2"], state)
    assert api.created == ["deep"] and api.playlists == {"pl1": ["u1"]}
    assert state.read_text(encoding="utf-8") == before


def test_apply_makes_a_new_playlist_when_the_old_one_is_no_longer_readable(tmp_path):
    api, state = FakeSpotify(), tmp_path / "push.json"
    push.apply(api, "rb1", "deep", ["u1"], state)
    api.down = "GET https://api.spotify.com/v1/playlists/pl1/items -> 403 forbidden"
    again = push.apply(api, "rb1", "deep", ["u1"], state)
    assert again["created"] and api.created == ["deep", "deep"]


def row(id_, name, attribute, parent, seq=1, songs=()):
    return NS(ID=id_, Name=name, Attribute=attribute, ParentID=parent, Seq=seq, Songs=list(songs))


class RbDB:
    def __init__(self, rows):
        self.rows = rows

    def get_playlist(self, ParentID):
        return NS(all=lambda: [r for r in self.rows if r.ParentID == ParentID])


def test_find_playlist_by_path_and_read_tracks_in_order():
    content = lambda i, t: NS(ID=i, ArtistName="A", Title=t, AlbumName=None, Length=200, ISRC=None)
    songs = [NS(TrackNo=2, Content=content(8, "second")), NS(TrackNo=1, Content=content(9, "first"))]
    db = RbDB([row("f", "funk_base", 1, "root"), row("p", "Funk_Crate", 0, "f", songs=songs)])
    found = push.find_playlist(db, "funk_base / funk_crate")
    assert found.ID == "p"
    assert [t.title for t in push.local_tracks(found)] == ["first", "second"]


def test_find_playlist_errors():
    db = RbDB([row("f", "funk_base", 1, "root")])
    with pytest.raises(push.PushError, match="No rekordbox playlist"):
        push.find_playlist(db, "nope")
    with pytest.raises(push.PushError, match="is a folder"):
        push.find_playlist(db, "funk_base")


def test_a_second_report_on_the_same_day_never_replaces_the_first(tmp_path):
    first = push.write_report("deep", {"run": 1}, tmp_path)
    second = push.write_report("deep", {"run": 2}, tmp_path)
    assert second.name == first.name.replace(".report.json", "-2.report.json")
    assert '"run": 1' in first.read_text(encoding="utf-8") and '"run": 2' in second.read_text(encoding="utf-8")
