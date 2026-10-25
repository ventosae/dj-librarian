"""dj-build and dj-crate straight into rekordbox: the power-mode writer (W-38, D-32, R-504, R-205).

    dj library build <proposal> --source db --apply --power-mode --preview-id <id>
    dj library crate <slug>     --source db --apply --power-mode --preview-id <id>

With the engine, power mode on and rekordbox closed, a proposal or a crate the DJ said yes to goes
into master.db instead of an XML to import. The plan is the XML route's own (`XmlPlan`: the folders,
the playlists and their tracks the preview showed, smart playlists left MANUAL), so both routes write
the same thing, and one preview id serves either (one preview, one write).

The chain, in this order, every link the existing one:
1. power mode on: the engine setting (DJ_POWER_MODE), --power-mode, Windows (`write_gate.require_power_mode`),
   and a build that reads rekordbox itself (`--source db`: the track ids are master.db's);
2. the preview id: its shape, then the build's or crate's own gate record (same content, unused, under 24 h);
3. rekordbox closed (`safety.open_db`'s process check), else "Close rekordbox, then say yes again. Nothing written.";
4. a verified backup of master.db, masterPlaylists6.xml, -wal and -shm (`safety.backup`);
5. the write, one session: re-plan against the live master.db with the tree writer (`tree.walk`), which
   must create exactly the nodes the preview did; every track a live row; then `tree.apply_rows` makes the
   folders and playlists and `add_to_playlist` the memberships in plan order (never track_no); one commit.
Any failure: rollback, nothing half-written, one line why. The log.md line is the XML route's with
`master.db` where the file was.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import typer

from dj import build_structure, libfolder, library, safety, write_gate
from dj import crate as crate_mod
from dj import tree as tree_mod
from dj.build_library import DB_READ, source_of
from dj.gate import GateError
from dj.libfolder import LibraryFolder, LibraryFolderError
from dj.model import Library, LibraryError, PlaylistNode
from dj.writers.rekordbox_xml import PlannedNode, XmlPlan, plan_lists

PREVIEW_LINE = "Writes into rekordbox directly (rekordbox must be closed). Backup first."
CLOSE_FIRST = "Close rekordbox, then say yes again. Nothing written."
OPEN_IT = "Open rekordbox: it's in the tree."
CHANGED = "rekordbox's tree changed since the preview. Nothing written; preview again and show the DJ."
SOURCE_XML = ("A write into rekordbox needs the build to read rekordbox itself: run the engine analysis "
              "(dj_library_analyze source=\"db\") so library.yaml says source: db, or pass --source db, then preview "
              "again. Nothing written.")  # fmt: skip
NOT_WINDOWS = "Writes into rekordbox are Windows only for now (Q-35): the XML to import is the route here."
CHANGED_ON_DISK = "WARNING: changed on disk"  # safety.open_db's note when a source file changed despite the failure
EXIT_ERROR, EXIT_REKORDBOX_RUNNING = 1, 2


class DbWriteError(RuntimeError):
    """Refused or rolled back: nothing was written. The message is one line."""


class RekordboxOpen(DbWriteError):
    """rekordbox runs (before the write, or it was started during it): nothing was written."""


class RolledBack(DbWriteError):
    """The write session failed part way: everything was rolled back, nothing was written."""


class MaybeWritten(DbWriteError):
    """The write stopped after master.db or masterPlaylists6.xml changed on disk (pyrekordbox's commit
    writes master.db, then saves masterPlaylists6.xml): not a rollback. The message names the backup."""


# -- is the route open --------------------------------------------------------------------------


def route_off(folder: LibraryFolder | str | Path, source: str | None = None) -> str | None:
    """Why a proposal or crate cannot go into rekordbox from here (one line), or None: the engine
    setting, Windows, and a build that reads master.db. The call still needs --power-mode."""
    if sys.platform not in safety.DB_WRITE_PLATFORMS:  # first: a Mac's off setting is not the reason
        return NOT_WINDOWS
    try:
        write_gate.require_power_mode(True)
    except GateError as exc:
        return str(exc)
    root = folder.root if isinstance(folder, LibraryFolder) else Path(folder)
    try:
        read = source_of(LibraryFolder(root), source)
    except (LibraryFolderError, ValueError, OSError) as exc:
        return f"{exc}"
    return None if read == "db" else SOURCE_XML


def preview_keys(folder: LibraryFolder | str | Path, source: str | None = None) -> dict[str, Any]:
    """The preview's keys for the skill: `into_rekordbox` (the line, or None) and, when None, why."""
    off = route_off(folder, source)
    return {"into_rekordbox": PREVIEW_LINE} if off is None else {"into_rekordbox": None, "into_rekordbox_off": off}


