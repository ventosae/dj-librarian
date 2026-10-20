"""dj analyze: pull into a cache, then reports. Fake API, no network, no rekordbox."""

from __future__ import annotations

import json

import pytest

from dj import analyze
from dj.spotify import SpotifyError


def track(tid, name, artists, year="2001-05-05", ms=240_000, pop=50, album="Alb", local=False):
    return {"id": None if local else tid, "uri": f"spotify:track:{tid}", "name": name,
            "duration_ms": ms, "popularity": pop, "explicit": False, "is_local": local,
            "external_ids": {"isrc": "X"}, "available_markets": ["AU", "DE"],
            "artists": [{"id": f"a_{a}", "name": a} for a in artists],
            "album": {"id": "al", "name": album, "release_date": year, "album_type": "album"}}


ARTISTS = {
    "a_Moodymann": {"id": "a_Moodymann", "name": "Moodymann", "genres": ["deep house", "detroit techno"], "popularity": 55, "followers": {"total": 1}},
    "a_Herbie": {"id": "a_Herbie", "name": "Herbie", "genres": ["jazz funk"], "popularity": 70, "followers": {"total": 2}},
    "a_Nobody": {"id": "a_Nobody", "name": "Nobody", "genres": [], "popularity": 1, "followers": {"total": 0}},
}


class FakeAPI:
    def __init__(self):
        self.artist_calls: list[list[str]] = []

    def me(self):
        return {"id": "dj_user", "display_name": "The DJ", "country": "AU", "email": "never@print"}

    def my_playlists(self):
        yield {"id": "p1", "name": "Deep", "owner": {"id": "dj_user", "display_name": "The DJ"}, "public": False}
        yield {"id": "p2", "name": "Jazz", "owner": {"id": "other", "display_name": "Someone"}, "public": True}
        yield {"id": "p3", "name": "Editorial", "owner": {"id": "spotify", "display_name": "Spotify"}, "public": True}

    def playlist_items(self, pid):
        if pid == "p3":
            raise SpotifyError("GET /playlists/p3/items -> 403 Forbidden")
        if pid == "p1":
            return iter([{"added_at": "2024-01-01T00:00:00Z", "item": track("t1", "Shades", ["Moodymann"])},
                         {"added_at": "2024-01-02T00:00:00Z", "track": track("t2", "Chameleon", ["Herbie"], year="1973")},
                         {"added_at": "2024-01-03T00:00:00Z", "item": None},
                         {"added_at": "2024-01-04T00:00:00Z", "item": track("x", "Rip", ["Nobody"], local=True)}])
        return iter([{"added_at": "2024-02-01T00:00:00Z", "item": track("t2", "Chameleon", ["Herbie"], year="1973")},
                     {"added_at": "2024-02-02T00:00:00Z", "item": track("t3", "Watermelon", ["Herbie", "Nobody"], year="1962-01-01", ms=700_000)}])

    def saved_tracks(self):
        return iter([{"added_at": "2023-06-01T00:00:00Z", "track": track("t1", "Shades", ["Moodymann"])},
                     {"added_at": "2022-06-01T00:00:00Z", "track": track("t9", "Lonely", ["Nobody"], pop=None, year=None)}])

    def saved_albums(self):
        return iter([{"added_at": "2023-01-01T00:00:00Z",
                      "album": {"id": "al1", "name": "Head Hunters", "release_date": "1973-10-13", "album_type": "album",
                                "total_tracks": 4, "artists": [{"id": "a_Herbie", "name": "Herbie"}]}}])

    def followed_artists(self):
        return iter([ARTISTS["a_Moodymann"]])

    def top_items(self, kind, rng):
        if kind == "artists":
            return [ARTISTS["a_Herbie"]] if rng == "long_term" else []
        return [track("t2", "Chameleon", ["Herbie"], year="1973")] if rng == "short_term" else []

    def artists(self, ids):
        # GET /artists?ids= was removed in Feb 2026 (C-06): dj analyze must never ask.
        self.artist_calls.append(list(ids))
        raise AssertionError("dj analyze called the removed batch GET /artists?ids=")


@pytest.fixture
def pulled(tmp_path):
    api = FakeAPI()
    cache = tmp_path / "cache"
    counts = analyze.pull(api, cache)
    return api, cache, counts


