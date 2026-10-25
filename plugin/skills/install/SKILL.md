---
name: install
description: Install the dj-librarian engine (MCP server) on this Mac or Windows PC. Run it in Claude Code; the DJ clicks Allow on each step.
disable-model-invocation: true
---

# Install the dj-librarian engine

The engine install the DJ starts by typing `/dj-librarian:install` in Claude Code (R-102, R-1101, D-29); the card in `dj-start/engine.md` sends them here.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run its pre-send checklist before each reply.

Eight steps; the DJ clicks Allow on every command. Before each step send one line, `Step N of 8 · <what>`, then run it and check its result. On Windows (PowerShell) every `"<uv>" ...` line below starts with `& ` (the call operator): `& "<uv>" sync ...`. Run steps 4, 5 and 7 with `UV_PROJECT_ENVIRONMENT` unset (Mac: `env -u UV_PROJECT_ENVIRONMENT "<uv>" ...`; Windows: `Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue` first), so the engine gets its own `.venv`. Stop at the first failure: show the error line and say "send this line to whoever gave you the plugin". Never edit Claude Desktop's config by hand and never change anything in it except `mcpServers["dj-librarian"]`.

1. **Which computer.** Mac: `uname -s` prints `Darwin`. Windows (PowerShell): `$env:OS` prints `Windows_NT`. Say "Mac path" or "Windows path". Anything else: "This installs on a Mac or a Windows PC only." and stop.

2. **uv.** Mac: `command -v uv || ~/.local/bin/uv --version`. Windows: `& "$env:USERPROFILE\.local\bin\uv.exe" --version`. If neither answers, install it. Mac: `curl -LsSf https://astral.sh/uv/install.sh | sh`. Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`. Then check again. Write down uv's absolute path (Mac: `command -v uv` or `$HOME/.local/bin/uv`; Windows: `%USERPROFILE%\.local\bin\uv.exe`). Every later step uses that path, never a bare `uv`.

3. **The engine folder.** Use `~/dj-librarian` (Windows: `%USERPROFILE%\dj-librarian`). If the home folder is synced (its path holds `OneDrive`, `Dropbox`, `iCloud`, `Mobile Documents` or `CloudStorage`), say so and use `~/Library/dj-librarian` (Windows: `%LOCALAPPDATA%\dj-librarian`). The source is `${CLAUDE_PLUGIN_ROOT}/engine/`. When it is missing, this copy of the plugin carries no engine (the light zip, or a plugin installed from a clone's marketplace): say "This copy of the plugin has no engine inside: upload dj-librarian-plugin-<version>.zip (developers: README, The engine on Windows and macOS)." and stop.
   - The folder exists and its `BUILD.txt` is the same as the source's: copy nothing.
   - It exists but holds neither `BUILD.txt` nor a `pyproject.toml` with `name = "dj-librarian"`: it is not an engine folder. Say so and stop.
   - It exists with another `BUILD.txt`: back it up first. Mac: `cp -R ~/dj-librarian ~/dj-librarian.bak-<YYYY-MM-DD>`. Windows: `Copy-Item -Recurse "$env:USERPROFILE\dj-librarian" "$env:USERPROFILE\dj-librarian.bak-<YYYY-MM-DD>"`. Never over an existing backup: add `-2`.
   - Then copy. Mac: `mkdir -p ~/dj-librarian && cp -R "${CLAUDE_PLUGIN_ROOT}/engine/." ~/dj-librarian/`. Windows: `New-Item -ItemType Directory -Force "$env:USERPROFILE\dj-librarian" | Out-Null; Copy-Item -Recurse -Force "${CLAUDE_PLUGIN_ROOT}/engine/*" "$env:USERPROFILE\dj-librarian"`.

4. **Dependencies.** `"<uv>" sync --directory "<engine folder>" --no-dev`. The first run downloads Python and the packages (a few minutes). Windows, updating an engine Claude Desktop already runs: Windows locks the running `dj-mcp.exe`, so first turn dj-librarian off in Customize → Connectors, and on again after the restart.

5. **The proof.** `"<uv>" run --directory "<engine folder>" --no-sync dj status`. It prints the rekordbox version and the track count. On any error: show it, say "send this line to whoever gave you the plugin", and stop here. Do not go on to the config.

6. **The dj-library folder.** Ask once: "Which folder is your dj-library? Drag it into this chat or paste its path." Check that it holds `library.yaml` (Mac: `test -f "<folder>/library.yaml"`; Windows: `Test-Path "<folder>\library.yaml"`). If it does not, say "That folder has no library.yaml: run session 1 first (say hi in a Cowork task)." and stop.

7. **Claude Desktop's config.** `"<uv>" run --directory "<engine folder>" --no-sync python "<engine folder>/scripts/merge_desktop_config.py" merge --uv "<uv>" --folder "<engine folder>" --library "<dj-library folder>"`. It backs the config up to `claude_desktop_config.json.bak-<date>` first, then adds or replaces only `mcpServers["dj-librarian"]` (with `DJ_LIBRARY` set to the dj-library folder) and keeps every other key. It prints one JSON line: say its `status` (added, replaced, unchanged) and where the backup went. An `error` line: show it and stop.

8. **Restart.** Say: "Restart Claude Desktop. Then in Customize → Connectors → dj-librarian, leave every `_apply`, `_write`, `_undo` tool on Ask every time." End with one line: `say "set me up" in a Cowork task to check it`.

To take the engine out again: `/dj-librarian:uninstall`.

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
