"""Onboarding session 1 (dj-start, W-13): find the DJ's rekordbox XML, set up the library folder.

Door 1 core: stdlib + PyYAML only (through dj.libfolder, dj.readers.xml and dj.model), so the
skill script `plugin/skills/dj-start/scripts/start.py` runs it in Cowork's sandbox (Q-06). The
script is argument parsing around three calls:

    library_root(text, keep_out=...)   the folder, checked; too wide or too busy -> refused
    find_xml(root)                     the newest rekordbox export dropped in it, and its state
    init(root, device=..., xml=None)   scaffold, copy the export into exports/, read it, log

Rules this module keeps:
- Create and add only (hard rule 1). The DJ's XML is only read. `init` reads it in full and
  checks the folder before anything is created, so a bad export or a foreign library.yaml leaves
  the folder as it was.
- One log.md line per change (R-904): `init` appends one when it created something, appended
  `.gitignore` lines or rewrote library.yaml (latest export, rekordbox version, device). A run
  that changed nothing writes nothing.
- The device the DJ gave last wins (R-101): a different device in library.yaml is changed
  through `libfolder.update_meta` and reported as `device_was`. The same goes for the DJ's
  handle (`dj_name`, R-1406): given, it is written to library.yaml; not given, the stored one
  stays.
- Only rekordbox's own export counts as the collection: an XML whose PRODUCT names another
  program (a proposal this tool wrote, for one) is never picked or imported.
- Every path returned is POSIX and relative to the library folder; a file outside it is shown
  by its bare name.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from dj import libfolder
from dj.libfolder import DEVICES, DIRS, FILES, LibraryFolder, LibraryFolderError
from dj.model import LibraryError
from dj.readers.xml import XML_FIELDS_MISSING, XML_NOTES, read_xml

MAX_DEPTH = 3  # folders below the library folder that find_xml looks into
SHOWN = 5  # candidates listed (R-1002 rule 9)
TOOL_DIRS = frozenset({"exports", "proposals"})  # the tool's own XML, never a drop (any case)
CROWDED = 10  # more entries of the DJ's own than this: not a folder to scaffold into
USER_FOLDERS = frozenset(
    {
        "desktop", "documents", "downloads", "music", "movies", "videos", "pictures",
        "onedrive", "dropbox", "icloud drive", "google drive",
    }
)  # fmt: skip

REASONS = ("no_xml", "xml", "folder", "usage", "refused")
NEXT = (
    "Step 4 of 6: run profile, structure, taste and identity, write profile/habits.md and "
    "profile/identity.md, then run the report, each script with --library on this folder."
)
NO_XML = (
    "No rekordbox XML in the library folder. Export the collection in rekordbox "
    "(File > Export Collection in xml format) and drop the file into the folder."
)
NOTHING = "Nothing was created."


class OnboardingError(LibraryFolderError):
    """One line for the DJ, what kind of problem it is, and the exit code.

    `reason`: `no_xml` nothing to import; `xml` the chosen file is not a usable rekordbox
    collection export; `folder` the folder cannot be set up as it is; `usage` a bad argument
    (the caller's mistake); `refused` (code 2) not a folder to set up a library in.
    """

    def __init__(self, message: str, reason: str, code: int = 1) -> None:
        super().__init__(message)
        if reason not in REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        self.message = " ".join(message.split())
        self.reason = reason
        self.code = code


def _refused(message: str) -> OnboardingError:
    return OnboardingError(f"{message} {NOTHING}", "refused", code=2)


# -- the folder ----------------------------------------------------------------------------


def library_root(text: str | Path, *, keep_out: Iterable[str | Path] = ()) -> Path:
    """The library folder, resolved, or OnboardingError.

    Empty text is a usage error (it would mean the current folder). Refused (code 2): a drive
    root, the home folder or a folder holding it (`libfolder`'s own check); a folder inside or
    holding one of `keep_out` (the plugin); and, while the folder is not set up yet (no
    library.yaml), a well-known user folder (Desktop, Documents, Downloads, ...) or one that
    already holds more than CROWDED files and folders of the DJ's own. A file: `folder` error.
    """
    if not str(text).strip():
        raise OnboardingError("--library is empty: give the library folder.", "usage")
    try:
        resolved = Path(text).expanduser().resolve()
    except (OSError, RuntimeError) as exc:  # RuntimeError: `~` with no home folder known
        raise OnboardingError(f"Cannot use that folder: {exc}", "folder") from exc
    try:
        libfolder._library_root(resolved, "the library folder")  # one copy of the drive/home rule
    except LibraryFolderError:
        raise _refused(
            "That folder is a whole drive or the home folder, not a library folder."
        ) from None
    for other in keep_out:
        other = Path(other).resolve()
        if resolved.is_relative_to(other) or other.is_relative_to(resolved):
            raise _refused("That folder is the plugin's own folder or holds it.")
    if resolved.exists() and not resolved.is_dir():
        raise OnboardingError(f"{resolved.name} is a file, not a folder.", "folder")
    if resolved.is_dir() and not LibraryFolder(resolved).library_yaml.exists():
        if resolved.name.casefold() in USER_FOLDERS:
            raise _refused(f"{resolved.name} is a shared user folder, not a library folder.")
        own = _own_entries(resolved)
        if own > CROWDED:
            raise _refused(f"That folder already holds {own} files and folders of yours.")
    return resolved


def _own_entries(root: Path) -> int:
    """Entries that are not the tool's, not hidden and not an XML the DJ dropped."""
    tool = set(DIRS) | set(FILES)
    try:
        names = [entry.name for entry in os.scandir(root)]
    except OSError:
        return 0
    return sum(
        1
        for name in names
        if name not in tool and not name.startswith(".") and not name.lower().endswith(".xml")
    )


def _stored_meta(root: Path) -> dict[str, Any] | None:
    """library.yaml as a dict when there is one and it is valid; None when there is none.

    One that does not read or is not this tool's -> `folder` error, before anything is made.
    """
    path = LibraryFolder(root).library_yaml
    if not path.exists():
        return None
    try:
        meta = libfolder.load_meta(root)
    except (LibraryFolderError, OSError, UnicodeDecodeError) as exc:
        raise OnboardingError(
            f"The library.yaml in that folder does not read ({exc}). {NOTHING}", "folder"
        ) from None
    errors = libfolder.validate_meta(meta)
    if errors:
        shown = "; ".join(errors[:3]) + ("; ..." if len(errors) > 3 else "")
        raise OnboardingError(
            f"The library.yaml in that folder is not one of this tool's ({shown}). {NOTHING}",
            "folder",
        )
    return meta


def folder_state(root: Path) -> dict[str, Any] | None:
    """What a set-up folder already holds: device, the DJ's handle (`dj_name`, None when the folder
    predates it: dj-start asks once), latest export, newest report. None = not set up."""
    meta = _stored_meta(root)
    if meta is None:
        return None
    try:
        latest: str | None = libfolder.relative(root, libfolder.latest_export(root))
    except LibraryError:
        latest = None
    reports = LibraryFolder(root).reports
    found = newest_report(reports.iterdir()) if reports.is_dir() else None
    return {
        "device": meta.get("device"),
        "dj_name": meta.get("dj_name"),
        "latest_export": latest,
        "latest_report": libfolder.relative(root, found) if found else None,
    }


_REPORT_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-library(?:-([1-9]\d*))?\.html$")


def newest_report(paths: Iterable[Path]) -> Path | None:
    """The newest dj-report file: `<date>-library.html`, or `<date>-library-N.html` for the Nth
    report of that day (dj.report writes create-only). Latest date first, then the highest N
    (`-10` after `-2`). Other files are ignored."""
    best: tuple[str, int] | None = None
    found = None
    for path in paths:
        m = _REPORT_NAME.match(path.name)
        if m is None:
            continue
        key = (m.group(1), int(m.group(2) or 1))
        if best is None or key > best:
            best, found = key, path
    return found


# -- find-xml ------------------------------------------------------------------------------


def _is_rekordbox(product: str | None) -> bool:
    """No PRODUCT name, or one that names rekordbox. Another program's XML is not the collection."""
    name = (product or "").strip().casefold()
    return not name or name.startswith("rekordbox")


def is_rekordbox_export(path: str | Path) -> bool:
    """The file starts like a rekordbox collection export: root DJ_PLAYLISTS and, when it has a
    PRODUCT, one that names rekordbox. Reads only the start of the file."""
    parser = ET.XMLPullParser(events=("start",))
    seen = 0
    try:
        with open(path, "rb") as fh:
            while chunk := fh.read(1 << 16):
                parser.feed(chunk)
                for _event, elem in parser.read_events():
                    seen += 1
                    if seen == 1:
                        if elem.tag != "DJ_PLAYLISTS":
                            return False
                        continue
                    return elem.tag != "PRODUCT" or _is_rekordbox(elem.get("Name"))
    except (ET.ParseError, OSError):
        return False
    return False  # empty, or a root with nothing in it


def find_exports(root: str | Path) -> list[Path]:
    """Rekordbox exports dropped in the folder, newest first (same time: by path).

    Skipped: exports/ and proposals/ at the top, in any letter case (a case-insensitive disk
    treats `Proposals` as the tool's folder); hidden folders and files (.cache, macOS ._ files,
    temp files); anything deeper than MAX_DEPTH folders; XML that is not rekordbox's export.
    Symlinked folders are not followed.
    """
    root = Path(root).resolve()
    found: list[tuple[float, str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        depth = len(here.relative_to(root).parts)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".")
            and depth < MAX_DEPTH
            and not (depth == 0 and d.casefold() in TOOL_DIRS)
        )
        for name in filenames:
            if name.startswith(".") or not name.lower().endswith(".xml"):
                continue
            path = here / name
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if is_rekordbox_export(path):
                found.append((mtime, path.relative_to(root).as_posix(), path))
    found.sort(key=lambda item: (-item[0], item[1]))
    return [path for _mtime, _rel, path in found]


def find_xml(root: str | Path) -> dict[str, Any]:
    """{"found", "xml", "candidates", "library"}: the newest export (or None), up to SHOWN
    candidates, and `folder_state` (None while the folder is not set up)."""
    root = Path(root)
    if not root.is_dir():
        raise OnboardingError(
            f"Library folder {root.name} not found. Connect the folder first.", "folder"
        )
    rels = [path.relative_to(root.resolve()).as_posix() for path in find_exports(root)]
    return {
        "found": len(rels),
        "xml": rels[0] if rels else None,
        "candidates": rels[:SHOWN],
        "library": folder_state(root),
    }


# -- init ----------------------------------------------------------------------------------


def _read_source(source: Path):
    """The DJ's XML read in full, before anything is created. Not a usable collection -> `xml`."""
    if not source.is_file():
        raise OnboardingError(f"{source.name}: file not found. Export the collection XML first.", "xml")
    if not is_rekordbox_export(source):
        product = _product_name(source)
        if product is not None:
            raise OnboardingError(
                f"{source.name} was written by {product}, not exported by rekordbox. {NOTHING}",
                "xml",
            )
    try:
        library = read_xml(source)
    except LibraryError as exc:
        raise OnboardingError(f"{exc} {NOTHING}", "xml") from None
    if not library.tracks:
        raise OnboardingError(
            f"{source.name} holds no tracks. Export the whole collection. {NOTHING}", "xml"
        )
    return library


def _product_name(source: Path) -> str | None:
    """PRODUCT Name of a DJ_PLAYLISTS file that is not rekordbox's, for the error line."""
    try:
        product, _version = libfolder.read_product(source)
    except (LibraryError, OSError):
        return None
    return None if _is_rekordbox(product) else " ".join(str(product).split())


def init(
    root: str | Path,
    *,
    device: str,
    xml: str | Path | None = None,
    today: date | None = None,
    now: datetime | None = None,
    dj_name: str | None = None,
) -> dict[str, Any]:
    """Scaffold the folder, copy the export into exports/, read the copy, log one line.

    `root` is a folder `library_root` accepted. Without `xml`, the newest export `find_exports`
    finds is used; none -> `no_xml`. Checked before anything is created: the device, an
    existing library.yaml (must be this tool's) and the whole XML (rekordbox's export, with
    tracks). The original XML is only read; the copy is `exports/<date>-collection.xml`, or
    the existing copy when one has the same content (`new_export` false). `dj_name` (what they
    call the DJ in the booth; one line, at most 40 characters) goes into library.yaml.
    """
    root = Path(root)
    if device not in DEVICES:
        raise OnboardingError(f"device must be one of {', '.join(DEVICES)}, got {device!r}", "usage")
    try:
        dj_name = libfolder.clean_dj_name(dj_name)
    except LibraryFolderError as exc:
        raise OnboardingError(f"--dj-name: {exc}", "usage") from None
    stored = _stored_meta(root) if root.is_dir() else None
    if xml is not None:
        source = Path(xml)
    else:
        found = find_exports(root) if root.is_dir() else []
        if not found:
            raise OnboardingError(NO_XML, "no_xml")
        source = found[0]
    library = _read_source(source)

    try:
        made = libfolder.scaffold(
            root, device=device, rekordbox_version=library.rekordbox_version, today=today,
            dj_name=dj_name,
        )
    except LibraryFolderError as exc:
        raise OnboardingError(str(exc), "folder") from None
    folder = LibraryFolder(root)
    before = {path.name for path in folder.exports.iterdir()}
    try:
        export = libfolder.import_export(root, source, today=today)
    except LibraryFolderError as exc:
        if made.created or made.gitignore_added:  # the scaffold is a change: it gets its line
            libfolder.append_log(
                root, "start", {"created": len(made.created), "skipped": len(made.skipped)}, now=now
            )
        raise OnboardingError(str(exc), "xml") from None

    device_was = None
    if stored is not None and stored.get("device") != device:
        device_was = stored.get("device")
        libfolder.update_meta(root, today=today, device=device)
    if dj_name and libfolder.load_meta(root).get("dj_name") != dj_name:
        libfolder.update_meta(root, today=today, dj_name=dj_name)

    export_rel = libfolder.relative(root, export)
    new_export = export.name not in before
    counts = read_xml(export).counts()
    created, skipped = list(made.created), list(made.skipped)
    (created if new_export else skipped).append(export_rel)
    meta = libfolder.load_meta(root)

    log = None
    if created or made.gitignore_added or meta != stored:
        action = "start" if device_was is None else f"start, device now {device}"
        log = libfolder.append_log(
            root,
            action,
            {"created": len(created), "skipped": len(skipped), "tracks": counts["tracks"]},
            file=export,
            now=now,
        )
    return {
        "created": created,
        "skipped": skipped,
        "gitignore_added": list(made.gitignore_added),
        "source": shown_path(root, source),
        "export": export_rel,
        "new_export": new_export,
        "device": meta.get("device"),
        "device_was": device_was,
        "dj_name": meta.get("dj_name"),
        "rekordbox_version": meta.get("rekordbox_version"),
        "counts": counts,
        "not_in_xml": {"fields": list(XML_FIELDS_MISSING), "notes": list(XML_NOTES)},
        "log": log,
        "next": NEXT,
    }


def shown_path(root: str | Path, path: str | Path) -> str:
    """Relative to the library folder when inside it, else the bare file name."""
    try:
        return libfolder.relative(root, path)
    except LibraryError:
        return Path(path).name
