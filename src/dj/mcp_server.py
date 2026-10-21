"""MCP server: lets an agent that cannot run Windows programs (Claude Cowork) use the dj CLI.

It is NOT a shell. Every tool runs one fixed `dj` command with --json, as a list of
arguments (no shell, no string building), so every rule in CLAUDE.md still holds:
dry-run by default, verified backup, refusal while rekordbox runs, add only.

Read tools and write tools are separate on purpose: in Claude Desktop, read tools can be
set to "always allow" while every write keeps asking for approval.

Results stay under the tool-result limit (NFR-03): a list that grows with the library comes back
one page at a time, counts first (`paginate`). A bare file name resolves under the tool's folder
(NFR-05): "set.txt" -> tracklists/set.txt, "x.plan.json" -> plans/x.plan.json.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from dj import libfolder
from dj.barber import MAX_QUESTIONS as BARBER_MAX_QUESTIONS
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
        "propose. Read the dj-sync skill first. Every *_apply / *_write / *_undo tool "
        "needs the preview_id its preview tool returned: call the preview, show the DJ the result, "
        "ask, and only after their explicit yes pass that preview_id. Direct master.db writes "
        "(dj_tree_apply, dj_apply_write and dj_copy_apply with mode=\"db\") also need power_mode=true and "
        "run on Windows only; the default write path is an XML the DJ imports: for new structures and "
        "crates (dj_structure_preview / dj_structure_write, dj_crate_preview / dj_crate_write), and for "
        "inbox adds and copies (dj_apply_write / dj_copy_apply with mode=\"xml\"). "
        "exit_code 2 = refused: the `hint` says why. Usually rekordbox is open: ask "
        "them to close it, then retry the same call; a library folder that is not set up needs "
        "dj-start first. Never ask for a way around a refusal. The dj_tidy_* tools work on the audio files "
        "(tags, names), never on master.db: after dj_tidy_apply they must Reload Tag in rekordbox. "
        "Results put counts first; a long list comes in pages (`paging` per list: page, pages, total): "
        "call the same tool with the same arguments and page=2 for more. Pages 2+ are cut from page 1's "
        "run (kept 10 minutes, `run_at`), so every page has the same preview_id; a different preview_id "
        "means the plan changed: show the DJ the new preview. A bare file name resolves under its folder "
        "(set.txt -> tracklists/set.txt, x.plan.json -> plans/x.plan.json). log.md lines are written by "
        "the tools; read log.md, never write it."
    ),
)

# NFR-05: the folder a tool looks in for a bare file name ("set.txt" -> tracklists/set.txt).
# Passed per tool (repo_file / library_file `folder=`), so a tool can point at another folder
# (the library's plans/ once plans live there) without touching the lookup.
TRACKLISTS = "tracklists"
PLANS = "plans"
EXPORTS = "exports"

# NFR-03: pages of a list that grows with the library (see `paginate`).
PAGE_SIZE = 50  # the default items per page
PAGE_SIZE_MAX = 200
PAGE_MAX = 100_000
# Characters of list items in one result (compact JSON), shared by its paged lists (`shares`). A
# page holds at most page_size items and stops early at this budget, so one result stays well under
# 20 000 characters (the counts, the preview id and the envelope are small).
PAGE_BUDGET = 12_000
# Page 2 onwards of a read tool is cut from the run page 1 made (`run_paged`), while that run is
# this young: no second Spotify search or file scan, the same list and the same preview_id.
RUN_KEEP_S = 600
RUN_KEEP = 8  # runs kept at most; the oldest goes first


class ToolInputError(ValueError):
    pass


def repo_file(path: str, suffixes: tuple[str, ...], folder: str | None = None) -> str:
    """A file argument must be an existing file inside the repo, of an expected type.

    A relative path is taken from the repo root; when no file is there and the tool has a default
    `folder`, it is looked up in that folder too (NFR-05: "set.txt" -> tracklists/set.txt). An
    existing exact path wins. Not found -> an error that says where it looked."""
    root = REPO_ROOT.resolve()
    candidate = Path(path)
    full = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not full.is_relative_to(root):
        raise ToolInputError(f"{path!r} is outside the dj-librarian folder.")
    if full.suffix.lower() not in suffixes:
        raise ToolInputError(f"{path!r}: expected one of {', '.join(suffixes)}.")
    options = [full]
    if folder and not candidate.is_absolute():
        in_folder = (root / folder / candidate).resolve()
        if in_folder.is_relative_to(root):
            options.append(in_folder)
    for option in options:  # the type again per place: a link in the folder may point at another file
        if option.is_file() and option.suffix.lower() in suffixes:
            return str(option)
    if candidate.is_absolute():
        raise ToolInputError(f"{path!r} not found: no file at that path.")
    where = f"{folder}/ and the repo root" if len(options) > 1 else "the repo root"
    raise ToolInputError(f"{path!r} not found: looked in {where}.")


def library_root() -> Path:
    """The configured dj-library folder (dj.libfolder.configured_root): DJ_LIBRARY, else the
    folder stored by remember_root, else <repo>/dj-library. A folder too wide to be a library
    (a drive root, the home folder) is refused."""
    try:
        return libfolder.configured_root()
    except libfolder.LibraryFolderError as exc:
        raise ToolInputError(str(exc)) from exc


def library_file(path: str, suffixes: tuple[str, ...], folder: str | None = None) -> str:
    """Like repo_file, but a file inside the configured library folder is accepted too.
    A relative path is looked up in the library folder first, then in the repo; with a default
    `folder`, then in that folder of each (NFR-05: "x.xml" -> exports/x.xml). An existing exact
    path wins.

    An unusable library setting (a drive root, the home folder) leaves the repo as the only
    root, as the CLI falls back to the repo (intake.default_paths): repo files keep working,
    and the setting's error is named only for a path the repo does not hold."""
    try:
        roots = [library_root().resolve(), REPO_ROOT.resolve()]
        unusable = ""
    except ToolInputError as exc:
        roots, unusable = [REPO_ROOT.resolve()], f" The library folder setting is not used: {exc}"
    candidate = Path(path)
    exact = [candidate] if candidate.is_absolute() else [root / candidate for root in roots]
    inside = [p.resolve() for p in exact if any(p.resolve().is_relative_to(r) for r in roots)]
    if not inside:
        where = "the dj-librarian folder" if unusable else "the dj-library folder and the dj-librarian folder"
        raise ToolInputError(f"{path!r} is outside {where}.{unusable}")
    if Path(path).suffix.lower() not in suffixes:
        raise ToolInputError(f"{path!r}: expected one of {', '.join(suffixes)}.")
    if folder and not candidate.is_absolute():
        in_folder = [(root / folder / candidate).resolve() for root in roots]
        inside += [p for p in in_folder if any(p.is_relative_to(r) for r in roots)]
    for full in inside:
        if full.is_file() and full.suffix.lower() in suffixes:
            return str(full)
    if candidate.is_absolute():
        raise ToolInputError(f"{path!r} not found: no file at that path.{unusable}")
    places = " and ".join(str(r) for r in roots)
    where = f"{folder}/ and the top of {places}" if folder else places
    raise ToolInputError(f"{path!r} not found: looked in {where}.{unusable}")


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
    return json.dumps(run_dj_data(options, positionals, as_json), indent=2, ensure_ascii=False)


