## What and why

<!-- One or two sentences. -->

## Requirements

<!-- The ids from docs/requirements.md this PR satisfies, e.g. R-501, NFR-03, C-05. -->

- R-

## Tests

<!-- New or changed test names. Anything that writes to rekordbox, Spotify or audio files needs tests. -->

- [ ] Tests added or updated
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check .` is clean
- [ ] `claude plugin validate ./plugin --strict` passes (if `plugin/` changed)

## Write safety

- [ ] This PR only creates and adds. It never deletes, renames, moves or reorders anything in rekordbox, Spotify or on disk.
- [ ] Every new write is dry-run by default and runs only behind `--apply` after a preview (or not applicable).
- [ ] No personal data: no library paths, playlist names, inbox data or names of real users.
- [ ] CHANGELOG.md updated under `[Unreleased]`.
