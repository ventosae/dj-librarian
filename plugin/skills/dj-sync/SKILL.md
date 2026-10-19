---
name: dj-sync
description: Process a Spotify inbox playlist into a rekordbox crate with the dj CLI — pull, match, plan, get the DJ's OK, apply, log. Also copies a rekordbox playlist to Spotify (dj push). Use whenever the DJ mentions syncing, their inbox, a crate, what's missing, the wishlist or shopping list, ambiguous matches, pushing a playlist to Spotify, or asks about the state of their playlists, even if they never say "sync".
---

# dj-sync

rekordbox is the truth. Spotify playlists are candidates. You only propose.

## How to run things
**In Cowork / Claude Desktop (you cannot run local programs): use the `dj-librarian` MCP tools.**

| Instead of the CLI command | Call this tool |
|---|---|
| `dj status --json` | `dj_status` |
| `dj tree --file X` / `--apply` | `dj_tree_preview(file)` / `dj_tree_apply(file)` |
| `dj pull <link>` | `dj_pull(link)` or `dj_pull(all_links=true)` |
| `dj match <link>` | `dj_match(link)` |
| `dj plan <link>` | `dj_plan(link)`, then edit the plan file yourself |
| `dj apply <plan>` / `--apply` | `dj_apply_preview(plan_file)` / `dj_apply_write(plan_file)` |
| `dj copy A B` / `--apply` | `dj_copy_preview(source, target)` / `dj_copy_apply(source, target)` |
| `dj push P` / `--apply` | `dj_push_preview(playlist)` / `dj_push_apply(playlist)` |

Every tool returns `{ok, exit_code, result | output, stderr}`. File arguments are paths
inside the repo (`bases.yaml`, `plans/....plan.json`). The write tools (`*_apply`,
`*_write`) need the DJ's explicit OK in the conversation first - always show them the
preview, then ask. `exit_code: 2` = rekordbox is open: ask them to close it, call again.
Never hand them a shell command when a tool exists.

## How to run the CLI (Claude Code, or the DJ in a terminal)
Always from the repo root:

    uv run dj <command> --json

If the repo sits in a cloud-synced folder, the venv must live outside it: set
`UV_PROJECT_ENVIRONMENT` (see CONTRIBUTING.md).
Every command takes `--json`. Read that, not the human text.
Exit codes: 0 ok · 1 error · 2 rekordbox is running (writes refused).

## Before anything
1. Read STATE.md, then README.md. CLAUDE.md holds the hard rules.
2. Pick the link: the one the DJ named, else the one STATE.md marks as current.
   A `<link>` is the `spotify` or the `crate` value of an entry in links.yaml.
   No entry yet: ask the DJ for the Spotify playlist and the crate, add it to links.yaml.
   The crate must already exist in rekordbox as a normal playlist. If it does not,
   the DJ creates it in rekordbox (or adds it to tree.yaml and asks for `dj tree --apply`).

## The loop
1. `uv run dj pull <link> --json`
2. `uv run dj match <link> --json`
3. Report in five lines: in crate · proposed · ambiguous · missing · declined.
4. Ambiguous first. For each, show `reasons`, then its `candidates`, one line each:
   title — artist — duration — bitrate — path tail (note `in_crate`). Ask for a pick.
   One question at a time.
5. `uv run dj plan <link> --json`. Open the plan file it names and write the DJ's answers:
   - `decision`: `yes` or `no` (PROPOSE and AMBIGUOUS start as `pending`, never `yes`).
   - AMBIGUOUS + yes also needs `pick`: a `rb_content_id` from that item's `candidates`.
   They say "yes to all" or name exceptions. Re-running `dj plan` the same day keeps the
   decisions already written.
6. `uv run dj apply <plan> --json` is a DRY-RUN. Show `would_add` and the `adds` list.
7. Ask: "is rekordbox closed?" Wait for a yes. Then `uv run dj apply <plan> --apply --json`.
   The CLI checks rekordbox itself and backs up master.db first. Exit code 2 means
   rekordbox is open: tell them, wait, run the same command again. Never work around it.
8. Read the report named in the output. `yes` picks are now in state/match_cache.json,
   `no` decisions in state/declined.json: neither is ever asked again.
9. Update STATE.md: counts, last sync date, next action. Append one line to log.md.

## Copying a rekordbox playlist to Spotify
`uv run dj push "<rekordbox playlist path>" --json` is a dry-run: MATCH · AMBIGUOUS · MISSING.
Show the counts and any AMBIGUOUS links, get their OK, then add `--apply`.
`--include-ambiguous` only if they checked those links. It creates one private playlist per
rekordbox playlist (state/push.json) and only ever adds to it. If they deleted that playlist
on Spotify, the next `--apply` makes a new one.

## Asking about state
`uv run dj status --json`: track count, the playlist tree, and per link the counts by
status, last pull and last apply. It is read-only and works while rekordbox is open.

## If you cannot run the CLI
Give the one exact command. Wait until they say it ran.
Then read the newest file in plans/ or reports/.

## Rules
- Never edit master.db, never call pyrekordbox, never write SQL. Only the dj CLI writes.
- Never remove, rename or delete anything in rekordbox. If the DJ wants that, they do it
  in rekordbox. If they removed a track from a crate, record it as declined
  (plan decision `no`, then apply) so it is not re-proposed.
- Do NOT run `dj tree --apply` on your own. `dj tree` may list CREATE lines for folders
  the DJ deleted on purpose. tree.yaml is a draft; rekordbox is the truth.
- HOLD lines in `dj tree` are smart playlists with an unconfirmed rule encoding. Leave
  them unless the DJ asks; never pass `--allow-uncalibrated` on your own.
- MISSING is a wishlist, not a failure. Point at wishlist/<crate>.md. Keep it short.
- A different version (extended mix, re-edit, remix, remaster) is the DJ's call, never yours.
- Never open, print or commit .env or .cache/.
- If a command errors: show the last 10 lines and stop. Never retry with --apply.

## Log line
YYYY-MM-DD sync <link> -> +N added, N ambiguous resolved, N missing, N declined
YYYY-MM-DD push <rekordbox playlist> -> N on Spotify, N ambiguous, N missing
