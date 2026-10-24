---
name: dj-tidy
description: Audit and tidy the DJ's music files with dj tidy - empty or odd tags, missing artwork, file-name convention, CDJ playability per equipment profile, half/double BPM, duplicates; then plan tag fixes parsed from the file names, get the DJ's OK, apply, undo. Use whenever the DJ mentions tags, metadata, artwork or covers, duplicates, renaming files, "will this play on the CDJ", library hygiene, cleaning the library, Reload Tag or Relocate, even if they never say "tidy".
---

# dj-tidy

The audio files are the durable store; rekordbox reads them. You only propose. Nothing here
touches master.db: `dj tidy` reads it read-only and writes to file tags only after the DJ's OK.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-904, R-1102, R-1104, R-1303, NFR-03, NFR-05, C-01.

## How to run things
**In Cowork / Claude Desktop: use the `dj-librarian` MCP tools.**

| Instead of the CLI command | Call this tool |
|---|---|
| `dj tidy audit <crate>` / `--all` / `--folder D` | `dj_tidy_audit(crate=...)` / `(all_tracks=true)` / `(folder=...)` |
| `dj tidy dupes ...` | `dj_tidy_dupes(...)` |
| `dj tidy plan ... [--rename] [--rename-imported]` | `dj_tidy_plan(...)`, then edit the plan file yourself |
| `dj tidy apply <plan>` / `--apply` | `dj_tidy_apply_preview(plan_file)` / `dj_tidy_apply(plan_file, preview_id)` |
| `dj tidy undo <plan>` / `--apply` | `dj_tidy_undo_preview(plan_file)` / `dj_tidy_undo(plan_file, preview_id)` |

A target is exactly one of: a crate path (`house_base/0_INBOX`), `all_tracks`, or a folder
inside the `roots:` of `tidy.yaml`. `dj_tidy_audit` returns the counts
(`brief`); read the `.md` report it names for the details. Every tool returns
`{ok, exit_code, result | output, stderr}`, counts first. A long list comes in pages: `paging`
says per list `page`, `pages` and `total`; call the same tool with the same arguments and `page=2`
for more. Pages 2+ are cut from page 1's run (kept 10 minutes, `run_at`): no second scan, no
second log line, and a preview's `preview_id` is the same on every page. A different `preview_id`
means the plan changed: show the DJ the new preview before any write.
`dj_tidy_plan`, `dj_tidy_apply` and `dj_tidy_undo` write, so they return the first page only and
`paging.items.rest_in` names the file with the rest (the plan, the report, the undo record). The plan
tools' `plan_file` may be a bare name: it is looked up in `plans/`
(`2026-10-20-tidy-all.plan.json`). `exit_code: 2` = rekordbox is open: ask them to
close it, call again. Never hand them a shell command when a tool exists.

The write gate (R-1102): `dj_tidy_apply_preview` and `dj_tidy_undo_preview` return a
`preview_id`. The write tool needs that id and refuses without it, after any change since the
preview (a file, a decision), or with an id already used: preview again. Never invent an id.

CLI (a clone of the repo, Claude Code): from the repo root, `uv run dj tidy <cmd> --json`
(venv outside any cloud-synced folder via `UV_PROJECT_ENVIRONMENT`, see CONTRIBUTING.md).
Exit codes 0 / 1 / 2 as above; 1 with `REFUSED` = no valid preview id. The write is the dry-run's
command with `--apply --preview-id <id>`.

## The loop
1. **Audit first, always.** `dj_tidy_audit(...)`. Report in one short block: files · clean ·
   errors · warnings · duplicate groups, then the top rule codes with counts. Read the `.md`
   when they ask about a specific file. The audit changes nothing and works while rekordbox is open.
2. Explain what matters in their words: errors = will not play on the chosen CDJ profile;
   `TAG_ARTIST_MISSING` = blank Artist column; `ART_MISSING` = no cover; `BPM_HALF_DOUBLE` = fix
   the grid in rekordbox (tag BPM is ignored); `NOT_IN_REKORDBOX` = file they never imported.
