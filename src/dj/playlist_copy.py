"""dj copy: append the tracks of one rekordbox playlist to another.

The source is only read. The target only grows: a track already in it is skipped,
nothing is removed or reordered, and track_no is never passed (see CLAUDE.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dj import libfolder, library
from dj.intake import slug
from dj.safety import REPO_ROOT

REPORT_DIR = REPO_ROOT / "reports"
ADD, SKIP = "ADD", "SKIP"


class CopyError(RuntimeError):
    pass


@dataclass
class Row:
    op: str
    content_id: str
    label: str
    note: str = ""

    def line(self) -> str:
        return f"{self.op:<5}{self.label}" + (f"  ({self.note})" if self.note else "")


@dataclass
class Plan:
    source: str
    target: str
    target_exists: bool = True
    rows: list[Row] = field(default_factory=list)

    @property
    def adds(self) -> list[Row]:
        return [r for r in self.rows if r.op == ADD]

    def counts(self) -> dict[str, int]:
        return {op: sum(r.op == op for r in self.rows) for op in (ADD, SKIP)}

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "target_exists": self.target_exists,
            "counts": self.counts(),
            "rows": [vars(r) for r in self.rows],
        }


def _deleted(row: Any) -> bool:
    """rekordbox flags a row it removed but has not purged yet. Treat it as gone."""
    return bool(getattr(row, "rb_local_deleted", 0))


def _find(db: Any, path: str) -> Any:
    try:
        return library.find_playlist(db, path)
    except library.LibraryError as exc:
        raise CopyError(str(exc)) from exc


def plan(db: Any, source: str, target: str, allow_missing_target: bool = False) -> Plan:
    """Reads only. One Row per track of the source, in the source's order.

    allow_missing_target is for the dry-run: a target that `dj tree` has not created yet
    counts as empty, so the whole job can be reviewed before anything is written.
    """
    src = _find(db, source)
    try:
        dst = _find(db, target)
    except CopyError:
        if not allow_missing_target:
            raise
        dst = None
    if dst is not None and str(dst.ID) == str(src.ID):
        raise CopyError("Source and target are the same playlist.")

    in_target = {str(s.ContentID) for s in dst.Songs if not _deleted(s)} if dst else set()
    out = Plan(source, target, target_exists=dst is not None)
    seen: set[str] = set()
    for song in sorted(src.Songs, key=lambda s: s.TrackNo or 0):
        if _deleted(song):
            continue
        cid, content = str(song.ContentID), song.Content
        if content is None or _deleted(content):
            out.rows.append(Row(SKIP, cid, f"content {cid}", "not in the library"))
            continue
        label = library.to_local(content).label
        if cid in in_target:
            out.rows.append(Row(SKIP, cid, label, "already in target"))
        elif cid in seen:
            out.rows.append(Row(SKIP, cid, label, "twice in source"))
        else:
            out.rows.append(Row(ADD, cid, label))
        seen.add(cid)
    return out


def apply(db: Any, source: str, target: str) -> Plan:
    """Inside a write session; the caller commits. Append only: never passes track_no."""
    out = plan(db, source, target)  # re-planned against the DB that is being written
    dst = _find(db, target)
    for row in out.adds:
        db.add_to_playlist(dst, row.content_id)
    return out


def write_report(done: Plan) -> Path:
    report = done.as_dict() | {"applied_at": datetime.now().isoformat(timespec="seconds")}
    # create-only: a second copy into the same target on one day gets -2, the first report stays
    return libfolder.write_new_numbered(REPORT_DIR, f"{date.today().isoformat()}-copy-{slug(done.target)}",
                                        ".report.json", json.dumps(report, indent=2, ensure_ascii=False))
