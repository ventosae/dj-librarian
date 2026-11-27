# Tool permissions

Which dj-librarian MCP tools read, which write files in your library folder, and which write to
rekordbox, Spotify or your audio files, with the setting we recommend for each (R-1101, R-1105, C-10).

## The two gates

A write needs a preview, then your explicit yes, then the write tool with the preview's `preview_id`
(R-1102). One preview, one write: the engine refuses a write without a valid id, or with one that
was used already. On top of that:

| Where | Gate 1 | Gate 2 |
|---|---|---|
| Cowork / Claude desktop app | Every write tool on **Ask every time**: Claude cannot write without you clicking Allow. | The engine's own chain before it touches rekordbox: rekordbox not running, a verified backup, one transaction, rollback on any failure. |
| Claude Code | The same: write tools on ask (see the settings below). | Plus the plugin's PreToolUse hook (`plugin/hooks/`): a write tool called without a `preview_id` is denied before it runs. |

Plugin hooks are not a Cowork component (C-10, Q-03), so in Cowork the permission setting is the
hard gate. The rekordbox write tools (`dj_tree_apply`, `dj_apply_write`, `dj_copy_apply`,
`dj_structure_write`, `dj_crate_write`) write straight into rekordbox's database, on a Mac and on
Windows alike. They refuse while rekordbox runs (process `rekordbox` on a Mac, `rekordbox.exe` on
Windows), and also when that check cannot run. `DJ_POWER_MODE=false` in the engine's environment is
the one off switch: it refuses every rekordbox write whatever the call says.

## Read tools: Allow (or Ask, your call)

| Tool | What it does |
|---|---|
| `dj_status` | Track count, playlist tree, links. Reads a snapshot of master.db. |
| `dj_library_inspect` | Library summary from a master.db snapshot. |
| `dj_query` | One `SELECT` on your catalog (`catalog/catalog.db`), read-only, 200 rows a page. |
| `dj_match` | Matches the last Spotify pull against the library. |
| `dj_pull` | Reads a Spotify playlist into `.cache/inbox/` in your dj-library folder. Read-only on Spotify. |
| `dj_tree_preview` | Dry-run of a tree file; returns a `preview_id`. |
| `dj_apply_preview` | Dry-run of a sync plan; returns a `preview_id`. |
| `dj_copy_preview` | Dry-run of a playlist copy; returns a `preview_id`. |
| `dj_push_preview` | Dry-run of a push to Spotify; returns a `preview_id`. |
| `dj_build_preview` | Dry-run of a tracklist to Spotify; returns a `preview_id`. |
| `dj_crate_preview` | Dry-run of a crate from a spec; returns a `preview_id`. |
| `dj_tidy_dupes` | Duplicate report; never deletes. |
| `dj_tidy_apply_preview` | Dry-run of a tidy plan; returns a `preview_id`. |
| `dj_tidy_undo_preview` | Dry-run of a tidy undo; returns a `preview_id`. |

## Library-text tools: Allow or Ask

These write files in your `dj-library/` folder (plans, analysis, proposals, the catalog), never
rekordbox, Spotify or audio files.

| Tool | What it writes |
|---|---|
| `dj_library_analyze` | Reads a master.db snapshot, then writes profile/ (with identity.json and sleeve.svg), structure/, taste/, the proposals, the HTML report, and the catalog (`catalog/catalog.db`, `catalog/tracks.csv`). |
| `dj_library_report` | Renders the HTML report again from the files in profile/, structure/ and taste/. |
| `dj_structure_preview` | `proposals/<slug>.yaml` and a preview record; returns a `preview_id`. |
| `dj_note` | One note on a track (field, value, source, date) in the catalog's `notes` table; notes survive every rebuild. |
| `dj_match_tracks` | Matches "Artist - Title" candidates against the library: owned ids, and the missing ones with store search links. With a crate it writes `crates/<slug>.to-buy.md`. |
| `dj_plan` | A sync plan and a wishlist (`plans/`, `wishlist/`). |
| `dj_wishlist_shop` | `wishlist/<crate>.shopping.md`: search links for the missing tracks (never fetched). |
| `dj_tidy_plan` | A tidy plan (`plans/`). |
| `dj_tidy_audit` | An audit report of the audio files (`reports/tidy/`); the files are only read. |
| `dj_barber_next` | Plans or resumes a Style Barber session (`.cache/barber.json`); returns the next question. |
| `dj_barber_record` | Appends the DJ's answer as a dated line to `taste/*.md` (never rewrites). |

## The backup tool: Allow or Ask

`dj_backup` is the one write tool without a preview id (D-31): it writes only under
`<dj-library>/backups/`, never touches rekordbox, and the hook does not match it.

| Tool | What it writes |
|---|---|
| `dj_backup` | `backups/rekordbox-<date>/`: a verified copy of rekordbox's database (`master.db`, `-wal`, `-shm`, `masterPlaylists6.xml`) with `manifest.json` and `RESTORE.md`. Reads rekordbox's folder, never writes it. Nothing is copied when nothing changed; no backup is ever deleted. |

## Write tools: Ask every time

| Tool | Writes to | Its preview |
|---|---|---|
| `dj_structure_write` | rekordbox: the folders and playlists of a structure proposal | `dj_structure_preview` |
| `dj_crate_write` | rekordbox: one crate playlist, and its record `crates/<slug>.md` | `dj_crate_preview` |
| `dj_tree_apply` | rekordbox: the missing folders and playlists of a tree file | `dj_tree_preview` |
| `dj_apply_write` | rekordbox: the approved tracks of a sync plan, appended to the crate | `dj_apply_preview` |
| `dj_copy_apply` | rekordbox: the tracks of one playlist, appended to another | `dj_copy_preview` |
| `dj_push_apply` | Spotify (a private playlist, adds only) | `dj_push_preview` |
| `dj_build_apply` | Spotify (a private playlist, adds only) | `dj_build_preview` |
| `dj_tidy_apply` | your audio files' tags and names (undo record first) | `dj_tidy_apply_preview` |
| `dj_tidy_undo` | your audio files' tags and names (restores them) | `dj_tidy_undo_preview` |

Every rekordbox write: rekordbox closed, a verified backup first, one transaction, adds only.
Every write tool's name ends in `_apply`, `_write` or `_undo`; no read or library-text tool's does.
That is the pattern the Claude Code hook matches.

## File and folder arguments

A tool takes a file inside your dj-library folder or the repo, never anywhere else. One exception:
`dj_tidy_audit`, `dj_tidy_dupes` and `dj_tidy_plan` take a music `folder`, which must sit inside the
`roots:` of your `tidy.yaml`; audio file writes (`dj_tidy_apply`, `dj_tidy_undo`) stay inside those
roots too.

## Where to set it

- **Cowork / Claude desktop app:** open the dj-librarian connector's tool permissions
  (**Customize → Connectors → dj-librarian**) and set each write tool above to Ask every time. Read
  tools can stay on Allow.
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
through silently. It runs through `uv` and fails closed on Claude Code 2.1.295 or later
(`onFailure: "block"`): if `uv` is missing, the script crashes or it times out, the write is
blocked. An older Claude Code has no `onFailure`: there a hook that cannot run may let the call
through, and ask-every-time and the engine's own preview-id check are the gates left.
The hook starts a bare `uv`: where `uv` is not on the PATH, Claude Code refuses every write tool (a
known gap).

The hook has run in tests and from a terminal, not yet inside a live Claude Code session with the
plugin installed (R-1105 asks for that run).
