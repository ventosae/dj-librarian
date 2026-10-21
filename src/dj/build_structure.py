"""dj-build: a proposal (tree as code) becomes a rekordbox XML the DJ imports (R-501..R-505).

Door 1 core: stdlib + PyYAML. Reads the latest export XML (`dj.readers.xml`) and
`structure/current-tree.yaml`; never opens master.db (R-504), never imports pyrekordbox.

    found = find_proposal(folder, "Build me the Lanes structure")    # or the slug, or the name
    p = preview(folder, ref)        # writes proposals/<slug>.yaml if missing + a gate record
    ... the DJ reads the preview and says yes ...
    r = apply(folder, ref, p.preview_id)   # writes proposals/<slug>.xml, one log.md line,
                                           # structure.chosen in library.yaml

Where a proposal comes from: `proposals/<slug>.yaml` first (the DJ may have edited it), then
the entry in `structure/proposals.yaml` (written by dj-report: a list of mappings with `slug`,
`name`, `family`, `principle`, `cost_minutes`, `trigger`, `lands`, `tree`). A reference is the
slug, the name (case ignored) or the trigger text "Build me the <name> structure".

The preview is `treeschema.diff(proposal, current tree)`: CREATE / SKIP / CONFLICT / MANUAL per
node. The tracks come from the latest export, so the diff is also run against that export's own
playlist tree: when `structure/current-tree.yaml` and the export disagree about a node of this
proposal (the tree file is older than the export), the build is blocked until dj-structure runs
again. A node that exists is spelled as it exists (rekordbox's own name), also in the XML and in
the import card. A CONFLICT, nothing to CREATE, or a build already written for exactly this
content blocks the build: no preview id is issued and `apply` refuses. The XML holds only the
CREATE nodes and their ancestor folders; playlists carry the tracks of their `from` playlists
(R-503); smart playlists are MANUAL (XML cannot carry rules). Tracks the DJ vetoed in
`taste/vetoes.md` ("never propose", R-702), and every copy of them (same artist and title), are
left out of those playlists; the preview counts them (`vetoed`) and the build's log line names
how many.

The digest the gate checks = the canonical proposal YAML + the current tree YAML + the export
(its path and tree) + the track ids of every playlist the XML will hold. Any change between
preview and apply -> refused.

Which library read the proposals came from (Q-17): each `structure/proposals.yaml` entry records
`source` (`dj.analysis.proposals`): the export, relative to the folder, or `master.db (snapshot
read <time>)`. The build reads the latest export, so it is blocked (no preview id; `apply` refuses)
when the export the entry names is gone from the folder, when the export the build reads is older
(file time) than that export, or, for a master.db read, older than the snapshot: playlists made
since would be missing. The line ends with `EXPORT_AGAIN`. An entry without `source` (a file from
before, a hand-made proposal) is not checked.

`apply` checks that `log.md` and `library.yaml` can take their change before it writes the XML.
Once the XML is written the build counts as done: a later failure (marking the preview used, the
log line, `structure.chosen`) comes back as a warning next to the written file, never as an error.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterable

import yaml

from dj import libfolder, treeschema
from dj.analysis.proposals import parse_source
from dj.gate import Gate, GateError, require_id
from dj.libfolder import LibraryFolder, LibraryFolderError
from dj.model import Library, LibraryError
from dj.readers.xml import read_xml
from dj.taste_files import read_vetoes
from dj.treeschema import (
    CONFLICT,
    CREATE,
    MANUAL,
    SKIP,
    DiffRow,
    TreeDoc,
    TreeNode,
    TreeSchemaError,
    norm,
)
from dj.writers.rekordbox_xml import (
    BuildError,
    XmlPlan,
    plan_xml,
    render,
    tracks_from,
    write_xml,
)

__all__ = [
    "BuildError",
    "BuildPreview",
    "BuildResult",
    "FoundProposal",
    "GateError",
    "apply",
    "find_proposal",
    "import_steps",
    "preview",
]

KIND = "build"  # the gate kind
CURRENT_TREE = "structure/current-tree.yaml"
PROPOSALS_FILE = "structure/proposals.yaml"
VETOES_FILE = "taste/vetoes.md"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TRIGGER = re.compile(r"^build\s+me\s+the\s+(.+?)\s+structure[.!]?$", re.IGNORECASE)
QUOTES = "\"'`“”‘’«»"
ROWS_LIMIT = 60  # rows in a JSON result; the rest are counted (NFR-03)
SHOWN = 5  # names in a message (lists <= 5)
MENU = {"mac": "rekordbox menu > Preferences", "windows": "File > Preferences"}
EXPORT_AGAIN = "Export again, then say the trigger prompt."


# -- finding the proposal ------------------------------------------------------------------


@dataclass(frozen=True)
class FoundProposal:
    """One proposal and where it was read from."""

    slug: str
    name: str
    doc: TreeDoc
    source: str  # relative path it was read from
    yaml_path: Path  # proposals/<slug>.yaml
    exists: bool  # proposals/<slug>.yaml was there (then `doc` is read from it)
    family: str = ""
    principle: str = ""
    cost_minutes: int | None = None
    trigger: str = ""
    warnings: tuple[str, ...] = ()
    made_from: str = ""  # the entry's `source` in structure/proposals.yaml: the read it was made from


def _folder(folder: LibraryFolder | str | Path) -> LibraryFolder:
    return folder if isinstance(folder, LibraryFolder) else LibraryFolder(Path(folder))


def _norm(text: Any) -> str:
    return " ".join(str(text).split()).casefold()


def _ref_keys(ref: str) -> set[str]:
    """The texts a reference may match: itself, and the name inside a trigger sentence."""
    if not isinstance(ref, str) or not ref.strip(QUOTES + " \t\r\n"):
        raise BuildError("Name the proposal: its slug, its name, or 'Build me the <name> structure'.")
    text = " ".join(ref.strip(QUOTES + " \t\r\n").split())
    keys = {_norm(text)}
    match = TRIGGER.match(text)
    if match:
        keys.add(_norm(match.group(1).strip(QUOTES + " ")))
    return keys


def _entries(folder: LibraryFolder) -> list[dict[str, Any]]:
    """The entries of structure/proposals.yaml; [] when the file is missing."""
    path = folder.root / PROPOSALS_FILE
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise BuildError(f"{PROPOSALS_FILE} is not valid YAML: {exc}") from exc
    except OSError as exc:
        raise BuildError(f"{PROPOSALS_FILE}: cannot read it ({exc.strerror or exc}).") from exc
    if isinstance(data, dict) and isinstance(data.get("proposals"), list):
        data = data["proposals"]
    if data is None:
        return []
    if not isinstance(data, list):
        raise BuildError(f"{PROPOSALS_FILE}: expected a list of proposals")
    entries = []
    slugs: dict[str, int] = {}
    names: dict[str, int] = {}
    for n, entry in enumerate(data, 1):
        where = f"{PROPOSALS_FILE} entry {n}"
        if not isinstance(entry, dict):
            raise BuildError(f"{where}: expected a mapping")
        slug, name = entry.get("slug"), entry.get("name")
        if not isinstance(slug, str) or not SLUG.match(slug):
            raise BuildError(f"{where}: slug must be lower-case letters, digits and '-', got {slug!r}")
        if not isinstance(name, str) or not name.strip():
            raise BuildError(f"{where}: name must be a non-empty text")
        if not isinstance(entry.get("tree"), list):
            raise BuildError(f"{where} ({slug}): needs a `tree:` list")
        if slug in slugs:  # one slug = one proposals/<slug>.yaml: two entries would mix up
            raise BuildError(f"{where}: slug {slug!r} is also entry {slugs[slug]}. Run dj-report again.")
        if _norm(name) in names:
            raise BuildError(f"{where}: name {name.strip()!r} is also entry {names[_norm(name)]}. Run dj-report again.")
        slugs[slug], names[_norm(name)] = n, n
        entries.append(entry)
    return entries


def _proposal_files(folder: LibraryFolder) -> dict[str, Path]:
    """slug -> proposals/<slug>.yaml, for every file named like a slug."""
    if not folder.proposals.is_dir():
        return {}
    return {
        p.stem: p
        for p in sorted(folder.proposals.iterdir())
        if p.suffix == ".yaml" and SLUG.match(p.stem) and p.is_file()
    }


def _load_proposal(path: Path, folder: LibraryFolder) -> TreeDoc:
    try:
        return treeschema.load(path)
    except (TreeSchemaError, UnicodeDecodeError) as exc:
        rel = folder.relative(path)
        raise BuildError(f"{rel}: {exc}. Fix the file and preview again.") from exc
    except OSError as exc:
        raise BuildError(f"{folder.relative(path)}: cannot read it ({exc.strerror or exc}).") from exc


def _entry_doc(entry: dict[str, Any]) -> TreeDoc:
    data: dict[str, Any] = {"tree": entry["tree"], "name": entry["name"].strip()}
    for key in ("family", "principle"):
        if isinstance(entry.get(key), str) and entry[key].strip():
            data[key] = entry[key].strip()
    try:
        return treeschema.parse(data, f"{PROPOSALS_FILE} / {entry['slug']}")
    except TreeSchemaError as exc:
        raise BuildError(str(exc)) from exc


def find_proposal(folder: LibraryFolder | str | Path, ref: str) -> FoundProposal:
    """Look a proposal up by slug, name or trigger text. Not found / ambiguous -> BuildError."""
    folder = _folder(folder)
    keys = _ref_keys(ref)
    files = _proposal_files(folder)
    try:
        entries, broken = _entries(folder), None
    except BuildError as exc:  # the DJ's own proposals/<slug>.yaml still wins (below)
        entries, broken = [], exc

    matches: dict[str, str] = {}  # slug -> how it matched
    for entry in entries:
        texts = {_norm(entry["slug"]), _norm(entry["name"])}
        if isinstance(entry.get("trigger"), str):
            texts.add(_norm(entry["trigger"]))
        if keys & texts:
            matches.setdefault(entry["slug"], PROPOSALS_FILE)
    for slug, path in files.items():
        texts = {_norm(slug)}
        if slug not in matches and not keys & texts:
            try:  # a hand-made or renamed proposal: match its name too
                name = treeschema.load(path).meta.get("name")
            except (TreeSchemaError, UnicodeDecodeError, OSError):
                name = None
            if name:
                texts.add(_norm(name))
        if keys & texts:
            matches.setdefault(slug, folder.relative(path))

    if broken is not None and not matches:
        raise broken  # the reference may be in the file that cannot be read
    if not matches:
        known = sorted({e["name"] for e in entries} | set(files))
        listed = ", ".join(known[:SHOWN]) + (f" (+{len(known) - SHOWN} more)" if len(known) > SHOWN else "")
        hint = f" Known: {listed}." if known else f" No proposals yet: run dj-report first ({PROPOSALS_FILE})."
        raise BuildError(f"No proposal matches {ref.strip()!r}.{hint}")
    if len(matches) > 1:
        raise BuildError(f"{ref.strip()!r} matches {len(matches)} proposals: {', '.join(sorted(matches))}. Use the slug.")

    (slug,) = matches
    entry = next((e for e in entries if e["slug"] == slug), {})
    yaml_path = folder.proposals / f"{slug}.yaml"
    exists = yaml_path.is_file()
    if exists:
        doc, source = _load_proposal(yaml_path, folder), folder.relative(yaml_path)
    else:
        doc, source = _entry_doc(entry), PROPOSALS_FILE
    cost = entry.get("cost_minutes")
    made_from = entry.get("source")
    warnings: tuple[str, ...] = ()
    if broken is not None:  # one line: a YAML error spans several
        warnings = (f"{' '.join(str(broken).split())} Read {source} alone.",)
    return FoundProposal(
        slug=slug,
        name=str(doc.meta.get("name") or entry.get("name") or slug),
        doc=doc,
        source=source,
        yaml_path=yaml_path,
        exists=exists,
        family=str(doc.meta.get("family") or entry.get("family") or ""),
        principle=str(doc.meta.get("principle") or entry.get("principle") or ""),
        cost_minutes=cost if isinstance(cost, int) and not isinstance(cost, bool) else None,
        trigger=str(entry.get("trigger") or f"Build me the {doc.meta.get('name') or slug} structure"),
        warnings=warnings,
        made_from=" ".join(made_from.split()) if isinstance(made_from, str) else "",
    )


# -- the state a preview and an apply both compute -----------------------------------------


@dataclass(frozen=True)
class _State:
    rows: tuple[DiffRow, ...]
    plan: XmlPlan
    digest: str
    counts: dict[str, int]
    lands: tuple[dict[str, Any], ...]
    blocked: str | None
    export: str


def _current_tree(folder: LibraryFolder) -> TreeDoc:
    path = folder.root / CURRENT_TREE
    if not path.is_file():
        raise BuildError(f"{CURRENT_TREE} not found: run dj-structure first.")
    try:
        return treeschema.load(path)
    except (TreeSchemaError, UnicodeDecodeError) as exc:
        raise BuildError(f"{CURRENT_TREE}: {exc}. Run dj-structure again.") from exc
    except OSError as exc:
        raise BuildError(f"{CURRENT_TREE}: cannot read it ({exc.strerror or exc}).") from exc


def _library(folder: LibraryFolder) -> tuple[Library, str]:
    try:
        export = libfolder.latest_export(folder.root)
        return read_xml(export), folder.relative(export)
    except (LibraryFolderError, LibraryError) as exc:
        raise BuildError(str(exc)) from exc


def _source_block(folder: LibraryFolder, made_from: str, export: str) -> str | None:
    """Why the proposal cannot be built from `export` (the export the build reads, relative), or
    None (Q-17, see the module docstring).

    Times are the files' modification times. `libfolder.import_export` keeps the time rekordbox
    wrote the export, so an old export imported late still reads as old. The limit: a file put
    into exports/ by other means carries whatever time that copy gave it."""
    if not made_from:
        return None
    read = folder.root / export
    kind, value = parse_source(made_from)
    if kind == "db":
        mtime = datetime.fromtimestamp(read.stat().st_mtime, tz=timezone.utc)
        when = value if isinstance(value, datetime) else None
        if when is not None and when.tzinfo is None:
            when = when.astimezone()  # a naive time is this computer's local time
        if when is None or mtime < when:
            stamp = _local(when.isoformat()) if when else "a time it does not say"
            return (
                f"{PROPOSALS_FILE} was made from master.db (read {stamp}), after the newest export "
                f"({export}): a playlist made since that export is not in it. {EXPORT_AGAIN}"
            )
        return None
    rel = Path(str(value))
    named = folder.root / rel
    if rel.is_absolute() or ".." in rel.parts or not named.is_file():
        return f"{PROPOSALS_FILE} was made from {value}, which is not in exports/ any more. {EXPORT_AGAIN}"
    if named.resolve() != read.resolve() and read.stat().st_mtime_ns < named.stat().st_mtime_ns:
        return (
            f"{PROPOSALS_FILE} was made from {value}, which is newer than the export dj-build reads "
            f"({export}). {EXPORT_AGAIN}"
        )
    return None


def _vetoed(folder: LibraryFolder, lib: Library) -> frozenset[str]:
    """The track ids `taste/vetoes.md` says never to propose (R-702), with every copy of each in
    `lib` (a veto names the song: `Vetoes.with_copies`); none when the file is missing."""
    try:
        return read_vetoes(folder.root / VETOES_FILE).with_copies(lib.tracks.values()).never_propose
    except LibraryError as exc:
        raise BuildError(f"{VETOES_FILE}: {exc}") from exc
    except OSError as exc:
        raise BuildError(f"{VETOES_FILE}: cannot read it ({exc.strerror or exc}).") from exc


def _only(rows: Iterable[DiffRow]) -> set[tuple[str, ...]]:
    """The CREATE nodes and every ancestor folder above them."""
    out: set[tuple[str, ...]] = set()
    for row in rows:
        if row.op == CREATE:
            out.update(row.path[:n] for n in range(1, len(row.path) + 1))
    return out


def _export_tree(lib: Library, current: TreeDoc) -> TreeDoc:
    """The playlist tree of the export the tracks are read from: names and kinds only.

    An XML export cannot carry a smart playlist as one: it shows it as a plain playlist (NODE
    Type 1) or leaves it out. So the current tree's smart playlists count as they are: one the
    export shows under that name stays smart, one it lacks is added (smart playlists never go
    into the XML; this only keeps them SKIP).
    """

    def level(nodes: Iterable[Any], known: tuple[TreeNode, ...]) -> tuple[TreeNode, ...]:
        smart = {norm(n.name): n for n in known if n.kind == "smart"}
        folders: dict[str, tuple[TreeNode, ...]] = {}
        for n in known:
            if n.kind == "folder":
                folders.setdefault(norm(n.name), n.children)
        out = []
        for node in nodes:
            key = norm(node.name)
            if node.kind == "folder":
                out.append(TreeNode("folder", node.name, children=level(node.children, folders.get(key, ()))))
            elif node.kind == "smart" or key in smart:
                out.append(TreeNode("smart", node.name))
            else:
                out.append(TreeNode("playlist", node.name))
        shown = {norm(n.name) for n in out}
        out += [TreeNode("smart", n.name) for key, n in smart.items() if key not in shown]
        return tuple(out)

    return TreeDoc(level(lib.roots, current.nodes), {})


def _row_key(row: DiffRow) -> tuple[str, str, tuple[str, ...]]:
    return row.op, row.kind, tuple(norm(p) for p in row.path)


def _stale(doc: TreeDoc, current: TreeDoc, exported: TreeDoc, export: str) -> str | None:
    """Why current-tree.yaml cannot be trusted for this proposal, or None.

    Both trees must give every node of the proposal the same row. They differ when the tree
    file was made from another export than the one the tracks come from (hard rule 5: a node
    that exists in rekordbox must come out SKIP, never CREATE)."""
    by_current = treeschema.diff(doc, current)
    by_export = treeschema.diff(doc, exported)
    # Both walk the proposal in the same order, so the first difference is at one node.
    for a, b in zip_longest(by_current, by_export):
        if a is None or b is None or _row_key(a) != _row_key(b):
            row = a if a is not None else b
            said = f"it says {a.op if a else 'nothing'}, the export says {b.op if b else 'nothing'}"
            return (
                f"{CURRENT_TREE} is older than the latest export ({export}): for "
                f"{'/'.join(row.path)} {said}. Run dj-structure again, then preview again."
            )
    return None


def _spelled(nodes: Iterable[TreeNode], existing: Iterable[TreeNode]) -> tuple[TreeNode, ...]:
    """`nodes` with every node that exists (same name ignoring case and outer spaces, same kind,
    as `treeschema.diff` matches) spelled as it exists, down the tree. The XML folders a new
    playlist sits in and the import card then carry rekordbox's own names (hard rule 5)."""
    by_name: dict[str, list[TreeNode]] = {}
    for node in existing:
        by_name.setdefault(norm(node.name), []).append(node)
    out = []
    for node in nodes:
        same = [e for e in by_name.get(norm(node.name), []) if e.kind == node.kind]
        if same:
            node = replace(node, name=same[0].name, children=_spelled(node.children, same[0].children))
        out.append(node)
    return tuple(out)


