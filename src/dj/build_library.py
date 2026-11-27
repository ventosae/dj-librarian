"""The library every command reads: a read-only snapshot of master.db (`dj.readers.db`, R-202).

    read_for_build(folder, source=None)  -> (Library, how files name that read)

One read on every OS: the analysis, the report, dj-build, dj-crate and the Style Barber all read
rekordbox itself, so a playlist the DJ made a minute ago is there, and the track ids are
master.db's own (what `dj.db_write` writes). Files name the read "master.db", never its path.
"""

from __future__ import annotations

from pathlib import Path

from dj import libfolder
from dj.libfolder import LibraryFolder
from dj.model import Library

DB_READ = "master.db"  # how the files a command writes name a master.db read
# "xml" is TEST SUPPORT ONLY (a Library from an export fixture): unreachable from the CLI, the MCP server and the skills.
SOURCES = ("db", "xml")
DEFAULT_SOURCE = "db"


def read_for_build(folder: LibraryFolder | str | Path, source: str | None = None) -> tuple[Library, str]:
    """(the Library, its name in files). `source` None: a master.db snapshot (DEFAULT_SOURCE)."""
    folder = folder if isinstance(folder, LibraryFolder) else LibraryFolder(Path(folder))
    source = source or DEFAULT_SOURCE
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}, got {source!r}")
    if source == "db":
        from dj.readers.db import (
            read_db,  # pyrekordbox loads only when a library is read
        )

        return read_db(), DB_READ
    from dj.readers.xml import read_xml  # test support only, see SOURCES

    export = libfolder.latest_export(folder.root)
    return read_xml(export), folder.relative(export)
