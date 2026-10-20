"""The preview gate: a real write needs the id of a preview the DJ said yes to (R-1102).

Door 1 core: stdlib only (+ `dj.libfolder` for the atomic write).

    gate = Gate(folder.cache)                       # library folder: <library>/.cache
    pid = gate.record("build", {"proposal": slug}, digest)   # at preview time
    gate.check(pid, "build", {"proposal": slug}, digest)     # at write time; raises GateError
    ... write ...
    gate.consume(pid)                               # after the write succeeded

A preview id is `sha256(kind, canonical args, digest)` cut to 12 hex digits, so the same preview
of the same content gets the same id. Its record is `<state_dir>/previews/<id>.json`.

`check` refuses (GateError) when the id is empty or malformed, has no record, belongs to another
kind or other arguments, was already used, is older than 24 hours, or when the content changed
since the preview (another digest).

One preview id, one write: a used record is never re-armed. Previewing the same content again
after its write gives the same id, still marked used, so `check` refuses it; a new write needs
changed content (and so a new id). Previewing unused content again refreshes its time.
`record(..., rearm=True)` (the dj CLI's writers, whose target can return to its earlier state)
keeps the used record used and gives the new preview the next id of the same content instead
(generation 1, 2, ...): the old id stays refused, the new one allows one write.

The clock: `now` is a parameter everywhere (tests pass a fixed time); None = the wall clock.
Times are stored and compared in UTC, so a clock change (daylight saving, travel) neither
expires a preview early nor stretches its 24 hours. A naive `now` is local time.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from dj.libfolder import write_text

MAX_AGE = timedelta(hours=24)
CLOCK_SKEW = timedelta(minutes=5)  # a record this far in the future is refused
MAX_GENERATIONS = 1000  # rearm: fresh ids of one content, a bound on the lookup
ID_LENGTH = 12
ID_PATTERN = re.compile(rf"^[0-9a-f]{{{ID_LENGTH}}}$")


class GateError(ValueError):
    """The write is refused: no valid preview for it. Nothing was written."""


def canonical(args: Mapping[str, Any]) -> str:
    """Arguments as one canonical JSON text (sorted keys, no spaces)."""
    if not isinstance(args, Mapping):
        raise GateError(f"preview arguments must be a mapping, got {type(args).__name__}")
    try:
        return json.dumps(dict(args), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise GateError(f"preview arguments must be plain JSON values: {exc}") from exc


def preview_id_for(kind: str, args: Mapping[str, Any], digest: str, generation: int = 0) -> str:
    """The id a preview of `kind` with `args` over content `digest` gets. `generation` n > 0: the
    id of the n-th fresh preview of the same content after the earlier ones were used (rearm)."""
    _check_kind(kind)
    _check_digest(digest)
    parts = [kind, canonical(args), digest] + ([str(generation)] if generation else [])
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:ID_LENGTH]


def valid_id(preview_id: Any) -> bool:
    """12 lower-case hex digits: the only shape a preview id has."""
    return isinstance(preview_id, str) and bool(ID_PATTERN.fullmatch(preview_id))  # no trailing newline


def require_id(preview_id: Any) -> str:
    """`preview_id` when it has the shape of one; else GateError (empty: "No preview id")."""
    if not valid_id(preview_id):
        raise GateError(_bad_id(preview_id))
    return preview_id


@dataclass(frozen=True)
class Preview:
    """One recorded preview, as stored in its JSON file."""

    id: str
    kind: str
    args: dict[str, Any]
    digest: str
    created: str  # ISO timestamp, UTC
    used: str | None = None  # ISO timestamp of the write (UTC), or None
    written: str | None = None  # what the write produced (e.g. a relative file path), or None


class Gate:
    """Preview records under `<state_dir>/previews/`."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)

    @property
    def previews(self) -> Path:
        return self.state_dir / "previews"

    def path_for(self, preview_id: str) -> Path:
        return self.previews / f"{require_id(preview_id)}.json"

    def record(
        self,
        kind: str,
        args: Mapping[str, Any],
        digest: str,
        *,
        now: datetime | None = None,
        rearm: bool = False,
    ) -> str:
        """Record a preview and return its id.

        An unused record with the same id is replaced fresh. A used one is kept as it is: the
        id stays used (one preview, one write); `load(id).used` tells the caller. With `rearm`,
        the preview instead gets the first id of the same content whose record is not used
        (generation 1, 2, ...), recorded fresh; the used ids stay refused.
        """
        for generation in range(MAX_GENERATIONS):
            preview_id = preview_id_for(kind, args, digest, generation)
            try:
                used = self.load(preview_id).used
            except GateError:
                break  # no record yet, or an unreadable one: write a fresh record
            if not used:
                break
            if not rearm:
                return preview_id
        else:
            raise GateError(f"This exact {kind} write already ran {MAX_GENERATIONS} times. Nothing recorded.")
        data = {
            "id": preview_id,
            "kind": kind,
            "args": json.loads(canonical(args)),
            "digest": digest,
            "created": _now(now).isoformat(timespec="seconds"),
            "used": None,
            "written": None,
        }
        self.previews.mkdir(parents=True, exist_ok=True)
        write_text(self.path_for(preview_id), json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return preview_id

    def load(self, preview_id: str) -> Preview:
        """The stored record. Missing or unreadable -> GateError."""
        path = self.path_for(preview_id)
        if not path.is_file():
            raise GateError(
                f"No preview with id {preview_id}. Run the preview first and show it to the DJ."
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = Preview(
                id=str(data["id"]),
                kind=str(data["kind"]),
                args=dict(data["args"]),
                digest=str(data["digest"]),
                created=str(data["created"]),
                used=data.get("used"),
                written=data.get("written"),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise GateError(f"Preview {preview_id} is unreadable ({exc}). Preview again.") from exc
        if record.id != preview_id:
            raise GateError(f"Preview {preview_id} is unreadable (it names {record.id}). Preview again.")
        return record

    def check(
        self,
        preview_id: str,
        kind: str,
        args: Mapping[str, Any],
        digest: str,
        *,
        now: datetime | None = None,
    ) -> Preview:
        """Return the record when this write may go ahead; else raise GateError."""
        record = self.load(require_id(preview_id))
        if record.kind != kind:
            raise GateError(
                f"Preview {preview_id} is for a {record.kind} write, not {kind}. Preview this one first."
            )
        if canonical(record.args) != canonical(args):
            raise GateError(
                f"Preview {preview_id} is for {canonical(record.args)}, not {canonical(args)}. "
                "Preview this one first."
            )
        if record.used:
            wrote = f", wrote {record.written}" if record.written else ""
            raise GateError(
                f"Preview {preview_id} was already used ({record.used}{wrote}). One preview, one "
                "write: a new write needs changed content and a new preview."
            )
        try:
            created = _now(datetime.fromisoformat(record.created))
        except ValueError as exc:
            raise GateError(f"Preview {preview_id} has no readable time. Preview again.") from exc
        age = _now(now) - created
        if age > MAX_AGE:
            raise GateError(
                f"Preview {preview_id} is older than 24 hours ({record.created}). Preview again."
            )
        if age < -CLOCK_SKEW:
            raise GateError(f"Preview {preview_id} is dated in the future ({record.created}). Preview again.")
        if record.digest != digest:
            raise GateError(
                f"Something changed since preview {preview_id} (the proposal, the current tree or "
                "the tracks). Preview again and show the DJ the new result."
            )
        return record

    def consume(
        self, preview_id: str, *, now: datetime | None = None, written: str | None = None
    ) -> Preview:
        """Mark the preview used, after the write succeeded. Missing -> GateError.

        `written`: what the write produced (a relative file path), kept in the record."""
        record = self.load(preview_id)
        data = {
            "id": record.id,
            "kind": record.kind,
            "args": record.args,
            "digest": record.digest,
            "created": record.created,
            "used": _now(now).isoformat(timespec="seconds"),
            "written": written,
        }
        write_text(self.path_for(preview_id), json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return Preview(**data)


def _now(moment: datetime | None) -> datetime:
    """`moment` (None = the wall clock) in UTC, whole seconds. A naive time is local time."""
    moment = moment if moment is not None else datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0)


def _check_kind(kind: Any) -> None:
    if not isinstance(kind, str) or not kind.strip():
        raise GateError(f"preview kind must be a non-empty text, got {kind!r}")


def _check_digest(digest: Any) -> None:
    if not isinstance(digest, str) or not digest.strip():
        raise GateError(f"preview digest must be a non-empty text, got {digest!r}")


def _bad_id(preview_id: Any) -> str:
    if preview_id is None or (isinstance(preview_id, str) and not preview_id.strip()):
        return "No preview id. Run the preview, show it to the DJ, and write only after a yes."
    return f"{preview_id!r} is not a preview id (12 hex digits from the preview)."
