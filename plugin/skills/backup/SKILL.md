---
name: backup
description: Back up the DJ's rekordbox database - a verified copy of master.db, its -wal and -shm, and masterPlaylists6.xml into backups/ in their dj-library folder, with RESTORE.md (the restore steps for their computer). Unchanged since the last verified copy - nothing is copied. Use when the DJ says "back up my library", "back up rekordbox", "is my library safe", asks for a backup before an import, or how to restore one, even if they never say "backup".
---

# Back up my library

A verified copy of the rekordbox database in the DJ's dj-library folder (R-206, D-31). It reads rekordbox's folder and writes only under `backups/` in the dj-library folder; it never changes rekordbox and never deletes a backup.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run its pre-send checklist before each reply.

One step. With the engine connected (the `dj_backup` tool answers), call `dj_backup`. In Claude Code (the Code tab) without it, run `"<uv>" run --directory "<engine folder>" --no-sync dj backup --library "<dj-library folder>"` (Windows: start the line with `& `; the engine folder is the one `/dj-librarian:install` used). Then show its `line` as it is, one of:

- `Backup: <path> · <size> · verified`: done. Name the folder and that `RESTORE.md` in it has the steps back.
- `Backup: unchanged since <date> · <path>`: nothing changed since that copy; nothing new was written.
- `... NOT verified (...)`: the copy was kept and flagged. Ask them to close rekordbox, then say "back up my library" again.

`dj_backup(list_backups=true)` (CLI `--list`) lists every backup with its date, whether it verified, its size, and the total. A refusal (exit 2) names the reason: a dj-library inside OneDrive, Dropbox, iCloud or Google Drive, or no dj-library set up yet (run `/dj-librarian:install` first). Analysis files and artwork are not in the copy: rekordbox's own File > Library > Backup Library covers them. To restore, the DJ follows `RESTORE.md` by hand; the tool never restores (v0.1).

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
