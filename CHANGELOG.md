# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
- MCP results stay under the tool-result limit: counts first, lists paged (`page`, `page_size`) on every preview and read tool; a bare file name resolves under its folder (`tracklists/`, `plans/`, `exports/`); every writing command appends its own `log.md` line (`dj.activity_log`), and the skills only read the log (W-22).
- `dj-crate` skill (Crate me): Claude turns a brief into `crates/<slug>.spec.yaml`; code picks exactly 30 / 50 / 70 owned tracks with a reason each, plus 20% spares across energy tiers, honouring vetoes; after a yes, `proposals/crate-<slug>.xml` to import and `crates/<slug>.md`. Built proposals leave vetoed tracks out. `dj library crate`, MCP `dj_crate_preview` / `dj_crate_write` (W-23).
- `dj-barber` skill (Style Barber): at most 8 short questions (about 10 minutes, progress stated): A/B picks from the DJ's own tracks, naming lanes, vetoes, pairs, what worked at a gig; every answer appends a dated line to `taste/*.md`. `dj library barber next|record`, MCP `dj_barber_next` / `dj_barber_record` (W-24).

### Changed
- Personal configuration and state moved out of version control; code, skills and tests generalised for any user.
- Tests read the shipped `examples/` configs instead of a personal `tidy.yaml` / `tree.yaml`; two tests made portable to POSIX hosts (path separators, case-sensitive file names).
- Skills moved from `.claude/skills/` to `plugin/skills/`. Ruff added with a baseline rule set.

### Fixed
- `.gitignore`: the personal-state folders (`plans/`, `reports/`, …) are ignored at the repo root only, so `docs/prompts/plans/` is tracked.

## [0.1.0] — unreleased

Target: "Dijok edition". See `docs/requirements.md` §3.