def preview_lines(data: dict[str, Any], command: str) -> list[str]:
    """The preview's text lines for the route: the line and the command, after the XML's."""
    if data.get("blocked") or not data.get("into_rekordbox"):
        return []
    return [PREVIEW_LINE, f"into rekordbox: {command} --apply --power-mode --preview-id {data['preview_id']} "
                          "(only after the DJ said yes, rekordbox closed)"]  # fmt: skip


# -- the write -----------------------------------------------------------------------------------


def _key(path: Iterable[str]) -> tuple[str, ...]:
    return tuple(tree_mod.norm(p) for p in path)


def _nodes(planned: Iterable[PlannedNode]) -> list[tree_mod.Node]:
    return [tree_mod.Node(n.kind, n.name, children=_nodes(n.children)) for n in planned]


def expected(planned: Iterable[PlannedNode], roots: Iterable[PlaylistNode], prefix: tuple[str, ...] = ()) -> set:
    """The nodes the preview creates: every plan node the previewed library lacks (name and kind,
    as the tree writer matches them), and everything under it."""
    out: set[tuple[str, ...]] = set()
    level: dict[tuple[str, str], PlaylistNode] = {}
    for n in roots:  # the first of same-named siblings, as the preview diff and tree.walk take it
        level.setdefault((tree_mod.norm(n.name), n.kind), n)
    for node in planned:
        path = prefix + (tree_mod.norm(node.name),)
        there = level.get((path[-1], node.kind))
        out |= expected(node.children, there.children if there else (), path)
        if there is None:
            out.add(path)
    return out


def write_plan(db: Any, plan: XmlPlan, lib: Library) -> dict[str, int]:
    """Inside `safety.open_db(write=True)`: the session commits once, or rolls everything back.
    Checks first, then writes: a refusal leaves the session untouched."""
    actions = tree_mod.walk(_nodes(plan.nodes), db)
    creates = {_key(a.path) for a in actions if a.op == tree_mod.CREATE}
    if any(a.op == tree_mod.CONFLICT for a in actions) or creates != expected(plan.nodes, lib.roots):
        raise DbWriteError(CHANGED)
    fills = [n for n in plan.walk() if n.kind == "playlist"]
    live = {t.content_id for t in library.all_tracks(db)}  # alive rows only
    gone = sorted({tid for n in fills for tid in n.track_ids} - live)
    if gone:
        raise DbWriteError(f"track {gone[0]} is not in rekordbox any more ({len(gone)} in all). Preview again. "
                           "Nothing written.")  # fmt: skip
    rows = {_key(path): row for path, row in tree_mod.apply_rows(actions, db).items()}
    added = 0
    for node in fills:
        row = rows.get(_key(node.path))
        if row is None:  # a plan playlist the tree already has: the expected-set check above rules it out
            raise DbWriteError(f"{'/'.join(node.path)} exists in rekordbox already. {CHANGED}")
        for tid in node.track_ids:
            db.add_to_playlist(row, tid)  # append: never track_no (CLAUDE.md)
            added += 1
    kinds = [a.kind for a in actions if a.op == tree_mod.CREATE]
    return {"folders": kinds.count("folder"), "playlists": kinds.count("playlist"), "entries": added}


