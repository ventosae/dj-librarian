# dj-librarian

A DJ librarian for rekordbox that you talk to through Claude.
It reads your rekordbox library and writes a report on it, rebuilds your playlist tree, picks crates for a night, syncs Spotify playlists into crates, and tidies the tags of your audio files.
rekordbox stays the source of truth: the tool only ever proposes and adds.

Status: early. Windows is the tested platform. macOS runs the same code (process check, master.db location) but is not yet confirmed against a live rekordbox on a Mac.

## Safety model

- **Create and add only.** Nothing that exists in rekordbox, on Spotify or on disk is ever deleted, renamed, moved or reordered. One exception: `dj tidy` fills empty tags and renames audio files inside their own folder, on your request and with an undo record first.
- **Preview, then yes.** Every write to rekordbox, Spotify or your audio files starts as a preview that writes nothing and returns a preview id. The write needs that id: one preview, one write. If anything changed since the preview, the write is refused. Claude asks you before it writes, and silence is not a yes.
- **Straight into rekordbox, one way only.** After your yes the write goes into rekordbox's database (`master.db`): rekordbox must be closed (if that check cannot run, the write is refused), a verified backup is taken first, everything lands in one transaction, and any error rolls it back. `DJ_POWER_MODE=false` in the engine's environment turns every rekordbox write off.
- **Idempotent.** A folder or playlist that exists at the same level is skipped. Running a command twice adds nothing the second time.

Text files in your own dj-library folder (plans, reports, analysis, proposals, the shopping list, the catalog) are written without a preview id. The full rules are in [CLAUDE.md](CLAUDE.md) and [docs/requirements.md](docs/requirements.md). Which tools to leave on "ask every time": [docs/permissions.md](docs/permissions.md).

## Install

What you need: the Claude desktop app on a plan with Cowork, and rekordbox 7 on the same Mac or Windows PC (rekordbox 6 is untested). You never type in a terminal yourself.

1. Download [`dist/dj-librarian-plugin-<version>.zip`](dist/) from this repo on GitHub (open the file, then **Download raw file**). Don't unzip it.
2. In the Claude app: **Customize → Plugins → Add → Upload plugin**, and pick the zip.
3. Open the **Code** tab, type `/dj-librarian:install` and click **Allow** on each step. It installs the engine on your computer, makes your dj-library folder and backs up your rekordbox database into it. Restart Claude Desktop when it says so.
4. Open a new Cowork task and type `/dj-librarian:dj-start`. About 5 minutes later you have the report on your library: who you are as a DJ, how the library is built, two or three ways to rebuild it.

Pick a structure and you see the new tree first. Close rekordbox, say yes, and it is written into rekordbox; open rekordbox again and it is there.

Updating, uninstalling, backups, permissions and the Spotify keys: [docs/install.md](docs/install.md).

## What you can say

| Skill | Say | What it does |
|---|---|---|
| `dj-start` | `/dj-librarian:dj-start`, "show my report" | Reads rekordbox, measures the library, writes the report and two or three structures to pick from. |
| `dj-build` | "Build me the House Bases structure" | Shows the new playlist tree, then writes it into rekordbox after your yes. |
| `dj-crate` | "Crate me 50 for Saturday" | Picks a crate from your own library with a reason per track. Name a seed track or say "build it with me" for the long version, with what to buy. |
| `dj-barber` | "Style barber" | A short question session that sharpens your taste files. |
| `dj-tidy` | "Check my tags" | Audits your audio files and fills empty tags, with an undo record first. |
| `dj-spotify` | "Connect Spotify", "sync my inbox" | Your own Spotify app, inbox playlists into crates, a shopping list, a playlist pushed to Spotify. |
| `install` | `/dj-librarian:install` | Installs or updates the engine; uninstall and backup live here too. |

Your files live in your dj-library folder: plain text you own (`profile/`, `structure/`, `taste/`, `reports/`, `proposals/`, `crates/`, `wishlist/`, `backups/`), plus `catalog/catalog.db` and `catalog/tracks.csv`, a copy of your collection you can open in any SQLite or spreadsheet tool.

## Configuration

The engine reads `links.yaml`, `tidy.yaml`, `bases.yaml` and `tree.yaml` from your dj-library folder. Copy what you need from [examples/](examples/):

