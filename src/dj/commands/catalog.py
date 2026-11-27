"""`dj library query | note`: the track catalog in the dj-library folder (D-37).

Nothing here writes to rekordbox, Spotify or audio files. `query` reads catalog/catalog.db (one SELECT,
read-only) after checking it against master.db, so the catalog is never stale; `note` appends one row
to its `notes` table. Both are library-text commands: no preview id. `cli.py` registers them on
`dj library`, as it registers `dj backup`.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import typer

from dj import catalog
from dj.analysis.common import NotALibraryFolder
from dj.libfolder import configured_root
from dj.model import LibraryError

EXIT_ERROR = 1
EXIT_REFUSED = 2  # the folder is not a dj-library (`REFUSED <reason>` on stderr)
_LIBRARY = typer.Option(None, "--library", help="The dj-library folder. Default: the configured one.")
_JSON = typer.Option(False, "--json", help="Machine-readable output.")


def _run(as_json: bool, call: Callable[[], dict[str, Any]], lines: Callable[[dict[str, Any]], list[str]]) -> None:
    try:
        result = call()
    except NotALibraryFolder as exc:
        typer.echo(f"REFUSED {exc}", err=True)
        raise typer.Exit(EXIT_REFUSED) from None
    except (LibraryError, OSError, ValueError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    if as_json:
        typer.echo(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        typer.echo("\n".join(lines(result)))


def query(
    sql: str = typer.Argument(..., help="One SELECT on the catalog: tracks, playlists, playlist_tracks, notes, meta."),
    page: int = typer.Option(1, "--page", min=1, help=f"The page of the result ({catalog.PAGE_ROWS} rows a page)."),
    library: str = _LIBRARY,
    as_json: bool = _JSON,
) -> None:
    """Ask the track catalog one SELECT: counts first (rows, page, pages), the columns, the rows.

    The catalog is checked against master.db first and built again when rekordbox changed. Read-only:
    anything but one SELECT is refused with one line (exit 1)."""

    def call() -> dict[str, Any]:
        root = library or configured_root()
        statement = catalog.one_select(sql)  # refused before anything is read or built
        catalog.ensure(root)
        return catalog.query(root, statement, page)

    def lines(result: dict[str, Any]) -> list[str]:
        c = result["counts"]
        head = f"{c['rows']} rows, page {c['page']} of {c['pages']}"
        table = ["\t".join(result["columns"])] + ["\t".join(str(v) for v in row) for row in result["rows"]]
        return [head, *table]

    _run(as_json, call, lines)


def note(
    track_id: str = typer.Argument(..., help="The track's id, as `dj library query` shows it (tracks.id)."),
    field: str = typer.Argument(..., help="What the note is about, one or two words: energy, mood, set, note."),
    value: str = typer.Argument(..., help="The note itself, one line."),
    source: str = typer.Option("dj", "--source", help="Who says so: dj (default), or where it came from."),
    library: str = _LIBRARY,
    as_json: bool = _JSON,
) -> None:
    """Add one dated note about a track to the catalog (table notes). Notes survive every rebuild.

    An id the catalog does not hold writes nothing (exit 1). Appends one log.md line."""

    def call() -> dict[str, Any]:
        root = library or configured_root()
        catalog.ensure(root)
        return catalog.note(root, track_id, field, value, source)

    def lines(result: dict[str, Any]) -> list[str]:
        n = result["note"]
        out = [f"note: {result['track']} ({n['track_id']}) {n['field']} = {n['value']} [{n['source']}, {n['date']}]",
               f"{result['counts']['notes']} note(s) on this track in {result['db']}"]  # fmt: skip
        return out + ([f"log: {result['log']}"] if result["log"] else [])

    _run(as_json, call, lines)
