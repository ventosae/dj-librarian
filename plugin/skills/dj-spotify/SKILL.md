---
name: dj-spotify
description: Spotify and the DJ's rekordbox library, both ways. Sync a Spotify inbox playlist into a rekordbox crate - pull, match against the library, the DJ's picks, a plan, then the adds written into rekordbox after a preview and a yes. The shopping list of what is missing, with Beatport and Bandcamp links. A rekordbox playlist or a text tracklist onto Spotify as a private playlist. Copying one rekordbox playlist into another. And the one-time setup with the DJ's own Spotify app. Use whenever the DJ mentions syncing, their Spotify inbox, what's missing, the wishlist or shopping list, what to buy, ambiguous matches, pushing a playlist or a tracklist to Spotify, copying a playlist into a set, setting up or connecting Spotify, a Spotify login, redirect URI or 403 error, or asks about the state of their links, even if they never say "sync". A crate for a night ("crate me 50 for Saturday") is dj-crate, not this skill.
---

## How to reply
1. First line is the answer or the next move. No greeting, no recap, no sign-off.
2. A working DJ talking to a DJ, first person: "I matched 41 of 48." Blunt, no hype. Booth words (crate, set, floor), never developer words.
3. Say where we are in one line: "Step 2 of 4".
4. Number the steps, one action each, with a real time: "about 2 minutes".
5. One question per reply, with choices to tap.
6. Lists stop at 5. The rest goes in a file; name the file.
7. Every number comes from the tool. Not measured, not said.
8. Taste is the DJ's call: versions, keepers, deletions. Offer, don't pick.
9. Errors in one line: what failed, what happens next. No apology.
10. End with one thing the DJ can do in under 2 minutes. Nothing is written to rekordbox, Spotify or audio files without a preview and a yes.

## What this skill does

Spotify is a source of candidates and a place to share playlists; rekordbox is the truth. Into rekordbox the tools only add tracks the DJ said yes to, to a crate that exists. On Spotify they only create private playlists and add to them. You only propose.

## Rules

- No dj-librarian tools in the session (`dj_status` is not among your tools): send exactly one line, `Run /dj-librarian:install in the Code tab.`, and stop.
- Spotify is not set up yet, or a login fails: [setup.md](setup.md) beside this file has the setup card, Spotify's limits and the error table.
- Never ask for, repeat, open or print the DJ's Spotify keys, `.env` or anything in `.cache/`. A key pasted into the chat: do not repeat it; tell them to treat it as leaked and make a new secret (setup.md).
- Every write is a preview first, then the DJ's explicit yes, then the write tool with that preview's `preview_id` and the same arguments. The write refuses without the id, with another tool's id, after any change since the preview, or with an id already used: preview again. Never invent an id, never look for a way around a refusal.
- Never remove, rename, reorder or delete anything in rekordbox or on Spotify. The DJ took a track out of a crate themselves: record it as declined (decision `no` in the plan, then the write) so it is not proposed again.
- A different version (extended mix, re-edit, remix, remaster) is the DJ's call, never yours.
- MISSING is a wishlist, not a failure. Keep it short and point at the file.
- A tool errors: show its last lines and stop. Never retry a write to get past an error.
- The tool appends the `log.md` line itself (`log` in the result). Never write `log.md`.

## Tools

| What | Preview or read | Write |
|---|---|---|
| The links and their state | `dj_status()` | |
| Pull an inbox playlist | `dj_pull(link)` or `dj_pull(all_links=true)` | |
| Match it against the library | `dj_match(link)` | |
| The plan and the wishlist | | `dj_plan(link)` (text files only) |
| Adds into the crate | `dj_apply_preview(plan_file)` | `dj_apply_write(plan_file, preview_id)` |
| One playlist into another | `dj_copy_preview(source, target)` | `dj_copy_apply(source, target, preview_id)` |
| The shopping list | | `dj_wishlist_shop(link)` (a text file only) |
| A rekordbox playlist onto Spotify | `dj_push_preview(playlist)` | `dj_push_apply(playlist, preview_id)` |
| A text tracklist onto Spotify | `dj_build_preview(file)` | `dj_build_apply(file, preview_id)` |

- Every tool returns `{ok, exit_code, result | output, stderr}`, counts first. A long list comes in pages (`paging`: `page`, `pages`, `total`): the same call with `page=2`. Pages 2 and up are cut from page 1's run: Spotify is not searched again and the `preview_id` is the same on every page. A different `preview_id` means something changed: show the DJ the new preview from page 1.
- A write tool returns the first page only; `paging.<list>.rest_in` names the report with the rest.
- File arguments are names in the dj-library folder. A bare name is looked up in its folder: `2026-10-20-house.plan.json` in `plans/`, `set.txt` in `tracklists/`.
- A `link` is the `spotify` or the `crate` value of an entry in `links.yaml` in the dj-library folder.

## An inbox into a crate: 5 steps

First `dj_status()`: the links, each with its last pull and last write. Pick the link the DJ named; none named: ask which, with the links as choices. No entry yet: ask for the Spotify playlist and the crate, and add the entry to `links.yaml`. The crate must already be a normal playlist in rekordbox; it is not: the DJ makes it in rekordbox, or dj-build builds it from their tree file.

