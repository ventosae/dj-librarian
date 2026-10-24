---
name: dj-identity
description: The DJ's identity from their own rekordbox library - six measured axes (Depth, Selectivity, Discipline, Breadth, Momentum, Memory), an archetype picked by code, and a 12-inch record sleeve drawn from the collection (profile/identity.json, profile/sleeve.svg), then liner notes in profile/identity.md. Use when the DJ asks what kind of DJ they are, for their archetype, their sleeve, their identity or liner notes, what their library says about them in one line, or when dj-start runs the analysis.
---

# dj-identity

The code measures six axes from the facts the other analysis skills wrote, picks an archetype
from the two strongest and draws the sleeve. You write the liner notes. Nothing here writes to
rekordbox, Spotify or audio files.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-1401, R-1402, R-1403, R-1404, R-1405, R-1406.

## What the six axes mean

Each axis is a score from 0 to 100, measured by code (R-1401). In booth words:

| Axis | What it says | Measured from |
|---|---|---|
| Depth | How far back your crates go. | how many decades really count, and how old the middle of the catalogue is |
| Selectivity | How picky you are about files. | lossless and 320 kbps share, and how much sits under 256 kbps |
| Discipline | How tidy the crates are. | playlists inside folders, the biggest dump, tracks in no playlist, doubles |
| Breadth | How wide your sound is. | genres you tag, BPM lanes, tempo bands you cover |
| Momentum | How hard you are still digging. | tracks added in the last 365 days, against your own pace, and the last add |
| Memory | How much you mark up. | ratings, colours, comments and My Tags (My Tags only from master.db) |

The archetype comes from the two highest axes (ties go to the earlier axis in the table): each
of the 15 pairs belongs to one of the 8 archetypes in [archetypes.yaml](archetypes.yaml), so the
same library always gets the same archetype (R-1402). The formulas and every input sit in
`profile/identity.json` next to each score.

The sleeve (`profile/sleeve.svg`, R-1403) is a 12-inch sleeve drawn from the collection: rings
are decades (oldest inside), segments are BPM bands, a brighter cell holds more tracks, and each
band takes the colour of the lane that owns it: the four biggest lanes have a colour, kept on
every chart of the report; the other lanes and bands no lane owns are grey. The DJ's handle is the
big type, the archetype is under it, the three biggest lanes are the liner notes at the bottom.
It only changes when the export does. The handle is `dj_name` in `library.yaml`, asked once by
dj-start ("What do they call you in the booth?"), "You" until then (R-1406).

## How to run

Step 1 of 2, under a minute. Run it after profile, structure and taste: it reads their facts.

1. Door 1, no engine (Cowork): from this skill's folder run
   `python3 scripts/identity.py --library <dj-library folder>` (`python` on Windows). Options:
   `--today YYYY-MM-DD` fixes the date the axes are measured at (default: the date in
   `profile/facts.json`); `--xml FILE` reads one export instead of the latest.
2. A clone of the repo (Claude Code at the repo root, for developers):
   `uv run dj library identity --json`. `--library DIR` defaults to the configured folder;
   `--xml` and `--today` work as above. `dj library analyze` runs it too, after taste and before
   the report.

Both print one JSON object, counts first: `counts`, `archetype` (slug, name), `top` (the two
axes), `scores` (all six), `handle`, `source`, `written` (`profile/identity.json`,
`profile/sleeve.svg`) and `log` (the line added to `log.md`). Exit 1 means it stopped: read
`error` and tell the DJ in one line (usually "run profile, structure and taste first", or the
facts came from an older export). Exit 2: refused, nothing written: the folder is not a
dj-library yet (run dj-start on it).

## Then write profile/identity.md (R-1404)

Step 2 of 2, about 2 minutes. The script never writes this file; you do.

1. Read `profile/identity.json`: `archetype` (name, meaning, booth_line), `top`, and each axis
   `score` with its `inputs`. Read nothing else for this file.
2. Write `profile/identity.md`: the liner notes, at most 120 words and at most four lines under
   the heading, in the voice, with the template below. Talk to the DJ as "you".
3. Every number is copied from `identity.json` exactly as it stands there (R-302): a count such
   as `decades`, `oldest`/`newest`, `median_decade`, `lossless`, `at_320`, `under_256`,
   `genres`, `lanes`, `added_last_365_days`, `days_since_last_add`, or a Memory percentage
   (`rating`, `colour`, `comment`). A count that opens a sentence is written as a word ("Six
   decades"), still the value from the file. Never quote a derived input (`effective_*`,
   `*_share`, `pace`, `freshness`): a DJ does not recognise it. No number of your own, no
   rounding, no estimate. Say "tracks", not "files".
4. Booth words, not the chart: never an axis name and a number in the same sentence, and no
   score at all ("Depth 94: the middle of the crates sits in the 2000s" becomes "Six decades in
   the crates, centred on the 2000s"). The report prints the six scores in the chart right next
   to the notes.
5. If `profile/identity.md` already exists, the DJ may have edited it. Leave it alone during the
   work phase; afterwards ask once whether to rewrite it from the new identity.
6. The DJ asked from the report ("draw my sleeve", "write my liner notes"): when this is done,
   render the report again (`python3 ../dj-report/scripts/report.py render --library <folder>`)
   and hand them the new file it names.

```markdown
# Liner notes

> Words by Claude, from profile/identity.json.

<Line 1: the two strong axes (`top`) in booth words, one fact each from their inputs, no axis
name: "Six decades in the crates, centred on the 2000s, and 5 genres across 3 BPM lanes." Don't
repeat the archetype name or its meaning: the report prints the name right above the notes.>

<Line 2: the archetype's booth line, in quotes.>

<Line 3: the weakest axis (the lowest score; ties go to the earlier axis) as a fact, and that
what to do about it is the DJ's call: "The soft spot is the files: 4 tracks under 256 kbps.
Better copies or not, your call.">

<Line 4: what this library is good at on a floor, from the strongest axis, standing on its own
(it follows the soft spot, so no "that" pointing back): "On a floor: an answer to any request
back to the 1970s.">
```

Four lines, no more. The heading and the "Words by Claude" line are fixed (the report shows the
notes without that line and credits Claude in its footer). The report hero shows the sleeve,
the archetype and these notes (R-1405); Style Barber names the archetype once per session.

## What this skill never does

- It never writes to rekordbox, Spotify or audio files, and never opens master.db for writing.
- The script writes only `profile/identity.json`, `profile/sleeve.svg` and one line in `log.md`.
- It never calls an axis good or bad: a low Discipline is a fact about the crates, not a verdict.

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