3. **Plan.** `dj_tidy_plan(...)` (no `rename` unless they asked for renames; `rename_imported`
   ONLY when they say in so many words that they want files rekordbox knows renamed and will
   Relocate them). Show the proposals as a table: file · field · old -> new · why. Proposals
   only ever fill EMPTY tags, from the file name. `SKIP_SWAP_SUSPECTED` and
   `SKIP_LOW_CONFIDENCE` items are theirs to fill by hand (Mp3tag or rekordbox).
4. They decide: "yes to all", or exceptions. Write `decision: yes|no` into the plan file.
   Re-running the plan the same day keeps decisions for unchanged proposals.
5. `dj_tidy_apply_preview(plan)`: show what would be written and what cannot run and why; keep
   its `preview_id`.
6. Ask: "write these tags? is rekordbox closed?" Wait for a yes. Then
   `dj_tidy_apply(plan, preview_id)`. Exit code 2 means rekordbox is open: tell them, wait, call
   again with the same id. Never work around it.
7. Tell them: in rekordbox select those tracks -> right-click -> **Reload Tag**. If the apply
   renamed imported files, point at the Relocate checklist in `reports/` and say each track
   shows `!` until relocated (cues and playlists survive).
8. Run the audit again to confirm the findings cleared, and name its report file to the DJ. The
   tool already appended the log.md line (`log` in the result); never write log.md yourself.

## Undo
`dj_tidy_undo_preview(plan)` is the dry-run: what would be restored, and a `preview_id`. After the
DJ's yes, `dj_tidy_undo(plan, preview_id)` restores tags and names from
the undo record in the engine's state (`.cache/engine/state/tidy/<plan>.undo.json` in the
dj-library folder; `state/tidy/` in a clone), newest first, and refuses a file that changed since. Never pass
`--force` on your own. Then Reload Tag again.

## Rules
- Never delete, move or rename a file on your own. Duplicates are a report with a suggested
  keeper; the DJ deletes in rekordbox (or moves the loser themselves).
- Never write BPM, key or genre tags; never touch rekordbox-only fields. Never edit master.db.
- Before the FIRST real apply ever, and before the first WAV or AIFF apply: rehearse on copies
  in a scratch folder inside one of the `roots:` (plan, apply, import the copy into rekordbox, undo).
- A low-confidence parse, a suspected `Title - Artist` swap, an edit/rework whose name looks
  like the original: the DJ's call, never yours.
- If a command errors: show the last 10 lines and stop. Never retry with `--apply`.
- Never open, print or commit .env or .cache/.

## Log line
The tool writes log.md, never you (R-904). `dj_tidy_audit` (it writes its reports),
`dj_tidy_plan`, `dj_tidy_apply` and `dj_tidy_undo` each append one line when they wrote
something; a dry-run or a refusal adds none. The line comes back as `log` in the result. An apply
or undo stopped by an error after it began writing still logs what it did (`, stopped by an
error`), named on stderr. To report what happened, read log.md: in the dj-library folder once it
is set up, else at the top of the repo. `log: null` with `WARNING log.md line not written` in
stderr: the write is done; tell the DJ in one line what held log.md. Lines look like:

    YYYY-MM-DD HH:MM tidy audit <target> -> N files, N errors, N warnings, N dupe groups; reports/tidy/<file>.audit.md
    YYYY-MM-DD HH:MM tidy plan <target> -> N files, N with proposals, N renames; plans/<plan>.plan.json
    YYYY-MM-DD HH:MM tidy apply <target> -> N written, N failed, N cannot run; state/tidy/<plan>.undo.json
    YYYY-MM-DD HH:MM tidy undo <target> -> N restored, N failed, N skipped; state/tidy/<plan>.undo.json

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
