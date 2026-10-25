"""Bump the version everywhere it is written, from pyproject.toml, the one source (W-37). Stdlib only.

    uv run python scripts/bump_version.py patch|minor [--today YYYY-MM-DD]

`patch` 0.1.0 -> 0.1.1, `minor` 0.1.1 -> 0.2.0 (CONTRIBUTING.md, "Versioning", says which). It writes
the new version into

- `pyproject.toml` (`[project] version`) and the project's own entry in `uv.lock`;
- `plugin/.claude-plugin/plugin.json`, the dj-librarian entry of `.claude-plugin/marketplace.json`
  and `mcpb/manifest.json`;
- `CHANGELOG.md`: the `[Unreleased]` entries become `## [<version>] - <date>`, with a fresh, empty
  `## [Unreleased]` above them.

The zip names (`scripts/build_plugin_zip.py`: `dj-librarian-plugin-<version>.zip`, the light zip, the
`.mcpb`) and the zip's `engine/BUILD.txt` stamp are made from pyproject.toml's version when they are
built: nothing to edit there. Each file keeps its own layout (a text edit, not a re-dump). It refuses,
changing nothing, when the files disagree before the bump (`tests/test_version_sync.py` fails on that
drift too), when `[Unreleased]` holds no entry, or when CHANGELOG already has the new version. Prints
one JSON object: the old and new version, the files written, the zip name. Never tags, commits or
pushes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = Path("pyproject.toml")
UV_LOCK = Path("uv.lock")
PLUGIN_JSON = Path("plugin") / ".claude-plugin" / "plugin.json"
MARKETPLACE = Path(".claude-plugin") / "marketplace.json"
MCPB = Path("mcpb") / "manifest.json"
CHANGELOG = Path("CHANGELOG.md")
NAME = "dj-librarian"
_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_UNRELEASED = "## [Unreleased]"


class BumpError(RuntimeError):
    """Nothing was changed. The message is one line."""


def next_version(current: str, part: str) -> str:
    match = _SEMVER.fullmatch(current)
    if not match:
        raise BumpError(f"pyproject.toml's version {current!r} is not MAJOR.MINOR.PATCH.")
    major, minor, patch = (int(n) for n in match.groups())
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    raise BumpError(f"say patch or minor, not {part!r}.")


def _json_version(text: str, where: str) -> str:
    data = json.loads(text)
    if where == "marketplace":
        entry = next((p for p in data.get("plugins", []) if p.get("name") == NAME), {})
        return str(entry.get("version", ""))
    return str(data.get("version", ""))


def versions(root: Path = REPO) -> dict[str, str]:
    """The version each file says (uv.lock: the project's own package entry)."""
    lock = re.search(rf'\[\[package\]\]\nname = "{NAME}"\nversion = "([^"]+)"', (root / UV_LOCK).read_text(encoding="utf-8"))
    return {
        "pyproject.toml": tomllib.loads((root / PYPROJECT).read_text(encoding="utf-8"))["project"]["version"],
        "uv.lock": lock.group(1) if lock else "",
        "plugin.json": _json_version((root / PLUGIN_JSON).read_text(encoding="utf-8"), "plugin"),
        "marketplace.json": _json_version((root / MARKETPLACE).read_text(encoding="utf-8"), "marketplace"),
        "mcpb/manifest.json": _json_version((root / MCPB).read_text(encoding="utf-8"), "mcpb"),
    }


def _sub_once(pattern: str, repl: str, text: str, where: str) -> str:
    out, n = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if n != 1:
        raise BumpError(f"{where}: the version line was not found.")
    return out


def changelog(text: str, new: str, day: date) -> str:
    """[Unreleased]'s entries under `## [<new>] - <day>`, a fresh empty [Unreleased] above."""
    if _UNRELEASED not in text:
        raise BumpError("CHANGELOG.md has no [Unreleased] section.")
    if re.search(rf"^## \[{re.escape(new)}\]", text, re.MULTILINE):
        raise BumpError(f"CHANGELOG.md already has a [{new}] section.")
    head, rest = text.split(_UNRELEASED, 1)
    following = re.search(r"^## \[", rest, re.MULTILINE)
    entries = rest[: following.start()] if following else rest
    if not re.search(r"^- ", entries, re.MULTILINE):
        raise BumpError("CHANGELOG.md's [Unreleased] holds no entry: nothing to release.")
    return f"{head}{_UNRELEASED}\n\n## [{new}] - {day.isoformat()}{rest}"


def bump(part: str, *, root: Path = REPO, today: date | None = None) -> dict[str, object]:
    found = versions(root)
    if len(set(found.values())) != 1:
        raise BumpError("the versions disagree, fix them first: " + ", ".join(f"{k} {v or '-'}" for k, v in found.items()))
    old = found["pyproject.toml"]
    new = next_version(old, part)
    q = re.escape(old)
    texts = {rel: (root / rel).read_text(encoding="utf-8") for rel in (PYPROJECT, UV_LOCK, PLUGIN_JSON, MARKETPLACE,
                                                                       MCPB, CHANGELOG)}  # fmt: skip
    out = {
        PYPROJECT: _sub_once(rf'^version = "{q}"$', f'version = "{new}"', texts[PYPROJECT], "pyproject.toml"),
        UV_LOCK: _sub_once(rf'^(\[\[package\]\]\nname = "{NAME}"\nversion = )"{q}"$', rf'\g<1>"{new}"',
                           texts[UV_LOCK], "uv.lock"),  # fmt: skip
        PLUGIN_JSON: _sub_once(rf'^(\s*"version": )"{q}"', rf'\g<1>"{new}"', texts[PLUGIN_JSON], "plugin.json"),
        MARKETPLACE: _sub_once(rf'("name": "{NAME}",(?:\n[^\n]*)*?\n\s*"version": )"{q}"', rf'\g<1>"{new}"',
                               texts[MARKETPLACE], "marketplace.json"),  # fmt: skip
        MCPB: _sub_once(rf'^(  "version": )"{q}"', rf'\g<1>"{new}"', texts[MCPB], "mcpb/manifest.json"),
        CHANGELOG: changelog(texts[CHANGELOG], new, today or date.today()),
    }
    for rel, text in out.items():  # everything is checked before the first write
        with open(root / rel, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    after = versions(root)
    if set(after.values()) != {new}:
        raise BumpError(f"after the bump the versions still disagree: {after}")
    return {"old": old, "new": new, "files": [rel.as_posix() for rel in out], "zip": f"dj-librarian-plugin-{new}.zip"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bump the version from pyproject.toml (patch or minor).")
    parser.add_argument("part", choices=("patch", "minor"))
    parser.add_argument("--today", type=date.fromisoformat, help="the CHANGELOG date (YYYY-MM-DD)")
    parser.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(bump(args.part, root=args.root, today=args.today)))
    except (BumpError, OSError, ValueError, KeyError) as exc:
        print(f"bump_version: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
