---
name: uninstall
description: Take the dj-librarian engine out of Claude Desktop's config. The engine folder stays.
disable-model-invocation: true
---

# Take the dj-librarian engine out

The DJ starts it by typing `/dj-librarian:uninstall` in Claude Code (R-1101, D-29).

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run its pre-send checklist before each reply.

Three steps; the DJ clicks Allow on each. Before each command send one line, `Step N of 3 · <what>`. On Windows (PowerShell) a `"<uv>" ...` line starts with `& ` (the call operator). Stop at the first failure and show the error line. Change nothing in Claude Desktop's config but `mcpServers["dj-librarian"]`; delete no folder.

1. **uv.** Mac: `command -v uv || ~/.local/bin/uv --version`. Windows (PowerShell): `& "$env:USERPROFILE\.local\bin\uv.exe" --version`. No uv: say "The engine was never installed here, so there is nothing to take out." and stop.

2. **The config.** `"<uv>" run --no-project python "<engine folder>/scripts/merge_desktop_config.py" remove`, where the engine folder is the one the install used (`~/dj-librarian`, or `~/Library/dj-librarian` / `%LOCALAPPDATA%\dj-librarian`). That folder gone: the same script from `${CLAUDE_PLUGIN_ROOT}/engine/scripts/merge_desktop_config.py`. It backs the config up to `claude_desktop_config.json.bak-<date>` first and takes out only the `dj-librarian` entry. It prints one JSON line: say its `status` (removed, absent) and where the backup went.

3. **Restart.** Say: "Restart Claude Desktop. The engine folder and your dj-library folder are untouched; delete the engine folder yourself if you want it gone."

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
