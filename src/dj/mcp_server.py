"""MCP server: lets an agent that cannot run Windows programs (Claude Cowork) use the dj CLI.

It is NOT a shell. Every tool runs one fixed `dj` command with --json, as a list of
arguments (no shell, no string building), so every rule in CLAUDE.md still holds:
dry-run by default, verified backup, refusal while rekordbox runs, add only.

Read tools and write tools are separate on purpose: in Claude Desktop, read tools can be
set to "always allow" while every write keeps asking for approval.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from dj import libfolder
from dj.gate import valid_id
from dj.safety import REPO_ROOT
from dj.tidy import TidyError
from dj.tidy import config as tidy_config

TIMEOUT_S = 600
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
SPOTIFY_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True)
LIBRARY_TEXT = ToolAnnotations(readOnlyHint=False, destructiveHint=False)  # text files in dj-library/

server = MCPServer(
    "dj-librarian",
    instructions=(
        "Tools for the DJ's rekordbox library via the dj CLI. rekordbox is the truth; you only "
        "propose. Read STATE.md and the dj-sync skill first. Always call the preview tool and "
        "show the DJ the result before any *_apply / *_write tool, and only call those after their "
        "explicit OK. exit_code 2 = refused: the `hint` says why. Usually rekordbox is open: ask "
        "them to close it, then retry the same call; a library folder that is not set up needs "
        "dj-start first. Never ask for a way around a refusal. The dj_tidy_* tools work on the audio files "
        "(tags, names), never on master.db: after dj_tidy_apply they must Reload Tag in rekordbox."
    ),
)


class ToolInputError(ValueError):
    pass


def repo_file(path: str, suffixes: tuple[str, ...]) -> str:
    """A file argument must be an existing file inside the repo, of an expected type."""
    candidate = Path(path)
    full = (candidate if candidate.is_absolute() else REPO_ROOT / candidate).resolve()
    if not full.is_relative_to(REPO_ROOT.resolve()):
        raise ToolInputError(f"{path!r} is outside the dj-librarian folder.")
    if full.suffix.lower() not in suffixes:
        raise ToolInputError(f"{path!r}: expected one of {', '.join(suffixes)}.")
    if not full.is_file():
        raise ToolInputError(f"{path!r} does not exist.")
    return str(full)


def library_root() -> Path:
    """The configured dj-library folder (dj.libfolder.configured_root): DJ_LIBRARY, else the
    folder stored by remember_root, else <repo>/dj-library. A folder too wide to be a library
    (a drive root, the home folder) is refused."""
    try:
        return libfolder.configured_root()
    except libfolder.LibraryFolderError as exc:
        raise ToolInputError(str(exc)) from exc


def library_file(path: str, suffixes: tuple[str, ...]) -> str:
    """Like repo_file, but a file inside the configured library folder is accepted too.
    A relative path is looked up in the library folder first, then in the repo."""
    roots = [library_root().resolve(), REPO_ROOT.resolve()]
    candidate = Path(path)
    options = [candidate] if candidate.is_absolute() else [root / candidate for root in roots]
    inside = [p.resolve() for p in options if any(p.resolve().is_relative_to(r) for r in roots)]
    if not inside:
        raise ToolInputError(f"{path!r} is outside the dj-library folder and the dj-librarian folder.")
    if Path(path).suffix.lower() not in suffixes:
        raise ToolInputError(f"{path!r}: expected one of {', '.join(suffixes)}.")
    for full in inside:
        if full.is_file() and full.suffix.lower() in suffixes:
            return str(full)
    raise ToolInputError(f"{path!r} does not exist (looked in {', '.join(str(r) for r in roots)}).")


def music_folder(path: str) -> str:
    """A folder argument must be an existing directory inside a tidy.yaml root."""
    full = Path(path).resolve()
    if not full.is_dir():
        raise ToolInputError(f"{path!r} is not a directory.")
    try:
        cfg = tidy_config.load_config()
    except TidyError as exc:
        raise ToolInputError(str(exc)) from exc
    if not tidy_config.folder_in_roots(full, cfg):
        roots = ", ".join(str(r) for r in cfg.roots)
        raise ToolInputError(f"{path!r} is outside the tidy.yaml roots ({roots}).")
    return str(full)


def tidy_target(crate: str, folder: str, all_tracks: bool) -> tuple[list[str], tuple[str, ...]]:
    """Exactly one target -> (options before `--`, positionals after it)."""
    if sum(bool(x) for x in (crate, folder, all_tracks)) != 1:
        raise ToolInputError("Give exactly one of crate, folder, all_tracks.")
    if all_tracks:
        return ["--all"], ()
    if folder:
        return ["--folder", music_folder(folder)], ()
    return [], (crate,)


MAC_PATH_DIRS = ("/usr/bin", "/bin")  # pgrep lives in /usr/bin


def host_env() -> dict[str, str]:
    """MCP clients start servers with a stripped environment; fill in what the dj process needs.

    Windows: pyrekordbox needs %ProgramFiles% and %APPDATA% to find rekordbox, tasklist needs
    %SystemRoot%. macOS: pyrekordbox and the master.db default live under HOME, and PATH gets
    /usr/bin and /bin. Any other OS: the environment as it is."""
    env = dict(os.environ)
    if sys.platform == "win32":
        home = Path.home()
        defaults = {
            "ProgramFiles": r"C:\Program Files",
            "SystemRoot": r"C:\Windows",
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "USERPROFILE": str(home),
        }
        present = {k.upper() for k in env}
        return env | {k: v for k, v in defaults.items() if k.upper() not in present}
    if sys.platform == "darwin":
        if not env.get("HOME"):
            env["HOME"] = str(Path.home())
        dirs = [d for d in env.get("PATH", "").split(":") if d]
        env["PATH"] = ":".join(dirs + [d for d in MAC_PATH_DIRS if d not in dirs])
    return env


def run_dj(options: list[str], positionals: tuple[str, ...] = (), as_json: bool = True) -> str:
    """Run `python -m dj.cli <options> [--json] -- <positionals>` and wrap the outcome."""
    cmd = [sys.executable, "-m", "dj.cli", *options]
    if as_json:
        cmd.append("--json")
    if positionals:
        cmd += ["--", *positionals]  # a value can never be read as an option
    env = host_env() | {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        done = subprocess.run(
            cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", stdin=subprocess.DEVNULL, timeout=TIMEOUT_S,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "exit_code": None, "error": f"timed out after {TIMEOUT_S}s"})

    out: dict[str, Any] = {"ok": done.returncode == 0, "exit_code": done.returncode}
    try:
        out["result"] = json.loads(done.stdout)
    except ValueError:
        out["output"] = done.stdout.strip()
    noise = ("Rekordbox is running!",)
    stderr = [l for l in done.stderr.splitlines() if l.strip() and not any(n in l for n in noise)]
    if stderr:
        out["stderr"] = stderr[-15:]
    if done.returncode == 2:
        out["hint"] = refusal_hint(stderr)
    return json.dumps(out, indent=2, ensure_ascii=False)


REKORDBOX_OPEN = "rekordbox is open. Ask the DJ to close it, then call this tool again."
NO_LIBRARY = (
    "The dj-library folder is not set up (no valid library.yaml). This is not rekordbox: calling "
    "this tool again will not help. Set the folder up with dj-start first."
)
REFUSED_OTHER = "Refused, see stderr. This is not rekordbox: calling this tool again will not help."


def refusal_hint(stderr: list[str]) -> str:
    """What exit code 2 means for this run. The `dj library` commands print `REFUSED <reason>`
    when the library folder is not one they write into; the rekordbox process check prints
    `STOP ...`. Only the latter is solved by closing rekordbox and retrying."""
    refused = next((line for line in stderr if line.startswith("REFUSED")), None)
    if refused is None:
        return REKORDBOX_OPEN
    if "library.yaml" in refused:
        return NO_LIBRARY
    return REFUSED_OTHER


def guarded(func: Any) -> Any:
    """Bad input is an answer for the agent, not a crash of the server."""

    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return func(*args, **kwargs)
        except ToolInputError as exc:
            return json.dumps({"ok": False, "exit_code": 1, "error": str(exc)})

    wrapper.__name__, wrapper.__doc__ = func.__name__, func.__doc__
    wrapper.__annotations__ = func.__annotations__
    wrapper.__wrapped__ = func
    return wrapper


# -- read-only ---------------------------------------------------------------------------


@server.tool(annotations=READ)
def dj_status() -> str:
    """Library overview: track count, the full playlist tree, whether rekordbox is running,
    and per link in links.yaml the counts by status, last pull and last apply. Read-only."""
    return run_dj(["status"])


@server.tool(annotations=READ)
@guarded
def dj_tree_preview(file: str = "tree.yaml") -> str:
    """Dry-run of a tree file (e.g. bases.yaml): one action per node - CREATE, SKIP, HOLD,
    CONFLICT. Writes nothing. `file` is a .yaml path inside the repo."""
    return run_dj(["tree", "--file", repo_file(file, (".yaml", ".yml"))])


@server.tool(annotations=READ)
@guarded
def dj_library_inspect(xml: str = "") -> str:
    """Library summary from one model: source, counts (tracks, folders, playlists, smart,
    orphans, entries; complete), a sample of the top of the playlist tree (at most 30 nodes and
    10 child names each; `tree_more` / `more_children` count the rest), which fields the source
    lacks, and notes. `xml` = a rekordbox collection XML inside the dj-library folder or the repo
    (e.g. exports/2026-10-20-collection.xml); empty = a read-only snapshot of master.db
    (`snapshot_path` = the copy that was read). Writes nothing."""
    if xml:
        return run_dj(["library", "inspect"], (library_file(xml, (".xml",)),))
    return run_dj(["library", "inspect"])


ANALYZE_SOURCES = ("xml", "db")


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
@guarded
def dj_library_analyze(source: str = "xml") -> str:
    """Analyse the DJ's library in one go and render the HTML report: reads the library once
    (source "xml" = the latest export in the dj-library folder; "db" = a read-only snapshot of
    master.db), then writes profile/, structure/ (incl. proposals.yaml with 2-3 restructure
    proposals), taste/ and reports/<date>-library.html, plus log.md lines. Text files in the
    configured dj-library folder only; rekordbox, Spotify and audio files are never written.
    Returns counts first, the report path, the proposals (trigger, cost) and any failed step.
    It always rebuilds structure/proposals.yaml (an edited copy is kept first): after renaming a
    proposal, render with the dj-report script instead. exit_code 2 = refused, see `hint`."""
    if source not in ANALYZE_SOURCES:
        raise ToolInputError(f"source must be one of {', '.join(ANALYZE_SOURCES)}, got {source!r}.")
    return run_dj(["library", "analyze", "--source", source])


@server.tool(annotations=SPOTIFY_READ)
def dj_pull(link: str = "", all_links: bool = False) -> str:
    """Download a Spotify inbox playlist to inbox/<crate>.json. Read-only on Spotify and
    rekordbox. `link` = the spotify or crate value of an entry in links.yaml."""
    if all_links:
        return run_dj(["pull", "--all"])
    return run_dj(["pull"], (link,))


@server.tool(annotations=READ)
def dj_match(link: str) -> str:
    """Match the last pull of a link against the library: IN_CRATE, PROPOSE, AMBIGUOUS
    (with up to 3 local candidates each), MISSING, DECLINED. Writes nothing."""
    return run_dj(["match"], (link,))


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def dj_plan(link: str) -> str:
    """Write plans/<date>-<crate>.plan.json and wishlist/<crate>.md (files in the repo only,
    rekordbox untouched). Returns the paths. Then edit the plan: decision yes|no, and for
    AMBIGUOUS a pick (rb_content_id from its candidates)."""
    return run_dj(["plan"], (link,))


@server.tool(annotations=READ)
@guarded
def dj_apply_preview(plan_file: str) -> str:
    """Dry-run of a plan: which `decision: yes` tracks would be added to the crate."""
    return run_dj(["apply"], (repo_file(plan_file, (".json",)),))


@server.tool(annotations=READ)
def dj_copy_preview(source: str, target: str) -> str:
    """Dry-run: which tracks of rekordbox playlist `source` would be appended to `target`."""
    return run_dj(["copy"], (source, target))


@server.tool(annotations=SPOTIFY_READ)
@guarded
def dj_build_preview(file: str, name: str = "") -> str:
    """Dry-run: match every 'Artist - Title' line of a tracklist file (tracklists/<name>.txt
    in the repo) on Spotify: MATCH, AMBIGUOUS, MISSING. rekordbox untouched, writes nothing."""
    options = ["build"] + (["--name", name] if name else [])
    return run_dj(options, (repo_file(file, (".txt", ".md")),))


@server.tool(annotations=SPOTIFY_READ)
def dj_push_preview(playlist: str) -> str:
    """Dry-run: match a rekordbox playlist on Spotify (MATCH, AMBIGUOUS, MISSING)."""
    return run_dj(["push"], (playlist,))


# -- writes: only after the DJ's explicit OK ----------------------------------------------


@server.tool(annotations=WRITE)
@guarded
def dj_tree_apply(file: str = "tree.yaml") -> str:
    """WRITES to rekordbox: create the missing folders/playlists of a tree file. Backup
    first, one commit, refuses while rekordbox is open (exit_code 2). Never changes or
    deletes what exists. Call dj_tree_preview first and get the DJ's OK."""
    return run_dj(["tree", "--file", repo_file(file, (".yaml", ".yml")), "--apply"], as_json=False)


