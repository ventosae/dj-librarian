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
| W-10 | PR: new repo `dj-librarian_01` scaffolded from the source code — allowlist copy, generalise, LICENSE, CONTRIBUTING, README, examples/, CI, `plugin/` manifest + marketplace | R-1201–1207, C-05 | Prompt issued (`docs/prompts/W-10.md`) |
| W-11 | PR: XML reader → the shared track/tree model | R-104, R-204, R-322 | Pending — first after W-10 (D-10) |
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
| Q-01 | Does the rekordbox XML export carry My Tags and play history? | W-11 |
| Q-02 | Does pyrekordbox locate master.db and its key on macOS without manual config? | W-20 |
| Q-03 | Do plugin hooks run in Cowork? (MCP connectors: yes, verified.) | W-21 |
| Q-04 | Is the current `spotify.py` already on the Feb 2026 endpoints? (Oct builds worked.) | W-25 |
| Q-05 | Which widgets render for a non-Anton Cowork user? | W-13 |
| Q-06 | Does `pip install dj-librarian` (or the plugin's scripts) run in Cowork's sandbox at skill time? | W-11 |
| Q-07 | Does `claude plugin validate` run headless in GitHub Actions? | W-10 |
| Q-08 | What does `${CLAUDE_PLUGIN_ROOT}` resolve to in a Cowork session, and can `.mcp.json` start `uv run` from the repo until PyPI exists? | W-21 |

## Later (one line each → issues after first push)

- L-01 Set builder from a brief: transition scorer + personal co-occurrence prior.
- L-02 Lexicon Local API adapter.
- L-03 `dj tidy` on macOS.
- L-04 Tracklist line accepts a Spotify URI / ISRC; de-prioritise "(Mixed)" releases.
- L-05 Post-gig feedback loop feeding `taste/feedback.md` into Crate me.
- L-06 Library "lint": schema violations as a reviewable plan.
- L-07 Lexicon / MIK energy ingestion as a review queue.