@contextmanager
def _session() -> Iterator[Any]:
    """`safety.open_db(write=True)`: power mode, Windows, rekordbox closed, verified backup, one commit."""
    try:
        with safety.open_db(write=True) as db:
            yield db
    except safety.RekordboxRunningError as exc:
        raise RekordboxOpen(CLOSE_FIRST) from exc
    except Exception as exc:
        warned = [n for n in getattr(exc, "__notes__", []) if n.startswith(CHANGED_ON_DISK)]
        if warned:  # after pyrekordbox's commit wrote master.db: not a rollback, whatever the error
            raise MaybeWritten(f"The write stopped after rekordbox's files changed ({_short(exc)}). {warned[0]} "
                               f"The backup is in {backup_dir()}. Open rekordbox and check the tree.") from exc
        if isinstance(exc, (DbWriteError, safety.SafetyError)):
            raise  # one line already: a refusal in the session, or no backup / not Windows (nothing written)
        raise RolledBack(f"The write stopped ({_short(exc)}). Rolled back: nothing written.") from exc


def _short(exc: BaseException) -> str:
    first = (str(exc).strip().splitlines() or [""])[0][:200]
    return f"{type(exc).__name__}: {first}"


def backup_dir() -> str:
    """Where the power-mode backup went, as a whole path: the engine's folder, not the dj-library's backups/."""
    return f"{safety.BACKUP_DIR.resolve()}{os.sep}"


@contextmanager
def _logged_if_written(root: Path, action: str, today: date | None) -> Iterator[None]:
    """R-904 for a write that stopped after rekordbox's files changed (MaybeWritten): one log.md line."""
    try:
        yield
    except MaybeWritten:
        try:
            libfolder.append_log(root, f"{action}, stopped after the commit", None, file=DB_READ, today=today)
        except (LibraryFolderError, OSError):
            pass  # the error line names the backup; the log line is the extra
        raise


@dataclass(frozen=True)
class DbResult:
    kind: str  # build | crate
    slug: str
    counts: dict[str, int]
    written: dict[str, int]  # what went into master.db: folders, playlists, entries (tracks in playlists)
    log_line: str
    record: str = ""  # crate: crates/<slug>.md
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        out = {"counts": self.counts, self.kind: self.slug, "written": DB_READ, "into_rekordbox": self.written,
               "backup": backup_dir(), "log_line": self.log_line, "next": OPEN_IT,
               "warnings": list(self.warnings)}  # fmt: skip
        if self.kind == "crate":
            out["record"] = self.record
        return out

    def lines(self) -> list[str]:
        w = self.written
        out = [f"Wrote into rekordbox: {w['folders']} folder(s), {w['playlists']} playlist(s), {w['entries']} "
               f"playlist entries, one commit. Backup in {backup_dir()}", OPEN_IT]  # fmt: skip
        if self.record:
            out.append(f"Crate record: {self.record}")
        return out + [f"log.md: {self.log_line}"] + [f"WARNING {x}" for x in self.warnings]


def _route(folder: LibraryFolder | str | Path, source: str | None) -> None:
    off = route_off(folder, source)
    if off is not None:
        raise DbWriteError(off)


def _after(gate: Any, preview_id: str, now: datetime | None, root: Path, action: str, counts: dict[str, int],
           today: date | None) -> tuple[str, list[str]]:  # fmt: skip
    """After the commit (the write stands): the id used up, the log.md line. Failures are warnings."""
    warnings: list[str] = []
    try:
        gate.consume(preview_id, now=now, written=DB_READ)
    except (GateError, OSError) as exc:
        warnings.append(f"Preview {preview_id} could not be marked used ({exc}). Do not use it again.")
    try:
        line = libfolder.append_log(root, action, counts, file=DB_READ, now=now, today=today)
    except (LibraryFolderError, OSError) as exc:
        told = ", ".join(f"{n} {key}" for key, n in counts.items())
        line = f"{libfolder.log_clock(today, now)} {action} -> {told}; {DB_READ}"
        warnings.append(f"log.md: the line was not added ({exc}). Add it by hand: {line}")
    return line, warnings


