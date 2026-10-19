"""tree.yaml -> actions against the rekordbox playlist tree. Create only."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dj import rules as rules_mod

ROOT_ID = "root"
KIND_BY_ATTRIBUTE = {0: "playlist", 1: "folder", 4: "smart"}
KINDS = ("playlist", "folder", "smart")

CREATE, SKIP, CONFLICT, HOLD = "CREATE", "SKIP", "CONFLICT", "HOLD"


class TreeError(ValueError):
    """tree.yaml is invalid. Raised before the DB is touched."""


class ConflictError(RuntimeError):
    """The plan holds a CONFLICT. Nothing is written."""


@dataclass
class Node:
    kind: str
    name: str
    rules: list[dict[str, Any]] | None = None
    children: list["Node"] = field(default_factory=list)


@dataclass
class Action:
    op: str
    kind: str
    path: tuple[str, ...]
    # ID of the existing parent; None when the parent is itself created by this plan.
    parent_id: str | None
    rules: list[dict[str, Any]] | None = None
    note: str = ""

    @property
    def name(self) -> str:
        return self.path[-1]

    def line(self) -> str:
        creates = self.op in (CREATE, HOLD)
        label = f"{self.op} {self.kind}" if creates else f"{self.op} {self.note}"
        text = f"{label:<16} {' / '.join(self.path)}"
        if creates and self.kind == "smart":
            text += f"  {rules_mod.describe(self.rules)}"
        if self.op == HOLD:
            text += f"  <- {self.note}"
        return text


def norm(name: str) -> str:
    return name.strip().casefold()


def alive(row: Any) -> bool:
    """rekordbox flags a row it removed but has not purged yet; pyrekordbox still returns it."""
    return row is not None and not getattr(row, "rb_local_deleted", 0)


def children_of(db: Any, parent_id: str = ROOT_ID) -> list[Any]:
    """Existing nodes directly under parent_id, in rekordbox order."""
    nodes = [n for n in db.get_playlist(ParentID=parent_id).all() if alive(n)]
    return sorted(nodes, key=lambda n: n.Seq or 0)


# -- loading -----------------------------------------------------------------------------


def load_tree(path: Path) -> list[Node]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return parse_nodes(data, where="tree")


def parse_nodes(data: Any, where: str) -> list[Node]:
    if not isinstance(data, list):
        raise TreeError(f"{where}: expected a list of nodes")
    nodes, seen = [], set()
    for item in data:
        node = _parse_node(item, where)
        if norm(node.name) in seen:
            raise TreeError(f"{where}: duplicate name {node.name!r} at the same level")
        seen.add(norm(node.name))
        nodes.append(node)
    return nodes


def _parse_node(item: Any, where: str) -> Node:
    if not isinstance(item, dict):
        raise TreeError(f"{where}: each node is a mapping, got {item!r}")
    kinds = [k for k in KINDS if k in item]
    if len(kinds) != 1:
        raise TreeError(f"{where}: a node needs exactly one of {', '.join(KINDS)}: {item!r}")
    kind = kinds[0]
    name = item[kind]
    if not isinstance(name, str) or not name.strip():
        raise TreeError(f"{where}: {kind} name must be a non-empty string (quote it): {name!r}")
    name = name.strip()
    here = f"{where} / {name}"

    allowed = {kind} | {"folder": {"children"}, "smart": {"rules"}, "playlist": set()}[kind]
    unknown = set(item) - allowed
    if unknown:
        raise TreeError(f"{here}: unexpected key(s) for a {kind}: {', '.join(sorted(unknown))}")

    node = Node(kind=kind, name=name)
    if kind == "folder":
        node.children = parse_nodes(item.get("children") or [], where=here)
    if kind == "smart":
        try:
            rules_mod.conditions(item.get("rules"))
        except ValueError as exc:
            raise TreeError(f"{here}: {exc}") from exc
        node.rules = item["rules"]
    return node


# -- planning (reads only) ---------------------------------------------------------------


def walk(nodes: list[Node], db: Any) -> list[Action]:
    """One Action per node in tree.yaml. Reads the DB, never writes."""
    actions: list[Action] = []
    _walk(nodes, db, ROOT_ID, (), actions)
    return actions


def _walk(
    nodes: list[Node], db: Any, parent_id: str | None, prefix: tuple[str, ...], out: list[Action]
) -> None:
    existing: dict[str, list[Any]] = {}
    if parent_id is not None:
        for row in children_of(db, parent_id):
            existing.setdefault(norm(row.Name or ""), []).append(row)

    for node in nodes:
        path = prefix + (node.name,)
        matches = existing.get(norm(node.name), [])
        same_kind = [m for m in matches if KIND_BY_ATTRIBUTE.get(m.Attribute) == node.kind]
        if not matches:
            out.append(Action(CREATE, node.kind, path, parent_id, node.rules))
            _walk(node.children, db, None, path, out)
        elif same_kind:
            out.append(Action(SKIP, node.kind, path, parent_id, note="exists"))
            _walk(node.children, db, same_kind[0].ID, path, out)
        else:
            found = KIND_BY_ATTRIBUTE.get(matches[0].Attribute, f"attr={matches[0].Attribute}")
            note = f"exists as {found}, wanted {node.kind}; subtree left alone"
            out.append(Action(CONFLICT, node.kind, path, parent_id, note=note))


def hold_uncalibrated(actions: list[Action]) -> list[Action]:
    """CREATE smart -> HOLD where a rule encoding is not yet confirmed against rekordbox.

    A held node is simply not created this run; a later run creates it (idempotent).
    """
    for action in actions:
        if action.op == CREATE and action.kind == "smart":
            pending = rules_mod.uncalibrated(action.rules)
            if pending:
                action.op = HOLD
                action.note = f"encoding unconfirmed: {', '.join(sorted(pending))}"
    return actions


def counts(actions: list[Action]) -> dict[str, int]:
    return {op: sum(a.op == op for a in actions) for op in (CREATE, HOLD, SKIP, CONFLICT)}


# -- applying (create only) --------------------------------------------------------------


def apply(actions: list[Action], db: Any) -> int:
    """Run the CREATE actions. The caller commits. Never passes seq= (see CLAUDE.md)."""
    if any(a.op == CONFLICT for a in actions):
        raise ConflictError("The plan holds a CONFLICT. Resolve it first. Nothing written.")

    created: dict[tuple[str, ...], Any] = {}
    for action in actions:
        if action.op != CREATE:
            continue
        if action.parent_id is None:
            parent = created[action.path[:-1]]
        elif action.parent_id == ROOT_ID:
            parent = None
        else:
            parent = action.parent_id

        if action.kind == "folder":
            row = db.create_playlist_folder(action.name, parent=parent)
        elif action.kind == "playlist":
            row = db.create_playlist(action.name, parent=parent)
        else:
            smart = rules_mod.build_smartlist(action.rules)
            row = db.create_smart_playlist(action.name, smart, parent=parent)
        created[action.path] = row
    return len(created)
