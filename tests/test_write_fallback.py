"""Writing on a disk that refuses deletes and renames (Q-27, W-30 item 1).

Cowork's device VM mounts the connected folder so that files can be created and written but not
deleted or renamed. There os.replace fails, and a temp file can never be removed. The writers in
dj.libfolder (and everything built on them: write_json, taste files, reports, crates, builds, the
tidy plan) then write the target in place, never hard-link, keep create-only files create-only,
and make no temp file at all on such a disk: a probe finds it before the first temp file. A
refused probe is written down in the library's .cache/ for later runs on the same platform and
device; any other computer, and any undo record, checks the disk itself. A stray temp file from
an earlier run means nothing.
"""

from __future__ import annotations

import errno
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest
import xml_fixtures as fx

from dj import libfolder
from dj.analysis.common import write_json
from dj.libfolder import NO_DELETE_NOTE, scaffold
from dj.tidy import plan as tidy_plan

DAY = date(2026, 10, 20)
_RUN_STATE = {"_REFUSED": set, "_PROBE_REFUSED": set, "_DELETES": set, "_TRUSTED": set, "_NOTES": dict,
              "_WRITTEN_DOWN": set}  # fmt: skip


def new_run(monkeypatch) -> None:
    """A new process: nothing this module learned about any disk is remembered."""
    for name, kind in _RUN_STATE.items():
        monkeypatch.setattr(libfolder, name, kind())


@pytest.fixture(autouse=True)
def fresh_run(monkeypatch):
    new_run(monkeypatch)


def _refuse(*_args, **_kwargs):
    raise PermissionError(errno.EACCES, "Operation not permitted")


def refuse_replace(monkeypatch) -> None:
    monkeypatch.setattr(libfolder.os, "replace", _refuse)


def refuse_link(monkeypatch) -> None:
    monkeypatch.setattr(libfolder.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EPERM, "no links")))


def no_delete_disk(monkeypatch, root: Path) -> None:
    """Under `root`: create and write work, a hard link works, delete and rename are refused."""
    real_unlink, real_replace, real_rename = os.unlink, os.replace, os.rename

    def inside(path) -> bool:
        try:
            return Path(path).resolve().is_relative_to(root.resolve())
        except (OSError, ValueError):
            return False

    def unlink(path, *a, **k):
        if inside(path):
            raise PermissionError(errno.EPERM, "Operation not permitted", str(path))
        return real_unlink(path, *a, **k)

    def replace(src, dst, *a, **k):
        if inside(src) or inside(dst):
            raise PermissionError(errno.EPERM, "Operation not permitted", str(src))
        return real_replace(src, dst, *a, **k)

    def rename(src, dst, *a, **k):
        if inside(src) or inside(dst):
            raise PermissionError(errno.EPERM, "Operation not permitted", str(src))
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(os, "unlink", unlink)
    monkeypatch.setattr(os, "remove", unlink)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "rename", rename)