def _digest(doc: TreeDoc, current: TreeDoc, exported: TreeDoc, export: str, plan: XmlPlan) -> str:
    payload = {
        "proposal": treeschema.dumps(doc),
        "current": treeschema.dumps(current),
        "export": export,
        "export_tree": [[list(path), node.kind] for path, node in treeschema.walk(exported)],
        "tracks": plan.playlist_tracks(),
    }
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _blocked(rows: tuple[DiffRow, ...], yaml_rel: str) -> str | None:
    conflicts = [r for r in rows if r.op == CONFLICT]
    if conflicts:
        names = ", ".join("/".join(r.path) for r in conflicts[:SHOWN])
        more = f" (+{len(conflicts) - SHOWN} more)" if len(conflicts) > SHOWN else ""
        return (
            f"{len(conflicts)} conflict(s): {names}{more} exist as another kind. Rename them in "
            f"{yaml_rel} and preview again."
        )
    if not any(r.op == CREATE for r in rows):
        manual = sum(r.op == MANUAL for r in rows)
        by_hand = f" The {manual} smart playlist(s) are made by hand in rekordbox." if manual else ""
        return f"Nothing to create: every folder and playlist of this proposal exists already.{by_hand}"
    return None


def _state(
    slug: str,
    doc: TreeDoc,
    current: TreeDoc,
    lib: Library,
    export: str,
    vetoed: frozenset[str] = frozenset(),
) -> _State:
    exported = _export_tree(lib, current)
    stale = _stale(doc, current, exported, export)
    spelled = TreeDoc(_spelled(doc.nodes, exported.nodes), doc.meta)
    rows = tuple(treeschema.diff(spelled, exported))  # the same rows as against current, or stale
    plan = plan_xml(spelled, lib, only=_only(rows), vetoed=vetoed)  # BuildError for an unknown `from`
    lands = []
    for row in rows:
        if row.op == CREATE and row.kind == "playlist":
            for source in row.fill_from:
                ids = tracks_from(lib, [source], "/".join(row.path))
                n = sum(tid not in vetoed for tid in ids)
                lands.append({"from": source, "to": "/".join(row.path), "tracks": n})
    counts = {
        "create": sum(r.op == CREATE for r in rows),
        "skip": sum(r.op == SKIP for r in rows),
        "conflict": sum(r.op == CONFLICT for r in rows),
        "manual": sum(r.op == MANUAL for r in rows),
        "tracks": len(plan.tracks),
    }
    return _State(
        rows=rows,
        plan=plan,
        digest=_digest(doc, current, exported, export, plan),
        counts=counts,
        lands=tuple(lands),
        blocked=stale or _blocked(rows, f"proposals/{slug}.yaml"),
        export=export,
    )


