# dj-librarian

A DJ librarian for rekordbox that you talk to through Claude.
It syncs Spotify playlists into rekordbox crates, builds playlist folders from a YAML file, copies playlists to Spotify, and tidies the tags of your audio files.
rekordbox stays the source of truth: the tool only ever proposes and adds.

Status: early (0.1.0, unreleased). Windows is the tested platform. macOS is ported (process check, master.db location) but not yet confirmed against a live rekordbox on a Mac.

## Safety model

- **Create and add only.** Nothing that exists in rekordbox, on Spotify or on disk is ever deleted, renamed, moved or reordered.
- **Dry-run is the default.** Every command that writes to rekordbox, Spotify or your audio files shows what it would do and prints a preview id first. Real writes need `--apply --preview-id <id>`: the id of the dry-run you said yes to. If anything changed since, the write is refused. Text files in your own folders (plans, reports, analysis, proposals, the shopping list) are written directly, without a preview id.
- **Preview, then yes.** Through Claude, every write tool has a preview tool and needs its `preview_id`, and Claude asks you before it writes. Silence is not a yes. Which tools to leave on "ask every time": [docs/permissions.md](docs/permissions.md).
- **Import, don't inject.** The default write path is a rekordbox XML file that you import yourself: `dj library build` writes a new playlist structure as `proposals/<slug>.xml`, `dj library crate` a crate as `proposals/crate-<slug>.xml`. Direct writes to rekordbox's `master.db` are a Windows power mode behind `--power-mode`: rekordbox must be closed, a verified backup is taken first, everything lands in one commit, and any error rolls back. `dj tree --apply` uses this power mode. Inbox adds and playlist copies write an XML too: `dj apply` and `dj copy` with `--apply --xml` write `proposals/<crate>-adds-<date>.xml` (any OS; you import it and drag the tracks onto the crate), or master.db with `--apply --power-mode`.
- **Idempotent.** A folder or playlist that exists at the same level is skipped. Running a command twice adds nothing the second time.

The full rules are in [CLAUDE.md](CLAUDE.md) and [docs/requirements.md](docs/requirements.md).

## Try it before the release

Until the first release, a tester runs the plugin from a zip. This is Door 1: no clone and no install beyond the zip, about 15 minutes to your first report.

1. Get the zip: once a version is tagged, ask the maintainer for `dj-librarian-plugin-<version>.zip` from the draft GitHub release (only maintainers see a draft), or build it in a clone with `uv run python scripts/build_plugin_zip.py` (it writes `dist/dj-librarian-plugin-<version>.zip`).
2. In the Claude app: **Customize → Plugins → Add → Upload plugin**, and pick the zip.
3. Open a new Cowork task and say "start". Door 1 runs in Cowork: an ordinary chat cannot connect a folder.
4. Three moves from you: say Mac or Windows, export your collection from rekordbox (File → Export Collection in xml format), connect a folder in Cowork (a new one called `dj-library`) and drop the XML into it.
5. About 5 minutes later the report is in `reports/<date>-library.html`: who you are as a DJ, how your library is built, two or three ways to rebuild it. Pick one and you see the new tree first; after your yes you get `proposals/<slug>.xml` to import in rekordbox yourself.

