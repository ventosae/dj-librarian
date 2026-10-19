"""One tree schema for `bases.yaml`, `structure/current-tree.yaml` and `proposals/*.yaml` (R-903).

Door 1 core: stdlib + PyYAML only. `dj.tree` (which pulls pyrekordbox) is imported lazily,
in `to_tree_nodes` only. `dj.rules` is never imported: the v1 rule shapes are checked here
and a test pins `RULE_TYPES` to `dj.rules.RULE_TYPES`.

A file is either a bare list of nodes (the `bases.yaml` shape, which `dj tree` also reads) or a
mapping `{tree: [...], name?, family?, principle?, source?, generated?}`. Each node has exactly
one of `playlist | folder | smart`:

    - folder: house_base
      children:
        - playlist: 1.2_groovy
          from: [old/groovy, old/deep]    # existing playlists whose tracks pre-fill it (R-503)
        - smart: house
          rules: [{genre_contains: house}]   # v1 rules (dj.rules)
        - smart: dark and fast
          rules_raw: "My Tag is dark AND BPM > 130"   # what v1 rules cannot say

Unknown keys and two names at one level that differ only in case or outer spaces are errors.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import yaml

KINDS = ("playlist", "folder", "smart")
META_KEYS = ("name", "family", "principle", "source", "generated")
_ALLOWED = {"playlist": {"from"}, "folder": {"children"}, "smart": {"rules", "rules_raw"}}

CREATE, SKIP, CONFLICT, MANUAL = "CREATE", "SKIP", "CONFLICT", "MANUAL"
OPS = (CREATE, SKIP, CONFLICT, MANUAL)


class TreeSchemaError(ValueError):
    """A tree file breaks the schema. Raised before anything is written."""


# -- v1 rule shapes (mirror of dj.rules; a test keeps the two in step) -------------------


def _text(value: Any, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TreeSchemaError(f"{key}: expected a non-empty string, got {value!r}")


def _whole(value: Any, key: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise TreeSchemaError(f"{key}: expected a whole number {low}-{high}, got {value!r}")
    return value


def _bpm_range(value: Any) -> None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise TreeSchemaError(f"bpm_range: expected [low, high], got {value!r}")
    low, high = (_whole(v, "bpm_range", 1, 999) for v in value)
    if low >= high:
        raise TreeSchemaError(f"bpm_range: low must be below high, got {value!r}")


_RULE_CHECKS = {
    "genre_contains": lambda v: _text(v, "genre_contains"),
    "comment_contains": lambda v: _text(v, "comment_contains"),
    "bpm_range": _bpm_range,
    "rating_min": lambda v: _whole(v, "rating_min", 1, 5),
    "added_last_days": lambda v: _whole(v, "added_last_days", 1, 3650),
}
RULE_TYPES = tuple(_RULE_CHECKS)


def check_rules(rules: Any) -> None:
    """A smart node's `rules:` list must be non-empty, one `type: value` pair per rule."""
    if not isinstance(rules, (list, tuple)) or not rules:
        raise TreeSchemaError("rules: expected a non-empty list")
    for rule in rules:
        if not isinstance(rule, Mapping) or len(rule) != 1:
            raise TreeSchemaError(f"rules: each rule is a single `type: value` pair, got {rule!r}")
        ((key, value),) = rule.items()
        if key not in _RULE_CHECKS:
            known = ", ".join(RULE_TYPES)
            raise TreeSchemaError(f"rules: unknown rule type {key!r} (v1 supports: {known})")
        _RULE_CHECKS[key](value)


# -- the model -----------------------------------------------------------------------------


def _plain_rule(rule: Any) -> Any:
    if not isinstance(rule, Mapping):
        return rule
    return {k: list(v) if isinstance(v, tuple) else v for k, v in rule.items()}


