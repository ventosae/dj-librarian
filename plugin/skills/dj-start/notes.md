# dj-start notes

Detail for dj-start: what the analysis writes, the two files you write (`profile/habits.md`, `profile/identity.md`), the report, and the taste files. Read the part you need.

## What the analysis writes

`dj_library_analyze()` reads one snapshot of rekordbox's database and writes text into the dj-library folder. Paths are relative to that folder; no file holds an absolute path.

| File | What is in it |
|---|---|
| `profile/stats.md`, `profile/facts.json` | Size, formats and bitrates, eras, the date-added timeline, fields used, empty fields, duplicate candidates |
| `profile/identity.json`, `profile/sleeve.svg` | The six axes with their inputs, the archetype, the 12-inch sleeve |
| `structure/analysis.md`, `structure/facts.json`, `structure/graph.json` | Shape, naming, sizes, overlap, orphans and empty playlists, dumps, what it reveals |
| `structure/current-tree.yaml` | The playlist tree as it is today, as code |
| `structure/proposals.yaml` | 2 or 3 ways to rebuild the tree, each with a name, a trigger, a cost and where playlists land |
| `taste/lanes.md`, `labels-artists.md`, `anchors.md`, `vocabulary.md`, `facts.json`, `cooccurrence.json` | BPM lanes, label and artist clusters, anchor tracks, the DJ's naming words, tracks played together |
| `reports/<date>-library.html` | The report: one file, opens offline |
| `catalog/catalog.db`, `catalog/tracks.csv` | Every track, every playlist and its tracks in order, and the DJ's notes |
| `log.md` | One line per step, written by the tool |

Before you suggest anything, read the five patterns in `profile/stats.md`: formats and bitrates, eras, the date-added timeline, fields used, duplicates. Each one is a habit the DJ already has. Start from it, never from a generic idea of a tidy library.

## profile/habits.md

About 3 minutes. The tool never writes this file; you do.

1. Read `profile/stats.md` and `profile/facts.json`, then `taste/vocabulary.md` and `structure/analysis.md`, and the playlist and folder names in `structure/current-tree.yaml`.
2. Write at most one page (about 300 words), four paragraphs, the template below. Talk to the DJ as "you", in their words: their playlist names, their genre words.
3. Every number is copied from `stats.md` exactly as it stands there. No number of your own, no rounding. Not measured means not said.
4. The file exists already: the DJ may have edited it. Leave it during the work; ask once afterwards whether to rewrite it from the new numbers.

```markdown
# Who you are as a DJ

> Words by Claude, from profile/stats.md and profile/facts.json.

<What you play. The eras and the sound, named with the DJ's own playlist and genre words. Numbers from Eras and Formats and bitrates.>

<How you dig. The date-added timeline: when it started, the busiest year and month, what the last 365 days look like.>

<How you keep the library. Formats and bitrates, the fields you fill and the one you skip, from Fields used and Empty fields.>

<One thing to watch. Duplicate candidates or the tracks under 256 kbps, stated as a fact. What to do about it is the DJ's call.>
```

The heading and the "Words by Claude" line are fixed. Keep the paragraphs short: a DJ reads this in a minute.

## profile/identity.md: the liner notes

The six axes, each a score from 0 to 100, measured by code:

| Axis | What it says | Measured from |
|---|---|---|
| Depth | How far back your crates go | how many decades really count, how old the middle of the catalogue is |
| Selectivity | How picky you are about files | lossless and 320 kbps share, how much sits under 256 kbps |
| Discipline | How tidy the crates are | playlists inside folders, the biggest dump, tracks in no playlist, doubles |
| Breadth | How wide your sound is | genres you tag, BPM lanes, tempo bands you cover |
| Momentum | How hard you are still digging | tracks added in the last 365 days against your own pace, the last add |
| Memory | How much you mark up | ratings, colours, comments, My Tags |

The archetype comes from the two highest axes (ties go to the earlier axis in the table), so the same library always gets the same one of 8. The sleeve is drawn from the collection: rings are decades (oldest inside), segments are BPM bands, a brighter cell holds more tracks, each band takes the colour of the lane that owns it. The big type is the booth name (`dj_name` in `library.yaml`, "You" until it is set).

About 2 minutes. The tool never writes this file; you do.

1. Read `profile/identity.json`: `archetype` (name, meaning, booth_line), `top`, and each axis `score` with its `inputs`. Read nothing else for this file.
2. Write at most 120 words and at most four lines under the heading, the template below. Talk to the DJ as "you".
3. Every number is copied from `identity.json` as it stands: a count such as `decades`, `oldest`, `newest`, `median_decade`, `lossless`, `at_320`, `under_256`, `genres`, `lanes`, `added_last_365_days`, `days_since_last_add`, or a Memory percentage (`rating`, `colour`, `comment`). A count that opens a sentence is written as a word ("Six decades"), still the value from the file. Never quote a derived input (`effective_*`, `*_share`, `pace`, `freshness`): a DJ does not recognise it. Say "tracks", not "files".
4. Booth words, not the chart: never an axis name and a number in one sentence, and no score at all. "Depth 94" becomes "Six decades in the crates, centred on the 2000s". The report prints the six scores next to the notes.
5. The file exists already: leave it during the work; ask once afterwards whether to rewrite it.
6. The DJ asked for the notes or the sleeve from the report: when the file is written, `dj_library_report()` and hand them the new file it names.

