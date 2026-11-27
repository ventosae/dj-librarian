# Spotify setup

One time per DJ, about 8 minutes. Run it only when the DJ asks for Spotify or a Spotify step needs it. Every DJ uses their own Spotify app: their keys, their account.

## The setup card

Show the DJ one step at a time. Wait for "done" before the next one.

1. **Premium (1 min).** The owner of a Spotify developer app needs Spotify Premium (since February 2026). Every DJ uses their own app, so the DJ needs Premium themselves.
2. **Your own app (3 min).** Open developer.spotify.com/dashboard, log in, Create app. Name and description: anything. Redirect URI, exactly: `http://127.0.0.1:8888/callback` (`127.0.0.1`, not `localhost`). Tick **Web API**. Save, then open the app's Settings: the Client ID is shown, the Client Secret sits behind "View client secret".
3. **Two keys where the engine reads them (2 min).** A text file named `.env` in the engine folder (`dj-librarian` in the home folder; never the dj-library folder, which may sync), with two lines, `SPOTIFY_CLIENT_ID=` and `SPOTIFY_CLIENT_SECRET=`, each followed by its key. `examples/.env.example` in the engine folder shows the shape. The keys go there only. Never into the chat.
4. **One link (1 min).** In `links.yaml` in their dj-library folder, one entry: `spotify:` the name of a Spotify playlist they own (their inbox), `crate:` the path of a normal rekordbox playlist that already exists (for example `house_base/0_INBOX`).
5. **Proof (1 min).** `dj_pull(link)`. One browser tab opens and asks for the two read permissions. They click Agree; the tab says done. The pull reports the number of tracks. Setup is finished.

They paste a key into the chat anyway: do not repeat it. Tell them to treat it as leaked, make a new secret in the app's Settings on the dashboard and put the new one in `.env`.

## Spotify's limits since February 2026

- One app per DJ: one client ID each. Never share one app between DJs.
- At most 5 Spotify users per app, each added by the owner in the app's User Management.
- Search returns at most 10 results per query, so a rare track can come back MISSING.
- An app reads only playlists the DJ owns or collaborates on. Another user's playlist or Spotify's own playlists answer 403 (sometimes 404): copy the tracks into a playlist of their own first.
- No BPM, key, popularity or genres from Spotify. BPM and key come from rekordbox.

## Permissions

- `playlist-read-private` and `playlist-read-collaborative`: the first pull asks for these two.
- `playlist-modify-private`: only for `dj_push_apply` and `dj_build_apply`. The first real write opens one more consent tab.

## Where the files go

`plans/`, `wishlist/` and the reports of each write (`reports/apply/`) sit in the dj-library folder, next to `links.yaml`. The pulled inbox, the match memory and the declined list are the engine's, under `.cache/` in that folder: read the report, not those. Plans list file paths from this computer, so the folder's `.gitignore` keeps `plans/*.plan.json` out of git. The login token stays in the engine folder, never in the dj-library folder, and goes only to Spotify's own API.

## If something fails

| Message | What it means, what to do |
|---|---|
| `.env not found`, `SPOTIFY_CLIENT_ID is empty`, or a key "not set" | Step 3 is not done: the keys are not in `.env` in the engine folder. Redo it, then pull again. |
| Spotify shows "Invalid redirect URI" | The app's redirect URI differs. Set it to `http://127.0.0.1:8888/callback` exactly. |
| `Spotify will not let this app read ... (403)` or `Spotify did not find ... (404)` | 403: the inbox playlist is not theirs. 404: it was deleted, the link is mistyped, or it is not theirs. Fix the link, or copy the tracks into their own playlist; update `links.yaml`. |
| `No Spotify login within 180s` | The consent tab was not answered. Pull again and click Agree. |
| `Spotify login refused: access_denied` | They clicked Cancel. Pull again when they are ready. |
