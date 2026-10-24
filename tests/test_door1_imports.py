"""Door 1 (contract section 0): these modules must import, and work, with the engine-only
packages missing, because skill scripts run them in Cowork's sandbox (Q-06).
Later work items append their modules to DOOR1_MODULES."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BLOCKED = ("pyrekordbox", "rapidfuzz", "httpx", "typer", "mcp")
DOOR1_MODULES = [
    "dj.model",
    "dj.readers.common",
    "dj.readers.xml",
    "dj.libfolder",
    "dj.treeschema",
    "dj.shopping",  # W-25: the shopping list (R-803)
    "dj.gate",
    "dj.writers.rekordbox_xml",
    "dj.build_structure",
    "dj.onboarding",
    "dj.analysis.common",
    "dj.analysis.profile",
    "dj.analysis",
    "dj.analysis.structure",
    "dj.taste_files",
    "dj.analysis.taste",
    "dj.barber",
    "dj.analysis.proposals",
    "dj.report",
    "dj.analysis.run_all",
    "dj.crate",
    "dj.write_gate",
    "dj.activity_log",
    "dj.design",  # W-31: the design tokens (R-408)
    "dj.sleeve",  # W-31: the sleeve (R-1403)
    "dj.analysis.identity",  # W-31: six axes, archetype, fingerprint (R-1401, R-1402)
    "dj.report_charts",  # W-31: the report's crate wall, axes and sleeve layers (R-403, R-408)
    "dj.hostenv",  # W-34: the host's settings and where the engine keeps its files (D-28)
]


def run_blocked(body: str) -> subprocess.CompletedProcess:
    code = textwrap.dedent(f"""
        import sys
        for name in {BLOCKED!r}:
            sys.modules[name] = None  # `import name` now raises ImportError
    """) + textwrap.dedent(body)
    paths = [str(REPO / "src")] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(paths), PYTHONUTF8="1")
    return subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=env)


def test_door1_modules_import_without_engine_packages():
    done = run_blocked(f"""
        import importlib
        for mod in {DOOR1_MODULES!r}:
            importlib.import_module(mod)
        leaked = [n for n in {BLOCKED!r} if sys.modules.get(n) is not None]
        assert not leaked, leaked
        print("ok")
    """)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr


def test_the_blocking_itself_works():
    done = run_blocked("import pyrekordbox\n")
    assert done.returncode != 0 and "import of pyrekordbox halted" in done.stderr


def test_read_xml_works_without_engine_packages():
    done = run_blocked("""
        import json
        from dj.readers.xml import read_xml
        print(json.dumps(read_xml("tests/fixtures/sample.xml").counts()))
    """)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["tracks"] == 24


# Every Door 1 script with the arguments of a normal run. Installed from a zip or a GitHub
# marketplace, the plugin runs as a copy with no dj core next to it (and dj is not on PyPI yet).
SCRIPTS = {
    "dj-start/scripts/start.py": ["find-xml"],
    "dj-profile/scripts/profile.py": [],
    "dj-structure/scripts/structure.py": [],
    "dj-taste/scripts/taste.py": [],
    "dj-identity/scripts/identity.py": [],
    "dj-report/scripts/report.py": [],
    "dj-barber/scripts/barber.py": ["next"],
    "dj-build/scripts/build.py": ["preview", "lanes"],
    "dj-crate/scripts/crate.py": ["preview", "saturday"],
}


def test_every_skill_script_names_the_missing_core_in_one_json_object(tmp_path):
    """No traceback where the core is missing: one JSON object that says so, exit 1."""
    import pytest
    import yaml

    site = Path(yaml.__file__).resolve().parents[1]
    if (site / "dj").exists():
        pytest.skip("dj is installed as a package here; the missing-core branch is not reachable")
    assert set(SCRIPTS) == {p.relative_to(REPO / "plugin" / "skills").as_posix()
                            for p in (REPO / "plugin" / "skills").glob("*/scripts/*.py")}
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(site)  # PyYAML and the engine packages, but no dj (no .pth under -S)
    library = tmp_path / "lib"
    library.mkdir()
    for script, args in SCRIPTS.items():
        copy = tmp_path / "cache" / "dj-librarian" / "0.1.0" / "skills" / script
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes((REPO / "plugin" / "skills" / script).read_bytes())
        done = subprocess.run([sys.executable, "-S", str(copy), *args, "--library", str(library)],
                              cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
                              timeout=120)  # fmt: skip
        assert done.returncode == 1, (script, done.stdout, done.stderr)
        assert "Traceback" not in done.stderr, (script, done.stderr)
        out = json.loads(done.stdout)
        assert "core" in out["error"] and "No module named 'dj'" in out["error"], (script, out)
    assert list(library.iterdir()) == []
