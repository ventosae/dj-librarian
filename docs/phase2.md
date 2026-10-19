# Phase 2: Spotify intake (spec, not built yet)

Run inside the Phase 1 repo.

## GOAL
Phase 2 of dj-librarian: process a Spotify "inbox" playlist into a rekordbox crate.
Commands: dj pull, dj match, dj plan, dj apply. The CLAUDE.md hard rules apply.

## MODEL
- rekordbox is the truth. Spotify playlists are candidates, not members.
- The tool only PROPOSES. Nothing enters a crate without decision = yes in the plan file.
- A track I removed from a crate stays removed: state/declined.json. Never re-propose it.
- Tracks with no local file go to wishlist/<crate>.md. That is normal, not an error.

## SPOTIFY
- My own developer app, development mode. Authorization Code flow.
  Redirect URI http://127.0.0.1:8888/callback (must be 127.0.0.1, not localhost).
  Scopes: playlist-read-private playlist-read-collaborative. Nothing else.
- Credentials from .env (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET).
  Token cache in .cache/, gitignored.
- February 2026 API migration: use GET /v1/playlists/{id}/items (old /tracks returns 403).
  In responses `track` became `item`; accept both. My playlists: GET /v1/me/playlists.
- Verify every endpoint against the live Web API reference. Do not trust old tutorials.
  If spotipy still calls /tracks, use httpx directly.
- No audio features: BPM and key come from rekordbox, never from Spotify.
- pull_spotify.py in the repo root is a working bootstrap. Reuse its logic.

## FILE CONTRACT
```
links.yaml                          - spotify: <name|url|id>   crate: <path in the tree>
inbox/<playlist>.json               uri, title, artists[], album, duration_ms, isrc, added_at
state/match_cache.json              spotify_uri -> rb_content_id (confirmed by me)
state/declined.json                 [{crate, spotify_uri, date}]
plans/<date>-<crate>.plan.json      items: status + decision (pending|yes|no) + pick
reports/<date>-<crate>.report.json  what apply did
wishlist/<crate>.md                 missing tracks, grouped by artist, with the Spotify link
```

## MATCHING  (src/dj/match.py: if it already exists, use it, do not rewrite it)
Order: match_cache -> ISRC (when both sides have one) -> exact normalised artist+title
-> fuzzy (rapidfuzz token_set_ratio).
Normalise: lowercase, strip accents, "&" -> "and", drop "feat./ft./featuring ...",
drop bracketed text, collapse punctuation and whitespace.
Version words (edit, extended, remix, remaster, mix, version, mono) are NOT silently
dropped: keep them as a separate `version` field on both sides.
Status per track:
```
IN_CRATE   the matched file is already in the crate
PROPOSE    one confident match: score >= 90, duration within 3 s, versions compatible
AMBIGUOUS  several candidates, or score 75-89, or duration differs by more than 5 s,
           or version words differ. List the top 3: title, artist, duration, bitrate, path
MISSING    nothing above 75
DECLINED   (crate, uri) is in declined.json
```
DJ-specific: a Spotify original against my local "Extended Mix" or re-edit is AMBIGUOUS,
never PROPOSE. I decide once; the cache remembers.

## COMMANDS
```
dj pull <link>|--all   Spotify -> inbox/. Read-only.
dj match <link>        counts per status + the ambiguous list. Writes nothing.
dj plan <link>         writes the plan + the wishlist. Prints the paths.
dj apply <plan>        only decision = yes. rekordbox closed -> backup -> add -> one commit.
                       Then: ambiguous picks -> match_cache; no -> declined; write the report.
dj status              add: per link, counts by status and last sync date.
```
Every command takes --json for machine-readable output. An agent reads it.

## TESTS
pytest, no real DB: normalisation, version detection, score thresholds, declined and
cache behaviour, idempotent apply (a second apply adds nothing).

## STEPS
1. Read CLAUDE.md and README.md. Run `dj status` to confirm Phase 1 still works.
2. Build pull. Run it on my first link. Show me the count.
3. Build match + tests. Run match. Show counts and the ambiguous list. STOP for my review.
4. Build plan. Show me the plan path. I set the decisions, or tell you them.
5. Build apply. Dry-run first. STOP for my OK. Then apply and show the report.
6. Update README.md with every command and flag.

## Bootstrap
`pull_spotify.py` gets one real playlist out as JSON before the CLI exists. Stdlib only.
Parsing is tested against both response shapes. The OAuth path is untested against live
Spotify. Run: `python pull_spotify.py "funk_109_bpm"` next to the .env. A browser tab
opens once.

## Known pyrekordbox pitfalls for this phase (found during Phase 1 research)
- `add_to_playlist(playlist, content, track_no=None)`: leave `track_no` unset (append, no
  sibling updates). It rejects folders and smart playlists.
- Issue #194: `DjmdContent.FolderPath` is POSIX-style (`D:/Music/x.mp3`); normalise paths
  with `Path(p).as_posix()` before comparing.
- Issue #209: avoid `move_song_in_playlist` (not allowed by rule 3 anyway).
