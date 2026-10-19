"""The audit Markdown/JSON and the Relocate checklist."""

from pathlib import Path

from tidy_fixtures import row

from dj.intake import Paths
from dj.library import to_track_info
from dj.tidy import checks, report
from dj.tidy.config import load_config
from dj.tidy.dupes import DupeGroup
from dj.tidy.scan import Target
from dj.tidy.tags import StreamInfo, Tags


def make_item(path, rb=None):
    f = checks.FileFacts(Path(path), True, 100, 1.0, None, "mp3", StreamInfo("mp3", 320, False, 44100, None, 200.0, (2, 3, 0)),
                         Tags(), None)
    return checks.Item(f, rb, "crate", True)


def test_audit_json_and_markdown(tmp_path):
    from dj.safety import REPO_ROOT

    cfg = load_config(REPO_ROOT / "examples" / "tidy.example.yaml")
    profiles = [cfg.profile(n) for n in cfg.default_profiles]
    rb = to_track_info(row("7", path="C:/Music/x/a.mp3"))
    a = make_item("C:/Music/x/a.mp3", rb)
    b = make_item("C:/Music/x/b.mp3")  # not in rekordbox
    findings = [checks.check_item(a, profiles, cfg), checks.check_item(b, profiles, cfg)]
    groups = [DupeGroup("fuzzy", (a, b), a, "in rekordbox")]
    meta = {"target": {}, "rb_rows": 1, "files": 2, "not_in_rekordbox": 1, "missing_files": 0, "unreadable": 0,
            "hash_mode": "collisions"}
    audit = report.audit_dict(Target("crate", "x/y", "x_y"), cfg, profiles, [a, b], findings, groups, meta)
    assert audit["kind"] == "tidy-audit" and audit["counts"]["items"] == 2 and audit["counts"]["clean"] == 0
    assert audit["counts"]["by_code"]["ART_MISSING"] == 2 and audit["items"][0]["rb_content_id"] == "7"
    assert audit["items"][0]["db"]["bpm"] == 120.0 and audit["items"][1]["db"] is None
    assert audit["duplicates"][0]["keeper"].endswith("a.mp3")

    md = report.audit_md(audit)
    assert md.startswith("# dj tidy audit: x/y") and "### ART_MISSING (2)" in md and "## Not in rekordbox (1)" in md
    assert "## Duplicates (1 groups" in md and "No file was changed" in md
    assert "no embedded picture" in md

    json_path, md_path = report.write_audit(audit, Paths(tmp_path))
    assert json_path.parent == tmp_path / "reports" / "tidy" and json_path.name.endswith("-x_y.audit.json")
    assert md_path.read_text(encoding="utf-8") == md


def test_relocate_md_lists_old_and_new():
    plan = {"plan_id": "p1", "target": {"value": "jazz/0_INBOX"}}
    md = report.relocate_md(plan, [{"rb_content_id": "9", "label": "A - B", "old": "C:/m/a.mp3", "new": "C:/m/A - B.mp3"}])
    assert "Relocate" in md and "| [ ] | 9 | A - B | C:/m/a.mp3 | C:/m/A - B.mp3 |" in md
