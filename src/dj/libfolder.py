"""The DJ's `dj-library/` folder: scaffold, `library.yaml`, exports, `log.md` (R-901..R-905).

Door 1 core: stdlib + PyYAML only (`dj.safety` is stdlib at import time).

Rules this module keeps:
- Create only. `scaffold` never overwrites a file; `import_export` copies the DJ's XML and
  never moves, renames or deletes it. "Never overwrites" holds under races too: a new file is
  written to a temp file and then linked into place, which fails if the name was taken.
  Only files the tool owns and rewrites (`library.yaml`, the state file) use os.replace.
- Add only. The one change to a file the DJ may have written: missing machine-path lines are
  appended to an existing `.gitignore` (its own lines are kept as they are).
- Library-relative paths. Every path written into the folder is POSIX and relative to it.
  Absolute paths live only in `exports/*.xml` and `proposals/*.xml`, which the scaffolded
  `.gitignore` keeps out of git (R-905), together with temp files (`*.tmp`).
- `library.yaml` is the one file that may name this computer (device, rekordbox version).
- A disk that refuses deletes and renames (Cowork's device VM, Q-27): a probe finds it before
  the first temp file, and files on it are then written in place, never through a temp file
  and never hard-linked. Other disks keep the temp-file route. See "-- writing --".
- One clock for log.md (Q-28): the date is the run's `--today` when given, else the local
  date; the time is always the local wall clock. See `log_clock`.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

import yaml

from dj.model import LibraryError
from dj.safety import REPO_ROOT, sha256

SCHEMA_VERSION = 1
DIRS = ("exports", "profile", "structure", "taste", "crates", "reports", "proposals", "wishlist")
FILES = ("README.md", "library.yaml", "links.yaml", "log.md", ".gitignore")
DEVICES = ("mac", "windows")
META_KEYS = (
    "schema_version",
    "device",
    "rekordbox_version",
    "created",
    "updated",
    "structure",
    "exports",
)
# Keys a library.yaml may hold but need not: files written before them stay valid (R-1406).
OPTIONAL_META_KEYS = ("dj_name",)
DJ_NAME_MAX = 40  # characters of the DJ's handle (what they call you in the booth)
ENV_VAR = "DJ_LIBRARY"
_DATED_EXPORT = re.compile(r"^(\d{4}-\d{2}-\d{2})-collection(?:-(\d+))?\.xml$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_CHUNK = 1 << 20


class LibraryFolderError(LibraryError):
    """The library folder or one of its files is not usable. Nothing was written.

    A dj.model.LibraryError (a ValueError), so callers can catch either."""


# -- the folder --------------------------------------------------------------------------


@dataclass(frozen=True)
class LibraryFolder:
    """Where everything lives inside one `dj-library/` folder."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    # folders (R-901)
    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def profile(self) -> Path:
        return self.root / "profile"

    @property
    def structure(self) -> Path:
        return self.root / "structure"

    @property
    def taste(self) -> Path:
        return self.root / "taste"

    @property
    def crates(self) -> Path:
        return self.root / "crates"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def proposals(self) -> Path:
        return self.root / "proposals"

    @property
    def wishlist(self) -> Path:
        return self.root / "wishlist"

    # files (R-901)
    @property
    def readme(self) -> Path:
        return self.root / "README.md"

    @property
    def library_yaml(self) -> Path:
        return self.root / "library.yaml"

    @property
    def links(self) -> Path:
        return self.root / "links.yaml"

    @property
    def log(self) -> Path:
        return self.root / "log.md"

    @property
    def gitignore(self) -> Path:
        return self.root / ".gitignore"

    # tool scratch state (gate previews, sessions); gitignored
    @property
    def cache(self) -> Path:
        return self.root / ".cache"

    def relative(self, path: str | Path) -> str:
        return relative(self.root, path)


@dataclass(frozen=True)
class ScaffoldResult:
    """Relative POSIX paths, in scaffold order: folders first, then files.

    `skipped` = it existed and was not created. `gitignore_added` = the lines appended to an
    existing `.gitignore` that lacked them (R-905); empty when nothing was added.
    """

    created: tuple[str, ...]
    skipped: tuple[str, ...]
    gitignore_added: tuple[str, ...] = ()


# -- scaffolded file contents --------------------------------------------------------------

README_TEXT = """\
# dj-library

Your library as plain text. The tool writes what it measured, Claude writes what it heard
from you, and you keep all of it. rekordbox stays the boss: nothing in here changes
rekordbox until you import a file yourself.

## Files at the top

- `README.md`: this page.
- `library.yaml`: the folder's settings. Mac or Windows, the rekordbox version of your last
  export, when the folder was made and last changed, the structure you picked, and your DJ
  name if you gave one. The tool keeps it current; you never need to edit it.
- `links.yaml`: your Spotify inbox playlists and the rekordbox crate each one feeds. Just a
  commented example until you set up Spotify.
- `log.md`: one line for every change the tool made: date, what, how many, which file. The
  tool writes it, not Claude.
- `.gitignore`: keeps the files that hold paths from this computer out of git.

## What goes in

- `exports/`: copies of the collection XML you export from rekordbox, named by date. Your
  original stays where you saved it. The tool reads the newest copy.

## What the tool found

- `profile/`: the numbers on your collection. Size, formats, bitrates, eras, empty tags,
  duplicates.
- `structure/`: how your playlist tree is built today (`current-tree.yaml`) and what that
  shape says about how you dig.
- `taste/`: your lanes, labels, artists, anchor tracks and the words you name playlists with.
  Every entry is dated. Old lines are never rewritten.

## What you get

- `reports/`: the HTML report on your library, one per run, named by date.
- `proposals/`: playlist trees and crates ready for rekordbox. A `.yaml` you can read and a
  `.xml` you import into rekordbox yourself.
- `crates/`: the brief for each crate and the tracks picked for it, one reason per track.
- `wishlist/`: tracks you don't own yet, with where to buy them.

## Git

The folder is ready for git: `git init`, `git add .`, `git commit`. The XML files in
`exports/` and `proposals/` hold the paths of your music on this computer, so they are
gitignored (`exports/*.xml`, `proposals/*.xml`), and so is any XML you drop at the top.
`.cache/` is the tool's scratch space, `.env` holds secrets and `*.tmp` is a temp file left
by a crash, or by a disk that does not let files be deleted: all gitignored too. Everything
else is text you can commit, diff and back up.

On a disk that does not let files be deleted (Claude's Cowork can mount your folder that way)
the tool writes each file in place instead of through a temp file, and says so in
`.cache/no-delete-disks.txt`. Your own computer checks its own disk and is not affected.
"""

