"""dj-report, Door 1: restructure proposals and the one-file HTML report (R-401 ... R-406).

    python3 report.py [propose|render] --library DIR [--today YYYY-MM-DD]

propose: 2 or 3 proposals from the latest export into structure/proposals.yaml (an edited copy
         is kept first). render: reports/<date>-library.html from the folder's files (a new file
         every time: -2, -3 ...). No command: both, with one log.md line.
Prints one JSON object on stdout; exit 0 = done, 1 = error, 2 = refused (the folder has no
valid library.yaml, or is a whole drive or the home folder: nothing written). Never touches
rekordbox, Spotify or audio files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import dj  # noqa: F401  (engine venv, or a future PyPI install)
except ImportError:  # plugin inside a clone of the repo
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2


class _Parser(argparse.ArgumentParser):
    """A usage error is an error (exit 1, one JSON object), not argparse's exit 2 (refused)."""

    def error(self, message: str) -> None:  # type: ignore[override]
        _emit({"ok": False, "error": f"usage: {message}"})
        raise SystemExit(EXIT_ERROR)


def _emit(data: dict) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character
    except (AttributeError, ValueError):
        pass
    print(json.dumps(data, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Restructure proposals and the HTML report for a dj-library folder.")
    parser.add_argument("command", nargs="?", choices=("propose", "render"), help="one step only (default: both)")
    parser.add_argument("--library", required=True, help="the dj-library folder")
    parser.add_argument("--today", help="date of the files, YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)

    try:
        from dj import report
        from dj.analysis import proposals
        from dj.analysis.common import NotALibraryFolder, parse_day
        from dj.model import LibraryError
        from dj.treeschema import TreeSchemaError
    except ImportError as exc:  # no engine venv and not inside a clone of the repo
        _emit({"ok": False, "error": f"cannot load the dj-librarian core: {exc}"})
        return EXIT_ERROR

    try:
        today = parse_day(args.today)
        if args.command == "propose":
            result = proposals.run(Path(args.library), today=today)
        elif args.command == "render":
            result = report.run_render(Path(args.library), today=today)
        else:
            result = report.run_report(Path(args.library), today=today)
    except NotALibraryFolder as exc:
        _emit({"ok": False, "refused": str(exc)})
        return EXIT_REFUSED
    except (LibraryError, TreeSchemaError, OSError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc)})
        return EXIT_ERROR
    _emit({"ok": True, **result})
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
