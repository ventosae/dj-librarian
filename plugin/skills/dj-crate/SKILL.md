---
name: dj-crate
description: Crate me. Pick a crate for a night (30, 50 or 70 tracks plus 20% spares) from the DJ's own library, from a brief ("Crate me 50 for Saturday's rooftop"). Turn the brief into a crate spec in crates/, preview the picks with one reason each, ask "Write the crate XML?", and only after an explicit yes write the crate XML into proposals/ and the crate record into crates/, then give the import card. Use when the DJ asks for a crate, a set list, tracks for a gig, a warm-up or peak-time selection, or says "crate me", even if they never say "crate". Syncing a Spotify inbox playlist into a crate is dj-sync, not this skill.
---

# dj-crate

A brief becomes a crate the DJ imports into rekordbox by hand. Code picks and orders the tracks
from their own library and `taste/` (lanes, anchors, co-occurrence, vetoes); you turn the brief
into the spec and say the reasons in your words. rekordbox changes only when the DJ drags the
playlists in. master.db is never opened.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-601, R-602, R-603, R-604, R-702.

## How to run things

| Step | Engine (MCP tool) | Cowork sandbox (script) |
|---|---|---|
| Preview | `dj_crate_preview(spec)` | `python3 scripts/crate.py preview <slug> --library <folder>` |
| Write | `dj_crate_write(spec, preview_id)` | `python3 scripts/crate.py apply <slug> --preview-id <id> --library <folder>` |

- Scripts run with `python3` (`python` on Windows, `uv run python` inside a clone of the repo).
- `<slug>` names `crates/<slug>.spec.yaml` in the dj-library folder (the path works too).
- The script prints one JSON object. Exit 0 = done, 1 = error, 2 = refused. The MCP tools return
  `{ok, exit_code, result | stderr}`; a `REFUSED` line means the same as exit 2.
- The tracks come from the latest export in `exports/`. `taste/` comes from dj-taste; without it
  the preview measures lanes and anchors from the export and says so in `warnings`.

### Gig feedback (R-702)

`taste/feedback.md` scores the picks. Two dated line shapes count; the sign sits right after the date:

- `+ Artist - Title: note` (`- [2026-10-22] + Kestrel Unit - Ballast: packed the floor`): the track
  worked at a gig. +1 to its score; its reason says "worked at a gig".
- `- Artist - Title: note` (`- [2026-10-22] - Grid Saint - Pressure Vessel: cleared the floor`):
  it flopped. -1, "flopped at a gig", and it is never a spare.

A line names the song: every copy of it counts, and the latest line for a song decides. A line
typed with `+` as its bullet (`+ [2026-10-22] Artist - Title: note`) counts as worked; a flop needs
the `-` sign after the date. Other lines are remarks and do not count. dj-barber's gig question writes these lines; the DJ may add one by
hand. `counts` says how many candidates `worked` and `flopped`. A change to the file changes the
crate, so preview again before a write.

## The flow: 5 steps, two questions at most

### Step 1 of 5: the brief (C1)

Ask one thing, and only when the brief lacks it: the event or vibe, and the size with three
chips **30 / 50 / 70**. Both missing: one question for both ("Who is it for, and how many? 30 /
50 / 70"). A brief that names both: no question, go to step 2.

### Step 2 of 5: the spec

Write `crates/<slug>.spec.yaml` from the brief. The slug is lower-case letters, digits and `-`
(`saturday-rooftop`). Put in only the fields the brief supports; leave the rest out.

| Field | What | Example |
|---|---|---|
| `name` (required) | the playlist name in rekordbox | `Saturday Rooftop` |
| `size` (required) | 30, 50 or 70 | `50` |
| `brief` (required) | the DJ's words, one line | `rooftop, sunset into the night` |
| `bpm`, `lanes` | a BPM window, or lane labels from `taste/lanes.md` | `[118, 124]`, `["118-124"]` |
| `genres`, `exclude_genres`, `keys`, `min_rating`, `my_tags`, `anchors`, `curve` | genre words; keys (Am, 8A or 1m: neighbours fit too); stars 0-5; My Tags (score only); track ids that must be in; `flat`, `warmup` or `peak` | see below |

```yaml
name: Saturday Rooftop
size: 50
brief: rooftop, sunset into the night, vocal house
bpm: [118, 124]
genres: [House, Deep House]
exclude_genres: [Techno]
anchors: ["9", "13"]
curve: warmup
```

- Anchors and lanes come from the DJ's files (`taste/anchors.md`, `taste/lanes.md`,
  `taste/facts.json`), never from memory. No track id you have not seen in a file.