def _row_dict(row: DiffRow) -> dict[str, Any]:
    out: dict[str, Any] = {"op": row.op, "kind": row.kind, "path": "/".join(row.path)}
    if row.fill_from:
        out["from"] = list(row.fill_from)
    if row.note:
        out["note"] = row.note
    return out


def _capped(items: list[Any], limit: int) -> tuple[list[Any], int]:
    return items[:limit], max(0, len(items) - limit)


# -- preview (R-501) -----------------------------------------------------------------------


@dataclass(frozen=True)
class BuildPreview:
    rows: tuple[DiffRow, ...]
    counts: dict[str, int]
    digest: str
    preview_id: str | None  # None when the build is blocked: nothing to approve
    yaml_path: Path
    slug: str = ""
    name: str = ""
    yaml_created: bool = False  # this preview wrote proposals/<slug>.yaml
    lands: tuple[dict[str, Any], ...] = ()
    blocked: str | None = None
    export: str = ""  # the export the tracks were read from (relative)
    unplaced: tuple[str, ...] = ()  # track ids without a file location, left out
    warnings: tuple[str, ...] = ()
    vetoed: tuple[str, ...] = ()  # track ids taste/vetoes.md says never to propose, left out (R-702)

    def to_dict(self, folder: LibraryFolder | str | Path, limit: int = ROWS_LIMIT) -> dict[str, Any]:
        rows, rows_more = _capped([_row_dict(r) for r in self.rows], limit)
        lands, lands_more = _capped(list(self.lands), SHOWN)
        return {
            "counts": self.counts,
            "proposal": self.slug,
            "name": self.name,
            "preview_id": self.preview_id,
            "blocked": self.blocked,
            "written": "Nothing written yet.",
            "yaml": _folder(folder).relative(self.yaml_path),
            "yaml_created": self.yaml_created,
            "export": self.export,
            "rows": rows,
            "rows_more": rows_more,
            "lands": lands,
            "lands_more": lands_more,
            "unplaced": len(self.unplaced),
            "vetoed": len(self.vetoed),
            "warnings": list(self.warnings),
        }


