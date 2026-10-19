"""dj analyze: a read-only census of the Spotify library.

Pull everything once into .cache/library/*.json (playlists, Liked Songs, saved albums,
followed artists, top items, artist genres), then write reports/library/*.md:

  00_summary.md    computed stats and rankings, meant to be read whole
  01_artists.md    one line per artist, by track count
  02_playlists.md  one section per playlist: stats, then its tracks
  03_liked.md      Liked Songs only, newest save first, with the playlists each one is in
  10_tracks.md     one line per unique track, sorted by artist; grep it, never read it whole

Spotify is only read. rekordbox is never touched. Genres live on artists, not tracks, so
"genre" here means the union of the track's artists' genres. Audio features (BPM, energy)
are not available to this app, so they are not part of the census.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from dj.safety import REPO_ROOT
from dj.spotify import SpotifyError

CACHE_DIR = REPO_ROOT / ".cache" / "library"
REPORT_DIR = REPO_ROOT / "reports" / "library"
TIME_RANGES = ("short_term", "medium_term", "long_term")
TOP_N = 40

# Coarse genre families for the summary. First match wins, so order matters:
# "jazz house" is house, "jazz funk" is jazz, "indie pop" is rock / indie.
FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("house", ("house",)),
    ("techno", ("techno", "minimal", "acid", "schranz")),
    ("disco / boogie", ("disco", "boogie", "italo")),
    ("jazz", ("jazz", "bebop", "bossa", "swing", "big band")),
    ("funk / soul / r&b", ("funk", "soul", "r&b", "rnb", "motown", "gospel", "quiet storm")),
    ("hip hop / rap", ("hip hop", "rap", "trap", "drill", "boom bap", "grime")),
    ("bass / breaks / dnb", ("drum and bass", "dnb", "jungle", "breakbeat", "breaks", "dubstep",
                             "garage", "bass", "footwork", "juke")),
    ("electronic / downtempo", ("electro", "downtempo", "trip hop", "idm", "ambient", "chill",
                                "lo-fi", "lofi", "trance", "edm", "synth", "new age", "glitch",
                                "dance", "rave", "big beat")),
    ("reggae / dub", ("reggae", "dub", "dancehall", "ska")),
    ("latin / afro / world", ("latin", "afro", "brazil", "samba", "cumbia", "salsa", "world",
                              "balkan", "arab", "turkish", "bossa", "tropical", "highlife",
                              "amapiano", "bhangra", "flamenco", "tango")),
    ("rock / indie", ("rock", "indie", "punk", "metal", "grunge", "shoegaze", "post-",
                      "alternative", "emo", "garage rock", "psych")),
    ("folk / country / blues", ("folk", "country", "blues", "bluegrass", "americana",
                                "singer-songwriter")),
    ("classical / soundtrack", ("classical", "soundtrack", "score", "orchestra", "piano",
                                "baroque", "opera", "modern composition")),
    ("pop", ("pop",)),
)


class AnalyzeError(RuntimeError):
    pass


# -- pull ------------------------------------------------------------------------------


def slim_artist(a: dict[str, Any]) -> dict[str, Any]:
    return {"id": a.get("id"), "name": a.get("name"), "genres": a.get("genres") or [],
            "popularity": a.get("popularity"),
            "followers": (a.get("followers") or {}).get("total")}


def slim_track(t: dict[str, Any]) -> dict[str, Any]:
    album = t.get("album") or {}
    return {
        "id": t.get("id"), "uri": t.get("uri"), "name": t.get("name"),
        "duration_ms": t.get("duration_ms") or 0, "popularity": t.get("popularity"),
        "explicit": bool(t.get("explicit")), "is_local": bool(t.get("is_local")),
        "isrc": (t.get("external_ids") or {}).get("isrc"),
        "artists": [{"id": a.get("id"), "name": a.get("name")} for a in t.get("artists") or []],
        "album": {"id": album.get("id"), "name": album.get("name"),
                  "release_date": album.get("release_date"),
                  "album_type": album.get("album_type")},
    }


def slim_album(a: dict[str, Any]) -> dict[str, Any]:
    return {"id": a.get("id"), "name": a.get("name"), "release_date": a.get("release_date"),
            "album_type": a.get("album_type"), "total_tracks": a.get("total_tracks"),
            "artists": [{"id": x.get("id"), "name": x.get("name")} for x in a.get("artists") or []]}


def _rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """{added_at, track} rows -> slim rows. Rows without a track are dropped."""
    out = []
    for row in rows:
        track = row.get("item") or row.get("track")  # Feb 2026 rename: track -> item
        if track:
            out.append({"added_at": row.get("added_at"), "track": slim_track(track)})
    return out


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def pull(api: Any, cache_dir: Path | None = None,
         progress: Callable[[str], None] = lambda _: None) -> dict[str, Any]:
    """Read the whole library into cache_dir. Returns counts."""
    cache = cache_dir or CACHE_DIR
    me = api.me()
    my_id = me.get("id")
    _write(cache / "me.json", {"id": my_id, "display_name": me.get("display_name"),
                               "country": me.get("country")})

    playlists, skipped = [], []
    for p in api.my_playlists():
        owner = p.get("owner") or {}
        entry = {"id": p["id"], "name": p.get("name"), "description": p.get("description"),
                 "owner_id": owner.get("id"), "owner_name": owner.get("display_name"),
                 "mine": owner.get("id") == my_id, "public": p.get("public"),
                 "collaborative": bool(p.get("collaborative"))}
        try:
            entry["rows"] = _rows(api.playlist_items(p["id"]))
        except SpotifyError as exc:
            # Spotify-owned editorial / algorithmic playlists answer 403 to dev-mode apps.
            if "403" not in str(exc):
                raise
            skipped.append({"name": entry["name"], "owner": entry["owner_name"]})
            progress(f"playlist {entry['name']}: SKIPPED (403, Spotify-owned)")
            continue
        playlists.append(entry)
        progress(f"playlist {entry['name']}: {len(entry['rows'])} rows")
    _write(cache / "playlists.json", playlists)
    _write(cache / "skipped.json", skipped)

    liked = _rows(api.saved_tracks())
    progress(f"liked songs: {len(liked)}")
    _write(cache / "liked.json", liked)

    albums = [{"added_at": r.get("added_at"), "album": slim_album(r["album"])}
              for r in api.saved_albums() if r.get("album")]
    progress(f"saved albums: {len(albums)}")
    _write(cache / "albums.json", albums)

    followed = [slim_artist(a) for a in api.followed_artists()]
    progress(f"followed artists: {len(followed)}")
    _write(cache / "followed.json", followed)

    top: dict[str, dict[str, list[dict[str, Any]]]] = {"artists": {}, "tracks": {}}
    for rng in TIME_RANGES:
        top["artists"][rng] = [slim_artist(a) for a in api.top_items("artists", rng)]
        top["tracks"][rng] = [slim_track(t) for t in api.top_items("tracks", rng)]
    _write(cache / "top.json", top)

    known = {a["id"]: a for a in followed if a.get("id")}
    for rng in TIME_RANGES:
        known.update({a["id"]: a for a in top["artists"][rng] if a.get("id")})
    wanted: set[str] = set()
    for track in _all_tracks(playlists, liked, top):
        wanted.update(a["id"] for a in track["artists"] if a.get("id"))
    for row in albums:
        wanted.update(a["id"] for a in row["album"]["artists"] if a.get("id"))
    missing = sorted(wanted - set(known))
    progress(f"artists: {len(wanted)} distinct, fetching {len(missing)}")
    genres_available = any(a.get("genres") for a in known.values())
    if not genres_available:
        # Spotify no longer returns artist genres to apps like this one (2025); when even
        # the top/followed artists carry none, thousands of lookups would return nothing.
        progress("artist genres: none returned by Spotify, skipping the artist fetch")
    else:
        try:
            for a in api.artists(missing):
                if a.get("id"):
                    known[a["id"]] = slim_artist(a)
        except SpotifyError as exc:
            if "403" not in str(exc):
                raise
            progress("artist genres: batch endpoint forbidden (403), keeping what we have")
    _write(cache / "artists.json", known)
    _write(cache / "pulled.json", {"pulled_at": datetime.now(timezone.utc).isoformat(),
                                   "playlists": len(playlists), "liked": len(liked),
                                   "albums": len(albums), "followed": len(followed),
                                   "artists": len(known), "genres_available": genres_available})
    return {"playlists": len(playlists), "playlist_rows": sum(len(p["rows"]) for p in playlists),
            "skipped": len(skipped), "liked": len(liked),
            "albums": len(albums), "followed": len(followed),
            "artists": len(known), "genres_available": genres_available, "cache": str(cache)}


def _all_tracks(playlists: list[dict[str, Any]], liked: list[dict[str, Any]],
                top: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for p in playlists:
        for row in p["rows"]:
            yield row["track"]
    for row in liked:
        yield row["track"]
    for rng in TIME_RANGES:
        yield from top["tracks"].get(rng, [])


# -- model -----------------------------------------------------------------------------


@dataclass
class Track:
    id: str
    name: str
    artist_ids: list[str]
    artist_names: list[str]
    album: str
    year: int | None
    album_type: str | None
    duration_ms: int
    popularity: int | None
    explicit: bool
    playlists: list[str] = field(default_factory=list)
    liked_at: str | None = None

    @property
    def artist(self) -> str:
        return ", ".join(self.artist_names) or "?"

    @property
    def liked(self) -> bool:
        return self.liked_at is not None


@dataclass
class Library:
    me: dict[str, Any]
    playlists: list[dict[str, Any]]
    liked: list[dict[str, Any]]
    albums: list[dict[str, Any]]
    followed: list[dict[str, Any]]
    top: dict[str, Any]
    artists: dict[str, dict[str, Any]]
    tracks: dict[str, Track]
    local_rows: int
    skipped: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)  # playlists dropped by the owner filter
    genres_available: bool = True

    def genres_of(self, track: Track) -> list[str]:
        seen: list[str] = []
        for aid in track.artist_ids:
            for g in (self.artists.get(aid) or {}).get("genres") or []:
                if g not in seen:
                    seen.append(g)
        return seen


def _year(date: str | None) -> int | None:
    if not date or len(date) < 4 or not date[:4].isdigit():
        return None
    return int(date[:4])


def _key(t: dict[str, Any]) -> str | None:
    """Spotify id, or a stable key for local files so they still count once."""
    if t.get("id"):
        return t["id"]
    if t.get("is_local") and t.get("name"):
        return "local:" + "|".join([t["name"]] + [a.get("name") or "" for a in t["artists"]])
    return None


def _track(t: dict[str, Any], key: str) -> Track:
    return Track(id=key, name=t.get("name") or "?",
                 artist_ids=[a["id"] for a in t["artists"] if a.get("id")],
                 artist_names=[a.get("name") or "?" for a in t["artists"]],
                 album=(t.get("album") or {}).get("name") or "", year=_year((t.get("album") or {}).get("release_date")),
                 album_type=(t.get("album") or {}).get("album_type"),
                 duration_ms=t.get("duration_ms") or 0, popularity=t.get("popularity"),
                 explicit=bool(t.get("explicit")))


def _owned_by(playlist: dict[str, Any], owners: set[str], my_id: str | None) -> bool:
    if "me" in owners and playlist.get("owner_id") == my_id:
        return True
    return bool({(playlist.get("owner_id") or "").lower(),
                 (playlist.get("owner_name") or "").lower()} & owners)


def load(cache_dir: Path | None = None, owners: Iterable[str] = ()) -> Library:
    """owners: playlist owner ids or display names to keep; "me" is the logged-in user.
    Empty keeps every playlist."""
    cache = cache_dir or CACHE_DIR
    if not (cache / "pulled.json").is_file():
        raise AnalyzeError(f"No cached pull in {cache}. Run `dj analyze` without --cached.")

    def read(name: str) -> Any:
        return json.loads((cache / name).read_text(encoding="utf-8"))

    me, pulled = read("me.json"), read("pulled.json")
    playlists, liked = read("playlists.json"), read("liked.json")
    excluded: list[str] = []
    wanted = {o.lower() for o in owners}
    if wanted:
        kept = [p for p in playlists if _owned_by(p, wanted, me.get("id"))]
        excluded = [p["name"] or "?" for p in playlists if p not in kept]
        playlists = kept
    seen: Counter[str] = Counter()
    for p in playlists:  # two playlists may share a name; keep them apart in the reports
        seen[p["name"]] += 1
        if seen[p["name"]] > 1:
            p["name"] = f"{p['name']} ({seen[p['name']]})"
    tracks: dict[str, Track] = {}
    local_rows = 0
    for p in playlists:
        for row in p["rows"]:
            key = _key(row["track"])
            if key is None:
                continue
            if key.startswith("local:"):
                local_rows += 1
            track = tracks.setdefault(key, _track(row["track"], key))
            if p["name"] not in track.playlists:
                track.playlists.append(p["name"])
    for row in liked:
        key = _key(row["track"])
        if key is None:
            continue
        track = tracks.setdefault(key, _track(row["track"], key))
        track.liked_at = row.get("added_at") or ""
    return Library(me=me, playlists=playlists, liked=liked, albums=read("albums.json"),
                   followed=read("followed.json"), top=read("top.json"), artists=read("artists.json"),
                   tracks=tracks, local_rows=local_rows,
                   skipped=read("skipped.json") if (cache / "skipped.json").is_file() else [],
                   excluded=excluded, genres_available=pulled.get("genres_available", True))


# -- stats -----------------------------------------------------------------------------


def family(genre: str) -> str:
    g = genre.lower()
    for name, keys in FAMILIES:
        if any(k in g for k in keys):
            return name
    return "other"


def hours(ms: int) -> str:
    return f"{ms / 3_600_000:.1f} h"


def mmss(ms: int) -> str:
    s = round(ms / 1000)
    return f"{s // 60}:{s % 60:02d}"


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "/").replace("\n", " ").strip()


def table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return lines


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def _decade(year: int | None) -> str:
    return f"{year // 10 * 10}s" if year else "unknown"


def _bucket(value: int | None, edges: tuple[int, ...], labels: tuple[str, ...]) -> str:
    if value is None:
        return "unknown"
    for edge, label in zip(edges, labels):
        if value < edge:
            return label
    return labels[-1]


def artist_rows(lib: Library) -> list[dict[str, Any]]:
    """Per artist: track count, liked count, playlists, genres. Sorted by tracks desc."""
    per: dict[str, dict[str, Any]] = {}
    for t in lib.tracks.values():
        for aid, name in zip(t.artist_ids, t.artist_names):
            row = per.setdefault(aid, {"id": aid, "name": name, "tracks": 0, "liked": 0,
                                       "playlists": set()})
            row["tracks"] += 1
            row["liked"] += t.liked
            row["playlists"].update(t.playlists)
    out = []
    for row in per.values():
        info = lib.artists.get(row["id"]) or {}
        row["genres"] = info.get("genres") or []
        row["popularity"] = info.get("popularity")
        row["playlists"] = sorted(row["playlists"])
        out.append(row)
    out.sort(key=lambda r: (-r["tracks"], -r["liked"], r["name"].lower()))
    return out


def genre_counts(lib: Library) -> tuple[Counter[str], Counter[str], Counter[str], int]:
    """(genre -> tracks, genre -> artists, family -> tracks, tracks with any genre)."""
    by_track: Counter[str] = Counter()
    by_fam: Counter[str] = Counter()
    with_genre = 0
    for t in lib.tracks.values():
        genres = lib.genres_of(t)
        if genres:
            with_genre += 1
        by_track.update(genres)
        by_fam.update({family(g) for g in genres} or {"unknown"})
    by_artist: Counter[str] = Counter()
    seen = {aid for t in lib.tracks.values() for aid in t.artist_ids}
    for aid in seen:
        by_artist.update((lib.artists.get(aid) or {}).get("genres") or [])
    return by_track, by_artist, by_fam, with_genre


def playlist_stats(lib: Library) -> list[dict[str, Any]]:
    by_name: dict[str, list[Track]] = defaultdict(list)
    for t in lib.tracks.values():
        for name in t.playlists:
            by_name[name].append(t)
    out = []
    for p in lib.playlists:
        ts = by_name.get(p["name"], [])
        genres: Counter[str] = Counter()
        artists: Counter[str] = Counter()
        for t in ts:
            genres.update(lib.genres_of(t))
            artists.update(t.artist_names)
        years = [t.year for t in ts if t.year]
        out.append({
            "name": p["name"], "mine": p["mine"], "owner": p.get("owner_name") or p.get("owner_id"),
            "rows": len(p["rows"]), "tracks": len(ts),
            "only_here": sum(len(t.playlists) == 1 for t in ts),
            "liked": sum(t.liked for t in ts),
            "duration_ms": sum(t.duration_ms for t in ts),
            "median_year": sorted(years)[len(years) // 2] if years else None,
            "avg_pop": round(sum(t.popularity or 0 for t in ts) / len(ts)) if ts else None,
            "top_genres": [g for g, _ in genres.most_common(3)],
            "top_artists": [a for a, _ in artists.most_common(3)],
            "tracks_list": sorted(ts, key=lambda t: (t.artist.lower(), t.name.lower())),
        })
    return out


def filing_families(lib: Library) -> list[tuple[str, int, list[str]]]:
    """(family, tracks, playlist names) from playlist names alone, most tracks first."""
    fam_of = {p["name"]: family(p["name"] or "") for p in lib.playlists}
    counts: Counter[str] = Counter()
    names: dict[str, list[str]] = defaultdict(list)
    for t in lib.tracks.values():
        counts.update({fam_of[n] for n in t.playlists if n in fam_of})
    for name, fam in fam_of.items():
        names[fam].append(name)
    return [(f, n, sorted(names[f], key=str.lower)) for f, n in counts.most_common()]


def overlaps(lib: Library, limit: int = 20) -> list[tuple[str, str, int]]:
    ids: dict[str, set[str]] = defaultdict(set)
    for t in lib.tracks.values():
        for name in t.playlists:
            ids[name].add(t.id)
    names = sorted(ids)
    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            n = len(ids[a] & ids[b])
            if n:
                pairs.append((a, b, n))
    pairs.sort(key=lambda x: -x[2])
    return pairs[:limit]


# -- reports ---------------------------------------------------------------------------


def summary_md(lib: Library) -> str:
    tracks = list(lib.tracks.values())
    mine = [p for p in lib.playlists if p["mine"]]
    rows_total = sum(len(p["rows"]) for p in lib.playlists)
    in_playlist = [t for t in tracks if t.playlists]
    liked = [t for t in tracks if t.liked]
    liked_only = [t for t in liked if not t.playlists]
    by_track, by_artist, by_fam, with_genre = genre_counts(lib)
    arts = artist_rows(lib)
    stats = playlist_stats(lib)

    L: list[str] = [f"# Spotify library census: {lib.me.get('display_name') or lib.me.get('id')}", ""]
    L += ["Pulled from the Spotify API by dj-librarian. Genres come from artists, not tracks. "
          "Popularity is Spotify's 0-100 score.", "", "## Totals", ""]
    L += table(["metric", "value"], [
        ["playlists", f"{len(lib.playlists)} ({len(mine)} mine, {len(lib.playlists) - len(mine)} followed)"],
        ["playlist rows (with duplicates)", rows_total],
        ["unique tracks in playlists", len(in_playlist)],
        ["Liked Songs", len(liked)],
        ["Liked Songs not in any playlist", f"{len(liked_only)} ({_pct(len(liked_only), len(liked))})"],
        ["playlist tracks also liked", f"{sum(t.liked for t in in_playlist)} ({_pct(sum(t.liked for t in in_playlist), len(in_playlist))})"],
        ["unique tracks overall", len(tracks)],
        ["local files in playlists", lib.local_rows],
        ["unique artists", len(arts)],
        ["artists with genre data", f"{sum(bool(a['genres']) for a in arts)} ({_pct(sum(bool(a['genres']) for a in arts), len(arts))})"],
        ["tracks with genre data", f"{with_genre} ({_pct(with_genre, len(tracks))})"],
        ["saved albums", len(lib.albums)],
        ["followed artists", len(lib.followed)],
        ["total listening time (unique tracks)", hours(sum(t.duration_ms for t in tracks))],
        ["average track length", mmss(sum(t.duration_ms for t in tracks) // max(len(tracks), 1))],
        ["explicit tracks", f"{sum(t.explicit for t in tracks)} ({_pct(sum(t.explicit for t in tracks), len(tracks))})"],
    ])

    L += ["", "## Playlists", "", "`only here` = tracks in no other playlist. `liked` = also in Liked Songs.", ""]
    if lib.excluded:
        L += [f"Owner filter active: {len(lib.excluded)} playlists by other owners left out.", ""]
    if lib.skipped:
        L += ["Not readable by this app (Spotify-owned, 403): " +
              "; ".join(p["name"] or "?" for p in lib.skipped), ""]
    L += table(["playlist", "owner", "tracks", "only here", "liked", "length", "median year", "avg pop", "top genres", "top artists"],
               [[s["name"], "me" if s["mine"] else s["owner"], s["tracks"], s["only_here"], s["liked"],
                 hours(s["duration_ms"]), s["median_year"], s["avg_pop"],
                 "; ".join(s["top_genres"]), "; ".join(s["top_artists"])] for s in stats])

    L += ["", f"## Top {TOP_N} artists by unique tracks", "", "Full list in 01_artists.md.", ""]
    L += table(["#", "artist", "tracks", "liked", "playlists", "pop", "genres"],
               [[i + 1, a["name"], a["tracks"], a["liked"], len(a["playlists"]), a["popularity"],
                 "; ".join(a["genres"][:4])] for i, a in enumerate(arts[:TOP_N])])

    L += ["", "## Genre families by playlist name (your own filing)", "",
          "Each playlist name mapped to a coarse family by keyword; a track counts once per family it is filed under.", ""]
    L += table(["family", "tracks", "share of playlist tracks", "playlists"],
               [[f, n, _pct(n, len(in_playlist)), "; ".join(names)] for f, n, names in filing_families(lib)])

    if not lib.genres_available:
        L += ["", "## Genres from Spotify", "",
              "Spotify returned no artist genres to this app, so the genre columns below and in the other files are empty. "
              "Genre judgments must come from the artists and labels themselves.", ""]
    L += ["", "## Genre families (artist genres, tracks)", "", "Coarse keyword grouping of artist genres; a track counts once per family.", ""]
    L += table(["family", "tracks", "share"],
               [[f, n, _pct(n, len(tracks))] for f, n in by_fam.most_common()])

    L += ["", f"## Top {TOP_N} genres", "", "`tracks` = tracks with at least one artist in that genre. `artists` = distinct artists.", ""]
    L += table(["#", "genre", "tracks", "artists"],
               [[i + 1, g, n, by_artist.get(g, 0)] for i, (g, n) in enumerate(by_track.most_common(TOP_N))])

    dec: Counter[str] = Counter(_decade(t.year) for t in tracks)
    L += ["", "## Release decades", ""]
    L += table(["decade", "tracks", "share"],
               [[d, n, _pct(n, len(tracks))] for d, n in sorted(dec.items(), key=lambda x: x[0])])
    yrs: Counter[int] = Counter(t.year for t in tracks if t.year)
    L += ["", "Top release years:", ""]
    L += table(["year", "tracks"], [[y, n] for y, n in yrs.most_common(15)])

    pop_edges, pop_labels = (20, 40, 60, 80), ("0-19 obscure", "20-39", "40-59", "60-79", "80-100 hits")
    pops: Counter[str] = Counter(_bucket(t.popularity, pop_edges, pop_labels) for t in tracks)
    L += ["", "## Popularity", ""]
    if pops.get("unknown", 0) == len(tracks):
        L += ["Spotify returned no popularity scores to this app.", ""]
    else:
        L += table(["bucket", "tracks", "share"],
                   [[b, pops.get(b, 0), _pct(pops.get(b, 0), len(tracks))] for b in pop_labels + ("unknown",) if pops.get(b)])

    dur_edges = (180_000, 300_000, 420_000, 600_000)
    dur_labels = ("< 3:00", "3:00-4:59", "5:00-6:59", "7:00-9:59", "10:00+")
    durs: Counter[str] = Counter(_bucket(t.duration_ms, dur_edges, dur_labels) for t in tracks)
    L += ["", "## Track length", ""]
    L += table(["bucket", "tracks", "share"],
               [[b, durs.get(b, 0), _pct(durs.get(b, 0), len(tracks))] for b in dur_labels])

    types: Counter[str] = Counter(t.album_type or "unknown" for t in tracks)
    L += ["", "## Release type", ""]
    L += table(["type", "tracks"], [[k, n] for k, n in types.most_common()])

    liked_years: Counter[str] = Counter((t.liked_at or "")[:4] or "unknown" for t in liked)
    if liked:
        L += ["", "## Liked Songs by year saved", ""]
        L += table(["year", "saved"], [[y, n] for y, n in sorted(liked_years.items())])

    L += ["", "## Playlist overlap (shared tracks)", ""]
    ov = overlaps(lib)
    L += table(["playlist A", "playlist B", "shared"], [[a, b, n] for a, b, n in ov]) if ov else ["none"]

    multi = sorted((t for t in tracks if len(t.playlists) >= 3), key=lambda t: -len(t.playlists))[:25]
    if multi:
        L += ["", "## Tracks in the most playlists", ""]
        L += table(["artist", "title", "playlists"], [[t.artist, t.name, f"{len(t.playlists)}: " + "; ".join(t.playlists)] for t in multi])

    L += ["", "## Spotify top items (listening history)", "",
          "short_term = last 4 weeks, medium_term = 6 months, long_term = about a year.", ""]
    for rng in TIME_RANGES:
        arts_top = lib.top["artists"].get(rng, [])
        trks_top = lib.top["tracks"].get(rng, [])
        L += [f"### {rng}", "", "Artists: " + "; ".join(f"{i + 1}. {a['name']}" for i, a in enumerate(arts_top[:25])) or "none", ""]
        L += ["Tracks: " + "; ".join(f"{i + 1}. {', '.join(x.get('name') for x in t['artists'])} - {t['name']}"
                                     for i, t in enumerate(trks_top[:25])) or "none", ""]
        g: Counter[str] = Counter(x for a in arts_top for x in a.get("genres") or [])
        if g:
            L += ["Genres of these artists: " + "; ".join(f"{k} ({n})" for k, n in g.most_common(12)), ""]

    if lib.albums:
        L += ["## Saved albums", ""]
        L += table(["artist", "album", "year", "tracks", "saved"],
                   [[", ".join(a.get("name") or "?" for a in r["album"]["artists"]), r["album"]["name"],
                     _year(r["album"]["release_date"]), r["album"]["total_tracks"], (r.get("added_at") or "")[:10]]
                    for r in sorted(lib.albums, key=lambda r: r.get("added_at") or "", reverse=True)])

    if lib.followed:
        in_lib = {aid for t in tracks for aid in t.artist_ids}
        L += ["", "## Followed artists", "", "`in library` = has at least one track in a playlist or Liked Songs.", ""]
        L += table(["artist", "in library", "pop", "genres"],
                   [[a["name"], "yes" if a["id"] in in_lib else "no", a.get("popularity"), "; ".join((a.get("genres") or [])[:4])]
                    for a in sorted(lib.followed, key=lambda a: (a["name"] or "").lower())])
    return "\n".join(L) + "\n"


def artists_md(lib: Library) -> str:
    arts = artist_rows(lib)
    L = ["# Artists", "", f"{len(arts)} artists, by unique track count. `L` = liked tracks. `pl` = number of playlists.", ""]
    L += table(["artist", "tracks", "L", "pl", "pop", "genres", "in"],
               [[a["name"], a["tracks"], a["liked"], len(a["playlists"]), a["popularity"],
                 "; ".join(a["genres"]), "; ".join(a["playlists"])] for a in arts])
    return "\n".join(L) + "\n"


def playlists_md(lib: Library) -> str:
    L = ["# Playlists", ""]
    for s in playlist_stats(lib):
        L += [f"## {s['name']}", "",
              f"owner: {'me' if s['mine'] else s['owner']} | tracks: {s['tracks']} | only here: {s['only_here']} | "
              f"liked: {s['liked']} | length: {hours(s['duration_ms'])} | median year: {s['median_year']} | "
              f"avg pop: {s['avg_pop']}", "",
              f"top genres: {'; '.join(s['top_genres']) or '-'}", "",
              f"top artists: {'; '.join(s['top_artists']) or '-'}", ""]
        L += table(["artist", "title", "year", "len", "pop", "L"],
                   [[t.artist, t.name, t.year, mmss(t.duration_ms), t.popularity, "L" if t.liked else ""]
                    for t in s["tracks_list"]])
        L.append("")
    return "\n".join(L) + "\n"


def tracks_md(lib: Library) -> str:
    ts = sorted(lib.tracks.values(), key=lambda t: (t.artist.lower(), t.year or 0, t.name.lower()))
    L = ["# Tracks", "", f"{len(ts)} unique tracks, sorted by artist. `L` = liked. "
         "Columns: artist | title | album | year | len | pop | genres | L | playlists", ""]
    L += table(["artist", "title", "album", "year", "len", "pop", "genres", "L", "playlists"],
               [[t.artist, t.name, t.album, t.year, mmss(t.duration_ms), t.popularity,
                 "; ".join(lib.genres_of(t)), "L" if t.liked else "", "; ".join(t.playlists)] for t in ts])
    return "\n".join(L) + "\n"


def liked_md(lib: Library) -> str:
    """Liked Songs only, newest save first. `saved` is the date you hit the heart."""
    ts = sorted((t for t in lib.tracks.values() if t.liked),
                key=lambda t: ((t.liked_at or ""), t.artist.lower()), reverse=True)
    unfiled = sum(1 for t in ts if not t.playlists)
    years: Counter[str] = Counter((t.liked_at or "")[:4] or "?" for t in ts)
    L = ["# Liked Songs", "", f"{len(ts)} liked tracks, newest save first. {unfiled} of them are in no "
         "playlist (`playlists` column empty). Columns: saved | artist | title | album | year | len | playlists", "",
         "Saved per year: " + "; ".join(f"{y} {n}" for y, n in sorted(years.items())), ""]
    L += table(["saved", "artist", "title", "album", "year", "len", "playlists"],
               [[(t.liked_at or "")[:10], t.artist, t.name, t.album, t.year, mmss(t.duration_ms),
                 "; ".join(t.playlists)] for t in ts])
    return "\n".join(L) + "\n"


def write_reports(lib: Library, report_dir: Path | None = None) -> list[Path]:
    out = report_dir or REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    files = {"00_summary.md": summary_md, "01_artists.md": artists_md,
             "02_playlists.md": playlists_md, "03_liked.md": liked_md, "10_tracks.md": tracks_md}
    written = []
    for name, fn in files.items():
        path = out / name
        path.write_text(fn(lib), encoding="utf-8")
        written.append(path)
    return written
