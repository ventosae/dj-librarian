---
name: dj-profile
description: Measure the DJ's rekordbox library from the collection XML in their dj-library folder - size, formats and bitrates, eras, the date-added timeline, which fields they fill, empty fields, duplicate candidates - into profile/stats.md and profile/facts.json, then write profile/habits.md, one page on who they are as a DJ in their own words. Use when the DJ asks what their library says about them, for library stats, formats or bitrates, low-bitrate files, duplicates, empty tags or fields, when they dig, or when dj-start runs the analysis.
---

# dj-profile

The numbers come from code. The words come from you. You read what the code measured, then
write one page about the DJ in their own vocabulary. Nothing here writes to rekordbox, Spotify
or audio files.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-301, R-302, R-311, R-312, R-341.

## Patterns I read first

Before you suggest anything (R-301), read these five patterns in `profile/stats.md`:

1. **Formats and bitrates**: what the DJ buys and rips, and how much sits under 256 kbps.
2. **Eras**: which decades the collection leans on, and how many tracks have no year.
3. **The date-added timeline**: first and last add, the busiest year and month, the last 365 days.
4. **Fields used**: which of genre, BPM, key, rating, colour, comment, label and My Tags they fill.
5. **Duplicates**: the same artist and title more than once (remixes and edits stay apart).

Nothing is suggested before these five are read. Each one is a habit the DJ already has: start
from it, never from a generic idea of a tidy library.

## How to run

Step 1 of 2, about a minute.

1. Door 1, no engine (Cowork): from this skill's folder run
   `python3 scripts/profile.py --library <dj-library folder>` (`python` on Windows). Options: `--xml FILE` reads one
   export instead of the latest in `exports/`; `--today YYYY-MM-DD` fixes the date in the files.
2. Engine (Claude Code, or the DJ in a terminal at the repo root):
   `uv run dj library profile --json`. `--library DIR` defaults to the configured folder;
   `--xml` and `--today` work as above.

Both print one JSON object: `written` (`profile/stats.md`, `profile/facts.json`), `headline` (the
5 stats that matter) and `source` (the export that was read). The run adds one line to `log.md`.
Exit 1 means it stopped: read `error`, tell the DJ in one line what failed and the fix (usually
"no export in exports/ yet: drop the collection XML in the folder"). The script exits 2 when it
refused and wrote nothing (read `refused`; the CLI prints `ERROR` and exits 1): the folder is
not a dj-library (no valid `library.yaml`: run dj-start on it first) or is a whole drive or
home folder (point it at the dj-library folder itself).
A relative `--xml` is looked up in the library folder first, then in the current folder.

My Tags live only in master.db. This version measures the XML export, so My Tags are not
measured: `stats.md` lists them under "Not in this source". Say that plainly; never guess them.

## Then write profile/habits.md (R-312)

Step 2 of 2, about 3 minutes. The script never writes this file; you do.

1. Read `profile/stats.md` and `profile/facts.json`. If they exist, read `taste/vocabulary.md`
   and `structure/analysis.md` too, and look at the playlist and folder names in the export.
2. Write `profile/habits.md`: at most one page (about 300 words), four paragraphs, the template
   below. Talk to the DJ as "you", in their words: their playlist names, their genre words.
3. Every number is copied from `stats.md` exactly as it stands there (R-302). No number of
   your own, no rounding, no estimate. Not measured means not said.
4. If `profile/habits.md` already exists, the DJ may have edited it. Leave it alone during the
   work phase; afterwards ask once whether to rewrite it from the new numbers.

```markdown
# Who you are as a DJ

> Words by Claude, from profile/stats.md and profile/facts.json.

<What you play. The eras and the sound, named with the DJ's own playlist and genre words.
Numbers from Eras and Formats and bitrates.>

<How you dig. The date-added timeline: when it started, the busiest year and month, what the
last 365 days look like.>

<How you keep the library. Formats and bitrates, the fields you fill and the one you skip,
from Fields used and Empty fields.>

<One thing to watch. Duplicate candidates or the tracks under 256 kbps, stated as a fact.
What to do about it is the DJ's call.>
```

The heading and the "Words by Claude" line are fixed. Keep the four paragraphs short: a DJ
reads this in a minute.

## What this skill never does (R-341)

- It never writes to rekordbox, Spotify or audio files, and never opens master.db for writing.
- The script writes only `profile/stats.md`, `profile/facts.json` and one line in `log.md`.
- It never picks which duplicate to keep or delete. That is the DJ's call, and deleting is
  not something this tool does.

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
