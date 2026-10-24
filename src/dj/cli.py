"""dj: manage a rekordbox playlist tree from files."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any

import typer

from dj import activity_log, hostenv, intake, library, safety, spotify, write_gate
from dj import analyze as analyze_mod
from dj import build as build_mod
from dj import playlist_copy as copy_mod
from dj import push as push_mod
from dj import tree as tree_mod
from dj.commands.library import library_app
from dj.commands.wishlist import wishlist_app
from dj.gate import GateError
from dj.readers import db as db_reader
from dj.tidy import TidyError
from dj.tidy import checks as tidy_checks
from dj.tidy import config as tidy_config
from dj.tidy import dupes as tidy_dupes
from dj.tidy import plan as tidy_plan
from dj.tidy import report as tidy_report
from dj.tidy import scan as tidy_scan
from dj.tree import KIND_BY_ATTRIBUTE, alive, children_of
from dj.writers import adds_xml

# show_locals stays off: a traceback must never print a token or the client secret.
app = typer.Typer(
    add_completion=False, no_args_is_help=True, help=__doc__, pretty_exceptions_show_locals=False
)
app.add_typer(library_app, name="library")
app.add_typer(wishlist_app, name="wishlist")

EXIT_ERROR = 1
EXIT_REKORDBOX_RUNNING = 2

# The write gate (R-1102, R-205): a write needs the id of the dry-run the DJ said yes to; a
# master.db write also needs --power-mode, on Windows.
_PREVIEW_ID_OPT = typer.Option(
    None, "--preview-id", help="With --apply: the id the dry-run printed, after the DJ said yes to it."
)
_POWER_MODE_OPT = typer.Option(
    False, "--power-mode",
    help="With --apply: write master.db directly (Windows only). The default write path is an XML "
         "you import: dj library build for new folders and playlists, --xml for adds and copies.",
)  # fmt: skip
_XML_OPT = typer.Option(
    False, "--xml",
    help="With --apply: write proposals/<crate>-adds-<date>.xml for the DJ to import (any OS, no "
         "--power-mode, master.db is never opened for writing), instead of writing master.db.",
)  # fmt: skip


def _refused(reason: object) -> None:
    """One line, exit 1: the write was refused before anything was read for it or written."""
    typer.echo(f"REFUSED {reason}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _gate_id(preview_id: str | None) -> None:
    """Before a write reads anything: an id with the shape of a preview id (R-1102)."""
    try:
        write_gate.require_id(preview_id)
    except GateError as exc:
        _refused(exc)


def _gate_db_write(power_mode: bool, preview_id: str | None) -> None:
    """Before a master.db write reads anything: --power-mode and Windows first (R-205), then an
    id with the shape of a preview id (R-1102). Its content is checked once the plan is known."""
    try:
        write_gate.require_power_mode(power_mode)
        write_gate.require_id(preview_id)
    except GateError as exc:
        _refused(exc)


def _gate_adds_write(xml: bool, power_mode: bool, preview_id: str | None) -> None:
    """Before `dj apply` / `dj copy --apply` reads anything: --xml (an XML to import, any OS, no
    write session) or --power-mode (master.db, Windows), never both; then the preview id's shape."""
    if xml and power_mode:
        _refused("--xml and --power-mode are two ways to write: pick one. Nothing written.")
    if xml:
        _gate_id(preview_id)
    else:
        _gate_db_write(power_mode, preview_id)


def _preview_keys(recorded: write_gate.Recorded | None) -> dict[str, Any]:
    """The dry-run's --json key for the gate (additive)."""
    return {"preview_id": recorded.preview_id if recorded else None}


def _db_off_keys() -> dict[str, Any]:
    """A master.db dry-run's --json key when the engine settings refuse master.db writes
    (DJ_POWER_MODE, dj.hostenv; additive, absent otherwise): the preview tool's result then tells
    the DJ that the power-mode route cannot be written."""
    off = hostenv.power_mode_refusal()
    return {"master_db_write": off} if off else {}


def _to_write(preview_id: str, power_mode: bool = False, xml: bool = False) -> str:
    """The dry-run's last line: how the write is called, after the DJ's yes. `xml`: the command
    also writes an XML to import (`dj apply`, `dj copy`), named first. When the engine settings
    refuse master.db writes, the power-mode route is not offered: the line says why instead."""
    flags = "--apply --power-mode" if power_mode else "--apply"
    off = hostenv.power_mode_refusal() if power_mode else None
    if off and xml:
        return (f"DRY-RUN. Nothing written. To write, after the DJ's yes: --apply --xml --preview-id {preview_id} "
                f"(an XML to import, any OS). Not master.db: {off}")
    if off:
        return f"DRY-RUN. Nothing written. This preview cannot be written: {off}"
    if xml:
        return (f"DRY-RUN. Nothing written. To write, after the DJ's yes: --apply --xml --preview-id {preview_id} "
                f"(an XML to import, any OS), or master.db on Windows: {flags} --preview-id {preview_id}")
    return f"DRY-RUN. Nothing written. To write, after the DJ's yes: {flags} --preview-id {preview_id}"


def _used(preview_id: str, written: str) -> None:
    """Mark the preview used after the write; a failure there is a warning, the write is done."""
    warning = write_gate.consume(preview_id, written=written)
    if warning:
        typer.echo(f"WARNING {warning}", err=True)


def _changed_since_preview() -> GateError:
    return GateError("The plan changed since the preview. Nothing written; preview again and show the DJ.")


def _snapshot() -> Any:
    """A read-only pass (R-202, Q-18): the pyrekordbox db of a snapshot copy of master.db, never
    the live file. Every dry-run, match, plan, push and tidy read and the tree print after a write
    read this way; only a write keeps its live session (`safety.open_db(write=True)`), whose
    re-plan inside the session is part of the write. A copy that fails -> db_reader.LibraryError."""
    return db_reader.open_snapshot()


def _log(action: str, counts: dict[str, int], file: str | Path | None = None) -> str | None:
    """R-904: the tool, not Claude, appends the log.md line of a write that is done (one per run
    that wrote something; never for a dry-run or a refusal). Returns the line; a line that could
    not be written is a warning on stderr, the write itself stands."""
    logged = activity_log.log_write(action, counts, file)
    if logged.warning:
        typer.echo(f"WARNING {logged.warning}", err=True)
    return logged.line


def _logged(line: str | None) -> list[str]:
    """The text output's line naming the log.md line that was appended."""
    return [f"log.md: {line}"] if line else []


def _log_interrupted(action: str, exc: Exception) -> None:
    """R-904 for a write stopped by an error after it began writing (push.PushInterrupted,
    tidy plan.Interrupted): one line with what was written by then, named on stderr. The error
    stays the run's failure. Any other error wrote nothing and logs nothing."""
    if isinstance(exc, push_mod.PushInterrupted):
        counts = ({"playlists created": 1} if exc.created else {}) | {"added": exc.added, "not added": exc.left}
        file = None
    elif isinstance(exc, tidy_plan.Interrupted):
        r = exc.result
        done = r.applied if isinstance(r, tidy_plan.ApplyResult) else r.restored
        if not (done or r.failed):
            return
        word = "written" if isinstance(r, tidy_plan.ApplyResult) else "restored"
        counts, file = {word: len(done), "failed": len(r.failed)}, r.undo_path
    else:
        return
    for line in _logged(_log(f"{action}, stopped by an error", counts, file)):
        typer.echo(line, err=True)


def _log_committed(action: str, added: int) -> None:
    """R-904 for a master.db write whose commit is done when the report after it fails."""
    if added:
        for line in _logged(_log(f"{action}, stopped by an error", {"added": added})):
            typer.echo(line, err=True)


_KIND_PLURAL = {"folder": "folders", "playlist": "playlists", "smart": "smart playlists"}
_STATUS_WORD = {intake.IN_CRATE: "in crate", intake.PROPOSE: "proposed", intake.AMBIGUOUS: "ambiguous",
                intake.MISSING: "missing", intake.DECLINED: "declined"}  # fmt: skip


