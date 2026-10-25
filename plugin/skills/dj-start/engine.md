# Engine set-up (M1)

The engine is the dj-librarian MCP server, running on the DJ's own computer. It reads rekordbox's
live database (My Tags, play counts) and runs Spotify and `dj tidy`. The plugin zip carries its
source; `/dj-librarian:install`, typed in the Code tab of the Claude desktop app, installs it while
the DJ clicks Allow on each step (D-29). The DJ types nothing else and opens no terminal of their
own. One card, about 5 minutes, then `dj_status` as the proof (R-102, R-1101, R-1105). The command
is unverified on a Mac until it has run there (Q-32); the second route is the
`dj-librarian-engine-<version>.mcpb` desktop extension (Q-31).

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by
[shared/adhd.md](../../shared/adhd.md), and run its pre-send checklist before each reply.

## When to offer it

- Only when the DJ says "set me up", or when what they ask for needs live data from their
  computer: My Tags, Spotify, `dj tidy` on the audio files. Never before the first report (R-102).
- `dj_status` is already there when the DJ says "set me up": skip the card, go to the proof.
- Play history: the engine does not read it yet (Q-13). Never promise it.
- In session 1 the only offer is the last line of dj-start step 6. Never push it twice in a row.

## The card

One card for Mac and Windows. The command is the DJ's to type: it never runs on its own.

```text
Step 1 of 2 · about 5 minutes. The engine installs from Claude Code; you click Allow:
1. In the Claude desktop app, open the Code tab and type /dj-librarian:install.
2. Click Allow on each step. When it asks which folder should be your dj-library, say ok for the one it offers or drag another in.
3. Restart Claude, then in Customize > Connectors > dj-librarian set every tool whose name ends in _apply, _write or _undo to Ask every time (9 tools).
Say set me up in a new Cowork task when Claude is back (under a minute).
```

The DJ gives the folder by dragging it in, or by its path on their computer. Never send them a path
you see in Cowork: that is where Cowork mounts the folder, not a path on their computer.

The 9 write tools are dj_tree_apply, dj_apply_write, dj_copy_apply, dj_push_apply, dj_build_apply,
dj_tidy_apply, dj_tidy_undo, dj_structure_write and dj_crate_write. Read tools can stay on Allow.

Spotify keys: with the install command they go in a `.env` file in the engine folder (`dj-librarian`
in the home folder, never the dj-library folder, which may sync); with the
desktop extension, in its settings form (dj-library folder, Spotify client ID, Spotify client secret,
Power mode (Windows)). Never into the chat; dj-spotify's card sets up the Spotify app.

State: with the install command the engine keeps its state in its own folder (`dj-librarian` in the
home folder: preview records, master.db backups, the Spotify token), and a new install backs that
folder up first. The desktop extension keeps it in the dj-library folder under `.cache/engine/`,
the Spotify token in `.dj-librarian/.cache/` in the home folder.

## The proof

When the DJ says set me up again, call `dj_status`. The engine works when it answers with `tracks`.
One line, the number from the tool:

```text
Step 2 of 2 · under a minute. Engine on: dj_status read <tracks> tracks live from your rekordbox.
Next: say what you wanted it for, My Tags, Spotify or tidy (under a minute).
```

When it fails, one matter-of-fact line and the fix, then wait:

- No `dj_status` tool: the install did not finish, or Claude was not restarted. Restart Claude and say set me up in a new Cowork task. Still nothing: type /dj-librarian:install in the Code tab again; it stops at the step that fails and shows one line.
- The command stopped with an error line: the DJ sends that line to whoever gave them the plugin. Meanwhile the second route: drag `dj-librarian-engine-<version>.mcpb` (from the release or from whoever is testing with them) onto Settings > Extensions, click Install, fill the form, say set me up in a new Cowork task (Q-31).
- `dj_status` says there is no library folder, or not a dj-library: type /dj-librarian:install again and give the folder that holds `library.yaml` (the extension: pick it in its settings form).
- Claude Code knows no /dj-librarian:install: the plugin is the light zip. Upload `dj-librarian-plugin-<version>.zip` (Customize > Plugins), then type the command again.
- `master.db not found`: rekordbox 7 has not run on this computer yet, or keeps its database elsewhere. Open rekordbox once, close it, say set me up. Still not found: say so plainly; the XML route keeps working.

## The gates

Every write goes preview first, then the DJ's explicit yes, then the write tool with the preview's
`preview_id`. Two gates hold that even if a chat gets it wrong: "Ask every time" on each write tool,
and the XML the DJ imports by hand. Master.db writes also need power mode (Windows only). In Claude
Code the plugin's hook also denies a write tool called without a `preview_id`. The full tool list
with the setting for each is `docs/permissions.md` in the repo.
