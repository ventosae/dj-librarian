# dj-librarian

A DJ librarian for rekordbox you talk to through Claude. Python core (`dj` CLI, `dj-mcp` MCP server) + a Claude plugin (`plugin/`). rekordbox is the source of truth; this tool only ever proposes and adds.

Read before changing anything: `docs/requirements.md` (numbered R-ids; authoritative), `docs/plan.md` (current work items), `docs/decisions.md`, `docs/architecture.md`. Every PR cites the R-ids it satisfies.

## Hard rules

1. Create and add only. Never delete, rename, move or reorder anything that exists in rekordbox, Spotify or on disk.
   Two exceptions (D-20, `docs/permissions.md`):
   - `dj tidy` renames audio files within their own folder only on the DJ's explicit request, after an undo record is written, with a Relocate list for rekordbox.
   - Tools that write or append the DJ's own text files in the library folder (analysis, `dj_plan`, `dj_tidy_plan`, audit reports, barber answers, the shopping list, the dj-build preview yaml) need no preview id. The write-gate hook matches only `_apply`, `_write` and `_undo` tools.
2. Dry-run is the default. Real writes only with `--apply`, and only after a preview the user said yes to. Silence is not a yes.
3. Before any master.db write: rekordbox closed (process check), verified backup of `master.db` + `masterPlaylists6.xml` + `-wal`/`-shm`, one commit at the end, rollback on any exception.
4. Default write path is rekordbox XML the user imports. Direct master.db writes are Windows power mode behind an explicit flag.
5. Idempotent: same name at the same level exists → `SKIP`.
6. Secrets live in `.env` (gitignored). Never print, log or commit them. Tokens go only to `https://api.spotify.com/v1/...`.
7. Nothing personal in the repo: no library paths, playlists, inbox data, names of real users. Config ships as `examples/*.example.yaml`; a user's own files live in their `dj-library/` folder.
8. Not covered here → ask first.

## Consequences in this codebase

- All DB access goes through `dj.safety.open_db()`. Nothing else may call `commit()`.
- The only mutating pyrekordbox calls allowed: `create_playlist_folder`, `create_playlist`, `create_smart_playlist`, `add_to_playlist` (never with `track_no=` or `seq=`; a `seq` re-sequences siblings and breaks rule 1).
- Never call `delete_*`, `move_*`, `rename_*`, `update_*` or set attributes on existing rows.
- After a rollback the db object is discarded, never reused.
- Read rows only through `tree.children_of`, `library.all_tracks`, `library.crate_content_ids`, `tree.alive` (rekordbox soft-deletes rows; pyrekordbox does not filter them).
- Read master.db from a snapshot copy, never the live file.
- pyrekordbox is pinned `<0.5` and tested to rekordbox 7.0.9; real libraries run 7.2.x. Read the installed pyrekordbox source before calling anything new. Do not guess signatures or units (DB `BPM` is ×100).
- `dj tidy` is the only code that writes to audio files: undo record first, write to a temp copy then `os.replace`, only EMPTY tags get proposals, file writes limited to the `roots:` in the user's `tidy.yaml`, refuses while rekordbox runs.
- A plan's `pick` must be one of the candidates the tool offered.

## MCP server rules

- `mcp_server.py` is a fixed list of `dj` commands. No tool runs an arbitrary command, reads an arbitrary file, or takes a path outside the user's library folder or the repo.
- Arguments are passed as a list; never a command string, never `shell=True`.
- Read tools and write tools are separate tools. Every write tool has a preview tool and refuses without a plan/preview id.
- Tool results: counts first, items paginated. Stay under the tool-result limit.

## Tests

- `uv run pytest`. `tests/conftest.py` blocks the real master.db and all sockets. No test opens a real DB or audio file outside `tmp_path`.
- `tests/test_contract.py` pins the pyrekordbox signatures the fakes assume: run after any pyrekordbox upgrade, before any write.
- Anything that writes to rekordbox, Spotify or audio files has tests, including the XML writer.
- CI runs the suite on Windows, macOS and Ubuntu, plus `claude plugin validate ./plugin --strict`, `ruff`, and a secret scan.

## Environment

- Python 3.13 via `uv`. Run everything with `uv run ...`. Native Python on Windows and macOS; not WSL (SQLite across the mount is unsafe; process checks are per-OS).
- Keep the venv outside cloud-synced folders: set `UV_PROJECT_ENVIRONMENT` (see `CONTRIBUTING.md`).
- While Claude Desktop has the MCP server open, the venv's `dj-mcp` binary is locked: use `uv run --no-sync`, or quit Claude Desktop before `uv sync` / `uv add`.
- Operating knowledge that is not a rule lives in `docs/lessons.md`. Keep this file to rules.

## Conventions

- One branch and one PR per change. Conventional commit titles (`feat:`, `fix:`, `docs:`, `chore:`, `test:`). Squash merge.
- Semver; `pyproject.version` = `plugin/.claude-plugin/plugin.json` version. `CHANGELOG.md` (Keep a Changelog).
- Never push, tag, publish or make the repo public without the owner's explicit yes in the conversation.
- Commit only when asked. Check `git status` for personal files before every commit.

## Layout

```
.claude-plugin/marketplace.json   self-hosted marketplace → ./plugin
plugin/                           the Claude plugin: .claude-plugin/plugin.json, skills/, shared/, hooks/, .mcp.json
src/dj/                           core: safety, library, tree, rules, match, spotify, push, build, analyze,
                                  playlist_copy, intake, tidy/, cli, mcp_server (+ readers/, analysis/, writers/ as they land)
tests/                            pytest; mocked db; synthetic audio and XML fixtures
examples/                         .env.example, links/tidy/bases/tree .example.yaml
templates/project/                Cowork Project instructions template for a DJ
docs/                             requirements, plan, decisions, architecture, breadboard, lessons
local/                            gitignored: the maintainer's own state and archived files
```