def _tree_log_counts(changes: list[dict[str, Any]], created: int) -> dict[str, int]:
    """`dj tree --apply`'s log counts: the created nodes per kind."""
    by_kind: dict[str, int] = {}
    for change in changes:
        key = _KIND_PLURAL.get(change["kind"], str(change["kind"]))
        by_kind[key] = by_kind.get(key, 0) + 1
    return by_kind if sum(by_kind.values()) == created else {"created": created}


def _tidy_target(target: Any) -> str:
    """A tidy plan's target in a log line, never an absolute path (R-905): the crate path, the
    music folder's own name, or the whole collection."""
    if not isinstance(target, dict):
        return "plan"
    if target.get("kind") == tidy_scan.FOLDER:
        return f"folder {Path(str(target.get('value') or '')).name}".strip()
    if target.get("kind") == tidy_scan.ALL:
        return "the whole collection"
    return str(target.get("value") or target.get("slug") or "plan")


@app.callback()
def main() -> None:
    # Playlist names can hold any character; the Windows console codepage cannot.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def rekordbox_version(db_path: Path) -> str | None:
    """rekordbox stamps its version into masterPlaylists6.xml next to master.db."""
    xml = db_path.parent / safety.PLAYLIST_XML
    if not xml.is_file():
        return None
    match = re.search(r'<PRODUCT[^>]*\bVersion="([^"]+)"', xml.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _entries(node: Any) -> int:
    """A playlist's tracks, without the ones rekordbox removed but has not purged yet."""
    return sum(1 for song in node.Songs if alive(song))


def print_tree(db: Any, smart_xml: bool = False, parent_id: str = "root", depth: int = 0) -> None:
    for node in children_of(db, parent_id):
        kind = KIND_BY_ATTRIBUTE.get(node.Attribute, f"attr={node.Attribute}")
        extra = f"  ({_entries(node)} tracks)" if kind == "playlist" else ""
        typer.echo(f"{'  ' * depth}[{kind}] {node.Name}{extra}")
        if smart_xml and kind == "smart":
            typer.echo(f"{'  ' * (depth + 1)}{node.SmartList}")
        if kind == "folder":
            print_tree(db, smart_xml, node.ID, depth + 1)


def tree_data(db: Any, parent_id: str = "root") -> list[dict[str, Any]]:
    out = []
    for node in children_of(db, parent_id):
        kind = KIND_BY_ATTRIBUTE.get(node.Attribute, f"attr={node.Attribute}")
        entry: dict[str, Any] = {"kind": kind, "name": node.Name}
        if kind == "playlist":
            entry["tracks"] = _entries(node)
        if kind == "smart":
            entry["smart_xml"] = node.SmartList
        if kind == "folder":
            entry["children"] = tree_data(db, node.ID)
        out.append(entry)
    return out


def links_data(db: Any, paths: intake.Paths) -> list[dict[str, Any]]:
    """Per link: counts by status from the last pull, and the sync dates. Offline."""
    try:
        links = intake.load_links(paths)
    except intake.IntakeError:
        return []
    out = []
    for link in links:
        entry: dict[str, Any] = {"spotify": link.spotify, "crate": link.crate}
        try:
            entry["counts"] = intake.counts(intake.match_link(link, db, paths))
            entry["last_pull"] = intake.load_inbox(link, paths).get("pulled_at")
        except (intake.IntakeError, library.LibraryError) as exc:
            entry["note"] = str(exc)
        entry["last_apply"] = intake.last_report(link, paths)
        out.append(entry)
    return out


def _running_or_none() -> bool | None:
    """The process check for a read: None where this OS cannot answer (R-201: a read works
    with rekordbox open and never depends on the check)."""
    try:
        return safety.rekordbox_running()
    except safety.SafetyError:
        return None


@app.command()
def status(
    smart_xml: bool = typer.Option(
        False, "--smart-xml", help="Print the raw rule XML of existing smart playlists."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Read-only: track count, playlist tree, rekordbox version, state of every link.
    Reads a snapshot copy of master.db (R-202), so it works while rekordbox runs (R-201)."""
    db_path = safety.find_master_db()
    data: dict[str, Any] = {
        "master_db": str(db_path),  # the live file, named only; SQLite opens the copy
        "rekordbox": rekordbox_version(db_path),
        "pyrekordbox": version("pyrekordbox"),
        "running": _running_or_none(),
    }
    paths = intake.default_paths()
    data["links_file"] = str(paths.links)  # the library folder's links.yaml, else the repo's
    # repo state/ files still read in place of the library's own, until the next apply
    data["state_from_repo"] = paths.carried_state()
    try:
        with db_reader.open_snapshot(db_path) as db:
            data["tracks"] = len(library.all_tracks(db))  # soft-deleted rows left out
            data["links"] = links_data(db, paths)
            if as_json:
                data["tree"] = tree_data(db)
                typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
                return
            typer.echo(f"master.db:     {data['master_db']}")
            typer.echo(f"rekordbox:     {data['rekordbox'] or 'unknown'}")
            typer.echo(f"pyrekordbox:   {data['pyrekordbox']}")
            running = {True: "YES", False: "no", None: "unknown (the process check could not answer)"}[data["running"]]
            typer.echo(f"running:       {running}")
            typer.echo(f"tracks:        {data['tracks']}")
            typer.echo("")
            typer.echo("playlist tree:")
            print_tree(db, smart_xml=smart_xml)
    except db_reader.LibraryError as exc:  # the snapshot copy failed or kept changing
        _fail(exc)
    typer.echo("")
    if data["state_from_repo"]:  # library folder only: the repo's declined list and match memory
        typer.echo(f"state:         {', '.join(data['state_from_repo'])} read from the repo's state/ "
                   "until the next `dj apply --apply` copies them into the library folder")
    typer.echo("links:" if data["links"] else "links:         none (links.yaml)")
    for link in data["links"]:
        typer.echo(f"  {link['spotify']} -> {link['crate']}")
        if "counts" in link:
            typer.echo("    " + ", ".join(f"{n} {s}" for s, n in link["counts"].items()))
        if "note" in link:
            typer.echo(f"    {link['note']}")
        typer.echo(f"    last pull {link.get('last_pull') or 'never'}, "
                   f"last apply {link.get('last_apply') or 'never'}")


def _tree_changes(actions: list[tree_mod.Action]) -> list[dict[str, Any]]:
    """What `dj tree --apply` would do: the CREATE actions, in order."""
    return [{"kind": a.kind, "path": list(a.path), "rules": a.rules} for a in actions if a.op == tree_mod.CREATE]


def _print_plan(actions: list[tree_mod.Action]) -> dict[str, int]:
    for action in actions:
        typer.echo(action.line())
    totals = tree_mod.counts(actions)
    typer.echo("")
    typer.echo(", ".join(f"{n} {op}" for op, n in totals.items()))
    return totals


def _config_arg(path: Path) -> Path:
    """A tree file given by a relative name ("bases.yaml", "tree.yaml"): the dj-library folder's
    when it has that file, else the name as given (from the working folder, as before; the MCP
    server runs the CLI in the repo). In the desktop extension the dj-library folder's only (no
    library folder: HostSettingError). An absolute path is taken as it is (W-34)."""
    if path.is_absolute():
        return path
    return hostenv.config_file(path, fallback=path)


@app.command()
def tree(
    apply: bool = typer.Option(False, "--apply", help="Really write. Default is a dry-run."),
    file: Path = typer.Option(Path("tree.yaml"), "--file", help="The tree file (a bare name: the dj-library folder's first)."),
    allow_uncalibrated: bool = typer.Option(
        False,
        "--allow-uncalibrated",
        help="Also create smart playlists whose rule encoding is unconfirmed (default: HOLD).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    preview_id: str = _PREVIEW_ID_OPT,
    power_mode: bool = _POWER_MODE_OPT,
) -> None:
    """Create what is missing from tree.yaml. Never changes what exists.

    The dry-run prints a preview id; --apply needs --power-mode and that id (R-205, R-1102)."""
    if apply and as_json:
        typer.echo("ERROR --json is for the dry-run; apply without it.", err=True)
        raise typer.Exit(EXIT_ERROR)
    if apply:
        _gate_db_write(power_mode, preview_id)
    try:
        file = _config_arg(file)
        nodes = tree_mod.load_tree(file)
    except (tree_mod.TreeError, OSError, hostenv.HostSettingError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)
    gate_args = {"file": write_gate.path_arg(file), "allow_uncalibrated": allow_uncalibrated}

    # Pass 1, read-only: the plan.
    def plan(db: Any) -> list[tree_mod.Action]:
        actions = tree_mod.walk(nodes, db)
        return actions if allow_uncalibrated else tree_mod.hold_uncalibrated(actions)

    try:
        with _snapshot() as db:  # R-202: a snapshot copy, never the live file
            actions = plan(db)
    except db_reader.LibraryError as exc:
        _fail(exc)
    changes = _tree_changes(actions)
    blocked = any(a.op == tree_mod.CONFLICT for a in actions)  # a CONFLICT plan gets no preview id
    if as_json:
        recorded = None if blocked else write_gate.record("tree", gate_args, changes)
        rows = [{"op": a.op, "kind": a.kind, "path": list(a.path), "note": a.note} for a in actions]
        data = {"counts": tree_mod.counts(actions), "actions": rows} | _preview_keys(recorded) | _db_off_keys()
        typer.echo(json.dumps(data, indent=2))
        return
    if apply and not blocked:  # a refused write is one REFUSED line, without the plan before it
        try:
            write_gate.check(preview_id, "tree", gate_args, changes)
        except GateError as exc:
            _refused(exc)
    totals = _print_plan(actions)
    if totals[tree_mod.HOLD]:
        typer.echo("HOLD = not created until its encoding is confirmed (see README).")

    if totals[tree_mod.CONFLICT]:
        typer.echo("CONFLICT found. Nothing written.", err=True)
        raise typer.Exit(EXIT_ERROR)
    if not apply:
        recorded = write_gate.record("tree", gate_args, changes)
        for line in recorded.lines():
            typer.echo(line)
        typer.echo(_to_write(recorded.preview_id, power_mode=True))
        return
    if not totals[tree_mod.CREATE]:
        typer.echo("Nothing to create. Nothing written.")
        return

    # Pass 2, the write: re-plan inside the write session; it must still be the previewed plan.
    try:
        with safety.open_db(write=True) as db:
            now = plan(db)
            if write_gate.digest(_tree_changes(now)) != write_gate.digest(changes):
                raise _changed_since_preview()
            created = tree_mod.apply(now, db)
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    except GateError as exc:
        _refused(exc)
    except safety.SafetyError as exc:  # e.g. not Windows (DB_WRITE_PLATFORMS): one line, nothing written
        _fail(exc)
    _used(preview_id, f"{created} node(s) in master.db")
    typer.echo(f"APPLIED. Created {created} node(s) in one commit. Backup in {safety.backup_folder_text()}.")
    if created:
        for line in _logged(_log("tree", _tree_log_counts(changes, created), file)):
            typer.echo(line)

    typer.echo("")
    try:
        with _snapshot() as db:  # the write is committed: read it back from a fresh snapshot
            typer.echo("final tree:")
            print_tree(db)
    except db_reader.LibraryError as exc:  # the write stands; only the print is missing
        typer.echo(f"WARNING final tree not printed ({exc}). dj status shows it.", err=True)


@app.command()
def push(
    playlist: str = typer.Argument(..., help="rekordbox playlist, e.g. 'funk_base/funk_crate'."),
    name: str = typer.Option(None, "--name", help="Spotify playlist name. Default: same name."),
    apply: bool = typer.Option(False, "--apply", help="Really write to Spotify. Default: dry-run."),
    include_ambiguous: bool = typer.Option(
        False, "--include-ambiguous", help="Also add the best pick of AMBIGUOUS tracks."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    preview_id: str = _PREVIEW_ID_OPT,
) -> None:
    """Copy a rekordbox playlist to a private Spotify playlist. Adds only, never removes.

    The dry-run prints a preview id; --apply needs it (R-1102). An unknown, used, expired or other
    preview id is refused before any token request; matching uses read scopes only; the write
    scope is asked for after the plan matched the preview."""
    if apply:
        _gate_id(preview_id)
    try:
        with _snapshot() as db:
            row = push_mod.find_playlist(db, playlist)
            rb_id, rb_name = str(row.ID), row.Name
            tracks = push_mod.local_tracks(row)
        spotify_name = name or rb_name
        gate_args = {"playlist": playlist, "name": spotify_name, "include_ambiguous": include_ambiguous}
        if apply:
            write_gate.precheck(preview_id, "push", gate_args)  # before any token or Spotify call
        api = spotify.Spotify(spotify.get_token(spotify.READ_SCOPES))
        results = [push_mod.match_track(api, t) for t in tracks]
        uris = push_mod.selected_uris(results, include_ambiguous)
        totals = {s: sum(r.status == s for r in results) for s in ("MATCH", "AMBIGUOUS", "MISSING")}
        changes = {"rekordbox_playlist_id": rb_id, "name": spotify_name, "uris": uris}
        payload: dict[str, Any] = {
            "rekordbox_playlist": playlist,
            "spotify_name": spotify_name,
            "applied": False,
            "counts": totals,
            "selected": len(uris),
            "items": [push_mod.result_dict(r) for r in results],
        }
        recorded = None
        if not apply:
            recorded = write_gate.record("push", gate_args, changes)
            payload |= _preview_keys(recorded)
        else:
            write_gate.check(preview_id, "push", gate_args, changes)  # before the write token
            if uris:
                writer = spotify.Spotify(spotify.get_token(spotify.WRITE_SCOPES))
                payload["result"] = push_mod.apply(writer, rb_id, spotify_name, uris)
                payload["applied"] = True
                _used(preview_id, f"Spotify playlist {spotify_name}")
                payload["report"] = str(push_mod.write_report(spotify_name, payload))
                res = payload["result"]
                payload["log"] = _log(f"push {playlist} to Spotify", {
                    "added": res["added"], "already there": res["already_there"], "missing": totals["MISSING"],
                }, payload["report"])  # fmt: skip
    except GateError as exc:
        _refused(exc)
    except (push_mod.PushError, spotify.SpotifyError, db_reader.LibraryError) as exc:
        _log_interrupted(f"push {playlist} to Spotify", exc)
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)

    if as_json:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    for r in results:
        typer.echo(push_mod.result_line(r))
    typer.echo("")
    typer.echo(", ".join(f"{n} {s}" for s, n in totals.items()) + f"  ({len(tracks)} tracks)")
    if payload["applied"]:
        res = payload["result"]
        verb = "Created" if res["created"] else "Updated"
        typer.echo(f"APPLIED. {verb} '{res['playlist']['name']}': added {res['added']}, "
                   f"already there {res['already_there']}.")
        typer.echo(res["playlist"]["url"])
        typer.echo(f"report: {payload['report']}")
        for line in _logged(payload.get("log")):
            typer.echo(line)
    elif apply:
        typer.echo("Nothing to add. Nothing written.")
    else:
        for line in recorded.lines():
            typer.echo(line)
        typer.echo(f"DRY-RUN. Would put {len(uris)} track(s) on Spotify. Nothing written. To write, "
                   f"after the DJ's yes: --apply --preview-id {recorded.preview_id}")


@app.command()
def build(
    tracklist: Path = typer.Argument(..., help="Text file, one 'Artist - Title (Mix)' per line."),
    name: str = typer.Option(None, "--name", help="Spotify playlist name. Default: the file name."),
    apply: bool = typer.Option(False, "--apply", help="Really write to Spotify. Default: dry-run."),
    include_ambiguous: bool = typer.Option(
        False, "--include-ambiguous", help="Also add the best pick of AMBIGUOUS tracks."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    preview_id: str = _PREVIEW_ID_OPT,
) -> None:
    """A text tracklist -> a private Spotify playlist. rekordbox untouched. Adds only.

    The dry-run prints a preview id; --apply needs it (R-1102). An unknown, used, expired or other
    preview id is refused before any token request; matching uses read scopes only; the write
    scope is asked for after the plan matched the preview."""
    if apply:
        _gate_id(preview_id)
    try:
        tracks, skipped = build_mod.load_tracklist(tracklist)
        name = name or build_mod.default_name(tracklist)
        gate_args = {"tracklist": write_gate.path_arg(tracklist), "name": name,
                     "include_ambiguous": include_ambiguous}  # fmt: skip
        if apply:
            write_gate.precheck(preview_id, "build", gate_args)  # before any token or Spotify call
        api = spotify.Spotify(spotify.get_token(spotify.READ_SCOPES))
        results = build_mod.match_all(api, tracks)
        uris = push_mod.selected_uris(results, include_ambiguous)
        totals = {s: sum(r.status == s for r in results) for s in ("MATCH", "AMBIGUOUS", "MISSING")}
        changes = {"name": name, "uris": uris}
        payload: dict[str, Any] = {
            "tracklist": str(tracklist),
            "spotify_name": name,
            "applied": False,
            "counts": totals,
            "selected": len(uris),
            "skipped_lines": skipped,
            "items": [push_mod.result_dict(r) for r in results],
        }
        recorded = None
        if not apply:
            recorded = write_gate.record("build", gate_args, changes)
            payload |= _preview_keys(recorded)
        else:
            write_gate.check(preview_id, "build", gate_args, changes)  # before the write token
            if uris:
                writer = spotify.Spotify(spotify.get_token(spotify.WRITE_SCOPES))
                payload["result"] = build_mod.apply(writer, name, uris)
                payload["applied"] = True
                _used(preview_id, f"Spotify playlist {name}")
                payload["report"] = str(push_mod.write_report(name, payload, kind="build"))
                res = payload["result"]
                payload["log"] = _log(f"build Spotify playlist {name}", {
                    "added": res["added"], "already there": res["already_there"], "missing": totals["MISSING"],
                }, payload["report"])  # fmt: skip
    except GateError as exc:
        _refused(exc)
    except (build_mod.BuildError, push_mod.PushError, spotify.SpotifyError) as exc:
        _log_interrupted(f"build Spotify playlist {name}", exc)
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)

    if as_json:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    for r in results:
        typer.echo(push_mod.result_line(r))
    typer.echo("")
    typer.echo(", ".join(f"{n} {s}" for s, n in totals.items()) + f"  ({len(tracks)} lines)")
    for line in skipped:
        typer.echo(f"skipped line (no ' - '): {line}")
    if payload["applied"]:
        res = payload["result"]
        verb = "Created" if res["created"] else "Updated"
        typer.echo(f"APPLIED. {verb} '{res['playlist']['name']}': added {res['added']}, "
                   f"already there {res['already_there']}.")
        typer.echo(res["playlist"]["url"])
        typer.echo(f"report: {payload['report']}")
        for line in _logged(payload.get("log")):
            typer.echo(line)
    elif apply:
        typer.echo("Nothing to add. Nothing written.")
    else:
        for line in recorded.lines():
            typer.echo(line)
        typer.echo(f"DRY-RUN. Would put {len(uris)} track(s) on Spotify. Nothing written. To write, "
                   f"after the DJ's yes: --apply --preview-id {recorded.preview_id}")


# -- Phase 2: Spotify inbox -> rekordbox crate -------------------------------------------


def _fail(exc: Exception) -> None:
    typer.echo(f"ERROR {exc}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _out(as_json: bool, payload: dict[str, Any], lines: list[str]) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False) if as_json else "\n".join(lines))


INTAKE_ERRORS = (intake.IntakeError, library.LibraryError, spotify.SpotifyError, db_reader.LibraryError)


@app.command()
def pull(
    link: str = typer.Argument(None, help="A link from links.yaml (its spotify or crate value)."),
    all_links: bool = typer.Option(False, "--all", help="Pull every link."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Spotify playlist -> inbox/<crate>.json. Read-only on both sides."""
    paths = intake.default_paths()
    try:
        if bool(link) == all_links:
            raise intake.IntakeError("Give one <link>, or --all.")
        links = intake.load_links(paths) if all_links else [intake.resolve_link(link, paths)]
        api = spotify.Spotify(spotify.get_token(spotify.READ_SCOPES))
        pulled = [intake.pull(api, l, paths) for l in links]
    except INTAKE_ERRORS as exc:
        _fail(exc)
    _out(as_json, {"pulled": pulled},
         [f"{p['tracks']} tracks  {p['link']} -> {p['inbox']}" for p in pulled])


def _match(link_arg: str) -> tuple[intake.Link, list[intake.Item], set[str]]:
    paths = intake.default_paths()
    link = intake.resolve_link(link_arg, paths)
    with _snapshot() as db:
        items = intake.match_link(link, db, paths)
        in_crate = library.crate_content_ids(library.find_playlist(db, link.crate))
    return link, items, in_crate


def _ambiguous_lines(items: list[intake.Item], in_crate: set[str]) -> list[str]:
    lines = []
    for item in items:
        if item.status != intake.AMBIGUOUS:
            continue
        s = round(item.spotify.duration_ms / 1000)
        lines.append(f"AMBIGUOUS  {item.spotify.label}  ({s // 60}:{s % 60:02d})  "
                     f"[{'; '.join(item.reasons)}]")
        for local, sc in item.top:
            mark = " (in crate)" if local.content_id in in_crate else ""
            d = local.duration_s
            lines.append(f"    {local.content_id}: {local.title} - {local.artist} - "
                         f"{d // 60}:{d % 60:02d} - {local.bitrate}kbps - "
                         f"...{local.path[-50:]}{mark}  [score {sc.score}]")
    return lines


@app.command()
def match(
    link: str = typer.Argument(..., help="A link from links.yaml."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Counts per status and the ambiguous list, from the last pull. Writes nothing."""
    try:
        lnk, items, in_crate = _match(link)
    except INTAKE_ERRORS as exc:
        _fail(exc)
    totals = intake.counts(items)
    payload = {"spotify": lnk.spotify, "crate": lnk.crate, "counts": totals,
               "items": [intake.item_dict(i, in_crate) for i in items]}
    lines = [f"{n:>4}  {s}" for s, n in totals.items()] + [""] + _ambiguous_lines(items, in_crate)
    _out(as_json, payload, lines)


@app.command()
def plan(
    link: str = typer.Argument(..., help="A link from links.yaml."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Write plans/<date>-<crate>.plan.json and wishlist/<crate>.md. rekordbox untouched."""
    paths = intake.default_paths()
    try:
        lnk, items, in_crate = _match(link)
        plan_path = intake.write_plan(lnk, items, in_crate, paths)
        wish_path = intake.write_wishlist(lnk, items, paths)
    except INTAKE_ERRORS as exc:
        _fail(exc)
    totals = intake.counts(items)
    line = _log(f"plan {lnk.crate}", {_STATUS_WORD.get(s, s.lower()): n for s, n in totals.items()}, plan_path)
    payload = {"plan": str(plan_path), "wishlist": str(wish_path), "counts": totals, "log": line}
    _out(as_json, payload, [f"plan:     {plan_path}", f"wishlist: {wish_path}",
                            "Set decision (yes/no) and, for AMBIGUOUS, pick. Then: dj apply <plan>", *_logged(line)])


@app.command(name="apply")
def apply_plan(
    plan_file: Path = typer.Argument(..., help="A plan file from `dj plan`."),
    apply: bool = typer.Option(False, "--apply", help="Really write. Default is a dry-run."),
    xml: bool = _XML_OPT,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    preview_id: str = _PREVIEW_ID_OPT,
    power_mode: bool = _POWER_MODE_OPT,
) -> None:
    """Add the `decision: yes` tracks of a plan to its crate. Appends only.

    The dry-run reads a snapshot of master.db and prints a preview id. --apply needs that id and
    one way to write: --xml (an XML the DJ imports, then one drag into the crate; any OS, master.db
    never opened for writing) or --power-mode (master.db, Windows) (R-205, R-802, R-1102)."""
    if apply:
        _gate_adds_write(xml, power_mode, preview_id)
    paths = intake.default_paths()
    try:
        plan_data = intake.load_plan(plan_file)
        by = intake.decisions(plan_data)
        with _snapshot() as db:  # R-202; for --xml also the fresh read the gate checks
            crate = library.find_playlist(db, plan_data["crate"])
            adds = intake.to_add(plan_data, library.crate_content_ids(crate))
            # the local file each add puts in the crate, as the library holds it (not the plan's copy)
            local = {t.content_id: t.label for t in library.all_tracks(db)} if adds else {}
            found = db_reader.tracks_by_id(db, [str(i["pick"]) for i in adds]) if apply and xml else {}
        gate_args = {"plan": write_gate.path_arg(plan_file)}
        changes = _apply_changes(plan_data, adds)
        payload: dict[str, Any] = {
            "crate": plan_data["crate"], "applied": False, "would_add": len(adds),
            "yes": len(by["yes"]), "no": len(by["no"]), "pending": len(by["pending"]),
            "adds": [{"spotify": i["spotify"], "rb_content_id": str(i["pick"]),
                      "local": local.get(str(i["pick"]))} for i in adds],  # fmt: skip
        }
        lines = [f"ADD  {i['spotify']}  -> {i['pick']} {local.get(str(i['pick'])) or '(not in the library)'}"
                 for i in adds]
        lines.append(f"{len(adds)} to add, {len(by['yes']) - len(adds)} yes already in crate, "
                     f"{len(by['no'])} no, {len(by['pending'])} pending")
        if not apply:
            recorded = write_gate.record("apply", gate_args, changes)
            payload |= _preview_keys(recorded) | _db_off_keys()
            lines += recorded.lines() + [_to_write(recorded.preview_id, power_mode=True, xml=True)]
        elif xml:
            write_gate.check(preview_id, "apply", gate_args, changes)  # before the XML is written
            done, more = _apply_as_xml(plan_data, plan_file, adds, found, paths, preview_id)
            payload |= done
            lines += more
        else:
            write_gate.check(preview_id, "apply", gate_args, changes)  # before any backup
            added: list[dict[str, Any]] = []
            if adds:  # no backup, no write session when there is nothing to add
                with safety.open_db(write=True) as db:
                    crate_now = library.find_playlist(db, plan_data["crate"])
                    now = intake.to_add(plan_data, library.crate_content_ids(crate_now))
                    if write_gate.digest(_apply_changes(plan_data, now)) != write_gate.digest(changes):
                        raise _changed_since_preview()
                    added = intake.add_to_crate(db, plan_data)
                _used(preview_id, f"{len(added)} track(s) to {plan_data['crate']}")
            try:
                report = intake.record(plan_data, plan_file, added, paths)
            except Exception:  # master.db is committed: log what it holds, the error stays the failure
                _log_committed(f"apply {plan_data['crate']}", len(added))
                raise
            line = _log(f"apply {plan_data['crate']}", {"added": len(added), "no": len(by["no"]),
                                                        "pending": len(by["pending"])}, report)  # fmt: skip
            payload |= {"applied": True, "added": len(added), "report": str(report), "log": line}
            lines.append(f"APPLIED. Added {len(added)} track(s) to '{plan_data['crate']}'.")
            lines.append(f"report: {report}")
            lines += _logged(line)
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    except GateError as exc:
        _refused(exc)
    except (*INTAKE_ERRORS, safety.SafetyError, adds_xml.BuildError) as exc:
        _fail(exc)
    _out(as_json, payload, lines)


def _adds_device(paths: intake.Paths) -> str:
    """The import card's OS: the dj-library folder's device when the inbox loop runs there."""
    return adds_xml.device_for(paths.root if paths.library else None)


def _xml_lines(written: adds_xml.AddsXml) -> list[str]:
    """What an --xml write prints: the file, then the import card (R-502) ending in the one drag."""
    lines = [f"WROTE {written.file}: {len(written.track_ids)} track(s) in the playlist "
             f"'{written.playlist}'. master.db untouched."]
    if written.unplaced:
        lines.append(f"{len(written.unplaced)} track(s) have no file location in rekordbox: left out of the XML.")
    lines += [f"{n}. {step}" for n, step in enumerate(written.import_steps, 1)]
    return lines


def _apply_as_xml(
    plan_data: dict[str, Any], plan_file: Path, adds: list[dict[str, Any]], found: dict[str, Any],
    paths: intake.Paths, preview_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """`dj apply --apply --xml`, after the gate: proposals/<crate>-adds-<date>.xml (create-only),
    then the decisions and the report (as a master.db apply records them), then one log.md line.
    No write session, no backup, no process check: master.db is only read, from a snapshot."""
    crate = plan_data["crate"]
    by = intake.decisions(plan_data)
    for item in adds:  # every pick checked before the file is written, as add_to_crate does
        if str(item["pick"]) not in found:
            raise intake.IntakeError(f"pick {item['pick']} is not in the library: {item['spotify']}")
    written = None
    if adds:
        written = adds_xml.write(
            paths.root, slug=intake.slug(crate), crate=crate, tracks=[found[str(i["pick"])] for i in adds],
            day=date.today(), device=_adds_device(paths), library=paths.library,
        )  # fmt: skip
        _used(preview_id, written.file)
    placed = set(written.track_ids) if written else set()
    in_xml = [i for i in adds if str(i["pick"]) in placed]
    left_out = [i for i in adds if str(i["pick"]) not in placed]  # no file location in rekordbox
    try:
        report = intake.record(plan_data, plan_file, [], paths, in_xml=in_xml, left_out=left_out,
                               xml=written.file if written else None)  # fmt: skip
    except Exception:  # the XML is written: log it, the error stays the failure
        if written:
            for line in _logged(_log(f"apply {crate} as XML, stopped by an error", {"in XML": len(in_xml)},
                                     written.path)):  # fmt: skip
                typer.echo(line, err=True)
        raise
    line = _log(f"apply {crate} as XML", {"in XML": len(in_xml), "no": len(by["no"]), "pending": len(by["pending"])},
                written.path if written else report)  # fmt: skip
    data: dict[str, Any] = {"applied": True, "mode": "xml", "added": 0, "in_xml": len(in_xml), "xml": None,
                            "report": str(report), "log": line}  # fmt: skip
    lines = _xml_lines(written) if written else ["Nothing to add. No XML written."]
    if written:
        data |= written.to_dict()
    lines.append(f"report: {report}")
    lines += _logged(line)
    return data, lines


def _apply_changes(plan_data: dict[str, Any], adds: list[dict[str, Any]]) -> dict[str, Any]:
    """What `dj apply --apply` would do: the adds to the crate, and the decisions it records
    (yes picks into the match cache, no into declined)."""
    by = intake.decisions(plan_data)
    return {
        "crate": plan_data["crate"],
        "add": [[i.get("spotify_uri"), str(i["pick"])] for i in adds],
        "yes": [[i.get("spotify_uri"), str(i.get("pick"))] for i in by["yes"]],
        "no": [i.get("spotify_uri") for i in by["no"]],
    }


# -- rekordbox playlist -> rekordbox playlist --------------------------------------------


@app.command(name="copy")
def copy_playlist(
    source: str = typer.Argument(..., help="rekordbox playlist to read, e.g. 'warm_up_ideas'."),
    target: str = typer.Argument(..., help="Playlist to append to, e.g. 'house_base/1.1_warm_up'."),
    apply: bool = typer.Option(False, "--apply", help="Really write. Default is a dry-run."),
    xml: bool = _XML_OPT,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    preview_id: str = _PREVIEW_ID_OPT,
    power_mode: bool = _POWER_MODE_OPT,
) -> None:
    """Append the tracks of one rekordbox playlist to another. Adds only, never removes.

    The dry-run reads a snapshot of master.db and prints a preview id. --apply needs that id and
    one way to write: --xml (an XML the DJ imports, then one drag into the target; any OS, master.db
    never opened for writing) or --power-mode (master.db, Windows) (R-205, R-802, R-1102)."""
    if apply:
        _gate_adds_write(xml, power_mode, preview_id)
    try:
        with _snapshot() as db:  # R-202; for --xml also the fresh read the gate checks
            planned = copy_mod.plan(db, source, target, allow_missing_target=not apply)
            found = db_reader.tracks_by_id(db, [r.content_id for r in planned.adds]) if apply and xml else {}
        gate_args = {"source": source, "target": target}
        changes = _copy_changes(planned)
        payload: dict[str, Any] = planned.as_dict() | {"applied": False}
        totals = planned.counts()
        lines = [r.line() for r in planned.rows]
        lines += ["", f"{totals[copy_mod.ADD]} to add, {totals[copy_mod.SKIP]} skipped  "
                      f"({source} -> {target})"]
        if not planned.target_exists:
            lines.append(f"Target '{target}' does not exist yet. Create it first (dj tree).")
        if not apply:
            recorded = write_gate.record("copy", gate_args, changes)
            payload |= _preview_keys(recorded) | _db_off_keys()
            lines += recorded.lines() + [_to_write(recorded.preview_id, power_mode=True, xml=True)]
        elif xml:
            write_gate.check(preview_id, "copy", gate_args, changes)  # before the XML is written
            if not planned.adds:
                lines.append("Nothing to add. Nothing written.")
            else:
                done, more = _copy_as_xml(planned, found, preview_id)
                payload |= done
                lines += more
        else:
            write_gate.check(preview_id, "copy", gate_args, changes)  # before any backup
            if not planned.adds:  # no backup, no write session when there is nothing to add
                lines.append("Nothing to add. Nothing written.")
            else:
                with safety.open_db(write=True) as db:
                    now = _copy_changes(copy_mod.plan(db, source, target))
                    if write_gate.digest(now) != write_gate.digest(changes):
                        raise _changed_since_preview()
                    done = copy_mod.apply(db, source, target)
                _used(preview_id, f"{len(done.adds)} track(s) to {target}")
                try:
                    report = copy_mod.write_report(done)
                except Exception:  # master.db is committed: log what it holds, the error stays the failure
                    _log_committed(f"copy {source} to {target}", len(done.adds))
                    raise
                line = _log(f"copy {source} to {target}", {"added": len(done.adds),
                                                           "skipped": done.counts()[copy_mod.SKIP]}, report)  # fmt: skip
                payload = done.as_dict() | {"applied": True, "added": len(done.adds),
                                            "report": str(report), "log": line}
                lines.append(f"APPLIED. Added {len(done.adds)} track(s) to '{target}'. "
                             f"Backup in {safety.backup_folder_text()}.")
                lines.append(f"report: {report}")
                lines += _logged(line)
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    except GateError as exc:
        _refused(exc)
    except (copy_mod.CopyError, library.LibraryError, safety.SafetyError, db_reader.LibraryError,
            adds_xml.BuildError) as exc:  # fmt: skip
        _fail(exc)
    _out(as_json, payload, lines)


def _copy_as_xml(planned: copy_mod.Plan, found: dict[str, Any], preview_id: str) -> tuple[dict[str, Any], list[str]]:
    """`dj copy --apply --xml`, after the gate: proposals/<target>-adds-<date>.xml (create-only)
    with the tracks to add in source order, the report, one log.md line. No write session."""
    missing = [r.content_id for r in planned.adds if r.content_id not in found]
    if missing:  # checked before the file is written
        raise copy_mod.CopyError(f"track {missing[0]} is not in the library any more. Preview again.")
    paths = intake.default_paths()
    written = adds_xml.write(
        paths.root, slug=intake.slug(planned.target), crate=planned.target,
        tracks=[found[r.content_id] for r in planned.adds], day=date.today(), device=_adds_device(paths),
        library=paths.library,
    )  # fmt: skip
    _used(preview_id, written.file)
    action = f"copy {planned.source} to {planned.target} as XML"
    try:
        report = copy_mod.write_report(planned, extra={"mode": "xml", "xml": written.file,
                                                       "in_xml": list(written.track_ids)})  # fmt: skip
    except Exception:  # the XML is written: log it, the error stays the failure
        for line in _logged(_log(f"{action}, stopped by an error", {"in XML": len(written.track_ids)}, written.path)):
            typer.echo(line, err=True)
        raise
    line = _log(action, {"in XML": len(written.track_ids), "skipped": planned.counts()[copy_mod.SKIP]}, written.path)
    data = {"applied": True, "mode": "xml", "added": 0, "report": str(report), "log": line} | written.to_dict()
    return data, _xml_lines(written) + [f"report: {report}", *_logged(line)]


def _copy_changes(planned: copy_mod.Plan) -> dict[str, Any]:
    """What `dj copy --apply` would do: the tracks it appends to the target, in order."""
    return {"source": planned.source, "target": planned.target, "add": [r.content_id for r in planned.adds]}


# -- Spotify library census ---------------------------------------------------------------


@app.command()
def analyze(
    cached: bool = typer.Option(False, "--cached", help="Skip the pull, rebuild reports from .cache/library/."),
    owner: list[str] = typer.Option([], "--owner", help="Keep only playlists by this owner id or name; 'me' = you. Repeatable."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Read the whole Spotify library into .cache/library/ and write reports/library/*.md.

    Read-only on Spotify (three extra read scopes). rekordbox is never touched.
    """
    payload: dict[str, Any] = {}
    lines: list[str] = []
    try:
        if not cached:
            api = spotify.Spotify(spotify.get_token(spotify.LIBRARY_SCOPES))
            pulled = analyze_mod.pull(api, progress=lambda m: typer.echo(m, err=True))
            payload["pulled"] = pulled
            lines += [f"pulled: {pulled['playlists']} playlists ({pulled['playlist_rows']} rows), "
                      f"{pulled['liked']} liked, {pulled['albums']} albums, "
                      f"{pulled['followed']} followed, {pulled['artists']} artists"]
        lib = analyze_mod.load(owners=owner)
        written = analyze_mod.write_reports(lib)
    except (analyze_mod.AnalyzeError, spotify.SpotifyError) as exc:
        _fail(exc)
    payload |= {"tracks": len(lib.tracks), "playlists": len(lib.playlists),
                "excluded": len(lib.excluded), "reports": [str(w) for w in written]}
    lines += [f"{len(lib.playlists)} playlists ({len(lib.excluded)} excluded by --owner), "
              f"{len(lib.tracks)} unique tracks"] + [f"wrote {w}" for w in written]
    _out(as_json, payload, lines)


# -- dj tidy: library hygiene for the audio files ----------------------------------------------

tidy_app = typer.Typer(
    add_completion=False, no_args_is_help=True, pretty_exceptions_show_locals=False,
    help="Library hygiene: audit the audio files, plan tag fixes from file names, apply, undo. "
         "Reads a snapshot copy of master.db, never writes it. Afterwards: Reload Tag in rekordbox.",
)
app.add_typer(tidy_app, name="tidy")
TIDY_ERRORS = (TidyError, library.LibraryError, db_reader.LibraryError)

_CRATE_ARG = typer.Argument(None, help="rekordbox playlist path, e.g. house_base/0_INBOX.")
_FOLDER_OPT = typer.Option(None, "--folder", help="A folder on disk (inside tidy.yaml roots) instead of a crate.")
_ALL_OPT = typer.Option(False, "--all", help="The whole rekordbox collection.")
# The default tidy.yaml; empty in the desktop extension without a library folder (load_config says so).
_CONFIG_OPT = typer.Option(str(tidy_config.DEFAULT_PATH or ""), "--config", help="tidy.yaml to use.")
_HASH_OPT = typer.Option("collisions", "--hash", help="Hash files for exact duplicates: collisions (same size only), all, none.")


def _tail(text: str, n: int = 60) -> str:
    return text if len(text) <= n else "..." + text[-n:]


def _tidy_scan(crate: str | None, folder: str | None, all_tracks: bool, config: str, hash_mode: str) -> tuple:
    cfg = tidy_config.load_config(config)
    target = tidy_scan.resolve_target(crate, folder, all_tracks, cfg)
    with _snapshot() as db:
        items, meta, known = tidy_scan.items_for(target, db, cfg, hash_mode)
    return cfg, target, items, meta, known


def _dupe_groups(items: list, cfg: Any) -> list:
    exact = tidy_dupes.exact_groups(items)
    return exact + tidy_dupes.fuzzy_groups(items, cfg.duplicate_duration_tolerance_s, skip=exact)


def _dupe_lines(groups: list) -> list[str]:
    lines = []
    for i, g in enumerate(groups, 1):
        keep = g.keeper.file.path.name if g.keeper else "-"
        lines.append(f"DUPE {i} ({g.kind})  keep: {keep}  [{g.reason}]")
        for m in g.members:
            s = m.file.stream
            kbps = f"{s.bitrate_kbps}kbps" if s and s.bitrate_kbps else (m.file.container or "?")
            rb = f"rb {m.rb.content_id}" if m.rb else "not in rekordbox"
            lines.append(f"    {_tail(m.file.path.as_posix())}  {kbps}  {m.duration_s:.0f}s  {rb}")
    return lines


@tidy_app.command()
def audit(
    crate: str = _CRATE_ARG,
    folder: str = _FOLDER_OPT,
    all_tracks: bool = _ALL_OPT,
    profile: list[str] = typer.Option([], "--profile", help="Equipment profile from tidy.yaml. Repeatable. Default: default_profiles."),
    hash_mode: str = _HASH_OPT,
    no_dupes: bool = typer.Option(False, "--no-dupes", help="Skip duplicate detection."),
    no_report: bool = typer.Option(False, "--no-report", help="Print only, write no report files."),
    brief: bool = typer.Option(False, "--brief", help="--json without the per-item details (read the .md report instead)."),
    config: str = _CONFIG_OPT,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Read-only audit: tags, artwork, file names, CDJ playability, duplicates. Writes reports/tidy/*."""
    try:
        cfg, target, items, meta, known = _tidy_scan(crate, folder, all_tracks, config, hash_mode)
        profiles = tidy_config.profiles_named(cfg, profile)
        findings = [tidy_checks.check_item(it, profiles, cfg, known) for it in items]
        groups = [] if no_dupes else _dupe_groups(items, cfg)
        audit_d = tidy_report.audit_dict(target, cfg, profiles, items, findings, groups, meta)
        written = None if no_report else tidy_report.write_audit(audit_d, intake.tidy_paths())
    except TIDY_ERRORS as exc:
        _fail(exc)
    c = audit_d["counts"]
    lines = [f"audit {target.label}: {c['items']} file(s), profiles {', '.join(p.name for p in profiles)}", ""]
    for it, fs in zip(items, findings):
        if fs:
            worst = fs[0].severity.upper()
            lines.append(f"{worst:5}  {', '.join(sorted({f.code for f in fs}))}  {_tail(it.file.path.as_posix())}")
    lines += ["", f"{c['clean']} clean, {c['items_with_errors']} with errors; "
                  f"{c['error']} errors, {c['warn']} warnings, {c['info']} infos; "
                  f"{c['duplicate_groups']} duplicate group(s)"]
    lines += [f"  {n:4}  {code}" for code, n in c["by_code"].items()]
    lines += _dupe_lines(groups)
    for w in cfg.warnings:
        lines.append(f"config warning: {w}")
    payload: dict[str, Any] = dict(audit_d)
    if brief:
        payload.pop("items", None)
        payload.pop("duplicates", None)
    if written:  # R-904: the reports are a write; --no-report writes nothing and logs nothing
        payload["reports"] = [str(p) for p in written]
        lines += [f"report: {written[1]}", f"json:   {written[0]}"]
        payload["log"] = _log(f"tidy audit {_tidy_target(target.as_dict())}", {
            "files": c["items"], "errors": c["error"], "warnings": c["warn"], "dupe groups": c["duplicate_groups"],
        }, written[1])  # fmt: skip
        lines += _logged(payload["log"])
    lines.append("No file was changed. Next: dj tidy plan <same target>.")
    _out(as_json, payload, lines)


@tidy_app.command()
def dupes(
    crate: str = _CRATE_ARG,
    folder: str = _FOLDER_OPT,
    all_tracks: bool = _ALL_OPT,
    hash_mode: str = _HASH_OPT,
    config: str = _CONFIG_OPT,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Read-only: exact (same bytes) and fuzzy (same artist/title/version, length within 2 s) duplicates."""
    try:
        cfg, target, items, meta, _ = _tidy_scan(crate, folder, all_tracks, config, hash_mode)
        groups = _dupe_groups(items, cfg)
    except TIDY_ERRORS as exc:
        _fail(exc)
    payload = {"target": target.as_dict(), "scan": meta, "groups": [g.as_dict() for g in groups]}
    lines = _dupe_lines(groups) or ["No duplicates found."]
    lines.append(f"{len(groups)} group(s) in {len(items)} file(s). Report only: nothing is deleted or moved.")
    _out(as_json, payload, lines)


def _change_text(item: dict[str, Any]) -> str:
    parts = [f"{k} {v['old']!r} -> {v['new']!r}" if k != "art" else f"art <- {Path(v['new']).name}"
             for k, v in item["changes"].items()]
    if item.get("rename"):
        flag = "  (IMPORTED: needs Relocate)" if item["rename"].get("imported") else ""
        parts.append(f"rename -> {item['rename']['new']!r}{flag}")
    return "; ".join(parts)


@tidy_app.command(name="plan")
def tidy_plan_cmd(
    crate: str = _CRATE_ARG,
    folder: str = _FOLDER_OPT,
    all_tracks: bool = _ALL_OPT,
    rename: bool = typer.Option(False, "--rename", help="Also plan renames to the naming rule (files rekordbox does not know)."),
    rename_imported: bool = typer.Option(False, "--rename-imported", help="Rename files rekordbox knows too; writes a Relocate checklist on apply."),
    art: str = typer.Option("local", "--art", help="local = embed a cover image found next to the file; none."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Not in v1: only empty tags get proposals."),
    config: str = _CONFIG_OPT,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Write plans/<date>-tidy-<target>.plan.json: tag values parsed from file names for EMPTY tags only."""
    try:
        if overwrite:
            raise TidyError("--overwrite is not in v1: only empty tags get proposals.")
        cfg, target, items, meta, known = _tidy_scan(crate, folder, all_tracks, config, "none")
        plan = tidy_plan.build_plan(items, target, cfg, known, rename=rename, rename_imported=rename_imported, art=art)
        path = tidy_plan.write_plan(plan, intake.tidy_paths())
    except TIDY_ERRORS as exc:
        _fail(exc)
    c = plan["counts"]
    lines = [f"plan {target.label}: {c['items']} file(s), {c['with_changes']} with proposals, {c['renames']} rename(s)", ""]
    for item in plan["items"]:
        if item["changes"] or item["rename"]:
            conf = (item.get("parsed") or {}).get("confidence", "")
            lines.append(f"{(item['decision'] or '').upper():8} [{conf:6}] {_tail(item['file'])}")
            lines.append(f"          {_change_text(item)}")
    skipped: dict[str, int] = {}
    for item in plan["items"]:
        if item["skip_reason"]:
            skipped[item["skip_reason"]] = skipped.get(item["skip_reason"], 0) + 1
    lines += [""] + [f"  {n:4}  {reason}" for reason, n in sorted(skipped.items())]
    lines += [f"plan: {path}", "Set decision yes/no per item, then: dj tidy apply <plan> (dry-run, prints a preview id); after a yes: --apply --preview-id <id>."]
    line = _log(f"tidy plan {_tidy_target(target.as_dict())}",
                {"files": c["items"], "with proposals": c["with_changes"], "renames": c["renames"]}, path)
    lines += _logged(line)
    _out(as_json, {"plan": str(path), "counts": c, "target": target.as_dict(),
                   "items": [i for i in plan["items"] if i["changes"] or i["rename"]], "skipped": skipped,
                   "log": line}, lines)


def _refuse_if_rekordbox_runs() -> None:
    """Before any tidy write. Off Windows (safety.TIDY_WRITE_PLATFORMS) it refuses outright:
    tidy on macOS is R-1303, v0.2. On Windows it asks safety.rekordbox_running; where that
    check cannot answer it raises SafetyError and the write is refused, never guessed."""
    if sys.platform not in safety.TIDY_WRITE_PLATFORMS:
        raise safety.SafetyError(
            f"dj tidy writes audio files on Windows only in v0.1 (macOS: R-1303, v0.2); this is "
            f"{sys.platform}. Nothing written.")
    if safety.rekordbox_running():
        raise safety.RekordboxRunningError(
            f"{safety.process_name()} is running. Close rekordbox before writing audio files; it may hold them open "
            "and it must Reload Tag afterwards anyway.")


@tidy_app.command(name="apply")
def tidy_apply(
    plan_file: str = typer.Argument(..., help="plans/<date>-tidy-<target>.plan.json"),
    apply: bool = typer.Option(False, "--apply", help="Really write the tags / rename. Default is a dry-run."),
    strict: bool = typer.Option(False, "--strict", help="Any item that cannot run aborts the whole apply before the first write."),
    config: str = _CONFIG_OPT,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    preview_id: str = _PREVIEW_ID_OPT,
) -> None:
    """Write the `decision: yes` tag changes into the files (undo record first, temp + atomic replace).
    master.db is never touched: afterwards select the tracks in rekordbox and Reload Tag.

    The dry-run prints a preview id; --apply needs it (R-1102)."""
    recorded = None
    log_line = None
    target = "plan"
    try:
        cfg = tidy_config.load_config(config)
        plan = tidy_plan.load_plan(plan_file)
        if apply:
            _refuse_if_rekordbox_runs()
            write_gate.require_id(preview_id)
        gate_args = {"plan": write_gate.path_arg(plan_file), "strict": strict, "config": write_gate.path_arg(config)}
        # The dry-run reads the files and writes nothing; --apply recomputes it before the first write.
        result = tidy_plan.apply_plan(plan, Path(plan_file), cfg, intake.tidy_paths(), strict=strict, dry_run=True)
        changes = _tidy_apply_changes(result.applied)
        if not apply:
            recorded = write_gate.record("tidy-apply", gate_args, changes)
        else:
            write_gate.check(preview_id, "tidy-apply", gate_args, changes)
            target = _tidy_target(plan.get("target"))  # before apply_plan updates the plan dict
            result = tidy_plan.apply_plan(plan, Path(plan_file), cfg, intake.tidy_paths(), strict=strict, dry_run=False)
            if result.applied:  # only a write uses the id up: a run where every item failed can be retried
                _used(preview_id, str(result.undo_path))
            if result.applied or result.failed:  # a failed item has an undo record and may be half-written
                log_line = _log(f"tidy apply {target}", {"written": len(result.applied), "failed": len(result.failed),
                                                         "cannot run": len(result.skipped)}, result.undo_path)  # fmt: skip
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    except GateError as exc:
        _refused(exc)
    except tidy_plan.Interrupted as exc:  # files were written before the error: log them, then fail
        _log_interrupted(f"tidy apply {target}", exc)
        _fail(exc)
    except (*TIDY_ERRORS, safety.SafetyError) as exc:
        _fail(exc)
    verb = "WROTE   " if apply else "WOULD   "
    lines = [f"{verb} {_tail(i['file'])}\n          {_change_text(i)}" for i in result.applied]
    lines += [f"SKIP     {_tail(i['file'])}  [{why}]" for i, why in result.skipped]
    lines += [f"FAILED   {_tail(i['file'])}  [{why}]" for i, why in result.failed]
    c = result.as_dict()["counts"]
    lines += ["", f"{c['applied']} {'written' if apply else 'to write'}, {c['skipped']} cannot run, {c['failed']} failed, "
                  f"{c['applied_before']} applied earlier, {c['pending']} pending, {c['no']} no"]
    if strict and result.skipped:
        lines.append("STRICT: nothing written because some items cannot run.")
    if not apply:
        lines += recorded.lines() + [_to_write(recorded.preview_id)]
    else:
        lines.append(f"APPLIED. Undo: dj tidy undo {plan_file} (a dry-run with its preview id), then --apply "
                     f"--preview-id <id>  (records in {result.undo_path})")
        lines.append("In rekordbox: select these tracks -> right-click -> Reload Tag.")
        if result.relocate_path:
            lines.append(f"Renamed files rekordbox knows: Relocate each one, checklist {result.relocate_path}")
        if result.report_path:
            lines.append(f"report: {result.report_path}")
        lines += _logged(log_line)
    payload = result.as_dict() | (_preview_keys(recorded) if not apply else {"log": log_line})
    _out(as_json, payload, lines)
    if result.failed or (strict and result.skipped):
        raise typer.Exit(EXIT_ERROR)


def _tidy_apply_changes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What `dj tidy apply --apply` would write: per ready item its file, the hash the plan saw,
    the tag changes and the rename."""
    return [{"file": i.get("file"), "sha256": i.get("sha256"), "changes": i.get("changes"),
             "rename": i.get("rename")} for i in items]  # fmt: skip


def _tidy_undo_changes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What `dj tidy undo --apply` would restore: per undo record its files and hash."""
    return [{"seq": r.get("seq"), "file_before": r.get("file_before"), "file_after": r.get("file_after"),
             "sha256_after": r.get("sha256_after")} for r in records]  # fmt: skip


@tidy_app.command(name="undo")
def tidy_undo(
    plan_file: str = typer.Argument(..., help="The plan whose apply should be reverted."),
    apply: bool = typer.Option(False, "--apply", help="Really restore. Default is a dry-run."),
    force: bool = typer.Option(False, "--force", help="Restore even if the file changed after the apply."),
    config: str = _CONFIG_OPT,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    preview_id: str = _PREVIEW_ID_OPT,
) -> None:
    """Put the tags (and names) back from state/tidy/<plan>.undo.json, newest change first.

    The dry-run prints a preview id; --apply needs it (R-1102)."""
    recorded = None
    log_line = None
    target = "plan"
    try:
        cfg = tidy_config.load_config(config)
        plan = tidy_plan.load_plan(plan_file)
        if apply:
            _refuse_if_rekordbox_runs()
            write_gate.require_id(preview_id)
        gate_args = {"plan": write_gate.path_arg(plan_file), "force": force, "config": write_gate.path_arg(config)}
        # The dry-run reads the files and writes nothing; --apply recomputes it before the first write.
        result = tidy_plan.undo_plan(plan, Path(plan_file), cfg, intake.tidy_paths(), dry_run=True, force=force)
        changes = _tidy_undo_changes(result.restored)
        if not apply:
            recorded = write_gate.record("tidy-undo", gate_args, changes)
        else:
            write_gate.check(preview_id, "tidy-undo", gate_args, changes)
            target = _tidy_target(plan.get("target"))
            result = tidy_plan.undo_plan(plan, Path(plan_file), cfg, intake.tidy_paths(), dry_run=False, force=force)
            if result.restored:  # only a write uses the id up: a run where every item failed can be retried
                _used(preview_id, str(result.undo_path))
            if result.restored or result.failed:  # a failed restore may have renamed the file back already
                log_line = _log(f"tidy undo {target}", {"restored": len(result.restored), "failed": len(result.failed),
                                                        "skipped": len(result.skipped)}, result.undo_path)  # fmt: skip
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    except GateError as exc:
        _refused(exc)
    except tidy_plan.Interrupted as exc:  # files were restored before the error: log them, then fail
        _log_interrupted(f"tidy undo {target}", exc)
        _fail(exc)
    except (*TIDY_ERRORS, safety.SafetyError) as exc:
        _fail(exc)
    verb = "RESTORED" if apply else "WOULD   "
    lines = [f"{verb} {_tail(r['file_before'])}" for r in result.restored]
    lines += [f"SKIP     {_tail(r['file_before'])}  [{why}]" for r, why in result.skipped]
    lines += [f"FAILED   {_tail(r['file_before'])}  [{why}]" for r, why in result.failed]
    c = result.as_dict()["counts"]
    lines += ["", f"{c['restored']} {'restored' if apply else 'to restore'}, {c['skipped']} skipped, {c['failed']} failed"]
    if not apply:
        lines += recorded.lines() + [_to_write(recorded.preview_id)]
    else:
        lines.append("UNDONE. In rekordbox: select these tracks -> Reload Tag.")
        lines += _logged(log_line)
    _out(as_json, result.as_dict() | (_preview_keys(recorded) if not apply else {"log": log_line}), lines)
    if result.failed:
        raise typer.Exit(EXIT_ERROR)


if __name__ == "__main__":
    app()
