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

### Changed
- Personal configuration and state moved out of version control; code, skills and tests generalised for any user.
- Tests read the shipped `examples/` configs instead of a personal `tidy.yaml` / `tree.yaml`; two tests made portable to POSIX hosts (path separators, case-sensitive file names).
- Skills moved from `.claude/skills/` to `plugin/skills/`. Ruff added with a baseline rule set.

### Fixed
- `.gitignore`: the personal-state folders (`plans/`, `reports/`, …) are ignored at the repo root only, so `docs/prompts/plans/` is tracked.

## [0.1.0] — unreleased

Target: "Dijok edition". See `docs/requirements.md` §3.
