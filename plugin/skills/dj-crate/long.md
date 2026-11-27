# The long path: a playlist built with the DJ

For a DJ who names a seed track ("build me a set around Kestrel Unit - Ballast") or says "build it with me". Up to 4 questions, some digging on the web, then the same preview and the same two write questions as the fast path. About 10 minutes. The reply rules, the spec and the refusals are in SKILL.md; this file is only what is different.

## Tools

| What | Tool |
|---|---|
| Find a track in the catalog | `dj_query(sql)`: one SELECT, read-only, 200 rows a page. Tables `tracks`, `playlists`, `playlist_tracks`, `notes`. Look at the columns first: `SELECT * FROM tracks LIMIT 1` |
| Which candidates the DJ owns | `dj_match_tracks(candidates, crate="")`: `candidates` is a list of `"Artist - Title"` strings. Counts first, then `owned` (candidate, id, artist, title, bpm, key) and `missing` (candidate, Beatport and Bandcamp search links). With `crate=<slug>` it also writes `crates/<slug>.to-buy.md` |
| Preview and write | `dj_crate_preview(spec)`, `dj_crate_write(spec, preview_id)`, as in SKILL.md |

## Step 1 of 4: the questions

Up to 4, one per reply, each with choices to tap. Skip one the DJ's message already answered (a seed they named, "for Saturday's warm-up", "50"). Never a fifth. Every reply starts `Question N of 4 · under a minute.`

1. **The slot.** `Where in the night does it sit?` Choices: **Warm-up / Peak time / Closing**, or their own words. It sets `curve` (`warmup`, `peak`, `flat`) and goes into `brief` in their words.
2. **The tempo.** `Which tempo? These are your lanes.` Choices: up to 4 lanes from `taste/lanes.md`, each by its range and the DJ's own name for it when they gave one (`118-124 · rooftop`), plus **Any**. A lane sets `lanes`; a window they type sets `bpm`; Any sets neither.
3. **The seed.** `Which track is it built around? Artist - Title.` Choices: up to 3 anchors from `taste/anchors.md` that sit in the lane they picked, plus **No seed**.
4. **The length, and from where.** `How many tracks: 30 / 50 / 70? And my tracks only, or also what to buy?` Choices: **30 / 50 / 70** and **My tracks only / Also what to buy**. They answer both in one line ("50, also what to buy"). A half they leave out: 50, and my tracks only; say which you took in the preview's first line.

## Step 2 of 4: the seed and the digging

```text
Step 2 of 4 · about 3 minutes. Digging: the seed, its label, who plays it, the sets it is in.
```

1. **Find the seed** with `dj_query` on `tracks`: artist and title, any case, part of the name is enough.
   - One row: the DJ owns it. `seed: "<id>"` goes in the spec: it is always in the crate. The tool takes the rest from the seed for whatever the spec leaves out: its BPM, 3 either side (a lane they picked in question 2 stays instead), its genre, and its key and neighbours on the wheel scoring up.
   - Several rows (copies, versions): show up to 5 with id, BPM, key and bitrate and ask which one. Versions are the DJ's call. This is still the seed question.
   - No row: the DJ does not own it. Look it up on the web (one of the 8 searches): BPM, key, genre, label. Those set `bpm` and `genres`; there is no `seed`. The seed goes first in the candidates, so it lands on the to-buy list.
2. **Write the spec** `crates/<slug>.spec.yaml` with what the answers and the seed give (SKILL.md, The spec).
3. **Dig, on the web: 8 searches at most.** Four angles, in this order, two searches each at most:
   1. the scene and the genre the seed belongs to;
   2. label mates: the same label, the same years;
   3. who plays it: DJs, charts;
   4. tracklists it is on: what was played before and after it.

   Collect candidates as `"Artist - Title"`, each with the link it came from. 20 to 60 is plenty. A track without a link is not a candidate: nothing from memory.
4. **Match.** Also what to buy: `dj_match_tracks(candidates, crate="<slug>")`. My tracks only: `dj_match_tracks(candidates)`, and the missing are dropped (say how many).
5. **Back into the spec.** The `owned` ids go into `prefer` (they score up; they are not forced in). The links you used go into `sources`, one quoted line each: the link, then a few words on what it is. The missing are in `crates/<slug>.to-buy.md` already, with their store links.

No web search in the session: skip the digging and say so in one line, `No web search in this session: I build it from your own tracks.` An unowned seed then sets nothing: the answers to questions 1 and 2 carry the spec.

## Step 3 of 4: preview

`dj_crate_preview(spec)`, then one card:

1. The counts line: picks, spares, candidates, vetoed (`counts`), then how many to buy (the `missing` count from `dj_match_tracks`) and the file, `crates/<slug>.to-buy.md`.
2. The first 5 picks in order, each with its `reason` in your words (the same facts, no new numbers), then "and N more". The seed's reason says "your seed".
3. Spares, per energy tier, then `warnings`, one line each.
4. Exactly: `Nothing written yet.`

Then the two write questions, as in SKILL.md: `Close rekordbox first.`, then `Write it into rekordbox?` **Yes / Change / Stop**.

## Edits by talking

The DJ says what is off; you change the spec and preview again. Every edit is one reply: what you changed in the spec in one line, what came in and what went out (up to 5 each), then the write questions start over with the new preview id. Pick numbers are positions in the latest preview.

| The DJ says | Change in the spec |
|---|---|
| "drop 7" | pick 7's id into `exclude`: it is never picked for this crate again |
| "more like 3" | find pick 3's neighbours with `dj_query` (same genre, BPM within 3, the same or a neighbouring key; the same label or artist first) and put up to 10 of their ids into `prefer` |
| "darker", "deeper", "harder", "more vocal" | the genre fields (`genres`, `exclude_genres`) in the DJ's own genre words from the catalog and `taste/vocabulary.md`; `my_tags` when they tag that way |
| "faster", "slower", "tighter" | `bpm` or `lanes` |
| "only the good ones" | `min_rating` |
| "longer", "shorter" | `size`: 30, 50 or 70 |
| "start with ...", "it has to have ..." | `seed` for the opener, `anchors` for tracks that must be in |

- A mood word maps to fields, never to a track you pick yourself. Not sure which genre word is "darker" for this DJ: offer two readings as choices, in their words.
- "Never play that again" is a veto, not an edit: one "never propose" line in `taste/vetoes.md`, only when they say never. `exclude` is for this crate only.
- An id in `exclude` and in `prefer`, `seed` or `anchors` at once is a spec problem: take it out of the other field first.

## Step 4 of 4: written, and next

After the yes, `dj_crate_write(spec, preview_id)`. Show the result's first line, the crate record (`crates/<slug>.md`: the picks, the spares and the sources) and the to-buy list.

```text
Step 4 of 4 · under 2 minutes. Open rekordbox: it's under Crates. To buy: crates/<slug>.to-buy.md. Open it and tick what you want.
```

Tracks they buy and add to rekordbox are picked up on the next read: a new slug or a new `name`, the same candidates through `dj_match_tracks`, and what was missing is now `owned`.