def build(root: str | Path, ref: str, preview_id: str, *, today: date | None = None, now: datetime | None = None,
          source: str | None = None) -> DbResult:  # fmt: skip
    """A previewed proposal into master.db (the chain in the module docstring)."""
    _route(root, source)
    folder, found, state, lib, gate = build_structure.checked(root, ref, preview_id, now=now, source=source)
    if state.export != DB_READ:
        raise DbWriteError(SOURCE_XML)
    with _logged_if_written(folder.root, f"build {found.slug}", today):
        with _session() as db:
            written = write_plan(db, state.plan, lib)
    counts = {k: state.counts[k] for k in ("create", "skip", "manual", "tracks")}  # as the preview and the XML count
    if state.plan.vetoed:
        counts["vetoed"] = len(state.plan.vetoed)
    line, warnings = _after(gate, preview_id, now, folder.root, f"build {found.slug}", counts, today)
    try:
        libfolder.update_meta(folder.root, today=today or (now.date() if now else None),
                              structure={"chosen": found.slug})  # fmt: skip
    except (LibraryFolderError, OSError) as exc:
        warnings.append(f"library.yaml: structure.chosen was not set to {found.slug} ({exc}).")
    return DbResult("build", found.slug, counts, written, line, warnings=tuple(found.warnings) + tuple(warnings))


def crate(root: str | Path, ref: str, preview_id: str, *, today: date | None = None, now: datetime | None = None,
          source: str | None = None) -> DbResult:  # fmt: skip
    """A previewed crate into master.db: its Crates folder, the picks, the spares (the chain above)."""
    _route(root, source)
    folder, state, gate = crate_mod.checked(root, ref, preview_id, now=now, source=source)
    if state.export != DB_READ:
        raise DbWriteError(SOURCE_XML)
    plan = plan_lists(crate_mod.playlist_lists(state), state.lib)
    with _logged_if_written(folder.root, f"crate {state.slug}", today):
        with _session() as db:
            written = write_plan(db, plan, state.lib)
    result = state.result
    counts = {"picks": len(result.picks), "spares": len(result.spares)}
    if result.counts.get("vetoed"):
        counts["vetoed"] = result.counts["vetoed"]
    line, warnings = _after(gate, preview_id, now, folder.root, f"crate {state.slug}", counts, today)
    record = ""
    try:
        day = today or (now.date() if now else date.today())
        path = libfolder.write_new_numbered(folder.crates, state.slug, ".md", crate_mod.render_md(state, DB_READ, day))
        record = folder.relative(path)
    except (LibraryFolderError, OSError) as exc:
        warnings.append(f"crates/{state.slug}.md was not written ({exc}). The crate is in rekordbox.")
    return DbResult("crate", state.slug, counts, written, line, record, tuple(warnings))


# -- the CLI ---------------------------------------------------------------------------------------


def run_cli(as_json: bool, call: Callable[[], DbResult]) -> None:
    """`dj library build|crate --apply --power-mode`: one JSON object or the text lines; a refusal is
    one `REFUSED` line (exit 1), rekordbox running one `STOP` line (exit 2), an error one `ERROR` line."""
    try:
        result = call()
    except RekordboxOpen as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING) from None
    except (RolledBack, MaybeWritten) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    except (GateError, DbWriteError) as exc:
        typer.echo(f"REFUSED {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    except (safety.SafetyError, build_structure.BuildError, crate_mod.CrateError, LibraryError, OSError,
            ValueError) as exc:  # fmt: skip
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    data = result.to_dict()
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False) if as_json else "\n".join(result.lines()))
