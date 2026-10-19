"""`dj library ...`: the library model (XML export or master.db snapshot) and its analysis.

Nothing here writes to rekordbox: `inspect` only reads; `profile`, `structure` and `taste`
write text files in the library folder (R-341).
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import typer

from dj import libfolder
from dj.analysis import profile as profile_analysis
from dj.analysis import structure as structure_analysis
from dj.analysis import taste as taste_analysis
from dj.analysis.common import parse_day
from dj.libfolder import configured_root
from dj.model import Library, LibraryError, PlaylistNode
from dj.readers.xml import XML_FIELDS_MISSING, XML_NOTES, read_xml
from dj.treeschema import TreeSchemaError

EXIT_ERROR = 1
EXIT_REFUSED = 2
# The tree part of `inspect` is bounded so the MCP result stays under the tool-result limit
# (NFR-03): counts are complete, names are a sample.
TOP_LIMIT = 30  # top-level nodes listed; the rest are counted in "tree_more"
CHILD_LIMIT = 10  # child names listed per node; the rest are counted in "more_children"
NAME_LIMIT = 120  # characters of a name shown; longer names end in "..."

library_app = typer.Typer(
    add_completion=False, no_args_is_help=True, pretty_exceptions_show_locals=False,
    help="The DJ's library as one model, read from a rekordbox XML export or a master.db "
         "snapshot, and its analysis. Nothing here writes to rekordbox.",
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


@library_app.command("profile")
def profile_cmd(
    library: str = typer.Option(None, "--library", help="The dj-library folder. Default: the configured one."),
    xml: str = typer.Option(None, "--xml", help="Read this collection XML instead of the latest export."),
    today: str = typer.Option(None, "--today", help="Date written into the files, YYYY-MM-DD. Default: today."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Measure the library: writes profile/stats.md, profile/facts.json and a log.md line.

    R-311. Reads the export only: nothing goes to rekordbox, Spotify or audio files (R-341)."""
    try:
        root = libfolder.configured_root() if not library else library
        result = profile_analysis.run(root, xml=xml, today=parse_day(today))
    except (LibraryError, OSError, ValueError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)
    if as_json:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    lines = [f"wrote {path}" for path in result["written"]] + [f"source: {result['source']}", ""]
    lines += [f"{h['label']}: {h['value']} ({h['note']})" for h in result["headline"]]
    typer.echo("\n".join(lines))


def _structure_lines(result: dict[str, Any]) -> list[str]:
    c = result["counts"]
    lines = [
        f"structure: read {result['source']} ({c['playlists'] + c['smart']} playlists, "
        f"{c['folders']} folders, {c['tracks']} tracks)",
        "wrote:",
        *[f"  {path}" for path in result["written"]],
    ]
    if result["kept"]:
        lines += ["kept your edited tree:", *[f"  {path}" for path in result["kept"]]]
    lines += ["what it reveals:", *[f"  - {line}" for line in result["reveals"]]]
    lines += ["", "Nothing was written to rekordbox."]
    return lines


@library_app.command()
def structure(
    library: str = typer.Option(None, "--library", help="The dj-library folder. Default: the configured one."),
    xml: str = typer.Option(None, "--xml", help="A collection XML to read instead of the latest export."),
    today: str = typer.Option(None, "--today", help="Date written into the files, YYYY-MM-DD. Default: today."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Measure the playlist tree: writes structure/analysis.md, graph.json, facts.json and
    current-tree.yaml in the library folder, and one log.md line. Never writes to rekordbox."""
    try:
        day = date.fromisoformat(today) if today else None
        root = Path(library) if library else configured_root()
        result = structure_analysis.run(root, xml=xml, today=day)
    except (LibraryError, TreeSchemaError, OSError, ValueError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False) if as_json else "\n".join(_structure_lines(result)))


SHOWN_LINES = 5  # added lines shown per file in the text output; --json carries all of them


@library_app.command()
def taste(
    library: str = typer.Option("", "--library", help="The dj-library folder. Empty: the configured one."),
    xml: str = typer.Option("", "--xml", help="Read this export instead of the latest one in exports/."),
    today: str = typer.Option("", "--today", help="Date for new entries, YYYY-MM-DD. Empty: today."),
    rebuild: bool = typer.Option(
        False, "--rebuild", help="Rewrite taste/*.md from scratch. Only after the DJ said yes."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Measure the DJ's taste (lanes, labels, artists, anchors, words) and append it to taste/.

    Appends, never rewrites (R-332): every run adds only new or changed lines and shows them.
    Reads the export only; never writes to rekordbox, Spotify or audio files (R-341).
    """
    try:
        day = date.fromisoformat(today) if today else None
        folder = library or configured_root()
        result = taste_analysis.run(folder, xml=xml or None, today=day, rebuild=rebuild)
    except taste_analysis.NotALibraryFolder as exc:
        typer.echo(f"REFUSED {exc}", err=True)
        raise typer.Exit(EXIT_REFUSED)
    except taste_analysis.TasteWriteError as exc:  # failed part way: still show what was added
        if as_json:
            typer.echo(json.dumps({"ok": False, "error": str(exc), "written": exc.written, "added": exc.added},
                                  indent=2, ensure_ascii=False))  # fmt: skip
        else:
            typer.echo("\n".join(_added_lines(exc.added)))
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)
    except (LibraryError, OSError, ValueError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)
    if as_json:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    c = result["counts"]
    lines = [
        f"taste: {c['lines_added']} lines added from {result['source']}"
        + (" (rebuilt from scratch)" if result["rebuild"] else ""),
        f"counts: {c['tracks']} tracks, {c['lanes']} lanes, {c['clusters']} clusters, "
        f"{c['anchors']} anchors, {c['pairs']} pairs, {c['words']} words",
    ]
    if result["backup"]:
        lines.append(f"old files kept in {result['backup']['folder']}")
    lines += _added_lines(result["added"])
    lines.append("log: " + result["log"])
    typer.echo("\n".join(lines))


def _added_lines(added: dict[str, list[str]]) -> list[str]:
    """The diff per file (R-332): at most SHOWN_LINES lines each, then how many more."""
    lines = []
    for path, new in added.items():
        lines.append(f"{path}: +{len(new)}")
        lines += [f"  {line}" for line in new[:SHOWN_LINES]]
        if len(new) > SHOWN_LINES:
            lines.append(f"  ... {len(new) - SHOWN_LINES} more in {path}")
    return lines
