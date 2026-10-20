---
name: dj-sync
description: Process a Spotify inbox playlist into a rekordbox crate with the dj CLI — pull, match, plan, get the DJ's OK, apply, log. Also copies a rekordbox playlist to Spotify (dj push). Use whenever the DJ mentions syncing, their Spotify inbox, the inbox crate (a Spotify playlist synced into a crate), what's missing, the wishlist or shopping list, ambiguous matches, pushing a playlist to Spotify, or asks about the state of their playlists, even if they never say "sync". A crate for a night or a gig ("crate me 50 for Saturday") is dj-crate, not this skill.
---

# dj-sync

rekordbox is the truth. Spotify playlists are candidates. You only propose.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-802, R-803, R-904, R-1101, R-1102, R-205, NFR-03, NFR-05, C-02.

## How to run things
**In Cowork / Claude Desktop (you cannot run local programs): use the `dj-librarian` MCP tools.**

| Instead of the CLI command | Call this tool |
|---|---|
| `dj status --json` | `dj_status` |
| `dj tree --file X` / `--apply` | `dj_tree_preview(file)` / `dj_tree_apply(preview_id, file, power_mode=true)` |
| `dj pull <link>` | `dj_pull(link)` or `dj_pull(all_links=true)` |
| `dj match <link>` | `dj_match(link)` |
| `dj plan <link>` | `dj_plan(link)`, then edit the plan file yourself |
| `dj apply <plan>` / `--apply` | `dj_apply_preview(plan_file)` / `dj_apply_write(plan_file, preview_id, power_mode=true)` |
| `dj copy A B` / `--apply` | `dj_copy_preview(source, target)` / `dj_copy_apply(source, target, preview_id, power_mode=true)` |
| `dj push P` / `--apply` | `dj_push_preview(playlist)` / `dj_push_apply(playlist, preview_id)` |

Every tool returns `{ok, exit_code, result | output, stderr}`. File arguments are paths
inside the repo (`bases.yaml`, `plans/....plan.json`); plans and tracklists may also sit in
the dj-library folder. A bare name is looked up in its folder
(`2026-10-20-house.plan.json` -> `plans/`, `set.txt` -> `tracklists/`).
Results put the counts first. A long list comes in pages: `paging` says per list `page`, `pages`
and `total`; call the same preview or read tool with the same arguments and `page=2` for more.
Pages 2+ are cut from page 1's run (kept 10 minutes, `run_at`): Spotify is not searched again and
the `preview_id` is the same on every page. Check it: a different `preview_id` means the plan
changed; show the DJ the new preview from page 1 before any write. A write tool returns the first
page only; `paging.<list>.rest_in` names the report with the rest.

The write gate (R-1102): every preview returns a `preview_id`. Show the DJ the preview, ask,
and only after their explicit yes call the write tool with that `preview_id` and the same
arguments (`dj_push_preview` and `dj_push_apply` take the same `name` and `include_ambiguous`).
The write refuses without the id, with another command's id, after anything changed since the
preview, or with an id already used: preview again and show the new result. Never invent an id.
Writes into master.db (`dj_tree_apply`, `dj_apply_write`, `dj_copy_apply`) are Windows power mode
(R-205): they also need `power_mode=true` and refuse on a Mac. Pass it only on Windows, after the
DJ said yes to a direct write; otherwise the XML they import is the way (dj-build).
`exit_code: 2` = rekordbox is open: ask them to close it, call again with the same `preview_id`.
Never hand them a shell command when a tool exists.

## How to run the CLI (Claude Code, or the DJ in a terminal)
Always from the repo root:

    uv run dj <command> --json

If the repo sits in a cloud-synced folder, the venv must live outside it: set
`UV_PROJECT_ENVIRONMENT` (see CONTRIBUTING.md).
Every command takes `--json`. Read that, not the human text.
Exit codes: 0 ok · 1 error or `REFUSED` (no valid preview id, no `--power-mode`) · 2 rekordbox is
running (writes refused). A dry-run prints `Preview id: <id>` (`preview_id` in `--json`); the write
is the same command with `--apply --preview-id <id>`, plus `--power-mode` for master.db.

## Before anything
1. Read STATE.md, then README.md. CLAUDE.md holds the hard rules.
2. Pick the link: the one the DJ named, else the one STATE.md marks as current.
   A `<link>` is the `spotify` or the `crate` value of an entry in links.yaml.
   links.yaml lives in the DJ's dj-library folder; while that file holds no link, the repo's
   links.yaml is used as before (`dj status` names the one in use as `links_file`). With the
   library's links.yaml, plans/, wishlist/ and the apply reports (reports/apply/) sit in that
   folder; the match memory and declined list are under its .cache/ (read the report, not
   those). Spotify setup for a new DJ: the dj-spotify skill.
   No entry yet: ask the DJ for the Spotify playlist and the crate, add it to links.yaml.
   The crate must already exist in rekordbox as a normal playlist. If it does not,
   the DJ creates it in rekordbox (or adds it to tree.yaml and asks for `dj tree`: the preview,
   then, on Windows after their yes, `--apply --power-mode --preview-id <id>`).

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
6. `uv run dj apply <plan> --json` is a DRY-RUN. Show `would_add` and the `adds` list; keep
   its `preview_id`.
7. Ask: "add these to the crate? is rekordbox closed?" Wait for a yes. Then
   `uv run dj apply <plan> --apply --power-mode --preview-id <preview_id> --json` (Windows only).
   The CLI checks rekordbox itself and backs up master.db first. Exit code 2 means
   rekordbox is open: tell them, wait, run the same command again. Never work around it.
8. Read the report named in the output. `yes` picks are now in state/match_cache.json,
   `no` decisions in state/declined.json: neither is ever asked again.
9. Update STATE.md: counts, last sync date, next action. The tool already appended the log.md
   line (`log` in the result); never write log.md yourself.

## Copying a rekordbox playlist to Spotify
`uv run dj push "<rekordbox playlist path>" --json` is a dry-run: MATCH · AMBIGUOUS · MISSING,
and a `preview_id`. Show the counts and any AMBIGUOUS links, get their OK, then run the same
command with `--apply --preview-id <preview_id>`.
`--include-ambiguous` only if they checked those links (in the dry-run too: the id covers it). It creates one private playlist per
rekordbox playlist (state/push.json) and only ever adds to it. If they deleted that playlist
on Spotify, a new dry-run gives a new `preview_id`, and its `--apply` makes a new one.

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
The tool writes log.md, never you (R-904). `dj plan`, and `dj apply`, `dj copy`, `dj push`,
`dj build` and `dj tree` with `--apply`, each append one line when they wrote something; a dry-run
or a refusal adds none. The line comes back as `log` in the result (`log.md: ...` in the text).
A push or build stopped by an error after the Spotify playlist existed still logs what it did
(`, stopped by an error`), named on stderr.
To report what happened, read log.md: in the dj-library folder once it is set up, else at the top
of the repo. `log: null` with `WARNING log.md line not written` in stderr: the write is done;
tell the DJ in one line what held log.md. Lines look like:

    YYYY-MM-DD HH:MM plan <crate> -> N in crate, N proposed, N ambiguous, N missing, N declined; plans/<file>
    YYYY-MM-DD HH:MM apply <crate> -> N added, N no, N pending; reports/<file>
    YYYY-MM-DD HH:MM push <rekordbox playlist> to Spotify -> N added, N already there, N missing; reports/<file>

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
