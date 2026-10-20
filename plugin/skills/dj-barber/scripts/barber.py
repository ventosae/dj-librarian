"""dj-barber: Style Barber, one short question at a time that sharpens taste/ (R-701, R-703).

    python barber.py next --library DIR [--today YYYY-MM-DD]
    python barber.py record N ANSWER --library DIR [--today YYYY-MM-DD]

`next` plans today's session (at most 8 questions) or resumes it, and prints the next question.
`record` appends the answer as one dated line to a taste file and prints the next question or
"done". Prints one JSON object on stdout. Exit 0 done, 1 error (an answer the question does not
take writes nothing), 2 refused (DIR is not a dj-library folder: no valid library.yaml).
Writes taste/*.md lines, .cache/barber.json and log.md; never rekordbox, Spotify or audio files.
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
    parser = _Parser(description="Style Barber: the next question, or record an answer (dj-barber).")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    nxt = commands.add_parser("next", help="plan or resume today's session; print the next question")
    rec = commands.add_parser("record", help="record the answer to question N")
    rec.add_argument("n", type=int, help="the question number")
    rec.add_argument("answer", help="a chip (A, B, keep, never, good), its number, free text, or skip")
    for sub in (nxt, rec):
        sub.add_argument("--library", required=True, help="the dj-library folder")
        sub.add_argument("--today", default=None, help="the session date, YYYY-MM-DD")
    args = parser.parse_args(argv)

    try:
        from dj import barber
        from dj.analysis.common import NotALibraryFolder
        from dj.model import LibraryError
    except ImportError as exc:  # no engine venv and not inside a clone of the repo
        _emit({"ok": False, "error": f"cannot load the dj core: {exc}"}, EXIT_ERROR)

    try:
        today = date.fromisoformat(args.today) if args.today else None
        if args.command == "next":
            result = barber.next_step(args.library, today=today)
        else:
            result = barber.answer(args.library, args.n, args.answer, today=today)
    except NotALibraryFolder as exc:
        _emit({"ok": False, "refused": str(exc)}, EXIT_REFUSED)
    except (LibraryError, OSError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc)}, EXIT_ERROR)
    except Exception as exc:  # still one JSON object on stdout, never a bare traceback
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, EXIT_ERROR)
    _emit({"ok": True, **result}, EXIT_OK)


if __name__ == "__main__":
    main()
