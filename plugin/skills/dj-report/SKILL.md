---
name: dj-report
description: Render the DJ's library report - one self-contained HTML file in reports/ with who they are as a DJ (their sleeve, archetype, liner notes and five stats), how their rekordbox tree is built (a crate wall of folders and playlists, overlaps, dumps, duplicates, orphans), two or three named ways to rebuild it, each with a trigger prompt, and one next action. Use at the end of the first run (dj-start step 4 and 5), when the DJ asks for their report, for restructure ideas, "how should I organise my library", or after a new export lands, even if they never say "report".
---

# dj-report

The report is the first long thing the DJ reads: four sections, one HTML file, opens offline.
The code makes every number and the proposals. You make the words: `profile/habits.md` before
the report, and the proposal names in the DJ's own vocabulary. Nothing here touches rekordbox.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-401, R-402, R-403, R-404, R-405, R-406, R-407, R-408, R-409, R-1003, R-1405.

## How the report is made

1. dj-profile, dj-structure, dj-taste and dj-identity have run: `profile/`, `structure/`, `taste/`
   hold the measured facts, `profile/identity.json` the axes and the archetype (R-302).
2. You write `profile/habits.md` (rules and template in `../dj-profile/SKILL.md`) and
   `profile/identity.md`, the liner notes (template in `../dj-identity/SKILL.md`). The report shows
   both in section 1. Missing: the report shows a placeholder line instead, so never block on them.
3. `propose`: the code picks 2 or 3 restructure proposals and writes `structure/proposals.yaml`.
4. `render`: the code writes `reports/<date>-library.html` from the folder's files. A new file
   every time (`-2`, `-3` ... on the same day); an old report is never overwritten. The JSON's
   `report` names the file this run wrote.
5. Optional, after step 4: rename a proposal in `structure/proposals.yaml` in the DJ's words
   (their playlist names, their genre words, see `taste/vocabulary.md`), then render only:
   `scripts/report.py render` or `uv run dj library report --render-only`. Every other run
   (the script without `render`, `dj library report`, `dj library analyze`, `dj_library_analyze`)
   writes the proposals again, and your names survive only in the kept copy.

The sections: 1 who you are (the sleeve, the DJ's handle, the archetype, the liner notes (the
archetype's one-line meaning stands in until they exist), the six axes, the 5 stats that matter,
then the narrative, R-402, R-1405); 2 how it's built (the crate wall: one row per top-level
folder, a bar per playlist in the folder's lane colour, dumps hatched, empty playlists as
outlines, overlaps as arcs; at most 5 reveals, R-403); 3 ways to rebuild it (2-3 cards, each with
a mini sleeve in the same lane colours, showing where that proposal puts each tempo band, and six
parts: name, principle, new tree, where playlists land, cost, trigger, R-404); 4 next (a sticky
footer with one action under 2 minutes, R-406).

The page follows `docs/design.md` (R-408): Booth (dark) by default, Day (light) one tap away in
the header, every chart with a tooltip on each mark and a "table" link to the file it was drawn
from. A sample built from the synthetic library, with its screenshots, lives in `docs/samples/`
(R-409): after any change to the report, `uv run python scripts/make_samples.py` builds it again.

## How to run

Paths are relative to this skill's folder. Each run prints one JSON object (counts first).
Scripts run with `python3` (`python` on Windows, `uv run python` inside a clone of the repo).

1. Both steps, as dj-start step 4 runs it: `python3 scripts/report.py --library <folder>`.
2. One step: `python3 scripts/report.py propose --library <folder>` or
   `python3 scripts/report.py render --library <folder>`. `--today YYYY-MM-DD` fixes the date.
3. Engine (Claude Code or a terminal at the repo root): `uv run dj library report --json`
   (`--render-only` after a rename), or the whole chain from one read of the library:
   `uv run dj library analyze [--source xml|db] --json` (MCP: `dj_library_analyze`).
   `--source db` reads a snapshot of master.db, so My Tags count.

