# lessons.md — what the build has learned

Operating knowledge that is not a rule. Rules live in `CLAUDE.md`. Add a dated line when something surprises you. No personal data.

## rekordbox / pyrekordbox

- 2026-09-20 `dj tree --apply` wrote 15 nodes to rekordbox 7.2.18 in one commit; rekordbox opened them; `genre_contains` / `comment_contains` smart playlists filled correctly.
- Smart-rule encodings for `bpm_range`, `rating_min`, `added_last_days` are unconfirmed. Nodes using them plan as `HOLD` and are not created without `--allow-uncalibrated`. The one GUI-made sample seen: a My Tag rule `PropertyName="myTag" Operator="8" ValueLeft="<tag id>"`, `AutomaticUpdate="0"`.
- pyrekordbox `commit()` rewrites `masterPlaylists6.xml` and re-syncs existing NODE `Timestamp`s to the DB's `updated_at`. Expected, harmless, covered by the backup.
- After `rollback()` pyrekordbox leaves its in-memory `masterPlaylists6.xml` dirty: discard the db object.
- `add_to_playlist` with `seq=None` appends and touches no sibling row; any `seq` re-sequences siblings.
- rekordbox soft-deletes rows (`rb_local_deleted`); pyrekordbox does not filter them.
- DB `BPM` is ×100 (120 BPM = 12000). `BPM_SCALE_UNEXPECTED` surfaces a wrong guess.
- pyrekordbox 0.4.x is tested to rekordbox 7.0.9; 0.5 renames `db6` → `masterdb`. Pinned `<0.5`.
- 2026-09-20 A `dj tree` dry-run can list CREATE lines for folders the DJ deleted in rekordbox on purpose. `tree.yaml` is a draft; never re-apply just because the dry-run shows CREATE.
- The rekordbox process check calls `tasklist.exe` by absolute path (`%SystemRoot%\System32`), never from PATH.
- Proven only by hand, not by tests: a real `add_to_playlist` commit (`dj apply --apply`, `dj copy --apply`) on a live master.db.
- The `.env` secret and the Spotify refresh-token cache are gitignored but, if the repo sits in a cloud-synced folder, they sync to that cloud. Keep the venv and ideally the repo out of synced folders.
- 2026-10-20 master.db stores smart-playlist rules (`DjmdPlaylist.SmartList`), not their tracks: pyrekordbox 0.4.4 `get_playlist_contents` evaluates `SmartList.filter_clause()` for a smart list instead of reading `DjmdSongPlaylist`. `dj.readers.db` keeps the rules raw and gives smart nodes no `track_ids`, so on a db Library a track only a smart playlist reaches counts as an orphan (`DB_NOTES`). Evaluating the rules through pyrekordbox would be approximate (wall clock for "in the last", unconfirmed rating/BPM encodings, unsupported properties dropped with a warning) and is a read path CLAUDE.md does not list.
- 2026-10-20 A read snapshot must be consistent: `dj.readers.db.snapshot` compares size and mtime of master.db and `-wal` before and after copying and copies again (3 tries) when rekordbox wrote meanwhile. `-shm` is not compared: SQLite rebuilds the WAL index when the first connection opens the copy.
- 2026-10-20 A DjmdSongMyTag link can be alive while its DjmdMyTag is soft-deleted; check both (`link.MyTag.rb_local_deleted`).

## rekordbox XML export

