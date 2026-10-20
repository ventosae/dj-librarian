"""The one-shot analysis: read the library once, then profile, structure, taste, proposals and the
HTML report (dj-start step 4 in one call; R-104, R-401 ... R-406).

Door 1 core, except the master.db read: `dj.readers.db` (pyrekordbox) is imported only inside
`analyze` when `source="db"`, so the module imports without the engine. The Library is read once
(the latest export, `xml`, or a master.db snapshot) and every step works on that one Library
through its `facts` / `write` functions, so data only master.db holds (My Tags, smart
playlists) reaches every file. Each step appends its own log.md line, as its script does.

Writes text files inside the library folder only: profile/, structure/, taste/, reports/ and
log.md. Never writes to rekordbox, Spotify or audio files; the master.db read is a read-only
session on a snapshot copy (R-202). Files written there name the source relative to the folder
("exports/<date>-collection.xml") or "master.db", never an absolute path.

A step that fails to write is recorded under `failed` and the rest still run, so the report
renders with what there is (breadboard P4); the report says what is missing.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable

from dj import report as report_mod
from dj import treeschema
from dj.analysis import profile, structure, taste
from dj.analysis import proposals as proposals_mod
from dj.analysis.common import library_folder, resolve_xml
from dj.libfolder import LibraryFolder, append_log, latest_export
from dj.model import Library, LibraryError
from dj.readers.xml import read_xml

SOURCES = ("xml", "db")
DB_SOURCE = "master.db"  # how files in the folder name a master.db read: never its absolute path
STEPS = ("profile", "structure", "taste", "report")


def read_library(folder: LibraryFolder, *, source: str = "xml", xml: str | Path | None = None) -> tuple[Library, str]:
    """(the Library, its source as files in the folder name it)."""
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}, got {source!r}")
    if source == "db":
        if xml:
            raise ValueError("--xml goes with --source xml; --source db reads master.db")
        # Door 2: pyrekordbox is imported only when master.db is asked for
        from dj.readers.db import read_db

        return read_db(), DB_SOURCE
    path = resolve_xml(folder.root, xml) if xml else latest_export(folder.root)
    return read_xml(path), proposals_mod.source_name(folder, path)


def analyze(
    folder: LibraryFolder | str | Path,
    *,
    source: str = "xml",
    xml: str | Path | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Read the Library once, write every analysis file and the report. Returns counts first,
    then the source, the files written and kept, the report, the proposals, the log lines and
    the steps that failed (`{step, error}`). A folder without a valid library.yaml ->
    common.NotALibraryFolder before anything is read or written."""
    folder = library_folder(folder)
    lib, label = read_library(folder, source=source, xml=xml)
    when = proposals_mod.log_time(today)
    written: list[str] = []
    kept: list[str] = []
    logs: list[str] = []
    failed: list[dict[str, str]] = []

    def step(name: str, work: Callable[[], None]) -> None:
        try:
            work()
        except (LibraryError, treeschema.TreeSchemaError, OSError, ValueError) as exc:
            failed.append({"step": name, "error": str(exc)})

    profile_facts = profile.facts(lib, today=today)
    structure_facts = structure.facts(lib, today=today)
    taste_facts = taste.facts(lib, today=today)
    found = proposals_mod.candidates(lib, profile_facts, structure_facts, taste_facts)
    report: dict[str, str] = {}

    def do_profile() -> None:
        paths = profile.write(folder, profile_facts, source=label, today=today)
        written.extend(folder.relative(p) for p in paths)
        counts = {"tracks": profile_facts["size"]["tracks"], "duplicates": profile_facts["duplicates"]["groups"]}
        logs.append(append_log(folder.root, "profile", counts, profile.STATS_MD, now=when))

    def do_structure() -> None:
        doc = treeschema.from_library(lib, today=today)
        paths = structure.write(folder, structure_facts, structure.graph(lib), doc, source=label, today=today)
        written.extend(folder.relative(p) for p in paths[: len(structure.FILES)])
        kept.extend(folder.relative(p) for p in paths[len(structure.FILES):])
        c = structure_facts["counts"]
        counts = {"playlists": c["playlists"] + c["smart"], "folders": c["folders"], "files": len(paths)}
        logs.append(append_log(folder.root, "structure", counts, "structure/analysis.md", now=when))

    def do_taste() -> None:
        try:
            result = taste.write(folder, taste_facts, source=label, today=today)
        except taste.TasteWriteError as exc:
            written.extend(exc.written)
            counts = {"lines added": sum(len(v) for v in exc.added.values()), "files written": len(exc.written)}
            logs.append(append_log(folder.root, "taste", counts, file=folder.taste, now=when))
            raise
        written.extend(result["written"])
        added = sum(len(lines) for lines in result["added"].values())
        logs.append(append_log(folder.root, "taste", {"lines added": added}, file=folder.taste, now=when))

    def do_report() -> None:
        paths = proposals_mod.write_proposals(folder, found, today, source=label)
        written.append(folder.relative(paths[0]))
        kept.extend(folder.relative(p) for p in paths[1:])
        path = report_mod.render(folder, today=today)
        report["path"] = folder.relative(path)
        written.append(report["path"])
        counts = {"proposals": len(found), "files": len(paths) + 1}
        logs.append(append_log(folder.root, "report", counts, path, now=when))

    for name, work in zip(STEPS, (do_profile, do_structure, do_taste, do_report)):
        step(name, work)

    c = lib.counts()
    return {
        "counts": {
            "tracks": c["tracks"],
            "playlists": c["playlists"] + c["smart"],
            "folders": c["folders"],
            "proposals": len(found),
            "files": len(written) + len(kept),
            "failed": len(failed),
        },
        "source": source,
        "read": label,
        "report": report.get("path"),
        "proposals": [p.summary() for p in found],
        "written": written,
        "kept": kept,
        "log": logs,
        "failed": failed,
    }
