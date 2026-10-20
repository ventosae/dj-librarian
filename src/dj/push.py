"""dj push: copy a rekordbox playlist to a private Spotify playlist.

rekordbox is only read. On Spotify the tool creates and adds, never removes or reorders.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from dj import libfolder, library, match
from dj.match import AMBIGUOUS, MATCH, Candidate, Local, Result
from dj.safety import REPO_ROOT
from dj.spotify import SpotifyError, refused_status

STATE_FILE = REPO_ROOT / "state" / "push.json"
REPORT_DIR = REPO_ROOT / "reports"


class PushError(RuntimeError):
    pass


ADD_BATCH = 100  # Spotify's most items per add request


class PushInterrupted(SpotifyError):
    """Spotify (or the state file) failed after the playlist existed: what was written before the
    error, so the caller can log it (R-904). The message is the original error's."""

    def __init__(self, cause: BaseException, playlist: dict[str, Any], created: bool, added: int, left: int):
        super().__init__(str(cause))
        self.playlist, self.created, self.added, self.left = playlist, created, added, left


# -- rekordbox side (read-only) ----------------------------------------------------------


def find_playlist(db: Any, path: str) -> Any:
    try:
        return library.find_playlist(db, path)
    except library.LibraryError as exc:
        raise PushError(str(exc)) from exc


def local_tracks(playlist: Any) -> list[Local]:
    songs = sorted(playlist.Songs, key=lambda s: s.TrackNo or 0)
    return [library.to_local(s.Content) for s in songs if library.alive(s) and library.alive(s.Content)]


# -- matching against Spotify search -----------------------------------------------------


def queries(local: Local) -> list[str]:
    base, version = match.parse_title(local.title, local.artist)
    artist = match.primary_artist(local.artist)
    out = []
    if local.isrc:
        out.append(f"isrc:{local.isrc}")
    if base and artist:
        out.append(f"track:{base} artist:{artist}")
    out.append(" ".join(x for x in (artist, base, version) if x))
    return out


def to_candidate(item: dict[str, Any]) -> Candidate:
    return Candidate(
        uri=item.get("uri", ""),
        title=item.get("name", ""),
        artists=[a.get("name", "") for a in item.get("artists") or []],
        album=(item.get("album") or {}).get("name", ""),
        duration_ms=int(item.get("duration_ms") or 0),
        isrc=(item.get("external_ids") or {}).get("isrc") or "",
        url=(item.get("external_urls") or {}).get("spotify", ""),
    )


def match_track(api: Any, local: Local, ignore_duration: bool = False) -> Result:
    """Search from the most to the least precise query; stop at the first confident match."""
    candidates: list[Candidate] = []
    for query in queries(local):
        candidates += [to_candidate(i) for i in api.search_tracks(query) if i.get("uri")]
        result = match.decide(local, candidates, ignore_duration)
        if result.status == MATCH:
            return result
    return match.decide(local, candidates, ignore_duration)


def selected_uris(results: list[Result], include_ambiguous: bool) -> list[str]:
    wanted = {MATCH, AMBIGUOUS} if include_ambiguous else {MATCH}
    uris: list[str] = []
    for r in results:
        if r.status in wanted and r.pick and r.pick.candidate.uri not in uris:
            uris.append(r.pick.candidate.uri)
    return uris


# -- applying on Spotify (create and add only) -------------------------------------------


def _load_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def apply(
    api: Any,
    rb_playlist_id: str,
    name: str,
    uris: list[str],
    state_file: Path | None = None,
    description: str = "Pushed from rekordbox by dj-librarian.",
) -> dict[str, Any]:
    """Create the Spotify playlist once (remembered in state/push.json), add what is missing.

    Only a remembered playlist Spotify answers 404 or 403 for counts as gone and is made again; any
    other error reading it (5xx, network, rate limit) is raised before anything is created.
    An error once the playlist exists (a new one is created, or adds have begun) is raised as
    PushInterrupted with what was written by then; an error before that writes nothing."""
    state_file = state_file or STATE_FILE
    state = _load_state(state_file)
    entry = state.get(rb_playlist_id)
    existing: list[str] = []
    created = False
    if entry:
        try:
            existing = api.playlist_item_uris(entry["spotify_id"])
        except SpotifyError as exc:
            if refused_status(exc) is None:
                raise  # Spotify did not answer: never a second playlist the DJ did not say yes to
            entry = None  # deleted on Spotify, or no longer this app's to read: make a new one
    if not entry:
        made = api.create_playlist(name, description)
        entry = {
            "spotify_id": made["id"],
            "name": name,
            "url": (made.get("external_urls") or {}).get("spotify", ""),
        }
        created = True

    to_add = [u for u in uris if u not in existing]
    added = 0
    try:
        if created:
            state[rb_playlist_id] = entry
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        for start in range(0, len(to_add), ADD_BATCH):  # one request per batch: count what got in
            batch = to_add[start : start + ADD_BATCH]
            api.add_items(entry["spotify_id"], batch)
            added += len(batch)
    except (SpotifyError, OSError) as exc:
        if created or added:
            raise PushInterrupted(exc, entry, created, added, len(to_add) - added) from exc
        raise
    return {
        "playlist": entry,
        "created": created,
        "added": len(to_add),
        "already_there": len(uris) - len(to_add),
    }


# -- output ------------------------------------------------------------------------------


def result_dict(r: Result) -> dict[str, Any]:
    def scored(s: match.Scored) -> dict[str, Any]:
        return {
            "uri": s.candidate.uri,
            "label": s.candidate.label,
            "album": s.candidate.album,
            "url": s.candidate.url,
            "score": s.score,
            "isrc_match": s.isrc_match,
            "duration_diff_s": s.duration_diff_s,
            "version_ok": s.version_ok,
        }

    return {
        "rb_content_id": r.local.content_id,
        "local": r.local.label,
        "status": r.status,
        "reasons": r.reasons,
        "pick": scored(r.pick) if r.pick else None,
        "top": [scored(s) for s in r.top],
    }


def result_line(r: Result) -> str:
    text = f"{r.status:<10} {r.local.label}"
    if r.pick:
        how = "isrc" if r.pick.isrc_match else f"score {r.pick.score}"
        text += f"\n           -> {r.pick.candidate.label}  [{how}, {r.pick.duration_diff_s}s off]"
        if r.reasons:
            text += f"  ({'; '.join(r.reasons)})"
        if r.status == AMBIGUOUS and r.pick.candidate.url:
            text += f"\n              {r.pick.candidate.url}"
    return text


def write_report(
    name: str, payload: dict[str, Any], report_dir: Path | None = None, kind: str = "push"
) -> Path:
    report_dir = report_dir or REPORT_DIR
    slug = re.sub(r"[^\w.-]+", "_", name).strip("_")
    # create-only: a second run on one day gets -2, the first report stays
    return libfolder.write_new_numbered(report_dir, f"{date.today().isoformat()}-{kind}-{slug}", ".report.json",
                                        json.dumps(payload, indent=2, ensure_ascii=False))
