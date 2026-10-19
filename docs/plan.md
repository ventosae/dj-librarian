# plan.md — live state

Updated 2026-10-20. Authoritative copy (repo `dj-librarian_01`). Project copies are snapshots. The sibling folder `dj-librarian` stays the owner's daily tool until the new repo replaces it (D-18).

## Milestone: v0.1 "Dijok edition" — requirements.md §3

Goal: one experienced DJ (Mac or Windows, Cowork) exports an XML, gets the HTML report in the same sitting, imports a structure. Then engine, crates, taste, Spotify. All Must (D-11). See breadboard.md.

## Status board

| ID | Work item (one PR each unless noted) | Reqs | Status |
|---|---|---|---|
| W-01 | Audit of the folder | — | Done 19 Oct |
| W-02 | Operating-chat analysis | — | Done 19 Oct (project doc) |
| W-03 | requirements.md, breadboard.md, decisions.md | — | Done 20 Oct (v0.4) |
| W-04 | Step 2: architecture + repo layout + dev workflow (`docs/architecture.md`) | R-12xx | Agreed 20 Oct |
| W-05 | Step 3: setup kit (CLAUDE.md, .gitignore, docs/, CHANGELOG) + W-10 prompt | R-1201–1207 | Delivered 20 Oct |
| W-10 | PR: new repo `dj-librarian_01` scaffolded from the source code — allowlist copy, generalise, LICENSE, CONTRIBUTING, README, examples/, CI, `plugin/` manifest + marketplace | R-1201–1207, C-05 | Built 20 Oct |
| W-11 | PR: XML reader → the shared track/tree model | R-104, R-204, R-322 | Built 20 Oct |
| W-12 | PR: `dj-library/` scaffold + `library.yaml` schema + shared tree schema | R-901–905 | Pending |
| W-13 | PR: `dj-start` skill (device chips, export card, folder step, scaffold, M1 card) | R-101–107 | Pending |
| W-14 | PR: `dj-profile` (scripts + SKILL.md) | R-301, 302, 311, 312, 341 | Pending — parallel with W-15/16 |
| W-15 | PR: `dj-structure` | R-321, 322 | Pending |
| W-16 | PR: `dj-taste` | R-331, 332 | Pending |
| W-17 | PR: `dj-report` HTML (dataviz pass) | R-401–407 | Pending |
| W-18 | PR: `dj-build` yaml → rekordbox XML + import card + log line | R-501–505, R-904 | Pending — plan mode |
| W-19 | PR: `shared/voice.md` + `shared/adhd.md` + checklists in every skill | R-1001–1003 | Pending |
| W-20 | PR: Mac port + CI on macos-latest | R-203, R-1302 | Pending |
| W-21 | PR: engine install flow (M1) + PreToolUse gate hook (Claude Code) + permissions doc (Cowork) | R-102, R-1101, R-1105, C-10 | Pending — plan mode |
| W-22 | PR: NFR fixes — paginated previews, bare filename resolution, tool-written log | NFR-03, NFR-05, R-904 | Pending |
| W-23 | PR: Crate me | R-601–604 | Pending |
| W-24 | PR: Style Barber | R-701–703 | Pending |
| W-25 | PR: Spotify Feb-2026 audit + guided setup + per-DJ links.yaml | R-801–805, C-06 | Pending — plan mode |
| W-26 | Cowork Project template (`templates/project/instructions.md`) | R-107, C-04 | Pending |
| W-27 | PyPI publish + release workflow + plugin zip (consent gate) | D-13, D-17 | Pending |
| W-28 | Dijok test session; lessons.md | A-01…A-08 | Pending |
| W-29 | Tag v0.1.0, CHANGELOG (consent gate) | R-1201 | Pending |

## Next actions

1. Anton: run `docs/prompts/W-10.md` from the Claude desktop app (Code tab) in `dj-librarian_01` (git identity + new venv env var set first). Paste the worker's output back to the PM chat.
2. Anton: upload `principles.md` to the project.
3. PM chat: review W-10 result → W-11 prompt.