@server.tool(annotations=WRITE)
@guarded
def dj_apply_write(plan_file: str) -> str:
    """WRITES to rekordbox: append the `decision: yes` tracks of a plan to its crate.
    Backup first, one commit, exit_code 2 while rekordbox is open. Then updates
    state/match_cache.json, state/declined.json and writes a report."""
    return run_dj(["apply", "--apply"], (repo_file(plan_file, (".json",)),))


@server.tool(annotations=WRITE)
def dj_copy_apply(source: str, target: str) -> str:
    """WRITES to rekordbox: append the tracks of playlist `source` to `target` (skips
    tracks already there). Backup first, one commit, exit_code 2 while rekordbox is open."""
    return run_dj(["copy", "--apply"], (source, target))


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
@guarded
def dj_build_apply(file: str, name: str = "", include_ambiguous: bool = False) -> str:
    """WRITES to Spotify: create (once) a private playlist from a tracklist file and add the
    MATCH tracks. Only ever adds. Call dj_build_preview first and get the DJ's OK."""
    options = ["build", "--apply"] + (["--name", name] if name else [])
    if include_ambiguous:
        options.append("--include-ambiguous")
    return run_dj(options, (repo_file(file, (".txt", ".md")),))


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
def dj_push_apply(playlist: str, name: str = "", include_ambiguous: bool = False) -> str:
    """WRITES to Spotify: create (once) a private playlist for a rekordbox playlist and add
    the MATCH tracks. Only ever adds. `include_ambiguous` only if the DJ checked the links."""
    options = ["push", "--apply"]
    if name:
        options += ["--name", name]
    if include_ambiguous:
        options.append("--include-ambiguous")
    return run_dj(options, (playlist,))


