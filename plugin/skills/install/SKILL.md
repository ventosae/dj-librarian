---
name: install
description: Install the dj-librarian engine on this Mac or Windows PC, take it out again, or back up the rekordbox database. Run it in Claude Code (the Code tab); the DJ clicks Allow on each step.
disable-model-invocation: true
---

## How to reply
1. First line is the answer or the next move. No greeting, no recap, no sign-off.
2. A working DJ talking to a DJ, first person: "I matched 41 of 48." Blunt, no hype. Booth words (crate, set, floor), never developer words.
3. Say where we are in one line: "Step 2 of 4".
4. Number the steps, one action each, with a real time: "about 2 minutes".
5. One question per reply, with choices to tap.
6. Lists stop at 5. The rest goes in a file; name the file.
7. Every number comes from the tool. Not measured, not said.
8. Taste is the DJ's call: versions, keepers, deletions. Offer, don't pick.
9. Errors in one line: what failed, what happens next. No apology.
10. End with one thing the DJ can do in under 2 minutes. Nothing is written to rekordbox, Spotify or audio files without a preview and a yes.

## Which part

The DJ typed `/dj-librarian:install` in the Code tab of the Claude desktop app. What they typed after it picks the part: nothing = **Install**; `uninstall` = **Uninstall**; `backup` = **Backup**.

For every part: the DJ clicks Allow on every command. Before each step send one line, `Step N of 8 · <what>` (of 3 for Uninstall), then run it and check its result. Stop at the first failure: show the error line and say "send this line to whoever gave you the plugin". On Windows (PowerShell) every `"<uv>" ...` line below starts with `& ` (the call operator): `& "<uv>" sync ...`. Never edit Claude Desktop's config by hand, and never change anything in it except `mcpServers["dj-librarian"]`. Delete no folder.

## Install: 8 steps, about 10 minutes

Run steps 4 to 7 with `UV_PROJECT_ENVIRONMENT` unset (Mac: `env -u UV_PROJECT_ENVIRONMENT "<uv>" ...`; Windows: `Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue` first), so the engine gets its own `.venv`.

1. **Which computer.** Mac: `uname -s` prints `Darwin`. Windows (PowerShell): `$env:OS` prints `Windows_NT`. Say "Mac path" or "Windows path". Anything else: "This installs on a Mac or a Windows PC only." and stop.

