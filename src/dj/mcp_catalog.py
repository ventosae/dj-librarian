"""The catalog's MCP tools (D-37), registered on the server of `dj.mcp_server`.

`mcp_server.py` loads this module with one import line at its end. Like every tool there, each one
runs one fixed `dj` command with --json, its arguments as a list (never a shell), through the
server's own `run_dj_data`; a value goes after `--`, so it can never be read as an option.
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any

# The server module: `__main__` when it was started as `python -m dj.mcp_server`, so the tools land on
# the server that runs, never on a second copy of it.
_main = sys.modules.get("__main__")
_is_main = getattr(getattr(_main, "__spec__", None), "name", "") == "dj.mcp_server"
m: Any = _main if _is_main else importlib.import_module("dj.mcp_server")

SQL_MAX = 4000  # characters of one SELECT
NOTE_FIELD_MAX, NOTE_VALUE_MAX = 60, 2000  # as dj.catalog


def _run(options: list[str], positionals: tuple[str, ...]) -> str:
    """One `dj` run as compact JSON (a page of rows is sized for the tool-result limit, NFR-03)."""
    return json.dumps(m.run_dj_data(options, positionals), ensure_ascii=False, separators=(",", ":"))


def _text(value: Any, name: str, limit: int) -> str:
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if not text or len(text) > limit:
        raise m.ToolInputError(f"{name} must be 1 to {limit} characters of text.")
    return text


@m.server.tool(annotations=m.READ)
@m.guarded
def dj_query(sql: str, page: int = 1) -> str:
    """Ask the DJ's track catalog one SQL SELECT (plain SQLite, <dj-library>/catalog/catalog.db; the
    same tracks are in catalog/tracks.csv). Tables: `tracks` (id, artist, title, album, duration_s,
    isrc, bitrate, location, kind, bit_depth, sample_rate, file_size, bpm, key, genre, label, remixer,
    year, rating 0-5, colour, comment, date_added YYYY-MM-DD, play_count, my_tags "a, b", cue_count,
    has_artwork 0/1, camelot like "8A", local 1 = a file / 0 = a streamed row with its id only),
    `playlists` (id, name, path "Folder/Playlist", kind folder|playlist|smart, parent), `playlist_tracks`
    (playlist_id, position, track_id; in order), `notes` (track_id, field, value, source, date) and
    `meta` (key, value). Returns counts first: {counts: {rows, page, pages}, columns, rows}; `rows`
    are lists in `columns` order, 200 a page at most (a page ends early when it gets long: select the
    columns you need); page=2 for the next. Read-only: anything that is not exactly one SELECT is
    refused with one line (exit_code 1). The catalog is checked against rekordbox first and built again
    when it changed (its files in the dj-library folder; rekordbox itself is only read)."""
    if not isinstance(sql, str) or not sql.strip() or len(sql) > SQL_MAX:
        raise m.ToolInputError(f"sql must be one SELECT statement of at most {SQL_MAX} characters.")
    page, _size = m.page_args(page, m.PAGE_SIZE)
    return _run(["library", "query", "--page", str(page)], (sql,))


@m.server.tool(annotations=m.LIBRARY_TEXT)
@m.guarded
def dj_note(track_id: str, field: str, value: str, source: str = "dj") -> str:
    """Add one note about a track to the catalog's `notes` table, dated today: `track_id` (tracks.id,
    from dj_query), `field` (what it is about: energy, mood, set, note ...), `value` (one line),
    `source` ("dj" = the DJ said so; else where it came from). Notes are only ever added and survive
    every rebuild of the catalog; read them with dj_query. A text file of the DJ's own library folder:
    no preview id. An unknown track id writes nothing (exit_code 1). Returns counts first and the
    log.md line it appended. Never touches rekordbox, Spotify or audio files."""
    tid = _text(str(track_id) if isinstance(track_id, int) and not isinstance(track_id, bool) else track_id,
                "track_id", 40)  # fmt: skip
    values = (tid, _text(field, "field", NOTE_FIELD_MAX), _text(value, "value", NOTE_VALUE_MAX))
    return _run(["library", "note", "--source", _text(source, "source", NOTE_FIELD_MAX)], values)


@m.server.tool(annotations=m.LIBRARY_TEXT)
@m.guarded
def dj_match_tracks(candidates: list[str], crate: str = "") -> str:
    """Split web-research candidates for a long crate into the tracks the DJ owns and the ones to
    buy (D-38). `candidates`: "Artist - Title" lines, each with an optional link at the end (at most
    200). `crate`: the crate's slug; with one, the missing ones are written to
    crates/<slug>.to-buy.md (a text file of the DJ's library folder: no preview id). Returns counts
    first {candidates, owned, missing}, `owned` (candidate, id, artist, title, bpm, key), `missing`
    (candidate, source, beatport, bandcamp search links, never fetched), `prefer` (every owned id: put
    them in the spec's `prefer`) and `to_buy` (the file, or null). rekordbox is only read."""
    if not isinstance(candidates, list) or not candidates or len(candidates) > 200:
        raise m.ToolInputError("candidates must be a list of 1 to 200 \"Artist - Title\" lines.")
    lines = tuple(_text(c, "a candidate", 500) for c in candidates)
    options = ["library", "match-tracks"]
    if crate:
        options += ["--crate", _text(crate, "crate", 80)]
    return _run(options, lines)