## Open questions

| ID | Question | Owner |
|---|---|---|
| Q-01 | Does the rekordbox XML export carry My Tags and play history? **Answered 20 Oct (W-11): no.** Per the pyrekordbox 0.4.4 XML schema the export has `PlayCount` and `LastPlayed` per track, but no My Tags, no history playlists and no smart-playlist rules; those need master.db (the engine). Confirm on a real rekordbox 7.2 export. | W-11 (answered) |
| Q-02 | Does pyrekordbox locate master.db and its key on macOS without manual config? | W-20 |
| Q-03 | Do plugin hooks run in Cowork? (MCP connectors: yes, verified.) | W-21 |
| Q-04 | Is the current `spotify.py` already on the Feb 2026 endpoints? (Oct builds worked.) | W-25 |
| Q-05 | Which widgets render for a non-Anton Cowork user? | W-13 |
| Q-06 | Does `pip install dj-librarian` (or the plugin's scripts) run in Cowork's sandbox at skill time? | W-11 |
| Q-07 | Does `claude plugin validate` run headless in GitHub Actions? Locally it passes with an empty config dir and no tokens, so the CI job has no `continue-on-error`. Confirm on the first Actions run. | W-10 → first push |
| Q-08 | What does `${CLAUDE_PLUGIN_ROOT}` resolve to in a Cowork session, and can `.mcp.json` start `uv run` from the repo until PyPI exists? | W-21 |
| Q-09 | The "no anton" grep hits `plugin/.claude-plugin/plugin.json` `author.name` by design. **Answered 20 Oct:** BUILD-v0.1 allows the name in `author` only; the check excludes it. | W-10 (answered) |
| Q-10 | Ruff 0.17's broader default rules (UP, B, SIM, BLE, S) give ~74 findings on the inherited code. A baseline set is pinned in `pyproject.toml`; widening it is a later PR. | later |
| Q-11 | The suite was green on Windows and on WSL Ubuntu; macOS not yet run. | W-20 / first CI run |
| Q-12 | `plugin.json` `repository` and the README clone/marketplace lines use `OWNER` as a placeholder. Fill in at first push. | W-27 |
| Q-13 | master.db play history (`DjmdHistory`) is not read; R-204's "history where the source has them" is deferred. `play_count` covers most-played. Add history sessions when a feature needs them. | later |
| Q-14 | rekordbox stores no member rows for smart playlists; the db reader returns smart playlists without `track_ids`, and `orphans()` ignores smart membership. Computing members from the rules (pyrekordbox `get_playlist_contents`) is open. | later |

## Later (one line each → issues after first push)

- L-01 Set builder from a brief: transition scorer + personal co-occurrence prior.
- L-02 Lexicon Local API adapter.
- L-03 `dj tidy` on macOS.
- L-04 Tracklist line accepts a Spotify URI / ISRC; de-prioritise "(Mixed)" releases.
- L-05 Post-gig feedback loop feeding `taste/feedback.md` into Crate me.
- L-06 Library "lint": schema violations as a reviewable plan.
- L-07 Lexicon / MIK energy ingestion as a review queue.

## Deviations from the v0.1 contract

The contract is `docs/prompts/plans/v0.1-interfaces.md`. Each item lists here what it built differently.

- **W-11.** `counts()["playlists"]` counts plain playlists; smart ones count under `smart`, and `entries` sums both. XML playlist ids are tree positions (`1.2.1`) because the export carries none. `tracks_in(folder)` and an ambiguous `node_at` raise `LibraryError`. `XML_FIELDS_MISSING` = `isrc, bit_depth, my_tags, has_artwork`; history and smart rules are in `XML_NOTES`. `read_db` retries the snapshot up to 3 times if master.db or its WAL changes during the copy. `dj library inspect --json` also returns `source_path`, `snapshot_path`, `rekordbox_version`, `notes`, and caps the tree sample (30 top nodes, 10 children each). R-322 (current tree as YAML) moves to W-15, after the tree schema (W-12).
