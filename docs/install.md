# Install

Install comes first (D-30). Upload the plugin zip (Door 1), then type `/dj-librarian:install` in Claude Code (Door 2, route 1): it installs the engine and makes your dj-library folder. Then say `/dj-librarian:dj-start` in a Cowork task: the first session reads rekordbox directly, no export. Without the install, the first session works from an XML export you make in rekordbox (Door 1, below). No terminal of your own either way.

## Door 1 — the plugin (Mac or Windows, 5 minutes)

What you need: the Claude desktop app, signed in to a plan that has Cowork. rekordbox 6 or 7.

1. Get `dj-librarian-plugin-<version>.zip` (from a GitHub release, or from whoever is testing with you). Don't unzip it. The light `dj-librarian-plugin-<version>-no-engine.zip` is the same without the install command, for Door 1 only.
2. Claude desktop app → **Customize → Plugins → Add → Upload plugin** → pick the zip. Turn the plugin on if it isn't.
3. Start a Cowork task **on this computer** (not a cloud task: the folder you connect must be on your machine).
4. Type **/dj-librarian:dj-start**. With the engine installed the first session is four steps and needs no export; without it, six steps, the XML export among them. The A6 card (`docs/handout/dj-librarian-a6.pdf`) has them.

Analysis runs on a copy of your rekordbox XML export, inside Cowork. rekordbox is never touched; a structure you choose arrives as an XML you import yourself.

Updating: upload the new zip the same way; it replaces the old one. Your `dj-library/` folder is untouched.

The light zip, `dj-librarian-plugin-<version>-no-engine.zip`, is Door 1 only: the same skills, no install command. Take it when the report and the XML builds are all you want.

## Door 2 — the engine (about 5 minutes, you click Allow)

Needed for: live master.db reads (My Tags, play counts), `dj tidy` on your audio files (audit and plan on both; writing tags on Windows only in v0.1), the Spotify inbox and the shopping list, Windows power mode.

The engine runs on your computer. Pick the first route that works for you.

### 1. The install command (first choice)

The plugin zip carries the engine's source. Claude Code installs it; you type one line and click **Allow** on each step.

1. Claude desktop app → **Code** tab → type **`/dj-librarian:install`**.
2. Click **Allow** on each step (8 of them): it finds or installs uv, copies the engine to `dj-librarian` in your home folder, installs what it needs, checks it with `dj status`, asks once which folder should be your dj-library (it makes it; `Music/dj-library` in your home folder is the offer), and adds the engine to Claude Desktop's config (a backup of the config first; no other entry changes).
3. Restart Claude Desktop. In **Customize → Connectors → dj-librarian**, leave every write tool on **Ask every time** (the list is below).
4. In a Cowork task, say **/dj-librarian:dj-start**: the first session reads your collection straight from rekordbox (`dj_status`, then the analysis from master.db) and ends with the same report. Later, **set me up** checks the engine.

A step fails: the command stops and shows one line. Send that line to whoever gave you the plugin. To take the engine out again: `/dj-librarian:uninstall` (the config entry goes, the folder stays). Unverified on a Mac until it has run there once (Q-32).

### 2. The desktop extension (second choice)

1. Get `dj-librarian-engine-<version>.mcpb` (from the GitHub release, or from whoever is testing with you). Don't unzip it.
2. Claude desktop app → **Settings → Extensions** → drag the `.mcpb` file onto that page → **Install**.
3. Fill the form it shows: **dj-library folder** (the one with `library.yaml`), **Spotify client ID** and **Spotify client secret** (optional), **Power mode (Windows)** (leave it off).
4. Set every write tool to **Ask every time**, open a new Cowork task and say **set me up**.

Unverified (Q-31): the app's host has to bring Python for this engine type. It is the same engine with the same tools: install one route only, or every tool shows twice.

### 3. By hand (third choice)

From a clone of the repo with uv, as a developer would: [README.md](../README.md#install) and [CONTRIBUTING.md](../CONTRIBUTING.md).

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

You need Spotify Premium and your own Spotify app; say **connect Spotify** and the dj-spotify skill walks you through it, about 8 minutes. Never paste the keys into the chat. With the install command, the keys go in a `.env` file in the engine folder (`dj-librarian` in your home folder, never the dj-library folder, which may be synced and which Cowork reads); with the desktop extension, in its settings form (**Spotify client ID**, **Spotify client secret**).

### Where the engine keeps its state

With the install command: in the engine folder (`dj-librarian` in your home folder): preview records, build and push state, the Spotify login token, caches, reports and the master.db backups taken before a power-mode write. A new version is copied over it after a backup copy (`dj-librarian.bak-<date>`), so nothing is lost.

With the desktop extension: in your dj-library folder, under `.cache/engine/` (preview records, build and push state, caches, master.db backups), reports in `reports/` there; the Spotify login token stays in `.dj-librarian/.cache/` in your home folder, never in the dj-library folder (it may be synced, and Cowork reads it). An update of the extension never touches these. With no usable library folder set, it keeps its state in `.dj-librarian` in your home folder until you pick one.

### Updating the engine

Install command: upload the new plugin zip (Door 1), then run `/dj-librarian:install` again; it backs up the old engine folder first. Desktop extension: drag the new `.mcpb` onto Settings → Extensions; it replaces the old one. Your dj-library folder stays either way.

## Status of each route

| Route | Mac | Windows |
|---|---|---|
| Door 1, the plugin zip in Cowork | verified on a Linux VM with the DJ's folder; first real Mac session pending | verified |
| Door 2, `/dj-librarian:install` | unverified (Q-32) | the same setup as the maintainer's daily one; the command itself not yet run on a fresh PC |
| Door 2, the `.mcpb` in Settings → Extensions | unverified (Q-31) | unverified (Q-31) |
| The engine's code (master.db reads, process check) | ported; no live Mac run yet | in daily use from a clone |

Q-32 stays open until the install command has run on a Mac. Q-31 stays open until the `.mcpb` has run once in the Claude desktop app on Windows, on a Mac, and inside a Cowork session.