```markdown
# Liner notes

> Words by Claude, from profile/identity.json.

<Line 1: the two strong axes (`top`) in booth words, one fact each from their inputs, no axis name: "Six decades in the crates, centred on the 2000s, and 5 genres across 3 BPM lanes." Don't repeat the archetype name or its meaning: the report prints the name right above the notes.>

<Line 2: the archetype's booth line, in quotes.>

<Line 3: the weakest axis (the lowest score; ties go to the earlier axis) as a fact, and that what to do about it is the DJ's call: "The soft spot is the tracks: 4 under 256 kbps. Better copies or not, your call.">

<Line 4: what this library is good at on a floor, from the strongest axis, standing on its own: "On a floor: an answer to any request back to the 1970s.">
```

Four lines, no more. The heading and the "Words by Claude" line are fixed; the report shows the notes without that line.

## The report

One HTML file per run in `reports/`, never overwritten (`-2`, `-3` on the same day). Four sections: who you are (the sleeve, the booth name, the archetype, the liner notes, the six axes, the 5 stats that matter, then `habits.md`); how it's built (a crate wall: one row per top-level folder, a bar per playlist, dumps hatched, empty playlists as outlines, overlaps as arcs; at most 5 reveals); ways to rebuild it (2 or 3 cards: name, principle, new tree, where playlists land, cost, trigger); next (one action under 2 minutes). `habits.md` or `identity.md` missing: the report shows a placeholder line, so never block on them.

Your words go on the page as you wrote them; the tool does not check them. No greeting, numbers only from the files, the DJ's own words, no hype.

### How the proposals are picked

Three families, each scored 0 to 100 from what the DJ already does. Every family that scores above 0 is proposed, best first, 3 at most; at least 2 always are. The first one is the recommendation.

1. **Bases**: one base per main genre, each with `0_INBOX`, `1_CRATES`, `2_SETS`. Wins when the DJ fills the genre field and already names folders and playlists after genres.
2. **Facets**: 5 to 8 shallow genre shelves, gig crates beside them. Wins with many genres, playlists that overlap or sit inside each other, and dumps.
3. **Gig-first**: a crate per residency or event, everything else in an archive. Wins when playlist names are dated or venue-like, or hold "gig", "set", "night" or "@".

Every proposal is built as a copy beside the DJ's tree: a top-level name the DJ already has gets " (new)" (`gigs (new)` next to their `Gigs`). Nothing is moved, renamed or deleted: `lands` says where a copy of each playlist goes.

### Renaming a proposal

1. In `structure/proposals.yaml` change `name` and `trigger` together: the trigger is exactly `Build me the <name> structure`. `slug` stays: it is the proposal's id. Each name is used once.
2. Use the DJ's words only: a playlist name, a genre word or a word from `taste/vocabulary.md`. Never touch `cost_minutes`, `lands` or a `from` path: those are measured, and the paths are the real rekordbox paths.
3. `dj_library_report()`: the new report shows the new name. The next `dj_library_analyze()` writes the proposals again and keeps your edited copy as `structure/proposals.edited-<date>.yaml`: name that file to the DJ.

## The taste files

Every taste file is `# Title`, a "Measured by code" line, a `## Now` section (at most 5 lines, refreshed on every read) and a `## Log` of dated lines:

```markdown
- [2026-10-21] never propose: Kestrel Unit - Ferrous <!-- key:veto:16 -->
- [2026-10-21] never pair: Grid Saint - Pressure Vessel + Okoro Lane - Sunday Sermon <!-- key:pair:17,1 -->
- [2026-11-01] lifted: Kestrel Unit - Ferrous <!-- key:veto:16 -->
- [2026-10-22] + Kestrel Unit - Ballast: packed the floor <!-- key:gig:saturday -->
```

- A read appends: one line for a new item, one `updated:` line when an item changed. Old lines stay as they are, the DJ's hand-typed ones included.
- The latest line for a key decides, so a veto is lifted by a new line with the same key.
- `taste/vetoes.md` (never propose, never pair) and `taste/feedback.md` (what worked at a gig) are written by dj-barber and the DJ, and read by dj-crate and dj-build. The analysis never touches them.
- After a read you started outside the first session, show what was added: at most 5 lines per file, then "N more in taste/<file>". Nothing added: say so in one line.
- A lane is the middle half of each playlist's BPMs, merged with its neighbours up to 12 BPM wide. An anchor is one of 1 to 3 top-rated, most-played tracks of a cluster.
