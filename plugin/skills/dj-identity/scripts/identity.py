"""dj-identity, Door 1: six measured axes, an archetype and the sleeve (R-1401 ... R-1403).

    python3 identity.py --library DIR [--xml FILE] [--today YYYY-MM-DD]

Reads profile/facts.json, structure/facts.json and taste/facts.json (run dj-profile,
dj-structure and dj-taste first) and the export they came from; writes profile/identity.json
and profile/sleeve.svg in the library folder and one line in log.md. Never writes
profile/identity.md (Claude writes the liner notes, R-1404) and never touches rekordbox,
Spotify or audio files. --today fixes the date the axes are measured at (default: the date in
profile/facts.json). Prints one JSON object on stdout; exit 0 = done, 1 = error (a facts file
missing, facts from another export), 2 = refused (the folder has no valid library.yaml, or is a
whole drive or the home folder: nothing written).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # the dj core, in this order (D-29): importable (engine venv or PyPI), a clone, the plugin zip
    import dj  # noqa: F401
except ImportError:  # a clone of the repo keeps it in ../../../../src, the plugin zip in ../../../engine/src
    _here = Path(__file__).resolve().parent
    for _core in (_here / "../../../../src", _here / "../../../engine/src"):
        if (_core / "dj" / "__init__.py").is_file():
            sys.path.insert(0, str(_core.resolve()))
            break

EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2
ARCHETYPES = Path(__file__).resolve().parents[1] / "archetypes.yaml"  # this skill's own table


class _Parser(argparse.ArgumentParser):
    """A usage error is an error (exit 1, one JSON object), not argparse's exit 2 (refused)."""

    def error(self, message: str) -> None:  # type: ignore[override]
        _emit({"ok": False, "error": f"usage: {message}"})
        raise SystemExit(EXIT_ERROR)


def _emit(data: dict) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # a handle can hold any character
    except (AttributeError, ValueError):
        pass
    print(json.dumps(data, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="The DJ's identity: profile/identity.json + profile/sleeve.svg.")
    parser.add_argument("--library", required=True, help="the dj-library folder")
    parser.add_argument("--xml", help="read this collection XML instead of the latest export")
    parser.add_argument("--today", help="the date the axes are measured at, YYYY-MM-DD")
    args = parser.parse_args(argv)

    try:
        from dj.analysis import identity
        from dj.analysis.common import NotALibraryFolder, parse_day
        from dj.model import LibraryError
    except ImportError as exc:  # no engine venv and not inside a clone of the repo (Q-06)
        _emit({"ok": False, "error": f"cannot load the dj-librarian core: {exc}", "reason": "core"})
        return EXIT_ERROR

    try:
        result = identity.run(Path(args.library), xml=args.xml, today=parse_day(args.today), archetypes=ARCHETYPES)
    except NotALibraryFolder as exc:
        _emit({"ok": False, "refused": str(exc)})
        return EXIT_REFUSED
    except (LibraryError, OSError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc)})
        return EXIT_ERROR
    _emit({"ok": True, **result})
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
