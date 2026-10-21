"""The shopping list: tracks on a Spotify inbox playlist with no local file (R-803).

Door 1 core: stdlib + `dj.libfolder` only, no Spotify call, no network. The rows are the
MISSING items of the newest plan for one link (`dj plan` writes down the last match), with
artist, title and label taken from the pulled inbox when it is there. A pull newer than that
plan is flagged (`stale_plan`, one summary line): run `dj plan` first. The file is a derived
report: every run rewrites `wishlist/<crate>.shopping.md` (temp file + os.replace), and its
header says so.

Beatport and Bandcamp links are search URLs built here and never fetched. BPM and key stay
"-": Spotify gives no audio features to apps created after November 2024, and the label shows
only when Spotify's track or album data carries one (docs/spotify-audit.md).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dj import libfolder

MISSING = "MISSING"  # = dj.intake.MISSING (not imported: intake pulls in pyrekordbox)
SUFFIX = ".shopping.md"
BEATPORT_SEARCH = "https://www.beatport.com/search"
BANDCAMP_SEARCH = "https://bandcamp.com/search"
TOP_LABELS = 3
NO_VALUE = "-"
_PLAN_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.plan\.json$")


class ShoppingError(ValueError):
    """No plan to read, or a plan that is not one. Nothing was written."""


@dataclass(frozen=True)
class Row:
    artist: str
    title: str
    label: str = ""
    uri: str = ""
    first: str = ""  # the first artist, when the inbox lists them one by one

    @property
    def line(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title

    @property
    def query(self) -> str:
        """The search text: first artist + title. From the plan text alone the artists are one
        joined string, so the first one is the part before the first comma."""
        first = self.first or (re.split(r",\s*", self.artist, maxsplit=1)[0] if self.artist else "")
        return " ".join(x for x in (first, self.title) if x)


def search_url(base: str, query: str) -> str:
    """`base?q=<query>`, URL-encoded (spaces as +, & / ? # escaped)."""
    return f"{base}?{urlencode({'q': query})}"


def beatport_url(row: Row) -> str:
    return search_url(BEATPORT_SEARCH, row.query)


def bandcamp_url(row: Row) -> str:
    return search_url(BANDCAMP_SEARCH, row.query)


# -- input ---------------------------------------------------------------------------------


def latest_plan(plans_dir: str | Path, slug: str) -> Path | None:
    """The newest `<YYYY-MM-DD>-<slug>.plan.json` in plans_dir, else None.

    The slug matches without regard to case: on Windows and macOS a plan rewritten after the
    DJ fixed the crate's case in links.yaml keeps its old file name. Newest date wins; on one
    date the exact-case name wins, then the name (deterministic on every OS).
    """
    plans_dir = Path(plans_dir)
    if not plans_dir.is_dir():
        return None
    wanted = slug.casefold()
    found = []
    for path in plans_dir.iterdir():
        m = _PLAN_NAME.match(path.name)
        if m and m.group(2).casefold() == wanted and path.is_file():
            found.append((m.group(1), m.group(2) == slug, path.name, path))
    return max(found)[3] if found else None


def stale(plan: dict[str, Any], inbox: dict[str, Any] | None) -> bool:
    """True when the inbox was pulled after the plan was written: the plan's MISSING list
    is not the last pull's. Unknown or unreadable times: False (nothing to compare)."""
    try:
        created = datetime.fromisoformat(str(plan.get("created")))
        pulled = datetime.fromisoformat(str((inbox or {}).get("pulled_at")))
    except ValueError:
        return False
    if (created.tzinfo is None) != (pulled.tzinfo is None):
        return False
    return pulled > created


def read_json(path: str | Path, what: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ShoppingError(f"{what} {Path(path).name} cannot be read: {type(exc).__name__}") from None
    if not isinstance(data, dict):
        raise ShoppingError(f"{what} {Path(path).name} is not a JSON object.")
    return data


def _split_label(text: str) -> tuple[str, str]:
    """A plan's `spotify` text "Artist, Artist - Title" -> (artists, title)."""
    artist, sep, title = text.partition(" - ")
    return (artist.strip(), title.strip()) if sep else ("", text.strip())


def _clean(value: Any) -> str:
    return " ".join(str(value).split()) if value else ""


def rows(plan: dict[str, Any], inbox: dict[str, Any] | None = None) -> list[Row]:
    """The plan's MISSING items in plan order, each Spotify track once."""
    by_uri = {t.get("uri"): t for t in (inbox or {}).get("tracks") or [] if isinstance(t, dict)}
    out: list[Row] = []
    seen: set[str] = set()
    for item in plan.get("items") or []:
        if not isinstance(item, dict) or item.get("status") != MISSING:
            continue
        uri = str(item.get("spotify_uri") or "")
        if uri and uri in seen:
            continue
        seen.add(uri)
        track = by_uri.get(uri)
        if track:
            names = [_clean(a) for a in track.get("artists") or [] if _clean(a)]
            artists, first = ", ".join(names), (names[0] if names else "")
            title = _clean(track.get("title"))
            label = _clean(track.get("label"))
        else:
            artists, title = _split_label(_clean(item.get("spotify")))
            label = first = ""
        out.append(Row(artist=artists, title=title or uri, label=label, uri=uri, first=first))
    return out


def top_labels(found: list[Row], n: int = TOP_LABELS) -> list[tuple[str, int]]:
    counts = Counter(r.label for r in found if r.label)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))[:n]


