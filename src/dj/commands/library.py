"""`dj library ...`: the library model (XML export or master.db snapshot) and its analysis.

Nothing here writes to rekordbox: `inspect` only reads; `profile`, `structure`, `taste`,
`identity`, `report` and `analyze` write text files in the library folder (R-341); `build` and `crate`
write a rekordbox XML the DJ imports, only with the id of a preview the DJ said yes to
(R-501..R-505, R-601..R-604).
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import typer

from dj import barber, build_structure, hostenv, libfolder
from dj import crate as crate_mod
from dj import report as report_mod
from dj.analysis import identity as identity_analysis
from dj.analysis import profile as profile_analysis
from dj.analysis import run_all
from dj.analysis import structure as structure_analysis
from dj.analysis import taste as taste_analysis
from dj.analysis.common import NotALibraryFolder, parse_day
from dj.gate import GateError
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
        "streaming": len(lib.streaming),  # rows rekordbox streams, left out of counts (Q-34)
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
        f"{c['smart']} smart, {c['orphans']} orphans, {c['entries']} entries"
        + (f"; {data['streaming']} streamed not counted" if data.get("streaming") else ""),
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


@library_app.command("identity")
def identity_cmd(
    library: str = typer.Option("", "--library", help="The dj-library folder. Empty: the configured one."),
    xml: str = typer.Option("", "--xml", help="Read this export instead of the latest one in exports/."),
    today: str = typer.Option(
        "", "--today", help="Date the axes are measured at, YYYY-MM-DD. Empty: the date in profile/facts.json."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Six measured axes, an archetype and the sleeve: profile/identity.json, profile/sleeve.svg.

    R-1401..R-1403. Reads profile/, structure/ and taste/ facts (run profile, structure and taste
    first) and the export; one log.md line. Never writes to rekordbox, Spotify or audio files."""
    try:
        root = library or configured_root()
        result = identity_analysis.run(root, xml=xml or None, today=parse_day(today))
    except NotALibraryFolder as exc:
        typer.echo(f"REFUSED {exc}", err=True)
        raise typer.Exit(EXIT_REFUSED)
    except (LibraryError, OSError, ValueError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)
    if as_json:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    scores = ", ".join(f"{axis} {score}" for axis, score in result["scores"].items())
    lines = [
        f"identity: {result['archetype']['name']} ({' + '.join(result['top'])}) for {result['handle']}",
        f"axes: {scores}",
        *[f"wrote {path}" for path in result["written"]],
        f"log: {result['log']}",
        "",
        "Nothing was written to rekordbox.",
    ]
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


# -- report and analyze (R-401 ... R-407) ------------------------------------------------------


def _proposal_lines(proposals: list[dict[str, Any]]) -> list[str]:
    return [f"  {p['trigger']} (about {p['cost_minutes']} minutes, {p['family']})" for p in proposals]