def test_pull_writes_slim_cache_and_never_calls_the_artist_batch(pulled):
    api, cache, counts = pulled
    assert counts == {"playlists": 2, "playlist_rows": 5, "skipped": 1, "liked": 2, "albums": 1,
                      "followed": 1, "artists": 2, "genres_available": True, "cache": str(cache)}
    # Moodymann came from followed, Herbie from top artists. Nobody stays without details:
    # the batch GET /artists?ids= is gone (R-804, C-06).
    assert api.artist_calls == []
    me = json.loads((cache / "me.json").read_text(encoding="utf-8"))
    assert "email" not in me
    playlists = json.loads((cache / "playlists.json").read_text(encoding="utf-8"))
    assert [p["mine"] for p in playlists] == [True, False]
    assert "available_markets" not in json.dumps(playlists)


def test_load_dedupes_by_id_and_keeps_local_files(pulled):
    _, cache, _ = pulled
    lib = analyze.load(cache)
    assert sorted(lib.tracks) == sorted(["t1", "t2", "t3", "t9", "local:Rip|Nobody"])
    assert lib.tracks["t2"].playlists == ["Deep", "Jazz"]
    assert lib.tracks["t1"].liked and lib.tracks["t1"].playlists == ["Deep"]
    assert lib.tracks["t9"].liked and not lib.tracks["t9"].playlists
    assert lib.local_rows == 1
    assert lib.genres_of(lib.tracks["t3"]) == ["jazz funk"]


def test_reports(pulled, tmp_path):
    _, cache, _ = pulled
    lib = analyze.load(cache)
    out = tmp_path / "reports"
    written = analyze.write_reports(lib, out)
    assert [w.name for w in written] == ["00_summary.md", "01_artists.md", "02_playlists.md", "03_liked.md", "10_tracks.md"]
    liked = (out / "03_liked.md").read_text(encoding="utf-8")
    assert "2 liked tracks, newest save first. 1 of them are in no playlist" in liked
    assert "Saved per year: 2022 1; 2023 1" in liked
    assert liked.index("| 2023-06-01 | Moodymann | Shades |") < liked.index("| 2022-06-01 | Nobody | Lonely |")
    assert "| 2023-06-01 | Moodymann | Shades | Alb | 2001 | 4:00 | Deep |" in liked
    summary = (out / "00_summary.md").read_text(encoding="utf-8")
    assert "| unique tracks overall | 5 |" in summary
    assert "| Liked Songs not in any playlist | 1 (50%) |" in summary
    assert "| Deep | me | 3 |" in summary and "| Jazz | Someone | 2 |" in summary
    assert "| 1 | Nobody | 3 | 1 | 2 |  |  |" in summary  # no batch fetch: no popularity
    assert "| 2 | Herbie | 2 | 0 | 2 | 70 | jazz funk |" in summary
    assert "| jazz | 2 |" in summary and "| house | 1 |" in summary
    assert "| 1970s | 1 |" in summary and "| unknown | 2 |" in summary
    assert "| Deep | Jazz | 1 |" in summary
    assert "Head Hunters" in summary and "never@print" not in summary
    assert ("Not readable by this app (403: not yours or Spotify-owned; 404: not found, or not "
            "readable): Editorial (403)") in summary
    artists = (out / "01_artists.md").read_text(encoding="utf-8")
    assert artists.splitlines()[7].startswith("| Herbie | 2 | 0 | 2 | 70 | jazz funk | Deep; Jazz |")
    tracks = (out / "10_tracks.md").read_text(encoding="utf-8")
    assert "| Herbie, Nobody | Watermelon | Alb | 1962 | 11:40 | 50 | jazz funk |  | Jazz |" in tracks


def test_load_without_pull_fails_clearly(tmp_path):
    with pytest.raises(analyze.AnalyzeError, match="dj analyze"):
        analyze.load(tmp_path)


def test_family_first_match_wins():
    assert analyze.family("jazz house") == "house"
    assert analyze.family("indie pop") == "rock / indie"
    assert analyze.family("bossa nova") == "jazz"
    assert analyze.family("jazz funk") == "jazz"
    assert analyze.family("zzz") == "other"


