---
name: dj-structure
description: Measure how the DJ's rekordbox playlist tree is built - depth and width, naming habits, playlist sizes, overlap between playlists, tracks in no playlist, empty playlists and dumps, smart vs plain - and write it to structure/ in their dj-library folder, with the current tree as code (current-tree.yaml). Use when the DJ asks how their playlists are organised, which playlists overlap or double up, what sits in no playlist, what their tree looks like, or during the first run (dj-start step P4), even if they never say "structure".
---

# dj-structure

How the playlist tree is built today, measured by code from the DJ's XML export. Reads only.
rekordbox stays the truth: nothing here changes the tree.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-301, R-302, R-321, R-322, R-341.

## Patterns I read first

What the DJ already does comes before any suggestion (R-301). The script measures:

1. Depth and width: how many levels, how many playlists per folder.
2. Naming conventions: the most common name pattern (`word_word`, `Word Word`), numbered names (`1.1_`, `01 `; the number is not part of the pattern), dated names (`2025-03`), the words they name playlists with.
3. Playlist sizes and dumps: smallest, median, largest; catch-all playlists (more than 300 tracks, more than half the collection, or a big share next to much smaller playlists; the exact rule is in analysis.md, Dumps).
4. Overlap: pairs of playlists sharing half their tracks or more, near-copies, playlists that sit entirely inside another.
5. Orphans, empty playlists, smart vs plain: tracks in no playlist, playlists with nothing in them, how many lists are smart.

## How to run it

1. Cowork, no engine (Door 1): `python3 scripts/structure.py --library <dj-library folder>` from this skill's folder (`python` on Windows, `uv run python` inside a clone of the repo). Options: `--xml FILE` reads another export instead of the newest in `exports/`; `--today YYYY-MM-DD` sets the date written into the files.
2. Engine installed (Door 2): `dj library structure --library DIR [--xml FILE] [--today YYYY-MM-DD] [--json]`. Without `--library` it uses the configured folder.
3. The script prints one JSON object: `ok`, `written` (the 4 files), `kept`, `source`, `counts`, `reveals`, `log`. Exit 1 = error, with `error` saying what failed.
4. No export yet, or a folder that is not a dj-library folder (no valid `library.yaml`): the error says so and nothing is written. Tell the DJ to run dj-start on the folder or drop the collection XML in it, then run it again. About 1 minute.

During the first run (dj-start P4) it runs after dj-profile and before dj-taste, with no questions asked.

## What it writes

All text, all inside the library folder, paths relative to it. The tool rewrites these on every run.

| File | What is in it |
|---|---|
| `structure/analysis.md` | Shape, Naming, Sizes, Overlap, Orphans and empty, Dumps, What it reveals. 5 rows at most per section. |
| `structure/facts.json` | Every number and the full lists behind analysis.md. |
| `structure/graph.json` | `nodes`, `edges` and `overlaps` for the tree drawing in the report. |
| `structure/current-tree.yaml` | The tree as code (below). |
| `log.md` | One line: `structure -> N playlists, N folders, N files; structure/analysis.md`. |

## Explaining what it reveals

1. Read `structure/analysis.md`. Every number you say comes from that file (R-302). Never count, compute or round one yourself; if it is not in the file, do not say it.
2. "What it reveals" holds at most 5 sentences built by code. Retell at most 5, one line each, in booth words: crate, set, warm-up, peak time. Say "overlap" or "share 5 tracks", not "Jaccard"; "playlist" and "folder", not "node".
3. Observations, not verdicts: "unsorted dump holds 67% of your collection." Whether that is a problem is the DJ's call.
4. Words you write into an MD file carry `> Words by Claude, from structure/analysis.md.` under the heading. Never edit `analysis.md` itself: the next run rewrites it.
5. No fixes from here. A rebuild is proposed in the report (dj-report) and written only after a preview and the DJ's yes.

## current-tree.yaml: the library as code

- The tree as it is today, in the one tree schema that `proposals/*.yaml` and `bases.yaml` use (R-903): folders, playlists, smart playlists. Loading the file gives back the same tree (R-322).
- Smart playlists keep their rules as `rules_raw`, the raw rule text from master.db. An XML export carries no smart playlists, so from Door 1 there are none in the file.
- rekordbox allows two playlists with the same name in one folder; the file cannot hold that. The second one is written `Name (2)`, and analysis.md (Naming) and facts.json (`naming.duplicates_renamed`) list each one.
- The DJ may edit it freely; dj never writes it back to rekordbox. If the DJ edited it, the next run first saves their copy as `structure/current-tree.edited-<date>.yaml` (listed under `kept`). Name that file in your reply.

## Never

- Never write to rekordbox, Spotify or audio files (R-341). This skill reads the XML export and writes text in `structure/` plus one `log.md` line. It opens no database.
- Never put an absolute path in the folder's files. The source is named relative to the library folder.
- Never invent a number, a playlist or a track that is not in `structure/analysis.md`.

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