@dataclass(frozen=True)
class TreeNode:
    kind: str
    name: str
    children: tuple["TreeNode", ...] = ()
    rules: tuple[dict[str, Any], ...] | None = None
    rules_raw: str | None = None
    fill_from: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Lists given in code become tuples, so equality does not depend on the container.
        if isinstance(self.children, list):
            object.__setattr__(self, "children", tuple(self.children))
        if isinstance(self.fill_from, list):
            object.__setattr__(self, "fill_from", tuple(self.fill_from))
        if isinstance(self.rules, (list, tuple)):
            object.__setattr__(self, "rules", tuple(_plain_rule(r) for r in self.rules))


@dataclass(frozen=True)
class TreeDoc:
    nodes: tuple[TreeNode, ...]
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.nodes, list):
            object.__setattr__(self, "nodes", tuple(self.nodes))
        meta = {k: v.isoformat() if isinstance(v, date) else v for k, v in dict(self.meta).items()}
        object.__setattr__(self, "meta", meta)


@dataclass(frozen=True)
class DiffRow:
    op: str
    kind: str
    path: tuple[str, ...]
    fill_from: tuple[str, ...] = ()
    note: str = ""


def norm(name: str) -> str:
    """Same as dj.tree.norm: names match ignoring outer spaces and case."""
    return name.strip().casefold()


# -- parsing -------------------------------------------------------------------------------


def parse(data: Any, where: str = "tree") -> TreeDoc:
    """A safe-loaded YAML value -> TreeDoc. Every problem -> TreeSchemaError naming the node."""
    if isinstance(data, list):
        return TreeDoc(_parse_level(data, where), {})
    if isinstance(data, dict):
        unknown = sorted(map(str, set(data) - {"tree", *META_KEYS}))
        if unknown:
            raise TreeSchemaError(f"{where}: unexpected top-level key(s): {', '.join(unknown)}")
        if "tree" not in data:
            raise TreeSchemaError(f"{where}: a mapping needs a `tree:` list of nodes")
        meta = {key: _meta_value(data[key], f"{where}: {key}") for key in META_KEYS if key in data}
        return TreeDoc(_parse_level(data["tree"], where), meta)
    raise TreeSchemaError(f"{where}: expected a list of nodes, or a mapping with a `tree:` list")


def load(path: str | Path) -> TreeDoc:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TreeSchemaError(f"{path.name}: not valid YAML: {exc}") from exc
    return parse(data, where=path.name)


def _meta_value(value: Any, where: str) -> str:
    if isinstance(value, date):  # an unquoted date in a hand-written file
        return value.isoformat()
    if not isinstance(value, str):
        raise TreeSchemaError(f"{where}: expected text, got {value!r}")
    return value


def _parse_level(items: Any, where: str) -> tuple[TreeNode, ...]:
    if not isinstance(items, list):
        raise TreeSchemaError(f"{where}: expected a list of nodes, got {items!r}")
    nodes: list[TreeNode] = []
    seen: dict[str, str] = {}
    for item in items:
        node = _parse_node(item, where)
        key = norm(node.name)
        if key in seen:
            raise TreeSchemaError(
                f"{where}: duplicate name {node.name!r} at the same level (also {seen[key]!r})"
            )
        seen[key] = node.name
        nodes.append(node)
    return tuple(nodes)