# -- dj-build: a proposal -> rekordbox XML the DJ imports (R-501..R-505) -------------------


def _proposal(proposal: str) -> str:
    if not isinstance(proposal, str) or not proposal.strip():
        raise ToolInputError("Name the proposal: its slug, its name, or 'Build me the <name> structure'.")
    return proposal.strip()


@server.tool(annotations=LIBRARY_TEXT)
@guarded
def dj_structure_preview(proposal: str) -> str:
    """Preview a structure proposal from the dj-library folder: CREATE / SKIP / CONFLICT /
    MANUAL per node against structure/current-tree.yaml, where existing playlists land, counts,
    and a preview_id. `proposal` = its slug, its name, or "Build me the <name> structure".
    Writes only proposals/<slug>.yaml (if missing; an existing one is the DJ's and is read as
    it is) and the preview record. No XML, rekordbox and master.db untouched. Show the DJ the
    result and ask "Write the XML?" before dj_structure_write. A `blocked` result has no
    preview_id (a conflict, nothing to create, current-tree.yaml older than the export, or this
    exact build already written)."""
    root = str(library_root())
    return run_dj(["library", "build", "--library", root], (_proposal(proposal),))


@server.tool(annotations=WRITE)
@guarded
def dj_structure_write(proposal: str, preview_id: str) -> str:
    """WRITES proposals/<slug>.xml (a rekordbox XML the DJ imports by hand; master.db is never
    opened), appends one log.md line and records the chosen structure in library.yaml. Needs the
    preview_id from dj_structure_preview and the DJ's explicit yes to that preview. Refuses
    without one, after any change since the preview, or when the id was already used (one
    preview, one write). Never overwrites a file: a taken name becomes <slug>-2.xml. `warnings`
    in the result: the XML is written; tell the DJ each one."""
    pid = (preview_id or "").strip() if isinstance(preview_id, str) else ""
    if not pid:
        raise ToolInputError(
            "No preview_id. Call dj_structure_preview, show the DJ the result, and call this only "
            "after their explicit yes."
        )
    if not valid_id(pid):
        raise ToolInputError(f"{preview_id!r} is not a preview id (12 hex digits from dj_structure_preview).")
    root = str(library_root())
    options = ["library", "build", "--library", root, "--apply", "--preview-id", pid]
    return run_dj(options, (_proposal(proposal),))


