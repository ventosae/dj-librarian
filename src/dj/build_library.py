"""The library dj-build reads (W-36, D-30; closes Q-17 for the engine path).

    read_for_build(folder, source=None)  -> (Library, how files name that read)

`source` "xml": the latest export in exports/ (as before). "db": a read-only snapshot of master.db,
named "master.db" (dj.readers.db, Door 2: pyrekordbox is imported only then). None: what
library.yaml's `source` says the last full analysis read (`dj library analyze` records it), "xml"
when it says nothing. So proposals made from master.db build against master.db, and a playlist the
DJ made after the last export is there to fill from: the `from` paths resolve in the snapshot.
"""

from __future__ import annotations

from pathlib import Path

from dj import libfolder
from dj.libfolder import SOURCES, LibraryFolder
from dj.model import Library, LibraryError
from dj.readers.xml import read_xml

DB_READ = "master.db"  # how the build and the files it writes name a master.db read
NO_ENGINE = ("library.yaml says source: db: this library is read from rekordbox through the engine. Use the "
             "engine's tools (dj_structure_* / dj_crate_*), or export the collection and analyse that export.")  # fmt: skip


def source_of(folder: LibraryFolder, source: str | None = None) -> str:
    """The read to use: `source` when given, else library.yaml's `source`, else "xml"."""
    if source is None:
        source = libfolder.load_meta(folder.root).get("source") or "xml"
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}, got {source!r}")
    return source


def read_for_build(folder: LibraryFolder | str | Path, source: str | None = None) -> tuple[Library, str]:
    folder = folder if isinstance(folder, LibraryFolder) else LibraryFolder(Path(folder))
    if source_of(folder, source) == "db":
        try:
            from dj.readers.db import (
                read_db,  # Door 2, only when master.db is asked for
            )
        except ImportError as exc:  # a skill script in Cowork's sandbox: no pyrekordbox there
            raise LibraryError(NO_ENGINE) from exc
        return read_db(), DB_READ
    export = libfolder.latest_export(folder.root)
    return read_xml(export), folder.relative(export)
