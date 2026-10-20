# Spotify audit: February 2026 Web API changes

R-804. Every Spotify endpoint and response field dj-librarian uses, checked against C-06
(`docs/requirements.md`) and the Spotify notes in `docs/lessons.md`. Written 2026-10-20 for W-25.
Offline: no live call was made. A live run on a real account is still open (R-805 acceptance).

Status: **ok** = works as written · **fixed** = changed in W-25 · **removed** = the endpoint is gone
and the code no longer calls it · **degraded** = still called, but a field may be missing and the
code copes.

Result: 15 endpoint rows (9 ok, 1 fixed, 4 removed and never called, 1 degraded) and 5 field rows
(1 ok, 1 fixed, 3 degraded). No call left that would fail on the February 2026 API.

## Endpoints

| Endpoint | Status | Evidence | Note |
|---|---|---|---|
| `GET /v1/search` | ok | `src/dj/spotify.py:214-217`; callers `src/dj/push.py:69-77` (push), `src/dj/build.py:76-77` (build) | `limit` capped at `min(limit, 10)` (C-06: max 10). Always sent explicitly. |
| `GET /v1/me/playlists` | ok | `src/dj/spotify.py:219-220`; `src/dj/intake.py:225-233`, `src/dj/analyze.py:121`, `pull_spotify.py:79` | Also lists playlists the DJ follows from other users; their items answer 403 or 404 (next row). |
| `GET /v1/playlists/{id}/items` | fixed | `src/dj/spotify.py:222-231`, `src/dj/spotify.py:57-83`; `src/dj/intake.py:205`, `src/dj/intake.py:236-245`; `src/dj/analyze.py:100`, `src/dj/analyze.py:127-139`; `src/dj/push.py:112`; `pull_spotify.py:63`, `pull_spotify.py:89` | `/items` and rows with `item` were already in place. A dev-mode app reads only playlists the user owns or collaborates on: `dj pull` of any other playlist now stops with a plain error that names the fix instead of a raw 403/404; `dj analyze` skips it (403 and 404 alike) and says why. One test for both (`spotify.refused_status`, messages in `spotify.UNREADABLE_PLAYLIST`): a 404 names both causes (gone or mistyped, or not readable) and both fixes. |
| `POST /v1/me/playlists` | ok | `src/dj/spotify.py:260-262`; `src/dj/push.py:116` | Body `public: false`. The removed `POST /users/{id}/playlists` is not used. |
| `POST /v1/playlists/{id}/items` | ok | `src/dj/spotify.py:264-267`; `src/dj/push.py:127-129` | At most 100 URIs per request. Adds only, to a playlist the app created. |
| `GET /v1/me` | degraded | `src/dj/spotify.py:235-236`; `src/dj/analyze.py:115-118` | `dj analyze` only. `country` read with `.get`, may be missing; `email` is never stored. |
| `GET /v1/me/tracks` | ok | `src/dj/spotify.py:238-240`; `src/dj/analyze.py:145` | `dj analyze` only (`user-library-read`). Not named in C-06; not yet confirmed live. |
| `GET /v1/me/albums` | ok | `src/dj/spotify.py:242-244`; `src/dj/analyze.py:150` | As above. |
| `GET /v1/me/following?type=artist` | ok | `src/dj/spotify.py:246-252`; `src/dj/analyze.py:154` | `dj analyze` only (`user-follow-read`). Not named in C-06; not yet confirmed live. |
| `GET /v1/me/top/{artists,tracks}` | ok | `src/dj/spotify.py:254-258`; `src/dj/analyze.py:160-161` | `dj analyze` only (`user-top-read`). |
| `GET /v1/artists?ids=` | removed | was `Spotify.artists`, called by `analyze.pull`; now `src/dj/analyze.py:172-178` | Batch fetch removed in Feb 2026. Method and call deleted: only followed and top artists carry details. |
| `GET /v1/tracks?ids=`, `GET /v1/albums?ids=` | removed | no caller, no client method (`src/dj/spotify.py:16-19`) | Batch fetches removed in Feb 2026. Never used. |
| `GET/POST /v1/users/{id}/playlists` | removed | no caller | Other users' endpoints removed in Feb 2026. Creation goes through `/me/playlists`. |
| `/v1/audio-features`, `/v1/audio-analysis`, `/v1/recommendations` | removed | no caller | Closed to new apps since November 2024. BPM and key come from rekordbox; the shopping list shows `-`. |
| `accounts.spotify.com/authorize`, `/api/token` (OAuth) | ok | `src/dj/spotify.py:104-154`; `pull_spotify.py:43`, `pull_spotify.py:48` | Not Web API. Client ID, secret, code and refresh token go only here. The bearer token goes only to `https://api.spotify.com/v1/` (`src/dj/spotify.py:193`); `pull_spotify.py:53` now refuses a `next` link to any other host (fixed in W-25, hard rule 6). |

## Response fields

| Field | Status | Evidence | Note |
|---|---|---|---|
| playlist row `item` (was `track`) | ok | `src/dj/intake.py:205`, `src/dj/spotify.py:228`, `src/dj/analyze.py:100`, `pull_spotify.py:63` | `item` wins; an old `track` row still reads. |
| track `external_ids.isrc` | degraded | `src/dj/intake.py:217`, `src/dj/push.py:64`, `src/dj/analyze.py:82`, `pull_spotify.py:70` | Read with `.get`; may be missing. Without it a match rests on artist, title and duration. |
| track or album `label` | degraded | `src/dj/intake.py:218` → `src/dj/shopping.py` | New in W-25, optional. The shopping list shows `-` when Spotify sends none. |
| `popularity` (track, artist) | fixed | `src/dj/analyze.py:72`, `src/dj/analyze.py:80`, `src/dj/analyze.py:432-441`, `src/dj/analyze.py:557-560`, `src/dj/analyze.py:633` | Removed field (C-06). The playlist average no longer counts a missing score as 0: no scores, no average (`-`). |
| artist `genres`, `followers` | degraded | `src/dj/analyze.py:71-73`, `src/dj/analyze.py:176-178` | Empty for this app; the census says so. Genre calls come from artists and labels. |

## Tests

- `tests/test_spotify_feb2026.py`: a fake Spotify that answers only the endpoints above (ok or
  degraded) and fails on any removed endpoint, a search limit over 10, another host or a missing
  token; `dj pull`, `dj push`, `dj build` and `dj analyze` run through it. Plus `dj build` and
  `dj push` dry-runs with a DJ's own `.env` (R-805), and the `next`-link guard of `pull_spotify.py`.
- `tests/test_spotify.py`: token only to `api.spotify.com`, no artist batch.
- `tests/test_analyze.py`: no artist batch call; no popularity means no average; a 404 playlist is
  skipped like a 403, any other error still stops the census.
- `tests/test_links_per_dj.py`: the inbox loop from the DJ's library folder (R-802).
