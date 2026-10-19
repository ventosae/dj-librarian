---
name: dj-tidy
description: Audit and tidy the DJ's music files with dj tidy - empty or odd tags, missing artwork, file-name convention, CDJ playability per equipment profile, half/double BPM, duplicates; then plan tag fixes parsed from the file names, get the DJ's OK, apply, undo. Use whenever the DJ mentions tags, metadata, artwork or covers, duplicates, renaming files, "will this play on the CDJ", library hygiene, cleaning the library, Reload Tag or Relocate, even if they never say "tidy".
---

# dj-tidy

The audio files are the durable store; rekordbox reads them. You only propose. Nothing here
touches master.db: `dj tidy` reads it read-only and writes to file tags only after the DJ's OK.

## How to run things
**In Cowork / Claude Desktop: use the `dj-librarian` MCP tools.**

| Instead of the CLI command | Call this tool |
|---|---|
| `dj tidy audit <crate>` / `--all` / `--folder D` | `dj_tidy_audit(crate=...)` / `(all_tracks=true)` / `(folder=...)` |
| `dj tidy dupes ...` | `dj_tidy_dupes(...)` |
| `dj tidy plan ... [--rename] [--rename-imported]` | `dj_tidy_plan(...)`, then edit the plan file yourself |
| `dj tidy apply <plan>` / `--apply` | `dj_tidy_apply_preview(plan_file)` / `dj_tidy_apply(plan_file)` |
| `dj tidy undo <plan> --apply` | `dj_tidy_undo(plan_file)` |

A target is exactly one of: a crate path (`house_base/0_INBOX`), `all_tracks`, or a folder
inside the `roots:` of `tidy.yaml`. `dj_tidy_audit` returns the counts
(`brief`); read the `.md` report it names for the details. Every tool returns
`{ok, exit_code, result | output, stderr}`. `exit_code: 2` = rekordbox is open: ask them to
close it, call again. Never hand them a shell command when a tool exists.

CLI (Claude Code or the DJ): from the repo root, `uv run dj tidy <cmd> --json`
(venv outside any cloud-synced folder via `UV_PROJECT_ENVIRONMENT`, see CONTRIBUTING.md).
Exit codes 0 / 1 / 2 as above.

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
5. `dj_tidy_apply_preview(plan)`: show what would be written and what cannot run and why.
6. Ask: "is rekordbox closed?" Wait for a yes. Then `dj_tidy_apply(plan)`. Exit code 2 means
   rekordbox is open: tell them, wait, call again. Never work around it.
7. Tell them: in rekordbox select those tracks -> right-click -> **Reload Tag**. If the apply
   renamed imported files, point at the Relocate checklist in `reports/` and say each track
   shows `!` until relocated (cues and playlists survive).
8. Run the audit again to confirm the findings cleared. Update STATE.md (hygiene line, latest
   report path) and append one line to log.md.

## Undo
`dj tidy undo <plan>` is a dry-run; `dj_tidy_undo(plan)` restores tags and names from
`state/tidy/<plan>.undo.json`, newest first, and refuses a file that changed since. Never pass
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
YYYY-MM-DD tidy <target> -> N files tagged, N art embedded, N renamed, N failed; undo state/tidy/<plan>.undo.json
YYYY-MM-DD tidy audit <target> -> N files, N errors, N warnings, N dupe groups; reports/tidy/<file>.md
