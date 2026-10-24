# Install

Two doors, no terminal. Door 1 is all a DJ needs for the first session. Door 2 is the engine, for live reads, My Tags, Spotify and tidy. The plugin zip carries both: one upload. Whether the engine starts from inside the zip is unverified (Q-31); the engine on its own is the fallback.

## Door 1 — the plugin (Mac or Windows, 5 minutes)

What you need: the Claude desktop app, signed in to a plan that has Cowork. rekordbox 6 or 7.

1. Get `dj-librarian-plugin-<version>.zip` (from a GitHub release, or from whoever is testing with you). Don't unzip it. For a first session, the light `dj-librarian-plugin-<version>-no-engine.zip` is the safe pick: the engine inside the full zip is unverified (Q-31).
2. Claude desktop app → **Customize → Plugins → Add → Upload plugin** → pick the zip. Turn the plugin on if it isn't.
3. Start a Cowork task **on this computer** (not a cloud task: the folder you connect must be on your machine).
4. Type **hi**. The first session is six steps; the A6 card (`docs/handout/dj-librarian-a6.pdf`) has them.

Analysis runs on a copy of your rekordbox XML export, inside Cowork. rekordbox is never touched; a structure you choose arrives as an XML you import yourself.

Updating: upload the new zip the same way; it replaces the old one. Your `dj-library/` folder is untouched.

The light zip, `dj-librarian-plugin-<version>-no-engine.zip`, is Door 1 only: the same skills, no engine inside. Take it when the report and the XML builds are all you want.

## Door 2 — the engine (no terminal, about 3 minutes)

Needed for: live master.db reads (My Tags, play counts), `dj tidy` on your audio files (audit and plan on both; writing tags on Windows only in v0.1), the Spotify inbox and the shopping list, Windows power mode.

The engine runs on your computer. The Claude app brings the Python it needs; you install nothing yourself.

### One upload: it's already in

Unverified until tested (Q-31): if no dj-librarian tools show up, use the fallback below.

The Door 1 zip carries the engine. After the first report:

1. Say **set me up** and point Claude at your dj-library folder.
2. Claude tells you where the engine settings are. Fill the form:
   - **dj-library folder** (required): the folder from the first session, the one with `library.yaml` in it. Pick it by its name on your computer, not a path Claude shows you from Cowork.
   - **Spotify client ID** and **Spotify client secret** (optional): leave both empty until you want Spotify.
   - **Power mode (Windows)**: leave it off. On, it allows direct master.db writes, still only after a preview and your yes, with rekordbox closed and a backup taken first.
3. Set every write tool to **Ask every time** (the list is below).
4. Say **done**. Claude calls `dj_status`; it answers with your track count, read live from rekordbox. No dj-librarian tools yet: open a new Cowork task (or restart Claude) and say **set me up** there.

Where the engine settings are:

| How the engine came in | Engine settings |
|---|---|
| Inside the plugin zip (the Claude desktop app, Cowork tasks) | Look under **Settings → Extensions → dj-librarian engine**. Where a plugin's own engine settings show is unverified (Q-31); not there? Use the fallback below: its settings land there. |
| The `.mcpb` on its own (the fallback) | **Settings → Extensions → dj-librarian engine** |
| Claude Code | None yet: Claude Code 2.1.299 does not start this engine from the plugin (Q-31). The report, builds and crates keep running on the XML. |

### Fallback: the engine on its own

When no dj-librarian tools show up after the upload, even in a new Cowork task or after a restart of Claude, or the engine settings are nowhere to be found:

1. Get `dj-librarian-engine-<version>.mcpb` (from the GitHub release, or from whoever is testing with you). Don't unzip it.
2. Claude desktop app → **Settings → Extensions** → drag the `.mcpb` file onto that page → **Install**.
3. Fill the form it shows: the same four fields as above.
4. Set every write tool to **Ask every time**, open a new Cowork task and say **set me up**.

This route is unverified too (Q-31). If the `.mcpb` does not install either, the report, the builds and the crates keep working on the XML; tell whoever gave you the plugin.

It is the same engine with the same tools. Install it only when the one upload did not give you the tools: two engines side by side would show every tool twice.

### Permissions: every write tool on Ask every time

In the dj-librarian tool permissions, set each of these to **Ask every time**. Read tools can stay on Allow. Claude Code takes them as an `ask` list in its settings; the block to paste and every tool's group are in [permissions.md](permissions.md).

| Write tool | Writes to |
|---|---|
| `dj_structure_write` | `proposals/<slug>.xml`, a rekordbox XML you import |
| `dj_crate_write` | `proposals/crate-<slug>.xml`, a rekordbox XML you import |
| `dj_tree_apply` | rekordbox master.db (power mode, Windows) |
| `dj_apply_write` | an XML you import, or master.db in power mode |
| `dj_copy_apply` | an XML you import, or master.db in power mode |
| `dj_push_apply` | Spotify (a private playlist, adds only) |
| `dj_build_apply` | Spotify (a private playlist, adds only) |
| `dj_tidy_apply` | your audio files' tags and names (undo record first) |
| `dj_tidy_undo` | your audio files' tags and names (restores them) |

### Spotify keys

They go in the engine's settings form (**Spotify client ID**, **Spotify client secret**): not in a `.env` file, never in the chat. You need Spotify Premium and your own Spotify app. Say **connect Spotify** and the dj-spotify skill walks you through it, about 8 minutes. New keys later: the same form.

### Where the engine keeps its state

In your dj-library folder, under `.cache/engine/`: preview records, build and push state, caches, and the master.db backups taken before a power-mode write. Reports land in `reports/` in the library folder. The Spotify login token stays on this computer, in `.dj-librarian/.cache/` in your home folder, never in the dj-library folder (it may be synced, and Cowork reads it); an update keeps it. An update replaces the engine's own install folder and never touches these, so nothing is lost. `.cache/` stays out of git (the folder's `.gitignore`). With no usable library folder set, the engine keeps its state in `.dj-librarian` in your home folder until you pick one.

### Updating the engine

It updates with the plugin zip (Door 1). On its own: drag the new `.mcpb` onto Settings → Extensions the same way; it replaces the old one. Your dj-library folder and the engine's state in it stay. If the settings form comes back empty, fill it again.

Developers: the clone route (git, uv, the `dj` CLI) lives in [README.md](../README.md#install) and [CONTRIBUTING.md](../CONTRIBUTING.md).

## Status of each route

| Route | Mac | Windows |
|---|---|---|
| Door 1, the plugin zip in Cowork | verified on a Linux VM with the DJ's folder; first real Mac session pending | verified |
| Door 2, the engine inside the plugin zip | unverified (Q-31) | unverified in the Claude desktop app (Q-31). Claude Code 2.1.299 refuses it: the skills load, the engine does not |
| Door 2 fallback, the `.mcpb` in Settings → Extensions | unverified (Q-31) | unverified (Q-31) |
| The engine's code (master.db reads, process check) | ported; no live Mac run yet | in daily use from a clone |

Q-31 stays open until each route has run once: the Claude desktop app on Windows, on a Mac, and inside a Cowork session. Claude Code 2.1.299 starts a bundle from a plugin only with a `python` server type, and that type needs uv on the machine. The engine keeps the `uv` type, the one where the host brings Python, so nobody installs anything; the one-upload route waits for a host that takes it inside a plugin.

Known gap: in Claude Code the plugin's write-gate hook starts `uv`. On a machine without uv it fails closed, so Claude Code refuses every write tool there ([permissions.md](permissions.md), The hook).