LINKS_TEXT = """\
# Your Spotify inbox playlists, one entry each. Nothing here until you set up Spotify.
#   spotify: the playlist's name, URL or ID (a playlist you own or collaborate on)
#   crate:   the path of a normal playlist that already exists in rekordbox
# Example: remove the leading "# " on the two lines below and put in your own names.
# - spotify: my_house_inbox
#   crate: house_base/0_INBOX
"""

LOG_TEXT = "# Log\n\n"

# The four lines of contract section 2, then two more that keep machine paths out of git:
# an XML export dropped at the top of the folder, and a temp file a crash left mid-write
# (a half-copied export holds absolute paths too).
GITIGNORE_LINES = ("exports/*.xml", "proposals/*.xml", ".cache/", ".env")
GITIGNORE_EXTRA = ("/*.xml", "*.tmp")
GITIGNORE_TEXT = """\
# Files that hold paths from this computer. Never in git.
exports/*.xml
proposals/*.xml
# An XML export dropped at the top of the folder before it was copied into exports/.
/*.xml
# A half-written temp file, left behind if the computer stopped mid-write.
*.tmp
# The tool's scratch space, and secrets.
.cache/
.env
"""
GITIGNORE_MARKER = "# Added by dj-librarian: files that hold paths from this computer stay out of git."

_META_HEADER = (
    "# dj-library settings. dj-librarian keeps this file current; you never need to edit it.\n"
    "# The one file in this folder that may name this computer (device, rekordbox version).\n"
)


# -- scaffold (R-901) ----------------------------------------------------------------------


def scaffold(
    root: str | Path,
    *,
    device: str,
    rekordbox_version: str | None = None,
    today: date | None = None,
    dj_name: str | None = None,
) -> ScaffoldResult:
    """Create what is missing. An existing folder or file is never touched (SKIP).
    `dj_name` (the DJ's handle) goes into a new library.yaml when given."""
    if device not in DEVICES:
        raise LibraryFolderError(f"device must be one of {', '.join(DEVICES)}, got {device!r}")
    _check_version(rekordbox_version)
    dj_name = clean_dj_name(dj_name)
    folder = LibraryFolder(Path(root))
    today = today or date.today()

    if folder.root.exists() and not folder.root.is_dir():
        raise LibraryFolderError(f"{folder.root} is a file, not a folder. Nothing was created.")
    # Check everything first, so a blocked entry leaves the folder exactly as it was.
    for name in DIRS:
        if (folder.root / name).exists() and not (folder.root / name).is_dir():
            raise LibraryFolderError(f"{name} is a file; it must be a folder. Nothing was created.")
    for name in FILES:
        if (folder.root / name).exists() and not (folder.root / name).is_file():
            raise LibraryFolderError(f"{name} is a folder; it must be a file. Nothing was created.")

    folder.root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    skipped: list[str] = []
    for name in DIRS:
        path = folder.root / name
        try:
            path.mkdir()  # fails if the name exists: never a check-then-create race
        except FileExistsError:
            if not path.is_dir():
                raise LibraryFolderError(
                    f"{name} is a file; it must be a folder. Scaffold stopped."
                ) from None
            skipped.append(name)
        else:
            created.append(name)

    contents = {
        "README.md": README_TEXT,
        "library.yaml": _meta_text(new_meta(device, rekordbox_version, today, dj_name=dj_name)),
        "links.yaml": LINKS_TEXT,
        "log.md": LOG_TEXT,
        ".gitignore": GITIGNORE_TEXT,
    }
    added: tuple[str, ...] = ()
    for name in FILES:
        if write_new_text(folder.root / name, contents[name]):
            created.append(name)
            continue
        skipped.append(name)
        if name == ".gitignore":
            added = ensure_gitignore(folder.root)
    return ScaffoldResult(tuple(created), tuple(skipped), added)


