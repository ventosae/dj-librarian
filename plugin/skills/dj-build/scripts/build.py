"""dj-build skill script (Door 1): preview a structure proposal, or write its rekordbox XML
after the DJ's explicit yes. A thin wrapper around `dj.build_structure`.

    python build.py preview "<proposal>" [--library DIR] [--today YYYY-MM-DD]
    python build.py apply "<proposal>" --preview-id ID [--library DIR] [--today YYYY-MM-DD]

<proposal> = the slug, the name, or "Build me the <name> structure". --library defaults to the
configured dj-library folder. Prints one JSON object on stdout.
Exit 0 = done, 1 = error, 2 = refused (no valid preview id: preview again, ask again).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, NoReturn

try:
    import dj  # noqa: F401  (engine venv, or a future PyPI install)
except ImportError:  # plugin inside a clone of the repo
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2


def emit(data: dict[str, Any], code: int) -> NoReturn:
    sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    raise SystemExit(code)


class Parser(argparse.ArgumentParser):
    """Usage errors are errors (exit 1, JSON), not argparse's exit 2 (which means refused here)."""

    def error(self, message: str) -> NoReturn:
        emit({"ok": False, "error": message}, EXIT_ERROR)


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = Parser(prog="build.py", description="Preview a proposal, or write its XML after a yes.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "apply"):
        cmd = sub.add_parser(name)
        cmd.add_argument("proposal", help="slug, name, or 'Build me the <name> structure'")
        cmd.add_argument("--library", help="the dj-library folder (default: the configured one)")
        cmd.add_argument("--today", help="date for new files and library.yaml, YYYY-MM-DD")
        if name == "apply":
            cmd.add_argument("--preview-id", default="", help="the id the preview returned")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> NoReturn:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse(argv)
    if args.command == "apply" and not args.preview_id.strip():
        emit({"ok": False, "refused": "No preview id: run the preview, show it, write only after a yes."},
             EXIT_REFUSED)  # fmt: skip

    from dj import build_structure, libfolder
    from dj.gate import GateError
    from dj.model import LibraryError
    from dj.treeschema import TreeSchemaError

    try:
        today = date.fromisoformat(args.today) if args.today else None
    except ValueError:
        emit({"ok": False, "error": f"--today: expected YYYY-MM-DD, got {args.today!r}"}, EXIT_ERROR)
    try:
        root = Path(args.library) if args.library else libfolder.configured_root()
        if not root.is_dir():
            emit({"ok": False, "error": f"{root} is not a folder. Run dj-start first."}, EXIT_ERROR)
        if args.command == "preview":
            data = build_structure.preview(root, args.proposal, today=today).to_dict(root)
        else:
            result = build_structure.apply(root, args.proposal, args.preview_id.strip(), today=today)
            data = result.to_dict()
    except GateError as exc:
        emit({"ok": False, "refused": str(exc)}, EXIT_REFUSED)
    except (build_structure.BuildError, TreeSchemaError, LibraryError, OSError) as exc:
        emit({"ok": False, "error": str(exc)}, EXIT_ERROR)
    emit({"ok": True, **data}, EXIT_OK)


if __name__ == "__main__":
    main()
