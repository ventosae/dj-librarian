"""dj.treeschema: one loader for bases.yaml, current-tree.yaml and proposals/*.yaml (R-903)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from dj import rules as rules_mod
from dj import tree as tree_mod
from dj import treeschema
from dj.treeschema import (
    CONFLICT,
    CREATE,
    MANUAL,
    SKIP,
    DiffRow,
    TreeDoc,
    TreeNode,
    TreeSchemaError,
    diff,
    dump,
    dumps,
    load,
    parse,
    to_tree_nodes,
    walk,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

FULL = TreeDoc(
    (
        TreeNode(
            "folder",
            "house_base",
            (
                TreeNode("playlist", "0_INBOX"),
                TreeNode("playlist", "1.2_groovy", fill_from=("old/groovy", "old/deep cuts")),
                TreeNode("folder", "empty folder"),
            ),
        ),
        TreeNode(
            "smart",
            "techno 128-135",
            rules=({"genre_contains": "techno"}, {"bpm_range": [128, 135]}),
        ),
        TreeNode("smart", "dark + fast", rules_raw="My Tag is dark AND BPM > 130"),
        TreeNode("folder", "Fiestas Ñandú", (TreeNode("playlist", "Ünïcode ☀ 夜"),)),
    ),
    {
        "name": "Bases",
        "family": "bases",
        "principle": "One folder per genre, the same shape inside each.",
        "source": "exports/2026-10-20-collection.xml",
        "generated": "2026-10-20",
    },
)


def shape(nodes):
    """(kind, name, rules, children) from either loader, for comparing the two."""
    out = []
    for n in nodes:
        rules = None if n.rules is None else [dict(r) for r in n.rules]
        out.append((n.kind, n.name, rules, shape(n.children)))
    return out


# -- round trip ----------------------------------------------------------------------------


def test_round_trip_full_doc():
    text = dumps(FULL)
    assert parse(yaml.safe_load(text)) == FULL
    assert "Ünïcode ☀ 夜" in text  # allow_unicode: names stay readable
    assert text.index("name:") < text.index("tree:")


def test_round_trip_bare_list_is_bases_shape():
    doc = TreeDoc(FULL.nodes[:1])
    text = dumps(doc)
    assert text.startswith("- folder: house_base")
    assert parse(yaml.safe_load(text)) == doc
    assert parse(yaml.safe_load(text)).meta == {}


def test_round_trip_through_a_file(tmp_path):
    path = dump(FULL, tmp_path / "proposals" / "bases.yaml")
    raw = path.read_bytes()
    assert b"\r" not in raw
    assert load(path) == FULL
    assert [p.name for p in path.parent.iterdir()] == ["bases.yaml"]  # no temp file left


def test_code_built_doc_with_lists_round_trips():
    doc = TreeDoc(
        [TreeNode("folder", "a", [TreeNode("playlist", "b", fill_from=["x/y"])]),
         TreeNode("smart", "c", rules=[{"bpm_range": (120, 128)}])],
        {"generated": date(2026, 10, 20)},
    )  # fmt: skip
    assert doc.meta == {"generated": "2026-10-20"}
    assert parse(yaml.safe_load(dumps(doc))) == doc


def test_empty_tree_round_trips():
    assert parse(yaml.safe_load(dumps(TreeDoc(())))) == TreeDoc(())
    doc = TreeDoc((), {"name": "nothing yet"})
    assert parse(yaml.safe_load(dumps(doc))) == doc


def test_dumps_of_bases_shape_is_read_by_dj_tree(tmp_path):
    doc = TreeDoc(
        (
            TreeNode("folder", "house_base", (TreeNode("playlist", "0_INBOX"),)),
            TreeNode("smart", "house", rules=({"genre_contains": "house"},)),
            TreeNode("playlist", "Ñandú"),
        )
    )
    path = tmp_path / "tree.yaml"
    path.write_text(dumps(doc), encoding="utf-8")
    assert shape(tree_mod.load_tree(path)) == shape(doc.nodes)


def test_round_trip_keeps_nel_and_other_line_break_characters(tmp_path):
    # PyYAML folds a raw NEL (U+0085) in a single-quoted scalar into a space; dumps must not.
    odd = "a\x85b\x85\x85c"
    doc = TreeDoc(
        (
            TreeNode("playlist", odd, fill_from=(f"old/{odd}",)),
            TreeNode("smart", "raw", rules_raw=f"My Tag is {odd}"),
            TreeNode("playlist", "line sep para"),
        ),
        {"name": "line1\x85line2", "principle": odd},
    )
    text = dumps(doc)
    assert parse(yaml.safe_load(text)) == doc
    # bases-shape keys only: dj tree reads the same names back
    bare = TreeDoc((TreeNode("playlist", odd), TreeNode("folder", "line sep para")))
    path = tmp_path / "tree.yaml"
    path.write_text(dumps(bare), encoding="utf-8")
    assert [n.name for n in tree_mod.load_tree(path)] == [n.name for n in bare.nodes]


def test_round_trip_every_control_and_special_character():
    specials = [chr(c) for c in (*range(0x20), *range(0x7F, 0xA0))]
    specials += [" ", " ", "﻿", "￾", "\ud800", "\U0001f3a7", "'", '"', "\\"]
    doc = TreeDoc(
        tuple(
            TreeNode("playlist", f"{i} x{ch}y", fill_from=(f"p{ch}q",))
            for i, ch in enumerate(specials)
        ),
        {"name": "x" + "".join(specials) + "y"},
    )
    assert parse(yaml.safe_load(dumps(doc))) == doc


def test_dumps_checks_the_text_it_emits(monkeypatch):
    doc = TreeDoc((TreeNode("playlist", "a"),))
    monkeypatch.setattr(treeschema.yaml, "dump", lambda *a, **k: "- playlist: b\n")
    with pytest.raises(TreeSchemaError, match="reads back as a different tree"):
        dumps(doc)
    monkeypatch.setattr(treeschema.yaml, "dump", lambda *a, **k: "- playlist: [unclosed\n")
    with pytest.raises(TreeSchemaError, match="does not read back"):
        dumps(doc)


@pytest.mark.parametrize(
    "doc",
    [
        TreeDoc((TreeNode("playlist", "a", children=(TreeNode("playlist", "b"),)),)),
        TreeDoc((TreeNode("smart", "a"),)),
        TreeDoc((TreeNode("smart", "a", rules=()),)),
        TreeDoc((TreeNode("folder", "a", fill_from=("x",)),)),
        TreeDoc((TreeNode("crate", "a"),)),
        TreeDoc((TreeNode("playlist", " a "),)),
        TreeDoc((TreeNode("playlist", "a"), TreeNode("playlist", "A"))),
        TreeDoc((TreeNode("playlist", "a"),), {"owner": "x"}),
    ],
)
def test_dumps_refuses_an_invalid_doc(doc):
    with pytest.raises(TreeSchemaError):
        dumps(doc)


# -- the examples load the same through both loaders ---------------------------------------


@pytest.mark.parametrize("name", ["bases.example.yaml", "tree.example.yaml"])
def test_examples_load_the_same_through_both_loaders(name):
    path = EXAMPLES / name
    doc = load(path)
    assert doc.meta == {}
    assert shape(doc.nodes) == shape(tree_mod.load_tree(path))
    assert shape(to_tree_nodes(doc)) == shape(tree_mod.load_tree(path))


def test_rule_types_match_dj_rules():
    assert treeschema.RULE_TYPES == tuple(rules_mod.RULE_TYPES)


@pytest.mark.parametrize(
    "rules",
    [
        [{"genre_contains": "house"}],
        [{"genre_contains": ""}],
        [{"genre_contains": 5}],
        [{"comment_contains": "#dark"}],
        [{"comment_contains": "  "}],
        [{"bpm_range": [120, 128]}],
        [{"bpm_range": [128, 120]}],
        [{"bpm_range": [0, 120]}],
        [{"bpm_range": [120, 1000]}],
        [{"bpm_range": [120]}],
        [{"bpm_range": "120-128"}],
        [{"bpm_range": [True, 128]}],
        [{"bpm_range": [120.5, 128]}],
        [{"rating_min": 3}],
        [{"rating_min": 6}],
        [{"rating_min": True}],
        [{"added_last_days": 30}],
        [{"added_last_days": 0}],
        [{"added_last_days": 3651}],
        [{"my_tag": "dark"}],
        [{"genre_contains": "a", "bpm_range": [1, 2]}],
        [["genre_contains", "x"]],
        [],
        "genre_contains",
        None,
    ],
)
def test_rule_shapes_agree_with_dj_rules(rules):
    try:
        rules_mod.conditions(rules)
        accepted_by_rules = True
    except ValueError:
        accepted_by_rules = False
    try:
        treeschema.check_rules(rules)
        accepted_here = True
    except TreeSchemaError:
        accepted_here = False
    assert accepted_here == accepted_by_rules


def test_norm_matches_dj_tree():
    for name in ("House", "  house  ", "ÑANDÚ", "Straße", "1.2_Groovy "):
        assert treeschema.norm(name) == tree_mod.norm(name)


# -- parsing -------------------------------------------------------------------------------


def test_parse_mapping_form_with_meta():
    doc = parse(
        {
            "name": "Facets",
            "family": "facets",
            "principle": "Mood first.",
            "source": "exports/x.xml",
            "generated": date(2026, 10, 20),  # unquoted in a hand-written file
            "tree": [{"playlist": "  a  ", "from": ["  x/y "]}, {"folder": "b", "children": None}],
        },
        "p.yaml",
    )
    assert doc.meta["generated"] == "2026-10-20"
    assert doc.nodes == (TreeNode("playlist", "a", fill_from=("x/y",)), TreeNode("folder", "b"))


def test_parse_from_null_is_empty():
    assert parse([{"playlist": "a", "from": None}]).nodes == (TreeNode("playlist", "a"),)


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ([{"playlist": "a", "colour": "red"}], "unexpected key"),
        ([{"folder": "a", "rules": [{"genre_contains": "x"}]}], "unexpected key"),
        ([{"smart": "a", "from": ["x"], "rules_raw": "y"}], "unexpected key"),
        ({"tree": [], "owner": "someone"}, "unexpected top-level key"),
        ([{"playlist": "a", "folder": "b"}], "exactly one of"),
        ([{"children": []}], "exactly one of"),
        ([{"playlist": ""}], "non-empty string"),
        ([{"playlist": "   "}], "non-empty string"),
        ([{"playlist": None}], "non-empty string"),
        ([{"playlist": 2024}], "non-empty string"),
        ([{"playlist": "House"}, {"playlist": " house "}], "duplicate name"),
        ([{"folder": "f", "children": [{"playlist": "A"}, {"smart": "a", "rules_raw": "x"}]}],
         "duplicate name"),
        ([{"playlist": "a", "from": "x/y"}], "`from` must be a list"),
        ([{"playlist": "a", "from": {"x": "y"}}], "`from` must be a list"),
        ([{"playlist": "a", "from": [3]}], "`from` entries"),
        ([{"playlist": "a", "from": [""]}], "`from` entries"),
        ([{"smart": "a", "rules": [{"genre_contains": "x"}], "rules_raw": "y"}], "not both"),
        ([{"smart": "a"}], "needs `rules`"),
        ([{"smart": "a", "rules_raw": ""}], "rules_raw must be"),
        ([{"smart": "a", "rules_raw": ["x"]}], "rules_raw must be"),
        ([{"smart": "a", "rules": [{"my_tag": "dark"}]}], "unknown rule type"),
        ([{"smart": "a", "rules": []}], "non-empty list"),
        ([{"folder": "a", "children": "b"}], "expected a list"),
        (["just a string"], "each node is a mapping"),
        ({"name": "x"}, "needs a `tree:`"),
        ({"tree": {"playlist": "a"}}, "expected a list"),
        ({"tree": [], "generated": 5}, "expected text"),
        ("a string", "expected a list of nodes"),
        (None, "expected a list of nodes"),
    ],
)  # fmt: skip
def test_parse_errors(data, fragment):
    with pytest.raises(TreeSchemaError, match=fragment):
        parse(data, "test.yaml")


def test_parse_error_names_the_node():
    with pytest.raises(TreeSchemaError, match=r"p\.yaml / outer / inner"):
        inner = {"folder": "inner", "children": [{"x": 1}]}
        parse([{"folder": "outer", "children": [inner]}], "p.yaml")


def test_tree_schema_error_is_a_value_error():
    assert issubclass(TreeSchemaError, ValueError)


def test_load_reports_bad_yaml(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- playlist: [unclosed\n", encoding="utf-8")
    with pytest.raises(TreeSchemaError, match="bad.yaml: not valid YAML"):
        load(path)


def test_load_reads_structure_and_proposal_files_alike(tmp_path):
    current = tmp_path / "current-tree.yaml"
    proposal = tmp_path / "bases.yaml"
    current.write_text(
        "- folder: house_base\n  children:\n    - playlist: 0_INBOX\n", encoding="utf-8"
    )
    proposal.write_text(
        "name: Bases\nfamily: bases\ntree:\n  - folder: house_base\n    children:\n"
        "      - playlist: 0_INBOX\n      - playlist: 1_CRATES\n        from: [old/crate]\n",
        encoding="utf-8",
    )
    assert load(current).nodes[0].children == (TreeNode("playlist", "0_INBOX"),)
    assert load(proposal).nodes[0].children[1].fill_from == ("old/crate",)


# -- walk, to_tree_nodes -------------------------------------------------------------------


def test_walk_is_depth_first_in_file_order():
    assert [(path, node.kind) for path, node in walk(FULL)] == [
        (("house_base",), "folder"),
        (("house_base", "0_INBOX"), "playlist"),
        (("house_base", "1.2_groovy"), "playlist"),
        (("house_base", "empty folder"), "folder"),
        (("techno 128-135",), "smart"),
        (("dark + fast",), "smart"),
        (("Fiestas Ñandú",), "folder"),
        (("Fiestas Ñandú", "Ünïcode ☀ 夜"), "playlist"),
    ]


def test_to_tree_nodes_feeds_dj_tree(db):
    doc = parse(
        [
            {"folder": "house_base", "children": [{"playlist": "0_INBOX", "from": ["old/inbox"]}]},
            {"smart": "house", "rules": [{"genre_contains": "house"}]},
        ]
    )
    nodes = to_tree_nodes(doc)
    assert all(isinstance(n, tree_mod.Node) for n in nodes)
    assert nodes[1].rules == [{"genre_contains": "house"}]
    nodes[1].rules[0]["genre_contains"] = "changed"  # a copy: the doc stays as it was
    assert doc.nodes[1].rules == ({"genre_contains": "house"},)
    actions = tree_mod.walk(to_tree_nodes(doc), db)
    assert [(a.op, a.kind, a.path) for a in actions] == [
        (tree_mod.CREATE, "folder", ("house_base",)),
        (tree_mod.CREATE, "playlist", ("house_base", "0_INBOX")),
        (tree_mod.CREATE, "smart", ("house",)),
    ]
    assert db.calls == []


def test_to_tree_nodes_rejects_smart_with_rules_raw():
    doc = parse([{"folder": "f", "children": [{"smart": "dark", "rules_raw": "My Tag is dark"}]}])
    with pytest.raises(TreeSchemaError, match="f / dark"):
        to_tree_nodes(doc)


# -- diff ----------------------------------------------------------------------------------

CURRENT = parse(
    [
        {"folder": "House_Base", "children": [{"playlist": "0_INBOX"}, {"playlist": "keep me"}]},
        {"playlist": "techno_base"},
        {"smart": "house", "rules": [{"genre_contains": "house"}]},
        {"playlist": "only in rekordbox"},
    ]
)

PROPOSAL = parse(
    {
        "name": "Bases",
        "tree": [
            {
                "folder": "house_base",
                "children": [
                    {"playlist": " 0_inbox "},
                    {"playlist": "1.2_groovy", "from": ["old/groovy"]},
                ],
            },
            {"folder": "techno_base", "children": [{"playlist": "1.1_hypnotic"}]},
            {"smart": "house", "rules": [{"genre_contains": "house"}]},
            {
                "folder": "new_base",
                "children": [
                    {"playlist": "a", "from": ["x/y"]},
                    {"smart": "dark", "rules_raw": "My Tag is dark"},
                    {"smart": "fast", "rules": [{"bpm_range": [130, 140]}]},
                ],
            },
        ],
    }
)


def test_diff_ops():
    rows = diff(PROPOSAL, CURRENT)
    assert [(r.op, r.kind, r.path, r.fill_from) for r in rows] == [
        (SKIP, "folder", ("house_base",), ()),
        (SKIP, "playlist", ("house_base", "0_inbox"), ()),
        (CREATE, "playlist", ("house_base", "1.2_groovy"), ("old/groovy",)),
        (CONFLICT, "folder", ("techno_base",), ()),
        (SKIP, "smart", ("house",), ()),
        (CREATE, "folder", ("new_base",), ()),
        (CREATE, "playlist", ("new_base", "a"), ("x/y",)),
        (MANUAL, "smart", ("new_base", "dark"), ()),
        (MANUAL, "smart", ("new_base", "fast"), ()),
    ]


def test_diff_notes():
    rows = {r.path: r for r in diff(PROPOSAL, CURRENT)}
    assert "exists as playlist, wanted folder" in rows[("techno_base",)].note
    assert "My Tag is dark" in rows[("new_base", "dark")].note
    assert "XML cannot carry" in rows[("new_base", "fast")].note
    assert "bpm_range" in rows[("new_base", "fast")].note
    assert rows[("house_base",)].note == "exists"


def test_diff_conflict_leaves_the_subtree_alone():
    rows = diff(PROPOSAL, CURRENT)
    assert not any(r.path[:1] == ("techno_base",) and len(r.path) > 1 for r in rows)


def test_diff_never_lists_what_only_exists_in_rekordbox():
    paths = {r.path for r in diff(PROPOSAL, CURRENT)}
    assert ("only in rekordbox",) not in paths
    assert ("house_base", "keep me") not in paths


def test_diff_against_nothing_creates_everything():
    rows = diff(PROPOSAL, None)
    assert {r.op for r in rows} == {CREATE, MANUAL}
    assert len(rows) == len(list(walk(PROPOSAL)))
    assert diff(PROPOSAL, TreeDoc(())) == rows


def test_diff_prefers_a_same_kind_match_among_duplicates():
    # A tree read from rekordbox can hold two nodes with one name at one level.
    inside = TreeNode("playlist", "in")
    current = TreeDoc((TreeNode("playlist", "x"), TreeNode("folder", "X", (inside,))))
    proposal = TreeDoc((TreeNode("folder", "x", (inside, TreeNode("playlist", "new"))),))
    assert diff(proposal, current) == [
        DiffRow(SKIP, "folder", ("x",), (), "exists"),
        DiffRow(SKIP, "playlist", ("x", "in"), (), "exists"),
        DiffRow(CREATE, "playlist", ("x", "new"), (), ""),
    ]
