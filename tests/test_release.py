"""The release workflow (W-32, W-27): .github/workflows/release.yml, scripts/release_notes.py and the
README's "Try it before the release".

release.yml runs only on a pushed `v*` tag (the owner's, W-29). It runs ci.yml's checks through
`workflow_call`, then checks that the tagged commit is on main, checks the tag against pyproject.toml
and plugin.json, cuts the version's CHANGELOG.md section, builds the plugin zip and creates a DRAFT
GitHub release with the zip attached.
No package index step, nothing public. Nothing here talks to the network.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "release_notes.py"
WORKFLOWS = REPO / ".github" / "workflows"
RELEASE = WORKFLOWS / "release.yml"
CI = WORKFLOWS / "ci.yml"
README = REPO / "README.md"

SAMPLE = """# Changelog

## [Unreleased]

### Added
- Something not released yet.

## [1.2.0] - 2026-11-02

### Added
- The crate wall.

### Fixed
- One clock for the log.

## [1.1.0] - 2026-10-01

## [1.0.0] - 2026-09-01

### Added
- First cut.

[1.2.0]: https://example.invalid/compare/v1.1.0...v1.2.0
[1.0.0]: https://example.invalid/releases/v1.0.0
"""


@pytest.fixture(scope="module")
def rn():
    spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8",
                          cwd=REPO, timeout=60)  # fmt: skip


def _version() -> str:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


# -- scripts/release_notes.py: the section -------------------------------------------------------


def test_section_is_the_body_under_the_heading(rn):
    notes = rn.section(SAMPLE, "1.2.0")
    assert notes == "### Added\n- The crate wall.\n\n### Fixed\n- One clock for the log.\n"


def test_section_accepts_a_leading_v(rn):
    assert rn.section(SAMPLE, "v1.2.0") == rn.section(SAMPLE, "1.2.0")


def test_the_last_section_stops_at_the_link_references(rn):
    assert rn.section(SAMPLE, "1.0.0") == "### Added\n- First cut.\n"


def test_a_missing_section_is_refused(rn):
    with pytest.raises(rn.ReleaseError, match=r"no section \[9\.9\.9\]"):
        rn.section(SAMPLE, "9.9.9")


def test_an_empty_section_is_refused(rn):
    with pytest.raises(rn.ReleaseError, match="empty"):
        rn.section(SAMPLE, "1.1.0")


def test_a_section_still_marked_unreleased_is_refused(rn):
    stub = SAMPLE.replace("## [1.2.0] - 2026-11-02", "## [1.2.0] — unreleased")
    with pytest.raises(rn.ReleaseError, match="still marked unreleased"):
        rn.section(stub, "1.2.0")
    with pytest.raises(rn.ReleaseError, match="still marked unreleased"):
        rn.section(SAMPLE, "Unreleased")


def test_a_version_is_matched_whole_not_as_a_prefix(rn):
    with pytest.raises(rn.ReleaseError, match="no section"):
        rn.section(SAMPLE, "1.2")


def test_cli_prints_the_notes_and_writes_them_as_utf8(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(SAMPLE.replace("The crate wall.", "The crate wall → sleeve."), encoding="utf-8")
    done = _run("1.2.0", "--changelog", str(changelog))
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("### Added\n- The crate wall → sleeve.\n")
    out = tmp_path / "notes.md"
    done = _run("1.2.0", "--changelog", str(changelog), "--out", str(out))
    assert done.returncode == 0 and done.stdout == ""
    assert out.read_bytes().decode("utf-8") == "### Added\n- The crate wall → sleeve.\n\n### Fixed\n- One clock for the log.\n"


@pytest.mark.parametrize("version, why", [("9.9.9", "no section"), ("1.1.0", "empty")])
def test_cli_exits_1_with_one_line_on_stderr(tmp_path, version, why):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / "notes.md"
    done = _run(version, "--changelog", str(changelog), "--out", str(out))
    assert done.returncode == 1
    assert why in done.stderr and len(done.stderr.strip().splitlines()) == 1
    assert done.stdout == "" and not out.exists()


def test_cli_wants_a_version_or_a_tag():
    assert _run().returncode == 2
    assert _run("1.0.0", "--check-tag", "v1.0.0").returncode == 2


def test_the_real_changelogs_version_section(rn):
    """Today CHANGELOG.md's [0.1.0] is a stub: its heading says "unreleased" and its body is one
    "Target" line, while every entry sits under [Unreleased]. The script refuses it, so a tag
    pushed now gets no draft release. At W-29 the owner moves the entries and dates the heading;
    from then on the script gives the section's body."""
    version = _version()
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = next(line for line in text.splitlines() if line.startswith(f"## [{version}]"))
    done = _run(version)
    if "unreleased" in heading.casefold():
        assert done.returncode == 1
        assert "still marked unreleased" in done.stderr and "W-29" in done.stderr
        assert done.stdout == ""
    else:
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip() == rn.section(text, version).strip()