rekordbox is never touched: Door 1 reads a copy of your export, and you do the import. Crate me and Style Barber run from the zip too. If the upload refuses the zip, build it again with `--flat` (the plugin at the zip's root; which layout the upload wants is still open, Q-21).

The engine comes in the same zip: live reads of your rekordbox database (My Tags), Spotify and `dj tidy` on your audio files. No clone, no terminal: say "set me up" after the report and point Claude at your dj-library folder; the engine card ([plugin/skills/dj-start/engine.md](plugin/skills/dj-start/engine.md), about 3 minutes) shows where the engine's settings are. Whether the engine starts from inside the zip is unverified (Q-31). The fallback is the engine on its own, `dj-librarian-engine-<version>.mcpb`: Claude desktop app → Settings → Extensions → drag it in → Install. The light zip, `dj-librarian-plugin-<version>-no-engine.zip`, is Door 1 only. All of it in one place: [docs/install.md](docs/install.md).

## Install

DJs: [docs/install.md](docs/install.md) is the one install doc. One upload, the plugin zip with the engine inside; the engine's `.mcpb` on its own as the fallback; which tools to leave on "ask every time"; the Spotify keys in the engine's settings form. Nothing to type in a terminal.

### From a clone (developers)

You need [uv](https://docs.astral.sh/uv/) and rekordbox 7.

```bash
git clone https://github.com/OWNER/dj-librarian.git
cd dj-librarian
uv sync
uv run dj status
```

`dj status` is read-only and works while rekordbox is open. If the clone sits in a cloud-synced folder (Dropbox, iCloud Drive and the like), keep the virtual environment outside it; see [CONTRIBUTING.md](CONTRIBUTING.md).

The three release files come from the clone:

| Command | Writes |
|---|---|
| `uv run python scripts/build_mcpb.py` | `dist/dj-librarian-engine-<version>.mcpb`, the engine on its own |
| `uv run python scripts/build_plugin_zip.py` | `dist/dj-librarian-plugin-<version>.zip`, the plugin with the engine inside |
| `uv run python scripts/build_plugin_zip.py --no-engine` | `dist/dj-librarian-plugin-<version>-no-engine.zip`, the light zip (Door 1 only) |

## Commands

| Command | What it does |
|---|---|
| `uv run dj status` | Read-only. Track count, the playlist tree, and per Spotify link the counts by status. |
| `uv run dj tree [--file F]` | Dry-run of `tree.yaml` (or `F`): `CREATE`, `SKIP`, `HOLD`, `CONFLICT` per node. |
| `uv run dj tree --apply --power-mode --preview-id <id>` | Creates the missing folders and playlists. Windows, rekordbox closed, backup first, one commit. |
| `uv run dj pull <link>` / `--all` | Reads a Spotify playlist into `.cache/inbox/` in your dj-library folder (`inbox/` in the repo while the library's `links.yaml` holds no link). Read-only on Spotify. |
| `uv run dj match <link>` | Matches the inbox against your library: `IN_CRATE`, `PROPOSE`, `AMBIGUOUS`, `MISSING`, `DECLINED`. |
| `uv run dj plan <link>` | Writes a plan file and a wishlist. You set `decision: yes\|no` per item. |
| `uv run dj apply <plan> [--apply --power-mode --preview-id <id>]` | Dry-run, then appends the approved tracks to the crate. |
| `uv run dj copy "<src>" "<dst>" [--apply --power-mode --preview-id <id>]` | Appends the tracks of one rekordbox playlist to another. The source is only read. |
| `uv run dj push "<playlist>" [--apply --preview-id <id>]` | Mirrors a rekordbox playlist into a private Spotify playlist. Adds only. |
| `uv run dj build <tracklist.txt> [--apply --preview-id <id>]` | Turns an `Artist - Title` text tracklist into a private Spotify playlist. |
| `uv run dj analyze` | Census of your Spotify library into Markdown reports. Read-only on Spotify. |
| `uv run dj wishlist shop <link>` | `wishlist/<crate>.shopping.md`: Beatport and Bandcamp search links for the MISSING tracks of the link's newest plan. |
| `uv run dj tidy audit <crate>` / `--all` / `--folder D` | Hygiene audit of the audio files (only read): tags, artwork, names, CDJ playability, duplicates. Writes its report in `reports/tidy/`. |
| `uv run dj tidy plan <target>` | Proposes values for EMPTY tags, parsed from the file names. |
| `uv run dj tidy apply <plan> [--apply --preview-id <id>]` | Writes approved tags (undo record first). Then Reload Tag in rekordbox. |
| `uv run dj tidy undo <plan> [--apply --preview-id <id>]` | Restores what that apply changed. |
| `uv run dj library use <folder>` | Tells the engine where your `dj-library/` folder is. |
| `uv run dj library inspect [xml]` | Read-only summary of the library from an XML export, or from a master.db snapshot. |
| `uv run dj library analyze [--source xml\|db]` | Reads the library once, then writes `profile/`, `structure/`, `taste/`, the proposals and the HTML report in your dj-library folder. One step each: `dj library profile`, `structure`, `taste`, `report`. |
| `uv run dj library build "<proposal>" [--apply --preview-id <id>]` | Preview of a restructure proposal, then `proposals/<slug>.xml` for you to import. Never opens master.db. |
| `uv run dj library crate <spec> [--apply --preview-id <id>]` | Preview of a crate from `crates/<slug>.spec.yaml`, then `proposals/crate-<slug>.xml` for you to import. |
| `uv run dj library barber next` / `record N ANSWER` | Style Barber: one short question at a time; the answers go into `taste/` as dated lines. |

Every command takes `--json`, except `dj tree --apply` (text only; its dry-run takes `--json`). Exit codes: `0` ok, `1` error, conflict or refused (no valid preview id, no `--power-mode`), `2` rekordbox is running (writes refused), or `dj library taste`, `report`, `analyze`, `barber` or `use` refused a folder that is not a set-up dj-library (`REFUSED` on stderr). `dj library profile` and `structure` report that case as `ERROR` with exit 1.

Through Claude, the MCP tools return counts first and long lists in pages (`page`, `page_size`; `paging` says how many there are). A bare file name is looked up in its folder: `set.txt` in `tracklists/`, `x.plan.json` in `plans/`.

## Configuration

Your configuration lives in your dj-library folder: the engine reads `links.yaml`, `tidy.yaml`, `bases.yaml` and `tree.yaml` there first. In a clone, the same files at the repo root (gitignored) are the fallback, and the repo's `links.yaml` is used while the library's holds no link. The engine extension takes the Spotify keys in its settings form; a clone reads them from `.env`. Copy what you need from [examples/](examples/):

| Example | Copy to | Used by |
|---|---|---|
| `examples/.env.example` | `.env` (a clone only) | Spotify commands. Create an app at the Spotify developer dashboard with redirect URI `http://127.0.0.1:8888/callback`. |
| `examples/links.example.yaml` | `links.yaml` in your dj-library folder | `pull`, `match`, `plan`: pairs a Spotify playlist with a rekordbox crate. |
| `examples/tree.example.yaml` | `tree.yaml` in your dj-library folder | `dj tree`: the playlist tree you want. |
| `examples/bases.example.yaml` | `bases.yaml` in your dj-library folder | `dj tree --file bases.yaml`: one folder per genre, same shape. |
| `examples/tidy.example.yaml` | `tidy.yaml` in your dj-library folder | `dj tidy`: your music roots, naming rule and CDJ profiles. File writes are limited to the roots. |

## Claude plugin

The plugin adds twelve skills (see `plugin/skills/`) and the engine: `engine.mcpb`, an MCP server with a fixed list of `dj` tools, which `plugin.json` names under `mcpServers`. A DJ starts with **dj-start** ("start"): it sets up the dj-library folder from a rekordbox XML export and writes the first report. Read tools and write tools are separate, so you can leave every write tool on "ask every time"; which tool is which: [docs/permissions.md](docs/permissions.md). In Claude Code the plugin also brings a PreToolUse hook (`plugin/hooks/`) that denies a write tool called without a `preview_id`. The hook starts `uv`, so on a machine without uv it blocks every write tool (it fails closed; a known gap).

The engine is an [MCP bundle](https://github.com/modelcontextprotocol/mcpb) of the `uv` type: the host brings Python and the dependencies, so a DJ installs nothing. Its settings form asks for the dj-library folder, the optional Spotify client ID and secret, and Power mode (Windows); the host hands them to the engine as `DJ_LIBRARY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` and `DJ_POWER_MODE`. The engine then keeps its state in `<dj-library>/.cache/engine/`, so an update of the extension loses nothing. Claude Code 2.1.299 refuses a `uv` bundle inside a plugin: it loads the skills, not the engine. Whether the Claude desktop app starts it, from the plugin or as an extension, on Windows, on a Mac and in Cowork, is open (Q-31).

`plugin/engine.mcpb` is a build product (gitignored): `uv run python scripts/build_mcpb.py --plugin` writes it, and `claude plugin validate ./plugin` needs it.

- **Claude Code, from a clone:** build the engine into the plugin as above, then add the marketplace from the clone. Run this inside the clone folder:

```bash
claude plugin marketplace add ./
```

```bash
claude plugin install dj-librarian@dj-librarian
```

Until Claude Code takes a `uv` bundle in a plugin (Q-31), register the engine from the clone by hand: [The engine on Windows and macOS](#the-engine-on-windows-and-macos) has the line for Claude Code and the config entry for Claude Desktop.

The skills that need no engine (dj-start through the report, crates, builds, Style Barber) run from the plugin zip: it carries their core in `vendor/` (D-22). A copy without it (a GitHub marketplace, until the core is on PyPI) answers with a one-line error that the dj-librarian core does not load. The skill scripts look for the core in this order: an importable `dj` (the engine's venv), a clone of the repo, the zip's `vendor/`.

Optional: [templates/project/instructions.md](templates/project/instructions.md) is a Cowork Project template you can paste into a new Project's instructions; the plugin works without it.

### The engine on Windows and macOS

The engine is the MCP server `dj-mcp`; it runs on your computer. A DJ gets it from the plugin zip or the `.mcpb` ([docs/install.md](docs/install.md)). From a clone (developers), register it by hand.

Claude Code, one line (`--scope user` makes it available in every folder; Claude Code started from your shell passes `UV_PROJECT_ENVIRONMENT` on):

```bash
claude mcp add --scope user dj-librarian -- uv run --directory /path/to/dj-librarian --no-sync dj-mcp
```

Claude Desktop, in its config file:

| OS | Claude Desktop config file |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "dj-librarian": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/dj-librarian", "--no-sync", "dj-mcp"],
      "env": {"UV_PROJECT_ENVIRONMENT": "/Users/<you>/.venvs/dj-librarian"}
    }
  }
}
```

On macOS, Claude Desktop starts programs with a short `PATH`: if it cannot find `uv`, put the full path that `which uv` prints into `command`. It does not read `~/.zshrc` either, so the `UV_PROJECT_ENVIRONMENT` from [CONTRIBUTING.md](CONTRIBUTING.md) does not reach it: pass the venv folder in `env` as above, as a full path (no `~`, no `$HOME`). On Windows it is written `C:\\Users\\<you>\\.venvs\\dj-librarian` in the JSON. Leave `env` out when uv uses `.venv/` inside the repo.

- **master.db.** Found through pyrekordbox, else at rekordbox's default location: `%APPDATA%\Pioneer\rekordbox\master.db` on Windows, `~/Library/Pioneer/rekordbox/master.db` on macOS. Set `DJ_MASTER_DB` to use another file. Reads work while rekordbox is open.
- **Is rekordbox running?** Checked with `tasklist` on Windows and `/usr/bin/pgrep` on macOS. If the check cannot answer, writes are refused.
- **Writes.** Direct master.db writes (`dj tree`, `dj apply`, `dj copy` with `--apply`) need `--power-mode` and stay Windows-only; on macOS they refuse with a one-line reason. In the engine extension, Power mode (Windows) in its settings is off by default, and while it is off every master.db write is refused. `dj tidy apply --apply` and `dj tidy undo --apply` write audio files on Windows only in v0.1; on macOS they refuse with a one-line reason (macOS support is planned for v0.2). Their dry-runs only read.

## Documentation

- [docs/install.md](docs/install.md): the install doc for DJs, both doors, no terminal.
- [docs/requirements.md](docs/requirements.md): numbered requirements (authoritative).
- [docs/architecture.md](docs/architecture.md): plugin architecture and repo layout.
- [docs/decisions.md](docs/decisions.md): decisions and their reasons.
- [docs/plan.md](docs/plan.md): current work items and open questions.
- [docs/lessons.md](docs/lessons.md): what the build has learned about rekordbox, Spotify and audio files.
- [CONTRIBUTING.md](CONTRIBUTING.md): development setup and pull request rules.

## Licence

[Apache-2.0](LICENSE).