def _parse_node(item: Any, where: str) -> TreeNode:
    if not isinstance(item, dict):
        raise TreeSchemaError(f"{where}: each node is a mapping, got {item!r}")
    kinds = [k for k in KINDS if k in item]
    if len(kinds) != 1:
        raise TreeSchemaError(f"{where}: a node needs exactly one of {', '.join(KINDS)}: {item!r}")
    kind = kinds[0]
    name = item[kind]
    if not isinstance(name, str) or not name.strip():
        raise TreeSchemaError(
            f"{where}: {kind} name must be a non-empty string (quote it): {name!r}"
        )
    name = name.strip()
    here = f"{where} / {name}"

    unknown = sorted(map(str, set(item) - {kind} - _ALLOWED[kind]))
    if unknown:
        raise TreeSchemaError(f"{here}: unexpected key(s) for a {kind}: {', '.join(unknown)}")

    if kind == "folder":
        return TreeNode(kind, name, children=_parse_level(item.get("children") or [], here))
    if kind == "playlist":
        return TreeNode(kind, name, fill_from=_parse_from(item.get("from"), here))

    if "rules" in item and "rules_raw" in item:
        raise TreeSchemaError(f"{here}: a smart playlist has `rules` or `rules_raw`, not both")
    if "rules" in item:
        try:
            check_rules(item["rules"])
        except TreeSchemaError as exc:
            raise TreeSchemaError(f"{here}: {exc}") from exc
        return TreeNode(kind, name, rules=tuple(copy.deepcopy(item["rules"])))
    if "rules_raw" in item:
        raw = item["rules_raw"]
        if not isinstance(raw, str) or not raw.strip():
            raise TreeSchemaError(f"{here}: rules_raw must be a non-empty string, got {raw!r}")
        return TreeNode(kind, name, rules_raw=raw.strip())
    raise TreeSchemaError(f"{here}: a smart playlist needs `rules` (v1) or `rules_raw` (text)")


def _parse_from(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TreeSchemaError(f"{where}: `from` must be a list of playlist paths like \"A/B\"")
    paths = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise TreeSchemaError(
                f"{where}: `from` entries are playlist paths (text), got {item!r}"
            )
        paths.append(item.strip())
    return tuple(paths)


# -- writing -------------------------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    """The safe dumper, with list items indented under their key and no &anchors."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, False)

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    # PyYAML writes NEL (U+0085) inside a single-quoted scalar as a raw line break, which the
    # loader folds into a space. Double quotes escape it as \N, so the text reads back the same.
    style = '"' if "\x85" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)


def _node_data(node: TreeNode) -> dict[str, Any]:
    data: dict[str, Any] = {node.kind: node.name}
    if node.children:
        data["children"] = [_node_data(child) for child in node.children]
    if node.rules is not None:
        data["rules"] = [_plain_rule(rule) for rule in copy.deepcopy(node.rules)]
    if node.rules_raw is not None:
        data["rules_raw"] = node.rules_raw
    if node.fill_from:
        data["from"] = list(node.fill_from)
    return data


def _doc_data(doc: TreeDoc) -> Any:
    tree = [_node_data(node) for node in doc.nodes]
    if not doc.meta:
        return tree  # bases shape: `dj tree` reads it as it is
    data: dict[str, Any] = {key: doc.meta[key] for key in META_KEYS if key in doc.meta}
    data.update({k: v for k, v in doc.meta.items() if k not in data})  # parse() rejects these
    data["tree"] = tree
    return data


def dumps(doc: TreeDoc) -> str:
    """YAML text for `doc`. Guarantee: parse(yaml.safe_load(dumps(doc))) == doc.

    Checked on the emitted text itself: text that would read back changed is never returned.
    """
    data = _doc_data(doc)
    # An invalid doc never reaches a file (parse raises and names the node) ...
    if parse(data, "dumps") != doc:
        raise TreeSchemaError(
            "dumps: the tree would read back changed (outer spaces in a name, path or rules_raw?)"
        )
    text = yaml.dump(
        data,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )
    # ... and neither does text the YAML emitter changed on the way out.
    try:
        back = parse(yaml.safe_load(text), "dumps")
    except yaml.YAMLError as exc:
        raise TreeSchemaError(f"dumps: the YAML written does not read back: {exc}") from exc
    if back != doc:
        raise TreeSchemaError("dumps: the YAML written reads back as a different tree")
    return text