# -- scripts/release_notes.py: the tag check ------------------------------------------------------


def _repo(tmp_path: Path, project: str, manifest: str) -> Path:
    root = tmp_path / "repo"
    (root / "plugin" / ".claude-plugin").mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{project}"\n', encoding="utf-8")
    (root / "plugin" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "x", "version": manifest}),
                                                                    encoding="utf-8")  # fmt: skip
    return root


def test_check_tag_passes_when_tag_and_both_versions_agree(rn, tmp_path):
    root = _repo(tmp_path, "1.2.0", "1.2.0")
    assert rn.check_tag("v1.2.0", root) == "1.2.0"
    done = _run("--check-tag", "v1.2.0", "--root", str(root))
    assert done.returncode == 0 and done.stdout.strip() == "1.2.0"


@pytest.mark.parametrize(
    "tag, project, manifest, why",
    [
        ("v1.2.1", "1.2.0", "1.2.0", "does not match"),
        ("1.2.0", "1.2.0", "1.2.0", "does not match"),  # no leading v
        ("v1.2.0-rc1", "1.2.0", "1.2.0", "does not match"),
        ("v1.2.0", "1.2.0", "1.1.0", "plugin.json says 1.1.0"),
    ],
)
def test_check_tag_refuses_a_mismatch(rn, tmp_path, tag, project, manifest, why):
    root = _repo(tmp_path, project, manifest)
    with pytest.raises(rn.ReleaseError, match=why):
        rn.check_tag(tag, root)
    done = _run("--check-tag", tag, "--root", str(root))
    assert done.returncode == 1 and why in done.stderr


def test_check_tag_on_this_repo():
    assert _run("--check-tag", f"v{_version()}").returncode == 0
    assert _run("--check-tag", "v999.0.0").returncode == 1


def test_release_notes_is_stdlib_only():
    tree = SCRIPT.read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from) (\w+)", tree, re.MULTILINE))
    assert imported <= {"__future__", "argparse", "json", "re", "sys", "tomllib", "pathlib"}


# -- .github/workflows/release.yml ----------------------------------------------------------------


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on(workflow: dict) -> dict:
    """The `on:` block (YAML 1.1 reads a bare `on` key as True)."""
    return workflow.get("on", workflow.get(True))


@pytest.fixture(scope="module")
def release() -> dict:
    return _load(RELEASE)


@pytest.fixture(scope="module")
def draft(release) -> dict:
    return release["jobs"]["draft"]


def _steps_text(job: dict) -> str:
    return "\n".join(str(step.get(key, "")) for step in job.get("steps", []) for key in ("name", "uses", "run"))


def test_release_runs_only_on_a_pushed_v_tag(release):
    assert _on(release) == {"push": {"tags": ["v*"]}}


def test_release_reads_by_default_and_writes_only_in_the_draft_job(release, draft):
    assert release["permissions"] == {"contents": "read"}
    assert draft["permissions"] == {"contents": "write"}
    for name, job in release["jobs"].items():
        if name != "draft":
            assert "write" not in json.dumps(job.get("permissions", {})), name


def test_release_runs_the_ci_checks_first(release, draft):
    assert release["jobs"]["checks"]["uses"] == "./.github/workflows/ci.yml"
    assert draft["needs"] == "checks"


def test_ci_can_be_called_and_still_runs_when_it_did(release):
    on = _on(_load(CI))
    assert set(on) == {"pull_request", "push", "workflow_call"}
    assert on["push"] == {"branches": ["main"]}
    assert on["pull_request"] is None and on["workflow_call"] is None


def test_release_checks_the_tag_and_the_notes_before_it_builds(draft):
    runs = [str(step.get("run", "")) for step in draft["steps"]]
    check = next(i for i, run in enumerate(runs) if "scripts/release_notes.py --check-tag \"$TAG\"" in run)
    build = next(i for i, run in enumerate(runs) if "scripts/build_plugin_zip.py" in run)
    notes = next(i for i, run in enumerate(runs) if re.search(r"release_notes\.py \"\$VERSION\" --out", run))
    create = next(i for i, run in enumerate(runs) if "gh release create" in run)
    assert check < notes < build < create  # a stub changelog stops the run before the build
    assert draft["env"]["TAG"] == "${{ github.ref_name }}"


