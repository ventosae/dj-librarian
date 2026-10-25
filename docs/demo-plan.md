# Demo plan — first session with Dijok (25 Oct 2026)

Door 1 only. The engine on a Mac has never run live; it is not part of tomorrow. The report and the XML import are the demo.

## Tonight (Anton, about 60 minutes)

1. Build the zip from `main`: `uv run python scripts/build_plugin_zip.py` → `dist/dj-librarian-plugin-0.1.0.zip`. (W-32 not needed for tomorrow.)
2. Dress rehearsal on your own Windows, **from the zip, not the clone**: Claude app → Customize → Plugins → Add → Upload plugin → the zip. New Cowork task on this computer, a new empty folder (not the old `dj-librarian` one), type **hi**, follow the six steps with a fresh rekordbox export. Watch for: chips rendering, the task list, the report opening as a file card, the three trigger chips. ~15 min.
3. Say the trigger for one proposal → yes → import the XML into your own rekordbox (Preferences → Advanced → Database → rekordbox xml). This is Q-16; it has never been done live. If the import fails, that section of the demo is "here is the XML" and nothing more. ~10 min.
4. Print `docs/handout/dj-librarian-a6.pdf` double-sided, A6 (or A4 "2 pages per sheet", cut). One for her, one for you.
5. AirDrop / message her the zip, or carry it on a stick.
6. Anything broke in 2 or 3 → paste it here; a fix prompt goes to the builder tonight.

## Before you start with her (5 minutes)

- Her Claude desktop app is installed, signed in, and has Cowork (Pro/Max/Team). If not, stop: no Cowork, no demo.
- rekordbox is open on her Mac with her real library. Note the version (Help → About).
- Agree the folder name: `dj-library` on her Desktop.
- Upload the zip on her machine (Customize → Plugins → Add → Upload plugin). Turn it on.

## The session (30–40 minutes, you don't touch her keyboard)

| Step | What she does | What you watch | Budget |
|---|---|---|---|
| 1 | New Cowork task on this computer, types **hi**, taps Mac, types her booth name | Chips render? Reply ≤ 5 lines? | 1 min |
| 2 | File → Export Collection in xml format → Desktop | Menu path right on her rekordbox version? | 2 min |
| 3 | Add folder → `dj-library` → drops the XML in | Folder prompt appears? | 2 min |
| 4 | Waits | Task list ticks; no questions asked; time it | 5–10 min (big library: longer) |
| 5 | Reads the report | Her face at the sleeve. Does she scroll? What does she say first? | 5 min |
| 6 | Picks a proposal, says the trigger, says yes, imports the XML | Preview shown before the write? Import works on Mac? | 10 min |

Don't help with wording. If she's stuck, note where, then say the card's line. If something fails, say "that's one for me", note it, move on.

## After (10 minutes)

Three questions, in this order, write her exact words:
1. Does the profile sound like you? What's wrong in it?
2. Which of the three would you actually build? Why that one?
3. What did you not understand?

Then: log A-01…A-08 pass/fail and the timings in `docs/lessons.md`; paste it all here. If she wants the engine (My Tags, Spotify), that's the next session, after the Mac installer (W-33).
