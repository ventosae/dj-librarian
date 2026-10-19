# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Open-source scaffolding: LICENSE (Apache-2.0), CONTRIBUTING, examples, CI, plugin manifest and self-hosted marketplace (W-10).
- `docs/`: requirements, plan, decisions, architecture, breadboard, lessons.

### Changed
- Personal configuration and state moved out of version control; code, skills and tests generalised for any user.
- Tests read the shipped `examples/` configs instead of a personal `tidy.yaml` / `tree.yaml`; two tests made portable to POSIX hosts (path separators, case-sensitive file names).
- Skills moved from `.claude/skills/` to `plugin/skills/`. Ruff added with a baseline rule set.

## [0.1.0] — unreleased

Target: "Dijok edition". See `docs/requirements.md` §3.
