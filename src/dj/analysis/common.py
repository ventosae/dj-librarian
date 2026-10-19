"""Helpers the analysis modules share (contract section 4). Door 1: stdlib + PyYAML only.

- `norm_key(artist, title)`: the duplicate-candidate key, without rapidfuzz.
- `dup_key(artist, title, remixer)`: `norm_key` plus the Remixer field when the title does not
  name the remix already, so a remix kept only in that field is not its original's duplicate.
- `provenance_line(module, source_rel, today)`: the line under the title of every generated MD
  file, so the file says its numbers were measured by code (R-302).
- `md_table(headers, rows, limit=5)`: a Markdown table of at most 5 rows (R-1002 rule 9), with
  "And N more" when rows were cut. The full data goes into the JSON sidecar.
- `write_json(path, data)`: a JSON sidecar. Sorted keys, indent 2, LF, written atomically.
- `pct(n, d)`: a whole-number percentage, rounded half up.
- `parse_day(text)`: a `--today YYYY-MM-DD` argument.
- `library_folder(root)`: the folder an analysis may write into, resolved and checked: a
  scaffolded dj-library (valid library.yaml), never a drive root or the home folder.
- `resolve_xml(root, xml)`: a `--xml` argument as the one file that is read and named.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

from dj import libfolder
from dj.libfolder import LibraryFolder, LibraryFolderError, write_text

LIST_LIMIT = 5  # R-1002 rule 9: no DJ-facing list longer than this

# Letters NFKD leaves alone because they are letters of their own, not accented ones.
_SPELLED = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ð": "d", "þ": "th"})
# "(Original Mix)", "[Original Version]", "(Original)": the same recording as the bare title.
_ORIGINAL_BRACKETED = re.compile(r"[(\[]\s*original(?:\s+(?:mix|version))?\s*[)\]]")
# "Title - Original Mix", the store spelling of the same thing.
_ORIGINAL_DASHED = re.compile(r"\s-\s*original(?:\s+(?:mix|version))?\s*$")
_FEATURING = re.compile(r"\b(?:featuring|feat|ft)\b")
_NOT_WORD = re.compile(r"[\W_]+")
_DRIVE = re.compile(r"^[A-Za-z]:")


def fold(text: str) -> str:
    """NFKD, accents stripped, casefolded; ø, æ, œ, ł, đ, ð, þ spelled with plain letters."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return plain.casefold().translate(_SPELLED)


def _clean(text: str) -> str:
    text = fold(text).replace("&", " and ")
    text = _ORIGINAL_BRACKETED.sub(" ", text)
    text = _ORIGINAL_DASHED.sub(" ", text)
    text = _FEATURING.sub(" feat ", text)
    return " ".join(_NOT_WORD.sub(" ", text).split())


def norm_key(artist: str, title: str) -> str:
    """The key two tracks share when they are duplicate candidates: `"artist|title"`.

    Accents stripped and case folded, `&` read as `and`, `feat.`/`ft.`/`featuring` as one word,
    a bracketed `(Original Mix)` / `(Original Version)` / `(Original)` or a trailing
    `- Original Mix` dropped, punctuation and runs of spaces collapsed to one space. Version
    words (remix, edit, extended, dub, ...) stay in the key, so a remix is never a duplicate of
    its original. Empty artist or title after cleaning -> "" (not a candidate for anything).
    """
    a, t = _clean(artist), _clean(title)
    return f"{a}|{t}" if a and t else ""


# A Remixer field that only says "Original (Mix|Version)" names no remix.
_ORIGINAL_ONLY = re.compile(r"^original(?: (?:mix|version))?$")


def dup_key(artist: str, title: str, remixer: str = "") -> str:
    """The duplicate-group key: `norm_key(artist, title)`, then `|<remixer>` when the Remixer
    field names someone the title does not already name.

    "Brass Tide" with Remixer "Dub Atelier" is a remix, not a copy of plain "Brass Tide".
    "Brass Tide (Dub Atelier Remix)" keeps the same key with or without that Remixer field,
    so two copies of one remix still group. Empty key -> "" (not a candidate)."""
    key = norm_key(artist, title)
    mix = _clean(remixer)
    if not key or not mix or _ORIGINAL_ONLY.match(mix):
        return key
    named = key.split("|", 1)[1]  # `_clean` leaves no "|" inside a part
    return key if f" {mix} " in f" {named} " else f"{key}|{mix}"


def _relative_posix(path: str) -> bool:
    if not path or path != path.strip() or "\n" in path or "\r" in path:
        return False
    if "\\" in path or path.startswith("/") or _DRIVE.match(path) or "://" in path:
        return False
    return ".." not in path.split("/")


