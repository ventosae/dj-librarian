"""`dj library ...`: the library model (XML export or master.db snapshot). Read-only here."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

import typer

from dj.model import Library, LibraryError, PlaylistNode
from dj.readers.xml import XML_FIELDS_MISSING, XML_NOTES, read_xml

EXIT_ERROR = 1
# The tree part of `inspect` is bounded so the MCP result stays under the tool-result limit
# (NFR-03): counts are complete, names are a sample.
TOP_LIMIT = 30  # top-level nodes listed; the rest are counted in "tree_more"
CHILD_LIMIT = 10  # child names listed per node; the rest are counted in "more_children"
NAME_LIMIT = 120  # characters of a name shown; longer names end in "..."

library_app = typer.Typer(
    add_completion=False, no_args_is_help=True, pretty_exceptions_show_locals=False,
    help="The DJ's library as one model, read from a rekordbox XML export or a master.db "
         "snapshot. Read-only: nothing here writes to rekordbox.",
)  # fmt: skip


def _name(name: str) -> str:
    return name if len(name) <= NAME_LIMIT else name[: NAME_LIMIT - 3] + "..."


def _node_entry(node: PlaylistNode) -> dict[str, Any]:
    entry: dict[str, Any] = {"kind": node.kind, "name": _name(node.name)}
    if node.kind == "playlist" or (node.kind == "smart" and node.track_ids):
        entry["tracks"] = len(node.track_ids)  # a smart node without members: unknown, left out
    entry["children"] = [_name(child.name) for child in node.children[:CHILD_LIMIT]]
    if len(node.children) > CHILD_LIMIT:
        entry["more_children"] = len(node.children) - CHILD_LIMIT
    return entry


def summary(lib: Library, snapshot_path: str | None = None) -> dict[str, Any]:
    """Counts first, then a bounded sample of the top of the tree (NFR-03)."""
    if lib.source == "xml":
        missing, notes = list(XML_FIELDS_MISSING), list(XML_NOTES)
    else:
        from dj.readers.db import (
            DB_NOTES,  # a db Library means the db reader is loaded already
        )

        missing, notes = [], list(DB_NOTES)
    return {
        "source": lib.source,
        "counts": lib.counts(),
        "source_path": lib.source_path,
        "snapshot_path": snapshot_path,
        "rekordbox_version": lib.rekordbox_version,
        "tree": [_node_entry(n) for n in lib.roots[:TOP_LIMIT]],
        "tree_more": max(0, len(lib.roots) - TOP_LIMIT),
        "fields_missing": missing,
        "notes": notes,
    }


def _lines(data: dict[str, Any]) -> list[str]:
    c = data["counts"]
    lines = [f"source:      {data['source']}  {data['source_path']}"]
    if data["snapshot_path"]:
        lines.append(f"snapshot:    {data['snapshot_path']} (read, then removed)")
    lines += [
        f"rekordbox:   {data['rekordbox_version'] or 'unknown'}",
        f"counts:      {c['tracks']} tracks, {c['folders']} folders, {c['playlists']} playlists, "
        f"{c['smart']} smart, {c['orphans']} orphans, {c['entries']} entries",
        "",
        "top of the tree:",
    ]
    for node in data["tree"]:
        size = f" ({node['tracks']} tracks)" if "tracks" in node else ""
        lines.append(f"  [{node['kind']}] {node['name']}{size}")
        lines += [f"      {name}" for name in node["children"]]
        if node.get("more_children"):
            lines.append(f"      ... {node['more_children']} more")
    if data["tree_more"]:
        lines.append(f"  ... {data['tree_more']} more at the top")
    if data["fields_missing"]:
        lines += ["", "not in the XML export: " + ", ".join(data["fields_missing"])]
    if data["notes"]:
        lines += ["", "notes:"] + [f"  {note}" for note in data["notes"]]
    return lines


class _ReaderLog(logging.Handler):
    """Shows what the readers log (INFO and up) on stderr, so the snapshot path is logged in
    real runs too (R-202), and keeps that path for the JSON."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.snapshot: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.snapshot = getattr(record, "snapshot", None) or self.snapshot
            typer.echo(f"{record.levelname} {record.getMessage()}", err=True)
        except Exception:
            self.handleError(record)


@contextmanager
def _reader_log() -> Iterator[_ReaderLog]:
    logger = logging.getLogger("dj.readers")
    handler, level = _ReaderLog(), logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


@library_app.command()
def inspect(
    xml: str = typer.Argument(None, help="A rekordbox collection XML. Empty: a master.db snapshot."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Read-only summary: source, counts, top of the tree, what the source does not carry."""
    with _reader_log() as reader_log:
        try:
            if xml:
                lib = read_xml(xml)
            else:
                from dj.readers.db import (
                    read_db,  # Door 2: pyrekordbox only when asked for
                )

                lib = read_db()
        except (LibraryError, OSError) as exc:
            typer.echo(f"ERROR {exc}", err=True)
            raise typer.Exit(EXIT_ERROR)
    data = summary(lib, reader_log.snapshot)
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False) if as_json else "\n".join(_lines(data)))
