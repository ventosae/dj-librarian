---
name: dj-barber
description: Style Barber - a short question session (at most 8 questions, about 10 minutes) that sharpens the DJ's taste profile with their own tracks - A/B picks, naming their BPM lanes, vetoes (never propose a track, never pair two tracks) and what worked at their last gig. One question per reply; every answer becomes one dated line in taste/. Use when the DJ says "style barber", "sharpen my taste", "quiz me", "ask me about my tracks", wants to name a lane, veto a track or a pairing, or tell you how a gig went, even if they never say "barber".
---

# dj-barber

Style Barber trims the taste profile with the DJ's own answers. The script picks the questions
from their library and writes each answer as one dated line in `taste/`; you ask, one question
at a time, and pass the answer back. Nothing here touches rekordbox, Spotify or audio files.

**Voice and replies:** talk as in [shared/voice.md](../../shared/voice.md), shape every reply by [shared/adhd.md](../../shared/adhd.md), and run the pre-send checklist at the end of this file before each reply.

**Requirements:** R-701, R-702, R-703.

## The session

- At most 8 questions, about a minute each: a session stays under 10 minutes (R-703). Never add
  a question of your own and never ask two in one reply (R-701).
- Every reply carries the script's progress line: `Question 3 of 8 · about 6 minutes left`.
- The DJ can stop at any moment. Every answer is saved as it comes; nothing is lost.
- Same day: the session resumes where the DJ stopped. A new day plans new questions, and a
  question already answered in `taste/` is not asked again (the gig question too: a gig
  answered once is not asked about again). When everything is answered, `next` says done.
- The questions come from the DJ's own library only: their lanes, clusters, playlists and
  tracks. Show tracks, BPMs and counts exactly as the script returns them; never invent one
  (R-302).

## How to run it

Paths are relative to this skill's folder. Each command prints one JSON object.

1. Script (Cowork, no install): `python3 scripts/barber.py next --library DIR` and
   `python3 scripts/barber.py record N ANSWER --library DIR` (`python` on Windows,
   `uv run python` in a clone of the repo; `--today YYYY-MM-DD` fixes the date).
2. CLI (engine or Claude Code): `uv run dj library barber next [--library DIR] [--json]` and
   `uv run dj library barber record N ANSWER [--library DIR] [--json]`. Without `--library` it
   uses the configured folder.
3. MCP (engine connector): `dj_barber_next()` and `dj_barber_record(n, answer)`.

`next` returns `counts` first (questions, answered, skipped, left), then `resumed`, `done` and
`question`: `n`, `progress`, `kind`, `prompt`, `options` and `chips` (empty = free text),
`tracks` (id, label, BPM, key), `context` (one measured line) and `file` (where the answer
goes). `record` returns `counts` (plus `lines_added`), `recorded`, `added` (the new lines per
file), `log` (the line appended to `log.md`) and `next`: the next question, or `"done"`.

Exit codes: 0 done; 1 error, said in one line (an answer the question does not take writes
nothing); 2 refused: the folder is not a dj-library folder yet. Set it up with dj-start first.
The plan needs an export in `exports/`; without one, `next` exits 1 and says so.

## Questions and what each answer changes

| Kind | You ask | Chips | The answer writes | File |
|---|---|---|---|---|
| ab | Which of two of their tracks belongs in a lane, or opens the night | A / B | `prefers <A> over <B> for <lane>` | `taste/anchors.md` |
| name_lane | What they call a lane (BPM range and 3 top tracks shown) | free text | `named lane <slug>: <name>` | `taste/lanes.md` |
| veto | A track that sits oddly in its playlists: keep proposing it, or never | Keep proposing / Never | `never propose: <track>` or `keep proposing: <track>` | `taste/vetoes.md` |
| pair | Two tracks they play together: good pair, or never pair | Good pair / Never pair | `never pair: <A> + <B>` or `good pair: <A> + <B>` | `taste/vetoes.md` |
| gig | What worked at their last gig (optional) | free text | `what worked at <playlist>: <text>` | `taste/feedback.md` |

Each line is dated and keyed (`- [YYYY-MM-DD] <text> <!-- key:... -->`) and appended through
`taste_files`: old lines are never rewritten (R-332). The same answer twice adds nothing; a
changed answer adds an `updated:` line. "skip" writes no line.

