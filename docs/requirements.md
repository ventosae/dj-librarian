# dj-librarian — Requirements

| | |
|---|---|
| Version | 0.4 |
| Date | 2026-10-20 |
| Owner | Anton |
| Status key | Proposed → Agreed → Built → Verified |
| ID scheme | R-xyz requirement (x = epic), C-xx constraint, NFR-xx non-functional, A-xx acceptance, OD-xx open decision |
| Priority | MoSCoW. Anton 20 Oct: every v0.1 function is Must. |

Change log: 0.1 first draft (19 Oct). 0.2 numbered BA structure. 0.3 all v0.1 functions Must; XML-export-first start (D-10). 0.4 (20 Oct): moved into the repo (authoritative copy); OD-03 and OD-05 closed; C-10 revised, C-11 and R-107 added; Cowork install path verified.

## 1. Vision

V-1. A DJ librarian you talk to. It learns how a DJ already works from their own rekordbox library, tells them who they are as a DJ, shows how the library is built today, proposes structures that fit their patterns, builds crates for a night, sharpens their taste profile, and keeps Spotify discoveries flowing into owned files. It only proposes; the DJ decides and pulls the trigger. Everything it learns is text the DJ owns (library as code), so the profile grows over time and the same files feed the app later. Open source.

## 2. Personas

| ID | Persona | Notes |
|---|---|---|
| P-1 | **Dijok** — the v0.1 test DJ | Experienced, performs a lot, has taste, messy library, ADHD, not technical. Has Cowork. OS and rekordbox version unknown → `dj-start` asks (R-101) and the flow branches. |
| P-2 | **Anton** — operator and builder | Runs the project, watches the first session, maintains the repo. Windows, rekordbox 7.2.x. |
| P-3 | **Contributor** | Stranger who clones, installs, runs tests, opens a PR. |

## 3. Release map

| Release | Name | Contents |
|---|---|---|
| v0.1 | Dijok edition | Epics E1–E13, all Must. Build order follows the breadboard: first-contact path first, engine and features after. |
| v0.2 | — | Set builder from a brief; Lexicon adapter; tidy on Mac |

## 4. Constraints and assumptions

| ID | Constraint / assumption | Source |
|---|---|---|
| C-01 | rekordbox is the source of truth. The tool only creates and adds; never deletes, renames, moves or reorders existing items. | CLAUDE.md |
| C-02 | Writes to rekordbox, Spotify or audio files happen only after preview → direct question → explicit yes. Silence or "sounds good" is not a yes. | project instructions |
| C-03 | The MCP engine runs on the DJ's machine (Mac or Windows). In Cowork it loads as the plugin's "Runs in each session" connector when the session runs on that computer; it can also be registered in Claude Desktop's config. | Anton 19 Oct; claude.com/docs/plugins/overview |
| C-04 | The DJ installs the plugin (shared code); the DJ's state lives in a connected `dj-library/` folder. A Cowork Project is an optional template the DJ pastes (R-107). | Anton 19–20 Oct |
| C-05 | Nothing personal in the repo: no credentials, tokens, library paths, playlists, inbox data, real users' names. Example configs instead. | dev_standard |
| C-06 | Spotify (Feb 2026 Web API dev mode): each DJ needs their own Spotify app (1 client ID), the app owner needs Spotify Premium, max 5 users per app, search limit 10, `popularity` and other-user playlist endpoints removed. | developer.spotify.com migration guide |
| C-07 | pyrekordbox is tested to rekordbox 7.0.9; installed rekordbox is 7.2.x. Every DB write is risky. | CLAUDE.md |
| C-08 | Voice from *How to Be a DJ* (Chuck Fresh, 2004) is style only. No passages or quotes reproduced. | IP |
| C-09 | ADHD reply rules come from the i-have-adhd skill (ayghri, MIT). Attribution kept. | Anton 19 Oct |
| C-10 | Cowork loads a plugin's skills, commands, agents and MCP connectors; hooks are not listed as a Cowork component. The write gate in Cowork is therefore the per-tool permission ("ask every time") plus the XML-import-by-DJ path. In Claude Code a PreToolUse hook (exit 2 or `permissionDecision: deny`) adds a hard gate on `mcp__plugin_dj-librarian_*__*_apply|*_write` without a plan id. | claude.com/docs/plugins/overview; code.claude.com/docs/hooks |
| C-11 | Install path for a DJ: Claude desktop app → **Customize → Plugins → Add → Add marketplace** with the GitHub URL (public repo, or private via the Claude GitHub App), or **Add → Upload plugin** (.zip of `plugin/`) for private testing before the repo is public. | claude.com/docs/plugins/overview |
| A-C1 | Assumed: pyrekordbox finds master.db and its key on macOS. **Unverified** — confirm in the Mac PR. | recall |

