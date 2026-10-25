---
name: dj-build
description: Turn a structure proposal from the library report into a rekordbox XML the DJ imports. Preview the tree first (CREATE / SKIP per node, where existing playlists land), ask "Write the XML?", write the XML into proposals/ only after an explicit yes, then give the import card for their OS. Use when the DJ says "Build me the ... structure" with a proposal's name, picks a proposal chip from the report, or asks to build, rebuild or import a new playlist tree, even if they never say "build".
---

# dj-build

A proposal becomes an XML the DJ imports into rekordbox by hand. You only propose: rekordbox
changes when the DJ drags the playlists in, never before. master.db is never opened (R-504).

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-501, R-502, R-503, R-504, R-505, R-702, R-904.

## How to run things

`library.yaml` says `source: db` (the engine path, D-30): use the engine column. The build then
reads a master.db snapshot, so every `from` playlist resolves there, including ones made after the
last export (`dj library build --source db`, Q-17). The script reads the export only.

| Step | Engine (MCP tool) | Cowork sandbox (script) |
|---|---|---|
| Preview | `dj_structure_preview(proposal)` | `python3 scripts/build.py preview "<proposal>" --library <folder>` |
| Write | `dj_structure_write(proposal, preview_id)` | `python3 scripts/build.py apply "<proposal>" --preview-id <id> --library <folder>` |

- Scripts run with `python3` (`python` on Windows, `uv run python` inside a clone of the repo).
- `<proposal>` = the slug, the name, or the trigger sentence the DJ typed ("Build me the Lanes structure").
- The script prints one JSON object. Exit 0 = done, 1 = error, 2 = refused. The MCP tools return
  `{ok, exit_code, result | stderr}`; a `REFUSED` line means the same as exit 2.
- Both need `structure/current-tree.yaml` (dj-structure) and `structure/proposals.yaml` (dj-report).

## The flow: 4 steps, one question

### Step 1 of 4: preview (B1)

Run the preview. Show one card, built from the result:

1. The tree as it will be: one line per node, `CREATE` or `SKIP` (exists already, stays out of the XML). Up to 5 lines, then "+N more".
2. Where existing playlists land (`lands`: from -> to, track count). Up to 5.
3. `MANUAL` rows: smart playlists the XML cannot carry; the DJ makes them by hand with the rules shown.
4. The counts line, then exactly: "Nothing written yet."

`vetoed` above 0: that many tracks `taste/vetoes.md` says never to propose, each with every copy
of it, stay out of the new playlists (R-702). Say the number in one line.

If `blocked` is set, there is no preview id. Say why in one line and offer Change or Stop only:

- A `CONFLICT`, or nothing to create: change `proposals/<slug>.yaml` with the DJ.
- `current-tree.yaml is older than the latest export`: run dj-structure, then preview again.
- `Export again, then say the trigger prompt.`: the proposals were made from a newer read than the
  export the build reads (a newer export, or master.db), or from an export that is gone. Say that
  line; the DJ exports the collection again (dj-start brings it in and rebuilds the proposals), then
  says "Build me the <name> structure" again.
- `Already built on ...`: that XML holds this exact build. Point to the file and the import card; a new build needs a changed proposal.

If `warnings` is not empty, state each one in one line (for example: `structure/proposals.yaml` could not be read, so the DJ's own file was used).

### Step 2 of 4: the gate (B2)

Ask the direct question **Write the XML?** with three answers: **Yes / Change / Stop**.

- **Yes** = an explicit yes to this preview: "yes", "write it", the Yes chip. Silence, "sounds good", "nice", a question back, or a yes to something else is not a yes: ask again.
- **Change** = edit `proposals/<slug>.yaml` the way the DJ says (it is their file; the tool never overwrites it), then preview again and go back to step 1 with the new preview id.
- **Stop** = nothing is written. The YAML stays in `proposals/` for later.

### Step 3 of 4: write and import (B3)

Only after the yes: call the write with the preview id from the latest preview. Then show:

1. "Wrote `proposals/<slug>.xml`." (name the file the result gives; it can be `<slug>-2.xml`).
2. With the engine (the MCP column above): call `dj_backup` right before the card and show its `line`. The DJ's import is the first thing that changes rekordbox, so a verified copy comes first (D-31, R-206); nothing changed since the last copy, nothing is copied. Without the engine, no line.
3. The import card: the 3 `import_steps` from the result, numbered, for the DJ's OS (Mac: rekordbox menu > Preferences; Windows: File > Preferences). "About 3 minutes."

The tool appends the `log.md` line itself (R-505, R-904): `YYYY-MM-DD HH:MM build <slug> -> N create, N skip, N manual, N tracks; proposals/<slug>.xml`. Do not write it yourself.

If the result has `warnings`, the XML is still written: state each warning in one line after the
file name. A log line that could not be added comes with its text; add it to `log.md` only if the
DJ says yes.

### Step 4 of 4: next (B4)

One line: "Open rekordbox, check the tree. Then: *Crate me 50 for Saturday*."

## Refusals and errors

- Refused (exit 2 / `REFUSED`): the preview id is missing, already used, older than 24 hours, or something changed since the preview. Run the preview again, show it, ask again. One preview id, one write: an id that was used never writes again. Never look for a way around it.
- "log.md cannot be written" or "library.yaml cannot be written": nothing was written. The DJ closes what holds the file open (a sync client, an editor); then write again with the same preview id.
- "run dj-structure first": `structure/current-tree.yaml` is missing. Run dj-structure, then preview.
- An unknown `from` path: name it, fix `proposals/<slug>.yaml` with the DJ, preview again.
- No proposal matches: list the names the error gives (up to 5) and ask which one.

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
