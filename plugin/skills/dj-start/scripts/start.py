"""dj-start: set up the DJ's library folder from their rekordbox XML export (R-103, R-104).

    start.py find-xml --library DIR
    start.py init --library DIR --device mac|windows [--dj-name NAME] [--xml FILE] [--today YYYY-MM-DD]

Argument parsing around dj.onboarding (find_xml, init); the rules live there. A relative --xml
is looked up in the library folder first, then in the current folder.

Prints one JSON object on stdout. Exit 0 = done; 1 = error, 2 = refused: then the JSON holds one
line in "error" and its kind in "reason" (no_xml, xml, folder, usage, core, disk; refused for
exit 2; internal for a bug). Every path in the JSON is POSIX and relative to the library folder.

Door 1: dj.onboarding is stdlib + PyYAML, so this runs in Cowork's sandbox without the engine
(Q-06). When the dj core cannot be imported at all, the script still prints one JSON object.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    import dj  # noqa: F401  (engine venv, or a future PyPI install)
except ImportError:  # plugin inside a clone of the repo
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

try:
    from dj import onboarding
except ImportError as exc:  # neither installed nor inside a clone of the repo (Q-06)
    onboarding = None
    CORE_MISSING = " ".join(f"The dj-librarian core does not load where this runs ({exc}).".split())

try:  # the plugin's own folder: never a library folder, nor one that holds it
    PLUGIN_ROOT: Path | None = Path(__file__).resolve().parents[3]
except IndexError:
    PLUGIN_ROOT = None


class ScriptError(Exception):
    """A bad argument: one line for the JSON, exit 1, reason `usage`."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _Parser(argparse.ArgumentParser):
    """argparse that reports a bad argument as JSON with exit 1, not as usage text with exit 2."""

    def error(self, message: str):  # type: ignore[override]
        raise ScriptError(f"{self.prog}: {message}")


def _library(text: str) -> Path:
    return onboarding.library_root(text, keep_out=[PLUGIN_ROOT] if PLUGIN_ROOT else [])


def cmd_find_xml(args: argparse.Namespace) -> dict[str, Any]:
    return onboarding.find_xml(_library(args.library))


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    root = _library(args.library)
    xml = _xml_arg(root, args.xml) if args.xml else None
    return onboarding.init(
        root, device=args.device, xml=xml, today=args.today, now=_now(args.today), dj_name=args.dj_name
    )


def _xml_arg(root: Path, text: str) -> Path:
    path = Path(text).expanduser()
    if not path.is_absolute():
        in_library = root / path
        path = in_library if in_library.is_file() else Path.cwd() / path
    return path  # a missing file is init's `xml` error


def _now(today: date | None) -> datetime:
    """The log time: now, on --today's date when one is given (tests pin the date)."""
    now = datetime.now()
    return now if today is None else datetime.combine(today, now.time())


def _day(text: str) -> date:
    try:
        if len(text) != 10:
            raise ValueError(text)
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a date YYYY-MM-DD, got {text!r}") from None


def _one_line(exc: BaseException) -> str:
    if isinstance(exc, OSError) and exc.strerror:
        name = f": {Path(str(exc.filename)).name}" if exc.filename else ""
        text = f"{exc.strerror}{name}"
    else:
        text = str(exc) or type(exc).__name__
    return " ".join(text.split())


def _parser() -> _Parser:
    parser = _Parser(prog="start.py", description="dj-start: set up the library folder.")
    sub = parser.add_subparsers(dest="command", required=True)

    find = sub.add_parser("find-xml", help="the newest rekordbox XML in the folder")
    find.add_argument("--library", required=True, help="the library folder")
    find.set_defaults(run=cmd_find_xml)

    init = sub.add_parser("init", help="scaffold the folder and copy the XML into exports/")
    init.add_argument("--library", required=True, help="the library folder")
    init.add_argument(
        "--device", required=True, type=str.lower, choices=onboarding.DEVICES, help="mac or windows"
    )
    init.add_argument("--dj-name", help="what they call the DJ in the booth (optional; the sleeve says You without it)")
    init.add_argument("--xml", help="the export; default: the newest XML in the folder")
    init.add_argument("--today", type=_day, help="YYYY-MM-DD; default: today")
    init.set_defaults(run=cmd_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    if onboarding is None:
        out, code = {"error": CORE_MISSING, "reason": "core"}, 1
    else:
        try:
            args = _parser().parse_args(argv)
            out, code = args.run(args), 0
        except ScriptError as exc:
            out, code = {"error": " ".join(exc.message.split()), "reason": "usage"}, 1
        except onboarding.OnboardingError as exc:
            out, code = {"error": exc.message, "reason": exc.reason}, exc.code
        except OSError as exc:  # permissions, a full disk, a folder that went away
            out, code = {"error": _one_line(exc), "reason": "disk"}, 1
        except Exception as exc:  # one JSON object, always
            out, code = {"error": _one_line(exc), "reason": "internal"}, 1
    print(json.dumps(out))
    return code


if __name__ == "__main__":
    sys.exit(main())
