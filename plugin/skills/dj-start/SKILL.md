---
name: dj-start
description: First session with a DJ, from hello to the HTML report on their rekordbox library in six steps (device, XML export, library folder, analysis, report, next move). Use on a first hello, or when the DJ says "sort my library", "start", "analyse my library" or "analyze my library", or when no dj-library folder is set up yet.
---

# dj-start

Session 1. The DJ makes three moves, waits once, and the first long thing they read is the HTML
report on their own library. rekordbox is never touched: the tool reads a copy of the XML export.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-101, R-102, R-103, R-104, R-105, R-106, R-107.

## Your moves

Before the work phase the DJ does exactly this, nothing more (R-106):

1. Tap their device: Mac or Windows.
2. Export the collection XML from rekordbox.
3. Connect a folder in Cowork and drop the XML into it.

Then they wait about 5 minutes and get the report.

## How to run the scripts

Paths are relative to this skill's folder. Run scripts with Python 3: `python3 scripts/start.py ...`
(`python` on Windows, `uv run python` inside a clone of the repo). Each prints one JSON object.
Exit 0 = done, 1 = error, 2 = refused; then the JSON holds one line in `error` and its kind in
`reason` (step 3 has a reply for each). Paths in the JSON are relative to the library folder.
Every number in a reply comes from this JSON or from the files the scripts write, never from you
(R-302).

Widgets: question chips, a task list, a file card. If one does not render, send the numbered-text
version the step gives (Q-05).

Already set up: when a folder is connected before step 1, run find-xml on it first. `library` not
null means the folder holds this tool's `library.yaml`: take the device from `library.device`,
skip step 1, then run init with find-xml's `xml` when it found one, without a word (init copies a
new export and skips one it already has). Then go to the first that fits:

- Nothing to read (no `xml` and no `library.latest_export`): step 2.
- A new export (`new_export` true) or no report yet (`library.latest_report` null): step 4.
- Otherwise nothing is new: step 6, with its "no new export" first line.

## The six steps

### Step 1: Hello (P1)

One line in the voice that ends with the device question, shown as two chips: **Mac** and **Windows**.

```text
Step 1 of 6 · under a minute. I'll read your rekordbox collection and hand you one report on how your library is built, 3 moves from you. Mac or Windows?
```

No chips: the numbered version.

```text
Step 1 of 6 · under a minute. I'll read your rekordbox collection and hand you one report on how your library is built, 3 moves from you. Mac or Windows? Reply 1 or 2.
1. Mac
2. Windows
```

Remember the answer. From here on show only that OS, never both (R-101). It becomes
`--device mac` or `--device windows` in step 3, and `library.yaml` keeps it for later sessions.

### Step 2: Export (P2)

One card, 3 numbered steps, about 2 minutes (R-104). Show only the block for the DJ's device,
never both.

Mac:

```text
Step 2 of 6 · about 2 minutes. Export your collection from rekordbox:
1. In rekordbox, open File in the menu bar at the top of the screen.
2. Click Export Collection in xml format.
3. Name it collection.xml, pick Desktop under Where, click Save. Then say done.
```

Windows:

```text
Step 2 of 6 · about 2 minutes. Export your collection from rekordbox:
1. In rekordbox, click File at the top left of the rekordbox window.
2. Click Export Collection in xml format.
3. Pick Desktop on the left, name it collection.xml, click Save. Then say done.
```

### Step 3: Folder (P3)

```text
Step 3 of 6 · about 1 minute. Connect a folder in Cowork (a new one called dj-library is best) and drop collection.xml into it.
```

Once the folder is connected, with the device from step 1:

1. `python3 scripts/start.py find-xml --library <folder>`: the newest rekordbox XML in the folder
   (`xml`), outside `exports/` and `proposals/`.
2. `python3 scripts/start.py init --library <folder> --device <mac|windows> --xml <xml>`: scaffolds
   the folder (R-103), copies the XML into `exports/` (the original stays where the DJ put it),
   reads the copy, records device, rekordbox version and date in `library.yaml`, and appends one
   line to `log.md` when anything changed.

find-xml returned `library` (the folder was set up in an earlier session): after init, go on as
Already set up says.

Report what was created in one line, from the init JSON (`created`, `export`, `counts`):

```text
Step 3 of 6 · done in under a minute. Created <n> folders and files, copied your export to <export>: <tracks> tracks, <playlists> playlists. Your original stays where you put it.
```

`created` is empty: the folder and this export were already there. Say that in the same line.
`device_was` is set: the folder was set up for the other device and `library.yaml` now holds the
one from step 1. Add `Switched the folder to your device.` to the same line.

When something is off, one matter-of-fact line with the next action, then wait for the DJ. Pick
the reply by `reason`. `no_xml`, or find-xml returns `xml: null`:

```text
Step 3 of 6 · about 1 minute. No rekordbox XML in that folder yet. Drop collection.xml into it and say done.
```