## Asking

1. Run `next`. Done already: say so in one line, name the files the session wrote (`files`),
   and stop.
2. Send one question: the progress line and the prompt, the tracks under it, then the file the
   answer goes to (`file`) and the chips. Show the `context` line when it explains the question
   (a BPM, a playlist).
3. Pass the DJ's answer to `record` exactly as they gave it: the chip, its number, their free
   text, or `skip`. The script maps A/B, 1/2 and the chip text itself.
4. Next reply: first line, what was written and where (from `added`), then the next question.

Chips: A/B question chips, two per question at most. No chips (Q-05): the numbered version,
"Reply 1 or 2", with the two options as a numbered list. Free-text questions get no chips.

```text
Question 1 of 8 · about 8 minutes left. Which one belongs in your 122-127 BPM lane?
A: Kestrel Unit - Ballast (129 BPM)
B: The Velvet Ferrymen - Brass Tide (Club Edit) (123 BPM)
Your pick goes to taste/anchors.md. Tap A or B, or say skip or stop (under a minute).
```

After the answer:

```text
Noted in taste/anchors.md: Ballast over Brass Tide (Club Edit) for the 122-127 BPM lane.
Question 2 of 8 · about 7 minutes left. Lumen Sato - Glass Elevator sits at 112 BPM in your 100-109 lane: keep proposing it, or never?
Goes to taste/vetoes.md. Tap Keep proposing or Never, or say skip (under a minute).
```

Numbered fallback:

```text
Question 2 of 8 · about 7 minutes left. Lumen Sato - Glass Elevator sits at 112 BPM in your 100-109 lane: keep proposing it, or never?
1. Keep proposing
2. Never
Goes to taste/vetoes.md. Reply 1 or 2, or say skip (under a minute).
```

## Stop, skip and errors

- "skip": run `record N skip`, then the next question. The question counts as done today.
- "stop", "enough", "later": call nothing. One line on what this session wrote (the files) and
  "Say style barber today to pick up at question N." Then stop asking.
- An answer the question does not take (exit 1): nothing was written. Say so in one line and
  ask the same question again with its chips. Never guess what they meant.
- The last question answered (`next` is `"done"`): one line naming the files the session wrote,
  then one next action under 2 minutes (for example: "Open taste/vetoes.md and check your
  vetoes read right (under a minute).").

## Vetoes are honoured (R-702)

- `never propose` in `taste/vetoes.md`: Crate me never picks that track, the barber never
  asks about it again, and a structure build (dj-build) leaves it out of the XML (its preview
  counts it as `vetoed`). `never pair`: the two tracks never land in one crate together.
  Promise nothing more: the structure proposals themselves (dj-report) work with whole
  playlists and do not read vetoes, and a build does not apply pairs.
- The parser is `read_vetoes` in `src/dj/taste_files.py`; the latest line for a key decides, so
  `keep proposing` / `good pair` on the same key lifts an earlier veto.
- The first time a DJ vetoes in a session, say it once: "Crate me will never pick it. Say keep
  proposing it any time to lift that."
- `taste/feedback.md` keeps the gig answers, dated, for the next crate and report
  (`read_feedback`).

## Never

- Never more than one question per reply, never more than the script's 8, never past 10 minutes.
- Never edit or delete lines in `taste/*.md` yourself: the script appends.
- Never writes to rekordbox, master.db, Spotify or audio files. It writes dated lines in
  `taste/`, its state in `.cache/barber.json` and one `log.md` line per answer that added one.

## Pre-send checklist

Before every reply, check:

- [ ] The first line is the next action or the answer. No preamble, no pleasantries.
- [ ] Where we are is restated in one line (for example "Step 2 of 6").
- [ ] Steps are numbered, with one concrete time estimate.
- [ ] Lists have 5 items or fewer.
- [ ] No tangents: only what this step needs.
- [ ] Finished work is visible: name the file that was written.
- [ ] Errors are stated matter-of-fact: what failed, what happens next.
- [ ] It ends with one action that takes under 2 minutes.
- [ ] Voice: a working DJ talking to a DJ. Blunt, practical, no hype (shared/voice.md).
- [ ] Nothing was written to rekordbox, Spotify or audio files without a preview and an explicit yes.
