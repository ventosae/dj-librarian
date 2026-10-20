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
| W-12 | PR: `dj-library/` scaffold + `library.yaml` schema + shared tree schema | R-901–905 | Built 20 Oct |
| W-13 | PR: `dj-start` skill (device chips, export card, folder step, scaffold, M1 card) | R-101–107 | Built 20 Oct |
| W-14 | PR: `dj-profile` (scripts + SKILL.md) | R-301, 302, 311, 312, 341 | Built 20 Oct |
| W-15 | PR: `dj-structure` | R-321, 322 | Built 20 Oct |
| W-16 | PR: `dj-taste` | R-331, 332 | Built 20 Oct |
| W-17 | PR: `dj-report` HTML (dataviz pass) | R-401–407 | Built 20 Oct |
| W-18 | PR: `dj-build` yaml → rekordbox XML + import card + log line | R-501–505, R-904 | Built 20 Oct |
| W-19 | PR: `shared/voice.md` + `shared/adhd.md` + checklists in every skill | R-1001–1003 | Built 20 Oct |
| W-20 | PR: Mac port + CI on macos-latest | R-203, R-1302 | Built 20 Oct |
| W-21 | PR: engine install flow (M1) + PreToolUse gate hook (Claude Code) + permissions doc (Cowork) | R-102, R-1101, R-1105, C-10 | Built 20 Oct (R-102 blocked on Q-08 for Cowork) |
| W-22 | PR: NFR fixes — paginated previews, bare filename resolution, tool-written log | NFR-03, NFR-05, R-904 | Built 20 Oct |
| W-23 | PR: Crate me | R-601–604 | Built 20 Oct |
| W-24 | PR: Style Barber | R-701–703 | Built 20 Oct |
| W-25 | PR: Spotify Feb-2026 audit + guided setup + per-DJ links.yaml | R-801–805, C-06 | Built 20 Oct |
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
| Q-04 | Is the current `spotify.py` already on the Feb 2026 endpoints? **Answered 20 Oct (W-25):** yes, after one fix: `dj analyze` no longer calls the removed `GET /artists?ids=`; popularity and genres are treated as missing. See `docs/spotify-audit.md`. A live run is still open (R-805). | W-25 (answered) |
| Q-05 | Which widgets render for a non-Anton Cowork user? | W-13 |
| Q-06 | Does `pip install dj-librarian` (or the plugin's scripts) run in Cowork's sandbox at skill time? | W-11 |
| Q-07 | Does `claude plugin validate` run headless in GitHub Actions? Locally it passes with an empty config dir and no tokens, so the CI job has no `continue-on-error`. Confirm on the first Actions run. | W-10 → first push |
| Q-08 | What does `${CLAUDE_PLUGIN_ROOT}` resolve to in a Cowork session, and can `.mcp.json` start `uv run` from the repo until PyPI exists? **Partly answered (W-21):** Claude Code loads a relative-path plugin from a marketplace added from the local clone in place, so `.mcp.json` finds the engine; a GitHub marketplace or a zip upload runs from a cached copy with no engine next to it. The Cowork add path is unverified; the engine card points a Cowork DJ at the README's manual registration when `dj_status` does not answer. R-102 is blocked on this for Cowork. | W-27 / first Cowork test |
| Q-09 | The "no anton" grep hits `plugin/.claude-plugin/plugin.json` `author.name` by design. **Answered 20 Oct:** BUILD-v0.1 allows the name in `author` only; the check excludes it. | W-10 (answered) |
| Q-10 | Ruff 0.17's broader default rules (UP, B, SIM, BLE, S) give ~74 findings on the inherited code. A baseline set is pinned in `pyproject.toml`; widening it is a later PR. | later |
| Q-11 | The suite is green on Windows and on WSL Ubuntu (W-20: 782 tests there); macOS not yet run. R-203 and R-1302 need the first `macos-latest` CI run and a live `dj_status` on a Mac (A-C1, Q-02). | first push / Mac tester |
| Q-12 | `plugin.json` `repository` and the README clone/marketplace lines use `OWNER` as a placeholder. Fill in at first push. | W-27 |
| Q-13 | master.db play history (`DjmdHistory`) is not read; R-204's "history where the source has them" is deferred. `play_count` covers most-played. Add history sessions when a feature needs them. | later |
| Q-14 | rekordbox stores no member rows for smart playlists; the db reader returns smart playlists without `track_ids`, and `orphans()` ignores smart membership. Computing members from the rules (pyrekordbox `get_playlist_contents`) is open. | later |
| Q-15 | R-1003: spot-check three real outputs (the HTML report, one MD file, one chat reply) against both checklists. The report check is automated (W-17); one MD file and one chat reply remain. | W-28 |
| Q-16 | R-502/R-503/A-03: import a built `proposals/<slug>.xml` into a real rekordbox 7.2 on Mac and on Windows and check the playlists hold the mapped tracks. Today only pyrekordbox and our reader read it back. | W-28 (Dijok session) |
| Q-17 | With `dj library analyze --source db`, a proposal's `from` paths come from master.db, but `dj library build` resolves them against the latest XML export; a playlist made after the last export fails there. Ask for a fresh export before building, or let build accept a db Library. | later |
| Q-18 | CLAUDE.md says master.db is read from a snapshot. `dj status` and `dj library` do; the dry-run passes of `dj tree`, `dj apply`, `dj copy`, `dj push` and `dj tidy audit/plan` still open the live file read-only through `open_db(write=False)`. Move them to the snapshot reader. | later |
| Q-19 | R-702 names `taste/feedback.md` (what worked at a gig) as an input to Crate me and proposals. Vetoes are honoured; feedback is free text and not scored yet (L-05 defers the loop). | later (L-05) |

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
- **W-12.** The scaffolded `.gitignore` adds `/*.xml` (the export the DJ drops at the top) and `*.tmp`; on an existing `.gitignore`, scaffold appends the missing machine-path lines instead of skipping (`ScaffoldResult.gitignore_added`). `import_export` skips when identical content is already anywhere in `exports/`, refuses a truncated XML or an invalid `library.yaml`, and copies create-only (hard link or exclusive create). `exports.latest` must be `exports/<name>.xml`. `configured_root()` is always absolute and refuses a drive root or the home folder. `LibraryFolderError` subclasses `dj.model.LibraryError`. `treeschema.dumps` checks that the emitted YAML reads back identical. The breadboard's P3 "XML moved to exports/" is a copy (hard rule 1).
- **W-13.** Onboarding logic lives in a new Door-1 module `dj.onboarding`; `start.py` parses arguments. `init` JSON adds `gitignore_added, source, new_export, device, device_was, not_in_xml, log`; `find-xml` adds `found` and `library`. Errors are `{error, reason}`. `log.md` gets a line only when something changed. The device given last wins (logged). Only a rekordbox export with tracks counts. `find-xml` searches 3 levels deep and skips `exports/`, `proposals/` and hidden entries. Exit 2 for a drive root, the home folder, the plugin folder or a crowded folder not yet set up. R-104 is Built with W-17 (its end-to-end test needs the report); R-106 waits for the Dijok transcript (W-28).
- **W-19.** R-1003 ("spot check on 3 outputs") is not claimed: `tests/test_skills.py` holds three skipped slots for a report (W-17), an MD file (W-14) and a chat reply (W-28); the mechanical checker is `tests/reply_checks.py`. The append-only `## Log` sections of `taste/*.md` are records like `log.md` and are exempt from the five-item cap; their `## Now` summary is capped at 5 (decided at W-16 integration).
- **W-14.** `dj.analysis.common` adds `library_folder()` (resolves `--library`, refuses a drive root or the home folder), `resolve_xml()` (a relative `--xml` is looked up in the library first) and `dup_key(artist, title, remixer)` (a remix named only in the Remixer field is not a duplicate of its original). R-312's acceptance ("Dijok says it sounds like him") is live (A-05); the skill gives Claude the habits.md template and the no-invented-numbers rule.
- **W-15.** Dumps = more than 300 entries, or more than half the collection, or more than 25% of it and more than twice the median size of the other non-empty playlists. `overlap.contained` lists pairs where one playlist sits inside another; naming patterns ignore a leading number or date. Duplicate sibling names get a deterministic suffix (`Name (2)`) in `current-tree.yaml` and are listed as `naming.duplicates_renamed`; a proposal's `from` must use the real name. `current-tree.yaml` is regenerated each run, but if the DJ edited it, their file is first kept as `structure/current-tree.edited-<date>.yaml` (create-only).
- **W-16.** Each `taste/*.md` has a `## Now` summary (at most 5 lines, regenerated each run) and an append-only `## Log` of dated, keyed entries (never rewritten; hand-written lines kept). A run adds at most 5 Log lines per file. `--rebuild` first keeps the old files in a dated backup folder. The CLI exits 2 (refused) when `--library` is not a library folder.
- **W-17.** Proposals score each family 0-100 from the DJ's patterns and propose every family above 0, at least 2, at most 3. Every `from` is a real path; smart playlists and playlists without a unique path "stay where they are". A dump lands in an inbox (a whole-playlist copy cannot split it; the cost counts 2 minutes per dump to split by hand). The My Tag axes are named in the facets principle only (the XML cannot set My Tags). `structure/proposals.yaml` is strict: a rename changes `name` and `trigger` together, then re-run `render` (CLI `--render-only`). Reports are create-only: `reports/<date>-library.html`, then `-library-2.html`. `analyze` logs one line per step and renders with whatever succeeded. R-404 is Built with W-18 (its trigger must work with dj-build). The R-1003 report slot is a real test now; the MD-file and chat slots stay open (Q-15).
- **W-18.** A blocked preview (a CONFLICT row or nothing to create) issues no preview id. The gate also refuses a malformed id and a record dated in the future; a new preview of unchanged content re-arms a used id (ids are deterministic). The XML carries `BitRate` and `SampleRate` too; tracks without a file location are left out and counted. Non-numeric library ids map to `max(id) + n`. `write_xml` is create-only (`<slug>-2.xml`). The preview's `lands` come from each new playlist's `from` list. The CLI exits 1 on a refusal (exit 2 stays "rekordbox is open"); the skill script exits 2 (refused). `tests/test_e2e_chain.py` runs the whole chain from export to a pyrekordbox read-back in one test.
- **W-20.** `safety.open_db(write=True)` refuses on any OS but Windows (`DB_WRITE_PLATFORMS`), before discovery, process check or backup (hard rule 4, R-205). The macOS process check is `/usr/bin/pgrep -x rekordbox` (30 s timeout). `dj status` reads a snapshot and reports `running: null` when the process check cannot answer. `dj tidy apply/undo` refuse with exit 1 when it cannot answer. No default master.db location on Linux. README has the Claude Desktop config path per OS.
- **W-21.** The gate for the older commands is `dj.write_gate` over `dj.gate.Gate(REPO_ROOT/state)`; design in `docs/prompts/plans/W-21.md`. A `dj tree` plan with a CONFLICT gets no id. An id is consumed only when something was written. A dry-run of a plan whose id was used issues a fresh id (the DJ may have undone the write); a replay of the used id stays refused. `--power-mode` and the platform are checked before the id and before any read; off Windows the master.db commands refuse up front in one line. `dj push` and `dj build` ask for the Spotify write scope only after the gate passed. The dry-run's last line now names the write flags. MCP previews for push, build and tidy gained `name`, `include_ambiguous`, `strict` so their arguments can match the write; new read tool `dj_tidy_undo_preview`. The hook runs through `uv run --no-project` (exec form, `onFailure: block`, fails closed). `dj library use <folder>` stores the library folder for the engine.
- **W-22.** Pages are cut by `page_size` and by a budget of about 12 000 characters of items, so `paging` carries `from` and `to` as well as page, pages, total; paged tools return compact JSON. Write tools trim their lists to the first page and name the file with the full list (`rest_in`). `dj_structure_preview` pages the 60 rows the CLI returns. Bare-name lookup applies to any relative path (folders: `tracklists/`, `plans/`, `exports/`) and the not-found message says where it looked. `dj.activity_log.log_write` writes to the configured library's `log.md`, else the repo's; it never raises (a warning on stderr instead), and the line comes back as `log` in the JSON. Not logged: `dj pull`, `dj analyze` (Spotify census), `dj tidy audit`, `dj library use`. Also in this commit: two extra W-21 gate tests (a refused write prints nothing on stdout; a push whose tracks the DJ removed on Spotify adds them back with a new preview id).
- **W-23.** Genres and keys filter and score (key = same Camelot code or a neighbour); My Tags only score (the XML has none). Anchors are always in the crate unless vetoed. Tracks without a BPM are never candidates; a second copy of a track is skipped. Too few picks raises `NotEnoughTracks` naming what to widen. Without `taste/facts.json` the taste facts are measured from the export. If the DJ's tree has a top-level `Crates` folder the XML uses its spelling; a same-named crate there blocks the preview. A crate already written is blocked like a build. `crates/<slug>.md` holds the full picks and spares tables (the crate record) under a summary of at most 5 lines. R-702 for proposals: `dj library build` leaves never-propose tracks out of filled playlists and reports `vetoed`; never-pair does not apply to whole-playlist moves. The MCP preview lists every pick in pages (`--picks-limit 0`); the CLI JSON default stays 30.
- **W-24.** An answer the question does not take raises `BarberError` and writes nothing. Every answer that adds a taste line also adds one `log.md` line. "keep" (veto) and "good" (pair) answers are recorded under the same key and lift an earlier veto. A/B keys hold the two ids in id order; a changed answer becomes an `updated:` line. `plan_session` also takes `skip`, `vetoes` and `source`. Free text is bounded (lane name 60, gig remark 300 characters). The barber's MCP tools carry no preview id: they append the DJ's own answers to text files in the library folder (D-20, proposed).
- **W-25.** Design and audit: `docs/prompts/plans/W-25.md`, `docs/spotify-audit.md`. When the configured library folder's `links.yaml` holds a link, the inbox loop runs there: `plans/`, `wishlist/`, `reports/apply/` visible; inbox and state under `.cache/`; the repo's `state/` is read until the first library apply. Plans keep local file paths (candidates), so the library `.gitignore` gets `plans/*.plan.json` (append-only) and `plans/.gitignore` (R-905 holds). The shopping list reads the newest plan's MISSING items (a newer pull is flagged `stale_plan`) and is a derived text file without a preview id (D-20). MCP sync plan and tracklist tools resolve files in the library folder or the repo (`library_file`); tidy plans stay in the repo. `.env` stays in the repo root, never in the library folder. R-801 and R-805 acceptance (a DJ completes setup; a live run) are live checks.