`xml` (the file is broken, is not rekordbox's own export, or holds no tracks):

```text
Step 3 of 6 · about 2 minutes. That XML did not read: <error> Export it again (step 2), drop the new file in and say done.
```

`folder` (a `library.yaml` that is not this tool's, a file where one of its folders goes) and
`refused`, exit 2 (a whole drive, the home folder, Desktop or another busy folder):

```text
Step 3 of 6 · about 1 minute. That folder won't hold the library: <error> Make a new folder called dj-library, connect it, drop the XML in and say done.
```

`disk` or `internal`:

```text
Step 3 of 6 · about 1 minute. Setting up the folder failed: <error> Check the folder is still connected, then say done.
```

`core` (this skill's scripts cannot load where they run, Q-06):

```text
Step 3 of 6 · about 2 minutes. My scripts don't load here: <error> Reinstall the dj-librarian plugin, open a new chat and say start.
```

`usage`: your own command was wrong. Fix it and run it again; nothing to tell the DJ.

After a clean init go straight to step 4. No question from here to the report.

### Step 4: Working (P4)

```text
Step 4 of 6 · about 5 minutes. Go make a coffee.
```

Show a task list with these 5 items and tick each one off as it finishes. Run them in order, each
script with `--library <folder>`:

1. Read collection: `init` did it in step 3. Tick it at once.
2. Profile: `python3 ../dj-profile/scripts/profile.py --library <folder>`
3. Structure: `python3 ../dj-structure/scripts/structure.py --library <folder>`
4. Taste: `python3 ../dj-taste/scripts/taste.py --library <folder>`
5. Report: write `profile/habits.md` yourself (rules in `../dj-profile/SKILL.md`), then
   `python3 ../dj-report/scripts/report.py --library <folder>`.

No task list: send this line instead.

```text
Step 4 of 6 · about 5 minutes. Go make a coffee. Working: read collection, profile, structure, taste, report.
```

A script fails (exit 1 or 2): mark that item failed, keep its one-line error for step 6, run the
rest. No question in this step and no other chat until step 5 (R-106, NFR-07).

### Step 5: Report (P5)

Deliver the file the report script's JSON names under `report` as a file card, with one line:
`reports/<date>-library.html`, or `-2`, `-3` ... when a report was already written that day.
Never guess the name. Step 6 goes out in the same reply, right under that line, so the reply ends
with one action under 2 minutes and the DJ never has to write to see it.

```text
Step 5 of 6 · about 5 minutes to read. Your report: reports/<date>-library.html
```

No file card: send the same line; the DJ opens the file from the folder.

The report script failed (step 6 then uses its "report failed" first line):

```text
Step 5 of 6 · under a minute. The report did not render: <error>. What I measured is in profile/, structure/ and taste/.
```

### Step 6: Next (P6)

Sent in the same reply as step 5, right under it. The first line is the
one action under 2 minutes. Chips: one per proposal in the report (2 or 3), each its trigger
`Build me the <name> structure` exactly as the report shows it, plus `not yet`. The last line
says what was missing and is the only place for the engine offer (R-102): the XML has no My Tags
or play history (Q-01; the init JSON lists them under `not_in_xml`). The engine reads My Tags,
but in this version not play history (Q-13), so never promise history.

```text
Step 6 of 6 · under 2 minutes. Pick one below: I show you the new tree before anything gets written.
The XML has no My Tags or play history; the engine reads your My Tags. Install the engine (about 10 minutes): say set me up.
```

No chips: this version.

```text
Step 6 of 6 · under 2 minutes. Reply with a number: I show you the new tree before anything gets written.
1. Build me the <name 1> structure
2. Build me the <name 2> structure
3. Build me the <name 3> structure
4. Not yet
The XML has no My Tags or play history; the engine reads your My Tags. Install the engine (about 10 minutes): say set me up.
```

A returning DJ with no new export (see Already set up): the same chips and last line, this first
line, and the report as a file card.

```text
Step 6 of 6 · under 2 minutes. No new export since your last report, <latest_report>. Pick one below: I show you the new tree before anything gets written.
```

The report failed: no chips, this first line, then the last line as above.

```text
Step 6 of 6 · under 2 minutes. Say run the report again and I retry it.
```

A step 4 item failed: add one line before the last line, `Skipped: <item>, <error>.`
The DJ says set me up: follow [engine.md](engine.md) in this folder, the engine card (M1). The DJ
picks a structure: the build skill takes over. Not yet: the report stays in `reports/`.

## Rules

- At most 3 DJ actions before the work phase: the three under Your moves.
- No questions between step 3 and step 5. Something missing: finish with what there is and say what was missing at step 6.
- Chat stays under 5 lines per reply until the report.
- Every reply starts with the step counter and a time estimate: `Step N of 6 · about N minutes`.
- Errors are matter-of-fact: what failed, then the next action, in one line.

The Cowork Project template `templates/project/instructions.md` is optional; nothing in this skill depends on it (R-107).

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
