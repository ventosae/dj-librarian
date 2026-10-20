"""Spotify inbox -> rekordbox crate: pull, match, plan, apply.

rekordbox is the truth. Spotify playlists are candidates, not members. The tool only
proposes: nothing enters a crate without `decision: yes` in the plan file.

Where the files live (R-802): in the DJ's library folder when its links.yaml holds at least
one link (`default_paths`), else in the repo root as before. See `Paths`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from dj import libfolder, library, match
from dj.match import Candidate, Local, Scored
from dj.safety import REPO_ROOT
from dj.spotify import SpotifyError, refused_status, unreadable_playlist

IN_CRATE, PROPOSE, AMBIGUOUS, MISSING, DECLINED = (
    "IN_CRATE", "PROPOSE", "AMBIGUOUS", "MISSING", "DECLINED",
)  # fmt: skip
STATUSES = (IN_CRATE, PROPOSE, AMBIGUOUS, MISSING, DECLINED)
PENDING, YES, NO = "pending", "yes", "no"

# A plan lists the paths of local music files (its candidates): machine data, kept out of git
# in a library folder (R-905). The line goes into the library's own .gitignore (append-only,
# libfolder.ensure_gitignore) and into plans/.gitignore (created once, never overwritten).
PLANS_IGNORE_LINE = "plans/*.plan.json"
PLANS_GITIGNORE = (
    "# dj-librarian: plans list the paths of music files on this computer. Not for git.\n"
    "*.plan.json\n"
)


class IntakeError(RuntimeError):
    pass


@dataclass
class Paths:
    """root = the repo (library=False, the layout of every earlier version) or the DJ's
    dj-library folder (library=True). links.yaml, plans/ and wishlist/ sit at the root either
    way. In a library folder the apply reports go to reports/apply/ (files the DJ reads), the
    inbox and state/ (match cache, declined list) are machine state under `.cache/`
    (gitignored by the scaffold).

    carry_from = the repo root, for a library folder that took over from it: while the
    library has no state file of its own, the repo's state/<same name> is read (`state_source`)
    and the next write (`record`) carries it into the library."""

    root: Path = REPO_ROOT
    library: bool = False
    carry_from: Path | None = None

    @property
    def machine(self) -> Path:
        return self.root / ".cache" if self.library else self.root

    @property
    def links(self) -> Path:
        return self.root / "links.yaml"

    @property
    def inbox(self) -> Path:
        return self.machine / "inbox"

    @property
    def plans(self) -> Path:
        return self.root / "plans"

    @property
    def reports(self) -> Path:
        return self.root / "reports" / "apply" if self.library else self.root / "reports"

    @property
    def wishlist(self) -> Path:
        return self.root / "wishlist"

    @property
    def cache(self) -> Path:
        return self.machine / "state" / "match_cache.json"

    @property
    def declined(self) -> Path:
        return self.machine / "state" / "declined.json"

    def state_source(self, path: Path) -> Path:
        """Where to read the state file `path` (`cache` or `declined`): `path` itself, or,
        while a library folder has none yet, the repo's state/<same name> it took over from.
        So the DJ's declined tracks and AMBIGUOUS picks survive the switch to the library."""
        if self.carry_from is not None and not path.is_file():
            earlier = self.carry_from / "state" / path.name
            if earlier.is_file():
                return earlier
        return path

    def carried_state(self) -> list[str]:
        """The repo state files read in place of the library's own (`dj status` names them)."""
        return [p.name for p in (self.cache, self.declined) if self.state_source(p) != p]


