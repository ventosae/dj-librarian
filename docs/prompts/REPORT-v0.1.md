# REPORT v0.1 "Dijok edition" — build of W-11 … W-26

Built 2026-10-20 on `main`, one squash commit per item, plus one verification commit. No push, no remote, no tag, nothing published.

## Result

| | Before (after W-10) | After |
|---|---|---|
| Tests, Windows | 344 passed | 2294 passed, 6 skipped |
| Tests, WSL Ubuntu | 344 passed | 2297 passed, 3 skipped |
| Ruff | clean | clean |
| `claude plugin validate ./plugin --strict` | passed | passed |
| `claude plugin validate .` | passed | passed |

The skips are platform-only tests (POSIX file modes and mount paths and a symlink case on Windows; one Windows-only test on Ubuntu) and two R-1003 spot-check slots waiting on reviewed real outputs (Q-15).

## Per item

| Item | Status | Commit | R-ids set to Built | Tests on main after |
|---|---|---|---|---|
| W-11 Library model, XML + master.db readers | Built | aefd158 | R-202, R-204 | 502 |
| W-12 dj-library scaffold, library.yaml, tree schema | Built | faf13e1 | R-901, R-902, R-903, R-905 | 715 |
| W-13 dj-start onboarding | Built | 15cdb56 | R-101, R-103, R-105 | 817 |
| W-19 voice.md, adhd.md, checklist in every skill | Built | 5aee80d | R-1001, R-1002 | 852 |
| W-14 dj-profile | Built | e45a651 | R-302, R-311, R-312, R-341 | 988 |
| W-15 dj-structure | Built | 972c60b | R-321, R-322 | 1093 |
| W-16 dj-taste | Built | 884de34 | R-301, R-331, R-332 | 1194 |
| W-17 dj-report (proposals + HTML) | Built | b040484 | R-104, R-401–R-403, R-405–R-407 | 1346 |
| W-18 dj-build (XML writer + preview gate) | Built | 1d7fd49 | R-404, R-501–R-505 | 1489 |
| W-20 Mac port | Built | 0655677 | R-201, R-203, R-1302 | 1554 |
| W-21 Write gate, power mode, hook, engine card | Built; R-102 blocked on Q-08 (Cowork) | ce5c017 | R-205, R-1101, R-1102, R-1105 | 1821 |
| W-22 Paging, bare names, tool-written log | Built | d14d8b7 | R-904, NFR-03, NFR-05 | 1954 |
| W-23 Crate me | Built | 91a8129 | R-601–R-604, R-702 | 2082 |
| W-24 Style Barber | Built | 9a189ea | R-701, R-703 | 2134 |
| W-25 Spotify for any DJ | Built | 7bed9d9 | R-801–R-805 | 2206 |
| W-26 Cowork Project template | Built | 35097b7 | R-107 | 2261 |
| Verification pass (5 audits + fixes) | — | 2da8742 | statuses qualified where acceptance is partial | 2294 |

Not Built, by design: R-102 (Q-08), R-106 (Dijok transcript), R-1003 (one MD file and one chat reply, Q-15), R-1201 tag and R-1205 issues (owner, after push), R-1303 (v0.2).

End-to-end proof: `tests/test_e2e_chain.py` runs the synthetic export through dj-start, dj-profile, dj-structure, dj-taste and dj-report (one self-contained HTML, four sections, no external URLs), then dj-build preview → refused without the id → written with it, and pyrekordbox reads the XML back with the same playlists and tracks.

## Q- lines added (docs/plan.md)

- Q-09 "anton" grep hits `plugin.json` author (answered: allowed). Q-10 wider ruff rules later. Q-11 macOS CI not yet run. Q-12 `OWNER` placeholders.
- Q-13 master.db play history not read. Q-14 smart-playlist members not stored in master.db.
- Q-15 R-1003 spot check: one MD file and one chat reply left. Q-16 live rekordbox import of built and crate XMLs.
- Q-17 db-sourced `from` paths vs the latest XML export. Q-18 remaining live master.db reads in dry-runs.
- Q-19 `taste/feedback.md` not scored. Q-20 dj-tidy renames vs hard rule 1.
- Q-21 Door 1 needs the core shipped with the plugin (zip or PyPI). Q-22 no XML route for inbox adds/copies on a Mac.
- Q-23 agree D-20 and put its exceptions into CLAUDE.md. Q-24 live acceptance checks for the Dijok session.
- Q-25 bare `uv` for engine and hook on a GUI-launched Mac. Q-26 three real playlist names remain in commit 99ac55a; `owner.name` in marketplace.json.
- Answered: Q-01 (XML has no My Tags, history or smart rules), Q-04 (Spotify audit), Q-08 partly (Claude Code path).

## Only the owner can do next

1. Decide Q-26 (history and `owner.name`), then create the GitHub repo and push `main`; watch the first CI run (Q-07, Q-11).
2. Agree or change D-19, D-20 (Q-23) and Q-20.
3. W-27 with consent: plugin zip with the core vendored (Q-21); PyPI later.
4. Mac live test: `dj_status`, the plugin engine and the hook on a GUI-launched Claude (Q-02, Q-25).
5. W-28 Dijok session: import a built XML and a crate (Q-16), the live checks in Q-24, the chat spot check (Q-15).
6. W-29: tag v0.1.0 after your yes.
