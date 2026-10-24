"""The preview gate for the dj CLI's write commands (R-1102) and power mode (R-205).

Stdlib only (+ `dj.gate`, `dj.hostenv`, `dj.safety`, which import no engine package at module level).

    changes = [...]                              # what the write would do, as plain JSON values
    pid = record("copy", args, changes)          # the dry-run: prints "Preview id: <pid>"
    precheck(preview_id, "copy", args)           # optional: everything but the plan, before it
                                                 # costs a token or a network call (push, build)
    check(preview_id, "copy", args, changes)     # the write, recomputed from a fresh read,
    ... write ...                                # before the backup / write token / first file
    consume(preview_id)                          # only after something was written

`args` are the command's normalised arguments (resolved paths, flags, the effective Spotify
name); `changes` are the planned changes (the actions, adds or items a write would perform).
The gate stores `digest(changes)`, so the same unused plan gives the same id (see `dj.gate`):
any change between the preview and the write gives another digest, and the write is refused.

One preview, one write, and a new preview may write again: a dry-run of a plan whose id was
already used gets a fresh id (`Gate.record(rearm=True)`). The CLI's targets can return to their
earlier state (the DJ removed the added rows in rekordbox, deleted the Spotify playlist, or ran
`dj tidy undo`), and the same plan must then be writable again, as it was before the gate. A
replay of the used id stays refused.

Records live in `REPO_ROOT/state/previews/` (gitignored); in the desktop extension in
`<dj-library>/.cache/engine/state/previews/` (dj.hostenv.state_root). `STATE_DIR` is read at call
time, so tests point it at a temporary folder.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dj import hostenv, safety
from dj.gate import Gate, GateError, require_id

STATE_DIR = hostenv.state_root() / "state"

POWER_MODE_REFUSAL = (
    "master.db writes are power mode (Windows only): add --power-mode. The default is an XML to "
    "import instead: --xml for inbox adds and copies (dj apply, dj copy), dj library build for new "
    "folders and playlists"
)

__all__ = [
    "POWER_MODE_REFUSAL",
    "STATE_DIR",
    "GateError",
    "Recorded",
    "check",
    "consume",
    "digest",
    "gate",
    "path_arg",
    "precheck",
    "record",
    "require_id",
    "require_power_mode",
]


def gate() -> Gate:
    return Gate(STATE_DIR)


def digest(changes: Any) -> str:
    """sha256 of the canonical JSON text of the planned changes (a value JSON cannot hold, such
    as a date from YAML, is written as its text)."""
    text = json.dumps(changes, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Recorded:
    """A recorded preview: its id, fresh and unused."""

    preview_id: str

    def lines(self) -> list[str]:
        """The text lines of a dry-run: one `Preview id:` line."""
        return [f"Preview id: {self.preview_id}"]


def record(kind: str, args: Mapping[str, Any], changes: Any) -> Recorded:
    """Record a preview of `changes` and return its id: unused, fresh for 24 hours. When the
    same plan's id was used by an earlier write, this preview gets a new id (rearm)."""
    return Recorded(gate().record(kind, args, digest(changes), rearm=True))


def precheck(preview_id: str | None, kind: str, args: Mapping[str, Any]) -> None:
    """GateError unless `preview_id` is a recorded, unused, fresh preview of this command with
    these arguments: every check but the plan's. For a write whose plan costs a token request or
    network calls to compute (push, build); `check` compares the plan afterwards."""
    pid = require_id(preview_id)
    g = gate()
    try:
        g.check(pid, kind, args, g.load(pid).digest)
    except GateError as exc:
        raise _worded(exc, pid) from None


def check(preview_id: str | None, kind: str, args: Mapping[str, Any], changes: Any) -> None:
    """GateError unless `preview_id` is a fresh, unused preview of exactly these changes."""
    pid = require_id(preview_id)
    try:
        gate().check(pid, kind, args, digest(changes))
    except GateError as exc:
        raise _worded(exc, pid) from None


def _worded(exc: GateError, pid: str) -> GateError:
    """dj.gate words two refusals for dj-build; the CLI's writers say them their own way."""
    text = str(exc)
    if text.startswith("Something changed since preview"):
        return GateError(
            f"The plan changed since preview {pid}. Nothing written; preview again and show the DJ the "
            "new result."
        )
    if " was already used (" in text:  # with rearm, a new dry-run gives a new id: no change needed
        head = text.split(" One preview, one write", 1)[0]
        return GateError(f"{head} One preview, one write: preview again for a new id and show the DJ.")
    return exc


def consume(preview_id: str, written: str | None = None) -> str | None:
    """Mark the preview used, after the write wrote something. The write is done by then, so a
    failure here is a warning to show (returned), never an error."""
    try:
        gate().consume(preview_id, written=written)
    except (GateError, OSError) as exc:
        return f"Preview {preview_id} could not be marked used ({exc}). Do not use it again."
    return None


def require_power_mode(power_mode: bool) -> None:
    """R-205: a master.db write needs --power-mode, and Windows. GateError (one line) otherwise.
    The engine settings come first: DJ_POWER_MODE false refuses whatever the flag says, and so
    does an unset value in the desktop extension (it fails closed); true, or unset in a clone,
    leaves this rule as it was (the setting never turns power mode on).

    Runs before the preview id is looked at and before any read, process check or backup."""
    refusal = hostenv.power_mode_refusal()
    if refusal:
        raise GateError(refusal)
    if not power_mode:
        raise GateError(POWER_MODE_REFUSAL)
    if sys.platform not in safety.DB_WRITE_PLATFORMS:
        raise GateError(
            f"master.db writes are power mode, Windows only; this is {sys.platform}. Write an XML to "
            "import instead: --xml for inbox adds and copies (dj apply, dj copy), dj library build for "
            "new folders and playlists. Nothing written."
        )


def path_arg(path: str | Path) -> str:
    """A file argument in the gate's args: resolved, POSIX spelling."""
    return Path(path).resolve().as_posix()
