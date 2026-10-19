"""dj: manage a rekordbox playlist tree from files."""

from __future__ import annotations

import json
import re
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import typer

from dj import analyze as analyze_mod
from dj import build as build_mod
from dj import intake, library, safety, spotify
from dj import playlist_copy as copy_mod
from dj import push as push_mod
from dj import tree as tree_mod
from dj.tidy import TidyError
from dj.tidy import checks as tidy_checks
from dj.tidy import config as tidy_config
from dj.tidy import dupes as tidy_dupes
from dj.tidy import plan as tidy_plan
from dj.tidy import report as tidy_report
from dj.tidy import scan as tidy_scan
from dj.tree import KIND_BY_ATTRIBUTE, children_of

# show_locals stays off: a traceback must never print a token or the client secret.
app = typer.Typer(
    add_completion=False, no_args_is_help=True, help=__doc__, pretty_exceptions_show_locals=False
)

EXIT_ERROR = 1
EXIT_REKORDBOX_RUNNING = 2


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


def print_tree(db: Any, smart_xml: bool = False, parent_id: str = "root", depth: int = 0) -> None:
    for node in children_of(db, parent_id):
        kind = KIND_BY_ATTRIBUTE.get(node.Attribute, f"attr={node.Attribute}")
        extra = f"  ({len(node.Songs)} tracks)" if kind == "playlist" else ""
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
            entry["tracks"] = len(node.Songs)
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


