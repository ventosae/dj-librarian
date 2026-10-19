"""dj build: a text tracklist -> a private Spotify playlist.

For tracklists copied from YouTube descriptions, 1001tracklists or liner notes.
Same matching as `dj push`, but a text line carries no duration and no ISRC, so a MATCH
here rests on artist + title + version words only. rekordbox is never touched.
On Spotify: create the playlist once (state/build.json), add only, never remove.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dj import push
from dj.intake import slug
from dj.match import Local, Result
from dj.safety import REPO_ROOT

STATE_FILE = REPO_ROOT / "state" / "build.json"
DESCRIPTION = "Built from a tracklist by dj-librarian."

# leading track numbers, timestamps and bullets: "01. ", "3) ", "[12:34] ", "1:02:03 ", "- "
_PREFIX = re.compile(r"^\s*(?:\d{1,3}[.)]|\[?\d{1,2}:\d{2}(?::\d{2})?\]?|[-*•])\s+")
_SPLIT = re.compile(r"\s+[-–—]+\s+")


class BuildError(RuntimeError):
    pass


def parse_line(line: str) -> tuple[str, str] | None:
    """'Artist - Title (Mix)' -> (artist, title). None when there is no ' - '."""
    text = _PREFIX.sub("", line).strip()
    parts = _SPLIT.split(text, maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return None
    return parts[0].strip(), parts[1].strip()


def parse_tracklist(text: str) -> tuple[list[Local], list[str]]:
    """One Local per track line (content_id = line number). Other lines come back as
    skipped, so a heading like 'Tracklisting' is reported, never matched."""
    tracks, skipped = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parsed = parse_line(raw)
        if parsed is None:
            skipped.append(raw.strip())
            continue
        artist, title = parsed
        tracks.append(Local(content_id=str(number), artist=artist, title=title))
    return tracks, skipped


def load_tracklist(path: Path) -> tuple[list[Local], list[str]]:
    path = Path(path)
    if not path.is_file():
        raise BuildError(f"Tracklist not found: {path}")
    tracks, skipped = parse_tracklist(path.read_text(encoding="utf-8"))
    if not tracks:
        raise BuildError(f"No 'Artist - Title' lines in {path.name}.")
    return tracks, skipped


def default_name(path: Path) -> str:
    return Path(path).stem.replace("_", " ").strip()


def key(name: str) -> str:
    """The state/build.json key: one Spotify playlist per name, case-insensitive."""
    return "build:" + slug(name).casefold()


def match_all(api: Any, tracks: list[Local]) -> list[Result]:
    return [push.match_track(api, t, ignore_duration=True) for t in tracks]


def apply(api: Any, name: str, uris: list[str], state_file: Path | None = None) -> dict[str, Any]:
    return push.apply(api, key(name), name, uris, state_file or STATE_FILE, description=DESCRIPTION)