# -- output --------------------------------------------------------------------------------


def _cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|") or NO_VALUE


def render(found: list[Row], *, crate: str, spotify: str, source: str,
           today: date | None = None, stale_plan: bool = False) -> str:
    """The shopping list as Markdown: title, provenance, summary (<= 5 lines), table.
    stale_plan: one summary line says the plan is older than the last pull."""
    day = (today or date.today()).isoformat()
    labels = top_labels(found)
    lines = [
        f"# Shopping list: {crate}",
        "",
        f"> Measured by code: dj.shopping from {source}, {day}.",
        "",
        "Generated file: every `dj wishlist shop` rewrites it, so edits here are lost. "
        "Keep your own notes in another file.",
        "",
        "## Summary",
        "",
    ]
    if found:
        lines.append(f"- {len(found)} track(s) on Spotify `{spotify}` have no local file.")
    else:
        lines.append(f"- Nothing to buy: every track on Spotify `{spotify}` in the last plan has "
                     "a local file or was declined.")
    if labels:
        lines.append("- Top labels: " + ", ".join(f"{name} ({n})" for name, n in labels) + ".")
    elif found:
        lines.append("- Labels: Spotify sent none for these tracks.")
    if stale_plan:
        lines.append(f"- Out of date: Spotify `{spotify}` was pulled after this plan. Run "
                     "`dj plan` for this link, then `dj wishlist shop` again.")
    lines.append("- BPM and key are blank (-): Spotify gives no audio features to new apps.")
    lines.append("- The links open a Beatport or Bandcamp search. Nothing was fetched.")
    if found:
        lines += ["", "## Tracks", "",
                  "| Artist - Title | Beatport | Bandcamp | Label | BPM | Key |",
                  "|---|---|---|---|---|---|"]
        for r in found:
            lines.append(f"| {_cell(r.line)} | [search]({beatport_url(r)}) | "
                         f"[search]({bandcamp_url(r)}) | {_cell(r.label)} | {NO_VALUE} | {NO_VALUE} |")
    return "\n".join(lines) + "\n"


def shop(
    root: str | Path,
    *,
    plans: str | Path,
    inbox: str | Path,
    wishlist: str | Path,
    crate: str,
    spotify: str,
    slug: str,
    library: bool,
    today: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write `wishlist/<slug>.shopping.md` from the newest plan for `slug`; return counts.

    root = the library folder (library=True: a log.md line is appended) or the repo root.
    `inbox` = the pulled inbox file for the link (optional; enriches artist, title, label).
    """
    root = Path(root)
    plan_path = latest_plan(plans, slug)
    if plan_path is None:
        raise ShoppingError(f"No plan for {crate} yet. Run `dj plan` for this link first.")
    plan = read_json(plan_path, "Plan")
    if not isinstance(plan.get("items"), list):
        raise ShoppingError(f"Plan {plan_path.name} has no items list.")
    inbox_path = Path(inbox)
    pulled = read_json(inbox_path, "Inbox") if inbox_path.is_file() else None
    found = rows(plan, pulled)
    is_stale = stale(plan, pulled)

    source = _shown(root, plan_path)
    text = render(found, crate=crate, spotify=spotify, source=source, today=today,
                  stale_plan=is_stale)
    target = Path(wishlist) / f"{slug}{SUFFIX}"
    target.parent.mkdir(parents=True, exist_ok=True)
    libfolder.write_text(target, text)

    log_line = None
    if library:
        log_line = libfolder.append_log(root, f"wishlist shop {crate}", {"missing": len(found)},
                                        file=target, now=now, today=today)
    return {
        "missing": len(found),
        "labels": [{"label": name, "tracks": n} for name, n in top_labels(found)],
        "file": _shown(root, target),
        "path": str(target),
        "plan": source,
        "stale_plan": is_stale,  # True: the inbox was pulled after the plan; run `dj plan` first
        "log": log_line,
    }


def _shown(root: Path, path: Path) -> str:
    """A path relative to root (POSIX) when it is inside, else its absolute form."""
    try:
        return libfolder.relative(root, path)
    except libfolder.LibraryFolderError:
        return str(path)