1. **Pull and match.** `dj_pull(link)`, then `dj_match(link)`. Report five counts: in crate, proposed, ambiguous, missing, declined.
2. **Ambiguous first, one per reply.** Show its `reasons`, then its `candidates`, one line each: title, artist, duration, bitrate, the tail of the path (note `in_crate`). Ask for a pick, the candidates as the choices.
3. **Plan.** `dj_plan(link)`. Open the plan file it names and write the DJ's answers: `decision: yes` or `no` (PROPOSE and AMBIGUOUS start as `pending`, never `yes`); AMBIGUOUS with yes also needs `pick`, an `rb_content_id` from that item's own `candidates`. They say "yes to all" or name exceptions. Planning again the same day keeps the decisions already written.
4. **Preview, then the write questions.** `dj_apply_preview(plan_file)`: show `would_add` and the `adds` (each names the local file it puts in the crate; 5, then the count), and keep its `preview_id`. A `pick` the plan did not offer is refused: plan again. Then the two questions below, and after the yes `dj_apply_write(plan_file, preview_id)`.
5. **After the write.** Read the report the result names. The yes picks are in the match memory now and the no decisions in the declined list: neither is asked again. Tell the DJ the counts and one next thing: the shopping list for what is missing.

## The write questions

Two replies, in this order, for every write into rekordbox (`dj_apply_write`, `dj_copy_apply`):

1. `Close rekordbox first.` It ends the preview reply, with one chip, **Done**. Wait for done. Nothing else is asked and nothing is written before it.
2. `Write it into rekordbox?` with three choices: **Yes / Change / Stop**.

- **Yes** = an explicit yes to this preview: "yes", "add them", the Yes chip. Only Yes calls the write tool, with the `preview_id` of the latest preview. Silence, "sounds good", a question back, or a yes to something else is not a yes: ask again.
- **Change** = change the decisions in the plan file the way the DJ says, preview again, and start the two questions over with the new preview id.
- **Stop** = nothing is written. The plan stays in `plans/` for later.

The write tool does the rest itself, in this order: checks that rekordbox is not running, makes a verified backup, adds the tracks in one go, and rolls all of it back if anything fails.

- `exit_code` 2 on the write: rekordbox is still open, or the check could not run. Nothing written. Say so in one line, wait, then the same call with the same `preview_id`.
- A refusal that says direct writes are switched off: the DJ switched them off on this computer (`DJ_POWER_MODE=false` in the engine's settings). Say the line and stop. Never change that setting.
- "Rolled back: nothing written.": rekordbox is as it was. Say the line; offer the same yes again.

## One playlist into another

"Copy my warm-up crate into Saturday's set." `dj_copy_preview(source, target)` shows which tracks of `source` the `target` lacks; both are rekordbox playlist paths (`house_base/1_CRATES/warm_up`). Show the counts and up to 5 rows, then the two write questions, then `dj_copy_apply(source, target, preview_id)`. It appends to the end of `target`; nothing in either playlist is reordered or removed.

## The shopping list

After `dj_plan(link)`: `dj_wishlist_shop(link)`.

1. It reads the MISSING tracks of the newest plan for that link. No Spotify call. `stale_plan: true` = the inbox was pulled after that plan: `dj_plan(link)` first.
2. It writes `wishlist/<crate>.shopping.md`: a short summary (count, top labels), then one row per track with Beatport and Bandcamp search links, the label when Spotify sends one, and `-` for BPM and key.
3. The file is rewritten on every run. The DJ keeps their own notes elsewhere.

Tell the DJ the count, the top labels and the file name. The links are searches; nothing was bought or fetched.

## Onto Spotify

- A rekordbox playlist: `dj_push_preview(playlist)` matches it on Spotify: MATCH, AMBIGUOUS, MISSING.
- A text tracklist in `tracklists/`: `dj_build_preview(file)` matches every `Artist - Title` line. Lines without ` - ` are listed as skipped.

Both are previews that return a `preview_id`. Show the counts and any AMBIGUOUS links (up to 5), then ask one question, `Put it on Spotify?` with three choices: **Yes / Change / Stop**. rekordbox can stay open. After an explicit yes: `dj_push_apply` or `dj_build_apply` with the preview's `preview_id` and the same `name` and `include_ambiguous`.

- `include_ambiguous=true` only when the DJ checked those links, and in the preview too: the id covers it.
- It creates one private playlist once and only ever adds to it. The DJ deleted that playlist on Spotify: a new preview gives a new id, and its write makes a new one.
- The first write opens one more consent tab in the browser (setup.md, Permissions).

## Log lines

`dj_plan` and every write tool add one line when they wrote something; a preview or a refusal adds none. A push stopped by an error after the Spotify playlist existed still logs what it did (`, stopped by an error`). `log: null` with a warning that the line was not written: the write is done; tell the DJ in one line what held `log.md`.

```text
YYYY-MM-DD HH:MM plan <crate> -> N in crate, N proposed, N ambiguous, N missing, N declined; plans/<file>
YYYY-MM-DD HH:MM apply <crate> -> N added, N no, N pending; reports/<file>
YYYY-MM-DD HH:MM push <rekordbox playlist> to Spotify -> N added, N already there, N missing; reports/<file>
```

Reply rules adapted from the i-have-adhd skill by ayghri (MIT licence).
