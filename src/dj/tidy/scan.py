"""Target -> items. Reads the rekordbox rows (through `library`, read-only) and the files.

A target is one of: a crate path (`house_base/0_INBOX`), the whole collection (`--all`),
or a folder on disk inside tidy.yaml's roots. Files and rows are cross-referenced both ways on
`library.posix_key` (FolderPath is stored POSIX-style, compared casefolded).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from dj import library
from dj.intake import slug
from dj.match import normalise_artist
from dj.tidy import TidyError, names, tags
from dj.tidy.checks import FileFacts, Item
from dj.tidy.config import TidyConfig, folder_in_roots

AUDIO_EXT = (".mp3", ".flac", ".wav", ".aif", ".aiff", ".m4a")
CRATE, FOLDER, ALL = "crate", "folder", "all"
HASH_MODES = ("collisions", "all", "none")


@dataclass(frozen=True)
class Target:
    kind: str
    value: str
    slug: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value, "slug": self.slug}

    @property
    def label(self) -> str:
        return {CRATE: self.value, FOLDER: self.value, ALL: "the whole collection"}[self.kind]


def resolve_target(crate: str | None, folder: str | None, all_tracks: bool, cfg: TidyConfig) -> Target:
    """Exactly one of crate / folder / all. A folder must exist and sit inside the roots."""
    if sum(bool(x) for x in (crate, folder, all_tracks)) != 1:
        raise TidyError("Give one <crate>, --folder, or --all.")
    if all_tracks:
        return Target(ALL, "", "all")
    if folder:
        path = Path(folder)
        if not path.is_dir():
            raise TidyError(f"--folder {folder!r} is not a directory.")
        if not folder_in_roots(path, cfg):
            roots = ", ".join(str(r) for r in cfg.roots)
            raise TidyError(f"--folder {path} is outside the tidy.yaml roots ({roots}).")
        full = path.resolve()
        return Target(FOLDER, str(full), slug(full.name) or "folder")
    return Target(CRATE, crate or "", slug(crate or ""))


def walk_folder(folder: Path) -> list[Path]:
    out = []
    for p in Path(folder).rglob("*"):
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXT:
            continue
        if p.name.endswith(tags.TMP_SUFFIX) or p.name.startswith("."):
            continue
        out.append(p)
    return sorted(out, key=lambda p: str(p).casefold())


def file_facts(path: Path, want_hash: bool = False) -> FileFacts:
    """Never raises: a file mutagen cannot read comes back with `read_error` set."""
    path = Path(path)
    if not path.is_file():
        return FileFacts(path, exists=False)
    st = path.stat()
    sha = tags.sha256(path) if want_hash else None
    try:
        t, s, a = tags.read(path)
    except TidyError as exc:
        return FileFacts(path, True, st.st_size, st.st_mtime, sha, None, None, None, None, str(exc))
    return FileFacts(path, True, st.st_size, st.st_mtime, sha, s.container, s, t, a)


def make_item(path: Path, rb: library.TrackInfo | None, crate: str | None, cfg: TidyConfig) -> Item:
    facts = file_facts(path)
    local_art = tags.find_local_art(path, cfg.art.local_names) if facts.exists else None
    return Item(
        file=facts,
        rb=rb,
        crate=crate,
        in_roots=folder_in_roots(path, cfg),
        parsed=names.parse_filename(path.stem),
        local_art=local_art,
    )


def hash_items(items: list[Item], mode: str) -> list[Item]:
    """`collisions` hashes only files that share a size with another; `all`; `none`."""
    if mode not in HASH_MODES:
        raise TidyError(f"--hash must be one of {', '.join(HASH_MODES)}")
    if mode == "none":
        return items
    sizes: dict[int, int] = {}
    for it in items:
        if it.file.exists:
            sizes[it.file.size] = sizes.get(it.file.size, 0) + 1
    out = []
    for it in items:
        if it.file.exists and it.file.sha256 is None and (mode == "all" or sizes.get(it.file.size, 0) > 1):
            try:
                digest = tags.sha256(it.file.path)
            except OSError:
                digest = None
            it = Item(dataclasses.replace(it.file, sha256=digest), it.rb, it.crate, it.in_roots, it.parsed, it.local_art)
        out.append(it)
    return out


def known_artists(infos: Iterable[library.TrackInfo]) -> frozenset[str]:
    return frozenset(a for a in (normalise_artist(t.artist) for t in infos if t.artist) if a)


def items_for(target: Target, db: Any, cfg: TidyConfig, hash_mode: str = "collisions"
              ) -> tuple[list[Item], dict[str, Any], frozenset[str]]:
    """-> (items, scan meta, known artists). `db` is a read-only session."""
    infos = library.track_infos(db)
    if target.kind == FOLDER:
        by_path = library.by_posix_path(infos)
        paths = walk_folder(Path(target.value))
        items = [make_item(p, by_path.get(library.posix_key(str(p))), None, cfg) for p in paths]
    elif target.kind == CRATE:
        _, in_crate = library.crate_track_infos(db, target.value, infos)
        items = [make_item(Path(t.path), t, target.value, cfg) for t in in_crate if t.path]
    else:
        items = [make_item(Path(t.path), t, None, cfg) for t in infos if t.path]
    items = hash_items(items, hash_mode)
    meta = {
        "target": target.as_dict(),
        "rb_rows": len(infos),
        "files": len(items),
        "not_in_rekordbox": sum(1 for it in items if it.rb is None),
        "missing_files": sum(1 for it in items if not it.file.exists),
        "unreadable": sum(1 for it in items if it.file.read_error),
        "hash_mode": hash_mode,
    }
    return items, meta, known_artists(infos)