- 2026-10-20 Field coverage of `dj.readers.xml`, checked against the pyrekordbox 0.4.4 XML schema (`rbxml.Track.ATTRIBS`, `Node` Type 0/1, KeyType 0/1), not yet against a real rekordbox 7.2 export. Carried: `id` (TrackID), `artist`, `title` (Name), `album`, `duration_s` (TotalTime), `bitrate`, `location` (file://localhost URL), `kind`, `sample_rate`, `file_size` (Size), `bpm` (AverageBpm, real BPM), `key` (Tonality), `genre`, `label`, `remixer`, `year`, `rating` (0/51/102/153/204/255), `colour` (RGB hex), `comment`, `date_added`, `play_count`, `cue_count` (POSITION_MARK children), and the playlist tree with track order. Not carried: `my_tags`, `isrc`, `bit_depth`, `has_artwork`, play history (only PlayCount and a LastPlayed date per track), smart-playlist rules (no node type for them). Those need master.db (Door 2).
- The XML `Colour` hex → colour name map (0xFF007F Pink … 0x660099 Purple) comes from community docs of the format; unverified. If the DJ renamed colours in rekordbox, master.db shows the new names and the two readers disagree on `colour`.
- Unverified: whether rekordbox can copy My Tags into the comment field on export; if it does, they arrive in `comment`, not `my_tags`.
- `pyrekordbox.rbxml.decode_path` drops the leading `/` of macOS paths (`file://localhost/Users/...` → `Users/...`) and turns them into backslash paths on Windows; `dj.readers.common.posix_location` keeps `/Users/...`, `//nas/share/...` and `D:/...` as POSIX strings on every OS.
- 2026-10-20 `pyrekordbox.rbxml.encode_path` writes `\\host\share\a.mp3` as `file://localhost///host/share/a.mp3` and `/Users/x/a.mp3` as `file://localhost//Users/x/a.mp3` (one slash too many). `posix_location` reads three or more slashes as a share, and exactly two as a share unless the first folder is `Users` or `Volumes` (macOS). `location_url` writes shares with three slashes. How rekordbox itself writes a network share in its export is not yet checked.

## Audio files (`dj tidy`)

- Tags are written as ID3v2.3 (rekordbox, CDJs and Windows Explorer all read it). rekordbox's own writes are v2.4; the audit flags them as info only.
- Undo restored every frame and the original ID3 version on test copies; bytes differ only when a tag already existed (the tag is rewritten). A 24-bit WAV came back byte-identical.
- M4A is read-only. Renaming a file rekordbox already knows requires Relocate in rekordbox afterwards; after any tag write the user must Reload Tag.
- Equipment profile values marked `verify` in `tidy.yaml` are unconfirmed against spec sheets.
- 2026-10-03 Reload Tag after a `dj tidy` write is not yet confirmed on rekordbox 7.2.x. Apply to one imported file first and check it in rekordbox.

## Spotify Web API

- The app receives no artist genres and no track popularity; `/artists?ids=` answers 403; editorial (Spotify-owned) playlists are refused with 403. Genre judgments must come from artists and labels.
- Feb 2026 dev-mode rules: app owner needs Premium; 1 client ID, 5 users per app; search `limit` max 10; `/playlists/{id}/tracks` → `/items`; batch fetches and other-user endpoints removed. Audit `spotify.py` before relying on it for other users.
- Scopes: two read scopes; `playlist-modify-private` only for `push --apply` / `build --apply`.
- `dj analyze` (library census) needs three further read scopes. Ask before adding any scope.
- 2026-09-20 The bearer token goes only to `https://api.spotify.com/v1/...`; a `next` link to any other host is refused. Error messages never contain the token or the secret, and tracebacks never show locals (`pretty_exceptions_show_locals=False`).
- The browser OAuth login is proven by hand only; tests cover everything after the token.

## Matching (Spotify ↔ local, text ↔ Spotify)

- A line with no version word can match a remix, a cover, an orchestral version or a "(Mixed)" DJ-mix cut. Fix: add the version in brackets, or swap the track. ~20 such swaps in one month of use.
- EP and album titles never match; pick a track from the EP.
- Spotify's own spellings win ("Musik", "Milles Away").
- Empty Artist tags on local files block matching. Fix the tags (`dj tidy`) before syncing.
- Two Spotify links on one crate share one inbox file: pull + match one link at a time, or key the inbox by link.
- `match.decide(..., ignore_duration=True)` is only for text lines that carry no length (`dj build`). `dj push` and the intake keep the duration check.

## Operating with Claude

- Tool results for ~45-line previews exceed the tool-result limit; Claude ends up parsing saved JSON by hand. Return counts first and paginate items.
- A bare filename rejected with "does not exist" was misread as a connection drop. Resolve bare names under their folder and show an example in the tool description.
- Eight parallel research subagents hit a monthly spend limit mid-task. Bound fan-out.
- A 1.56M-token chat was compacted; `STATE.md` + `log.md` carried a clean resume. File-based state works. The tool, not Claude, should write the log lines.
- The real write gate was the per-tool "ask every time" permission, not the skill text. "Yes" was often implicit ("It's on", "Create playlists"). Gates belong in tools and hooks.

## Environment (uv, Windows)

- To add a package while the venv's `dj-mcp` binary is locked: `uv add --no-sync X`, then `uv pip install --python <venv>/Scripts/python.exe --link-mode=copy X`. Hardlinks from the uv cache into a venv on another volume fail with "os error 396".
- MCP clients start servers with a stripped environment; `mcp_server.py` restores the variables pyrekordbox needs to find rekordbox.
