# Engine set-up (M1)

The engine is the dj-librarian MCP server, running on the DJ's own computer. It reads rekordbox's
live database (My Tags, play counts) and runs Spotify and `dj tidy`. It comes inside the plugin
zip, or on its own as `dj-librarian-engine-<version>.mcpb`. The Claude app brings the Python it
needs, so the DJ installs nothing and never opens a terminal. One card, about 3 minutes, then
`dj_status` as the proof (R-102, R-1101, R-1105). Whether the engine starts from inside the plugin
zip is unverified until it has run once (Q-31); the `.mcpb` is the fallback.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by
[shared/adhd.md](../../shared/adhd.md), and run its pre-send checklist before each reply.

## When to offer it

- Only when the DJ says "set me up", or when what they ask for needs live data from their
  computer: My Tags, Spotify, `dj tidy` on the audio files. Never before the first report (R-102).
- `dj_status` is already there when the DJ says "set me up": skip the card, go to the proof.
- Play history: the engine does not read it yet (Q-13). Never promise it.
- In session 1 the only offer is the last line of dj-start step 6. Never push it twice in a row.

## The card

One card for Mac and Windows, in the Claude desktop app and in Cowork. Replace `<engine settings>`
with the row below for how the engine came in before you send it: inside the plugin zip unless the
DJ says they installed the `.mcpb`.

```text
Step 1 of 2 · about 3 minutes. The engine is already in. Point it at your folder, then I check it works:
1. Open <engine settings> and pick your dj-library folder there, the one you connected in Cowork (library.yaml is in it). Leave Power mode off.
2. Spotify client ID and secret: paste them into the same form if you have them, or leave both empty.
3. In the dj-librarian tool permissions, set every tool whose name ends in _apply, _write or _undo to Ask every time (9 tools). Read tools can stay on Allow.
Say done once the form is saved (under a minute).
```

| How the engine came in | `<engine settings>` |
|---|---|
| Inside the plugin zip | Settings > Extensions > dj-librarian engine (not there? say so) |
| The `.mcpb` on its own | Settings > Extensions > dj-librarian engine |

Where a plugin's own engine settings show is unverified (Q-31): Settings > Extensions is where the
fallback puts them, hence "not there? say so". Not there: the fallback under The proof.

The DJ picks the folder in the form by its name. Never send them a path you see in Cowork: that is
where Cowork mounts the folder, not a path on their computer.

Claude Code: send no card. Claude Code 2.1.299 does not start this engine from the plugin (Q-31).
Say so in one line; the report, builds and crates keep running on the XML.

The form has four fields: dj-library folder (required), Spotify client ID, Spotify client secret
(both optional) and Power mode (Windows), off by default. Spotify keys go into that form only,
never into the chat or a `.env`; dj-spotify's card sets up the Spotify app. The 9 write tools are
dj_tree_apply, dj_apply_write, dj_copy_apply, dj_push_apply, dj_build_apply, dj_tidy_apply,
dj_tidy_undo, dj_structure_write and dj_crate_write.

The engine keeps its state in the dj-library folder, under `.cache/engine/` (preview records, the
master.db backups), so an update of the engine loses nothing. The Spotify token stays on the
computer, in `.dj-librarian/.cache/` in the home folder, never in the dj-library folder.

## The proof

When the DJ says done, call `dj_status`. The engine works when it answers with `tracks`. One line,
the number from the tool:

```text
Step 2 of 2 · under a minute. Engine on: dj_status read <tracks> tracks live from your rekordbox.
Next: say what you wanted it for, My Tags, Spotify or tidy (under a minute).
```

When it fails, one matter-of-fact line and the fix, then wait:

- No `dj_status` tool after done: the form is not saved (the engine starts only once the dj-library folder is set), or new tools show only in a new task. Saved: the DJ opens a new Cowork task (or restarts Claude) and says set me up there. Still nothing: the fallback. The DJ gets `dj-librarian-engine-<version>.mcpb` from the release or from whoever is testing with them, drags it onto Settings > Extensions in the Claude desktop app, clicks Install, fills the same form and says set me up in a new Cowork task.
- The settings are not under Settings > Extensions: the engine came inside the plugin and this Claude shows its settings elsewhere or not at all (Q-31), or the plugin is the light zip without the engine. The fallback above puts them there.
- `dj_status` says there is no library folder, or not a dj-library: the form points nowhere or at the wrong folder. Open <engine settings>, pick the folder that holds `library.yaml`, say done.
- `master.db not found`: rekordbox 7 has not run on this computer yet, or keeps its database elsewhere. Open rekordbox once, close it, say done. Still not found: say so plainly; the XML route keeps working.

## The gates

Every write goes preview first, then the DJ's explicit yes, then the write tool with the preview's
`preview_id`. Two gates hold that even if a chat gets it wrong: "Ask every time" on each write tool,
and the XML the DJ imports by hand. Power mode off in the form refuses every master.db write. In
Claude Code the plugin's hook also denies a write tool called without a `preview_id`. The full tool
list with the setting for each is `docs/permissions.md` in the repo.