def run_paged(options: list[str], positionals: tuple[str, ...] = (), *, keys: Sequence[str], page: int = 1,
              page_size: int = PAGE_SIZE, rest_in: str | None = None, more: Mapping[str, str] | None = None,
              view: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> str:
    """run_dj, with the lists named by `keys` cut to one page (NFR-03, see `paginate`). Compact
    JSON: the result is sized for the tool-result limit. `view` reshapes the CLI result first.

    A read tool's page 1 always runs the command. A later page comes from the run kept for the
    same command line when it is younger than RUN_KEEP_S (else the command runs again): every page
    is cut from one list, with one preview_id, and Spotify is not searched or the files scanned
    again. `run_at` says when that run happened. A tool whose call writes (`rest_in` set) is never
    kept: it is called once and returns its first page."""
    command = (*options, "--", *positionals)
    reads = rest_in is None
    kept = RUNS.get(command) if reads and page > 1 else None
    out = kept if kept is not None else run_dj_data(options, positionals)
    if reads and kept is None and out.get("ok") and isinstance(out.get("result"), dict):
        out["run_at"] = datetime.now().isoformat(timespec="seconds")
        RUNS.put(command, out)
    out = dict(out)  # the kept run stays whole; only this answer is cut to a page
    if isinstance(out.get("result"), dict):
        result = view(out["result"]) if view else out["result"]
        out["result"] = paginate(result, keys, page, page_size, rest_in=rest_in, more=more)
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


class Runs:
    """The last RUN_KEEP successful read runs per command line, each for RUN_KEEP_S seconds."""

    def __init__(self) -> None:
        self._runs: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, command: tuple[str, ...]) -> dict[str, Any] | None:
        with self._lock:
            found = self._runs.get(command)
            if found is None or time.monotonic() - found[0] >= RUN_KEEP_S:
                self._runs.pop(command, None)
                return None
            return found[1]

    def put(self, command: tuple[str, ...], out: dict[str, Any]) -> None:
        with self._lock:
            self._runs.pop(command, None)
            self._runs[command] = (time.monotonic(), out)
            while len(self._runs) > RUN_KEEP:
                self._runs.pop(next(iter(self._runs)))

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()


RUNS = Runs()


def run_dj_data(options: list[str], positionals: tuple[str, ...] = (), as_json: bool = True) -> dict[str, Any]:
    """The outcome of one `dj` run: {ok, exit_code, result | output, stderr, hint}."""
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
        return {"ok": False, "exit_code": None, "error": f"timed out after {TIMEOUT_S}s"}

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
    return out


# -- pages (NFR-03) --------------------------------------------------------------------------


def page_args(page: Any, page_size: Any) -> tuple[int, int]:
    """page >= 1, 1 <= page_size <= PAGE_SIZE_MAX, whole numbers; else ToolInputError before any run."""
    for name, value, high in (("page", page, PAGE_MAX), ("page_size", page_size, PAGE_SIZE_MAX)):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= high:
            raise ToolInputError(f"{name} must be a whole number from 1 to {high}, got {value!r}.")
    return page, page_size


def _chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))


def page_bounds(items: Sequence[Any], page_size: int, budget: int = PAGE_BUDGET) -> list[tuple[int, int]]:
    """(start, end) of every page of `items`, in order: at most `page_size` items each, and a page
    ends early before the item that would take it over `budget` characters (a single item bigger
    than the budget gets a page of its own). Deterministic: the same list and page_size always give
    the same pages, so page 2 starts where page 1 ended."""
    bounds: list[tuple[int, int]] = []
    start = used = 0
    for i, item in enumerate(items):
        size = _chars(item) + 1  # the comma
        if i > start and (i - start >= page_size or used + size > budget):
            bounds.append((start, i))
            start, used = i, 0
        used += size
    if start < len(items):
        bounds.append((start, len(items)))
    return bounds


def _page_need(items: Sequence[Any], page_size: int) -> int:
    """Characters of the biggest page of `items` when only page_size cuts them."""
    sizes = [_chars(item) + 1 for item in items]
    return max((sum(sizes[i:i + page_size]) for i in range(0, len(sizes), page_size)), default=0)


