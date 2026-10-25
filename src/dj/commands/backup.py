"""`dj backup`: a verified copy of the rekordbox database in the dj-library folder (W-37, D-31, R-206).

Reads rekordbox's folder, writes only under `<dj-library>/backups/`; see `dj.backup`. No preview id:
it never touches rekordbox and only adds files (the one write without one, CLAUDE.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from dj import backup as backup_mod
from dj import libfolder

EXIT_ERROR = 1
EXIT_REFUSED = 2  # the folder is not one a backup may go into (`REFUSED <reason>` on stderr)


def _echo(as_json: bool, payload: dict[str, Any], lines: list[str]) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False) if as_json else "\n".join(lines))


def backup(
    library: Path | None = typer.Option(None, "--library", help="The dj-library folder (default: DJ_LIBRARY)."),
    list_only: bool = typer.Option(False, "--list", help="List the backups (date, verified, size) and the total."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Back up rekordbox's database (master.db, its -wal/-shm, masterPlaylists6.xml) into
    <dj-library>/backups/rekordbox-<date>/, verified, with RESTORE.md. Unchanged since the newest
    verified backup: nothing is copied. Never writes rekordbox's folder; never deletes a backup."""
    try:
        root = library.expanduser().resolve() if library else backup_mod.default_library()
        if list_only:
            listing = backup_mod.list_backups(root)
            _echo(as_json, listing, backup_mod.list_lines(listing))
            return
        result = backup_mod.take_backup(root)
    except backup_mod.BackupError as exc:
        refused = exc.reason in ("synced", "not_library", "pioneer")
        typer.echo(f"REFUSED {exc}" if refused else str(exc), err=True)
        raise typer.Exit(EXIT_REFUSED if refused else EXIT_ERROR) from None
    except libfolder.LibraryFolderError as exc:  # no dj-library configured
        typer.echo(f"REFUSED {exc}", err=True)
        raise typer.Exit(EXIT_REFUSED) from None
    log = None
    if result.status != "unchanged":  # R-904: one log.md line per change; nothing new, no line
        action = "backup" if result.verified else "backup, NOT verified"
        try:
            log = libfolder.append_log(root, action, {"files": len(result.manifest["files"])}, file=result.folder)
        except (OSError, libfolder.LibraryFolderError) as exc:
            typer.echo(f"warning: no log.md line ({exc})", err=True)
    _echo(as_json, result.as_json() | {"log": log}, [result.line])