2. **uv.** Mac: `command -v uv || ~/.local/bin/uv --version`. Windows: `& "$env:USERPROFILE\.local\bin\uv.exe" --version`. Neither answers: install it. Mac: `curl -LsSf https://astral.sh/uv/install.sh | sh`. Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`. Then check again. Write down uv's absolute path (Mac: `command -v uv` or `$HOME/.local/bin/uv`; Windows: `%USERPROFILE%\.local\bin\uv.exe`). Every later step uses that path, never a bare `uv`.

3. **The engine folder.** Use `~/dj-librarian` (Windows: `%USERPROFILE%\dj-librarian`). The home folder is synced (its path holds `OneDrive`, `Dropbox`, `iCloud`, `Mobile Documents` or `CloudStorage`): say so and use `~/Library/dj-librarian` (Windows: `%LOCALAPPDATA%\dj-librarian`). The source is `${CLAUDE_PLUGIN_ROOT}/engine/`. It is missing: say "This copy of the plugin has no engine inside: upload dj-librarian-plugin-<version>.zip and type the command again." and stop.
   - The folder exists and its `BUILD.txt` is the same as the source's: copy nothing.
   - It exists but holds neither `BUILD.txt` nor a `pyproject.toml` with `name = "dj-librarian"`: it is not an engine folder. Say so and stop.
   - It exists with another `BUILD.txt`: back it up first. Mac: `cp -R ~/dj-librarian ~/dj-librarian.bak-<YYYY-MM-DD>`. Windows: `Copy-Item -Recurse "$env:USERPROFILE\dj-librarian" "$env:USERPROFILE\dj-librarian.bak-<YYYY-MM-DD>"`. Never over an existing backup: add `-2`.
   - Then copy. Mac: `mkdir -p ~/dj-librarian && cp -R "${CLAUDE_PLUGIN_ROOT}/engine/." ~/dj-librarian/`. Windows: `New-Item -ItemType Directory -Force "$env:USERPROFILE\dj-librarian" | Out-Null; Copy-Item -Recurse -Force "${CLAUDE_PLUGIN_ROOT}/engine/*" "$env:USERPROFILE\dj-librarian"`.

4. **Dependencies.** `"<uv>" sync --directory "<engine folder>" --no-dev`. The first run downloads Python and the packages (a few minutes). Windows, updating an engine Claude Desktop already runs: Windows locks the running `dj-mcp.exe`, so first turn dj-librarian off in Customize → Connectors, and on again after the restart.

5. **The proof.** `"<uv>" run --directory "<engine folder>" --no-sync dj status`. It prints the rekordbox version and the track count. On any error: show it, say "send this line to whoever gave you the plugin", and stop here. Do not go on to the config.

6. **The dj-library folder and its first backup.** Ask once: "Which folder should be your dj-library? Drag one in or paste a path. If it doesn't exist I make it." Offer `~/Music/dj-library` (Windows: `%USERPROFILE%\Music\dj-library`) as the default: "Or say ok for <that path>." Then `"<uv>" run --directory "<engine folder>" --no-sync python "<engine folder>/scripts/library_init.py" --folder "<folder>" --device <mac|windows>`, the device from step 1. It makes a missing folder, sets up an empty one, keeps one that already holds `library.yaml` as it is, and refuses a folder with other files in it or one inside OneDrive, Dropbox, iCloud or Google Drive (the rule of step 3). It prints one JSON line: say its `status` (created, existing). An `error` line: show it, ask for another folder once, and stop if that one is refused too. Then the backup command of the Backup part below, and its line.

7. **Claude Desktop's config.** `"<uv>" run --directory "<engine folder>" --no-sync python "<engine folder>/scripts/merge_desktop_config.py" merge --uv "<uv>" --folder "<engine folder>" --library "<dj-library folder>"`. It backs the config up to `claude_desktop_config.json.bak-<date>` first, then adds or replaces only `mcpServers["dj-librarian"]` (with `DJ_LIBRARY` set to the dj-library folder) and keeps every other key. It prints one JSON line: say its `status` (added, replaced, unchanged) and where the backup went. An `error` line: show it and stop.

8. **Restart.** Say: "Restart Claude Desktop. Then in Customize → Connectors → dj-librarian, leave every `_apply`, `_write` and `_undo` tool on Ask every time. Anything written into rekordbox goes in only after a preview, your yes and a backup, and only while rekordbox is closed." End with one line: `In a Cowork task, say /dj-librarian:dj-start`.

Spotify keys are not part of the install: the dj-spotify skill sets them up when the DJ asks for Spotify, in a `.env` file in the engine folder, never in the chat.

## Uninstall: 3 steps

The DJ typed `/dj-librarian:install uninstall`.

1. **uv.** Mac: `command -v uv || ~/.local/bin/uv --version`. Windows (PowerShell): `& "$env:USERPROFILE\.local\bin\uv.exe" --version`. No uv: say "The engine was never installed here, so there is nothing to take out." and stop.

2. **The config.** `"<uv>" run --no-project python "<engine folder>/scripts/merge_desktop_config.py" remove`, where the engine folder is the one the install used (`~/dj-librarian`, or `~/Library/dj-librarian` / `%LOCALAPPDATA%\dj-librarian`). That folder is gone: the same script from `${CLAUDE_PLUGIN_ROOT}/engine/scripts/merge_desktop_config.py`. It backs the config up to `claude_desktop_config.json.bak-<date>` first and takes out only the `dj-librarian` entry. It prints one JSON line: say its `status` (removed, absent) and where the backup went.

3. **Restart.** Say: "Restart Claude Desktop. The engine folder and your dj-library folder are untouched, backups included; delete the engine folder yourself if you want it gone."

## Backup

A verified copy of the rekordbox database in the DJ's dj-library folder. It reads rekordbox's folder and writes only under `backups/` in the dj-library folder; it never changes rekordbox and never deletes a backup.

One step. The engine's tools are in the session: `dj_backup()`. In the Code tab without them: `"<uv>" run --directory "<engine folder>" --no-sync dj backup --library "<dj-library folder>"`. Then show its line as it is, one of:

- `Backup: <path> · <size> · verified`: done. Name the folder, and say `RESTORE.md` in it has the steps back.
- `Backup: unchanged since <date> · <path>`: nothing changed since that copy; nothing new was written.
- `... NOT verified (...)`: the copy was kept and flagged. During the install: say it and go on (the next backup runs before the first write). Otherwise ask them to close rekordbox, then run it again.

`dj_backup(list_backups=true)` (the command with `--list`) lists every backup with its date, whether it verified, its size, and the total. A refusal names its reason: a dj-library inside OneDrive, Dropbox, iCloud or Google Drive, or no dj-library set up yet (run the install first). Say once: "Analysis files and artwork are not in it: rekordbox's File > Library > Backup Library covers those." To restore, the DJ follows `RESTORE.md` by hand; the tool never restores.

Reply rules adapted from the i-have-adhd skill by ayghri (MIT licence).
