# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `dj backup [--library] [--list]`, the MCP tool `dj_backup` and the backup skill (W-37, D-31, R-206): a verified copy of rekordbox's database (`master.db`, `-wal`, `-shm`, `masterPlaylists6.xml`) in `<dj-library>/backups/rekordbox-<date>/` with `manifest.json` and `RESTORE.md`, the steps back for that OS. Nothing is copied when the database is unchanged since the newest verified copy; every backup is kept; an unverified copy is kept and flagged; refused in a synced folder; rekordbox's folder is only read. It runs at install step 7, first in an engine session, and right before every import card on the engine path. `dj_backup` is the one write tool without a preview id (CLAUDE.md).
- Versioning (W-37): `version` in `pyproject.toml` is the one source; `scripts/bump_version.py patch|minor` writes it into `uv.lock`, `plugin.json`, the marketplace entry (which now carries a version) and `mcpb/manifest.json`, and dates CHANGELOG's `[Unreleased]`. `tests/test_version_sync.py` fails CI on drift, `dj status` included. CONTRIBUTING has the rules (patch, minor, when to tag).

### Changed
- Honest track counts (Q-34): rows rekordbox streams (Spotify, Beatport Streaming, ...) are counted apart and left out of the tracks and playlists that profile, structure, taste, crates and builds see, from master.db and from an export alike. `dj status` prints `tracks: N · L local · S streaming` and the dj-librarian version; the profile's Collection stat says how many streamed rows were not counted.
- `/dj-librarian:install` is nine steps: the backup is step 7, the config merge and the restart are 8 and 9.

### Fixed
- The install doc's intro check ignores case (W-36 rewrote the intro).

## [0.1.0] - 2026-10-25

Target: "Dijok edition". See `docs/requirements.md` §3.