def library_links_root() -> Path | None:
    """The configured library folder when its links.yaml holds at least one entry, else None.

    The scaffold writes links.yaml as comments only, so a fresh folder keeps the repo layout
    until the DJ adds a link. A links.yaml that cannot be read (not valid YAML, not UTF-8, a
    read error) still counts: the DJ gets the error for their own file from `load_links`,
    never a silent switch back to the repo.
    """
    try:
        root = libfolder.configured_root()
    except libfolder.LibraryFolderError:
        return None
    links = root / "links.yaml"
    if not links.is_file():
        return None
    try:
        data = yaml.safe_load(links.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        return root
    return root if data else None


def default_paths() -> Paths:
    """Paths for the inbox loop: the DJ's library folder (R-802), else the repo root."""
    root = library_links_root()
    if root is None:
        return Paths()
    return Paths(root, library=True, carry_from=REPO_ROOT)


def slug(text: str) -> str:
    return re.sub(r"[^\w.-]+", "_", text).strip("_")


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# -- links.yaml --------------------------------------------------------------------------


@dataclass
class Link:
    spotify: str  # playlist name, URL or ID
    crate: str  # path of a normal playlist in rekordbox, e.g. "funk_base/funk_crate"

    @property
    def slug(self) -> str:
        return slug(self.crate)


def load_links(paths: Paths) -> list[Link]:
    if not paths.links.is_file():
        raise IntakeError("links.yaml not found. Add your first link to links.yaml in your "
                          "dj-library folder (see examples/links.example.yaml).")
    try:
        data = yaml.safe_load(paths.links.read_text(encoding="utf-8")) or []
    except UnicodeDecodeError:
        raise IntakeError(f"links.yaml is not UTF-8: {paths.links}. Open it in a text editor and "
                          "save it with the encoding UTF-8.") from None
    except OSError as exc:
        raise IntakeError(f"links.yaml cannot be read ({type(exc).__name__}): {paths.links}") from None
    except yaml.YAMLError as exc:
        where = getattr(exc, "problem_mark", None)
        line = f" (line {where.line + 1})" if where is not None else ""
        raise IntakeError(f"links.yaml is not valid YAML{line}: {paths.links}") from None
    links = []
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("spotify") or not entry.get("crate"):
            raise IntakeError(f"links.yaml: each entry needs `spotify` and `crate`: {entry!r}")
        links.append(Link(str(entry["spotify"]).strip(), str(entry["crate"]).strip()))
    return links


def resolve_link(arg: str, paths: Paths) -> Link:
    """<link> on the command line = the `spotify` or the `crate` value of an entry."""
    links = load_links(paths)
    wanted = arg.strip().casefold()
    hits = [l for l in links if wanted in (l.spotify.casefold(), l.crate.casefold(), l.slug.casefold())]
    if len(hits) != 1:
        known = ", ".join(l.spotify for l in links) or "(none)"
        raise IntakeError(f"{len(hits)} links match {arg!r}. Known: {known}")
    return hits[0]


# -- pull (Spotify, read-only) -----------------------------------------------------------


def flatten(rows: Any) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        t = row.get("item") or row.get("track")  # Feb 2026 rename: track -> item
        if not t or t.get("type", "track") != "track" or not t.get("uri"):
            continue
        album = t.get("album") or {}
        out.append(
            {
                "uri": t["uri"],
                "title": t.get("name"),
                "artists": [a.get("name") for a in t.get("artists") or []],
                "album": album.get("name"),
                "duration_ms": t.get("duration_ms"),
                # Optional since Feb 2026: read when Spotify sends them (docs/spotify-audit.md).
                "isrc": (t.get("external_ids") or {}).get("isrc"),
                "label": t.get("label") or album.get("label"),
                "added_at": row.get("added_at"),
            }
        )
    return out


def find_spotify_playlist(api: Any, ref: str) -> tuple[str, str]:
    """name | URL | ID -> (playlist id, display name)."""
    m = re.search(r"(?:playlist[/:])?([A-Za-z0-9]{22})$", ref.split("?")[0])
    if m:
        return m.group(1), ref
    for p in api.my_playlists():
        if (p.get("name") or "").casefold() == ref.casefold():
            return p["id"], p["name"]
    raise IntakeError(f"No Spotify playlist of yours is called {ref!r}.")


def pull(api: Any, link: Link, paths: Paths) -> dict[str, Any]:
    pid, name = find_spotify_playlist(api, link.spotify)
    try:
        tracks = flatten(api.playlist_items(pid))
    except SpotifyError as exc:
        # Feb 2026 (C-06): 403/404 = not the DJ's playlist, or gone (dj.spotify.UNREADABLE_PLAYLIST)
        code = refused_status(exc)
        if code is None:
            raise
        raise IntakeError(unreadable_playlist(link.spotify, code)) from None
    data = {
        "playlist_id": pid,
        "name": name,
        "crate": link.crate,
        "pulled_at": datetime.now().isoformat(timespec="seconds"),
        "tracks": tracks,
    }
    path = paths.inbox / f"{link.slug}.json"
    _write_json(path, data)
    return {"link": link.spotify, "crate": link.crate, "tracks": len(tracks), "inbox": str(path)}


def load_inbox(link: Link, paths: Paths) -> dict[str, Any]:
    path = paths.inbox / f"{link.slug}.json"
    if not path.is_file():
        raise IntakeError(f"{path.name} not found in inbox/. Run `dj pull` first.")
    return json.loads(path.read_text(encoding="utf-8"))


# -- match (Spotify track -> local files) ------------------------------------------------


def _candidate(track: dict[str, Any]) -> Candidate:
    uri = track["uri"]
    return Candidate(
        uri=uri,
        title=track.get("title") or "",
        artists=[a for a in track.get("artists") or [] if a],
        album=track.get("album") or "",
        duration_ms=int(track.get("duration_ms") or 0),
        isrc=track.get("isrc") or "",
        url="https://open.spotify.com/track/" + uri.rsplit(":", 1)[-1],
    )


@dataclass
class Item:
    spotify: Candidate
    status: str
    pick: Local | None = None
    how: str = ""  # cache | isrc | exact | fuzzy
    reasons: tuple[str, ...] = ()
    top: tuple[tuple[Local, Scored], ...] = ()


def _reasons(s: Scored) -> list[str]:
    out = []
    if not s.isrc_match and s.score < match.CONFIDENT_SCORE:
        out.append(f"score {s.score}")
    if s.duration_diff_s > match.DURATION_OK_S:
        out.append(f"duration differs {s.duration_diff_s}s")
    if not s.version_ok:
        out.append("version differs")
    return out


def match_one(
    track: dict[str, Any],
    crate: str,
    tracks: list[Local],
    in_crate: set[str],
    cache: dict[str, str],
    declined: list[dict[str, Any]],
) -> Item:
    """Order: declined -> match_cache -> ISRC -> exact normalised -> fuzzy."""
    cand = _candidate(track)
    if any(d.get("crate") == crate and d.get("spotify_uri") == cand.uri for d in declined):
        return Item(cand, DECLINED)

    by_id = {t.content_id: t for t in tracks}
    cached = by_id.get(str(cache.get(cand.uri, "")))
    if cached:
        status = IN_CRATE if cached.content_id in in_crate else PROPOSE
        return Item(cand, status, pick=cached, how="cache")

    scored = [(t, match.score(t, cand)) for t in tracks]
    scored.sort(key=lambda p: (not p[1].isrc_match, -p[1].score, p[1].duration_diff_s))
    plausible = [p for p in scored if p[1].isrc_match or p[1].score >= match.POSSIBLE_SCORE]
    if not plausible:
        return Item(cand, MISSING)
    top = tuple(plausible[:3])

    confident = [p for p in plausible if p[1].confident]
    if len(confident) == 1:
        local, s = confident[0]
        how = "isrc" if s.isrc_match else "exact" if s.score == 100 else "fuzzy"
        status = IN_CRATE if local.content_id in in_crate else PROPOSE
        return Item(cand, status, pick=local, how=how, top=top)
    if len(confident) > 1:
        return Item(cand, AMBIGUOUS, reasons=(f"{len(confident)} local files match",), top=top)
    return Item(cand, AMBIGUOUS, reasons=tuple(_reasons(plausible[0][1])), top=top)


def match_link(link: Link, db: Any, paths: Paths) -> list[Item]:
    inbox = load_inbox(link, paths)
    playlist = library.find_playlist(db, link.crate)
    in_crate = library.crate_content_ids(playlist)
    tracks = library.all_tracks(db)
    cache = _read_json(paths.state_source(paths.cache), {})
    declined = _read_json(paths.state_source(paths.declined), [])
    return [match_one(t, link.crate, tracks, in_crate, cache, declined) for t in inbox["tracks"]]


def counts(items: list[Item]) -> dict[str, int]:
    return {s: sum(i.status == s for i in items) for s in STATUSES}


def _local_dict(local: Local, s: Scored | None, in_crate: bool) -> dict[str, Any]:
    out = {
        "rb_content_id": local.content_id,
        "title": local.title,
        "artist": local.artist,
        "duration_s": local.duration_s,
        "bitrate": local.bitrate,
        "path": local.path,
        "in_crate": in_crate,
    }
    if s:
        out |= {"score": s.score, "isrc_match": s.isrc_match, "duration_diff_s": s.duration_diff_s,
                "version_ok": s.version_ok}  # fmt: skip
    return out


def item_dict(item: Item, in_crate: set[str]) -> dict[str, Any]:
    return {
        "spotify_uri": item.spotify.uri,
        "spotify": item.spotify.label,
        "duration_s": round(item.spotify.duration_ms / 1000),
        "url": item.spotify.url,
        "status": item.status,
        "how": item.how,
        "reasons": list(item.reasons),
        "pick": item.pick.content_id if item.pick else None,
        "candidates": [_local_dict(l, s, l.content_id in in_crate) for l, s in item.top],
    }


# -- plan + wishlist ---------------------------------------------------------------------


def write_plan(link: Link, items: list[Item], in_crate: set[str], paths: Paths) -> Path:
    """PROPOSE and AMBIGUOUS start as `pending`. Decisions already made today are kept."""
    path = paths.plans / f"{date.today().isoformat()}-{link.slug}.plan.json"
    earlier = {i["spotify_uri"]: i for i in _read_json(path, {}).get("items", [])}
    out = []
    for item in items:
        entry = item_dict(item, in_crate)
        if item.status in (PROPOSE, AMBIGUOUS):
            old = earlier.get(item.spotify.uri, {})
            entry["decision"] = old.get("decision", PENDING)
            if item.status == AMBIGUOUS:
                entry["pick"] = old.get("pick")
        else:
            entry["decision"] = None
        out.append(entry)
    plan = {
        "spotify": link.spotify,
        "crate": link.crate,
        "created": datetime.now().isoformat(timespec="seconds"),
        "counts": counts(items),
        "how_to": "Set decision to yes or no. For AMBIGUOUS also set pick to a rb_content_id "
        "from candidates. Then: dj apply <this file>",
        "items": out,
    }
    _write_json(path, plan)
    if paths.library:
        libfolder.ensure_gitignore(paths.root, (PLANS_IGNORE_LINE,))  # add only
        libfolder.write_new_text(paths.plans / ".gitignore", PLANS_GITIGNORE)  # SKIP if there
    return path


def write_wishlist(link: Link, items: list[Item], paths: Paths) -> Path:
    """MISSING tracks grouped by artist, with the Spotify link. Regenerated every plan."""
    groups: dict[str, list[Item]] = {}
    for item in items:
        if item.status == MISSING:
            artist = item.spotify.artists[0] if item.spotify.artists else "Unknown"
            groups.setdefault(artist, []).append(item)
    lines = [f"# Wishlist: {link.crate}", "", f"From Spotify `{link.spotify}`, {date.today()}. "
             f"{sum(map(len, groups.values()))} track(s) with no local file.", ""]  # fmt: skip
    for artist in sorted(groups, key=str.casefold):
        lines.append(f"## {artist}")
        for item in groups[artist]:
            s = round(item.spotify.duration_ms / 1000)
            lines.append(f"- [{item.spotify.title}]({item.spotify.url}) ({s // 60}:{s % 60:02d})"
                         f" - {item.spotify.album}")  # fmt: skip
        lines.append("")
    path = paths.wishlist / f"{link.slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# -- apply -------------------------------------------------------------------------------


def load_plan(path: Path) -> dict[str, Any]:
    if not Path(path).is_file():
        raise IntakeError(f"Plan not found: {path}")
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in plan.get("items", []):
        if item.get("decision") == YES and not item.get("pick"):
            raise IntakeError(f"decision is yes but pick is empty: {item.get('spotify')}")
        offered = {str(c.get("rb_content_id")) for c in item.get("candidates") or []}
        if item.get("decision") == YES and offered and str(item["pick"]) not in offered:
            raise IntakeError(f"pick {item['pick']} is not one of the candidates: {item.get('spotify')}")
        if item.get("decision") not in (None, PENDING, YES, NO):
            raise IntakeError(f"decision must be pending, yes or no: {item.get('spotify')}")
    return plan


def decisions(plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    items = plan.get("items", [])
    return {d: [i for i in items if i.get("decision") == d] for d in (YES, NO, PENDING)}


def to_add(plan: dict[str, Any], in_crate: set[str]) -> list[dict[str, Any]]:
    """The yes items whose pick is not in the crate yet, each local file once."""
    seen, out = set(in_crate), []
    for item in decisions(plan)[YES]:
        if str(item["pick"]) not in seen:
            seen.add(str(item["pick"]))
            out.append(item)
    return out


def add_to_crate(db: Any, plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Inside a write session. Append only: never passes track_no (see CLAUDE.md)."""
    playlist = library.find_playlist(db, plan["crate"])
    adds = to_add(plan, library.crate_content_ids(playlist))
    for item in adds:  # check everything before the first write
        if db.get_content(ID=str(item["pick"])) is None:
            raise IntakeError(f"pick {item['pick']} is not in the library: {item['spotify']}")
    for item in adds:
        db.add_to_playlist(playlist, str(item["pick"]))
    return adds


def record(plan: dict[str, Any], plan_path: Path, added: list[dict[str, Any]], paths: Paths) -> Path:
    """After the commit: yes picks -> match_cache, no -> declined, write the report.

    In a library folder the state is read through `state_source` (the repo's state/ until the
    library has its own) and always written to the library: the first apply carries it over.
    The repo files are only read, never changed.
    """
    by_decision = decisions(plan)
    cache = _read_json(paths.state_source(paths.cache), {})
    for item in by_decision[YES]:
        cache[item["spotify_uri"]] = str(item["pick"])
    _write_json(paths.cache, cache)

    declined = _read_json(paths.state_source(paths.declined), [])
    known = {(d["crate"], d["spotify_uri"]) for d in declined}
    for item in by_decision[NO]:
        if (plan["crate"], item["spotify_uri"]) not in known:
            declined.append({"crate": plan["crate"], "spotify_uri": item["spotify_uri"],
                             "spotify": item.get("spotify"), "date": date.today().isoformat()})  # fmt: skip
    _write_json(paths.declined, declined)

    report = {
        "plan": _plan_ref(plan_path, paths),
        "spotify": plan.get("spotify"),
        "crate": plan["crate"],
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "added": [{"spotify": i["spotify"], "rb_content_id": str(i["pick"])} for i in added],
        "counts": {
            "added": len(added),
            "yes_already_in_crate": len(by_decision[YES]) - len(added),
            "declined": len(by_decision[NO]),
            "still_pending": len(by_decision[PENDING]),
        },
    }
    path = paths.reports / f"{date.today().isoformat()}-{slug(plan['crate'])}.report.json"
    _write_json(path, report)
    return path


def _plan_ref(plan_path: Path, paths: Paths) -> str:
    """The plan as the report names it. In a library folder the report is a file the DJ reads
    (reports/apply/), so the path is library-relative; a plan from outside: its name only."""
    if not paths.library:
        return str(plan_path)
    try:
        return libfolder.relative(paths.root, Path(plan_path).resolve())
    except libfolder.LibraryFolderError:
        return Path(plan_path).name


def last_report(link: Link, paths: Paths) -> str | None:
    found = sorted(paths.reports.glob(f"*-{link.slug}.report.json"))
    return _read_json(found[-1], {}).get("applied_at") if found else None