@app.command()
def status(
    smart_xml: bool = typer.Option(
        False, "--smart-xml", help="Print the raw rule XML of existing smart playlists."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Read-only: track count, playlist tree, rekordbox version, state of every link."""
    db_path = safety.find_master_db()
    data: dict[str, Any] = {
        "master_db": str(db_path),
        "rekordbox": rekordbox_version(db_path),
        "pyrekordbox": version("pyrekordbox"),
        "running": safety.rekordbox_running(),
    }
    with safety.open_db(write=False, db_path=db_path) as db:
        data["tracks"] = db.get_content().count()
        data["links"] = links_data(db, intake.Paths())
        if as_json:
            data["tree"] = tree_data(db)
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
            return
        typer.echo(f"master.db:     {data['master_db']}")
        typer.echo(f"rekordbox:     {data['rekordbox'] or 'unknown'}")
        typer.echo(f"pyrekordbox:   {data['pyrekordbox']}")
        typer.echo(f"running:       {'YES' if data['running'] else 'no'}")
        typer.echo(f"tracks:        {data['tracks']}")
        typer.echo("")
        typer.echo("playlist tree:")
        print_tree(db, smart_xml=smart_xml)
    typer.echo("")
    typer.echo("links:" if data["links"] else "links:         none (links.yaml)")
    for link in data["links"]:
        typer.echo(f"  {link['spotify']} -> {link['crate']}")
        if "counts" in link:
            typer.echo("    " + ", ".join(f"{n} {s}" for s, n in link["counts"].items()))
        if "note" in link:
            typer.echo(f"    {link['note']}")
        typer.echo(f"    last pull {link.get('last_pull') or 'never'}, "
                   f"last apply {link.get('last_apply') or 'never'}")


def _print_plan(actions: list[tree_mod.Action]) -> dict[str, int]:
    for action in actions:
        typer.echo(action.line())
    totals = tree_mod.counts(actions)
    typer.echo("")
    typer.echo(", ".join(f"{n} {op}" for op, n in totals.items()))
    return totals


@app.command()
def tree(
    apply: bool = typer.Option(False, "--apply", help="Really write. Default is a dry-run."),
    file: Path = typer.Option(Path("tree.yaml"), "--file", help="The tree file."),
    allow_uncalibrated: bool = typer.Option(
        False,
        "--allow-uncalibrated",
        help="Also create smart playlists whose rule encoding is unconfirmed (default: HOLD).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Create what is missing from tree.yaml. Never changes what exists."""
    try:
        nodes = tree_mod.load_tree(file)
    except (tree_mod.TreeError, OSError) as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(EXIT_ERROR)

    # Pass 1, read-only: the plan.
    def plan(db: Any) -> list[tree_mod.Action]:
        actions = tree_mod.walk(nodes, db)
        return actions if allow_uncalibrated else tree_mod.hold_uncalibrated(actions)

    with safety.open_db(write=False) as db:
        actions = plan(db)
    if as_json:
        if apply:
            typer.echo("ERROR --json is for the dry-run; apply without it.", err=True)
            raise typer.Exit(EXIT_ERROR)
        rows = [{"op": a.op, "kind": a.kind, "path": list(a.path), "note": a.note} for a in actions]
        typer.echo(json.dumps({"counts": tree_mod.counts(actions), "actions": rows}, indent=2))
        return
    totals = _print_plan(actions)
    if totals[tree_mod.HOLD]:
        typer.echo("HOLD = not created until its encoding is confirmed (see README).")

    if totals[tree_mod.CONFLICT]:
        typer.echo("CONFLICT found. Nothing written.", err=True)
        raise typer.Exit(EXIT_ERROR)
    if not apply:
        typer.echo("DRY-RUN. Nothing written. Re-run with --apply.")
        return
    if not totals[tree_mod.CREATE]:
        typer.echo("Nothing to create. Nothing written.")
        return

    # Pass 2, the write: re-plan inside the write session, create, one commit.
    try:
        with safety.open_db(write=True) as db:
            created = tree_mod.apply(plan(db), db)
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    typer.echo(f"APPLIED. Created {created} node(s) in one commit. Backup in backups/.")

    typer.echo("")
    typer.echo("final tree:")
    with safety.open_db(write=False) as db:
        print_tree(db)


@app.command()
def push(
    playlist: str = typer.Argument(..., help="rekordbox playlist, e.g. 'funk_base/funk_crate'."),
    name: str = typer.Option(None, "--name", help="Spotify playlist name. Default: same name."),
    apply: bool = typer.Option(False, "--apply", help="Really write to Spotify. Default: dry-run."),
    include_ambiguous: bool = typer.Option(
        False, "--include-ambiguous", help="Also add the best pick of AMBIGUOUS tracks."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Copy a rekordbox playlist to a private Spotify playlist. Adds only, never removes."""
    try:
        with safety.open_db(write=False) as db:
            row = push_mod.find_playlist(db, playlist)
            rb_id, rb_name = str(row.ID), row.Name
            tracks = push_mod.local_tracks(row)
        scopes = spotify.WRITE_SCOPES if apply else spotify.READ_SCOPES
        api = spotify.Spotify(spotify.get_token(scopes))
        results = [push_mod.match_track(api, t) for t in tracks]
        uris = push_mod.selected_uris(results, include_ambiguous)
        totals = {s: sum(r.status == s for r in results) for s in ("MATCH", "AMBIGUOUS", "MISSING")}
        payload: dict[str, Any] = {
            "rekordbox_playlist": playlist,
            "spotify_name": name or rb_name,
            "applied": False,
            "counts": totals,
            "selected": len(uris),
            "items": [push_mod.result_dict(r) for r in results],
        }
        if apply and uris:
            payload["result"] = push_mod.apply(api, rb_id, name or rb_name, uris)
            payload["applied"] = True
            payload["report"] = str(push_mod.write_report(name or rb_name, payload))
    except (push_mod.PushError, spotify.SpotifyError) as exc:
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
    elif apply:
        typer.echo("Nothing to add. Nothing written.")
    else:
        typer.echo(f"DRY-RUN. Would put {len(uris)} track(s) on Spotify. Re-run with --apply.")


@app.command()
def build(
    tracklist: Path = typer.Argument(..., help="Text file, one 'Artist - Title (Mix)' per line."),
    name: str = typer.Option(None, "--name", help="Spotify playlist name. Default: the file name."),
    apply: bool = typer.Option(False, "--apply", help="Really write to Spotify. Default: dry-run."),
    include_ambiguous: bool = typer.Option(
        False, "--include-ambiguous", help="Also add the best pick of AMBIGUOUS tracks."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """A text tracklist -> a private Spotify playlist. rekordbox untouched. Adds only."""
    try:
        tracks, skipped = build_mod.load_tracklist(tracklist)
        name = name or build_mod.default_name(tracklist)
        scopes = spotify.WRITE_SCOPES if apply else spotify.READ_SCOPES
        api = spotify.Spotify(spotify.get_token(scopes))
        results = build_mod.match_all(api, tracks)
        uris = push_mod.selected_uris(results, include_ambiguous)
        totals = {s: sum(r.status == s for r in results) for s in ("MATCH", "AMBIGUOUS", "MISSING")}
        payload: dict[str, Any] = {
            "tracklist": str(tracklist),
            "spotify_name": name,
            "applied": False,
            "counts": totals,
            "selected": len(uris),
            "skipped_lines": skipped,
            "items": [push_mod.result_dict(r) for r in results],
        }
        if apply and uris:
            payload["result"] = build_mod.apply(api, name, uris)
            payload["applied"] = True
            payload["report"] = str(push_mod.write_report(name, payload, kind="build"))
    except (build_mod.BuildError, push_mod.PushError, spotify.SpotifyError) as exc:
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
    elif apply:
        typer.echo("Nothing to add. Nothing written.")
    else:
        typer.echo(f"DRY-RUN. Would put {len(uris)} track(s) on Spotify. Re-run with --apply.")


# -- Phase 2: Spotify inbox -> rekordbox crate -------------------------------------------


def _fail(exc: Exception) -> None:
    typer.echo(f"ERROR {exc}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _out(as_json: bool, payload: dict[str, Any], lines: list[str]) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False) if as_json else "\n".join(lines))


INTAKE_ERRORS = (intake.IntakeError, library.LibraryError, spotify.SpotifyError)


@app.command()
def pull(
    link: str = typer.Argument(None, help="A link from links.yaml (its spotify or crate value)."),
    all_links: bool = typer.Option(False, "--all", help="Pull every link."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Spotify playlist -> inbox/<crate>.json. Read-only on both sides."""
    paths = intake.Paths()
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
    paths = intake.Paths()
    link = intake.resolve_link(link_arg, paths)
    with safety.open_db(write=False) as db:
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
    paths = intake.Paths()
    try:
        lnk, items, in_crate = _match(link)
        plan_path = intake.write_plan(lnk, items, in_crate, paths)
        wish_path = intake.write_wishlist(lnk, items, paths)
    except INTAKE_ERRORS as exc:
        _fail(exc)
    payload = {"plan": str(plan_path), "wishlist": str(wish_path), "counts": intake.counts(items)}
    _out(as_json, payload, [f"plan:     {plan_path}", f"wishlist: {wish_path}",
                            "Set decision (yes/no) and, for AMBIGUOUS, pick. Then: dj apply <plan>"])


@app.command(name="apply")
def apply_plan(
    plan_file: Path = typer.Argument(..., help="A plan file from `dj plan`."),
    apply: bool = typer.Option(False, "--apply", help="Really write. Default is a dry-run."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Add the `decision: yes` tracks of a plan to its crate. Appends only."""
    paths = intake.Paths()
    try:
        plan_data = intake.load_plan(plan_file)
        by = intake.decisions(plan_data)
        with safety.open_db(write=False) as db:
            crate = library.find_playlist(db, plan_data["crate"])
            adds = intake.to_add(plan_data, library.crate_content_ids(crate))
        payload: dict[str, Any] = {
            "crate": plan_data["crate"], "applied": False, "would_add": len(adds),
            "yes": len(by["yes"]), "no": len(by["no"]), "pending": len(by["pending"]),
            "adds": [i["spotify"] for i in adds],
        }
        lines = [f"ADD  {i['spotify']}  -> {i['pick']}" for i in adds]
        lines.append(f"{len(adds)} to add, {len(by['yes']) - len(adds)} yes already in crate, "
                     f"{len(by['no'])} no, {len(by['pending'])} pending")
        if not apply:
            lines.append("DRY-RUN. Nothing written. Re-run with --apply.")
        else:
            added: list[dict[str, Any]] = []
            if adds:  # no backup, no write session when there is nothing to add
                with safety.open_db(write=True) as db:
                    added = intake.add_to_crate(db, plan_data)
            report = intake.record(plan_data, plan_file, added, paths)
            payload |= {"applied": True, "added": len(added), "report": str(report)}
            lines.append(f"APPLIED. Added {len(added)} track(s) to '{plan_data['crate']}'.")
            lines.append(f"report: {report}")
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    except INTAKE_ERRORS as exc:
        _fail(exc)
    _out(as_json, payload, lines)


# -- rekordbox playlist -> rekordbox playlist --------------------------------------------


@app.command(name="copy")
def copy_playlist(
    source: str = typer.Argument(..., help="rekordbox playlist to read, e.g. 'jazzy_relevations'."),
    target: str = typer.Argument(..., help="Playlist to append to, e.g. 'jazz_base/2.1_jazzy_relevations'."),
    apply: bool = typer.Option(False, "--apply", help="Really write. Default is a dry-run."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Append the tracks of one rekordbox playlist to another. Adds only, never removes."""
    try:
        with safety.open_db(write=False) as db:
            planned = copy_mod.plan(db, source, target, allow_missing_target=not apply)
        payload: dict[str, Any] = planned.as_dict() | {"applied": False}
        totals = planned.counts()
        lines = [r.line() for r in planned.rows]
        lines += ["", f"{totals[copy_mod.ADD]} to add, {totals[copy_mod.SKIP]} skipped  "
                      f"({source} -> {target})"]
        if not planned.target_exists:
            lines.append(f"Target '{target}' does not exist yet. Create it first (dj tree).")
        if not apply:
            lines.append("DRY-RUN. Nothing written. Re-run with --apply.")
        elif not planned.adds:  # no backup, no write session when there is nothing to add
            lines.append("Nothing to add. Nothing written.")
        else:
            with safety.open_db(write=True) as db:
                done = copy_mod.apply(db, source, target)
            report = copy_mod.write_report(done)
            payload = done.as_dict() | {"applied": True, "added": len(done.adds),
                                        "report": str(report)}
            lines.append(f"APPLIED. Added {len(done.adds)} track(s) to '{target}'. "
                         "Backup in backups/.")
            lines.append(f"report: {report}")
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    except (copy_mod.CopyError, library.LibraryError) as exc:
        _fail(exc)
    _out(as_json, payload, lines)


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
         "Reads master.db read-only, never writes it. Afterwards: Reload Tag in rekordbox.",
)
app.add_typer(tidy_app, name="tidy")
TIDY_ERRORS = (TidyError, library.LibraryError)

_CRATE_ARG = typer.Argument(None, help="rekordbox playlist path, e.g. house_base/0_INBOX.")
_FOLDER_OPT = typer.Option(None, "--folder", help="A folder on disk (inside tidy.yaml roots) instead of a crate.")
_ALL_OPT = typer.Option(False, "--all", help="The whole rekordbox collection.")
_CONFIG_OPT = typer.Option(str(tidy_config.DEFAULT_PATH), "--config", help="tidy.yaml to use.")
_HASH_OPT = typer.Option("collisions", "--hash", help="Hash files for exact duplicates: collisions (same size only), all, none.")


def _tail(text: str, n: int = 60) -> str:
    return text if len(text) <= n else "..." + text[-n:]


def _tidy_scan(crate: str | None, folder: str | None, all_tracks: bool, config: str, hash_mode: str) -> tuple:
    cfg = tidy_config.load_config(config)
    target = tidy_scan.resolve_target(crate, folder, all_tracks, cfg)
    with safety.open_db(write=False) as db:
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
        written = None if no_report else tidy_report.write_audit(audit_d, intake.Paths())
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
    if written:
        payload["reports"] = [str(p) for p in written]
        lines += [f"report: {written[1]}", f"json:   {written[0]}"]
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
        path = tidy_plan.write_plan(plan, intake.Paths())
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
    lines += [f"plan: {path}", "Set decision yes/no per item, then: dj tidy apply <plan> (dry-run), --apply to write."]
    _out(as_json, {"plan": str(path), "counts": c, "target": target.as_dict(),
                   "items": [i for i in plan["items"] if i["changes"] or i["rename"]], "skipped": skipped}, lines)


def _refuse_if_rekordbox_runs() -> None:
    if safety.rekordbox_running():
        raise safety.RekordboxRunningError(
            f"{safety.PROCESS_NAME} is running. Close rekordbox before writing audio files; it may hold them open "
            "and it must Reload Tag afterwards anyway.")


@tidy_app.command(name="apply")
def tidy_apply(
    plan_file: str = typer.Argument(..., help="plans/<date>-tidy-<target>.plan.json"),
    apply: bool = typer.Option(False, "--apply", help="Really write the tags / rename. Default is a dry-run."),
    strict: bool = typer.Option(False, "--strict", help="Any item that cannot run aborts the whole apply before the first write."),
    config: str = _CONFIG_OPT,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Write the `decision: yes` tag changes into the files (undo record first, temp + atomic replace).
    master.db is never touched: afterwards select the tracks in rekordbox and Reload Tag."""
    try:
        cfg = tidy_config.load_config(config)
        plan = tidy_plan.load_plan(plan_file)
        if apply:
            _refuse_if_rekordbox_runs()
        result = tidy_plan.apply_plan(plan, Path(plan_file), cfg, intake.Paths(), strict=strict, dry_run=not apply)
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    except TIDY_ERRORS as exc:
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
        lines.append("DRY-RUN. Nothing written. Re-run with --apply.")
    else:
        lines.append(f"APPLIED. Undo: dj tidy undo {plan_file} --apply  (records in {result.undo_path})")
        lines.append("In rekordbox: select these tracks -> right-click -> Reload Tag.")
        if result.relocate_path:
            lines.append(f"Renamed files rekordbox knows: Relocate each one, checklist {result.relocate_path}")
        if result.report_path:
            lines.append(f"report: {result.report_path}")
    _out(as_json, result.as_dict(), lines)
    if result.failed or (strict and result.skipped):
        raise typer.Exit(EXIT_ERROR)


@tidy_app.command(name="undo")
def tidy_undo(
    plan_file: str = typer.Argument(..., help="The plan whose apply should be reverted."),
    apply: bool = typer.Option(False, "--apply", help="Really restore. Default is a dry-run."),
    force: bool = typer.Option(False, "--force", help="Restore even if the file changed after the apply."),
    config: str = _CONFIG_OPT,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Put the tags (and names) back from state/tidy/<plan>.undo.json, newest change first."""
    try:
        cfg = tidy_config.load_config(config)
        plan = tidy_plan.load_plan(plan_file)
        if apply:
            _refuse_if_rekordbox_runs()
        result = tidy_plan.undo_plan(plan, Path(plan_file), cfg, intake.Paths(), dry_run=not apply, force=force)
    except safety.RekordboxRunningError as exc:
        typer.echo(f"STOP {exc}", err=True)
        raise typer.Exit(EXIT_REKORDBOX_RUNNING)
    except TIDY_ERRORS as exc:
        _fail(exc)
    verb = "RESTORED" if apply else "WOULD   "
    lines = [f"{verb} {_tail(r['file_before'])}" for r in result.restored]
    lines += [f"SKIP     {_tail(r['file_before'])}  [{why}]" for r, why in result.skipped]
    lines += [f"FAILED   {_tail(r['file_before'])}  [{why}]" for r, why in result.failed]
    c = result.as_dict()["counts"]
    lines += ["", f"{c['restored']} {'restored' if apply else 'to restore'}, {c['skipped']} skipped, {c['failed']} failed"]
    lines.append("DRY-RUN. Nothing written. Re-run with --apply." if not apply
                 else "UNDONE. In rekordbox: select these tracks -> Reload Tag.")
    _out(as_json, result.as_dict(), lines)
    if result.failed:
        raise typer.Exit(EXIT_ERROR)


if __name__ == "__main__":
    app()
