---
name: dj-spotify
description: Connect a DJ's own Spotify account to dj-librarian and use it. Guided setup (Premium check, their own Spotify developer app, the redirect URI, two keys in the engine settings, first pull as proof), the Spotify limits since February 2026, the shopping list of missing tracks with Beatport and Bandcamp links, and pushing a rekordbox playlist or a text tracklist to Spotify. Use when the DJ wants to set up or connect Spotify, hits a Spotify login, redirect URI or 403 error, asks what to buy or for a shopping list, or wants a playlist or a tracklist on Spotify.
---

# dj-spotify

Spotify is a source of candidates and a place to share playlists. rekordbox stays the truth. On
Spotify the tool only creates private playlists and adds to them.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-801, R-802, R-803, R-804, R-805, C-06.

Run this setup only when the DJ asks for Spotify or a Spotify feature needs it (breadboard Y1).
It needs the engine on their computer (the dj-librarian tools). If `dj_status` does not answer,
set up the engine first (dj-start, engine card).

## Setup card: about 8 minutes

Show the DJ this card, one step at a time. Wait for "done" before the next step.

1. **Premium (1 min).** The owner of a Spotify developer app needs Spotify Premium (since
   February 2026). Every DJ uses their own app, so the DJ needs Premium themselves.
2. **Your own app (3 min).** Open developer.spotify.com/dashboard, log in, Create app. Name and
   description: anything. Redirect URI, exactly: `http://127.0.0.1:8888/callback`
   (`127.0.0.1`, not `localhost`). Tick **Web API**. Save, then open the app's Settings: the
   Client ID is shown, the Client Secret sits behind "View client secret".
3. **Two keys where the engine reads them (2 min).** Engine from `/dj-librarian:install`: a text
   file named `.env` in the engine folder (`dj-librarian` in the home folder, never the synced
   dj-library folder) with two lines, `SPOTIFY_CLIENT_ID=` and
   `SPOTIFY_CLIENT_SECRET=`, each followed by its key (`examples/.env.example` shows it). Engine
   as the desktop extension: its settings form (Settings > Extensions > dj-librarian engine),
   **Spotify client ID** and **Spotify client secret**, save. No terminal.

   The keys go there only. Never into the chat. In a clone of the repo (developers) the repo's
   `.env` works too.
4. **One link (1 min).** In `links.yaml` in their dj-library folder, one entry: `spotify:` the
   name of a Spotify playlist they own (their inbox), `crate:` the path of a normal rekordbox
   playlist that already exists (for example `house_base/0_INBOX`).
5. **Proof (1 min).** `dj pull <link>` (MCP: `dj_pull(link)`). One browser tab opens and asks
   for the two read permissions. They click Agree; the tab says done. The pull reports the
   number of tracks. Setup is finished.

If they paste a key into the chat anyway: do not repeat it. Tell them to treat it as leaked,
make a new secret in the app's Settings on the dashboard and put the new one in the engine
settings.

## Spotify limits since February 2026 (C-06)

- One app per DJ: one client ID each. Do not share one app between DJs.
- At most 5 Spotify users per app, each added by the owner in the app's User Management.
- Search returns at most 10 results per query, so a rare track can come back MISSING.
- An app reads only playlists the DJ owns or collaborates on. Another user's playlist or
  Spotify's own playlists answer 403 (sometimes 404): copy the tracks into a playlist of their
  own first.
- No BPM, key, popularity or genres from Spotify. BPM and key come from rekordbox.

The full endpoint audit is `docs/spotify-audit.md` (R-804).

## Permissions (scopes)

- `playlist-read-private` and `playlist-read-collaborative`: the first pull asks for these two.
- `playlist-modify-private`: only for `dj push --apply` and `dj build --apply`. The first real
  write opens one more consent tab.
- `dj analyze` needs three more read scopes. Ask the DJ before running it.

## Where the files go (R-802)

When `links.yaml` in the dj-library folder holds a link, the inbox loop works in that folder:
`plans/`, `wishlist/` and the apply reports in `reports/apply/` next to `links.yaml`; the
pulled inbox, the match memory and the declined list are the engine's, under `.cache/`. While
it holds no link, the repo's `links.yaml` and folders are used, as before. `dj status` names the
one in use as `links_file`.