def provenance_line(module: str, source_rel: str, today: date | None = None) -> str:
    """`> Measured by code: <module> from <relative source file>, <YYYY-MM-DD>.` (R-302).

    `source_rel` must be a POSIX path relative to the library folder (or a bare file name):
    an absolute path never goes into a file in the library folder -> ValueError.
    """
    source = str(source_rel)
    if not _relative_posix(source):
        raise ValueError(f"provenance source must be a relative POSIX path, got {source!r}")
    if not module or not module.strip():
        raise ValueError("provenance module must be named")
    return f"> Measured by code: {module.strip()} from {source}, {(today or date.today()).isoformat()}."


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.replace("|", "\\|").split())


def md_table(
    headers: Sequence[Any],
    rows: Iterable[Sequence[Any]],
    limit: int = LIST_LIMIT,
    *,
    where: str | None = None,
) -> str:
    """A Markdown table of the first `limit` rows (1 to 5). Rows past it are cut and counted
    on a line after the table: `And N more.` or, with `where`, `And N more in <where>.`
    Cells are one line each; a `|` in a cell is escaped."""
    if not 1 <= limit <= LIST_LIMIT:
        raise ValueError(f"limit must be 1 to {LIST_LIMIT}, got {limit}")
    if not headers:
        raise ValueError("a table needs headers")
    rows = [list(row) for row in rows]
    width = len(headers)
    if any(len(row) != width for row in rows):
        raise ValueError(f"every row needs {width} cells")
    lines = [
        "| " + " | ".join(_cell(h) for h in headers) + " |",
        "|" + "---|" * width,
    ]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows[:limit]]
    rest = len(rows) - min(len(rows), limit)
    if rest:
        lines += ["", f"And {rest} more" + (f" in {where}." if where else ".")]
    return "\n".join(lines)


def write_json(path: str | Path, data: Any) -> Path:
    """`data` as JSON: sorted keys, indent 2, UTF-8, LF, a final newline; temp file + os.replace.
    The same data always gives the same bytes."""
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return write_text(path, text + "\n")


def pct(n: int, d: int) -> int:
    """`n` of `d` as a whole percent, rounded half up (`pct(1, 8)` = 13). 0 when `d` is 0.

    100 only when `n == d` and 0 only when `n == 0`: 239 of 240 is 99, 1 of 1000 is 1, so a
    file never claims "every track" or "none" when that is not true."""
    if d <= 0 or n <= 0:
        return 0
    value = (200 * n + d) // (2 * d)
    return min(99, max(1, value)) if n < d else value


def parse_day(text: str | None) -> date | None:
    """`YYYY-MM-DD` -> date; empty -> None (the caller then uses today). Anything else -> ValueError."""
    if text is None or not str(text).strip():
        return None
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise ValueError(f"--today must be a date YYYY-MM-DD, got {text!r}") from None


# -- the folder an analysis writes into ------------------------------------------------------


class NotALibraryFolder(LibraryFolderError):
    """The folder is not one an analysis writes into: no valid library.yaml (not scaffolded),
    or a whole drive or home folder. Nothing was written. Skill scripts exit 2 (refused)."""


def library_folder(root: str | Path | LibraryFolder) -> LibraryFolder:
    """`root` resolved to an absolute path and checked before anything is read or written.

    - A drive root, the home folder or a folder above it -> NotALibraryFolder.
    - A folder that does not exist -> LibraryFolderError ("does not exist").
    - No library.yaml, or one that does not validate -> NotALibraryFolder ("run dj-start").

    Resolving first means a relative `--library dj-library` gives paths relative to the
    library folder, never to the current folder."""
    text = root.root if isinstance(root, LibraryFolder) else root
    try:
        resolved = libfolder._library_root(text, "the library folder")
    except LibraryFolderError as exc:
        raise NotALibraryFolder(f"{exc} Nothing was written.") from None
    folder = LibraryFolder(resolved)
    if not folder.root.is_dir():
        raise LibraryFolderError("The library folder does not exist. Scaffold it first.")
    if not folder.library_yaml.is_file():
        raise NotALibraryFolder(
            f"{folder.root.name} is not a dj-library folder (no library.yaml). "
            "Set it up with dj-start first. Nothing was written."
        )
    try:
        errors = libfolder.validate_meta(libfolder.load_meta(folder.root))
    except LibraryFolderError as exc:
        errors = [str(exc)]
    if errors:
        raise NotALibraryFolder(
            f"{folder.root.name}: library.yaml is not valid ({'; '.join(errors)}). "
            "Run dj-start on the folder first. Nothing was written."
        )
    return folder


def resolve_xml(root: str | Path, xml: str | Path) -> Path:
    """A `--xml` argument as one absolute path, the file that is both read and named in the
    provenance line. A relative path is looked up in the library folder first, then in the
    current folder (as dj-start does). Not found in either -> LibraryFolderError."""
    given = Path(xml).expanduser()
    path = given
    if not given.is_absolute():
        in_library = Path(root) / given
        path = in_library if in_library.is_file() else Path.cwd() / given
    if not path.is_file():
        raise LibraryFolderError(
            f"{given.as_posix()}: file not found in the library folder or the current folder."
        )
    return path.resolve()
