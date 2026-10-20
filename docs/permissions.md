# Tool permissions

Which dj-librarian MCP tools read, which write text files in your library folder, and which write to
rekordbox, Spotify or your audio files, with the setting we recommend for each (R-1101, R-1105, C-10).

## The two gates

A write needs a preview, then your explicit yes, then the write tool with the preview's `preview_id`
(R-1102). The engine refuses a write without a valid id. On top of that:

| Where | Gate 1 | Gate 2 |
|---|---|---|
| Cowork / Claude desktop app | Every write tool on **Ask every time**: Claude cannot write without you clicking Allow. | The default write path is a rekordbox XML you import yourself (`dj_structure_write`). Nothing reaches rekordbox until you import it. |
| Claude Code | The same: write tools on ask (see the settings below). | Plus the plugin's PreToolUse hook (`plugin/hooks/`): a write tool called without a `preview_id` is denied before it runs. |

Plugin hooks are not a Cowork component (C-10, Q-03), so in Cowork the permission setting is the
hard gate. Direct master.db writes (`dj_tree_apply`, `dj_apply_write`, `dj_copy_apply`) are a
Windows power mode on top: they also need `power_mode=true` (R-205).

## Read tools: Allow (or Ask, your call)

| Tool | What it does |
|---|---|
| `dj_status` | Track count, playlist tree, links. Reads a snapshot of master.db. |
| `dj_library_inspect` | Library summary from an XML export or a master.db snapshot. |
| `dj_match` | Matches the last Spotify pull against the library. |
| `dj_pull` | Reads a Spotify playlist into `inbox/` (read-only on Spotify). |
| `dj_tree_preview` | Dry-run of a tree file; returns a `preview_id`. |
| `dj_apply_preview` | Dry-run of a sync plan; returns a `preview_id`. |
| `dj_copy_preview` | Dry-run of a playlist copy; returns a `preview_id`. |
| `dj_push_preview` | Dry-run of a push to Spotify; returns a `preview_id`. |
| `dj_build_preview` | Dry-run of a tracklist to Spotify; returns a `preview_id`. |
| `dj_tidy_audit` | Hygiene audit of the audio files; writes a report only. |
| `dj_tidy_dupes` | Duplicate report; never deletes. |
| `dj_tidy_apply_preview` | Dry-run of a tidy plan; returns a `preview_id`. |
| `dj_tidy_undo_preview` | Dry-run of a tidy undo; returns a `preview_id`. |
| `dj_crate_preview` | Dry-run of a crate from a spec; returns a `preview_id`. |

## Library-text tools: Allow or Ask

These write text files in your `dj-library/` folder or the repo (plans, analysis, proposals), never
rekordbox, Spotify or audio files.

| Tool | What it writes |
|---|---|
| `dj_plan` | A sync plan and a wishlist (`plans/`, `wishlist/`). |
| `dj_tidy_plan` | A tidy plan (`plans/`). |
| `dj_library_analyze` | profile/, structure/, taste/ and the HTML report. |
| `dj_structure_preview` | `proposals/<slug>.yaml` and a preview record; returns a `preview_id`. |
| `dj_barber_next` | Plans or resumes a Style Barber session (`.cache/barber.json`); returns the next question. |
| `dj_barber_record` | Appends the DJ's answer as a dated line to `taste/*.md` (never rewrites). |
| `dj_wishlist_shop` | `wishlist/<crate>.shopping.md`: search links for the missing tracks (never fetched). |

## Write tools: Ask every time

| Tool | Writes to | Its preview |
|---|---|---|
| `dj_structure_write` | `proposals/<slug>.xml`, a rekordbox XML you import | `dj_structure_preview` |
| `dj_crate_write` | `proposals/crate-<slug>.xml` (a rekordbox XML you import) and `crates/<slug>.md` | `dj_crate_preview` |
| `dj_tree_apply` | rekordbox master.db (power mode, Windows) | `dj_tree_preview` |
| `dj_apply_write` | rekordbox master.db (power mode, Windows) | `dj_apply_preview` |
| `dj_copy_apply` | rekordbox master.db (power mode, Windows) | `dj_copy_preview` |
| `dj_push_apply` | Spotify (a private playlist, adds only) | `dj_push_preview` |
| `dj_build_apply` | Spotify (a private playlist, adds only) | `dj_build_preview` |
| `dj_tidy_apply` | your audio files' tags and names (undo record first) | `dj_tidy_apply_preview` |
| `dj_tidy_undo` | your audio files' tags and names (restores them) | `dj_tidy_undo_preview` |

Every write tool's name ends in `_apply`, `_write` or `_undo`; no read or library-text tool's does.
That is the pattern the Claude Code hook matches.

These are the tools the engine has today. Crate me adds `dj_crate_preview` (a read tool) and
`dj_crate_write` (a write tool: Ask every time) when it ships; the hook already matches the
write tool's name.

## Where to set it

- **Cowork / Claude desktop app:** open the dj-librarian connector's tool permissions and set each
  write tool above to Ask every time. Read tools can stay on Allow.
- **Claude Code:** put the write tools under `ask` in your settings (`~/.claude/settings.json`).
  The plugin's tools are named `mcp__plugin_dj-librarian_dj-librarian__<tool>`; a server you
  registered by hand as `dj-librarian` is `mcp__dj-librarian__<tool>`.

```json
{
  "permissions": {
    "ask": [
      "mcp__plugin_dj-librarian_dj-librarian__dj_structure_write",
      "mcp__plugin_dj-librarian_dj-librarian__dj_crate_write",
      "mcp__plugin_dj-librarian_dj-librarian__dj_tree_apply",
      "mcp__plugin_dj-librarian_dj-librarian__dj_apply_write",
      "mcp__plugin_dj-librarian_dj-librarian__dj_copy_apply",
      "mcp__plugin_dj-librarian_dj-librarian__dj_push_apply",
      "mcp__plugin_dj-librarian_dj-librarian__dj_build_apply",
      "mcp__plugin_dj-librarian_dj-librarian__dj_tidy_apply",
      "mcp__plugin_dj-librarian_dj-librarian__dj_tidy_undo"
    ]
  }
}
```

## The hook (Claude Code)

`plugin/hooks/hooks.json` runs `plugin/hooks/gate.py` before every tool whose full name matches
`^mcp__(plugin_dj-librarian_dj-librarian|dj-librarian)__[A-Za-z0-9_]+_(apply|write|undo)$`. It denies
the call when `preview_id` is missing or is not 12 lower-case hex digits, and lets everything else
through silently. It runs through `uv` (no system Python needed) and fails closed on Claude Code
2.1.295 or later (`onFailure: "block"`): if `uv` is missing, the script crashes or it times out, the
write is blocked. An older Claude Code has no `onFailure`: there a hook that cannot run may let the
call through, and ask-every-time and the engine's own preview-id check are the gates left.

The hook has run in tests and from a terminal, not yet inside a live Claude Code session with the
plugin installed (R-1105 asks for that run).