- The file exists already: it is an earlier crate. Change it only when the DJ asks to change that
  crate; for a new night use a new slug.

### Step 3 of 5: preview

Run the preview. Show one card, built from the result:

1. The counts line: picks, spares, candidates, vetoed (`counts`).
2. The first 5 picks in order, each with its `reason` in your words (same facts, no new numbers), then "and N more".
3. Spares, marked as spares: how many per energy tier (low, mid, high). They land in their own playlist, `<name> spares` (no spares fit: no spares playlist).
4. `warnings`, one line each; then exactly: "Nothing written yet."

`blocked` set: there is no preview id. Say why in one line and offer Change or Stop only. "Only N
tracks fit": say the count and the filter the error names to widen, and offer the smaller size it
suggests.

### Step 4 of 5: the gate (C2)

Ask the direct question **Write the crate XML?** with three answers: **Yes / Change / Stop**.

- **Yes** = an explicit yes to this preview: "yes", "write it", the Yes chip. Silence, "nice", a question back, or a yes to something else is not a yes: ask again.
- **Change** = edit `crates/<slug>.spec.yaml` the way the DJ says, preview again, back to step 3 with the new preview id. What can change: `size`, `curve`, the filters (`bpm`, `lanes`, `genres`, `exclude_genres`, `keys`, `min_rating`), `anchors` and `my_tags`. The spec cannot drop one pick by id: to lose a track, narrow a filter. A "never propose" line in `taste/vetoes.md` keeps it out of every crate from now on, so write one only when the DJ says never.
- **Stop** = nothing is written. The spec stays in `crates/` for later.

### Step 5 of 5: write and import

Only after the yes: call the write with the preview id from the latest preview. Then show:

1. "Wrote `proposals/crate-<slug>.xml`" and the crate record `crates/<slug>.md` (name the files the result gives; they can end in `-2`).
2. With the engine (the MCP column above): call `dj_backup` right before the card and show its `line`. The DJ's import is the first thing that changes rekordbox, so a verified copy comes first (D-31, R-206); nothing changed since the last copy, nothing is copied. Without the engine, no line.
3. The import card: the 3 `import_steps` from the result, numbered, for the DJ's OS. "About 3 minutes."
4. Next, one line: "Open rekordbox, play the first three picks. Then tell me what to change: size, BPM, genres, keys or anchors."

A written crate keeps its name: once imported, rekordbox has `Crates/<name>`. To change it after
the write, give the spec a new `name` (`Saturday Rooftop 2`) or, when the DJ did not import it,
ask for a fresh export first. The preview blocks a name that a crate written since the latest
export already used.

The tool appends the `log.md` line itself (R-904): `YYYY-MM-DD HH:MM crate <slug> -> N picks, N
spares; proposals/crate-<slug>.xml`. Do not write it yourself. `warnings` in the result: the XML
is written; state each one in one line.

## Refusals and errors

- Refused (exit 2 / `REFUSED`): the preview id is missing, already used, older than 24 hours, or the spec, the export or `taste/` changed since the preview. Preview again, show it, ask again. Never look for a way around it.
- A spec problem: the error lists each one; fix the spec and preview again.
- A vetoed track (`taste/vetoes.md`) never appears, as a pick or a spare; a never-pair is never in one crate. A veto names the song, so every copy of it (same artist and title) stays out too. A vetoed anchor, or a second copy of another anchor, is left out with a warning: tell the DJ.
- `log.md cannot be written`: nothing was written. The DJ closes what holds it open; then write again with the same preview id.
- `blocked` "`Crates/<name>` is in `proposals/crate-....xml`, written ... after your latest export": an earlier crate took that name and the export is older than it. Offer a new `name`, or a fresh export when that crate was never imported.
- A warning that an earlier crate XML "holds a Crates folder too": the import card drags the two playlists into that Crates folder. Say so in one line; if the DJ never imported the earlier XML, they drag the whole Crates folder into Playlists instead.

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
