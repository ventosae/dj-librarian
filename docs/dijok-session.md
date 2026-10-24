# Dijok session — run sheet (W-28)

About 75 minutes. Dijok drives; Anton writes, out of the room by screen share for steps 1–3 and the engine install. Pass marks: `docs/requirements.md` §7; live checks: `docs/plan.md` Q-24.

## Before (Anton, about 20 minutes)

- [ ] Zip built from `main` (`uv run python scripts/build_plugin_zip.py`) and uploaded in his Claude app (Customize → Plugins → Add → Upload plugin). Refused? Rebuild with `--flat`.
- [ ] A new Cowork task open, not a chat. Folder name agreed: `dj-library`, new and empty.
- [ ] Noted: Mac or Windows ____ · rekordbox version ____ · rekordbox playlist count ____
- [ ] Screen share tested; `docs/samples/reports/sample-library.html` open on your laptop.

## During (under 15 minutes to the report, NFR-01)

Leave before "start", watch by screen share, come back at the coffee line in step 4 (A-01). Every reply: `Step N of 6 · <time>` first, at most one question (step 1 asks two), under 5 lines until the report.

| Step | Expected reply | Budget | Took |
|---|---|---|---|
| 1 Hello | Mac / Windows chips + "What do they call you in the booth?" | under 1 min | |
| 2 Export | 3 numbered lines for his OS, ends "say done" | about 2 min | |
| 3 Folder | Connect a folder, drop the XML; then "Created n …" | about 1 min | |
| 4 Working | "Go make a coffee." + 5 tasks ticking | about 5 min | |
| 5 Report | File card `reports/<date>-library.html` | 5 min to read | |
| 6 Next | One chip per proposal + "not yet"; engine offer last | under 2 min | |

- [ ] His actions before step 4: ____ (R-106: at most 3; a re-export or a permission click counts).
- [ ] No question in steps 4–5; widgets or the numbered fallback (Q-05); stalls: minute, step.

Do not help with:

- Exporting, Fixing anything (file, folder, error), Explaining the report: his questions go to Claude.
- Step in only if he is stuck over 5 minutes or a write comes without a yes; that check fails.

## After (same sitting)

- [ ] A-01 export and folder without Anton in the room, at most 3 actions.
- [ ] A-02 the report in the same sitting; minutes from hello ____
- [ ] A-03 he picks a proposal, says yes, imports `proposals/<slug>.xml`; the playlists appear.
- [ ] A-04 rekordbox unchanged before his import; audio untouched; each build or crate XML follows his yes (the analysis log lines need none).
- [ ] A-05 the profile sounds like him (question 1).
- [ ] A-06 engine from the card, without Anton in the room; `dj_status` answers; add path (Q-08).
- [ ] A-07 a crate he'd play; a Barber line in `taste/`; Spotify set up without Anton, `dj pull` works.
- [ ] A-08 Anton watched it all; lessons written; in `docs/plan.md` W-28 Done, R-106 from the tally.
- [ ] R-1003 (a reply vs `adhd.md`, `voice.md`), Q-16 (two XMLs imported), Q-24; Mac: Q-02, Q-25.

Lessons in `docs/lessons.md` (dated, no names): minutes per step, misread replies verbatim, widgets, zip layout, the import, any write without a yes.

Ask, in this order, and write down his words:

1. Does the profile sound like you?
2. Which proposal would you build?
3. What did you not understand?
