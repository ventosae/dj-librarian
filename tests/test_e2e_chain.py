"""The whole v0.1 chain on the synthetic library, one test, through the skill scripts.

xml_fixtures export -> dj-start init -> dj-profile, dj-structure, dj-taste scripts -> MD files ->
dj-report -> one self-contained HTML -> dj-build preview -> explicit preview id -> dj-build apply
-> a rekordbox XML that pyrekordbox reads back with the same playlists and tracks the proposal
maps. No master.db, no network, no engine: every step runs as the DJ's Claude would run it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import xml_fixtures as fx
from pyrekordbox.rbxml import RekordboxXml

from dj import treeschema
from dj.readers.xml import read_xml

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "plugin" / "skills"
TODAY = "2026-10-20"
HABITS = """# Who you are as a DJ

> Words by Claude, from profile/stats.md and profile/facts.json.

You run a working crate: house in front, disco and funk underneath, a dump you keep meaning to sort.
"""


def run(script: str, *args: object) -> tuple[int, dict]:
    done = subprocess.run(
        [sys.executable, str(SKILLS / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO, timeout=300,
    )  # fmt: skip
    try:
        return done.returncode, json.loads(done.stdout)  # one JSON object (contract section 0)
    except ValueError as exc:
        raise AssertionError((script, done.stdout, done.stderr)) from exc


def rekordbox_tree(path: Path) -> dict[tuple[str, ...], tuple[str, list[str]]]:
    """path -> (kind, track keys) for every node pyrekordbox finds under ROOT."""
    out: dict[tuple[str, ...], tuple[str, list[str]]] = {}

    def walk(node, prefix: tuple[str, ...]) -> None:
        for child in node.get_playlists():
            here = prefix + (child.name,)
            if child.is_folder:
                out[here] = ("folder", [])
                walk(child, here)
            else:
                out[here] = ("playlist", [str(k) for k in child.get_tracks()])

    walk(RekordboxXml(path).get_playlist(), ())
    return out


def test_the_whole_chain_from_export_to_an_importable_rekordbox_xml(tmp_path):
    lib = tmp_path / "dj-library"
    lib.mkdir()
    dropped = fx.write_xml(lib / "rekordbox.xml")
    original = dropped.read_bytes()

    # P3: the folder step.
    code, out = run("dj-start/scripts/start.py", "init", "--library", lib, "--device", "windows", "--today", TODAY)
    assert code == 0 and out["counts"] == fx.EXPECTED_COUNTS, out
    assert dropped.read_bytes() == original  # copied, never moved

    # P4: the three analysis scripts write their MD files (measured by code).
    for script in ("dj-profile/scripts/profile.py", "dj-structure/scripts/structure.py", "dj-taste/scripts/taste.py"):
        code, out = run(script, "--library", lib, "--today", TODAY)
        assert code == 0 and out.get("ok", True), (script, out)
    for md in ("profile/stats.md", "structure/analysis.md", "taste/lanes.md", "taste/labels-artists.md",
               "taste/anchors.md", "taste/vocabulary.md"):
        text = (lib / md).read_text(encoding="utf-8")
        assert text.startswith("# ") and "> Measured by code:" in text, md
    assert (lib / "structure" / "current-tree.yaml").is_file()
    (lib / "profile" / "habits.md").write_text(HABITS, encoding="utf-8")  # Claude's words (R-312)

    # P5: one self-contained HTML with the four sections of R-402..R-406.
    code, out = run("dj-report/scripts/report.py", "--library", lib, "--today", TODAY)
    assert code == 0 and out["ok"] is True, out
    page = (lib / out["report"]).read_text(encoding="utf-8")
    for section in ("who", "structure", "proposals", "next"):
        assert f'<section id="{section}">' in page
    assert not re.search(r"https?://|<script[^>]*\bsrc=|<link[^>]*\bhref=|@import|url\(", page, re.I)
    assert "a working crate" in page  # the narrative made it in
    triggers = [p["trigger"] for p in out["proposals"]]
    assert 2 <= len(triggers) <= 3 and all(t in page for t in triggers)

    # B1: the trigger prompt from the report drives dj-build (R-404, R-501). Nothing written yet.
    trigger = triggers[0]
    code, preview = run("dj-build/scripts/build.py", "preview", trigger, "--library", lib, "--today", TODAY)
    assert code == 0 and preview["ok"] is True and preview["preview_id"], preview
    assert preview["counts"]["create"] > 0
    assert not list((lib / "proposals").glob("*.xml"))

    # B2: no id, no write.
    code, refused = run("dj-build/scripts/build.py", "apply", trigger, "--library", lib, "--today", TODAY)
    assert code == 2 and "refused" in refused
    assert not list((lib / "proposals").glob("*.xml"))

    # B3: after the yes, with the preview id: proposals/<slug>.xml and one log line (R-502, R-505).
    log_before = (lib / "log.md").read_text(encoding="utf-8")
    code, built = run("dj-build/scripts/build.py", "apply", trigger, "--library", lib, "--today", TODAY,
                      "--preview-id", preview["preview_id"])
    assert code == 0 and built["ok"] is True, built
    xml_path = lib / built["written"]
    assert xml_path.suffix == ".xml" and xml_path.is_file()
    log_after = (lib / "log.md").read_text(encoding="utf-8")
    assert len(log_after.splitlines()) == len(log_before.splitlines()) + 1

    # pyrekordbox reads it back with the same playlists, filled from the mapped ones (R-503).
    library = read_xml(lib / "exports" / sorted(p.name for p in (lib / "exports").glob("*.xml"))[-1])
    proposal = treeschema.load(lib / preview["yaml"])
    current = treeschema.load(lib / "structure" / "current-tree.yaml")
    created = {tuple(r.path) for r in treeschema.diff(proposal, current) if r.op == "CREATE"}
    expected: dict[tuple[str, ...], list[str]] = {}
    for path, node in treeschema.walk(proposal):
        if tuple(path) in created and node.kind == "playlist":
            ids: list[str] = []
            for source in node.fill_from:
                ids += [t.id for t in library.tracks_in(source) if t.id not in ids]
            expected[tuple(path)] = ids
    got = rekordbox_tree(xml_path)
    got_playlists = {path: keys for path, (kind, keys) in got.items() if kind == "playlist"}
    assert got_playlists == expected
    assert any(expected.values()), "at least one new playlist is pre-filled from an existing one"
    assert all(path[:-1] in got or len(path) == 1 for path in got)  # every node sits under its parent