## 5. Requirements

### E1 Onboarding (`dj-start`) — see breadboard.md

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-101 | Ask the DJ's device (Mac / Windows) first, as chips, and branch every later step on it. | M | First reply asks device; later steps show only that OS. | Built | v0.1 |
| R-102 | Engine install (MCP on the DJ's machine) is offered **after** the first report, when a feature needs it; numbered steps per OS, ≤ 10 min; `dj_status` as the proof. | M | Dijok completes it without Anton; `dj_status` answers. | Agreed | v0.1 |
| R-103 | Guide the DJ to connect a `dj-library/` folder in Cowork and scaffold it (R-901). | M | Scaffold exists; `library.yaml` records device, rekordbox version, date. | Built | v0.1 |
| R-104 | **First-contact input is the rekordbox XML export** (File → Export Collection in xml format), guided by a 3-step card, dropped into the connected folder. | M | Analysis + report run on the XML alone. | Built | v0.1 |
| R-105 | Onboarding states time estimates and progress ("Step 2 of 6") on every turn. | M | Every onboarding reply has both. | Built | v0.1 |
| R-106 | Super short start: ≤ 3 DJ actions before the work phase; zero questions during the work phase; chat under 5 lines until the report (NFR-07). | M | Transcript of the Dijok session. | Agreed | v0.1 |
| R-107 | Cowork Project template (`templates/project/instructions.md`) the DJ can paste into a new Project: voice, ADHD rules, safety, folder conventions. Optional; nothing essential depends on it. | M | Template exists; the flow works without it. | Agreed | v0.1 |

### E2 Library access

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-201 | Read master.db read-only through the engine on Mac and Windows, with rekordbox open. | M | `dj_status` returns counts on both OS with rekordbox running. | Built | v0.1 |
| R-202 | Read from a snapshot copy of master.db, never the live file. | M | Live file never opened for read; snapshot path logged. | Built | v0.1 |
| R-203 | Mac port: process check without `tasklist.exe`, DB discovery under `~/Library/Pioneer/rekordbox`, path handling, Claude Desktop config path on macOS. | M | Tests green on `macos-latest` and `windows-latest`; live `dj_status` on one Mac when a Mac tester appears. | Built | v0.1 |
| R-204 | One track/tree model fed by two readers: XML export and master.db. Fields: track metadata, playlist tree, smart playlists, ratings, colours, comments, date added; My Tags, play counts, history where the source has them. | M | Field list documented per reader; fixtures for each. | Built | v0.1 |
| R-205 | Direct master.db writes (`dj tree --apply`, `dj apply --apply`, `dj copy --apply`) stay Windows-only power mode behind an explicit flag. | M | Flag absent → command refuses with a one-line reason. | Agreed | v0.1 |

### E3 Analysis (`dj-profile`, `dj-structure`, `dj-taste`)

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-301 | Three separate skills; each learns from patterns the DJ already exhibits before suggesting anything. | M | Each SKILL.md names the patterns it reads first. | Built | v0.1 |
| R-302 | Measured facts come from code (deterministic, tested); words come from Claude. Each MD file states which is which. | M | Every number has a script origin; tests cover the scripts. | Built | v0.1 |
| R-311 | `dj-profile`: collection size, formats and bitrates, eras, date-added timeline, use of genre / BPM / key / rating / colour / comment fields, empty fields, duplicate candidates. | M | `profile/stats.md` from a fixture library. | Built | v0.1 |
| R-312 | `dj-profile`: narrative "who you are as a DJ" in the DJ's own vocabulary, ≤ 1 page. | M | `profile/habits.md`; Dijok says it sounds like him (A-05). | Built | v0.1 |
| R-321 | `dj-structure`: tree depth and width, naming conventions, playlist sizes, overlap (Jaccard), orphans, dead or empty playlists, smart vs plain. | M | `structure/analysis.md` + graph data from a fixture. | Built | v0.1 |
| R-322 | `dj-structure`: export the real tree as `structure/current-tree.yaml` (library as code). | M | YAML round-trips to the same tree in a test. | Built | v0.1 |
| R-331 | `dj-taste`: label and artist clusters, BPM lanes per playlist, key preferences, co-occurrence across playlists (personal prior), top-rated / most-played, 1–3 anchor tracks per cluster, the DJ's own naming vocabulary. | M | `taste/lanes.md`, `labels-artists.md`, `anchors.md`, `vocabulary.md` from a fixture. | Built | v0.1 |
| R-332 | `dj-taste` files are appended and refined across sessions, never regenerated from scratch without asking. | M | Second run preserves prior entries; diff shown. | Built | v0.1 |
| R-341 | Analysis never writes to rekordbox, Spotify or audio files. | M | Test: analysis opens no write session. | Built | v0.1 |

### E4 Library report (`dj-report`) — the wow

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-401 | One self-contained HTML file `reports/<date>-library.html`, opens offline, opens in Cowork's side panel. | M | No external requests; renders from the folder. | Built | v0.1 |
| R-402 | Section 1: DJ profile narrative + the 5 stats that matter. | M | Present; lists capped at 5. | Built | v0.1 |
| R-403 | Section 2: small graph of the current structure (tree) and playlist overlap, with what it reveals (dumps, duplicates, orphans). | M | Graph renders from `structure/` data. | Built | v0.1 |
| R-404 | Section 3: two or three named restructure proposals; each: name in the DJ's vocabulary, one-line principle, sketch tree, where existing playlists land, cost in minutes, trigger prompt (e.g. "Build me the African Bass Telepathy structure"). | M | Six parts each; trigger prompt works with `dj-build`. | Built | v0.1 |
| R-405 | Proposal families: Bases (genre base → inbox / crates / sets), Facets (5–8 shallow genre buckets + My Tag Role / Body / Vibe / Status + gig crates), Gig-first (crates per residency or event + archive). The DJ's patterns pick which and how named. | M | Picking rules documented in the skill. | Built | v0.1 |
| R-406 | Section 4: one next action under two minutes. | M | Present. | Built | v0.1 |
| R-407 | Report written in the voice (R-1001) and passes the ADHD rules (R-1002). | M | Checklists pass. | Built | v0.1 |

### E5 Build a structure (`dj-build`)

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-501 | A trigger prompt produces `proposals/<name>.yaml` (tree as code) and a preview diff against the current tree. | M | Preview lists CREATE / SKIP per node; nothing written yet. | Built | v0.1 |
| R-502 | After an explicit yes, write `proposals/<name>.xml` (rekordbox XML) and show per-OS import steps (Preferences → Advanced → Database → rekordbox xml; drag in). | M | XML validates with pyrekordbox; rekordbox imports it on Mac and Windows. | Built | v0.1 |
| R-503 | Playlists in the XML pre-filled from existing playlists where the proposal maps them; tracks referenced by location. | M | Imported playlists contain the mapped tracks. | Built | v0.1 |
| R-504 | master.db is never written by `dj-build`. | M | Test: no write session opened. | Built | v0.1 |
| R-505 | Every build appends a line to `log.md` (R-904). | M | Line present after build. | Built | v0.1 |

### E6 Crate me

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-601 | From a brief (event or vibe; size chips 30 / 50 / 70), select tracks from the DJ's own library. | M | Exactly N owned tracks, one-line reason each. | Agreed | v0.1 |
| R-602 | Claude turns the brief into a structured spec; code selects and orders from `taste/` (lanes, anchors, co-occurrence, vetoes) and rekordbox fields (BPM, key, rating, My Tags); Claude writes the reasons. | M | Selection reproducible from the spec. | Proposed | v0.1 |
| R-603 | Preview → yes → `proposals/crate-<name>.xml` for import (R-502) + `crates/<name>.md`. | M | Files produced; rekordbox imports the playlist. | Agreed | v0.1 |
| R-604 | Spares: +20% tracks across energy levels, marked as spares. | M | Spares listed separately. | Proposed | v0.1 |

### E7 Style Barber

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-701 | Interactive session that sharpens the taste profile: one short question per turn, A/B picks from the DJ's own tracks, naming of lanes, vetoes. | M | A session updates ≥ 1 `taste/` file with dated entries. | Agreed | v0.1 |
| R-702 | `taste/vetoes.md` (never pair / never propose) and `taste/feedback.md` (what worked at a gig), honoured by Crate me and proposals. | M | A vetoed track never appears in a crate. | Proposed | v0.1 |
| R-703 | ≤ 10 minutes per session; progress stated. | M | Transcript check. | Agreed | v0.1 |

### E8 Spotify sync + shopping list

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-801 | Guided Spotify setup for a new DJ: Premium check, create their own app, scopes, `.env` — numbered steps per C-06. | M | Dijok completes it without Anton; `dj pull` works. | Agreed | v0.1 |
| R-802 | Inbox loop for any DJ: `pull → match → plan → yes → apply → log → wishlist`; links and crate paths in the DJ's `dj-library/links.yaml`. | M | Tests pass with repo paths removed; live run on Anton's library. | Agreed | v0.1 |
| R-803 | Shopping list: missing tracks → `wishlist/<crate>.shopping.md` with Beatport / Bandcamp links, label, BPM / key. | M | File produced for one crate. | Agreed | v0.1 |
| R-804 | `spotify.py` audited against the Feb 2026 endpoint changes (`/items`, batch removal, search limit 10, removed fields). | M | Audit note; failing calls fixed; tests updated. | Proposed | v0.1 |
| R-805 | `dj build` (tracklist → Spotify) and `dj push` available to any DJ with their own app. | M | Live run by Anton. | Agreed | v0.1 |

### E9 Library as code (`dj-library/`)

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-901 | Scaffold: `README.md`, `library.yaml`, `exports/`, `profile/`, `structure/`, `taste/`, `crates/`, `reports/`, `proposals/`, `wishlist/`, `links.yaml`, `log.md`. Text only. | M | Created by `dj-start`; documented in README. | Built | v0.1 |
| R-902 | `library.yaml`: device, rekordbox version, dates, chosen structure, schema version. | M | Schema test. | Built | v0.1 |
| R-903 | `structure/current-tree.yaml` and `proposals/*.yaml` share one tree schema (today's `bases.yaml` shape). | M | One loader for both. | Built | v0.1 |
| R-904 | The tool, not Claude, appends `log.md` lines (date, action, counts, file). | M | Every writing command appends. | Agreed | v0.1 |
| R-905 | Folder is git-initialisable; nothing machine-specific outside `library.yaml`. | M | `git init` + commit works; no absolute paths elsewhere. | Built | v0.1 |

### E10 Voice and ADHD UX

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-1001 | `voice.md`: Chuck Fresh style guide — first-person working DJ, blunt, practical, unsentimental, war-story examples, "smart music programmer" stance — with our own do / don't examples. No book text (C-08). | M | Every skill references it; a reviewer finds no book text. | Built | v0.1 |
| R-1002 | `adhd.md`: the 10 i-have-adhd rules (lead with next action; number steps; end with one < 2-min action; no tangents; restate state; concrete time estimates; make finished work visible; matter-of-fact errors; cap lists at 5; no preamble or pleasantries). | M | Pre-send checklist in each SKILL.md. | Built | v0.1 |
| R-1003 | Every report, MD file and chat reply passes both checklists. | M | Spot check on 3 outputs. | Agreed | v0.1 |

### E11 Write-safety (product feature)

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-1101 | Read tools and write tools are separate MCP tools; write tools default to "ask every time". | M | Tool list shows the split; install steps set permissions. | Built (Windows) | v0.1 |
| R-1102 | Every write has a preview tool; the write tool refuses without a plan or preview id. | M | Test per writer. | Proposed | v0.1 |
| R-1103 | Power-mode DB writes: rekordbox-closed check, verified backup, one commit, rollback on error, undo where possible. | M | Existing tests kept green. | Built | v0.1 |
| R-1104 | Tests for every component that writes to rekordbox, Spotify or audio files, including the XML writer. | M | CI enforces. | Agreed | v0.1 |
| R-1105 | A real gate blocks writes without a yes: in Cowork, tool permission "ask every time" + XML import by the DJ; in Claude Code, additionally the plugin PreToolUse hook (C-10). | M | Hook test in Claude Code; permissions step in onboarding. | Proposed | v0.1 |

### E12 Open-source dev standard

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-1201 | Semantic versioning; `CHANGELOG.md`; tags on release (consent gate). | M | v0.1.0 tag after Anton's yes. | Agreed | v0.1 |
| R-1202 | Conventional commits; one branch and one PR per change. | M | Git history shows it. | Agreed | v0.1 |
| R-1203 | CI on every PR: tests on `windows-latest`, `macos-latest`, `ubuntu-latest`; `claude plugin validate ./plugin --strict`; ruff; secret scan. | M | Green CI on the first PR. | Agreed | v0.1 |
| R-1204 | `README`, `CONTRIBUTING`, `LICENSE` (Apache-2.0, D-12), `examples/.env.example`, `examples/*.example.yaml`. | M | A stranger installs from README. | Agreed | v0.1 |
| R-1205 | Issues are the backlog; plan.md "Later" items become issues. | M | Issues created on first push. | Agreed | v0.1 |
| R-1206 | Personal data removed: STATE.md, log.md, CRATES.md, links.yaml, tidy.yaml, bases.yaml, tree.yaml, tracklists/, wishlist/, Claude outputs/, settings.local.json ignored in place; "Anton" out of code, tool descriptions, skills, tests, README; paths parameterised. | M | `git grep -il anton -- src tests plugin README.md CONTRIBUTING.md examples` finds nothing. | Agreed | v0.1 |
| R-1207 | Plugin layout: `plugin/.claude-plugin/plugin.json`, repo-root `.claude-plugin/marketplace.json` (source `./plugin`), `plugin/skills/`, `plugin/.mcp.json`, `plugin/hooks/hooks.json`; no `bin/` (Cowork refuses it). | M | `claude plugin validate ./plugin --strict` passes. | Agreed | v0.1 |

### E13 Platforms

| ID | Requirement | Pri | Acceptance | Status | Release |
|---|---|---|---|---|---|
| R-1301 | Windows 11 + rekordbox 7.2.x. | M | Anton's machine. | Built | v0.1 |
| R-1302 | macOS + rekordbox 7.x. | M | CI green on macOS; live `dj_status` on the first Mac tester. | Built | v0.1 |
| R-1303 | `dj tidy` (audio files) on macOS. | C | — | Proposed | v0.2 |

## 6. Non-functional

| ID | Requirement | Pri |
|---|---|---|
| NFR-01 | Setup to first report under one hour for P-1 (target: under 15 minutes on the XML path). | M |
| NFR-02 | Analysis of a 10k-track library completes in under 5 minutes. | S |
| NFR-03 | MCP tool results stay under the tool-result limit: counts first, items paginated. | M |
| NFR-04 | No secrets printed, logged or committed; tokens only sent to `api.spotify.com`. | M |
| NFR-05 | Bare filenames resolve under their folder (`tracklists/`), example in the tool description. | S |
| NFR-06 | Research fan-out (subagents, web searches) bounded per task. | S |
| NFR-07 | ≤ 3 DJ actions and ≤ 5 minutes of DJ time before the work phase; no questions during it. | M |

## 7. Acceptance for v0.1 (the Dijok test)

| ID | Criterion |
|---|---|
| A-01 | Dijok exports the XML and connects the folder without Anton in the room (≤ 3 actions). |
| A-02 | Dijok gets `reports/<date>-library.html` in the same sitting. |
| A-03 | Dijok picks a proposal, imports the XML, and the playlists appear in rekordbox. |
| A-04 | Nothing in rekordbox changed before his import; nothing on disk changed without a yes. |
| A-05 | Dijok says the profile sounds like him. |
| A-06 | Dijok installs the engine after the report, without Anton; `dj_status` answers. |
| A-07 | Crate me produces one crate he would play; Style Barber updates `taste/` once; Spotify setup completes if he uses Spotify. |
| A-08 | Anton watches one session and logs lessons in `docs/lessons.md`. |

## 8. Open decisions

| ID | Decision | Owner | Status |
|---|---|---|---|
| OD-01 | Licence: Apache-2.0 (D-12). Can still change before the repo goes public. | Anton | Agreed by default 20 Oct |
| OD-02 | Crate me / Style Barber / Spotify priority. | Anton | Closed 20 Oct: all Must |
| OD-03 | Dijok's OS and rekordbox version. | Anton | Closed 20 Oct: unknown; `dj-start` asks; Mac live test opportunistic |
| OD-04 | Name the DJ-facing product (dj-librarian vs something in the voice). | Anton | Open |
| OD-05 | How the engine reaches Cowork. | Claude | Closed 20 Oct: plugin stdio MCP ("Runs in each session") works in Cowork sessions on the DJ's computer; Claude Desktop config is the alternative (C-03) |
| OD-06 | XML-export-first start, engine after the report. | Anton | Closed 20 Oct: agreed (D-10) |

## 9. Sources

`docs/breadboard.md`, `docs/architecture.md`, `docs/lessons.md`. Research (project docs): "How DJs Organize Vast Libraries"; "rekordbox Library Tools: Market Scan"; "How DJ Set Planners Build Sets"; operating-chat analysis 2026-10-19. External: i-have-adhd SKILL.md (ayghri, MIT); *How to Be a DJ* (Chuck Fresh, 2004) for voice; Spotify Web API February 2026 migration guide; Claude Code docs — plugin manifest reference, marketplace reference, hooks, install; claude.com/docs/plugins/overview.
