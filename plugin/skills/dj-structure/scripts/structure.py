"""dj-structure: measure the DJ's playlist tree and write structure/ (R-321, R-322, R-302).

    python structure.py --library DIR [--xml FILE] [--today YYYY-MM-DD]

Reads the newest export in DIR/exports/ (or --xml), writes structure/analysis.md, graph.json,
facts.json and current-tree.yaml, appends one log.md line. Prints one JSON object on stdout.
Exit 0 = done, 1 = error. Never writes to rekordbox, Spotify or audio files (R-341).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

try:
    import dj  # noqa: F401  (engine venv, or a future PyPI install)
except ImportError:  # plugin inside a clone of the repo
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

EXIT_OK, EXIT_ERROR = 0, 1


class _Parser(argparse.ArgumentParser):
    """A usage error is an error like any other: one JSON object, exit 1."""

    def error(self, message: str) -> None:  # type: ignore[override]
        _emit({"ok": False, "error": f"usage: {message}"})
        sys.exit(EXIT_ERROR)


def _emit(data: dict) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character
    except (AttributeError, ValueError):
        pass
    print(json.dumps(data, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Measure the playlist tree and write structure/ in the library folder.")
    parser.add_argument("--library", required=True, help="The dj-library folder.")
    parser.add_argument("--xml", help="A collection XML to read instead of the newest export.")
    parser.add_argument("--today", help="Date written into the files, YYYY-MM-DD. Default: today.")
    args = parser.parse_args(argv)
    try:
        from dj.analysis import structure
        from dj.model import LibraryError
        from dj.treeschema import TreeSchemaError
    except ImportError as exc:  # no engine venv and not inside a clone of the repo (Q-06)
        _emit({"ok": False, "error": f"cannot load the dj-librarian core: {exc}", "reason": "core"})
        return EXIT_ERROR
    try:
        today = date.fromisoformat(args.today) if args.today else None
        result = structure.run(Path(args.library), xml=args.xml, today=today)
    except (LibraryError, TreeSchemaError, OSError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc)})
        return EXIT_ERROR
    _emit({"ok": True, **result})
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
