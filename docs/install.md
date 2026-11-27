# Install

One route, on a Mac or a Windows PC, about 10 minutes. You click; you never type in a terminal.

What you need: the Claude desktop app, signed in to a plan that has Cowork, and rekordbox 7 on the same computer (rekordbox 6 is untested).

## The steps

1. **Get the zip.** Download `dj-librarian-plugin-<version>.zip` from `dist/` in the repo on GitHub (open the file, then **Download raw file**), or take it from a GitHub release. Don't unzip it.
2. **Upload it.** Claude desktop app → **Customize → Plugins → Add → Upload plugin** → pick the zip. Turn the plugin on if it isn't.
3. **Install the engine.** Open the **Code** tab, type **`/dj-librarian:install`** and click **Allow** on each step. It finds or installs uv, copies the engine to `dj-librarian` in your home folder, installs what it needs, checks it with `dj status`, asks once which folder should be your dj-library (`Music/dj-library` in your home folder is the offer), backs up your rekordbox database into that folder's `backups/`, and adds the engine to Claude Desktop's config (a backup of the config first; no other entry changes).
4. **Restart Claude Desktop.** In **Customize → Connectors → dj-librarian**, leave every write tool on **Ask every time** ([permissions.md](permissions.md) has the list).
5. **Start.** Open a Cowork task **on this computer** (not a cloud task) and type **`/dj-librarian:dj-start`**. It reads your collection straight from rekordbox and, about 5 minutes later, opens the report. The A6 card (`docs/handout/dj-librarian-a6.pdf`) has the steps.

A step fails: the command stops and shows one line. Send that line to whoever gave you the plugin.

No dj-librarian tools in a session? One line: run `/dj-librarian:install` in the Code tab.

## How it writes

Nothing is written to rekordbox without a preview and your yes. Then: close rekordbox, say yes, and the write goes straight into rekordbox's database, after a verified backup, in one transaction that is rolled back on any error. While rekordbox is open, or when the check for it cannot run, the write is refused. Open rekordbox again and the new folders and playlists are there. It only adds: nothing that exists is deleted, renamed, moved or reordered.

To turn rekordbox writes off, set `DJ_POWER_MODE=false` in the engine's entry in Claude Desktop's config.

## Update

Upload the new zip the same way (it replaces the old one), then run `/dj-librarian:install` again: it backs up the old engine folder to `dj-librarian.bak-<date>` and copies the new one. On Windows, turn dj-librarian off in **Customize → Connectors** first, and on again after the restart. Your dj-library folder is untouched.

## Uninstall

In the Code tab, run `/dj-librarian:install` and say **uninstall**. It takes the dj-librarian entry out of Claude Desktop's config, after a backup of the config. It deletes no folder: the engine folder and your dj-library stay until you delete them yourself. Remove the plugin under **Customize → Plugins**.

## Backup

The install takes the first backup, and every write into rekordbox takes one before it starts. For one more, say **back up my library**: a verified copy of rekordbox's database lands in `backups/rekordbox-<date>/` in your dj-library folder, with a `RESTORE.md` that has the steps back for your computer. Nothing is copied when nothing changed, and no backup is ever deleted. Analysis files and artwork are not in it: rekordbox's own **File → Library → Backup Library** covers those.

## Spotify keys

You need Spotify Premium and your own Spotify app; say **connect Spotify** and the dj-spotify skill walks you through it, about 8 minutes. The two keys go in a file named `.env` in the engine folder (`dj-librarian` in your home folder), never in the dj-library folder and never in the chat.

## Where things live

| Folder | What is in it |
|---|---|
| your dj-library folder | Your files, plain text you own: the report, profile, structure, taste, proposals, crates, the wishlist, the catalog (`catalog/catalog.db`, `catalog/tracks.csv`) and `backups/`. |
| `dj-librarian` in your home folder | The engine: its code, preview records, the Spotify login, caches. An update replaces the code after a backup copy. |

## Status

| | Mac | Windows |
|---|---|---|
| `/dj-librarian:install` | not yet run on a Mac | the same setup as the maintainer's daily one; the command itself not yet run on a fresh PC |
| Reading rekordbox | ported; no live Mac run yet | in daily use |
| Writing into rekordbox | the same code path; no live Mac write yet | in use on the maintainer's library |
| `dj tidy` writing audio files | not yet: it audits and plans only | yes |
