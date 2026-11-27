"""Web candidates against the DJ's library, for a long crate (D-38).

`match(lib, candidates)` splits "Artist - Title" lines (from web research) into the tracks the DJ
owns and the ones to buy, with Beatport and Bandcamp search links (`dj.shopping`, never fetched).
The owned ids go into the crate spec's `prefer`; `write_to_buy` writes `crates/<slug>.to-buy.md`,
a text file of the DJ's own library folder: no preview id. Nothing here touches rekordbox.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from dj import match as m
from dj.libfolder import LibraryFolder
from dj.model import Library, id_sort_key
from dj.shopping import Row, bandcamp_url, beatport_url

MAX_CANDIDATES = 200
SHOWN = 30  # rows of each list in a result; the file holds them all
_SPLIT = re.compile(r"\s+[-–—]\s+")
_URL = re.compile(r"\s*\(?(https?://\S+?)\)?\s*$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse(line: str) -> tuple[str, str, str]:
    """("Artist", "Title", "url") from "Artist - Title" with an optional trailing link."""
    text = " ".join(str(line or "").split())
    url = ""
    if found := _URL.search(text):
        url, text = found.group(1), text[: found.start()].strip()
    parts = _SPLIT.split(text, maxsplit=1)
    return (parts[0], parts[1], url) if len(parts) == 2 else ("", text, url)


def _words(text: str) -> set[str]:
    return {w for w in m.normalise(text).split() if len(w) > 2}


def match(lib: Library, candidates: Iterable[str]) -> dict[str, Any]:
    """{counts, owned, missing}: owned = a local file that matches confidently (rapidfuzz, as
    `dj match`; version words count), missing = the rest, with store search links."""
    tracks = sorted((t for t in lib.tracks.values() if t.location), key=lambda t: id_sort_key(t.id))
    locals_ = [(t, m.Local(t.id, t.artist, t.title, t.album, t.duration_s, t.isrc), _words(t.title)) for t in tracks]
    owned: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(candidates)[:MAX_CANDIDATES]:
        artist, title, url = parse(raw)
        line = f"{artist} - {title}" if artist else title
        if not title or line.casefold() in seen:
            continue
        seen.add(line.casefold())
        cand = m.Candidate(uri=line, title=title, artists=[artist] if artist else [])
        want = _words(title)
        best = None
        for t, local, words in locals_:
            if want and not want & words:
                continue
            s = m.score(local, cand, ignore_duration=True)
            if s.confident and (best is None or s.score > best[0]):  # ties: the lowest id
                best = (s.score, t)
        if best is not None:
            t = best[1]
            owned.append({"candidate": line, "id": t.id, "artist": t.artist, "title": t.title,
                          "bpm": round(t.bpm, 1), "key": t.key})  # fmt: skip
        else:
            row = Row(artist=artist, title=title)
            missing.append({"candidate": line, "source": url, "beatport": beatport_url(row),
                            "bandcamp": bandcamp_url(row)})  # fmt: skip
    counts = {"candidates": len(seen), "owned": len(owned), "missing": len(missing)}
    return {"counts": counts, "owned": owned, "missing": missing}


def write_to_buy(folder: LibraryFolder | str | Path, slug: str, missing: list[dict[str, Any]],
                 *, today: date | None = None) -> Path:  # fmt: skip
    """crates/<slug>.to-buy.md, rewritten each run (temp file + os.replace)."""
    if not SLUG.match(slug):
        raise ValueError(f"crate must be a slug like saturday-rooftop, got {slug!r}")
    folder = folder if isinstance(folder, LibraryFolder) else LibraryFolder(Path(folder))
    folder.crates.mkdir(parents=True, exist_ok=True)
    path = folder.crates / f"{slug}.to-buy.md"
    day = (today or date.today()).isoformat()
    lines = [f"# To buy for {slug}", "", f"{len(missing)} tracks from the research, not in your library ({day}).",
             "Rewritten each time the crate is matched again.", "",
             "| Track | Beatport | Bandcamp | Found on |", "|---|---|---|---|"]  # fmt: skip
    for r in missing:
        name = r["candidate"].replace("|", "/")
        found = r.get("source") or "-"
        lines.append(f"| {name} | [search]({r['beatport']}) | [search]({r['bandcamp']}) | {found} |")
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def run(folder: LibraryFolder | str | Path, candidates: list[str], crate: str = "",
        lib: Library | None = None) -> dict[str, Any]:  # fmt: skip
    """match + (with a crate slug) the to-buy file. Lists cut to SHOWN; counts first."""
    folder = folder if isinstance(folder, LibraryFolder) else LibraryFolder(Path(folder))
    if lib is None:
        from dj.build_library import read_for_build

        lib, _label = read_for_build(folder)
    result = match(lib, candidates)
    to_buy = None
    if crate and result["missing"]:
        to_buy = folder.relative(write_to_buy(folder, crate, result["missing"]))
    return {"counts": result["counts"], "owned": result["owned"][:SHOWN], "missing": result["missing"][:SHOWN],
            "prefer": [o["id"] for o in result["owned"]], "to_buy": to_buy}  # fmt: skip
