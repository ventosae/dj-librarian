# Breadboard — DJ ↔ dj-librarian interaction (v0.1)

Agreed 2026-10-20 (D-10). Shape Up style: Places (where the DJ is), Affordances (what they see / can do), Connections (what moves them on). Behind each place: the work the tool does unseen.

Principle: **super short start, loaded output.** The DJ makes ≤ 3 moves and waits once. The first thing of substance they see is the HTML report. Everything else (engine install, builds, crates, Spotify) comes after the wow, one next action at a time.

## Session 1 — from zero to the report

```
P0 Plugin ──► P1 Hello ──► P2 Export ──► P3 Folder ──► P4 Working ──► P5 Report ──► P6 Next
  (installed)  (1 tap)      (2 min)       (1 action)    (wait, ~5 min)  (open HTML)   (1 tap)
```

| # | Place | DJ sees (affordances) | DJ does | Behind the curtain | Widget |
|---|---|---|---|---|---|
| P0 | Plugin installed | Nothing yet. (Optional: Project instructions pasted from the template.) | Types anything ("hi", "sort my library") | Skill `dj-start` triggers; voice + ADHD rules load with it | — |
| P1 | Hello | One line in the voice + a question: **Mac or Windows?** Two chips. | Taps one | Device recorded for the session | Question widget (chips) |
| P2 | Export | One card: 3 numbered steps for their OS to export the collection XML (File → Export Collection in xml format → save). "About 2 minutes." | Does the 3 steps | — | Checklist card (numbered, ≤ 5 lines) |
| P3 | Folder | One line: connect a folder in Cowork; drop the XML in it. | Connects folder, drops file | Folder detected; `dj-library/` scaffold written; XML moved to `exports/`; `library.yaml` written | Connected-folder prompt |
| P4 | Working | Task list: 5 steps ticking (read collection → profile → structure → taste → report). One line: "About 5 minutes. Go make a coffee." No questions asked. | Waits | `dj-profile`, `dj-structure`, `dj-taste` run on the XML; MD files written; `dj-report` renders HTML | Task list widget (progress) |
| P5 | Report | The HTML opens in the side panel. 4 sections: who you are; how it's built (graph); 3 ways to rebuild it, each with a trigger prompt; one next action. | Reads, scrolls | File card delivered; copy saved to `reports/` | File / artifact card |
| P6 | Next | One line, one action under 2 minutes: "Pick one: say *Build me the ___ structure*." Or, for builds on live data: "Install the engine (10 min) — say *set me up*." | Taps / types | — | Question widget (3 proposal chips + "not yet") |

Rules for session 1:
- Zero questions between P3 and P5. If something is missing, finish with what there is and say what was missing at P6.
- Every reply states step N of 6 and a time estimate (ADHD rules 5, 6).
- The report is the first long thing the DJ reads. Chat stays under 5 lines until then.

## Session 2+ — one feature per visit, same shape

```
Trigger prompt ──► Preview ──► Yes? ──► Output file ──► Import card ──► Next
```

| # | Place | DJ sees | DJ does | Behind | Widget |
|---|---|---|---|---|---|
| B1 | Build (from P6 chip or typed prompt) | Preview: the tree as it will be, CREATE / SKIP per node, where existing playlists land. "Nothing written yet." | Reads | `dj-build` diff vs `current-tree.yaml` | Diff card |
| B2 | Gate | Direct question: **Write the XML?** Yes / Change / Stop. | Taps Yes | — | Question widget |
| B3 | Output | `proposals/<name>.xml` written. Import card: 3 steps for their OS (Preferences → Advanced → Database → rekordbox xml → pick file → drag playlists in). | Imports in rekordbox | `log.md` line appended | Checklist card |
| B4 | Next | "Open rekordbox, check the tree. Then: *Crate me 50 for Saturday*." | — | — | Question widget |
| C1 | Crate me | Asks one thing only if needed (event or vibe; size chips 30 / 50 / 70). Then preview list with one-line reasons, spares marked. | Picks, reads | Spec from the brief; selection by code from `taste/` + fields | Chips + list card |
| C2 | Gate → Output | Same as B2–B3; `proposals/crate-<name>.xml` + `crates/<name>.md`. | | | |
| S1 | Style Barber | One question per turn, ≤ 10 min, progress stated. A/B picks from their own tracks. | Taps | `taste/` files updated, dated | Question widget (A/B chips) |
| M1 | Engine install | Only when the DJ asks or a feature needs it (live DB read, Spotify, tidy). 3-step card per OS (install `uv`, enable the plugin's connector, set write tools to ask-every-time), "about 10 minutes", then `dj_status` as the proof. | Installs | MCP connector runs on their computer | Checklist card |
| Y1 | Spotify setup | Only on request. Card: Premium check, create your app, paste two keys into `.env`. "About 8 minutes." | Follows | `dj pull` as proof | Checklist card |

## Open

- Which widgets Cowork renders for a non-Anton user (question chips, task list, file card) — verify in build; fall back to numbered text (Q-05).
- XML scope check: does the export carry My Tags and history? If not, the first report says so and offers M1 as the way to get them (Q-01).