# -- dj tidy: audio files, never master.db -------------------------------------------------


@server.tool(annotations=READ)
@guarded
def dj_tidy_audit(crate: str = "", folder: str = "", all_tracks: bool = False, profiles: str = "",
                  brief: bool = True) -> str:
    """Read-only hygiene audit of the audio files behind a rekordbox crate (path like
    house_base/0_INBOX), a music folder inside tidy.yaml roots, or the whole collection:
    missing/odd tags, artwork, file names, CDJ playability per profile, duplicates. Writes
    reports/tidy/<date>-<target>.audit.md + .json and returns the counts (brief) or everything.
    `profiles` = comma-separated tidy.yaml profile names. Works while rekordbox is open."""
    options, positionals = tidy_target(crate, folder, all_tracks)
    for name in [p.strip() for p in profiles.split(",") if p.strip()]:
        options += ["--profile", name]
    if brief:
        options.append("--brief")
    return run_dj(["tidy", "audit", *options], positionals)


@server.tool(annotations=READ)
@guarded
def dj_tidy_dupes(crate: str = "", folder: str = "", all_tracks: bool = False) -> str:
    """Read-only duplicate report (exact bytes, or same artist/title/version within 2 s) with a
    suggested keeper per group. Never deletes or moves: the DJ decides, rekordbox deletes."""
    options, positionals = tidy_target(crate, folder, all_tracks)
    return run_dj(["tidy", "dupes", *options], positionals)


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
@guarded
def dj_tidy_plan(crate: str = "", folder: str = "", all_tracks: bool = False, rename: bool = False,
                 rename_imported: bool = False, art: str = "local") -> str:
    """Write plans/<date>-tidy-<target>.plan.json (a repo file; no audio file, no rekordbox
    change): tag values parsed from the file names for EMPTY tags only, plus local cover art.
    `rename` also plans renames of files rekordbox does not know; `rename_imported` renames
    known files too (needs the DJ's explicit words; Relocate in rekordbox afterwards). Then set
    decision yes|no per item."""
    options, positionals = tidy_target(crate, folder, all_tracks)
    if rename:
        options.append("--rename")
    if rename_imported:
        options.append("--rename-imported")
    options += ["--art", art if art in ("local", "none") else "local"]
    return run_dj(["tidy", "plan", *options], positionals)