@library_app.command("report")
def report_cmd(
    library: str = typer.Option(None, "--library", help="The dj-library folder. Default: the configured one."),
    today: str = typer.Option(None, "--today", help="Date of the report, YYYY-MM-DD. Default: today."),
    render_only: bool = typer.Option(
        False, "--render-only",
        help="Only render the HTML report from the folder's files; structure/proposals.yaml stays as "
             "it is (use it after renaming a proposal).",
    ),  # fmt: skip
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Build 2 or 3 restructure proposals into structure/proposals.yaml and render the HTML report
    reports/<date>-library.html from the files in the library folder. One log.md line.
    --render-only skips the proposals step, so a renamed proposal shows as written.

    R-401..R-406. Reads the latest export and the folder's files; never writes to rekordbox.
    A second report on the same day is <date>-library-2.html: `report` names the file written."""
    try:
        root = library or configured_root()
        if render_only:
            result = report_mod.run_render(root, today=parse_day(today))
        else:
            result = report_mod.run_report(root, today=parse_day(today))
    except NotALibraryFolder as exc:
        typer.echo(f"REFUSED {exc}", err=True)
        raise typer.Exit(EXIT_REFUSED)
    except (LibraryError, TreeSchemaError, OSError, ValueError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)
    if as_json:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if render_only:
        lines = [f"report: {result['report']} ({result['counts']['proposals']} proposals from "
                 "structure/proposals.yaml)", f"wrote {result['report']}"]  # fmt: skip
    else:
        lines = [f"report: {result['report']} ({result['counts']['proposals']} proposals from {result['source']})"]
        lines += _proposal_lines(result["proposals"])
        lines += [f"wrote {path}" for path in result["written"]]
        lines += [f"kept your edited copy {path}" for path in result["kept"]]
    lines += ["log: " + result["log"], "", "Nothing was written to rekordbox."]
    typer.echo("\n".join(lines))


@library_app.command("analyze")
def analyze_cmd(
    library: str = typer.Option(None, "--library", help="The dj-library folder. Default: the configured one."),
    source: str = typer.Option("xml", "--source", help="xml: the latest export (or --xml); db: a master.db snapshot."),
    xml: str = typer.Option(None, "--xml", help="Read this collection XML instead of the latest export."),
    today: str = typer.Option(None, "--today", help="Date written into the files, YYYY-MM-DD. Default: today."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Read the library once, then profile, structure, taste, identity, proposals and the HTML report.

    Writes text files in the library folder only, one log.md line per step. --source db reads a
    snapshot copy of master.db (read-only). Never writes to rekordbox, Spotify or audio files.
    Exit 1 when a step failed (the rest still ran; `failed` names it)."""
    with _reader_log():
        try:
            root = library or configured_root()
            result = run_all.analyze(root, source=source, xml=xml, today=parse_day(today))
        except NotALibraryFolder as exc:
            typer.echo(f"REFUSED {exc}", err=True)
            raise typer.Exit(EXIT_REFUSED)
        except (LibraryError, TreeSchemaError, OSError, ValueError) as exc:
            typer.echo(f"ERROR {exc}", err=True)
            raise typer.Exit(EXIT_ERROR)
    if as_json:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        c = result["counts"]
        lines = [
            f"analyze: read {result['read']} ({c['tracks']} tracks, {c['playlists']} playlists, {c['folders']} folders)",
            f"report: {result['report'] or 'not rendered'}",
            *_proposal_lines(result["proposals"]),
            f"wrote {c['files']} files:",
            *[f"  {path}" for path in result["written"]],
            *[f"kept your edited copy {path}" for path in result["kept"]],
            *[f"FAILED {f['step']}: {f['error']}" for f in result["failed"]],
            "",
            "Nothing was written to rekordbox.",
        ]
        typer.echo("\n".join(lines))
    if result["failed"]:
        raise typer.Exit(EXIT_ERROR)


# -- dj library use (R-102: the engine card's step 2) ----------------------------------------


@library_app.command()
def use(
    folder: str = typer.Argument(..., help="The DJ's dj-library folder (set up by dj-start)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Tell the engine where the dj-library folder is: stores its absolute path in
    state/library-path.txt (gitignored) and prints it. The MCP tools then read and write there.
    The DJ_LIBRARY environment variable, when set, still wins."""
    path = Path(folder).expanduser()
    if not path.is_dir():
        _fail(f"{folder} is not a folder. Point it at the dj-library folder dj-start set up.")
    if not (path / "library.yaml").is_file():
        typer.echo(f"REFUSED {path} is not a dj-library folder (no library.yaml). Set it up with dj-start "
                   "first, or point at the folder that holds library.yaml. Nothing was stored.", err=True)  # fmt: skip
        raise typer.Exit(EXIT_REFUSED)
    try:
        if hostenv.env_value(libfolder.ENV_VAR):
            libfolder.configured_root()  # an unusable DJ_LIBRARY refuses before anything is stored
        stored = libfolder.remember_root(path)
        effective = libfolder.configured_root()
    except libfolder.LibraryFolderError as exc:
        typer.echo(f"REFUSED {exc} Nothing was stored.", err=True)
        raise typer.Exit(EXIT_REFUSED)
    stored_in = str(libfolder._state_file()) if hostenv.bundle_mode() else "state/library-path.txt"
    data = {"library": str(stored), "stored_in": stored_in, "in_use": str(effective)}
    if as_json:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return
    lines = [f"Library folder: {stored}", f"Stored in {stored_in}."]
    if effective != stored:
        lines.append(f"DJ_LIBRARY is set and wins for now: {effective}")
    typer.echo("\n".join(lines))


# -- dj library build (R-501..R-505) -------------------------------------------------------


def _refuse(message: str) -> None:
    typer.echo(f"REFUSED {message}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _fail(message: str) -> None:
    typer.echo(f"ERROR {message}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _preview_lines(data: dict[str, Any], rows: list[Any], slug: str) -> list[str]:
    c = data["counts"]
    state = "new, written now" if data["yaml_created"] else "yours, read as it is"
    lines = [
        f"proposal:    {data['name']} ({slug})",
        f"tree file:   {data['yaml']} ({state})",
        f"tracks from: {data['export']}",
        f"counts:      {c['create']} create, {c['skip']} skip, {c['conflict']} conflict, "
        f"{c['manual']} manual, {c['tracks']} tracks",
        "",
    ]
    for row in rows:
        source = f"  <- {', '.join(row.fill_from)}" if row.op == "CREATE" and row.fill_from else ""
        note = f"  ({row.note})" if row.op in ("CONFLICT", "MANUAL") and row.note else ""
        lines.append(f"  {row.op:<8} {row.kind:<8} {'/'.join(row.path)}{source}{note}")
    if data["lands"]:
        lines += ["", "where existing playlists land:"]
        lines += [f"  {x['from']} -> {x['to']} ({x['tracks']} tracks)" for x in data["lands"]]
        if data["lands_more"]:
            lines.append(f"  ... {data['lands_more']} more")
    if data["unplaced"]:
        lines += ["", f"{data['unplaced']} track(s) have no file location and stay out of the XML."]
    if data.get("vetoed"):
        lines += ["", f"{data['vetoed']} vetoed track(s) (taste/vetoes.md) stay out of the XML."]
    lines += [f"WARNING {w}" for w in data["warnings"]]
    lines += ["", "Nothing written yet."]
    if data["blocked"]:
        lines.append(f"BLOCKED {data['blocked']}")
    else:
        lines.append(f"preview id:  {data['preview_id']}")
        lines.append(
            f"to write:    dj library build {slug} --apply --preview-id {data['preview_id']} "
            "(only after the DJ said yes)"
        )
    return lines


def _apply_lines(data: dict[str, Any]) -> list[str]:
    c = data["counts"]
    lines = [
        f"Wrote {data['written']} ({c['create']} create, {c['skip']} skip, {c['manual']} manual, "
        f"{c['tracks']} tracks). rekordbox untouched until you import it.",
        f"Import in rekordbox ({data['device']}):",
    ]
    lines += [f"  {n}. {step}" for n, step in enumerate(data["import_steps"], 1)]
    lines.append(f"log.md: {data['log_line']}")
    lines += [f"WARNING {w}" for w in data["warnings"]]
    return lines


@library_app.command()
def build(
    proposal: str = typer.Argument(..., help="Slug, name, or 'Build me the <name> structure'."),
    library: str = typer.Option(None, "--library", help="The dj-library folder. Default: the configured one."),
    apply: bool = typer.Option(False, "--apply", help="Write proposals/<slug>.xml. Needs --preview-id."),
    preview_id: str = typer.Option(None, "--preview-id", help="The id the preview printed, after the DJ's yes."),
    today: str = typer.Option(None, "--today", help="Date for new files and library.yaml (YYYY-MM-DD)."),
    rows_limit: int = typer.Option(
        build_structure.ROWS_LIMIT, "--rows-limit", min=0,
        help="Rows in the preview's --json; the rest are counted in rows_more. 0 = every row (the MCP tool pages them).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    source: str = typer.Option(None, "--source", help="xml: the latest export; db: a master.db snapshot. Default: library.yaml's."),
) -> None:
    """Preview a proposal (CREATE / SKIP / CONFLICT / MANUAL per node), or with --apply and the
    preview id write proposals/<slug>.xml for the DJ to import. Reads master.db only for --source db."""
    if apply and not (preview_id or "").strip():
        _refuse("--apply needs --preview-id: run the preview, show it, write only after a yes.")
    try:
        day = date.fromisoformat(today) if today else None
    except ValueError:
        _fail(f"--today: expected YYYY-MM-DD, got {today!r}")
    try:
        root = Path(library) if library else libfolder.configured_root()
        if not root.is_dir():
            _fail(f"{root} is not a folder. Scaffold the dj-library folder first (dj-start).")
        if apply:
            result = build_structure.apply(root, proposal, (preview_id or "").strip(), today=day, source=source)
            data = result.to_dict()
            text = _apply_lines(data)
        else:
            found = build_structure.preview(root, proposal, today=day, source=source)
            data = found.to_dict(root, limit=rows_limit or len(found.rows))
            text = _preview_lines(data, list(found.rows), found.slug)
    except GateError as exc:
        _refuse(str(exc))
    except (build_structure.BuildError, TreeSchemaError, LibraryError, OSError, ValueError) as exc:
        _fail(str(exc))
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False) if as_json else "\n".join(text))


# -- dj library barber next|record (Style Barber, R-701, R-703) ------------------------------

barber_app = typer.Typer(
    add_completion=False, no_args_is_help=True, pretty_exceptions_show_locals=False,
    help="Style Barber: one short question at a time (at most 8, about 10 minutes) that sharpens "
         "taste/. Writes dated lines in taste/*.md, .cache/barber.json and log.md; never rekordbox.",
)  # fmt: skip
library_app.add_typer(barber_app, name="barber")


def _question_lines(q: dict[str, Any]) -> list[str]:
    def bpm(track: dict[str, Any]) -> str:
        return f" ({track['bpm']} BPM)" if track["bpm"] else ""

    lines = [q["progress"], q["prompt"]]
    if q["kind"] == "ab":  # the chips name the tracks
        lines += [f"  {chip}{bpm(track)}" for chip, track in zip(q["chips"], q["tracks"])]
    else:
        lines += [f"  {track['label']}{bpm(track)}" for track in q["tracks"]]
        if q["chips"]:
            lines.append("  " + " / ".join(q["chips"]))
    lines.append(f"  {q['context']}")
    answers = "|".join(q["options"]) + "|skip" if q["options"] else "text|skip"
    lines.append(f"answer: dj library barber record {q['n']} <{answers}>  -> {q['file']}")
    return lines


def _barber_counts(c: dict[str, int]) -> str:
    return f"{c['answered']} answered, {c['skipped']} skipped, {c['left']} left of {c['questions']}"


def _barber_run(as_json: bool, call: Any, lines: Any) -> None:
    try:
        result = call()
    except NotALibraryFolder as exc:
        typer.echo(f"REFUSED {exc}", err=True)
        raise typer.Exit(EXIT_REFUSED)
    except (LibraryError, OSError, ValueError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False) if as_json else "\n".join(lines(result)))


@barber_app.command("next")
def barber_next(
    library: str = typer.Option("", "--library", help="The dj-library folder. Empty: the configured one."),
    today: str = typer.Option("", "--today", help="The session date, YYYY-MM-DD. Empty: today."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Plan today's session (or resume it) and show the next question. Counts first."""

    def lines(result: dict[str, Any]) -> list[str]:
        head = f"barber: {_barber_counts(result['counts'])}" + (" (resumed)" if result["resumed"] else "")
        if result["done"]:
            files = ", ".join(result["files"]) or "no taste file changed"
            return [head, f"done for today: {files}"]
        question = _question_lines(result["question"])
        context = [result["archetype_line"]] if result.get("archetype_line") else []
        return [head, *question[:2], *context, *question[2:]]  # the archetype right under the question

    _barber_run(as_json, lambda: barber.next_step(library or configured_root(), today=parse_day(today)), lines)


@barber_app.command("record")
def barber_record(
    n: int = typer.Argument(..., help="The question number, as `next` showed it."),
    answer: str = typer.Argument(..., help="A chip (A, B, keep, never, good), its number, free text, or skip."),
    library: str = typer.Option("", "--library", help="The dj-library folder. Empty: the configured one."),
    today: str = typer.Option("", "--today", help="The session date, YYYY-MM-DD. Empty: today."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Record an answer to today's session and show the next question, or done.

    Appends one dated line to a taste file (never a rewrite). An answer the question does not
    take writes nothing (exit 1)."""

    def lines(result: dict[str, Any]) -> list[str]:
        rec = result["recorded"]
        added = result["counts"]["lines_added"]
        out = [
            f"barber: question {rec['n']} {rec['status']} ({rec['answer']}) -> {added} "
            f"line{'' if added == 1 else 's'} added to {rec['file'] if added else 'no file'}",
            *[f"  {line}" for lines_ in result["added"].values() for line in lines_],
        ]
        if result["log"]:
            out.append(f"log: {result['log']}")
        out.append(f"barber: {_barber_counts(result['counts'])}")
        if result["done"]:
            out.append("done for today: " + (", ".join(result["files"]) or "no taste file changed"))
        else:
            out += _question_lines(result["next"])
        return out

    _barber_run(
        as_json, lambda: barber.answer(library or configured_root(), n, answer, today=parse_day(today)), lines
    )


# -- dj library crate (R-601..R-604, R-702) ------------------------------------------------


def _pick_line(n: int, pick: dict[str, Any], spare: bool = False) -> str:
    tier = f"[{pick['tier']}] " if spare else ""
    key = f", {pick['key']}" if pick["key"] else ""
    return f"  {n:>2}. {tier}{pick['track']} ({pick['bpm']} BPM{key}): {pick['reason']}"


def _crate_preview_lines(found: crate_mod.CratePreview) -> list[str]:
    data = found.to_dict(limit=len(found.picks))  # a terminal shows every pick
    c = data["counts"]
    lines = [
        f"crate:       {data['name']} ({data['crate']}), {c['picks']} picks + {c['spares']} spares, "
        f"curve {data['curve']}",
        f"spec:        {data['spec']} ({data['filters']})",
        f"tracks from: {data['export']}",
        f"taste from:  {data['taste']}",
        f"counts:      {c['candidates']} candidates, {c['vetoed']} vetoed, {c['never_pair']} never-pair, "
        f"{c['duplicates']} duplicates, {c['tracks']} tracks",
        f"playlists:   {', '.join(data['playlists'])}",
        "",
        "picks:",
        *[_pick_line(p["n"], p) for p in data["picks"]],
        "spares:",
        *[_pick_line(p["n"], p, spare=True) for p in data["spares"]],
    ]
    lines += [f"WARNING {w}" for w in data["warnings"]]
    lines += ["", "Nothing written yet."]
    if data["blocked"]:
        lines.append(f"BLOCKED {data['blocked']}")
    else:
        lines.append(f"preview id:  {data['preview_id']}")
        lines.append(
            f"to write:    dj library crate {data['crate']} --apply --preview-id {data['preview_id']} "
            "(only after the DJ said yes)"
        )
    return lines


def _crate_apply_lines(data: dict[str, Any]) -> list[str]:
    c = data["counts"]
    lines = [
        f"Wrote {data['written']} ({c['picks']} picks, {c['spares']} spares). rekordbox untouched until you import it.",
    ]
    if data["record"]:
        lines.append(f"Crate record: {data['record']}")
    lines.append(f"Import in rekordbox ({data['device']}):")
    lines += [f"  {n}. {step}" for n, step in enumerate(data["import_steps"], 1)]
    lines.append(f"log.md: {data['log_line']}")
    lines += [f"WARNING {w}" for w in data["warnings"]]
    return lines


@library_app.command("crate")
def crate_cmd(
    spec: str = typer.Argument(..., help="The crate's slug, or the path of crates/<slug>.spec.yaml."),
    library: str = typer.Option(None, "--library", help="The dj-library folder. Default: the configured one."),
    apply: bool = typer.Option(False, "--apply", help="Write proposals/crate-<slug>.xml. Needs --preview-id."),
    preview_id: str = typer.Option(None, "--preview-id", help="The id the preview printed, after the DJ's yes."),
    today: str = typer.Option(None, "--today", help="Date written into crates/<slug>.md (YYYY-MM-DD)."),
    picks_limit: int = typer.Option(crate_mod.PICKS_LIMIT, "--picks-limit", min=0,
                                    help="Picks listed in the preview JSON; 0 = all (the MCP tool pages them)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Preview a crate from crates/<slug>.spec.yaml (picks with a reason each, spares by energy),
    or with --apply and the preview id write proposals/crate-<slug>.xml and crates/<slug>.md
    for the DJ to import. Never opens master.db."""
    if apply and not (preview_id or "").strip():
        _refuse("--apply needs --preview-id: run the preview, show it, write only after a yes.")
    try:
        day = date.fromisoformat(today) if today else None
    except ValueError:
        _fail(f"--today: expected YYYY-MM-DD, got {today!r}")
    try:
        root = Path(library) if library else libfolder.configured_root()
        if not root.is_dir():
            _fail(f"{root} is not a folder. Scaffold the dj-library folder first (dj-start).")
        if apply:
            data = crate_mod.apply(root, spec, (preview_id or "").strip(), today=day).to_dict()
            text = _crate_apply_lines(data)
        else:
            found = crate_mod.preview(root, spec, today=day)
            data = found.to_dict(picks_limit)
            text = _crate_preview_lines(found)
    except GateError as exc:
        _refuse(str(exc))
    except (crate_mod.CrateError, build_structure.BuildError, LibraryError, OSError) as exc:
        _fail(str(exc))
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False) if as_json else "\n".join(text))
