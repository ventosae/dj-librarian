"""dj-profile, Door 1: measure the library from its latest export (R-311).

    python3 profile.py --library DIR [--xml FILE] [--today YYYY-MM-DD]

Writes profile/stats.md and profile/facts.json in the library folder and one line in log.md.
Never writes profile/habits.md (Claude writes it, R-312) and never touches rekordbox, Spotify
or audio files (R-341). A relative --xml is looked up in the library folder first, then in the
current folder. Prints one JSON object on stdout; exit 0 = done, 1 = error, 2 = refused (the
folder has no valid library.yaml, or is a whole drive or the home folder: nothing written).
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
        print(json.dumps({"ok": False, "error": message}))
        raise SystemExit(EXIT_ERROR)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Measure the library: profile/stats.md + profile/facts.json.")
    parser.add_argument("--library", required=True, help="the dj-library folder")
    parser.add_argument("--xml", help="read this collection XML instead of the latest export")
    parser.add_argument("--today", help="date written into the files, YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)

    from dj.analysis import profile
    from dj.analysis.common import NotALibraryFolder, parse_day
    from dj.model import LibraryError

    try:
        result = profile.run(Path(args.library), xml=args.xml, today=parse_day(args.today))
    except NotALibraryFolder as exc:
        print(json.dumps({"ok": False, "refused": str(exc)}))
        return EXIT_REFUSED
    except (LibraryError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return EXIT_ERROR
    print(json.dumps({"ok": True, **result}))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