def test_owner_filter_keeps_me_and_named_owner(pulled):
    _, cache, _ = pulled
    lib = analyze.load(cache, owners=["me"])
    assert [p["name"] for p in lib.playlists] == ["Deep"] and lib.excluded == ["Jazz"]
    assert lib.tracks["t2"].playlists == ["Deep"] and "t3" not in lib.tracks
    lib = analyze.load(cache, owners=["SOMEONE"])
    assert [p["name"] for p in lib.playlists] == ["Jazz"]
    summary = analyze.summary_md(lib)
    assert "Owner filter active: 1 playlists" in summary
    assert "| jazz | 2 | 100% | Jazz |" in summary  # family from the playlist name


def test_pull_skips_artist_fetch_when_spotify_returns_no_genres(tmp_path):
    api = FakeAPI()
    for a in ARTISTS.values():
        a["genres"] = []
    try:
        counts = analyze.pull(api, tmp_path)
        assert counts["genres_available"] is False and api.artist_calls == []
        lib = analyze.load(tmp_path)
        assert not lib.genres_available
        assert "Spotify returned no artist genres" in analyze.summary_md(lib)
    finally:
        ARTISTS["a_Moodymann"]["genres"] = ["deep house", "detroit techno"]
        ARTISTS["a_Herbie"]["genres"] = ["jazz funk"]


def test_pull_works_with_a_client_that_has_no_artist_batch(tmp_path):
    class NoBatch(FakeAPI):
        artists = None  # GET /artists?ids= is gone (R-804, C-06): calling it would raise

    counts = analyze.pull(NoBatch(), tmp_path)
    assert counts["artists"] == 2  # followed + top only


def test_no_popularity_from_spotify_is_no_average_not_zero(pulled):
    # R-804: popularity is one of the fields removed in Feb 2026 (C-06). A missing score must
    # not turn into an average of 0; tracks that do carry one are averaged on their own.
    _, cache, _ = pulled
    lib = analyze.load(cache)
    for t in lib.tracks.values():
        t.popularity = None
    assert {s["name"]: s["avg_pop"] for s in analyze.playlist_stats(lib)} == {"Deep": None, "Jazz": None}
    assert "Spotify returned no popularity scores to this app." in analyze.summary_md(lib)
    playlists = analyze.playlists_md(lib)
    assert "| avg pop: -\n" in playlists and "avg pop: 0" not in playlists
    lib.tracks["t2"].popularity = 40  # Chameleon, in both playlists
    assert {s["name"]: s["avg_pop"] for s in analyze.playlist_stats(lib)} == {"Deep": 40, "Jazz": 40}


def test_duplicate_playlist_names_are_kept_apart(pulled):
    _, cache, _ = pulled
    import json as _json
    pl = _json.loads((cache / "playlists.json").read_text(encoding="utf-8"))
    pl.append(dict(pl[0], id="p1b"))
    (cache / "playlists.json").write_text(_json.dumps(pl), encoding="utf-8")
    lib = analyze.load(cache)
    assert [p["name"] for p in lib.playlists] == ["Deep", "Jazz", "Deep (2)"]
    assert lib.tracks["t1"].playlists == ["Deep", "Deep (2)"]


class GonePlaylistAPI(FakeAPI):
    """One followed playlist answers 404 (not readable, or deleted since the listing)."""

    def __init__(self, code=404):
        super().__init__()
        self.code = code

    def playlist_items(self, pid):
        if pid == "p2":
            raise SpotifyError(f"GET https://api.spotify.com/v1/playlists/p2/items -> {self.code} x")
        return super().playlist_items(pid)


def test_a_404_playlist_is_skipped_like_a_403_not_the_end_of_the_census(tmp_path):
    progress = []
    counts = analyze.pull(GonePlaylistAPI(), tmp_path / "cache", progress.append)
    assert (counts["playlists"], counts["skipped"]) == (1, 2)
    skipped = json.loads((tmp_path / "cache" / "skipped.json").read_text(encoding="utf-8"))
    assert [(s["name"], s["status"]) for s in skipped] == [("Jazz", 404), ("Editorial", 403)]
    assert "playlist Jazz: SKIPPED (404, not found, or not readable by this app)" in progress
    summary = analyze.summary_md(analyze.load(tmp_path / "cache"))
    assert "Jazz (404); Editorial (403)" in summary


def test_other_spotify_errors_still_stop_the_census(tmp_path):
    with pytest.raises(SpotifyError, match="500"):
        analyze.pull(GonePlaylistAPI(code=500), tmp_path / "cache")
