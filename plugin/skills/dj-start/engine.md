# Engine install (M1)

The engine is the dj-librarian MCP server, running on the DJ's own computer. It reads rekordbox's
live database (My Tags, play counts) and runs Spotify and `dj tidy`. One card, three steps, about 10
minutes, then `dj_status` as the proof (R-102, R-1101, R-1105).

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by
[shared/adhd.md](../../shared/adhd.md), and run its pre-send checklist before each reply.

## When to offer it

- Only when the DJ says "set me up", or when what they ask for needs live data from their
  computer: My Tags, Spotify, `dj tidy` on the audio files. Never before the first report (R-102).
- Play history: the engine does not read it yet (Q-13). Never promise it.
- In session 1 the only offer is the last line of dj-start step 6. Never push it twice in a row.

## The card

Take the device from `library.yaml` (`device`). Show only the block for that device, never both.
Replace `<your dj-library folder>` with the folder's full path before you send the card.

Mac:

```text
Step 1 of 2 · about 10 minutes. Install the engine in three moves, then I check it works:
1. Install uv: open Terminal, paste curl -LsSf https://astral.sh/uv/install.sh | sh and press Return. Close Terminal and open it again.
2. Get the engine: download the dj-librarian repo (git clone, or Code > Download ZIP and unzip it), cd into that folder in Terminal and run uv sync, then uv run dj library use <your dj-library folder>. Turn on the dj-librarian plugin from that folder (Claude Code: claude plugin marketplace add ./ then claude plugin install dj-librarian@dj-librarian; Cowork: Customize > Plugins) and restart Claude.
3. In the dj-librarian connector's tool permissions, set every write tool to Ask every time: dj_tree_apply, dj_apply_write, dj_copy_apply, dj_push_apply, dj_build_apply, dj_tidy_apply, dj_tidy_undo, dj_structure_write, dj_crate_write. Read tools can stay on Allow.
Say done when Claude is back (under a minute).
```

Windows:

```text
Step 1 of 2 · about 10 minutes. Install the engine in three moves, then I check it works:
1. Install uv: open PowerShell, paste powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" and press Enter. Close PowerShell and open it again.
2. Get the engine: download the dj-librarian repo (git clone, or Code > Download ZIP and unzip it), cd into that folder in PowerShell and run uv sync, then uv run dj library use <your dj-library folder>. Turn on the dj-librarian plugin from that folder (Claude Code: claude plugin marketplace add ./ then claude plugin install dj-librarian@dj-librarian; Cowork: Customize > Plugins) and restart Claude.
3. In the dj-librarian connector's tool permissions, set every write tool to Ask every time: dj_tree_apply, dj_apply_write, dj_copy_apply, dj_push_apply, dj_build_apply, dj_tidy_apply, dj_tidy_undo, dj_structure_write, dj_crate_write. Read tools can stay on Allow.
Say done when Claude is back (under a minute).
```

Until the engine is on PyPI, step 2 is the clone plus `uv sync`; after that it becomes one `uvx` line.
Keep the clone outside cloud-synced folders (Dropbox, iCloud Drive, OneDrive). On Windows you can
instead set `UV_PROJECT_ENVIRONMENT` as CONTRIBUTING.md says. On a Mac the plugin's engine never
sees that setting (Claude does not read `~/.zshrc`): keep the clone out of synced folders, or
register the engine by hand with `env` (README, "The engine on Windows and macOS").

The plugin's `.mcp.json` starts the engine from the folder above the plugin folder (`uv run
--directory <plugin folder>/..`), so it works only while the plugin runs from the clone itself.
Claude Code does that for a plugin from a marketplace added from a local folder (`claude plugin
marketplace add ./` inside the clone): it loads in place. A marketplace added from GitHub, or a
plugin uploaded as a zip, runs from a cached copy with no engine next to it. Which Cowork add path
keeps the plugin in the clone is unverified (Q-08). Until it is, a Cowork DJ whose `dj_status`
does not answer registers the engine by hand in Claude's config file, pointing at the clone
(README, "The engine on Windows and macOS").

## The proof

When the DJ says done, call `dj_status`. The engine works when it answers with `tracks`. One line,
the number from the tool:

```text
Step 2 of 2 · under a minute. Engine on: dj_status read <tracks> tracks live from your rekordbox.
Next: say what you wanted it for, My Tags, Spotify or tidy (under a minute).
```

When it fails, one matter-of-fact line and the fix, then wait:

- No dj_status tool: the plugin is not on, or Claude was not restarted (step 2, last part). If both are done, the plugin runs from a copy: the next line.
- `dj-mcp` not found, or no `pyproject.toml`: the plugin runs from a copy, not from the clone (Q-08). Claude Code: add the marketplace from the clone folder (`claude plugin marketplace add ./`). Cowork: register the engine by hand, README "The engine on Windows and macOS".
- `master.db not found`: rekordbox 7 is not in its usual place. Set `DJ_MASTER_DB` to the master.db path and restart Claude.
- `uv` not found: step 1 did not finish. Open a new Terminal or PowerShell and run `uv --version`. Works there but not in Claude on a Mac: Claude started from the Dock has a short `PATH`; register the engine by hand with the full path `which uv` prints (README).
- No virtual environment, or `dj-mcp` missing although the clone is right: the engine looks for its venv in the clone (`.venv/`). A Mac clone in a synced folder whose venv lives elsewhere: move the clone out, run `uv sync` there, restart Claude.

## The gates

Every write goes preview first, then the DJ's explicit yes, then the write tool with the preview's
`preview_id`. Two gates hold that even if a chat gets it wrong: "Ask every time" on each write tool,
and the XML the DJ imports by hand. In Claude Code the plugin's hook also denies a write tool called
without a `preview_id`. The full tool list with the setting for each is `docs/permissions.md` in the
repo.
