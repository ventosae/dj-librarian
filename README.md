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

## Install

You need [uv](https://docs.astral.sh/uv/) and rekordbox 7.

```bash
git clone https://github.com/OWNER/dj-librarian.git
cd dj-librarian
uv sync
uv run dj status
```

`dj status` is read-only and works while rekordbox is open. If the clone sits in a cloud-synced folder (Dropbox, iCloud Drive and the like), keep the virtual environment outside it; see [CONTRIBUTING.md](CONTRIBUTING.md).

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

Your own configuration is gitignored. `links.yaml` belongs in your dj-library folder (the repo's `links.yaml` is the fallback while the library's holds no link); the other files live next to the code. Copy what you need from [examples/](examples/):

| Example | Copy to | Used by |
|---|---|---|
| `examples/.env.example` | `.env` | Spotify commands. Create an app at the Spotify developer dashboard with redirect URI `http://127.0.0.1:8888/callback`. |
| `examples/links.example.yaml` | `links.yaml` in your dj-library folder | `pull`, `match`, `plan`: pairs a Spotify playlist with a rekordbox crate. |
| `examples/tree.example.yaml` | `tree.yaml` | `dj tree`: the playlist tree you want. |
| `examples/bases.example.yaml` | `bases.yaml` | `dj tree --file bases.yaml`: one folder per genre, same shape. |
| `examples/tidy.example.yaml` | `tidy.yaml` | `dj tidy`: your music roots, naming rule and CDJ profiles. File writes are limited to the roots. |

## Claude plugin

The plugin adds twelve skills (see `plugin/skills/`) and an MCP server with a fixed list of `dj` tools. A DJ starts with **dj-start** ("set me up"): it sets up the dj-library folder from a rekordbox XML export and writes the first report. Read tools and write tools are separate, so you can leave every write tool on "ask every time"; which tool is which: [docs/permissions.md](docs/permissions.md). In Claude Code the plugin also brings a PreToolUse hook (`plugin/hooks/`) that denies a write tool called without a `preview_id`.

The plugin starts its MCP server from the folder above the plugin folder (`uv run --directory <plugin folder>/..`), so it works only while the plugin runs from your clone, after `uv sync` there.

- **Claude Code:** add the marketplace from your clone, so the plugin loads in place. Run this inside the clone folder:

```bash
claude plugin marketplace add ./
```

```bash
claude plugin install dj-librarian@dj-librarian
```

A marketplace added from GitHub (`OWNER/dj-librarian`), or the plugin uploaded as a zip, runs a cached copy of the plugin with no engine next to it. The skills that need no engine (dj-start through the report, crates, builds, Style Barber) still run from the plugin zip: `uv run python scripts/build_plugin_zip.py` writes `dist/dj-librarian-plugin-<version>.zip`, which carries their core in `vendor/` (D-22). A copy without it (a GitHub marketplace, until the core is on PyPI) answers with a one-line error that the dj-librarian core does not load. The skill scripts look for the core in this order: an importable `dj` (the engine's venv), a clone of the repo, the zip's `vendor/`.

- **Claude desktop app:** Customize → Plugins → Add → Add marketplace. Whether the plugin's MCP server then starts from your clone is not verified yet (open question Q-08). If `dj_status` does not answer, register the engine by hand as below.

On macOS, an app started from the Dock or Finder gets a short `PATH`. Where `uv` sits in `~/.local/bin` or Homebrew's folder, the engine may not start, and a hook that cannot run blocks every write tool. Two fixes, both unverified until the first Mac test (Q-25):

- Link `uv` into `/usr/local/bin`, which apps started from the Dock usually see. In Terminal:

```bash
sudo mkdir -p /usr/local/bin && sudo ln -sf "$(command -v uv)" /usr/local/bin/uv
```

- The plugin starts its engine with its `uv path` option (default `uv`). Set it to the full path `command -v uv` prints (Claude Code: `/plugin configure dj-librarian`). The write-gate hook keeps a bare `uv`, so it needs the link.

If `dj_status` still does not answer, register the engine by hand with the full path to `uv` (below). The plugin's engine also gets no `UV_PROJECT_ENVIRONMENT` from `~/.zshrc`: on a Mac, keep the clone out of cloud-synced folders so uv uses `.venv/` inside it.

Optional: [templates/project/instructions.md](templates/project/instructions.md) is a Cowork Project template you can paste into a new Project's instructions; the plugin works without it.

### The engine on Windows and macOS

The engine is the MCP server `dj-mcp`; it runs on your computer. The plugin starts it for you. To register it in Claude Desktop by hand instead, add it to Claude Desktop's config file:

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
- **Writes.** Direct master.db writes (`dj tree`, `dj apply`, `dj copy` with `--apply`) need `--power-mode` and stay Windows-only; on macOS they refuse with a one-line reason. `dj tidy apply --apply` and `dj tidy undo --apply` write audio files on Windows only in v0.1; on macOS they refuse with a one-line reason (macOS support is planned for v0.2). Their dry-runs only read.

## Documentation

- [docs/requirements.md](docs/requirements.md): numbered requirements (authoritative).
- [docs/architecture.md](docs/architecture.md): plugin architecture and repo layout.
- [docs/decisions.md](docs/decisions.md): decisions and their reasons.
- [docs/plan.md](docs/plan.md): current work items and open questions.
- [docs/lessons.md](docs/lessons.md): what the build has learned about rekordbox, Spotify and audio files.
- [CONTRIBUTING.md](CONTRIBUTING.md): development setup and pull request rules.

## Licence

[Apache-2.0](LICENSE).
