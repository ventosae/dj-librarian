"""The personal-data grep (R-1206, C-05, Q-26): real people's names stay out of the shipped files.

    uv run python scripts/check_personal.py

Greps the tracked and new (not ignored) files under PATHS, case-insensitively, for the names of
the real people the project knows: the owner's name as `plugin.json` gives it under `author.name`,
and the named personas of docs/requirements.md (a bold name followed by a role, like the operator
and the test DJ). The names are read, never written here, so this file holds none.

The only hits allowed are the owner's name in exactly three fields: `author.name` in
`plugin/.claude-plugin/plugin.json`, `owner.name` in `.claude-plugin/marketplace.json` and
`author.name` in `mcpb/manifest.json` (the engine bundle, W-34). A hit anywhere else, or a second
hit in those files, fails. Prints one line per problem and exits 1,
or prints `ok` and exits 0. CI runs it; tests/test_personal_data.py runs the same check.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
PATHS = ("src", "tests", "plugin", "examples", "README.md", "CONTRIBUTING.md", "templates", "docs/samples",
         ".claude-plugin", "mcpb")  # fmt: skip
PLUGIN_JSON = "plugin/.claude-plugin/plugin.json"
MARKETPLACE_JSON = ".claude-plugin/marketplace.json"
MCPB_JSON = "mcpb/manifest.json"  # the engine bundle's manifest (W-34): author as in plugin.json
# The one field per file where the owner's name belongs (R-1206 as widened by Q-26).
ALLOWED = {PLUGIN_JSON: ("author", "name"), MARKETPLACE_JSON: ("owner", "name"), MCPB_JSON: ("author", "name")}
_PERSONA = re.compile(r"^\| P-\d+ \| \*\*(.+?)\*\* — ", re.MULTILINE)  # `| P-2 | **Name** — role |`


def names(root: Path = REPO) -> list[str]:
    """The words to look for: the owner's name from plugin.json, the named personas' names."""
    found: list[str] = []
    author = json.loads((root / PLUGIN_JSON).read_text(encoding="utf-8")).get("author", {}).get("name", "")
    found += author.split()
    requirements = root / "docs" / "requirements.md"
    if requirements.is_file():
        for name in _PERSONA.findall(requirements.read_text(encoding="utf-8")):
            found += name.split()
    return sorted({word for word in found if len(word) >= 3}, key=str.casefold)


def grep(root: Path, words: Iterable[str], paths: Iterable[str] = PATHS) -> list[tuple[str, int, str]]:
    """(path, line number, line) for every line of a tracked or new file under `paths` that holds
    one of `words`, any case. git grep, so ignored files (the owner's own state) are skipped."""
    words = list(words)
    if not words:
        return []
    cmd = ["git", "-C", str(root), "grep", "--untracked", "-n", "-i", "-I", "--no-color", "-F"]
    for word in words:
        cmd += ["-e", word]
    done = subprocess.run([*cmd, "--", *paths], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if done.returncode not in (0, 1):  # 1 = no match
        raise RuntimeError(f"git grep failed: {done.stderr.strip()}")
    hits = []
    for line in done.stdout.splitlines():
        path, number, text = line.split(":", 2)
        hits.append((path, int(number), text))
    return hits


def _where(value: Any, words: list[str], at: tuple = ()) -> list[tuple]:
    """The JSON paths (keys and values) in `value` whose text holds one of `words`."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _holds(str(key), words):
                found.append((*at, key, "<key>"))
            found += _where(item, words, (*at, key))
    elif isinstance(value, list):
        for n, item in enumerate(value):
            found += _where(item, words, (*at, n))
    elif isinstance(value, str) and _holds(value, words):
        found.append(at)
    return found


def _holds(text: str, words: list[str]) -> bool:
    return any(word.casefold() in text.casefold() for word in words)


def problems(root: Path, words: list[str], hits: list[tuple[str, int, str]]) -> list[str]:
    """Every hit that is not the owner's name in its one allowed field, one line each."""
    out = []
    by_file: dict[str, list[tuple[int, str]]] = {}
    for path, number, text in hits:
        by_file.setdefault(path, []).append((number, text))
    for path, lines in sorted(by_file.items()):
        field = ALLOWED.get(path)
        if field is None:
            out += [f"{path}:{number}: a real person's name" for number, _text in lines]
            continue
        try:
            data = json.loads((root / path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out.append(f"{path}: not readable JSON ({exc})")
            continue
        where = _where(data, words)
        if where != [field]:
            others = [".".join(map(str, w)) for w in where if w != field]
            out.append(f"{path}: the name may stand only in {'.'.join(field)}; also found in {', '.join(others) or '?'}")
        if len(lines) != 1:
            out.append(f"{path}: {len(lines)} lines hold the name; only the {'.'.join(field)} line may")
        elif not re.fullmatch(rf'\s*"{field[-1]}"\s*:\s*".*",?\s*', lines[0][1]):
            out.append(f"{path}:{lines[0][0]}: the name sits outside the {'.'.join(field)} field")
    return out


def main() -> int:
    if not (REPO / ".git").exists():
        print("not a git checkout: nothing to check")
        return 0
    words = names()
    found = problems(REPO, words, grep(REPO, words))
    for line in found:
        print(line)
    if found:
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
