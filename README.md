# dj-librarian

A DJ librarian for rekordbox that you talk to through Claude.
It syncs Spotify playlists into rekordbox crates, builds playlist folders from a YAML file, copies playlists to Spotify, and tidies the tags of your audio files.
rekordbox stays the source of truth: the tool only ever proposes and adds.

Status: early (0.1.0, unreleased). Windows is the tested platform. macOS is ported (process check, master.db location) but not yet confirmed against a live rekordbox on a Mac.

## Safety model

- **Create and add only.** Nothing that exists in rekordbox, on Spotify or on disk is ever deleted, renamed, moved or reordered.
- **Dry-run is the default.** Every command shows what it would do and writes nothing. Real writes need `--apply`.
- **Preview, then yes.** Through Claude, every write tool has a preview tool, and Claude asks you before it writes. Silence is not a yes.
- **Import, don't inject.** The default write path is a rekordbox XML file that you import yourself. Direct writes to rekordbox's `master.db` are a Windows power mode: rekordbox must be closed, a verified backup is taken first, everything lands in one commit, and any error rolls back. Until the XML writer lands, today's `--apply` commands use this power mode.
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
| `uv run dj tree --apply` | Creates the missing folders and playlists. rekordbox closed, backup first, one commit. |
| `uv run dj pull <link>` / `--all` | Reads a Spotify playlist into `inbox/`. Read-only. |
| `uv run dj match <link>` | Matches the inbox against your library: `IN_CRATE`, `PROPOSE`, `AMBIGUOUS`, `MISSING`, `DECLINED`. |
| `uv run dj plan <link>` | Writes a plan file and a wishlist. You set `decision: yes\|no` per item. |
| `uv run dj apply <plan> [--apply]` | Dry-run, then appends the approved tracks to the crate. |
| `uv run dj copy "<src>" "<dst>" [--apply]` | Appends the tracks of one rekordbox playlist to another. The source is only read. |
| `uv run dj push "<playlist>" [--apply]` | Mirrors a rekordbox playlist into a private Spotify playlist. Adds only. |
| `uv run dj build <tracklist.txt> [--apply]` | Turns an `Artist - Title` text tracklist into a private Spotify playlist. |
| `uv run dj analyze` | Read-only census of your Spotify library into Markdown reports. |
| `uv run dj tidy audit <crate>` / `--all` / `--folder D` | Read-only hygiene audit of the audio files: tags, artwork, names, CDJ playability, duplicates. |
| `uv run dj tidy plan <target>` | Proposes values for EMPTY tags, parsed from the file names. |
| `uv run dj tidy apply <plan> [--apply]` | Writes approved tags (undo record first). Then Reload Tag in rekordbox. |
| `uv run dj tidy undo <plan> [--apply]` | Restores what that apply changed. |

Every command takes `--json`. Exit codes: `0` ok, `1` error or conflict, `2` rekordbox is running (writes refused).

## Configuration

Your own configuration lives next to the code and is gitignored. Copy what you need from [examples/](examples/):

| Example | Copy to | Used by |
|---|---|---|
| `examples/.env.example` | `.env` | Spotify commands. Create an app at the Spotify developer dashboard with redirect URI `http://127.0.0.1:8888/callback`. |
| `examples/links.example.yaml` | `links.yaml` | `pull`, `match`, `plan`: pairs a Spotify playlist with a rekordbox crate. |
| `examples/tree.example.yaml` | `tree.yaml` | `dj tree`: the playlist tree you want. |
| `examples/bases.example.yaml` | `bases.yaml` | `dj tree --file bases.yaml`: one folder per genre, same shape. |
| `examples/tidy.example.yaml` | `tidy.yaml` | `dj tidy`: your music roots, naming rule and CDJ profiles. File writes are limited to the roots. |

## Claude plugin

The plugin adds two skills (`dj-sync`, `dj-tidy`) and an MCP server with a fixed list of `dj` tools. Read tools and write tools are separate, so you can leave every write tool on "ask every time".

- **Claude desktop app:** Customize → Plugins → Add → Add marketplace, then enter this repository's GitHub URL. The plugin's MCP server runs on your computer and needs the clone and `uv sync` from the install step.
- **Claude Code:**

```bash
claude plugin marketplace add OWNER/dj-librarian
```

```bash
claude plugin install dj-librarian@dj-librarian
```

On Claude Code 2.1.275 or later, one step also works: `/plugin install dj-librarian --marketplace OWNER/dj-librarian`.

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
- **Writes.** Direct master.db writes (`dj tree`, `dj apply`, `dj copy` with `--apply`) stay Windows-only; on macOS they refuse with a one-line reason. `dj tidy apply --apply` and `dj tidy undo --apply` write audio files on Windows only in v0.1; on macOS they refuse with a one-line reason (macOS support is planned for v0.2). Their dry-runs only read.

## Documentation

- [docs/requirements.md](docs/requirements.md): numbered requirements (authoritative).
- [docs/architecture.md](docs/architecture.md): plugin architecture and repo layout.
- [docs/decisions.md](docs/decisions.md): decisions and their reasons.
- [docs/plan.md](docs/plan.md): current work items and open questions.
- [docs/lessons.md](docs/lessons.md): what the build has learned about rekordbox, Spotify and audio files.
- [CONTRIBUTING.md](CONTRIBUTING.md): development setup and pull request rules.

## Licence

[Apache-2.0](LICENSE).
