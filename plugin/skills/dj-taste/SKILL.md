---
name: dj-taste
description: Measure the DJ's taste from their rekordbox collection XML and keep it in taste/ - BPM lanes per playlist, label and artist clusters, key preferences, tracks they play together, top-rated and most-played tracks, 1-3 anchor tracks per cluster, and the words they name playlists with. Appends dated lines across sessions and never regenerates without asking. Use whenever the DJ asks about their taste, sound, lanes, BPM ranges, go-to labels or artists, anchor tracks or naming vocabulary, after a new export lands, or during onboarding (dj-start runs it), even if they never say "taste".
---

# dj-taste

The DJ's taste, read from what they already did: playlists, ratings, plays, names. The script
measures; you put words around its numbers. Nothing here touches rekordbox.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-301, R-302, R-331, R-332, R-341.

## Patterns I read first

Before suggesting anything (R-301), read the patterns the DJ already shows:

| Pattern | Measured from | Lands in |
|---|---|---|
| Labels and artists | label and artist tags; how many playlists each one sits in; clusters of labels played together | `taste/labels-artists.md` |
| BPM lanes per playlist | the middle half of each playlist's BPMs; overlapping ranges merge into lanes up to 12 BPM wide | `taste/lanes.md` |
| Keys | key tags; minor vs major share | `taste/facts.json` (`keys`) |
| Co-occurrence | tracks that sit together in 2 or more playlists | `taste/cooccurrence.json` |
| Ratings and play counts | stars and plays; 1-3 anchor tracks per cluster | `taste/anchors.md` |
| The DJ's own words | words in folder and playlist names | `taste/vocabulary.md` |

How each one is measured (percentiles, merge rule, cluster rule, tie-breaks) is written in the
docstring of `src/dj/analysis/taste.py`. Quote it when the DJ asks "why is that a lane?".

## How to run it

1. Script (Cowork, no install): `python <plugin>/skills/dj-taste/scripts/taste.py --library DIR
   [--xml FILE] [--today YYYY-MM-DD] [--rebuild]`. `--xml` reads one specific export (a relative
   path is looked up in the library folder first, then in the current folder); `--rebuild` only
   after the DJ's explicit yes (see below). In a clone of the repo the script finds the core by
   itself.
2. CLI (engine or Claude Code): `uv run dj library taste [--library DIR] [--xml FILE]
   [--today YYYY-MM-DD] [--rebuild] [--json]`. Without `--library` it uses the configured folder.

Both read the latest export (`exports.latest` in `library.yaml`, else the newest `exports/*.xml`).
The script prints one JSON object (the CLI does with `--json`; without it, the same in short
text, at most 5 added lines per file): `counts` first (tracks, lanes, clusters, anchors, pairs, words,
lines_added), then `source`, `written`, `added` (the new log lines per file), `backup` (after a
rebuild: the folder that holds the old files) and `log` (the line appended to `log.md`). A few
seconds on a small library; allow a minute for a big one.

Exit codes: 0 done; 1 error (say what failed and what happens next); 2 refused: the folder has no
`library.yaml`, so it is not a dj-library folder yet. Set it up with dj-start, then run again.
All four MD files are checked before any is written, so most errors leave `taste/` as it was. A
write that fails part way (a file held open by an editor or a sync app) exits 1 with `written`
and `added` beside `error`: show those added lines like a normal run, then the error.

## The files

| File | What is in it | Written by |
|---|---|---|
| `taste/lanes.md` | BPM lanes and the playlists in each; mixed playlists named | the script |
| `taste/labels-artists.md` | top labels and artists, clusters | the script |
| `taste/anchors.md` | 1-3 anchor tracks per cluster | the script |
| `taste/vocabulary.md` | the DJ's naming words, with example names | the script |
| `taste/facts.json`, `taste/cooccurrence.json` | every number and the full lists (pairs: the 5,000 strongest); rewritten each run | the script |
| `taste/vetoes.md`, `taste/feedback.md` | what never to propose or pair; what the DJ said about picks | Style Barber and the DJ |

Every taste MD file is `# Title`, the provenance line
`> Measured by code: dj.analysis.taste from exports/<file>.xml, <YYYY-MM-DD>.`, a `## Now`
section (at most 5 lines: the current top items, refreshed every run) and a `## Log` of dated
lines `- [YYYY-MM-DD] <text> <!-- key:<stable key> -->`. A run adds at most 5 lines per file;
the full lists are in the JSON files. Numbers come only from the script (R-302). If you add
words of your own to a taste file, put them under their own `##` heading with the line
`> Words by Claude, from <relative files>.` and no numbers the script did not give.

## Append, never regenerate (R-332)

- Every run appends only: one line for a new item, one `updated:` line when an item changed. Old
  lines stay exactly as they are, including the lines the DJ typed by hand. Only the Now section
  and the provenance line are refreshed.
- After every run you start, show the added lines: at most 5 per file, then "N more in
  taste/<file>". When nothing was added, say so in one line ("Nothing new since the last export").
- Exception, onboarding: when dj-start runs the script in its step 4 (P4), say nothing about it.
  dj-start's rules own that reply (no question and no other chat until the report). The diff is
  shown from the next run on.
- Never regenerate from scratch on your own. `--rebuild` rewrites the four MD files and drops
  every old line from them, the DJ's own included. Ask first, say what will be lost, and pass
  `--rebuild` only after an explicit yes. Silence is not a yes. Before it rewrites, the script
  copies the old files to `.cache/taste-rebuild-<date>/` (named in `backup`); tell the DJ that
  folder. `log.md` records it (`4 files rebuilt, 4 old files kept in .cache/...`).
- Never edit or delete lines in `taste/*.md` yourself. To correct something, append a dated line.

## Vetoes and feedback

Style Barber and the DJ write these; Crate me reads them; dj-taste never touches them.

```markdown
- [2026-10-21] never propose: Kestrel Unit - Ferrous <!-- key:veto:16 -->
- [2026-10-21] never pair: Grid Saint - Pressure Vessel + Okoro Lane - Sunday Sermon <!-- key:pair:17,1 -->
- [2026-11-01] lifted: Kestrel Unit - Ferrous <!-- key:veto:16 -->
```

The key holds the track ids (from `facts.json`, `cooccurrence.json` or the export); the text is
for people. The latest line for a key decides, so a veto is lifted by appending a line with the
same key and other text. Keys match without regard to spaces around the ids, and a pair matches
in either order (`pair:1,17` lifts `pair:17,1`). `taste/feedback.md` holds one dated line per
remark, the key optional:
`- [2026-10-22] too dark for a warm-up: Kestrel Unit - Ballast <!-- key:feedback:18 -->`.
The parsers are `read_vetoes` and `read_feedback` in `src/dj/taste_files.py`.

## Telling the DJ

Not during onboarding (see above). On any other run:

1. One line: what was measured, from which export, and the file names written.
2. Up to 5 lines from the Now sections, in the DJ's words: their lanes, their labels, their anchors.
3. The added lines, at most 5 per file.
4. One next action under 2 minutes (for example: "Open taste/lanes.md: does 119-122 feel like
   your warm-up?").

## Never (R-341)

- Never writes to rekordbox, master.db, Spotify or audio files. It reads the export copy in
  `exports/` and writes text in `taste/` plus one line in `log.md` (and, on `--rebuild`, the
  copy of the old files in `.cache/`).
- No absolute paths in taste files: the export is named relative to the library folder.

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