### Added
- Open-source scaffolding: LICENSE (Apache-2.0), CONTRIBUTING, examples, CI, plugin manifest and self-hosted marketplace (W-10).
- `docs/`: requirements, plan, decisions, architecture, breadboard, lessons.
- One library model (`dj.model`) fed by two readers: the rekordbox XML export (standard library only) and a read-only snapshot of master.db. `dj library inspect` and the MCP tool `dj_library_inspect` (W-11).
- `dj-library/` folder: create-only scaffold (README, `library.yaml` schema v1, `links.yaml`, `log.md`, `.gitignore`), export import by copy, tool-written `log.md` lines, and one tree schema (`dj.treeschema`) shared by `bases.yaml`, `structure/current-tree.yaml` and `proposals/*.yaml` (W-12).
- `dj-start` skill: onboarding session 1 in six steps (device, export card per OS, folder, work phase, report, next) with `scripts/start.py` (`find-xml`, `init`) (W-13).
- `plugin/shared/voice.md` (our own do/don't pairs, no book text) and `plugin/shared/adhd.md` (the 10 reply rules, attributed); every skill ends with the pre-send checklist, enforced by `tests/test_skills.py` (W-19).
- `dj-profile` skill: measured profile (`profile/stats.md`, `profile/facts.json`: size, formats, bitrates, eras, timeline, field use, duplicates, the 5 stats that matter); `dj library profile` (W-14).
- `dj-structure` skill: tree depth and width, naming, sizes, overlap (Jaccard), orphans, empty playlists, dumps, smart vs plain (`structure/analysis.md`, `graph.json`, `facts.json`) and the current tree as code (`structure/current-tree.yaml`, `treeschema.from_library`); `dj library structure` (W-15).
- `dj-taste` skill: labels and artists, clusters, BPM lanes, keys, co-occurrence, top-rated and most-played, anchors, the DJ's own words; `taste/*.md` are appended and refined across sessions, never regenerated without asking (`dj.taste_files`, incl. vetoes and feedback parsers); `dj library taste` (W-16).
- `dj-report` skill: 2-3 restructure proposals (bases, facets, gig-first) picked from the DJ's patterns (`structure/proposals.yaml`), and the one-file HTML report (`reports/<date>-library.html`: who you are, how it's built, three ways to rebuild it, one next action; no external requests). `dj library report`, `dj library analyze` and the MCP tool `dj_library_analyze` (W-17).
- `dj-build` skill: a proposal becomes `proposals/<slug>.yaml` (tree as code) and a preview (CREATE / SKIP per node); only with that preview's id does it write `proposals/<slug>.xml`, a rekordbox XML the DJ imports, plus import steps for their OS and a `log.md` line. The preview gate (`dj.gate`) and the XML writer (`dj.writers.rekordbox_xml`, read back by pyrekordbox in tests). `dj library build`, MCP `dj_structure_preview` / `dj_structure_write`. master.db is never opened (W-18).
- `tests/test_e2e_chain.py`: one test runs export, start, profile, structure, taste, report and build through the skill scripts (W-18).
- macOS port: rekordbox process check with `pgrep`, master.db discovery under `~/Library/Pioneer/rekordbox`, MCP environment per OS, Claude Desktop config path per OS in the README; master.db writes stay Windows-only (W-20).
- Write gate everywhere (W-21): every dry-run of `dj tree`, `dj apply`, `dj copy`, `dj push`, `dj build`, `dj tidy apply`, `dj tidy undo` returns a preview id, and `--apply` refuses without that id (or after the plan changed); master.db writes also need `--power-mode` (Windows only). MCP write tools require `preview_id`. A Claude Code PreToolUse hook (`plugin/hooks/`) denies write tools without one. Engine install card (`dj-start/engine.md`), `dj library use`, `docs/permissions.md`.
- MCP results stay under the tool-result limit: counts first, lists paged (`page`, `page_size`) on every preview and read tool; a bare file name resolves under its folder (`tracklists/`, `plans/`, `exports/`); every writing command appends its own `log.md` line (`dj.activity_log`; exceptions in `docs/plan.md`), and the skills only read the log (W-22).
- `dj-crate` skill (Crate me): Claude turns a brief into `crates/<slug>.spec.yaml`; code picks exactly 30 / 50 / 70 owned tracks with a reason each, plus 20% spares across energy tiers, honouring vetoes; after a yes, `proposals/crate-<slug>.xml` to import and `crates/<slug>.md`. Built proposals leave vetoed tracks out. `dj library crate`, MCP `dj_crate_preview` / `dj_crate_write` (W-23).
- `dj-barber` skill (Style Barber): at most 8 short questions (about 10 minutes, progress stated): A/B picks from the DJ's own tracks, naming lanes, vetoes, pairs, what worked at a gig; every answer appends a dated line to `taste/*.md`. `dj library barber next|record`, MCP `dj_barber_next` / `dj_barber_record` (W-24).
- Spotify for any DJ (W-25): `dj-spotify` skill with the setup card (own app, Premium, redirect URI, `.env`); the inbox loop follows `links.yaml` in the DJ's library folder; `dj wishlist shop` writes `wishlist/<crate>.shopping.md` with Beatport and Bandcamp search links; February 2026 API audit (`docs/spotify-audit.md`) with the removed batch artists call dropped. MCP `dj_wishlist_shop`.
- `tests/test_skills.py` pins the eleven v0.1 skills.
- Optional Cowork Project template `templates/project/instructions.md`: voice, the 10 reply rules, safety, the `dj-library/` folder conventions (W-26).
- `dj-identity` skill (W-31): six measured axes (Depth, Selectivity, Discipline, Breadth, Momentum, Memory), an archetype picked by code from `archetypes.yaml`, and the sleeve, a deterministic 12-inch SVG fingerprint of the library (`profile/identity.json`, `profile/sleeve.svg`); Claude writes the liner notes (`profile/identity.md`). dj-start asks the DJ's handle (`library.yaml` `dj_name`); Style Barber names the archetype once.
- Report redesign (W-31): the sleeve hero with handle, archetype, liner notes and the 5 stats; a crate wall with hatched dumps and the overlap arc; three proposal cards with mini sleeves; a sticky Next bar; Booth (dark, default) and Day themes; hover tooltips and a table link on every chart; phone and print layouts. `docs/design.md` is the design system and `scripts/check_palette.py` validates it in CI. `docs/samples/` with `report-booth.png` and `report-day.png`, made by `scripts/make_samples.py`.
- `dj apply --xml` and `dj copy --xml`: approved inbox adds and copies as a rekordbox XML to import, on any OS; MCP `dj_apply_write` / `dj_copy_apply` take `mode` (W-30, Q-22).
- `scripts/build_plugin_zip.py`: the plugin zip a DJ uploads, with one copy of the core at `plugin/engine/` (the engine's source; the skill scripts import from `engine/src`) and a light `-no-engine` zip for Door 1 (W-30, W-35, D-29).
- Gig feedback scores Crate me: `+` lines add a point, `-` lines take one off and never make a spare (W-30, Q-19).
- `docs/samples/chat-session-1.md`: the six dj-start replies, checked against the reply rules (W-30, Q-15).
- `.github/workflows/release.yml`: on a pushed `v*` tag it runs the CI checks (`ci.yml` via `workflow_call`), refuses a tag that is not on `main` or does not match `pyproject.toml` and `plugin.json`, cuts the version's CHANGELOG section (`scripts/release_notes.py`), builds the plugin zip and creates a draft GitHub release with the zip attached; no PyPI step (W-32, W-27).
- README "Try it before the release": install the zip (Customize → Plugins → Add → Upload plugin), what Door 1 does and where the engine comes from (W-32, W-34).
- `docs/dijok-session.md`: the one-page run sheet for the first tester session (W-28): before, during, after, the A-01…A-08 checks and the three questions (W-32).
- The engine as a standalone MCPB desktop extension (W-34, D-28): `mcpb/manifest.json` (uv type; settings form: dj-library folder, Spotify keys, Power mode) and `scripts/build_mcpb.py` → `dj-librarian-engine-<v>.mcpb` (`--smoke`, `--npx`); `release.yml` attaches it with both plugin zips.
- The engine reads its settings from the host (`dj.hostenv`): `DJ_LIBRARY`, `SPOTIFY_CLIENT_ID/SECRET` (before any `.env`), `DJ_POWER_MODE` (false, or unset in the extension, refuses every master.db write), `DJ_ENGINE=mcpb`. Config files come from the dj-library folder first; as an extension its state (backups, previews, caches, tidy undo records) lives in `<dj-library>/.cache/engine/` so it survives updates (W-34).
- `docs/install.md` (one upload, the `.mcpb` fallback, permissions, where the state lives), a terminal-free engine card, dj-start's "The engine is already in" line, the A6 handout with its re-render README (W-34).
- `/dj-librarian:install` and `/dj-librarian:uninstall` (W-35, D-29): Claude Code installs the engine from the plugin zip into `~/dj-librarian` (uv, `uv sync`, `dj status`) and adds it to Claude Desktop's config with `DJ_LIBRARY`, a backup first and nothing else touched (`src/dj/installer.py`, `scripts/merge_desktop_config.py`); the DJ clicks Allow. `docs/install.md`, the engine card, dj-start's offer and the A6 card point at it.

### Changed
- Install comes first (W-36, D-30): `/dj-librarian:install` asks which folder should be the dj-library and makes it (`scripts/library_init.py`, `dj.library_setup`); dj-start reads master.db through the engine when it is installed (four steps, no export, `library.yaml` records `source: db`) and keeps the six XML steps without it; `dj library build --source db` (default: `library.yaml`'s) builds from a master.db snapshot (Q-17).
- Personal configuration and state moved out of version control; code, skills and tests generalised for any user.
- Tests read the shipped `examples/` configs instead of a personal `tidy.yaml` / `tree.yaml`; two tests made portable to POSIX hosts (path separators, case-sensitive file names).
- Skills moved from `.claude/skills/` to `plugin/skills/`. Ruff added with a baseline rule set.
- Lane colours by size (Q-30, D-27): the four biggest lanes keep a colour, numbered 1-4 by BPM and assigned once in `identity.json`; every other lane is Other on every chart and on the sleeve (W-32).
- The plugin names no MCP server: `plugin/.mcp.json`, the `uv_path` option, the vendored core (`plugin/vendor/`) and the bundle inside the zip are gone; Spotify keys go in the engine settings form (extension) or `.env` in the dj-library folder (W-34, W-35).
- CLAUDE.md: size rules (module ≤ 600 lines, tests ≤ 1.5× code, PR ≤ +2,000 lines) and the install line; the handout previews and `docs/samples/report.png` are rendered locally, not tracked (W-35).

### Fixed
- `/dj-librarian:install` and `:uninstall` are skills (`plugin/skills/install/`, `uninstall/`), not the legacy `commands/` format the Claude desktop app flagged.
- The plugin zip uploads on claude.ai: the plugin sits at the zip's root, and the dj-build and dj-crate descriptions carry no `<…>` placeholders (Q-21).
- `.gitignore`: the personal-state folders (`plans/`, `reports/`, …) are ignored at the repo root only, so `docs/prompts/plans/` is tracked.
- v0.1 verification pass: a plan's pick is checked against the offered candidates (cache matches included); soft-deleted picks are refused; `dj status` counts only rows that are not soft-deleted; the process check reads a localized tasklist; `dj push/build` never create a second Spotify playlist on a 5xx, network or 429 error; reports are create-only; `dj tidy apply/undo` never write outside the tidy.yaml roots and tidy renames never overwrite; mounted volume roots are refused as a library folder; `dj_tidy_audit` is a library-text tool; tests also block DNS and UDP; skill scripts answer with a JSON `core` error when the core is missing; skills call `python3`; three real playlist names removed from CLI help and tests; README, CONTRIBUTING, permissions and several skills brought up to date.
- W-30: every read-only pass reads a master.db snapshot, never the live file (Q-18); writes on a disk that refuses deletes go in place without temp files (Q-27); one clock for every `log.md` line (Q-28); dj-build refuses proposals made from a newer source than the export it reads (Q-17); CI's personal-data check covers `.claude-plugin/`, `templates/` and `docs/samples/` (Q-26).
- W-31 polish: no "Words by Claude" captions in the hero; four-line liner notes; at most 4 colours per chart, extra lanes in Other (D-26); sparse sleeve rings drawn wider and lighter, decade labels on the sleeve.
- CLAUDE.md hard rule 1 names its two exceptions (D-20); D-19 to D-23 and D-26 recorded.
