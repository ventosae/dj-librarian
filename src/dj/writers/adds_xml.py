"""The XML route for inbox adds and playlist copies: `dj apply --xml`, `dj copy --xml` (Q-22, R-802).

Stdlib + PyYAML only (through `dj.build_structure` and `dj.writers.rekordbox_xml`); it never opens
master.db. The CLI reads the approved tracks from a master.db snapshot
(`dj.readers.db.tracks_by_id`, R-202) and hands them in as `dj.model.Track`s, after the preview id
matched the preview (`dj.write_gate.check`). Design: `docs/prompts/plans/W-30.md`.

What it writes, create-only (hard rule 1): `proposals/<crate-slug>-adds-<YYYY-MM-DD>.xml` (then
`-2`, `-3` ...) under the folder the inbox loop runs in: the dj-library folder when its links.yaml
holds a link (`dj.intake.default_paths`), else the dj-librarian folder (gitignored there: the XML
holds file paths from this computer). The XML holds one top-level playlist, `<crate leaf> adds
<date>`, with the approved tracks in order, each by its file location in the library
(`dj.writers.rekordbox_xml.plan_lists`); a track without a location is left out and listed in
`unplaced`. rekordbox changes only when the DJ imports the file and drags the tracks onto the
crate (`import_steps`: the build card's first two steps, then that one drag).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from dj import libfolder
from dj.build_structure import MENU, import_steps, product_version
from dj.model import Library, Track
from dj.writers.rekordbox_xml import BuildError, plan_lists, render, write_xml

PROPOSALS = "proposals"
LIBRARY_FOLDER = "your dj-library folder"
REPO_FOLDER = "the dj-librarian folder"

__all__ = ["AddsXml", "BuildError", "device_for", "playlist_name", "write"]


@dataclass(frozen=True)
class AddsXml:
    """What `write` wrote."""

    path: Path
    file: str  # relative to the folder it was written in, POSIX
    playlist: str  # the one playlist in the XML
    crate: str  # where the DJ drags the tracks
    track_ids: tuple[str, ...]  # in the XML, in order
    unplaced: tuple[str, ...]  # left out: no file location in the library
    device: str
    import_steps: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "xml": self.file,
            "playlist": self.playlist,
            "crate": self.crate,
            "in_xml": len(self.track_ids),
            "unplaced": list(self.unplaced),
            "device": self.device,
            "import_steps": list(self.import_steps),
        }


def playlist_name(crate: str, day: date) -> str:
    """`<crate leaf> adds <YYYY-MM-DD>`: the playlist the DJ finds under "rekordbox xml"."""
    leaf = next((part.strip() for part in reversed(crate.split("/")) if part.strip()), crate.strip())
    return f"{leaf} adds {day.isoformat()}"


def device_for(library_root: Path | None) -> str:
    """The OS of the import card: `device` from the dj-library folder's library.yaml when the inbox
    loop runs there, else this computer's (mac on macOS, windows anywhere else)."""
    if library_root is not None:
        try:
            device = libfolder.load_meta(library_root).get("device")
        except (libfolder.LibraryFolderError, OSError, ValueError):
            device = None
        if device in MENU:
            return str(device)
    return "mac" if sys.platform == "darwin" else "windows"


def drag_step(playlist: str, crate: str) -> str:
    """The import card's last step: the one drag that puts the tracks in the crate."""
    return (
        f"Open {playlist} under rekordbox xml, select all its tracks and drag them onto {crate} in "
        "Playlists: that one drag adds them."
    )


def write(
    root: Path,
    *,
    slug: str,
    crate: str,
    tracks: Sequence[Track],
    day: date,
    device: str,
    library: bool,
) -> AddsXml:
    """Write `proposals/<slug>-adds-<day>.xml` under `root` (create-only) with one playlist of
    `tracks`, in order; return what was written. `library`: `root` is the dj-library folder (else
    the dj-librarian folder), for the import card's wording. No track with a file location ->
    BuildError, nothing written."""
    if not slug.strip() or "/" in slug or "\\" in slug:
        raise BuildError(f"the crate slug must be one file-name part, got {slug!r}")
    name = playlist_name(crate, day)
    lib = Library(source="db", tracks={t.id: t for t in tracks})
    plan = plan_lists([((name,), [t.id for t in tracks])], lib)
    placed = tuple(plan.playlist_tracks()[name])
    if not placed:
        raise BuildError(
            f"None of the {len(tracks)} track(s) has a file location in rekordbox: nothing to import. "
            "Nothing was written."
        )
    text = render(plan, product_version=product_version())
    path = write_xml(text, Path(root) / PROPOSALS / f"{slug}-adds-{day.isoformat()}.xml")
    file = path.relative_to(Path(root)).as_posix()
    first, second, _drag_folders = import_steps(device, file, folder=LIBRARY_FOLDER if library else REPO_FOLDER)
    return AddsXml(
        path=path,
        file=file,
        playlist=name,
        crate=crate,
        track_ids=placed,
        unplaced=tuple(plan.unplaced),
        device=device,
        import_steps=(first, second, drag_step(name, crate)),
    )