def test_release_drafts_only_a_commit_that_is_on_main(draft):
    """gitleaks-action scans no commits on a tag push, so the checks job's secret scan proves
    nothing there. The draft job checks out the full history and refuses a tagged commit that is
    not on main (a commit on main had its scan in ci.yml), before anything else runs."""
    checkout = draft["steps"][0]
    assert checkout["uses"] == "actions/checkout@v5" and checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    runs = [str(step.get("run", "")) for step in draft["steps"]]
    on_main = next(i for i, run in enumerate(runs) if "git merge-base --is-ancestor HEAD origin/main" in run)
    assert "exit 1" in runs[on_main]
    check = next(i for i, run in enumerate(runs) if "--check-tag" in run)
    create = next(i for i, run in enumerate(runs) if "gh release create" in run)
    assert on_main == 1 and on_main < check < create


def test_release_creates_a_draft_with_the_zip_and_the_notes(draft):
    step = next(step for step in draft["steps"] if "gh release create" in str(step.get("run", "")))
    run = " ".join(step["run"].split())
    assert run.startswith('gh release create "$TAG" --draft --verify-tag')
    assert '--notes-file "$RUNNER_TEMP/notes.md"' in run
    assert run.endswith('"dist/dj-librarian-plugin-$VERSION.zip"')
    assert step["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    assert step["env"]["GH_REPO"] == "${{ github.repository }}"


def test_release_never_publishes(release):
    text = RELEASE.read_text(encoding="utf-8").casefold()
    steps = "\n".join(_steps_text(job) for job in release["jobs"].values()).casefold()
    for word in ("pypi", "twine", "publish", "uv build", "npm"):
        assert word not in steps, word
    assert "pypa/gh-action-pypi-publish" not in text and "secrets.pypi" not in text
    assert "--draft=false" not in text and "gh release edit" not in text
    assert steps.count("gh release create") == 1 and "--draft" in steps


def test_release_pins_actions_the_way_ci_does(release):
    ci_uses = set(re.findall(r"uses:\s*(\S+)", CI.read_text(encoding="utf-8")))
    for job in release["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                assert step["uses"] in ci_uses, step["uses"]


# -- README: Try it before the release ------------------------------------------------------------


def _readme_section(title: str) -> str:
    text = README.read_text(encoding="utf-8").replace("\r\n", "\n")
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    sections = {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}
    return sections[title]


def test_readme_tells_a_tester_how_to_install_the_zip():
    section = _readme_section("Try it before the release")
    steps = re.findall(r"^(\d)\. (.+)$", section, re.MULTILINE)
    assert [n for n, _ in steps] == ["1", "2", "3", "4", "5"]
    assert "scripts/build_plugin_zip.py" in section and "draft GitHub release" in section
    assert "**Customize → Plugins → Add → Upload plugin**" in section
    assert "Door 1" in section and "reports/<date>-library.html" in section
    assert "export your collection" in section and "connect a folder" in section


def test_readme_sends_the_tester_to_cowork_and_starts_with_start():
    """Door 1 connects a folder, which only a Cowork task can do; dj-start answers "start", while
    "set me up" is the engine card's phrase."""
    section = _readme_section("Try it before the release")
    steps = dict(re.findall(r"^(\d)\. (.+)$", section, re.MULTILINE))
    assert 'Cowork task and say "start"' in steps["3"]
    assert "connect a folder in Cowork" in steps["4"]
    readme = README.read_text(encoding="utf-8")
    assert '**dj-start** ("start")' in readme and '**dj-start** ("set me up")' not in readme
    skill = (REPO / "plugin" / "skills" / "dj-start" / "SKILL.md").read_text(encoding="utf-8")
    assert '"start"' in skill.split("---", 2)[1]


def test_readme_says_the_engine_needs_a_clone_and_links_the_card():
    section = _readme_section("Try it before the release")
    assert "The engine is not in the zip" in section and "clone" in section
    links = re.findall(r"\]\(([^)]+)\)", section)
    assert "plugin/skills/dj-start/engine.md" in links and "#the-engine-on-windows-and-macos" in links
    assert (REPO / "plugin" / "skills" / "dj-start" / "engine.md").is_file()
    assert "### The engine on Windows and macOS" in README.read_text(encoding="utf-8")
