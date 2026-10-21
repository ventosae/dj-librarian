"""dj-taste: measure the DJ's taste from the latest export and append it to taste/*.md.

    python taste.py --library DIR [--xml FILE] [--today YYYY-MM-DD] [--rebuild]

Prints one JSON object on stdout. Exit 0 done, 1 error, 2 refused (DIR is not a dj-library
folder: no library.yaml). Appends only; `--rebuild` rewrites taste/*.md from scratch and is
passed only after the DJ said yes to it (R-332). Reads the export; never writes to rekordbox,
Spotify or audio files (R-341).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

try:  # the dj core, in this order (D-22): importable (engine venv or PyPI), a clone, the plugin zip
    import dj  # noqa: F401
except ImportError:  # a clone of the repo keeps it in ../../../../src, the plugin zip in ../../../vendor
    _here = Path(__file__).resolve().parent
    for _core in (_here / "../../../../src", _here / "../../../vendor"):
        if (_core / "dj" / "__init__.py").is_file():
            sys.path.insert(0, str(_core.resolve()))
            break

EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # argparse would exit 2, which means "refused" here
        _emit({"ok": False, "error": message}, EXIT_ERROR)


def _emit(data: dict, code: int) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(code)


def main(argv: list[str] | None = None) -> None:
    parser = _Parser(description="Append the DJ's taste to taste/*.md (dj-taste).")
    parser.add_argument("--library", required=True, help="the dj-library folder")
    parser.add_argument("--xml", default=None, help="an export to read instead of the latest one")
    parser.add_argument("--today", default=None, help="date for new entries, YYYY-MM-DD")
    parser.add_argument("--rebuild", action="store_true", help="rewrite from scratch (only after a yes)")
    args = parser.parse_args(argv)

    try:
        from dj.analysis import taste
        from dj.model import LibraryError
    except ImportError as exc:  # no engine venv and not inside a clone of the repo
        _emit({"ok": False, "error": f"cannot load the dj core: {exc}"}, EXIT_ERROR)

    try:
        today = date.fromisoformat(args.today) if args.today else None
        result = taste.run(args.library, xml=args.xml, today=today, rebuild=args.rebuild)
    except taste.NotALibraryFolder as exc:
        _emit({"ok": False, "refused": str(exc)}, EXIT_REFUSED)
    except taste.TasteWriteError as exc:  # failed part way: show what was written and added
        _emit({"ok": False, "error": str(exc), "written": exc.written, "added": exc.added}, EXIT_ERROR)
    except (LibraryError, OSError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc)}, EXIT_ERROR)
    except Exception as exc:  # still one JSON object on stdout, never a bare traceback
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, EXIT_ERROR)
    _emit({"ok": True, **result}, EXIT_OK)


if __name__ == "__main__":
    main()
