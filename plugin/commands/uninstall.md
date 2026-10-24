---
description: Take the dj-librarian engine out of Claude Desktop's config. The engine folder stays.
disable-model-invocation: true
---

# Take the dj-librarian engine out

Three steps; the DJ clicks Allow on each. Before each command send one line, `Step N of 3 · <what>`. On Windows (PowerShell) a `"<uv>" ...` line starts with `& ` (the call operator). Stop at the first failure and show the error line. Change nothing in Claude Desktop's config but `mcpServers["dj-librarian"]`; delete no folder.

1. **uv.** Mac: `command -v uv || ~/.local/bin/uv --version`. Windows (PowerShell): `& "$env:USERPROFILE\.local\bin\uv.exe" --version`. No uv: say "The engine was never installed here, so there is nothing to take out." and stop.

2. **The config.** `"<uv>" run --no-project python "<engine folder>/scripts/merge_desktop_config.py" remove`, where the engine folder is the one the install used (`~/dj-librarian`, or `~/Library/dj-librarian` / `%LOCALAPPDATA%\dj-librarian`). That folder gone: the same script from `${CLAUDE_PLUGIN_ROOT}/engine/scripts/merge_desktop_config.py`. It backs the config up to `claude_desktop_config.json.bak-<date>` first and takes out only the `dj-librarian` entry. It prints one JSON line: say its `status` (removed, absent) and where the backup went.

3. **Restart.** Say: "Restart Claude Desktop. The engine folder and your dj-library folder are untouched; delete the engine folder yourself if you want it gone."