def shares(result: Mapping[str, Any], lists: Sequence[str], page_size: int, budget: int = PAGE_BUDGET) -> dict[str, int]:
    """Each paged list's part of the character budget. A list whose pages fit in an even share
    gets what they need; what it leaves goes to the bigger lists, evenly (a short `links` does not
    halve `tree`). The same result and page_size always give the same shares."""
    need = {key: _page_need(result[key], page_size) for key in lists}
    out: dict[str, int] = {}
    left, pending = budget, sorted(lists, key=lambda key: need[key])
    while pending and need[pending[0]] <= left // len(pending):
        key = pending.pop(0)
        out[key] = need[key]
        left -= need[key]
    for key in pending:
        out[key] = max(1, left // len(pending))
    return out


def paginate(result: Mapping[str, Any], keys: Sequence[str], page: int = 1, page_size: int = PAGE_SIZE,
             budget: int = PAGE_BUDGET, rest_in: str | None = None,
             more: Mapping[str, str] | None = None) -> dict[str, Any]:
    """One page of a CLI result (NFR-03): every count / summary key is kept, `counts` first; each
    list named in `keys` is cut to page `page`; `paging` says per list {page, pages, page_size,
    total, from, to} (from/to: 1-based positions shown, null on an empty page). A page beyond the
    end gives an empty list with the totals. Keys that are not lists in `result` are left alone; a
    result without any of them comes back unchanged. `rest_in` (for tools whose call writes and so
    cannot be called again for page 2) names the result key holding the file with the full list.
    `more` maps a list the CLI already capped to the key counting what it left out: that list's
    `total` counts those too, and `listed` says how many the pages reach."""
    lists = [k for k in keys if isinstance(result.get(k), list)]
    if not lists:
        return dict(result)
    share = shares(result, lists, page_size, budget)
    out: dict[str, Any] = {k: result[k] for k in ("counts",) if k in result}
    out |= {k: v for k, v in result.items() if k not in lists and k != "counts"}
    paging: dict[str, dict[str, Any]] = {}
    pages: dict[str, list[Any]] = {}
    for key in lists:
        items = result[key]
        bounds = page_bounds(items, page_size, share[key])
        start, end = bounds[page - 1] if page <= len(bounds) else (len(items), len(items))
        pages[key] = items[start:end]
        paging[key] = {"page": page, "pages": max(1, len(bounds)), "page_size": page_size, "total": len(items),
                       "from": start + 1 if end > start else None, "to": end if end > start else None}  # fmt: skip
        unlisted = result.get((more or {}).get(key, ""))
        if isinstance(unlisted, int) and not isinstance(unlisted, bool) and unlisted > 0:
            paging[key] |= {"total": len(items) + unlisted, "listed": len(items)}
        if rest_in and len(bounds) > 1:
            paging[key]["rest_in"] = result.get(rest_in)
    return out | {"paging": paging} | pages


# -- dj status: the nested tree as rows (NFR-03) -----------------------------------------------


def status_rows(nodes: Any, smart_xml: bool = False, parent: str = "") -> list[dict[str, Any]]:
    """`dj status --json`'s nested `tree` as one row per node, depth first: {path, kind} plus
    `tracks` (playlists), `children` (folders, the direct ones) and, only when asked, `smart_xml`.
    A row is small whatever the folder holds, so one big folder pages like any other list."""
    rows: list[dict[str, Any]] = []
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        path = f"{parent}/{node.get('name')}" if parent else str(node.get("name"))
        children = node.get("children")
        row: dict[str, Any] = {"path": path, "kind": node.get("kind")}
        if "tracks" in node:
            row["tracks"] = node["tracks"]
        if isinstance(children, list):
            row["children"] = len(children)
        if smart_xml and "smart_xml" in node:
            row["smart_xml"] = node["smart_xml"]
        rows.append(row)
        rows += status_rows(children, smart_xml, path)
    return rows


def status_view(result: dict[str, Any], smart_xml: bool = False) -> dict[str, Any]:
    """dj_status's result: `tree` as rows (`status_rows`) and the counts first (tracks, folders,
    playlists, smart, links)."""
    if not isinstance(result.get("tree"), list):
        return result
    rows = status_rows(result["tree"], smart_xml)
    kinds = Counter(row["kind"] for row in rows)
    counts: dict[str, Any] = {"tracks": result["tracks"]} if isinstance(result.get("tracks"), int) else {}
    counts |= {"folders": kinds["folder"], "playlists": kinds["playlist"], "smart": kinds["smart"]}
    if isinstance(result.get("links"), list):
        counts["links"] = len(result["links"])
    if isinstance(result.get("counts"), dict):
        counts |= result["counts"]
    return result | {"counts": counts, "tree": rows}


# -- text results (NFR-03) -----------------------------------------------------------------------


def short_tree_output(text: str, budget: int = PAGE_BUDGET) -> str:
    """dj_tree_apply's text within `budget` characters: `dj tree --apply` prints one line per
    planned node, the summary (counts, APPLIED, the log.md line) and then the whole final tree.
    A longer text keeps the summary; the node lines are cut to what fits and the final tree is
    left out (dj_status pages it). A short text comes back as it is."""
    if len(text) <= budget:
        return text
    head, cut, tree = text.partition("\nfinal tree:")
    lines = head.split("\n")
    blank = lines.index("") if "" in lines else len(lines)
    actions, summary = lines[:blank], lines[blank:]
    used = sum(len(line) + 1 for line in summary) + 300
    kept: list[str] = []
    for line in actions:
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    out = kept + ([f"... {len(actions) - len(kept)} more node line(s), as dj_tree_preview showed them"]
                  if len(kept) < len(actions) else [])  # fmt: skip
    out += summary
    if cut:
        out.append(f"final tree: {len(tree.splitlines()) - 1} line(s) left out; dj_status pages the tree.")
    return "\n".join(out)


# A tool whose call writes cannot be called again for page 2 (its preview id is used up): its
# lists come back as their first page, and `rest_in` names the file that holds all of them.
WRITTEN_LISTS: dict[str, Any] = {"keys": ("adds", "rows", "items", "skipped_lines"), "rest_in": "report"}


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


def preview_id_arg(preview_id: Any, preview_tool: str) -> str:
    """A write tool's preview_id: 12 lower-case hex from the preview tool (R-1102). Empty or
    malformed -> ToolInputError, before anything runs."""
    pid = preview_id.strip() if isinstance(preview_id, str) else ""
    if not pid:
        raise ToolInputError(
            f"No preview_id. Call {preview_tool}, show the DJ the result, and call this only after "
            "their explicit yes, with the preview_id it returned."
        )
    if not valid_id(pid):
        raise ToolInputError(f"{preview_id!r} is not a preview id (12 lower-case hex digits from {preview_tool}).")
    return pid


POWER_MODE_REFUSAL = (
    "master.db writes are power mode (Windows only): pass power_mode=true only when the DJ asked for a "
    "direct write. The default write path is an XML to import instead: mode=\"xml\" for inbox adds and "
    "copies (dj_apply_write, dj_copy_apply), dj_structure_preview / dj_structure_write for new folders "
    "and playlists."
)
ADD_MODES = ("xml", "db")


def power_mode_arg(power_mode: Any) -> None:
    """R-205: a direct master.db write needs power_mode=true, checked before the preview id."""
    if power_mode is not True:
        raise ToolInputError(POWER_MODE_REFUSAL)


def add_mode_flags(mode: Any, power_mode: Any) -> list[str]:
    """dj_apply_write / dj_copy_apply (R-802, R-205): "xml" writes an XML the DJ imports (any OS,
    no power_mode); "db" writes master.db and needs power_mode=true. Empty: "db" when
    power_mode=true, else "xml" (the default write path). Checked before the preview id."""
    if not isinstance(mode, str) or mode.strip() not in ("", *ADD_MODES):
        raise ToolInputError(f"mode must be one of {', '.join(ADD_MODES)}, got {mode!r}.")
    chosen = mode.strip() or ("db" if power_mode is True else "xml")
    if chosen == "xml":
        if power_mode is True:
            raise ToolInputError('mode="xml" writes an XML to import and needs no power_mode: pass one of the two.')
        return ["--xml"]
    power_mode_arg(power_mode)
    return ["--power-mode"]


# -- read-only ---------------------------------------------------------------------------


@server.tool(annotations=READ)
@guarded
def dj_status(page: int = 1, page_size: int = PAGE_SIZE, smart_xml: bool = False) -> str:
    """Library overview: counts first (tracks, folders, playlists, smart, links), whether
    rekordbox is running, the playlist tree as one row per node, depth first (`tree`: path like
    "house_base/0_INBOX", kind, tracks, children) and per link in links.yaml (`links`) the counts
    by status, last pull and last apply (`links_file`: the dj-library folder's links.yaml, else
    the repo's; `state_from_repo`: repo state files still read until the first apply in the
    library folder). Read-only. `tree` and `links` come in pages (`paging`):
    page=2 for the next, cut from page 1's run. smart_xml=true adds each smart playlist's raw rule
    XML to its row."""
    page, page_size = page_args(page, page_size)
    return run_paged(["status"], keys=("tree", "links"), page=page, page_size=page_size,
                     view=lambda result: status_view(result, smart_xml is True))


@server.tool(annotations=READ)
@guarded
def dj_tree_preview(file: str = "tree.yaml", page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Dry-run of a tree file (e.g. bases.yaml): counts and one action per node - CREATE, SKIP,
    HOLD, CONFLICT - and a preview_id (null when there is a CONFLICT). Writes nothing. `file` is a
    .yaml path inside the repo (e.g. "bases.yaml"). The `actions` come in pages (`paging`; the
    preview_id is on every page). Show the DJ the result; dj_tree_apply needs this preview_id."""
    page, page_size = page_args(page, page_size)
    return run_paged(["tree", "--file", repo_file(file, (".yaml", ".yml"))], keys=("actions",), page=page,
                     page_size=page_size)


@server.tool(annotations=READ)
@guarded
def dj_library_inspect(xml: str = "", page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Library summary from one model: source, counts (tracks, folders, playlists, smart,
    orphans, entries; complete), a sample of the top of the playlist tree (at most 30 nodes and
    10 child names each; `tree_more` / `more_children` count the rest; the sample comes in pages,
    `paging`: its `total` counts every top-level node, `listed` the ones in the sample), which
    fields the source lacks, and notes. `xml` = a rekordbox collection XML inside the dj-library
    folder or the repo; a bare name is looked up in exports/ (e.g.
    "2026-10-20-collection.xml" -> exports/2026-10-20-collection.xml); empty = a read-only
    snapshot of master.db (`snapshot_path` = the copy that was read). Writes nothing. The whole
    tree: dj_status."""
    page, page_size = page_args(page, page_size)
    positionals = (library_file(xml, (".xml",), folder=EXPORTS),) if xml else ()
    return run_paged(["library", "inspect"], positionals, keys=("tree",), page=page, page_size=page_size,
                     more={"tree": "tree_more"})


ANALYZE_SOURCES = ("xml", "db")


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
@guarded
def dj_library_analyze(source: str = "xml") -> str:
    """Analyse the DJ's library in one go and render the HTML report: reads the library once
    (source "xml" = the latest export in the dj-library folder; "db" = a read-only snapshot of
    master.db), then writes profile/ (incl. identity.json, the six axes and the archetype, and
    sleeve.svg), structure/ (incl. proposals.yaml with 2-3 restructure proposals), taste/ and
    reports/<date>-library.html, plus log.md lines. Identity runs after taste, before the
    report. Text files in the configured dj-library folder only; rekordbox, Spotify and audio
    files are never written.
    Returns counts first, the report path, the proposals (trigger, cost) and any failed step.
    It always rebuilds structure/proposals.yaml (an edited copy is kept first): after renaming a
    proposal, render with the dj-report script instead. exit_code 2 = refused, see `hint`."""
    if source not in ANALYZE_SOURCES:
        raise ToolInputError(f"source must be one of {', '.join(ANALYZE_SOURCES)}, got {source!r}.")
    return run_dj(["library", "analyze", "--source", source])


@server.tool(annotations=SPOTIFY_READ)
def dj_pull(link: str = "", all_links: bool = False) -> str:
    """Download a Spotify inbox playlist to the inbox (<library>/.cache/inbox/<crate>.json, or
    inbox/ in the repo when the library folder's links.yaml has no link yet). Read-only on
    Spotify and rekordbox. `link` = the spotify or crate value of an entry in links.yaml."""
    if all_links:
        return run_dj(["pull", "--all"])
    return run_dj(["pull"], (link,))


@server.tool(annotations=READ)
@guarded
def dj_match(link: str, page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Match the last pull of a link against the library: counts first, then the `items`:
    IN_CRATE, PROPOSE, AMBIGUOUS (with up to 3 local candidates each), MISSING, DECLINED.
    Writes nothing. `items` come in pages (`paging`): page=2 for the next."""
    page, page_size = page_args(page, page_size)
    return run_paged(["match"], (link,), keys=("items",), page=page, page_size=page_size)


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def dj_plan(link: str) -> str:
    """Write plans/<date>-<crate>.plan.json and wishlist/<crate>.md (text files in the
    dj-library folder, or in the repo while its links.yaml has no link; rekordbox untouched) and
    one log.md line. Returns the paths, the counts and the log line. Then edit the plan: decision
    yes|no, and for AMBIGUOUS a pick (rb_content_id from its candidates)."""
    return run_dj(["plan"], (link,))


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def dj_wishlist_shop(link: str) -> str:
    """Write the shopping list wishlist/<crate>.shopping.md from the MISSING tracks of the
    link's newest plan (call dj_plan first): artist - title, Beatport and Bandcamp search links
    (never fetched), label when Spotify sends one; BPM and key are '-'. A generated text file,
    rewritten on every call; rekordbox and Spotify untouched. Returns counts first: missing,
    top labels, the file, the log.md line (library folder only). `stale_plan: true` = the
    inbox was pulled after that plan: call dj_plan, then this again."""
    return run_dj(["wishlist", "shop"], (link,))


@server.tool(annotations=READ)
@guarded
def dj_apply_preview(plan_file: str, page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Dry-run of a plan: the counts (would_add, yes, no, pending), which `decision: yes` tracks
    would be added to the crate (`adds`, in pages: `paging`), and a preview_id (on every page).
    Writes nothing. `plan_file` = a plan in plans/ of the dj-library folder or the repo; a bare name is looked up there
    ("2026-10-20-house.plan.json" -> plans/2026-10-20-house.plan.json). Show the DJ the result;
    dj_apply_write needs this preview_id."""
    page, page_size = page_args(page, page_size)
    return run_paged(["apply"], (library_file(plan_file, (".json",), folder=PLANS),), keys=("adds",), page=page,
                     page_size=page_size)


@server.tool(annotations=READ)
@guarded
def dj_copy_preview(source: str, target: str, page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Dry-run: counts and which tracks of rekordbox playlist `source` would be appended to
    `target` (`rows`, in pages: `paging`), and a preview_id (on every page). Writes nothing. Show
    the DJ the result; dj_copy_apply needs this preview_id."""
    page, page_size = page_args(page, page_size)
    return run_paged(["copy"], (source, target), keys=("rows",), page=page, page_size=page_size)


@server.tool(annotations=SPOTIFY_READ)
@guarded
def dj_build_preview(file: str, name: str = "", include_ambiguous: bool = False, page: int = 1,
                     page_size: int = PAGE_SIZE) -> str:
    """Dry-run: match every 'Artist - Title' line of a tracklist file on Spotify: counts (MATCH,
    AMBIGUOUS, MISSING), the matches (`items`) and the lines without ' - ' (`skipped_lines`), both
    in pages (`paging`), and a preview_id (on every page). rekordbox untouched, writes nothing.
    Page 1 searches Spotify; pages 2+ are cut from that run (10 minutes), so the preview_id stays
    the same: a different one means the matches changed, show the DJ again. `file` = a tracklist
    in tracklists/ (dj-library folder or repo); a bare name is looked up there ("set.txt" -> tracklists/set.txt). Pass the
    same `name` and `include_ambiguous` you will pass to dj_build_apply: its preview_id is for
    exactly these arguments."""
    page, page_size = page_args(page, page_size)
    options = ["build"] + (["--name", name] if name else [])
    if include_ambiguous:
        options.append("--include-ambiguous")
    return run_paged(options, (library_file(file, (".txt", ".md"), folder=TRACKLISTS),), keys=("items", "skipped_lines"),
                     page=page, page_size=page_size)


@server.tool(annotations=SPOTIFY_READ)
@guarded
def dj_push_preview(playlist: str, name: str = "", include_ambiguous: bool = False, page: int = 1,
                    page_size: int = PAGE_SIZE) -> str:
    """Dry-run: match a rekordbox playlist on Spotify: counts (MATCH, AMBIGUOUS, MISSING), the
    matches (`items`, in pages: `paging`) and a preview_id (on every page). Writes nothing. Page 1
    searches Spotify; pages 2+ are cut from that run (10 minutes), so the preview_id stays the
    same: a different one means the matches changed, show the DJ again. Pass the same `name` and
    `include_ambiguous` you will pass to dj_push_apply: its preview_id is for exactly these
    arguments."""
    page, page_size = page_args(page, page_size)
    options = ["push"] + (["--name", name] if name else [])
    if include_ambiguous:
        options.append("--include-ambiguous")
    return run_paged(options, (playlist,), keys=("items",), page=page, page_size=page_size)


# -- writes: only after the DJ's explicit OK ----------------------------------------------


@server.tool(annotations=WRITE)
@guarded
def dj_tree_apply(preview_id: str, file: str = "tree.yaml", power_mode: bool = False) -> str:
    """WRITES to rekordbox master.db: create the missing folders/playlists of a tree file.
    Backup first, one commit, refuses while rekordbox is open (exit_code 2). Never changes or
    deletes what exists. Windows power mode (R-205): needs power_mode=true, else refused; the
    default write path is an XML the DJ imports (dj_structure_preview / dj_structure_write).
    Call dj_tree_preview, show the DJ the result, ask, and only after their explicit yes pass its
    preview_id (same `file`). Refused without it, after any change since the preview, or with a
    used id. Appends one log.md line itself. A long text keeps the summary (counts, APPLIED, the
    log.md line) and leaves the final tree out: dj_status pages it."""
    power_mode_arg(power_mode)
    pid = preview_id_arg(preview_id, "dj_tree_preview")
    options = ["tree", "--file", repo_file(file, (".yaml", ".yml")), "--apply", "--power-mode", "--preview-id", pid]
    out = run_dj_data(options, as_json=False)
    if isinstance(out.get("output"), str):
        out["output"] = short_tree_output(out["output"])
    return json.dumps(out, indent=2, ensure_ascii=False)


@server.tool(annotations=WRITE)
@guarded
def dj_apply_write(plan_file: str, preview_id: str, power_mode: bool = False, mode: str = "") -> str:
    """WRITES the `decision: yes` tracks of a plan for its crate. The default write path is an XML
    the DJ imports (mode="xml", any OS, no power_mode): proposals/<crate>-adds-<date>.xml with one
    playlist of those tracks, master.db never opened for writing; the result gives the import card
    (`import_steps`) ending in the one drag of those tracks onto the crate. mode="db" appends them to
    the crate in rekordbox master.db: Windows power mode (R-205), needs power_mode=true, else refused;
    backup first, one commit, exit_code 2 while rekordbox is open. mode empty = "db" with
    power_mode=true, else "xml". Either way it then updates the match cache and the declined list
    and writes a report (reports/apply/ in a library folder). Call dj_apply_preview, show the DJ the
    result, ask, and only after their explicit yes pass its preview_id (one preview id serves both
    modes; same `plan_file`; a bare name is looked up in plans/: "2026-10-20-house.plan.json" ->
    plans/2026-10-20-house.plan.json). Appends one log.md line itself. A long list comes back as its
    first page; `paging.<list>.rest_in` names the report with all of it."""
    flags = add_mode_flags(mode, power_mode)
    pid = preview_id_arg(preview_id, "dj_apply_preview")
    plan = library_file(plan_file, (".json",), folder=PLANS)
    return run_paged(["apply", "--apply", *flags, "--preview-id", pid], (plan,), **WRITTEN_LISTS)


@server.tool(annotations=WRITE)
@guarded
def dj_copy_apply(source: str, target: str, preview_id: str, power_mode: bool = False, mode: str = "") -> str:
    """WRITES the tracks of playlist `source` that `target` lacks, for `target`. The default write
    path is an XML the DJ imports (mode="xml", any OS, no power_mode): proposals/<target>-adds-<date>.xml
    with one playlist of those tracks, master.db never opened for writing; the result gives the import
    card (`import_steps`) ending in the one drag onto `target`. mode="db" appends them in rekordbox
    master.db: Windows power mode (R-205), needs power_mode=true, else refused; backup first, one
    commit, exit_code 2 while rekordbox is open. mode empty = "db" with power_mode=true, else "xml".
    Call dj_copy_preview, show the DJ the result, ask, and only after their explicit yes pass its
    preview_id (one preview id serves both modes; same source and target). Appends one log.md line
    itself. A long list comes back as its first page; `paging.<list>.rest_in` names the report with
    all of it."""
    flags = add_mode_flags(mode, power_mode)
    pid = preview_id_arg(preview_id, "dj_copy_preview")
    return run_paged(["copy", "--apply", *flags, "--preview-id", pid], (source, target), **WRITTEN_LISTS)


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
@guarded
def dj_build_apply(file: str, preview_id: str, name: str = "", include_ambiguous: bool = False) -> str:
    """WRITES to Spotify: create (once) a private playlist from a tracklist file and add the
    MATCH tracks. Only ever adds. Call dj_build_preview with the same file ("set.txt" ->
    tracklists/set.txt), name and include_ambiguous, show the DJ the result, ask, and only after
    their explicit yes pass its preview_id. Appends one log.md line itself. A long list comes back
    as its first page; `paging.<list>.rest_in` names the report with all of it."""
    pid = preview_id_arg(preview_id, "dj_build_preview")
    options = ["build", "--apply", "--preview-id", pid] + (["--name", name] if name else [])
    if include_ambiguous:
        options.append("--include-ambiguous")
    return run_paged(options, (library_file(file, (".txt", ".md"), folder=TRACKLISTS),), **WRITTEN_LISTS)


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
@guarded
def dj_push_apply(playlist: str, preview_id: str, name: str = "", include_ambiguous: bool = False) -> str:
    """WRITES to Spotify: create (once) a private playlist for a rekordbox playlist and add
    the MATCH tracks. Only ever adds. `include_ambiguous` only if the DJ checked the links.
    Call dj_push_preview with the same playlist, name and include_ambiguous, show the DJ the
    result, ask, and only after their explicit yes pass its preview_id. Appends one log.md line
    itself. A long list comes back as its first page; `paging.<list>.rest_in` names the report with
    all of it."""
    pid = preview_id_arg(preview_id, "dj_push_preview")
    options = ["push", "--apply", "--preview-id", pid]
    if name:
        options += ["--name", name]
    if include_ambiguous:
        options.append("--include-ambiguous")
    return run_paged(options, (playlist,), **WRITTEN_LISTS)


# -- dj-build: a proposal -> rekordbox XML the DJ imports (R-501..R-505) -------------------


def _proposal(proposal: str) -> str:
    if not isinstance(proposal, str) or not proposal.strip():
        raise ToolInputError("Name the proposal: its slug, its name, or 'Build me the <name> structure'.")
    return proposal.strip()


@server.tool(annotations=LIBRARY_TEXT)
@guarded
def dj_structure_preview(proposal: str, page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Preview a structure proposal from the dj-library folder: counts, CREATE / SKIP / CONFLICT /
    MANUAL per node against structure/current-tree.yaml (`rows`, every node, in pages: `paging`;
    pages 2+ are cut from page 1's run), where existing playlists land, and a preview_id (on every
    page). `proposal` = its slug, its name, or "Build me the <name> structure".
    Writes only proposals/<slug>.yaml (if missing; an existing one is the DJ's and is read as
    it is) and the preview record. No XML, rekordbox and master.db untouched. Show the DJ the
    result and ask "Write the XML?" before dj_structure_write. A `blocked` result has no
    preview_id (a conflict, nothing to create, current-tree.yaml older than the export, or this
    exact build already written)."""
    page, page_size = page_args(page, page_size)
    root = str(library_root())
    options = ["library", "build", "--library", root, "--rows-limit", "0"]  # every row: the pages bound it
    return run_paged(options, (_proposal(proposal),), keys=("rows",), page=page, page_size=page_size,
                     more={"rows": "rows_more"})


@server.tool(annotations=WRITE)
@guarded
def dj_structure_write(proposal: str, preview_id: str) -> str:
    """WRITES proposals/<slug>.xml (a rekordbox XML the DJ imports by hand; master.db is never
    opened), appends one log.md line and records the chosen structure in library.yaml. Needs the
    preview_id from dj_structure_preview and the DJ's explicit yes to that preview. Refuses
    without one, after any change since the preview, or when the id was already used (one
    preview, one write). Never overwrites a file: a taken name becomes <slug>-2.xml. `warnings`
    in the result: the XML is written; tell the DJ each one."""
    pid = preview_id_arg(preview_id, "dj_structure_preview")
    root = str(library_root())
    options = ["library", "build", "--library", root, "--apply", "--preview-id", pid]
    return run_dj(options, (_proposal(proposal),))


# -- Crate me: a crate from the DJ's own library -> rekordbox XML (R-601..R-604, R-702) ------

CRATE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _crate_spec(spec: str) -> str:
    """A crate slug as it is, or the path of a spec file, which must be a .yaml inside the
    dj-library folder or the repo (the CLI then insists on crates/<slug>.spec.yaml)."""
    text = spec.strip() if isinstance(spec, str) else ""
    if not text:
        raise ToolInputError("Name the crate: its slug, or the path of crates/<slug>.spec.yaml.")
    if CRATE_SLUG.match(text):
        return text
    return library_file(text, (".yaml",))


@server.tool(annotations=READ)
@guarded
def dj_crate_preview(spec: str, page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Preview a crate from the DJ's own library: `spec` = the slug of crates/<slug>.spec.yaml
    in the dj-library folder (or that path). Returns counts first, the picks in order with a
    one-line reason each and the spares by energy tier, in pages (`paging`; pages 2+ are cut from
    page 1's run), and a preview_id on every page. Writes nothing but the preview record: no XML, no crates/*.md, rekordbox
    and master.db untouched. Show the DJ the result and ask "Write the crate XML?" before
    dj_crate_write. A `blocked` result has no preview_id (a playlist of that name exists in the
    DJ's Crates folder, or this exact crate was written already)."""
    page, page_size = page_args(page, page_size)
    root = str(library_root())
    options = ["library", "crate", "--library", root, "--picks-limit", "0"]  # every pick: the pages bound it
    return run_paged(options, (_crate_spec(spec),), keys=("picks", "spares"), page=page, page_size=page_size,
                     more={"picks": "picks_more"})


@server.tool(annotations=WRITE)
@guarded
def dj_crate_write(spec: str, preview_id: str) -> str:
    """WRITES proposals/crate-<slug>.xml (a rekordbox XML the DJ imports by hand: folder Crates
    with the playlist and its spares) and crates/<slug>.md (the crate record), and appends one
    log.md line. Needs the preview_id from dj_crate_preview and the DJ's explicit yes to that
    preview. Refuses without one, after any change since the preview, or when the id was already
    used. Never overwrites a file (a taken name becomes -2). `warnings`: the XML is written; tell
    the DJ each one."""
    pid = (preview_id or "").strip() if isinstance(preview_id, str) else ""
    if not pid:
        raise ToolInputError(
            "No preview_id. Call dj_crate_preview, show the DJ the result, and call this only after "
            "their explicit yes."
        )
    if not valid_id(pid):
        raise ToolInputError(f"{preview_id!r} is not a preview id (12 hex digits from dj_crate_preview).")
    root = str(library_root())
    options = ["library", "crate", "--library", root, "--apply", "--preview-id", pid]
    return run_dj(options, (_crate_spec(spec),))


# -- dj tidy: audio files, never master.db -------------------------------------------------


@server.tool(annotations=LIBRARY_TEXT)
@guarded
def dj_tidy_audit(crate: str = "", folder: str = "", all_tracks: bool = False, profiles: str = "",
                  brief: bool = True, page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Hygiene audit of the audio files behind a rekordbox crate (path like house_base/0_INBOX),
    a music folder inside tidy.yaml roots, or the whole collection: missing/odd tags, artwork,
    file names, CDJ playability per profile, duplicates. Only reads the audio files and rekordbox;
    writes reports/tidy/<date>-<target>.audit.md + .json and one log.md line, and returns the counts
    (brief) or everything (brief=false: `items` and `duplicates` in pages, `paging`; page=2 for
    the next). Page 1 scans the files; pages 2+ are cut from that scan (10 minutes) and scan and
    log nothing. `profiles` = comma-separated tidy.yaml profile names. Works while rekordbox is
    open."""
    page, page_size = page_args(page, page_size)
    options, positionals = tidy_target(crate, folder, all_tracks)
    for name in [p.strip() for p in profiles.split(",") if p.strip()]:
        options += ["--profile", name]
    if brief:
        options.append("--brief")
    return run_paged(["tidy", "audit", *options], positionals, keys=("items", "duplicates"), page=page,
                     page_size=page_size)


@server.tool(annotations=READ)
@guarded
def dj_tidy_dupes(crate: str = "", folder: str = "", all_tracks: bool = False, page: int = 1,
                  page_size: int = PAGE_SIZE) -> str:
    """Read-only duplicate report (exact bytes, or same artist/title/version within 2 s) with a
    suggested keeper per group (`groups`, in pages: `paging`; page=2 for the next). Never deletes
    or moves: the DJ decides, rekordbox deletes."""
    page, page_size = page_args(page, page_size)
    options, positionals = tidy_target(crate, folder, all_tracks)
    return run_paged(["tidy", "dupes", *options], positionals, keys=("groups",), page=page, page_size=page_size)


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
@guarded
def dj_tidy_plan(crate: str = "", folder: str = "", all_tracks: bool = False, rename: bool = False,
                 rename_imported: bool = False, art: str = "local") -> str:
    """Write plans/<date>-tidy-<target>.plan.json (a repo file; no audio file, no rekordbox
    change) and one log.md line: tag values parsed from the file names for EMPTY tags only, plus
    local cover art. `rename` also plans renames of files rekordbox does not know;
    `rename_imported` renames known files too (needs the DJ's explicit words; Relocate in rekordbox
    afterwards). Then set decision yes|no per item. A long `items` list comes back as its first
    page; `paging.items.rest_in` names the plan file with all of them."""
    options, positionals = tidy_target(crate, folder, all_tracks)
    if rename:
        options.append("--rename")
    if rename_imported:
        options.append("--rename-imported")
    options += ["--art", art if art in ("local", "none") else "local"]
    return run_paged(["tidy", "plan", *options], positionals, keys=("items",), rest_in="plan")


@server.tool(annotations=READ)
@guarded
def dj_tidy_apply_preview(plan_file: str, strict: bool = False, page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Dry-run of a tidy plan: counts, which `decision: yes` items would be written and which
    cannot run and why (`items`, in pages: `paging`), and a preview_id (on every page). Writes
    nothing. `plan_file` = a plan in plans/; a bare name is looked up there
    ("2026-10-20-tidy-all.plan.json" -> plans/2026-10-20-tidy-all.plan.json). Pass the same
    `strict` you will pass to dj_tidy_apply."""
    page, page_size = page_args(page, page_size)
    options = ["tidy", "apply"] + (["--strict"] if strict else [])
    return run_paged(options, (repo_file(plan_file, (".json",), folder=PLANS),), keys=("items",), page=page,
                     page_size=page_size)


@server.tool(annotations=WRITE)
@guarded
def dj_tidy_apply(plan_file: str, preview_id: str, strict: bool = False) -> str:
    """WRITES AUDIO FILES: the `decision: yes` tag changes (and planned renames) of a tidy plan.
    Undo record first, temp + atomic replace per file, exit_code 2 while rekordbox is open.
    master.db untouched: afterwards the DJ selects the tracks in rekordbox -> Reload Tag.
    Call dj_tidy_apply_preview, show the DJ the result, ask, and only after their explicit yes
    pass its preview_id (same `plan_file`; a bare name is looked up in plans/:
    "2026-10-20-tidy-all.plan.json" -> plans/2026-10-20-tidy-all.plan.json). Appends one log.md
    line itself. A long `items` list comes back as its first page; `paging.items.rest_in` names the
    report with all of them."""
    pid = preview_id_arg(preview_id, "dj_tidy_apply_preview")
    options = ["tidy", "apply", "--apply", "--preview-id", pid] + (["--strict"] if strict else [])
    return run_paged(options, (repo_file(plan_file, (".json",), folder=PLANS),), keys=("items",), rest_in="report")


@server.tool(annotations=READ)
@guarded
def dj_tidy_undo_preview(plan_file: str, page: int = 1, page_size: int = PAGE_SIZE) -> str:
    """Dry-run of undoing a tidy plan's apply: counts, which files would get their tags and names
    back and which are skipped and why (`items`, in pages: `paging`), and a preview_id (on every
    page). Writes nothing. `plan_file` = a plan in plans/; a bare name is looked up there
    ("2026-10-20-tidy-all.plan.json" -> plans/2026-10-20-tidy-all.plan.json). dj_tidy_undo needs
    this preview_id."""
    page, page_size = page_args(page, page_size)
    return run_paged(["tidy", "undo"], (repo_file(plan_file, (".json",), folder=PLANS),), keys=("items",),
                     page=page, page_size=page_size)


@server.tool(annotations=WRITE)
@guarded
def dj_tidy_undo(plan_file: str, preview_id: str) -> str:
    """WRITES AUDIO FILES: restores the tags and names a tidy plan's apply changed, from
    state/tidy/<plan>.undo.json, newest first. exit_code 2 while rekordbox is open. Then Reload Tag.
    Call dj_tidy_undo_preview, show the DJ the result, ask, and only after their explicit yes
    pass its preview_id (same `plan_file`; a bare name is looked up in plans/:
    "2026-10-20-tidy-all.plan.json" -> plans/2026-10-20-tidy-all.plan.json). Appends one log.md
    line itself. A long `items` list comes back as its first page; `paging.items.rest_in` names the
    undo record with all of them."""
    pid = preview_id_arg(preview_id, "dj_tidy_undo_preview")
    return run_paged(["tidy", "undo", "--apply", "--preview-id", pid], (repo_file(plan_file, (".json",), folder=PLANS),),
                     keys=("items",), rest_in="undo")


# -- Style Barber: taste text files in the library folder only (R-701, R-703) ----------------
#
# Like dj_plan, these write text files only (taste/*.md lines, .cache/barber.json, log.md), so
# they have no preview tool and no preview_id: the DJ's answer to the question is the consent,
# and every line is appended, never a rewrite. Exit code 2 here means "not a dj-library folder".

BARBER_ANSWER_MAX = 400  # characters; a free-text answer is one line (a lane name, a gig remark)


@server.tool(annotations=LIBRARY_TEXT)
def dj_barber_next() -> str:
    """Style Barber, in the configured dj-library folder: plan today's session (at most 8
    questions, about 10 minutes) or resume it, and return counts (questions, answered, skipped,
    left) and the next question: n, progress line, kind (ab, name_lane, veto, pair, gig),
    prompt, options/chips (empty = free text), tracks, the taste file an answer goes to.
    `archetype_line`: the DJ's archetype in one line, only with a new session's first question
    (say it once). `done` true = nothing left today. Writes only .cache/barber.json; never rekordbox.
    exit_code 2 = the dj-library folder is not set up: run dj-start first."""
    return run_dj(["library", "barber", "next"])


@server.tool(annotations=LIBRARY_TEXT)
@guarded
def dj_barber_record(n: int, answer: str) -> str:
    """Record the DJ's answer to question `n` of today's Style Barber session: appends one dated
    line to taste/anchors.md, lanes.md, vetoes.md or feedback.md (never rewrites), then returns
    the added lines and the next question, or "done". `answer` = what the DJ picked or typed: a
    chip (A, B, keep, never, good), its number (1, 2), free text for a lane name or gig remark,
    or skip. An answer the question does not take writes nothing (exit_code 1); exit_code 2 = the
    dj-library folder is not set up. Never touches rekordbox, Spotify or audio files."""
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= BARBER_MAX_QUESTIONS:
        raise ToolInputError(f"n must be a question number from 1 to {BARBER_MAX_QUESTIONS}.")
    if not isinstance(answer, str) or not answer.strip() or len(answer) > BARBER_ANSWER_MAX:
        raise ToolInputError(f"answer must be one line of 1 to {BARBER_ANSWER_MAX} characters.")
    if "\n" in answer or "\r" in answer:
        raise ToolInputError("answer must be one line.")
    return run_dj(["library", "barber", "record"], (str(n), answer.strip()))


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