Exit 0 = done; 1 = error: read `error` and tell the DJ in one line what failed and what happens
next; 2 = refused: the folder has no valid `library.yaml`, run dj-start on it first (MCP: the
`hint` says so; it is not rekordbox, so a retry does not help). A broken
`structure/proposals.yaml` after your edit is exit 1 naming the proposal and the part (2 or 3
proposals, each name used once): fix that part and run `render` again. About a minute in all.

## How the families are picked (R-405)

Three families. Each gets a score from 0 to 100 from what the DJ already does:

1. **Bases** (one base per main genre, each with `0_INBOX`, `1_CRATES`, `2_SETS`): wins when the
   DJ fills the genre field and already names folders and playlists after genres.
2. **Facets** (5 to 8 shallow genre shelves, gig crates beside them; My Tags Role, Body, Vibe and
   Status sort inside them later): wins when there are many genres, playlists that overlap or
   sit inside each other, and dumps.
3. **Gig-first** (a crate per residency or event, everything else in an archive): wins when
   playlist names are dated or venue-like, or hold "gig", "set", "night" or "@".

Facets scores 0 when fewer than 5 genres hold 2 tracks or more. Every family that scores above 0
is proposed, best first, 3 at most; at least 2 always are. The first one is the recommendation.
The exact points are in the docstring of `src/dj/analysis/proposals.py`; quote it when the DJ
asks "why this one?".

Every proposal is built as a copy beside the DJ's tree: a top-level name the DJ already has gets
" (new)" (for example `gigs (new)` next to their `Gigs`), so the build creates every folder and
playlist the report shows and the cost counts exactly those.

## Renaming a proposal

- Change `name` and `trigger` together: the trigger is exactly `Build me the <name> structure`.
  `slug` stays as it is: it is the proposal's id. Each name is used once.
- Then render only (`scripts/report.py render`), never the default run: see step 5 above.
- Use the DJ's words only: a playlist name, a genre word or a word from `taste/vocabulary.md`.
  Never invent a number; `cost_minutes` and `lands` come from the code.
- Keep the YAML valid and every `from` path as written: those are the real rekordbox paths.
- The next `propose` run writes the file again; your edited copy is kept first as
  `structure/proposals.edited-<date>.yaml`. Name that file in your reply when the JSON lists it
  under `kept`.

## Delivering it (breadboard P5 and P6)

1. Send the file the last run's JSON names under `report` as a file card with one line, as
   dj-start step 5 shows: `reports/<date>-library.html`, or `-2`, `-3` ... after a second run
   that day. Never guess the name. No file card: the same line; the DJ opens the file from the
   folder.
2. In the same reply, step 6: one action under 2 minutes. Chips: one per proposal, each its
   trigger exactly as the report shows it, plus `not yet`.
3. A step that failed before the report: name it in one line before the last line.

```text
Step 5 of 6 · about 5 minutes to read. Your report: <report>
Step 6 of 6 · under 2 minutes. Pick one below: I show you the new tree before anything gets written.
```

## Checking the report (R-407, R-1003)

The report's words follow both checklists. The code keeps the mechanical part of its own text:
the first line of every section is its point, every list has 5 items or fewer, every library
name is escaped, and the page loads nothing from outside. The code does not check your words:
`profile/habits.md` and a renamed proposal go on the page as you wrote them. Your part:

- `profile/habits.md` passes the pre-send checklist below: no preamble, numbers only from the
  files, the DJ's own words, no word from the Avoid column of voice.md.
- A renamed proposal is a booth word or the DJ's word, never hype and never a word from the
  Avoid column of voice.md.
- Your reply around the report passes the pre-send checklist below.

## What this skill never does

- It never writes to rekordbox, Spotify or audio files. A proposal is built later, as a copy,
  by dj-build, after a preview and the DJ's yes.
- It never puts an absolute path into the report or `structure/proposals.yaml`.
- It never moves, renames or deletes a playlist: `lands` says where a copy of each one goes.

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