| Example | Copy to | Used for |
|---|---|---|
| `examples/links.example.yaml` | `links.yaml` | Pairs a Spotify playlist with the rekordbox crate it feeds. |
| `examples/tree.example.yaml` | `tree.yaml` | The playlist tree you want. |
| `examples/bases.example.yaml` | `bases.yaml` | One folder per genre, same shape as the tree. |
| `examples/tidy.example.yaml` | `tidy.yaml` | Your music roots, naming rule and CDJ profiles. File writes are limited to the roots. |
| `examples/.env.example` | `.env` in the engine folder | The Spotify keys of your own Spotify app. Never in the dj-library folder, never in the chat. |

The engine's environment: `DJ_LIBRARY` (your dj-library folder; the install sets it), `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` (read before any `.env`), `DJ_POWER_MODE` (`false` turns rekordbox writes off), `DJ_MASTER_DB` (another `master.db` than rekordbox's default location).

## Claude plugin

The zip is the plugin at its root (`.claude-plugin/plugin.json`, `skills/`, `hooks/`) plus `engine/`, the engine's source. `/dj-librarian:install` copies `engine/` to `dj-librarian` in your home folder, runs `uv sync` there and registers the MCP server `dj-mcp` in Claude Desktop's config, after a backup of that config and without touching any other entry.

Read tools and write tools are separate tools, and every write tool refuses without the `preview_id` of its preview. In Claude Code the plugin also brings a PreToolUse hook (`plugin/hooks/`) that denies a write tool called without a `preview_id`. The hook starts `uv`, so on a machine without uv it blocks every write tool (it fails closed).

With no engine tools in the session, a skill answers with one line: "Run /dj-librarian:install in the Code tab."

Optional: [templates/project/instructions.md](templates/project/instructions.md) is a Cowork Project template you can paste into a new Project's instructions; the plugin works without it.

## Developers

You need [uv](https://docs.astral.sh/uv/) and rekordbox 7.

```bash
git clone https://github.com/ventosae/dj-librarian.git
cd dj-librarian
uv sync --group dev
uv run dj status
```

`dj status` is read-only and works while rekordbox is open; `uv run dj --help` lists the commands. If the clone sits in a cloud-synced folder, keep the virtual environment outside it: [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
uv run pytest
uv run ruff check .
uv run python scripts/build_plugin_zip.py
```

The last line writes `dist/dj-librarian-plugin-<version>.zip`, the one file a DJ uploads. The tests never open a real rekordbox database, a socket or an audio file outside a temp folder.

To use the clone's engine instead of an installed one, register it by hand. Claude Code:

```bash
claude mcp add --scope user dj-librarian -- uv run --directory /path/to/dj-librarian --no-sync dj-mcp
```

Claude Desktop, in `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "dj-librarian": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/dj-librarian", "--no-sync", "dj-mcp"]
    }
  }
}
```

On macOS, Claude Desktop starts programs with a short `PATH`: if it cannot find `uv`, put the full path that `which uv` prints into `command`.

- **master.db.** Found through pyrekordbox, else at rekordbox's default location: `%APPDATA%\Pioneer\rekordbox\master.db` on Windows, `~/Library/Pioneer/rekordbox/master.db` on macOS. Reads use a snapshot copy and work while rekordbox is open.
- **Is rekordbox running?** Checked with `tasklist` on Windows (`rekordbox.exe`) and `/usr/bin/pgrep` on macOS (`rekordbox`). If the check cannot answer, writes are refused.
- **Audio files.** `dj tidy` writes tags and names on Windows only for now; on macOS it audits and plans, and the write refuses with a one-line reason.

## Documentation

- [docs/install.md](docs/install.md): install, update, uninstall, backup.
- [docs/permissions.md](docs/permissions.md): which tool reads, which writes, and what to set.
- [docs/requirements.md](docs/requirements.md): numbered requirements (authoritative).
- [docs/architecture.md](docs/architecture.md): plugin architecture and repo layout.
- [docs/decisions.md](docs/decisions.md): decisions and their reasons.
- [docs/plan.md](docs/plan.md): current work items and open questions.
- [docs/lessons.md](docs/lessons.md): what the build has learned about rekordbox, Spotify and audio files.
- [CONTRIBUTING.md](CONTRIBUTING.md): development setup and pull request rules.

## Licence

[Apache-2.0](LICENSE).
