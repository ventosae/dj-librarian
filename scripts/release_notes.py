"""The release notes for one version, cut from CHANGELOG.md, and the tag check (W-32). Stdlib only.

    uv run python scripts/release_notes.py 0.1.0 [--out FILE] [--changelog PATH]
    uv run python scripts/release_notes.py --check-tag v0.1.0 [--root DIR]

The first form prints (or writes to FILE, UTF-8) the body of the `## [0.1.0] ...` section of
CHANGELOG.md: every line under that heading up to the next `## ` line or the first `[label]: ...`
link-reference line (Keep a Changelog puts those at the end), blank lines trimmed at both ends. It exits 1, with one line on stderr, when:

- the changelog has no section for that version,
- the section holds nothing but blank lines,
- the section's heading still says "unreleased" (or is [Unreleased] itself): the owner moves
  the [Unreleased] entries into the version section and dates it before tagging (W-29), so a tag
  on a changelog that was not moved gets no draft release with a stub body.

The second form checks that the tag is `v<version>` for the version pyproject.toml gives, and that
plugin/.claude-plugin/plugin.json says the same version (CLAUDE.md, Conventions); exit 1 otherwise.

.github/workflows/release.yml runs both on a pushed `v*` tag before it creates the draft release.
Nothing here uploads, tags or publishes anything.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHANGELOG = REPO / "CHANGELOG.md"
PLUGIN_JSON = Path("plugin") / ".claude-plugin" / "plugin.json"
_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\]")
_LINK_REF = re.compile(r"^\[[^\]]+\]:\s*\S")  # `[0.1.0]: https://...` at the end of the file


class ReleaseError(RuntimeError):
    """The notes or the tag are not ready for a release. The message is one line."""


def section(text: str, version: str) -> str:
    """The body of the `## [version]` section of a Keep a Changelog text, trimmed."""
    version = version.removeprefix("v")
    lines = text.splitlines()
    for start, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match["version"].strip() == version:
            break
    else:
        raise ReleaseError(f"CHANGELOG.md has no section [{version}].")
    if "unreleased" in lines[start].casefold():  # `## [0.1.0] — unreleased`, or `## [Unreleased]` itself
        raise ReleaseError(f"CHANGELOG.md section [{version}] is still marked unreleased: move the [Unreleased] "
                           "entries into it and date it before tagging (W-29).")  # fmt: skip
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## ") or _LINK_REF.match(line):
            break
        body.append(line.rstrip())
    notes = "\n".join(body).strip("\n")
    if not notes.strip():
        raise ReleaseError(f"CHANGELOG.md section [{version}] is empty.")
    return notes + "\n"


def versions(root: Path = REPO) -> tuple[str, str]:
    """(pyproject.toml's version, plugin.json's version)."""
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        manifest = json.loads((root / PLUGIN_JSON).read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError) as exc:
        raise ReleaseError(f"cannot read the version from pyproject.toml and plugin.json: {exc}") from None
    return str(project), str(manifest)


def check_tag(tag: str, root: Path = REPO) -> str:
    """The version, when `tag` is `v<version>` and pyproject.toml and plugin.json agree on it."""
    project, manifest = versions(root)
    if project != manifest:
        raise ReleaseError(f"pyproject.toml says {project}, plugin.json says {manifest}: make them equal first.")
    if tag != f"v{project}":
        raise ReleaseError(f"tag {tag} does not match the version: pyproject.toml and plugin.json say {project}, "
                           f"so the tag must be v{project}.")  # fmt: skip
    return project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release notes from CHANGELOG.md, or the tag check (stdlib only).")
    parser.add_argument("version", nargs="?", help="the version whose CHANGELOG.md section to print, e.g. 0.1.0")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG, help="the changelog (default: CHANGELOG.md)")
    parser.add_argument("--out", type=Path, help="write the notes to this file (UTF-8) instead of printing them")
    parser.add_argument("--check-tag", metavar="TAG", help="check that TAG is v<version> of pyproject.toml and plugin.json")
    parser.add_argument("--root", type=Path, default=REPO, help="the repo folder for --check-tag (default: this repo)")
    args = parser.parse_args(argv)
    if (args.version is None) == (args.check_tag is None):
        parser.error("give a version, or --check-tag TAG")
    try:
        if args.check_tag is not None:
            print(check_tag(args.check_tag, args.root.resolve()))
            return 0
        try:
            text = args.changelog.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReleaseError(f"cannot read {args.changelog}: {exc.strerror or exc}") from None
        notes = section(text, args.version)
    except ReleaseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.out is not None:
        args.out.write_text(notes, encoding="utf-8", newline="\n")
    else:
        if hasattr(sys.stdout, "reconfigure"):  # a console on Windows may not be UTF-8
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