def gitignore_missing(root: str | Path, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """The machine-path lines the folder's `.gitignore` lacks (all of them if there is none).
    `extra` = further lines a feature needs (W-25: `plans/*.plan.json`)."""
    path = LibraryFolder(Path(root)).gitignore
    have: set[str] = set()
    if path.is_file():
        have = {line.strip() for line in path.read_bytes().decode("utf-8", "replace").splitlines()}
    return tuple(line for line in GITIGNORE_LINES + GITIGNORE_EXTRA + extra if line not in have)


def ensure_gitignore(root: str | Path, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Append the missing machine-path lines (and `extra`) to an existing `.gitignore`;
    return them.

    Add only: the DJ's own lines stay exactly as they are. Lines go at the end, after a
    marker comment, so they win over an earlier `!` rule. No `.gitignore` -> nothing done
    (scaffold creates it).
    """
    path = LibraryFolder(Path(root)).gitignore
    if not path.is_file():
        return ()
    missing = gitignore_missing(root, extra)
    if not missing:
        return ()
    existing = path.read_bytes()
    lead = "\n" if existing and not existing.endswith(b"\n") else ""
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(lead + GITIGNORE_MARKER + "\n" + "".join(line + "\n" for line in missing))
    return missing


# -- library.yaml (R-902) ------------------------------------------------------------------


def new_meta(device: str, rekordbox_version: str | None, today: date, *, dj_name: str | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "device": device,
        "rekordbox_version": rekordbox_version,
        "created": today.isoformat(),
        "updated": today.isoformat(),
        "structure": {"chosen": None},
        "exports": {"latest": None},
    }
    if dj_name:
        meta["dj_name"] = dj_name
    return meta


def clean_dj_name(value: Any) -> str | None:
    """The DJ's handle on one line (spaces collapsed); None for nothing or blank. Control
    characters, a line break or more than DJ_NAME_MAX characters -> LibraryFolderError."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise LibraryFolderError(f"dj_name: expected text, got {value!r}")
    if any(ch in "\r\n" or (not ch.isprintable() and not ch.isspace()) for ch in value):
        raise LibraryFolderError("dj_name: one line of plain text, please")
    text = " ".join(value.split())
    if len(text) > DJ_NAME_MAX:
        raise LibraryFolderError(f"dj_name: at most {DJ_NAME_MAX} characters, got {len(text)}")
    return text or None


def load_meta(root: str | Path) -> dict[str, Any]:
    """library.yaml as a dict, dates as ISO strings. Not validated: see validate_meta."""
    path = LibraryFolder(Path(root)).library_yaml
    if not path.is_file():
        raise LibraryFolderError("library.yaml not found. Scaffold the library folder first.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LibraryFolderError(f"library.yaml is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise LibraryFolderError("library.yaml: expected a mapping of settings")
    return _iso_dates(data)


def validate_meta(data: Any) -> list[str]:
    """Every problem with a library.yaml mapping, one line each. Empty list = valid."""
    if not isinstance(data, dict):
        return ["library.yaml: expected a mapping of settings"]
    errors = [f"missing key: {key}" for key in META_KEYS if key not in data]
    known = set(META_KEYS) | set(OPTIONAL_META_KEYS)
    errors += [f"unknown key: {key}" for key in sorted(map(str, set(data) - known))]
    if "dj_name" in data and data["dj_name"] is not None:
        try:
            if clean_dj_name(data["dj_name"]) is None:
                errors.append("dj_name: expected a name or null, got an empty text")
        except LibraryFolderError as exc:
            errors.append(str(exc))

    if "schema_version" in data:
        version = data["schema_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            errors.append(f"schema_version: expected a whole number, got {version!r}")
        elif version != SCHEMA_VERSION:
            errors.append(
                f"schema_version: this tool reads {SCHEMA_VERSION}, the file says {version}"
            )
    if "device" in data and data["device"] not in DEVICES:
        errors.append(f"device: expected one of {', '.join(DEVICES)}, got {data['device']!r}")
    if "rekordbox_version" in data:
        value = data["rekordbox_version"]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"rekordbox_version: expected text or null, got {value!r}")
    for key in ("created", "updated"):
        if key in data and not _is_iso_date(data[key]):
            errors.append(f"{key}: expected a date YYYY-MM-DD, got {data[key]!r}")
    if "structure" in data:
        errors += _check_section(data["structure"], "structure", "chosen", _check_chosen)
    if "exports" in data:
        errors += _check_section(data["exports"], "exports", "latest", _check_latest)
    return errors


def update_meta(root: str | Path, today: date | None = None, **changes: Any) -> dict[str, Any]:
    """Apply `changes` to library.yaml, stamp `updated`, validate, write atomically.

    A mapping value (`structure`, `exports`) is merged into the existing mapping.
    Invalid result -> LibraryFolderError and the file is left as it was.
    """
    unknown = sorted(set(changes) - set(META_KEYS) - set(OPTIONAL_META_KEYS))
    if unknown:
        raise LibraryFolderError(f"library.yaml has no key(s): {', '.join(unknown)}")
    folder = LibraryFolder(Path(root))
    meta = load_meta(folder.root)
    for key, value in changes.items():
        if isinstance(value, Mapping) and isinstance(meta.get(key), dict):
            meta[key] = {**meta[key], **value}
        else:
            meta[key] = value
    meta["updated"] = (today or date.today()).isoformat()
    meta = _iso_dates(meta)
    errors = validate_meta(meta)
    if errors:
        raise LibraryFolderError("library.yaml not updated: " + "; ".join(errors))
    write_text(folder.library_yaml, _meta_text(meta))
    return meta


def _meta_text(meta: Mapping[str, Any]) -> str:
    ordered = {key: meta[key] for key in META_KEYS + OPTIONAL_META_KEYS if key in meta}
    body = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return _META_HEADER + body


def _iso_dates(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    for key in ("created", "updated"):
        value = out.get(key)
        if isinstance(value, date) and not isinstance(value, datetime):
            out[key] = value.isoformat()
    return out


def _is_iso_date(value: Any) -> bool:
    if isinstance(value, datetime):
        return False
    if isinstance(value, date):
        return True
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _check_section(value: Any, section: str, key: str, check: Any) -> list[str]:
    if not isinstance(value, dict):
        return [f"{section}: expected a mapping with `{key}`, got {value!r}"]
    errors = [f"{section}: unknown key: {k}" for k in sorted(map(str, set(value) - {key}))]
    if key not in value:
        errors.append(f"{section}: missing key: {key}")
    else:
        errors += check(value[key])
    return errors


def _check_chosen(value: Any) -> list[str]:
    if value is None or (isinstance(value, str) and value.strip()):
        return []
    return [f"structure.chosen: expected a structure name or null, got {value!r}"]


def _check_latest(value: Any) -> list[str]:
    if value is None or _is_export_path(value):
        return []
    return [f"exports.latest: expected exports/<name>.xml or null, got {value!r}"]


def _is_export_name(name: str) -> bool:
    """A file name the tool treats as an export: `<name>.xml`, not hidden, plain characters.

    Lower-case `.xml` only, so the `.gitignore` line `exports/*.xml` matches it on every OS.
    Hidden names (temp files, macOS `._` files) are never exports.
    """
    return (
        len(name) > len(".xml")
        and name.endswith(".xml")
        and not name.startswith(".")
        and name == name.strip()
        and not any(ch in name for ch in '/\\:\0')
    )


def _is_export_path(value: Any) -> bool:
    """`exports/<name>.xml`, POSIX and relative to the folder, directly inside exports/."""
    if not isinstance(value, str):
        return False
    head, sep, name = value.partition("/")
    return head == "exports" and sep == "/" and _is_export_name(name)


def _check_version(value: Any) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise LibraryFolderError(f"rekordbox_version must be text or None, got {value!r}")


# -- exports -------------------------------------------------------------------------------


def import_export(root: str | Path, xml_path: str | Path, *, today: date | None = None) -> Path:
    """Copy the DJ's collection XML into exports/ and record it in library.yaml.

    Copies, never moves: the source file is only read. Target name
    `exports/<YYYY-MM-DD>-collection.xml`, then `-2`, `-3` ... when taken. A file with the
    same content already in exports/ -> SKIP: nothing copied, that file becomes the latest.
    The whole XML is parsed first, so a truncated or broken export is refused; the copy is
    checked to be byte for byte what was parsed.
    """
    folder = LibraryFolder(Path(root))
    source = Path(xml_path)
    if not source.is_file():
        raise LibraryFolderError(f"{source.name}: file not found. Export the collection XML first.")
    meta = load_meta(folder.root)  # the folder must be scaffolded
    errors = validate_meta(meta)
    if errors:
        raise LibraryFolderError("library.yaml: " + "; ".join(errors) + ". Nothing was copied.")
    product, version, digest, size = _scan_export(source)
    folder.exports.mkdir(exist_ok=True)

    target = _identical_export(folder, size, digest)
    if target is None:
        target = _copy_new(source, digest, folder, today or date.today())

    changes: dict[str, Any] = {}
    latest = relative(folder.root, target)
    exports = meta.get("exports")
    if not isinstance(exports, dict) or exports.get("latest") != latest:
        changes["exports"] = {"latest": latest}
    is_rekordbox = product is None or product.strip().casefold() == "rekordbox"
    if version and is_rekordbox and meta.get("rekordbox_version") != version:
        changes["rekordbox_version"] = version
    if changes:
        update_meta(folder.root, today=today, **changes)
    return target


def read_product(xml_path: str | Path) -> tuple[str | None, str | None]:
    """(PRODUCT Name, PRODUCT Version) of a rekordbox XML.

    Reads the whole file: a truncated or broken XML -> LibraryFolderError.
    """
    product, version, _digest, _size = _scan_export(Path(xml_path))
    return product, version


def _scan_export(path: Path) -> tuple[str | None, str | None, str, int]:
    """Parse the whole XML once, streaming: (PRODUCT Name, PRODUCT Version, sha256, size).

    Digest and size are of exactly the bytes parsed, so a copy is checked against what was
    read, not against a file that may have changed since.
    Elements are cleared as they end, so a large collection does not fill memory.
    """
    parser = ET.XMLPullParser(events=("start", "end"))
    digest = hashlib.sha256()
    size = 0
    state: dict[str, Any] = {"depth": 0, "root": None, "first": None, "product": (None, None)}

    def handle(events: Iterator[tuple[str, ET.Element]]) -> None:
        for event, elem in events:
            if event == "end":
                state["depth"] -= 1
                if state["depth"] == 1:
                    state["root"].clear()  # a top-level section is done
                elif state["depth"] > 1:
                    elem.clear()
                continue
            state["depth"] += 1
            if state["root"] is None:
                if elem.tag != "DJ_PLAYLISTS":
                    raise LibraryFolderError(f"{path.name} is not a rekordbox XML export.")
                state["root"] = elem
            elif state["depth"] == 2 and state["first"] is None:
                state["first"] = elem.tag  # PRODUCT comes first; another section means none
                if elem.tag == "PRODUCT":
                    version = (elem.get("Version") or "").strip() or None
                    state["product"] = (elem.get("Name"), version)

    try:
        with open(path, "rb") as fh:
            while chunk := fh.read(_CHUNK):
                digest.update(chunk)
                size += len(chunk)
                parser.feed(chunk)
                handle(parser.read_events())
        parser.close()
        handle(parser.read_events())
    except ET.ParseError as exc:
        raise LibraryFolderError(
            f"{path.name} is not readable XML ({exc}). Nothing was copied. If rekordbox was "
            "still exporting, wait for it to finish and try again."
        ) from exc
    if state["root"] is None:
        raise LibraryFolderError(f"{path.name} is not a rekordbox XML export.")
    name, version = state["product"]
    return name, version, digest.hexdigest(), size


def latest_export(root: str | Path) -> Path:
    """The export to read: `exports.latest` from library.yaml, else the newest exports/*.xml.

    A stored value that is not `exports/<name>.xml`, or names a file that is gone, is ignored.
    """
    folder = LibraryFolder(Path(root))
    try:
        exports = load_meta(folder.root).get("exports")
    except LibraryFolderError:
        exports = None
    latest = exports.get("latest") if isinstance(exports, dict) else None
    if _is_export_path(latest):
        path = folder.root / latest
        if path.is_file():
            return path
    found = _export_files(folder)
    if not found:
        raise LibraryFolderError("No export in exports/ yet. Import the collection XML first.")
    return found[-1]


def _export_files(folder: LibraryFolder) -> list[Path]:
    """The exports in exports/, oldest first. Hidden and temp files are not exports."""
    if not folder.exports.is_dir():
        return []
    files = (p for p in folder.exports.iterdir() if _is_export_name(p.name) and p.is_file())
    return sorted(files, key=_export_order)


def _export_order(path: Path) -> tuple:
    match = _DATED_EXPORT.match(path.name)
    if match:
        return (1, match.group(1), int(match.group(2) or 1), path.name)
    return (0, "", 0, path.name)


def _identical_export(folder: LibraryFolder, size: int, digest: str) -> Path | None:
    for existing in _export_files(folder):
        if existing.stat().st_size == size and sha256(existing) == digest:
            return existing
    return None


def _export_names(folder: LibraryFolder, day: date) -> Iterator[Path]:
    stem = day.isoformat() + "-collection"
    yield folder.exports / f"{stem}.xml"
    n = 2
    while True:
        yield folder.exports / f"{stem}-{n}.xml"
        n += 1


def _copy_new(source: Path, digest: str, folder: LibraryFolder, day: date) -> Path:
    """Copy `source` to the first free dated name in exports/. Source only read.

    Copied to a temp file, checked against `digest` (the bytes that were parsed), then linked
    into place: a name another import took in the meantime is never overwritten. The copy keeps
    the source's file time, so exports/ dates each export by when rekordbox wrote it, not by when
    it was imported (dj-build compares those times, Q-17). On a disk that refuses deletes (Q-27)
    the bytes are read and checked first, then written straight to the first free name with an
    exclusive create: no temp file, nothing to remove.
    """
    if _writes_direct(folder.exports):
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise LibraryFolderError(
                f"{source.name} changed while it was being copied. Nothing was copied. "
                "Wait for rekordbox to finish the export and try again."
            )
        stamp = source.stat()
        for candidate in _export_names(folder, day):  # ends: some -N is always free
            if _create_direct(candidate, data):
                with contextlib.suppress(OSError):  # keep the export's own time (Q-17)
                    os.utime(candidate, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                return candidate
    fd, tmp = _temp_next_to(folder.exports / "collection.xml")
    try:
        with os.fdopen(fd, "wb") as out, open(source, "rb") as src:
            shutil.copyfileobj(src, out, _CHUNK)
            written = os.fstat(src.fileno())
        if sha256(tmp) != digest:
            raise LibraryFolderError(
                f"{source.name} changed while it was being copied. Nothing was copied. "
                "Wait for rekordbox to finish the export and try again."
            )
        with contextlib.suppress(OSError):  # a disk that keeps no times: the copy's own time
            os.utime(tmp, ns=(written.st_atime_ns, written.st_mtime_ns))
        for candidate in _export_names(folder, day):  # ends: some -N is always free
            if _place_new(tmp, candidate):
                return candidate
    finally:
        _discard(tmp)  # our own temp file, never the DJ's
    raise AssertionError("unreachable")  # pragma: no cover


# -- log.md (R-904) ------------------------------------------------------------------------


def _wall_clock() -> datetime:
    """The local wall clock. One function, so a test can pin it (Q-28)."""
    return datetime.now()


def log_clock(today: date | None = None, now: datetime | None = None) -> str:
    """`YYYY-MM-DD HH:MM`, the start of every log.md line: one clock for all of them (Q-28).

    The date is `today` (a run's `--today`) when given, else the local date. The time is always
    the local wall clock: `now` when given (an aware moment is shown in local time, so a UTC
    gate time reads as the DJ's clock), else the clock itself. Never a made-up 00:00."""
    moment = now if now is not None else _wall_clock()
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    day = today or moment.date()
    return f"{day.isoformat()} {moment.strftime('%H:%M')}"


def append_log(
    root: str | Path,
    action: str,
    counts: Mapping[str, int] | None = None,
    file: str | Path | None = None,
    now: datetime | None = None,
    *,
    today: date | None = None,
) -> str:
    """Append `YYYY-MM-DD HH:MM <action> -> <n> <key>, <n> <key>; <file>` and return it.

    ` -> ...` is left out without counts, `; <file>` without a file. The file is written
    relative to the folder. log.md is created with its title line when missing. The time stamp
    is `log_clock(today, now)`: pass the run's `--today` as `today`.
    """
    folder = LibraryFolder(Path(root))
    if not folder.root.is_dir():
        raise LibraryFolderError("The library folder does not exist. Scaffold it first.")
    line = f"{log_clock(today, now)} {_one_line(action, 'action')}"
    if counts:
        parts = []
        for key, n in counts.items():
            if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                raise LibraryFolderError(f"log count {key!r} must be a whole number, got {n!r}")
            parts.append(f"{n} {_one_line(str(key), 'count name')}")
        line += " -> " + ", ".join(parts)
    if file is not None:
        line += "; " + _log_path(folder.root, file)

    log = folder.log
    try:  # a missing log.md is created with its title; "x" fails if it appeared meanwhile
        with open(log, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(LOG_TEXT + line + "\n")
        return line
    except FileExistsError:
        pass
    existing = log.read_bytes()
    with open(log, "a", encoding="utf-8", newline="\n") as fh:
        if existing and not existing.endswith(b"\n"):
            fh.write("\n")
        fh.write(line + "\n")
    return line


def _one_line(text: Any, what: str) -> str:
    if not isinstance(text, str) or not text.strip() or "\n" in text or "\r" in text:
        raise LibraryFolderError(f"log {what} must be one line of text, got {text!r}")
    return text.strip()


def _log_path(root: Path, file: str | Path) -> str:
    text = str(file)
    if "\n" in text or "\r" in text or not text.strip():
        raise LibraryFolderError(f"log file must be one path, got {text!r}")
    path = Path(text.replace("\\", "/")) if isinstance(file, str) else Path(file)
    if _DRIVE.match(text) and not path.is_absolute():  # a Windows path, read on Mac or Linux
        raise LibraryFolderError(f"{text} is outside the library folder")
    return relative(root, path)


# -- where the folder is -------------------------------------------------------------------


def _state_file() -> Path:
    return REPO_ROOT / "state" / "library-path.txt"


def configured_root() -> Path:
    """DJ_LIBRARY env var, else the path stored by remember_root, else REPO_ROOT/dj-library.

    Always absolute (resolved). MCP path checks treat it as a boundary, so a drive root, the
    home folder or a folder above it is refused (LibraryFolderError) rather than returned.
    """
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        return _library_root(env, f"{ENV_VAR}")
    stored = _state_file()
    if stored.is_file():
        text = stored.read_text(encoding="utf-8").strip()
        if text:
            return _library_root(text, "state/library-path.txt")
    return _library_root(REPO_ROOT / "dj-library", "the default library folder")


def remember_root(path: str | Path) -> Path:
    """Store the folder's absolute path in REPO_ROOT/state/library-path.txt (gitignored).

    A drive root, the home folder or a folder above it is refused: nothing is stored.
    """
    resolved = _library_root(path, "the library folder")
    state = _state_file()
    state.parent.mkdir(parents=True, exist_ok=True)
    write_text(state, str(resolved) + "\n")
    return resolved


def _library_root(path: str | Path, where: str) -> Path:
    """`path` expanded and resolved; refused if it is too wide to be one library folder."""
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError) as exc:  # RuntimeError: `~` with no home folder known
        raise LibraryFolderError(f"{where}: cannot use {path}: {exc}") from exc
    too_wide = resolved.parent == resolved or _volume_root(resolved)  # a filesystem, drive or volume root
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    if home is not None and home.is_relative_to(resolved):
        too_wide = True  # the home folder, or a folder that holds it
    if too_wide:
        raise LibraryFolderError(
            f"{where}: {resolved} is a whole drive or home folder, not a library folder. "
            "Point it at the dj-library folder itself."
        )
    return resolved


# Where macOS and Linux desktops mount a whole drive, and how deep the drive's own folder sits:
# /Volumes/<drive>, /media/<drive> or /media/<user>/<drive>, /run/media/<user>/<drive>. Not /mnt:
# a sandbox may mount the connected folder itself there (and WSL is not supported anyway).
_VOLUME_MOUNTS = ((("/", "Volumes"), 3), (("/", "media"), 4), (("/", "run", "media"), 5))


def _volume_root(path: str | Path) -> bool:
    """True for a mounted drive's own folder, or a folder above it (a DJ's external music drive
    on a Mac is /Volumes/<drive>). By path, not os.path.ismount: Cowork mounts the folder the DJ
    connected, the dj-library folder itself, and that one must stay usable."""
    parts = PurePosixPath(Path(path).as_posix()).parts
    return any(parts[: len(base)] == base and len(parts) <= depth for base, depth in _VOLUME_MOUNTS)


def relative(root: str | Path, path: str | Path) -> str:
    """`path` as a POSIX path relative to `root`. A relative `path` is taken from `root`."""
    base = Path(root).resolve()
    target = Path(path)
    if not target.is_absolute():
        target = base / target
    target = target.resolve()
    try:
        rel = target.relative_to(base)
    except ValueError:
        raise LibraryFolderError(f"{path} is outside the library folder") from None
    return rel.as_posix()


# -- writing -------------------------------------------------------------------------------
#
# Every file the tool writes goes through write_text (replace) or write_new_text (create only).
# On a normal disk: a temp file `.<name>.<random>.tmp` next to the target, then os.replace or a
# hard link, so a crash never leaves half a file under the real name.
#
# Some disks refuse deletes and renames but let a program create and write files: Cowork's
# device VM mounts the connected folder that way (Q-27). There a temp file can never be removed
# by anyone, and os.replace fails. So (decided in W-30, revised in its review):
# - The probe. The first time a run is about to make a temp file on a disk (a device number),
#   it makes an empty `.dj-probe.<random>.tmp` there and removes it. Removed: the disk deletes,
#   and every write on it keeps the temp-file route for the rest of the run. Refused (after a
#   few tries on Windows, where a scanner can hold a new file for a moment): the disk does not
#   delete, and every write on it for the rest of the run goes straight to the target, in every
#   folder, with no temp file. The probe comes before any temp file, so on such a disk no temp
#   file is ever made, and none is ever hard-linked to a real file.
# - Straight to the target means `open(path, "w")`; create-only writers use `open(path, "x")`,
#   so they still never overwrite. Nothing is removed, nothing is hard-linked.
# - On a disk the probe passed, os.replace, os.link or a temp's removal can still raise OSError
#   (a file held open, a scanner): that write goes in place, nothing else is removed, and a
#   refused removal sends the rest of the run's writes on that disk in place. That is never
#   remembered after the run. (A removal refused right after a create-only hard link leaves that
#   one temp linked to its file: possible only on a disk that deletes, never on a no-delete one.)
# - Later runs. A refused probe is written down in the library folder's
#   `.cache/no-delete-disks.txt` (gitignored) as `<platform> <device number> <date>`. A later run
#   on the same platform and device writes in place from the start: no probe, no new file. Any
#   other computer reading the same folder (the DJ's own Mac or PC) does not match, checks its
#   own disk and keeps the temp-file route. An undo record (`fsync=True`) never trusts the note:
#   it goes in place only after a delete or its own rename was refused in this run.
# - A temp file of ours from an earlier run (a crash) means nothing here: it never switches a
#   folder to in-place writes, and it is never removed (hard rule 1).
# - The cost on such a disk: the one empty probe file nothing can remove, per library folder and
#   device (once per session if the VM's device number changes between sessions), and the note;
#   plus one more empty probe per run that writes an undo record, since that never trusts the note.
# Audio files are not written here: `dj tidy` keeps its temp copy + os.replace (CLAUDE.md) and
# fails loudly on such a disk rather than write an audio file in place.

NO_DELETE_NOTE = "no-delete-disks.txt"  # in the library folder's .cache/ (Q-27)
_NOTE_HEADER = (
    "# dj-librarian: disks where this folder could not delete a file (Q-27, e.g. Cowork's device VM).\n"
    "# On a computer that matches a line (same platform, same device number) the tool writes the\n"
    "# files here in place, without a temp file, so a crash mid-write can leave half a file.\n"
    "# Other computers check their own disk and keep the safe route. Line: platform device date.\n"
)
_PROBE_PREFIX = ".dj-probe."
_PROBE_TRIES = 3 if os.name == "nt" else 1  # POSIX: a refused unlink is final
_PROBE_PAUSE = 0.05  # seconds between tries

# What this run knows about each disk (device number). Never carried to the next run.
_REFUSED: set[int] = set()  # a delete was refused here in this run: write in place
_PROBE_REFUSED: set[int] = set()  # ...by the probe itself: worth writing down in the note
_DELETES: set[int] = set()  # the probe was removed in this run: the temp-file route
_TRUSTED: set[int] = set()  # a library's note names this disk (from an earlier run)
_NOTES: dict[str, frozenset[str]] = {}  # library folder -> the disks its note names, read once
_WRITTEN_DOWN: set[tuple[str, int]] = set()  # (library folder, disk) already in its note


def write_text(path: str | Path, text: str, *, fsync: bool = False) -> Path:
    """UTF-8, LF line ends. Written to a temp file next to `path`, then os.replace; on a disk
    that refuses that, written in place (Q-27, see above). `fsync=True` flushes the bytes to
    disk before the file takes its name (an undo record).

    Replaces an existing file: only for files the tool owns and rewrites (library.yaml, the
    state file, its own tree files). A file that must never be overwritten: write_new_text.
    """
    path = Path(path)
    if _writes_direct(path.parent, fsync=fsync):
        _write_direct(path, text, fsync=fsync)
        return path
    fd, tmp = _temp_next_to(path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            if fsync:
                fh.flush()
                os.fsync(fh.fileno())
        try:
            os.replace(tmp, path)
        except OSError:  # a disk that refuses renames (Q-27): write the target in place
            _write_direct(path, text, fsync=fsync)
    finally:
        _discard(tmp)
    return path


def write_new_text(path: str | Path, text: str) -> bool:
    """Create `path` with `text` (UTF-8, LF) only if no file has that name. False = it existed.

    The existence check and the creation are one step (see _place_new), so a file that
    appears in the meantime is kept, never overwritten. On a disk that refuses deletes (Q-27)
    the file is created in place with an exclusive create: still never an overwrite.
    """
    path = Path(path)
    if _writes_direct(path.parent):
        return _create_direct(path, text.encode("utf-8"))
    fd, tmp = _temp_next_to(path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return _place_new(tmp, path)
    finally:
        _discard(tmp)


MAX_NUMBERED = 10_000  # `<base>-N<suffix>` tries before giving up


def write_new_numbered(folder: str | Path, base: str, suffix: str, text: str) -> Path:
    """Write `text` to `<folder>/<base><suffix>`, or to the first free `<base>-N<suffix>` (N = 2,
    3, ...). Returns the path. Create-only: a report from an earlier run is never replaced."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(1, MAX_NUMBERED + 1):
        path = folder / (f"{base}{suffix}" if n == 1 else f"{base}-{n}{suffix}")
        if write_new_text(path, text):
            return path
    raise LibraryFolderError(f"{base}{suffix}: {MAX_NUMBERED} numbered names are taken. Nothing was written.")


def _temp_next_to(target: Path) -> tuple[int, Path]:
    """A hidden temp file in the target's folder: `.<name>.<random>.tmp` (gitignored: *.tmp)."""
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    return fd, Path(name)


def _place_new(tmp: Path, target: Path) -> bool:
    """Give our finished temp file the name `target`, only if that name is free.

    A hard link fails when the name exists, so check and create are one step. A disk that
    cannot hard-link (FAT, exFAT, some network shares) gets the name reserved with O_EXCL
    first; the temp file then replaces our own empty reservation, never someone else's file.
    A disk that refuses that rename too (Q-27): the temp's bytes are written into our own
    reservation in place.
    """
    try:
        os.link(tmp, target)
        return True
    except FileExistsError:
        return False
    except OSError:
        pass
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        return False
    os.close(fd)
    try:
        os.replace(tmp, target)
    except OSError:  # Q-27: the reservation is ours; fill it in place, remove nothing
        return _fill_reservation(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            if target.stat().st_size == 0:  # still our own empty reservation
                target.unlink()
        raise
    return True


def _fill_reservation(tmp: Path, target: Path) -> bool:
    """Copy our temp file's bytes into `target`, the empty file we just created with O_EXCL.
    False when it is no longer empty (someone else wrote it meanwhile): theirs is kept."""
    with open(target, "r+b") as out:
        if os.fstat(out.fileno()).st_size:
            return False
        with open(tmp, "rb") as src:
            shutil.copyfileobj(src, out, _CHUNK)
    return True


def _discard(tmp: Path) -> None:
    """Remove our own temp file if it is still there. A refusal (on a disk the probe passed: a
    file held open, a scanner) sends the rest of this run's writes on that disk in place, so no
    more temp files pile up. Not written down: the next run probes again (Q-27)."""
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        dev = _device(tmp.parent)
        if dev is not None:
            _REFUSED.add(dev)


def _write_direct(path: Path, text: str, *, fsync: bool = False) -> None:
    """Write `text` into `path` in place (UTF-8, LF): the fallback for a disk that refuses
    renames and deletes (Q-27). No temp file, no link, nothing removed."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        if fsync:
            fh.flush()
            os.fsync(fh.fileno())


def _create_direct(path: Path, data: bytes) -> bool:
    """Create `path` with `data` only if no file has that name (exclusive create, "x"): the
    create-only fallback (Q-27). False = it existed and is kept."""
    try:
        with open(path, "xb") as fh:
            fh.write(data)
    except FileExistsError:
        return False
    return True


def _key(directory: Path) -> str:
    try:
        return str(directory.resolve())
    except OSError:
        return str(directory.absolute())


def _device(directory: Path) -> int | None:
    """The device number of the disk `directory` is on; None when it cannot be read."""
    try:
        return os.stat(directory).st_dev
    except OSError:
        return None


def _disk_id(dev: int) -> str:
    """`<platform> <device number>`: a disk as one computer sees it (the note's key, Q-27)."""
    return f"{sys.platform} {dev}"


def _owning_library(directory: Path) -> Path | None:
    """The library folder (the one holding library.yaml) `directory` is in, at most three levels
    up; None outside a library folder."""
    directory = directory.absolute()
    for folder in (directory, *list(directory.parents)[:3]):
        if (folder / "library.yaml").is_file():
            return folder
    return None


def _note_disks(text: str) -> frozenset[str]:
    """The `<platform> <device>` keys of a note's lines (comments and blank lines skipped)."""
    keys = set()
    for line in text.splitlines():
        words = line.split()
        if len(words) >= 2 and not words[0].startswith("#"):
            keys.add(f"{words[0]} {words[1]}")
    return frozenset(keys)


def _read_note(root: Path) -> frozenset[str]:
    key = _key(root)
    if key not in _NOTES:
        try:
            text = (root / ".cache" / NO_DELETE_NOTE).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        _NOTES[key] = _note_disks(text)
    return _NOTES[key]


def _noted(directory: Path, dev: int) -> bool:
    """True when the note of `directory`'s library folder names this disk on this platform."""
    if dev in _TRUSTED:
        return True
    root = _owning_library(directory)
    if root is None or _disk_id(dev) not in _read_note(root):
        return False
    _TRUSTED.add(dev)
    return True


def _write_down(directory: Path, dev: int) -> None:
    """Add this disk to the note of `directory`'s library folder, once (a refused probe, Q-27).
    Appended, never rewritten; nothing outside a library folder. Best effort: a note that cannot
    be written only costs the next run one more probe."""
    root = _owning_library(directory)
    if root is None or (_key(root), dev) in _WRITTEN_DOWN:
        return
    _WRITTEN_DOWN.add((_key(root), dev))
    note = root / ".cache" / NO_DELETE_NOTE
    with contextlib.suppress(OSError, UnicodeDecodeError):
        known = note.read_text(encoding="utf-8") if note.is_file() else ""
        if _disk_id(dev) in _note_disks(known):
            return
        note.parent.mkdir(exist_ok=True)
        lead = _NOTE_HEADER if not known else ("" if known.endswith("\n") else "\n")
        with open(note, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{lead}{_disk_id(dev)} {date.today().isoformat()}\n")
        _NOTES.pop(_key(root), None)


def _probe_deletes(directory: Path) -> bool | None:
    """Make an empty `.dj-probe.<random>.tmp` in `directory` and remove it (Q-27). True = removed,
    False = the disk refused (the file stays: nothing can remove it), None = nothing could be
    made here (the write itself then says why)."""
    try:
        fd, name = tempfile.mkstemp(dir=directory, prefix=_PROBE_PREFIX, suffix=".tmp")
    except OSError:
        return None
    os.close(fd)
    for attempt in range(_PROBE_TRIES):
        if attempt:
            time.sleep(_PROBE_PAUSE)
        try:
            os.unlink(name)
        except FileNotFoundError:
            return True
        except OSError:
            continue
        return True
    return False


def _writes_direct(directory: Path, *, fsync: bool = False) -> bool:
    """Write in place, with no temp file, in `directory` (Q-27): its disk refused a delete in
    this run, or the library folder's note names this disk (not for an `fsync` undo record,
    which needs a refusal seen in this run). Otherwise the probe decides, once a run a disk."""
    dev = _device(directory)
    if dev is None:
        return False  # no such folder: the temp-file route raises the plain error
    if dev in _REFUSED:
        if dev in _PROBE_REFUSED:
            _write_down(directory, dev)  # a library folder made after the probe refused
        return True
    if dev in _DELETES:
        return False
    if not fsync and _noted(directory, dev):
        return True
    deletes = _probe_deletes(directory)
    if deletes is None:
        return False
    if deletes:
        _DELETES.add(dev)
        return False
    _REFUSED.add(dev)
    _PROBE_REFUSED.add(dev)
    _write_down(directory, dev)
    return True
