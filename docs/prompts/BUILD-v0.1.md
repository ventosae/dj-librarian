Model: claude-opus-5-5 · Effort: high · Mode: normal, auto-accept edits for the session

# BUILD v0.1 "Dijok edition" — all work items, one session, resumable

## Context
- Repo root, branch `main` (create it from the current commit if it doesn't exist: `git branch main && git switch main`). Windows 11, uv, venv at `$env:UV_PROJECT_ENVIRONMENT`. Baseline: `uv run pytest` green.
- The spec is in the repo. Read in this order, fully, before touching code: `CLAUDE.md`, `docs/requirements.md` (every R-id has an acceptance column: that is your test list), `docs/breadboard.md` (the user flow every skill must produce), `docs/architecture.md` (layout, two doors, one core), `docs/plan.md` (work items W-11…W-26, their R-ids and order), `docs/lessons.md`, `docs/prompts/W-11.md` (the detailed spec for the first item; follow it).
- Existing code to build on, never refactor: `src/dj/*` (`match.Local`, `library.TrackInfo`, `tree.Node`, `safety`), `plugin/skills/dj-sync`, `plugin/skills/dj-tidy`, `tests/conftest.py` (blocks real DB and sockets).
- `../dj-librarian` is the owner's live tool: read-only reference, never written.

## Task
Build W-11 → W-12 → W-13 → W-19 → W-14 → W-15 → W-16 → W-17 → W-18 → W-20 → W-21 → W-22 → W-23 → W-24 → W-25 → W-26, in that order. Each item is one branch, one squash commit on `main`, no remote.

Per item:
1. Branch `feat/<w-id>-<slug>` off `main`. Re-read the item's R-ids and the breadboard places it serves.
2. Items that touch a writer or a gate (W-18, W-21, W-25): first write `docs/prompts/plans/<W-id>.md` — the design in ≤ 30 lines, checked against the CLAUDE.md hard rules — then build.
3. Implement. Skills live in `plugin/skills/<name>/SKILL.md` with `scripts/` beside them; every skill references `plugin/shared/voice.md` and `plugin/shared/adhd.md` and ends with the pre-send checklist. Code goes in `src/dj/`, tests in `tests/`. Measured facts from code, words from Claude (R-302).
4. Tests for every R-id's acceptance line. Writers (XML writer, any `--apply`) get a test that proves the dry-run writes nothing and the live path refuses without a yes/plan id.
5. `uv run ruff check . --fix && uv run pytest && claude plugin validate ./plugin --strict` — all green before the commit.
6. Update `docs/plan.md` (status → Built, answer any Q- it resolves, add new Q- lines), `CHANGELOG.md` (Unreleased), and the R-id status column in `docs/requirements.md` (Proposed → Built).
7. Squash-merge into `main` with a conventional title (`feat: …`, `fix: …`, `docs: …`). Delete the branch.
8. If an item cannot pass its criteria after 3 honest attempts: record the gap as a `Q-` line in `docs/plan.md` with status Blocked, commit what passes, continue with the next item that does not depend on it.

Fixed decisions you do not revisit: XML export is first contact (D-10); the engine is the plugin's stdio MCP (D-15); v0.1 writes only rekordbox XML the DJ imports (D-04); master.db writes stay Windows power mode behind a flag (R-205); voice is style only, no book text (C-08); the 10 ADHD rules are in R-1002; licence Apache-2.0.

Resume rule: if this session restarts or compacts, read `docs/plan.md` and continue from the first item not marked Built.

## Boundaries
- Never run anything with `--apply` against a real rekordbox, Spotify account or audio file. No real `master.db`, no real music folder, no network in tests. Spotify work (W-25) is code + tests + the setup card only.
- Never push, add a remote, tag, publish to PyPI, upload a plugin zip, or make anything public (W-27, W-29 are the owner's).
- Nothing personal in the repo: no names of real users outside `author`, no real paths, playlists or inbox data. `git grep -il anton -- src tests plugin examples README.md` must stay empty.
- Do not delete, move or write anything under `../dj-librarian`.
- Do not change existing public behaviour of `dj` commands except where an R-id says so (NFR-03, NFR-05).
- No `bin/` directory in `plugin/`.

## Success criteria
- `docs/plan.md`: W-11…W-26 all Built, or Blocked with a Q- line each.
- `uv run pytest` green; count higher than baseline by ≥ 150; every writer has a dry-run-writes-nothing test.
- `uv run ruff check .` clean; `claude plugin validate ./plugin --strict` → `Validation passed`; `claude plugin validate .` passes.
- `plugin/skills/` contains `dj-start`, `dj-profile`, `dj-structure`, `dj-taste`, `dj-report`, `dj-build`, `dj-crate`, `dj-barber`, `dj-spotify`, `dj-sync`, `dj-tidy`, each with a SKILL.md that names its R-ids, references `shared/voice.md` + `shared/adhd.md`, and ends with the pre-send checklist.
- `plugin/shared/voice.md` and `plugin/shared/adhd.md` exist; `voice.md` has ≥ 5 do / don't pairs written by you, no quotes from the book.
- End-to-end on fixtures: `tests/xml_fixtures.py` library → `dj-profile`, `dj-structure`, `dj-taste` scripts → MD files → `dj-report` → one self-contained HTML (no external URLs) with the four sections of R-402…R-406 → `dj-build` turns one proposal into a rekordbox XML that `pyrekordbox` reads back with the same playlists. One test runs this whole chain.
- `templates/project/instructions.md` exists (R-107).
- `git log --oneline` on `main`: one squash commit per item, conventional titles; working tree clean.
- `docs/prompts/REPORT-v0.1.md` written: per item Built/Blocked, test count before/after, the Q- lines added, and a ≤ 10-line list of what only the owner can do next (push, publish, Mac live test, Dijok session).

## Output
Paste back, nothing else: the contents of `docs/prompts/REPORT-v0.1.md`.
