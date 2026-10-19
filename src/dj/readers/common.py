"""Helpers both readers share. Door 1: stdlib only.

BPM_SCALE equals `dj.rules.BPM_SCALE` (a test asserts it). It is not imported from there,
because `dj.rules` pulls in pyrekordbox.
"""

from __future__ import annotations

import math
import re
from datetime import date
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, unquote

BPM_SCALE = 100  # master.db DjmdContent.BPM stores 120 BPM as 12000
RATING_STEP = 51  # rekordbox XML Rating: 0, 51, 102, 153, 204, 255 = 0-5 stars
URL_PREFIX = "file://localhost/"  # as pyrekordbox.rbxml.URL_PREFIX

# Kind words (XML `Kind`, e.g. "MP3 File") and file extensions -> model kind.
_KIND_WORDS = {
    "mp3": "mp3",
    "m4a": "m4a",
    "aac": "m4a",
    "mp4": "m4a",
    "alac": "m4a",
    "flac": "flac",
    "wav": "wav",
    "wave": "wav",
    "aif": "aiff",
    "aiff": "aiff",
}

# rekordbox's eight track colours: XML `Colour` (RGB hex) -> the name master.db shows
# (DjmdColor.Commnt). From community documentation of the XML format; not yet checked
# against a real rekordbox 7.2 export. Unknown values pass through unchanged.
COLOUR_NAMES = {
    "0xFF007F": "Pink",
    "0xFF0000": "Red",
    "0xFFA500": "Orange",
    "0xFFFF00": "Yellow",
    "0x00FF00": "Green",
    "0x25FDE9": "Aqua",
    "0x0000FF": "Blue",
    "0x660099": "Purple",
}
COLOUR_CODES = {name: code for code, name in COLOUR_NAMES.items()}

# After `file://localhost`, the path part says what kind of location it is:
#   `///X/...` (three or more slashes) -> network share `//X/...` (pyrekordbox's encode_path of
#                                         `\\X\...`; `location_url` writes shares this way too)
#   `//X/...`  (exactly two)           -> share `//X/...`, except when X is Users or Volumes:
#                                         a macOS path with one slash too many (encode_path of
#                                         `/Users/...`). rekordbox runs only on macOS and Windows,
#                                         and macOS music lives under /Users or /Volumes.
# Only a Windows server literally named Users or Volumes, written with two slashes, reads wrong.
_MAC_ROOTS = {"Users", "Volumes"}
_DRIVE = re.compile(r"^/*([A-Za-z]:)(/|$)")

# Deeper playlist trees are refused as malformed (rekordbox trees are a handful of levels).
MAX_TREE_DEPTH = 64


def to_int(value: Any) -> int:
    """'320' / 320 / '44100.0' / None -> int; anything unreadable ('inf', 'nan', '1e999') -> 0."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError, OverflowError):
            return 0


def to_float(value: Any) -> float:
    """'122.50' -> 122.5; unreadable or not finite ('inf', 'nan') -> 0.0."""
    try:
        number = float(str(value).strip()) if value is not None else 0.0
    except ValueError:
        return 0.0
    return number if math.isfinite(number) else 0.0


def text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def kind_from(kind_text: str | None, location: str | None) -> str:
    """'MP3 File' or the file extension -> mp3|m4a|flac|wav|aiff|unknown. The kind text wins."""
    for word in re.findall(r"[a-z0-9]+", (kind_text or "").lower()):
        if word in _KIND_WORDS:
            return _KIND_WORDS[word]
    suffix = PurePosixPath(posix_location(location or "")).suffix.lower().lstrip(".")
    return _KIND_WORDS.get(suffix, "unknown")


def posix_location(url_or_path: str | None) -> str:
    """A rekordbox Location (XML `file://localhost/...` URL) or FolderPath -> POSIX path string.

    - `file://localhost/D:/Music/a%20b.mp3` -> `D:/Music/a b.mp3` (percent-escapes, UTF-8)
    - `file://localhost/Users/x/a.mp3`      -> `/Users/x/a.mp3`
    - `file://localhost///nas/music/a.mp3`  -> `//nas/music/a.mp3` (network share)
    - `file://localhost//nas/music/a.mp3`   -> `//nas/music/a.mp3` (network share)
    - `file://localhost//Users/x/a.mp3`     -> `/Users/x/a.mp3` (one slash too many)
    - `file://nas/music/a.mp3`              -> `//nas/music/a.mp3`
    - `C:\\Music\\a.mp3`                    -> `C:/Music/a.mp3` (backslashes)
    A plain path is not percent-decoded: a real file name may hold a '%'.
    """
    raw = (url_or_path or "").strip()
    if not raw:
        return ""
    if raw[:5].lower() == "file:":
        rest = raw[5:]
        if rest.startswith("//"):
            host, sep, tail = rest[2:].partition("/")
            rest = "/" + tail if sep else ""
            if host and host.lower() != "localhost":
                rest = "//" + host + rest
        path = unquote(rest).replace("\\", "/")
        drive = _DRIVE.match(path)
        if drive:
            return drive.group(1) + path[drive.end(1):]
        if path.startswith("//"):
            body = path.lstrip("/")
            slashes = len(path) - len(body)
            if slashes == 2 and body.split("/", 1)[0] in _MAC_ROOTS:
                return "/" + body
            return "//" + body
        return path
    return raw.replace("\\", "/")


def location_url(path: str) -> str:
    """POSIX path -> rekordbox XML Location (`file://localhost/...`), percent-encoded.
    The inverse of `posix_location` for the forms it returns: `D:/...`, `/Users/...` and
    shares `//host/...` (written `file://localhost///host/...`, as pyrekordbox does)."""
    posix = posix_location(path)
    body = posix if posix.startswith("//") else posix.lstrip("/")
    return URL_PREFIX + quote(body, safe="/:")


def parse_date(value: Any) -> date | None:
    """'2021-03-14', '2021-03-14 10:22:01', '2021/03/14' -> date; empty or unreadable -> None."""
    raw = text(value)[:10].replace("/", "-")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def stars_from_rating(raw: Any) -> int:
    """XML Rating 0/51/102/153/204/255 -> 0-5 stars. 1-5 is taken as stars already
    (how master.db is expected to store it); other values round to the nearest star."""
    value = to_int(raw)
    if value <= 0:
        return 0
    if value <= 5:
        return value
    return max(0, min(5, round(value / RATING_STEP)))


def colour_name(raw: Any) -> str:
    """'0xFF007F' / '#ff007f' / 'Pink' -> 'Pink'. Unknown values come back stripped, unchanged."""
    value = text(raw)
    if not value:
        return ""
    hexpart = value[2:] if value[:2].lower() == "0x" else value.lstrip("#")
    if re.fullmatch(r"[0-9A-Fa-f]{6}", hexpart):
        return COLOUR_NAMES.get("0x" + hexpart.upper(), value)
    return value