On the switch nothing is lost: until the first `dj apply --apply` in the library folder, the
repo's declined list and match memory are still read (`dj status`: `state_from_repo`), and
that apply copies them over. Plans list file paths from this computer, so they stay out of git
(`plans/*.plan.json` in the folder's `.gitignore`). The engine extension keeps the login token
on the computer, in `.dj-librarian/.cache/` in the home folder (never in the library folder, which
may sync), so an update does not log the DJ out. In a clone, `.env` and the login token stay in the dj-librarian folder, never in the
dj-library folder.

## Shopping list (R-803)

After `dj plan <link>` (MCP `dj_plan`): `dj wishlist shop <link>` (MCP `dj_wishlist_shop(link)`).

1. It reads the MISSING tracks of the newest plan for that link. No Spotify call. If the
   inbox was pulled after that plan, it says so (`stale_plan: true`): run `dj plan` first.
2. It writes `wishlist/<crate>.shopping.md`: a short summary (count, top labels), then one row
   per track with Beatport and Bandcamp search links, the label when Spotify sends one, and `-`
   for BPM and key.
3. The file is generated and rewritten on every run. The DJ keeps their own notes elsewhere.
4. In a dj-library folder it appends one line to `log.md`.

Tell the DJ the count, the top labels and the file name. The links are searches; nothing was
bought or fetched.

## Push and build with their own app (R-805)

Both work for any DJ whose engine settings (in a clone: `.env`) hold their own app's keys.

- `dj push "<rekordbox playlist path>"` (MCP `dj_push_preview`): matches the playlist on
  Spotify. MATCH, AMBIGUOUS, MISSING.
- `dj build <tracklist.txt>` (MCP `dj_build_preview`): matches every `Artist - Title` line of a
  text tracklist. Lines without ` - ` are listed as skipped.

Both are dry-runs that return a `preview_id`. Show the counts and any AMBIGUOUS links, get the
DJ's yes, then run the same command with `--apply --preview-id <id>` (MCP `dj_push_apply` /
`dj_build_apply` with the preview's `preview_id` and the same `name` and `include_ambiguous`).
That creates one private playlist once and only ever adds to it.

## If something fails

| Message | What it means, what to do |
|---|---|
| `Spotify client ID ... not set` or `Spotify client secret not set` (the engine); `.env not found` or `SPOTIFY_CLIENT_ID is empty` (a clone) | Step 3 is not done: the keys are not in the engine settings (in a clone: `.env`). Redo it, then pull again. |
| Spotify shows "Invalid redirect URI" | The app's redirect URI differs. Set it to `http://127.0.0.1:8888/callback` exactly. |
| `Spotify will not let this app read ... (403)` or `Spotify did not find ... (404)` | 403: the inbox playlist is not theirs. 404: it was deleted, the link is mistyped, or it is not theirs. Fix the link, or copy the tracks into their own playlist; update links.yaml. |
| `No Spotify login within 180s` | The consent tab was not answered. Run the pull again and click Agree. |
| `Spotify login refused: access_denied` | They clicked Cancel. Run it again when they are ready. |

## Rules

- Never ask for, repeat, open or print `.env`, the client secret or anything in `.cache/`.
- The login token goes only to `https://api.spotify.com/v1/...`. The CLI enforces it.
- On Spotify: create private playlists and add tracks. Never remove, reorder or rename.
- Every Spotify write is a preview first, then the DJ's explicit yes, then `--apply --preview-id <id>`.

## Pre-send checklist

Before every reply, check:

- [ ] The first line is the next action or the answer. No preamble, no pleasantries.
- [ ] Where we are is restated in one line (for example "Step 2 of 6").
- [ ] Steps are numbered, with one concrete time estimate.
- [ ] Lists have 5 items or fewer.
- [ ] No tangents: only what this step needs.
- [ ] Finished work is visible: name the file that was written.
- [ ] Errors are stated matter-of-fact: what failed, what happens next.
- [ ] It ends with one action that takes under 2 minutes.
- [ ] Voice: a working DJ talking to a DJ. Blunt, practical, no hype (shared/voice.md).
- [ ] Nothing was written to rekordbox, Spotify or audio files without a preview and an explicit yes.
