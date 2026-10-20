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
    "dj.analysis.proposals",
    "dj.report",
    "dj.analysis.run_all",
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
