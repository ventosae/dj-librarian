import pytest

from dj import tree
from dj.tree import CONFLICT, CREATE, HOLD, SKIP

TREE = [
    {"playlist": "00 inbox"},
    {
        "folder": "01 sets",
        "children": [{"playlist": "demo"}, {"smart": "funk", "rules": [{"genre_contains": "funk"}]}],
    },
]


def plan(data, db):
    return tree.walk(tree.parse_nodes(data, "tree"), db)


def ops(actions):
    return [(a.op, a.kind, a.path) for a in actions]


def test_empty_db_creates_everything(db):
    assert ops(plan(TREE, db)) == [
        (CREATE, "playlist", ("00 inbox",)),
        (CREATE, "folder", ("01 sets",)),
        (CREATE, "playlist", ("01 sets", "demo")),
        (CREATE, "smart", ("01 sets", "funk")),
    ]


def test_walk_never_writes(db):
    plan(TREE, db)
    assert db.calls == [] and db.rows == []


def test_existing_folder_is_skipped_and_descended(db):
    sets = db.seed("folder", "01 sets")
    db.seed("playlist", "demo", sets)
    assert ops(plan(TREE, db)) == [
        (CREATE, "playlist", ("00 inbox",)),
        (SKIP, "folder", ("01 sets",)),
        (SKIP, "playlist", ("01 sets", "demo")),
        (CREATE, "smart", ("01 sets", "funk")),
    ]


def test_match_ignores_case_and_outer_whitespace(db):
    db.seed("playlist", "  00 INBOX ")
    assert plan(TREE, db)[0].op == SKIP


def test_same_name_at_another_level_is_not_a_match(db):
    other = db.seed("folder", "other")
    db.seed("playlist", "00 inbox", other)
    assert plan(TREE, db)[0].op == CREATE


def test_kind_mismatch_is_a_conflict_and_subtree_is_left_alone(db):
    db.seed("playlist", "01 sets")
    actions = plan(TREE, db)
    assert ops(actions) == [
        (CREATE, "playlist", ("00 inbox",)),
        (CONFLICT, "folder", ("01 sets",)),
    ]
    with pytest.raises(tree.ConflictError):
        tree.apply(actions, db)
    assert db.calls == []


def test_apply_creates_under_the_right_parents(db):
    sets = db.seed("folder", "01 sets")
    created = tree.apply(plan(TREE, db), db)
    assert created == 3
    assert db.calls == [
        ("playlist", "00 inbox", None),
        ("playlist", "demo", sets.ID),
        ("smart", "funk", sets.ID),
    ]


def test_apply_nests_new_children_under_new_folder(db):
    tree.apply(plan(TREE, db), db)
    folder = next(r for r in db.rows if r.Name == "01 sets")
    assert ("playlist", "demo", folder.ID) in db.calls


def test_apply_is_idempotent(db):
    tree.apply(plan(TREE, db), db)
    first = list(db.calls)
    second = plan(TREE, db)
    assert {a.op for a in second} == {SKIP}
    assert tree.apply(second, db) == 0
    assert db.calls == first


def test_apply_never_commits(db):
    tree.apply(plan(TREE, db), db)
    assert db.commits == 0


def test_existing_smart_playlist_is_skipped_untouched(db):
    sets = db.seed("folder", "01 sets")
    smart = db.seed("smart", "funk", sets)
    smart.SmartList = "<their rules>"
    tree.apply(plan(TREE, db), db)
    assert smart.SmartList == "<their rules>"


@pytest.mark.parametrize(
    "data, message",
    [
        ({"playlist": "x"}, "expected a list"),
        ([{"playlist": "x", "folder": "y"}], "exactly one of"),
        ([{"name": "x"}], "exactly one of"),
        ([{"playlist": 2024}], "non-empty string"),
        ([{"playlist": "x", "children": []}], "unexpected key"),
        ([{"folder": "x", "rules": []}], "unexpected key"),
        ([{"smart": "x"}], "non-empty list"),
        ([{"smart": "x", "rules": [{"my_tag": "a"}]}], "unknown rule type"),
        ([{"playlist": "x"}, {"folder": "X "}], "duplicate name"),
        ([{"folder": "f", "children": [{"playlist": "a"}, {"playlist": "A"}]}], "duplicate name"),
    ],
)
def test_invalid_yaml_is_rejected(data, message):
    with pytest.raises(tree.TreeError, match=message):
        tree.parse_nodes(data, "tree")


def test_example_tree_yaml_loads():
    from dj.safety import REPO_ROOT

    nodes = tree.load_tree(REPO_ROOT / "examples" / "tree.example.yaml")
    assert [n.name for n in nodes][:2] == ["00 inbox", "01 sets"]


def test_example_bases_yaml_loads():
    from dj.safety import REPO_ROOT

    nodes = tree.load_tree(REPO_ROOT / "examples" / "bases.example.yaml")
    assert [n.name for n in nodes] == ["house_base", "techno_base", "disco_base"]


def test_uncalibrated_smart_nodes_are_held_not_created(db, monkeypatch):
    from dj import rules

    monkeypatch.setattr(rules, "CALIBRATED", set())
    data = [
        {"folder": "04 tempo", "children": [{"smart": "85-100", "rules": [{"bpm_range": [85, 100]}]}]},
        {"smart": "funk", "rules": [{"genre_contains": "funk"}]},
    ]
    actions = tree.hold_uncalibrated(plan(data, db))
    assert [a.op for a in actions] == [CREATE, HOLD, CREATE]
    assert "bpm_range" in actions[1].line()
    assert tree.apply(actions, db) == 2
    assert [c[1] for c in db.calls] == ["04 tempo", "funk"]

    # once calibrated, the next run creates the held node inside the existing folder
    monkeypatch.setattr(rules, "CALIBRATED", {"bpm_range"})
    later = tree.hold_uncalibrated(plan(data, db))
    assert [a.op for a in later] == [SKIP, CREATE, SKIP]
    assert tree.apply(later, db) == 1


def test_soft_deleted_rows_do_not_count_as_existing(db):
    ghost = db.seed("playlist", "00 inbox")
    ghost.rb_local_deleted = 1  # removed in rekordbox, not purged yet
    assert plan(TREE, db)[0].op == CREATE