def temps(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.tmp"))


def hard_links(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and os.stat(p).st_nlink > 1)


def disk(path: Path) -> str:
    return f"{sys.platform} {os.stat(path).st_dev}"


def note_of(root: Path) -> Path:
    return root / ".cache" / NO_DELETE_NOTE


def count_temps(monkeypatch) -> list[Path]:
    """Every temp file a writer makes from now on (its target), in order."""
    calls: list[Path] = []
    real = libfolder._temp_next_to
    monkeypatch.setattr(libfolder, "_temp_next_to", lambda target: calls.append(target) or real(target))
    return calls


def no_temp_and_no_probe(monkeypatch) -> None:
    monkeypatch.setattr(libfolder, "_temp_next_to", lambda target: pytest.fail(f"temp file for {target}"))
    monkeypatch.setattr(libfolder, "_probe_deletes", lambda folder: pytest.fail(f"probe in {folder}"))


def library(tmp_path: Path) -> Path:
    root = tmp_path / "dj-library"
    scaffold(root, device="mac", today=DAY)
    return root


# -- os.replace or os.link raising: the directory holds exactly the target -----------------------


@pytest.mark.parametrize("existing", [False, True])
def test_write_text_writes_in_place_when_replace_is_refused(tmp_path, monkeypatch, existing):
    target = tmp_path / "library.yaml"
    if existing:
        target.write_bytes(b"old: 1\n")
    refuse_replace(monkeypatch)
    assert libfolder.write_text(target, "new: 2\nline: two\n") == target
    assert target.read_bytes() == b"new: 2\nline: two\n"  # UTF-8, LF
    assert [p.name for p in tmp_path.iterdir()] == ["library.yaml"]


def test_write_json_writes_in_place_when_replace_is_refused(tmp_path, monkeypatch):
    refuse_replace(monkeypatch)
    path = write_json(tmp_path / "facts.json", {"b": 1, "a": [1, 2]})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": [1, 2], "b": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["facts.json"]


def test_write_new_text_with_link_refused_keeps_the_directory_clean(tmp_path, monkeypatch):
    refuse_link(monkeypatch)
    assert libfolder.write_new_text(tmp_path / "notes.md", "first\n") is True
    assert [p.name for p in tmp_path.iterdir()] == ["notes.md"]


def test_write_new_text_with_link_and_replace_refused_fills_its_own_reservation(tmp_path, monkeypatch):
    refuse_link(monkeypatch)
    refuse_replace(monkeypatch)
    path = tmp_path / "notes.md"
    assert libfolder.write_new_text(path, "first\n") is True
    assert libfolder.write_new_text(path, "second\n") is False  # still create-only
    assert path.read_bytes() == b"first\n"
    assert [p.name for p in tmp_path.iterdir()] == ["notes.md"]


def test_write_new_numbered_with_replace_and_link_refused(tmp_path, monkeypatch):
    refuse_link(monkeypatch)
    refuse_replace(monkeypatch)
    first = libfolder.write_new_numbered(tmp_path, "2026-10-20-library", ".html", "<p>1</p>\n")
    second = libfolder.write_new_numbered(tmp_path, "2026-10-20-library", ".html", "<p>2</p>\n")
    assert (first.name, second.name) == ("2026-10-20-library.html", "2026-10-20-library-2.html")
    assert {p.name for p in tmp_path.iterdir()} == {first.name, second.name}
    assert first.read_bytes() == b"<p>1</p>\n"


def test_a_reservation_someone_else_filled_is_kept(tmp_path):
    tmp, target = tmp_path / ".t.abcdefgh.tmp", tmp_path / "t.md"
    tmp.write_bytes(b"ours\n")
    target.write_bytes(b"theirs\n")
    assert libfolder._fill_reservation(tmp, target) is False
    assert target.read_bytes() == b"theirs\n"


def test_the_tidy_plan_writer_leaves_no_temp_and_writes_in_place_when_refused(tmp_path, monkeypatch):
    path = tmp_path / "plans" / "x.plan.json"
    tidy_plan._write_json_atomic(path, {"a": 1})
    refuse_replace(monkeypatch)
    tidy_plan._write_json_atomic(path, {"a": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}
    assert [p.name for p in path.parent.iterdir()] == ["x.plan.json"]


# -- a disk that refuses deletes: the probe finds it before any temp file -------------------------


def test_on_a_no_delete_disk_no_temp_file_is_made_and_nothing_is_hard_linked(tmp_path, monkeypatch):
    root = tmp_path / "dj-library"
    root.mkdir()
    no_delete_disk(monkeypatch, root)
    calls = count_temps(monkeypatch)

    made = scaffold(root, device="mac", today=DAY)
    assert set(made.created) >= {"README.md", "library.yaml", "log.md", ".gitignore"}
    (probe,) = temps(root)  # the one file nothing can remove: the probe, empty, never a link
    assert probe.parent == root and probe.name.startswith(".dj-probe.") and probe.stat().st_size == 0
    assert (root / "README.md").read_text(encoding="utf-8") == libfolder.README_TEXT
    assert "*.tmp" in libfolder.GITIGNORE_TEXT and ".cache/" in libfolder.GITIGNORE_TEXT  # both out of git
    note = note_of(root).read_text(encoding="utf-8")
    assert note.startswith("# dj-librarian:") and f"\n{disk(root)} " in note

    libfolder.update_meta(root, today=date(2026, 10, 21), dj_name="DJ Sample")
    libfolder.write_text(root / "profile" / "stats.md", "# Stats\n")
    write_json(root / "profile" / "facts.json", {"tracks": 24})
    libfolder.write_new_numbered(root / "reports", "2026-10-21-library", ".html", "<p>r</p>\n")
    assert libfolder.write_new_text(root / "crates" / "a.md", "a\n") is True
    assert libfolder.write_new_text(root / "crates" / "a.md", "b\n") is False  # create-only holds
    assert calls == []  # not one temp file in the whole run
    assert temps(root) == [probe]
    assert hard_links(root) == []
    assert libfolder.load_meta(root)["dj_name"] == "DJ Sample"
    assert (root / "crates" / "a.md").read_bytes() == b"a\n"

    # A later run on the same disk reads the note: in place from the start, no probe, no new file.
    new_run(monkeypatch)
    no_temp_and_no_probe(monkeypatch)
    libfolder.write_text(root / "structure" / "analysis.md", "# Structure\n")
    libfolder.write_text(root / "library.yaml", (root / "library.yaml").read_text(encoding="utf-8"))
    assert libfolder.write_new_text(root / "taste" / "lanes.md", "lanes\n") is True
    assert temps(root) == [probe] and hard_links(root) == []


def test_a_library_first_written_on_a_no_delete_disk_leaves_one_probe_for_all_its_folders(tmp_path, monkeypatch):
    """Scaffolded on the DJ's computer, then used from Cowork: one probe for the whole library,
    not one leftover per folder, and no file hard-linked to a temp."""
    root = library(tmp_path)
    new_run(monkeypatch)
    no_delete_disk(monkeypatch, root)
    libfolder.write_new_numbered(root / "profile", "stats", ".md", "# Stats\n")
    libfolder.write_new_numbered(root / "reports", "2026-10-20-library", ".html", "<p>r</p>\n")
    libfolder.write_text(root / "structure" / "analysis.md", "# Structure\n")
    assert libfolder.write_new_text(root / "taste" / "lanes.md", "lanes\n") is True
    write_json(root / "profile" / "facts.json", {"tracks": 24})
    (probe,) = temps(root)
    assert probe.parent == root / "profile" and probe.name.startswith(".dj-probe.")
    assert hard_links(root) == []
    assert f"\n{disk(root)} " in note_of(root).read_text(encoding="utf-8")


def test_on_a_no_delete_disk_the_export_copy_is_checked_and_written_in_place(tmp_path, monkeypatch):
    root = library(tmp_path)
    source = fx.write_xml(tmp_path / "collection.xml")
    note_of(root).parent.mkdir()
    note_of(root).write_text(f"{disk(root)} 2026-10-19\n", encoding="utf-8")  # an earlier run's
    new_run(monkeypatch)
    no_delete_disk(monkeypatch, root)
    target = libfolder.import_export(root, source, today=DAY)
    assert target.name == "2026-10-20-collection.xml"
    assert target.read_bytes() == source.read_bytes()
    assert temps(root) == []
    again = libfolder.import_export(root, source, today=DAY)
    assert again == target and sorted(p.name for p in (root / "exports").iterdir()) == [target.name]


def test_an_undo_record_never_trusts_the_note_and_the_disk_is_written_down_once(tmp_path, monkeypatch):
    root = library(tmp_path)
    new_run(monkeypatch)
    no_delete_disk(monkeypatch, root)
    libfolder.write_text(root / "profile" / "stats.md", "# Stats\n")  # the probe refuses: noted
    new_run(monkeypatch)
    monkeypatch.setattr(libfolder, "_temp_next_to", lambda target: pytest.fail(f"temp file for {target}"))
    undo = root / "state" / "tidy" / "x.undo.json"
    tidy_plan._write_json_atomic(undo, {"step": 1})  # probes again (refused), then in place
    tidy_plan._write_json_atomic(undo, {"step": 2})  # known in this run now: no second probe
    assert json.loads(undo.read_text(encoding="utf-8")) == {"step": 2}
    assert len([p for p in temps(root) if p.name.startswith(".dj-probe.")]) == 2 == len(temps(root))
    note = note_of(root).read_text(encoding="utf-8")
    assert note.count(f"{disk(root)} ") == 1 and note.count("# dj-librarian:") == 1


# -- a normal disk keeps the temp-file route ------------------------------------------------------


def test_a_leftover_temp_from_an_earlier_run_never_switches_to_in_place(tmp_path, monkeypatch):
    """What a Cowork session (or a crash) leaves behind does not cost the DJ's own computer its
    atomic writes, the tidy undo record least of all."""
    root = library(tmp_path)
    leftovers = {root / ".README.md.k3j9x0qa.tmp": b"readme", root / "profile" / ".stats.md.abcdefgh.tmp": b"half",
                 root / ".dj-probe.zz99yy88.tmp": b""}  # fmt: skip
    for path, data in leftovers.items():
        path.write_bytes(data)
    new_run(monkeypatch)
    calls = count_temps(monkeypatch)
    libfolder.write_text(root / "profile" / "stats.md", "# Stats\n")
    assert libfolder.write_new_text(root / "crates" / "a.md", "a\n") is True
    undo = root / "state" / "tidy" / "x.undo.json"
    tidy_plan._write_json_atomic(undo, {"step": 1})
    tidy_plan._write_json_atomic(undo, {"step": 2})
    assert calls == [root / "profile" / "stats.md", root / "crates" / "a.md", undo, undo]
    assert set(temps(root)) == set(leftovers)  # ours from before: never removed (hard rule 1)
    assert all(path.read_bytes() == data for path, data in leftovers.items())
    assert not note_of(root).exists()


def test_a_note_from_another_computer_does_not_switch_this_one(tmp_path, monkeypatch):
    root = library(tmp_path)
    dev = os.stat(root).st_dev
    other = "darwin" if sys.platform != "darwin" else "win32"
    note_of(root).parent.mkdir()
    note_of(root).write_text(f"# note\n{other} {dev} 2026-10-19\n{sys.platform} {dev + 1} 2026-10-19\n",
                             encoding="utf-8")  # fmt: skip
    new_run(monkeypatch)
    calls = count_temps(monkeypatch)
    libfolder.write_text(root / "profile" / "stats.md", "# Stats\n")
    assert calls == [root / "profile" / "stats.md"] and temps(root) == []


def test_a_note_naming_this_disk_is_overruled_by_a_probe_that_deletes(tmp_path, monkeypatch):
    """The note saves the probe for ordinary files. An undo record probes anyway; when the disk
    deletes after all, the rest of the run goes back to the temp-file route."""
    root = library(tmp_path)
    note_of(root).parent.mkdir()
    note_of(root).write_text(f"{disk(root)} 2026-10-19\n", encoding="utf-8")
    new_run(monkeypatch)
    calls = count_temps(monkeypatch)
    libfolder.write_text(root / "profile" / "stats.md", "# Stats\n")
    assert calls == []  # the note: in place, no probe
    undo = root / "state" / "tidy" / "x.undo.json"
    tidy_plan._write_json_atomic(undo, {"step": 1})
    libfolder.write_text(root / "profile" / "stats.md", "# Stats 2\n")
    assert calls == [undo, root / "profile" / "stats.md"]
    assert temps(root) == []


def test_a_refused_temp_removal_on_a_disk_that_deletes_is_not_written_down(tmp_path, monkeypatch):
    """A file held for a moment (a scanner, a sync client) is not a no-delete disk: in place for
    the rest of this run, not remembered, and the next run uses temp files again."""
    root = library(tmp_path)
    new_run(monkeypatch)
    real_unlink = os.unlink

    def unlink(path, *a, **k):
        if Path(path).name.startswith(".a.md.") and Path(path).exists():
            raise PermissionError(errno.EACCES, "held by another program", str(path))
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(os, "unlink", unlink)
    refuse_replace(monkeypatch)
    calls = count_temps(monkeypatch)
    libfolder.write_text(root / "a.md", "a\n")
    libfolder.write_text(root / "b.md", "b\n")
    assert calls == [root / "a.md"]  # b.md: in place, no second leftover
    assert [p.name.startswith(".a.md.") for p in temps(root)] == [True]
    assert not note_of(root).exists()
    monkeypatch.undo()
    new_run(monkeypatch)
    calls = count_temps(monkeypatch)
    libfolder.write_text(root / "c.md", "c\n")
    assert calls == [root / "c.md"]


def test_the_probe_tries_again_before_it_calls_a_disk_no_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(libfolder, "_PROBE_TRIES", 3)
    monkeypatch.setattr(libfolder, "_PROBE_PAUSE", 0)
    real_unlink = os.unlink
    refused: list[str] = []

    def unlink(path, *a, **k):
        if Path(path).name.startswith(".dj-probe.") and not refused:
            refused.append(str(path))
            raise PermissionError(errno.EACCES, "scanning", str(path))
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(os, "unlink", unlink)
    calls = count_temps(monkeypatch)
    libfolder.write_text(tmp_path / "a.md", "a\n")
    assert len(refused) == 1 and calls == [tmp_path / "a.md"]
    assert [p.name for p in tmp_path.iterdir()] == ["a.md"]


def test_a_folder_on_a_normal_disk_keeps_the_temp_file_route(tmp_path, monkeypatch):
    calls = count_temps(monkeypatch)
    libfolder.write_text(tmp_path / "a.md", "a\n")
    assert calls == [tmp_path / "a.md"] and [p.name for p in tmp_path.iterdir()] == ["a.md"]


def test_the_note_names_a_disk_by_platform_and_device_only():
    text = "# comment\n\nlinux 2049 2026-10-21\n  darwin 16777220 2026-10-22  \n# win32 5 x\nbroken\n"
    assert libfolder._note_disks(text) == {"linux 2049", "darwin 16777220"}