def dump(doc: TreeDoc, path: str | Path) -> Path:
    """Write `dumps(doc)` atomically (temp file + os.replace), UTF-8, LF."""
    from dj.libfolder import write_text

    path = Path(path)
    text = dumps(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_text(path, text)


# -- reading the tree ----------------------------------------------------------------------


def _nodes_of(doc: TreeDoc | Sequence[TreeNode] | None) -> tuple[TreeNode, ...]:
    if doc is None:
        return ()
    if isinstance(doc, TreeDoc):
        return doc.nodes
    return tuple(doc)


def walk(doc: TreeDoc | Sequence[TreeNode]) -> Iterator[tuple[tuple[str, ...], TreeNode]]:
    """(path, node) for every node, depth-first, in file order."""

    def visit(nodes: Sequence[TreeNode], prefix: tuple[str, ...]):
        for node in nodes:
            path = prefix + (node.name,)
            yield path, node
            yield from visit(node.children, path)

    yield from visit(_nodes_of(doc), ())


def to_tree_nodes(doc: TreeDoc) -> list[Any]:
    """TreeDoc -> `dj.tree.Node` list for `dj tree`. `from` is dropped (tree.yaml has none).

    A smart node without v1 rules cannot be created by `dj tree` -> TreeSchemaError.
    """
    from dj import tree as tree_mod  # lazy: dj.tree pulls dj.rules -> pyrekordbox

    def convert(node: TreeNode, where: str) -> Any:
        here = f"{where} / {node.name}"
        if node.kind == "smart" and node.rules is None:
            raise TreeSchemaError(
                f"{here}: smart playlist has rules_raw only; dj tree needs v1 rules"
            )
        return tree_mod.Node(
            kind=node.kind,
            name=node.name,
            rules=[dict(r) for r in copy.deepcopy(node.rules)] if node.rules is not None else None,
            children=[convert(child, here) for child in node.children],
        )

    return [convert(node, "tree") for node in _nodes_of(doc)]


# -- diff ----------------------------------------------------------------------------------


def diff(
    proposal: TreeDoc | Sequence[TreeNode], current: TreeDoc | Sequence[TreeNode] | None
) -> list[DiffRow]:
    """What building `proposal` on top of `current` would do. Reads only, create only.

    CREATE   the node is new.
    SKIP     a node with this name (case and outer spaces ignored) and kind exists.
    CONFLICT the name exists as another kind; nothing below it is planned.
    MANUAL   a new smart playlist: an XML import cannot carry rules, the DJ makes it by hand.
    Nodes that exist only in `current` are not listed: nothing is ever removed.
    """
    rows: list[DiffRow] = []
    _diff(_nodes_of(proposal), _nodes_of(current), (), rows)
    return rows


def _diff(
    nodes: Sequence[TreeNode],
    existing_nodes: Sequence[TreeNode],
    prefix: tuple[str, ...],
    out: list[DiffRow],
) -> None:
    existing: dict[str, list[TreeNode]] = {}
    for node in existing_nodes:
        existing.setdefault(norm(node.name), []).append(node)

    for node in nodes:
        path = prefix + (node.name,)
        matches = existing.get(norm(node.name), [])
        same_kind = [m for m in matches if m.kind == node.kind]
        if not matches:
            if node.kind == "smart":
                out.append(DiffRow(MANUAL, node.kind, path, (), _manual_note(node)))
            else:
                out.append(DiffRow(CREATE, node.kind, path, node.fill_from))
            _diff(node.children, (), path, out)
        elif same_kind:
            out.append(DiffRow(SKIP, node.kind, path, node.fill_from, "exists"))
            _diff(node.children, same_kind[0].children, path, out)
        else:
            note = f"exists as {matches[0].kind}, wanted {node.kind}; subtree left alone"
            out.append(DiffRow(CONFLICT, node.kind, path, node.fill_from, note))


def _manual_note(node: TreeNode) -> str:
    if node.rules is not None:
        what = " AND ".join(f"{k} {v}" for rule in node.rules for k, v in rule.items())
    else:
        what = node.rules_raw or ""
    return f"make it in rekordbox by hand (XML cannot carry smart rules): {what}"