@server.tool(annotations=READ)
@guarded
def dj_tidy_apply_preview(plan_file: str) -> str:
    """Dry-run of a tidy plan: which `decision: yes` items would be written, which cannot run and why."""
    return run_dj(["tidy", "apply"], (repo_file(plan_file, (".json",)),))


@server.tool(annotations=WRITE)
@guarded
def dj_tidy_apply(plan_file: str, strict: bool = False) -> str:
    """WRITES AUDIO FILES: the `decision: yes` tag changes (and planned renames) of a tidy plan.
    Undo record first, temp + atomic replace per file, exit_code 2 while rekordbox is open.
    master.db untouched: afterwards the DJ selects the tracks in rekordbox -> Reload Tag.
    Call dj_tidy_apply_preview first and get their OK."""
    options = ["tidy", "apply", "--apply"] + (["--strict"] if strict else [])
    return run_dj(options, (repo_file(plan_file, (".json",)),))


@server.tool(annotations=WRITE)
@guarded
def dj_tidy_undo(plan_file: str) -> str:
    """WRITES AUDIO FILES: restores the tags and names a tidy plan's apply changed, from
    state/tidy/<plan>.undo.json, newest first. exit_code 2 while rekordbox is open. Then Reload Tag."""
    return run_dj(["tidy", "undo", "--apply"], (repo_file(plan_file, (".json",)),))


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