def _local(stamp: str) -> str:
    """A stored ISO time as local 'YYYY-MM-DD HH:MM' (the text as it is if unreadable)."""
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return str(stamp)
    return (moment.astimezone() if moment.tzinfo else moment).strftime("%Y-%m-%d %H:%M")


def _already_built(gate: Gate, preview_id: str, slug: str) -> str | None:
    """The block for a build already written for exactly this content (one preview, one write)."""
    record = gate.load(preview_id)
    if not record.used:
        return None
    wrote = record.written or "an XML in proposals/"
    return (
        f"Already built on {_local(record.used)}: {wrote}. Import that file; it holds this exact "
        f"build. For a new build, change proposals/{slug}.yaml and preview again."
    )


def _with_meta(found: FoundProposal, today: date) -> TreeDoc:
    meta = {"name": found.name}
    if found.family:
        meta["family"] = found.family
    if found.principle:
        meta["principle"] = found.principle
    meta["source"] = PROPOSALS_FILE
    meta["generated"] = today.isoformat()
    return TreeDoc(found.doc.nodes, meta)


def preview(
    folder: LibraryFolder | str | Path,
    ref: str,
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> BuildPreview:
    """CREATE / SKIP / CONFLICT / MANUAL per node, and a preview id for the gate.

    Writes `proposals/<slug>.yaml` when it does not exist yet (create-only; an existing one is
    read as the DJ left it) and the gate record in `.cache/previews/`. Nothing else: no XML.
    """
    folder = _folder(folder)
    current = _current_tree(folder)
    found = find_proposal(folder, ref)
    lib, export = _library(folder)

    created = False
    if not found.exists:
        text = treeschema.dumps(_with_meta(found, today or (now.date() if now else date.today())))
        folder.proposals.mkdir(exist_ok=True)
        created = libfolder.write_new_text(found.yaml_path, text)
    doc = _load_proposal(found.yaml_path, folder)  # the file wins, also over what we just wrote

    state = _state(found.slug, doc, current, lib, export, _vetoed(folder, lib))
    preview_id, blocked = None, _source_block(folder, found.made_from, export) or state.blocked
    if blocked is None:
        gate = Gate(folder.cache)
        preview_id = gate.record(KIND, {"proposal": found.slug}, state.digest, now=now)
        blocked = _already_built(gate, preview_id, found.slug)
        if blocked:
            preview_id = None
    return BuildPreview(
        rows=state.rows,
        counts=state.counts,
        digest=state.digest,
        preview_id=preview_id,
        yaml_path=found.yaml_path,
        slug=found.slug,
        name=str(doc.meta.get("name") or found.name),
        yaml_created=created,
        lands=state.lands,
        blocked=blocked,
        export=export,
        unplaced=state.plan.unplaced,
        warnings=found.warnings,
        vetoed=state.plan.vetoed,
    )


# -- apply (R-502..R-505) ------------------------------------------------------------------


@dataclass(frozen=True)
class BuildResult:
    xml_path: Path
    rows: tuple[DiffRow, ...]
    import_steps: tuple[str, ...]
    log_line: str
    slug: str = ""
    xml_file: str = ""  # relative to the library folder
    counts: dict[str, int] = field(default_factory=dict)
    drags: tuple[dict[str, str], ...] = ()
    device: str = ""
    warnings: tuple[str, ...] = ()  # the XML is written; what went wrong after it

    def to_dict(self) -> dict[str, Any]:
        moves, moves_more = _capped(list(self.drags), SHOWN)
        return {
            "counts": self.counts,
            "proposal": self.slug,
            "written": self.xml_file,
            "device": self.device,
            "import_steps": list(self.import_steps),
            "drags": moves,
            "drags_more": moves_more,
            "log_line": self.log_line,
            "warnings": list(self.warnings),
        }


def drags(rows: Iterable[DiffRow]) -> list[dict[str, str]]:
    """The new subtrees the DJ drags from "rekordbox xml" into place: the CREATE nodes whose
    parent is not new itself, and where each one goes ("Playlists" = the top level)."""
    rows = list(rows)
    created = {r.path for r in rows if r.op == CREATE}
    out = []
    for row in rows:
        if row.op == CREATE and row.path[:-1] not in created:
            out.append({"node": "/".join(row.path), "into": "/".join(row.path[:-1]) or "Playlists"})
    return out


def import_steps(
    device: str, xml_file: str, moves: list[dict[str, str]] | None = None, *, folder: str = "your dj-library folder"
) -> tuple[str, ...]:
    """The import card for the DJ's OS (R-502): three steps. `folder` names where `xml_file`
    sits (the inbox loop's XML can sit in the dj-librarian folder, `dj.writers.adds_xml`)."""
    if device not in MENU:
        raise BuildError(f"device must be one of {', '.join(MENU)}, got {device!r}")
    moves = list(moves or [])
    shown = "; ".join(f"{m['node']} into {m['into']}" for m in moves[:SHOWN])
    more = f"; +{len(moves) - SHOWN} more" if len(moves) > SHOWN else ""
    where = f": {shown}{more}" if moves else ""
    return (
        f"In rekordbox open {MENU[device]} > Advanced > Database > rekordbox xml > Imported Library "
        f"> Browse, pick {xml_file} in {folder}, close Preferences.",
        'In the tree view turn on "rekordbox xml" and open it.',
        f"Drag the new playlists into Playlists{where}.",
    )


def _meta_device(folder: LibraryFolder) -> str:
    try:
        meta = libfolder.load_meta(folder.root)
    except LibraryFolderError as exc:
        raise BuildError(str(exc)) from exc
    errors = libfolder.validate_meta(meta)
    if errors:
        raise BuildError("library.yaml: " + "; ".join(errors) + ". Nothing was written.")
    return str(meta["device"])


def _preflight(folder: LibraryFolder, slug: str) -> None:
    """Before the XML is written: log.md takes a line and library.yaml takes structure.chosen.

    Opening a file to append writes nothing; it fails when the file is a folder, read-only or
    held by another program (a cloud-sync client, an editor)."""
    try:
        meta = libfolder.load_meta(folder.root)
    except LibraryFolderError as exc:
        raise BuildError(f"{exc} Nothing was written.") from exc
    structure = meta.get("structure") if isinstance(meta.get("structure"), dict) else {}
    errors = libfolder.validate_meta({**meta, "structure": {**structure, "chosen": slug}})
    if errors:
        raise BuildError("library.yaml: " + "; ".join(errors) + ". Nothing was written.")
    for path in (folder.log, folder.library_yaml):
        if not path.exists():
            continue  # log.md is created with its title line when missing
        try:
            with open(path, "a", encoding="utf-8"):
                pass
        except OSError as exc:
            raise BuildError(
                f"{folder.relative(path)} cannot be written ({exc.strerror or exc}). Close what holds "
                "it open, then write again with the same preview id. Nothing was written."
            ) from exc


def _log_text(slug: str, counts: dict[str, int], xml_file: str, now: datetime | None, today: date | None = None) -> str:
    """The log.md line `append_log` writes, for the warning when it could not be written."""
    told = ", ".join(f"{n} {key}" for key, n in counts.items())
    return f"{libfolder.log_clock(today, now)} build {slug} -> {told}; {xml_file}"


def product_version() -> str:
    """dj-librarian's version for the XML's PRODUCT line: the installed package, else the
    clone's pyproject.toml, else the plugin's plugin.json (the core vendored in the plugin zip
    sits in `<plugin>/vendor/dj/`, D-22)."""
    from importlib import metadata

    try:
        return metadata.version("dj-librarian")
    except metadata.PackageNotFoundError:
        pass
    above = Path(__file__).resolve().parents[2]  # the clone, or the plugin folder
    try:
        import tomllib  # Python 3.11+; Cowork's sandbox may run 3.10

        pyproject = above / "pyproject.toml"
        return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
    except (ImportError, OSError, KeyError, ValueError):
        pass
    try:
        manifest = json.loads((above / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        return str(manifest["version"])
    except (OSError, KeyError, TypeError, ValueError):
        return "unknown"


def apply(
    folder: LibraryFolder | str | Path,
    ref: str,
    preview_id: str,
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> BuildResult:
    """Write `proposals/<slug>.xml` for a preview the DJ said yes to. Refuses (GateError /
    BuildError, nothing written) without a valid preview id, after any change since the
    preview, on a CONFLICT, with nothing to create, or when log.md / library.yaml cannot take
    their change. Once the XML is written, a later failure is a warning in the result. Never
    opens master.db (R-504)."""
    require_id(preview_id)  # no id, no write: refused before anything is read
    folder = _folder(folder)
    device = _meta_device(folder)
    current = _current_tree(folder)
    found = find_proposal(folder, ref)
    if not found.exists:
        raise BuildError(f"proposals/{found.slug}.yaml is missing: run the preview first.")
    lib, export = _library(folder)
    state = _state(found.slug, found.doc, current, lib, export, _vetoed(folder, lib))
    blocked = _source_block(folder, found.made_from, export) or state.blocked
    if blocked:
        raise BuildError(blocked + " Nothing was written.")
    gate = Gate(folder.cache)
    gate.check(preview_id, KIND, {"proposal": found.slug}, state.digest, now=now)
    _preflight(folder, found.slug)

    text = render(state.plan, product_version=product_version())
    xml_path = write_xml(text, folder.proposals / f"{found.slug}.xml")
    # The XML is written: from here on the build is done, and a failure below is a warning.
    xml_file = folder.relative(xml_path)
    counts = {k: state.counts[k] for k in ("create", "skip", "manual", "tracks")}
    if state.plan.vetoed:
        counts["vetoed"] = len(state.plan.vetoed)
    warnings = list(found.warnings)
    try:
        gate.consume(preview_id, now=now, written=xml_file)
    except (GateError, OSError) as exc:
        warnings.append(f"Preview {preview_id} could not be marked used ({exc}). Do not use it again.")
    try:
        log_line = libfolder.append_log(folder.root, f"build {found.slug}", counts, file=xml_path, now=now, today=today)
    except (LibraryFolderError, OSError) as exc:
        log_line = _log_text(found.slug, counts, xml_file, now, today)
        warnings.append(f"log.md: the build line was not added ({exc}). Add it by hand: {log_line}")
    try:
        libfolder.update_meta(
            folder.root, today=today or (now.date() if now else None), structure={"chosen": found.slug}
        )
    except (LibraryFolderError, OSError) as exc:
        warnings.append(f"library.yaml: structure.chosen was not set to {found.slug} ({exc}).")
    moves = drags(state.rows)
    return BuildResult(
        xml_path=xml_path,
        rows=state.rows,
        import_steps=import_steps(device, xml_file, moves),
        log_line=log_line,
        slug=found.slug,
        xml_file=xml_file,
        counts=counts,
        drags=tuple(moves),
        device=device,
        warnings=tuple(warnings),
    )
