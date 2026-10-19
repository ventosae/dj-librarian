"""dj.libfolder: the dj-library/ scaffold, library.yaml, exports, log.md (R-901..R-905)."""

from __future__ import annotations

import errno
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

import dj
from dj import libfolder
from dj.libfolder import (
    DIRS,
    FILES,
    GITIGNORE_EXTRA,
    GITIGNORE_LINES,
    GITIGNORE_MARKER,
    META_KEYS,
    SCHEMA_VERSION,
    LibraryFolder,
    LibraryFolderError,
    append_log,
    configured_root,
    import_export,
    latest_export,
    load_meta,
    relative,
    remember_root,
    scaffold,
    update_meta,
    validate_meta,
)

DAY = date(2026, 10, 20)
NEXT_DAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 20, 14, 5)
REPO = Path(__file__).resolve().parents[1]

# R-901, spelled out so a change to DIRS/FILES cannot quietly drop an entry.
R901_DIRS = (
    "exports", "profile", "structure", "taste", "crates", "reports", "proposals", "wishlist",
)  # fmt: skip
R901_FILES = ("README.md", "library.yaml", "links.yaml", "log.md")


def collection_xml(locations: list[str], *, product="rekordbox", version="7.2.8") -> str:
    """A tiny synthetic rekordbox collection export. Only made-up names and paths."""
    tracks = "\n".join(
        f'    <TRACK TrackID="{i}" Name="Synthetic {i}" Artist="Test Artist" Location="{loc}"/>'
        for i, loc in enumerate(locations, start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <PRODUCT Name="{product}" Version="{version}" Company="Example"/>
  <COLLECTION Entries="{len(locations)}">
{tracks}
  </COLLECTION>
  <PLAYLISTS>
    <NODE Type="0" Name="ROOT" Count="1">
      <NODE Name="Demo" Type="1" KeyType="0" Entries="1"><TRACK Key="1"/></NODE>
    </NODE>
  </PLAYLISTS>
</DJ_PLAYLISTS>
"""


def file_url(path: Path) -> str:
    return "file://localhost/" + path.as_posix().lstrip("/")


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    root = tmp_path / "dj-library"
    scaffold(root, device="windows", today=DAY)
    return root


@pytest.fixture
def export_file(tmp_path: Path) -> Path:
    src = tmp_path / "Desktop" / "rekordbox.xml"
    src.parent.mkdir()
    src.write_text(collection_xml(["file://localhost/C:/Music/one.mp3"]), encoding="utf-8")
    return src


# -- scaffold (R-901) ----------------------------------------------------------------------


def test_scaffold_creates_every_r901_entry(tmp_path):
    root = tmp_path / "dj-library"
    result = scaffold(root, device="mac", today=DAY)

    for name in R901_DIRS:
        assert (root / name).is_dir(), name
    for name in R901_FILES + (".gitignore",):
        assert (root / name).is_file(), name
    assert DIRS == R901_DIRS
    assert set(FILES) == set(R901_FILES) | {".gitignore"}
    assert result.created == DIRS + FILES
    assert result.skipped == ()


def test_scaffold_second_run_creates_nothing(lib):
    result = scaffold(lib, device="windows", today=NEXT_DAY)
    assert result.created == ()
    assert result.skipped == DIRS + FILES


def test_scaffold_never_overwrites_an_edited_file(lib):
    edited = {name: f"my own {name}\n" for name in FILES}
    for name, text in edited.items():
        (lib / name).write_text(text, encoding="utf-8")
    (lib / "taste" / "lanes.md").write_text("# Lanes\n", encoding="utf-8")

    result = scaffold(lib, device="mac", rekordbox_version="7.0.0", today=NEXT_DAY)

    assert result.created == ()
    assert result.skipped == DIRS + FILES
    for name, text in edited.items():
        if name != ".gitignore":
            assert (lib / name).read_text(encoding="utf-8") == text
    assert (lib / "taste" / "lanes.md").read_text(encoding="utf-8") == "# Lanes\n"
    # .gitignore: the DJ's own lines stay as they are; the machine-path lines are added after.
    gitignore = (lib / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.startswith(edited[".gitignore"] + GITIGNORE_MARKER + "\n")
    assert result.gitignore_added == GITIGNORE_LINES + GITIGNORE_EXTRA


def test_scaffold_appends_only_the_missing_gitignore_lines(tmp_path):
    root = tmp_path / "dj-library"
    root.mkdir()
    (root / ".gitignore").write_bytes(b".DS_Store\r\nexports/*.xml\r\n!keep.xml")  # no final EOL

    result = scaffold(root, device="mac", today=DAY)

    added = tuple(x for x in GITIGNORE_LINES + GITIGNORE_EXTRA if x != "exports/*.xml")
    assert result.gitignore_added == added
    assert ".gitignore" in result.skipped and ".gitignore" not in result.created
    raw = (root / ".gitignore").read_bytes()
    assert raw.startswith(b".DS_Store\r\nexports/*.xml\r\n!keep.xml\n")  # original bytes kept
    assert raw.endswith(("\n".join((GITIGNORE_MARKER, *added)) + "\n").encode("utf-8"))
    assert libfolder.gitignore_missing(root) == ()
    again = scaffold(root, device="mac", today=NEXT_DAY)
    assert again.gitignore_added == ()
    assert (root / ".gitignore").read_bytes() == raw


def test_scaffolded_gitignore_covers_every_machine_path_line(lib):
    assert libfolder.gitignore_missing(lib) == ()
    assert scaffold(lib, device="windows", today=DAY).gitignore_added == ()


def test_scaffold_adds_only_what_is_missing(tmp_path):
    root = tmp_path / "dj-library"
    (root / "exports").mkdir(parents=True)
    (root / "README.md").write_text("mine\n", encoding="utf-8")

    result = scaffold(root, device="mac", today=DAY)

    assert set(result.skipped) == {"exports", "README.md"}
    assert set(result.created) == (set(DIRS) | set(FILES)) - {"exports", "README.md"}
    assert (root / "README.md").read_text(encoding="utf-8") == "mine\n"


def test_scaffold_files_are_utf8_text_with_lf(lib):
    for name in FILES:
        raw = (lib / name).read_bytes()
        assert b"\r" not in raw, name
        raw.decode("utf-8")
    assert sorted(p.name for p in lib.iterdir() if p.is_file()) == sorted(FILES)


def test_scaffold_rejects_an_unknown_device(tmp_path):
    with pytest.raises(LibraryFolderError, match="device"):
        scaffold(tmp_path / "lib", device="linux", today=DAY)
    assert not (tmp_path / "lib").exists()


def test_scaffold_blocked_by_a_file_creates_nothing(tmp_path):
    root = tmp_path / "dj-library"
    root.mkdir()
    (root / "exports").write_text("not a folder", encoding="utf-8")
    with pytest.raises(LibraryFolderError, match="exports"):
        scaffold(root, device="mac", today=DAY)
    assert [p.name for p in root.iterdir()] == ["exports"]


def racing_link(monkeypatch, name: str, text: str = "written by someone else\n") -> None:
    """os.link that lets another writer create `name` just before ours lands (a race)."""
    real_link = os.link

    def link(src, dst, *args, **kwargs):
        if Path(dst).name == name and not Path(dst).exists():
            Path(dst).write_text(text, encoding="utf-8")
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(libfolder.os, "link", link)


def no_hard_links(monkeypatch) -> None:
    """A disk that cannot hard-link (FAT, exFAT): os.link fails with a non-EEXIST error."""

    def link(src, dst, *args, **kwargs):
        raise OSError(errno.EPERM, "hard links not supported here", str(dst))

    monkeypatch.setattr(libfolder.os, "link", link)


def test_scaffold_never_overwrites_a_file_that_appears_mid_run(tmp_path, monkeypatch):
    root = tmp_path / "dj-library"
    racing_link(monkeypatch, "README.md")

    result = scaffold(root, device="mac", today=DAY)

    assert "README.md" in result.skipped and "README.md" not in result.created
    assert (root / "README.md").read_text(encoding="utf-8") == "written by someone else\n"
    assert sorted(p.name for p in root.iterdir() if p.is_file()) == sorted(FILES)  # no temp left


@pytest.mark.parametrize("hard_links", [True, False])
def test_write_new_text_creates_once_and_never_overwrites(tmp_path, monkeypatch, hard_links):
    if not hard_links:
        no_hard_links(monkeypatch)
    path = tmp_path / "notes.md"
    assert libfolder.write_new_text(path, "first\n") is True
    assert libfolder.write_new_text(path, "second\n") is False
    assert path.read_bytes() == b"first\n"
    assert [p.name for p in tmp_path.iterdir()] == ["notes.md"]


def test_scaffold_works_on_a_disk_without_hard_links(tmp_path, monkeypatch):
    no_hard_links(monkeypatch)
    root = tmp_path / "dj-library"
    assert scaffold(root, device="mac", today=DAY).created == DIRS + FILES
    assert scaffold(root, device="mac", today=NEXT_DAY).created == ()
    assert sorted(p.name for p in root.iterdir() if p.is_file()) == sorted(FILES)


def test_library_folder_paths(tmp_path):
    folder = LibraryFolder(tmp_path)
    for name in DIRS:
        assert getattr(folder, name) == tmp_path / name
    assert folder.readme == tmp_path / "README.md"
    assert folder.library_yaml == tmp_path / "library.yaml"
    assert folder.links == tmp_path / "links.yaml"
    assert folder.log == tmp_path / "log.md"
    assert folder.gitignore == tmp_path / ".gitignore"
    assert folder.cache == tmp_path / ".cache"
    assert LibraryFolder(str(tmp_path)).root == tmp_path


def test_readme_documents_every_folder_and_file(lib):
    text = (lib / "README.md").read_text(encoding="utf-8")
    for name in DIRS:
        assert f"`{name}/`" in text, name
    for name in FILES:
        assert f"`{name}`" in text, name
    assert "`exports/*.xml`" in text and "`proposals/*.xml`" in text
    assert "gitignored" in text


def test_readme_lists_have_at_most_five_items(lib):
    """R-1002 rule 9: lists of 5 or fewer in every DJ-facing section."""
    sections: dict[str, int] = {}
    current = ""
    for line in (lib / "README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            current = line
        elif line.startswith("- "):
            sections[current] = sections.get(current, 0) + 1
    assert sections and max(sections.values()) <= 5


def test_links_yaml_is_a_commented_example_only(lib):
    from dj import intake

    text = (lib / "links.yaml").read_text(encoding="utf-8")
    assert all(not line or line.startswith("#") for line in text.splitlines())
    assert yaml.safe_load(text) is None
    assert intake.load_links(intake.Paths(root=lib)) == []


def test_log_md_starts_with_its_title(lib):
    assert (lib / "log.md").read_text(encoding="utf-8").splitlines()[0] == "# Log"


def test_gitignore_keeps_machine_files_out(lib):
    lines = (lib / ".gitignore").read_text(encoding="utf-8").splitlines()
    for line in GITIGNORE_LINES + GITIGNORE_EXTRA:
        assert line in lines
    assert set(GITIGNORE_LINES) == {"exports/*.xml", "proposals/*.xml", ".cache/", ".env"}
    assert set(GITIGNORE_EXTRA) == {"/*.xml", "*.tmp"}


def test_temp_files_are_named_for_the_gitignore(tmp_path):
    fd, tmp = libfolder._temp_next_to(tmp_path / "2026-10-20-collection.xml")
    os.close(fd)
    assert tmp.parent == tmp_path
    assert tmp.name.startswith(".") and tmp.name.endswith(".tmp")  # hidden, matches *.tmp
    assert not libfolder._is_export_name(tmp.name)


def test_repo_gitignore_ignores_a_dj_library_inside_the_clone():
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "dj-library/" in lines


# -- library.yaml (R-902) ------------------------------------------------------------------


def test_library_yaml_records_device_version_dates_structure_schema(tmp_path):
    root = tmp_path / "lib"
    scaffold(root, device="mac", rekordbox_version="7.2.8", today=DAY)
    meta = load_meta(root)
    assert list(meta) == list(META_KEYS)
    assert meta == {
        "schema_version": SCHEMA_VERSION,
        "device": "mac",
        "rekordbox_version": "7.2.8",
        "created": "2026-10-20",
        "updated": "2026-10-20",
        "structure": {"chosen": None},
        "exports": {"latest": None},
    }
    assert validate_meta(meta) == []


def test_validate_meta_accepts_the_scaffolded_file(lib):
    assert validate_meta(yaml.safe_load((lib / "library.yaml").read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize("key", META_KEYS)
def test_validate_meta_rejects_a_missing_key(lib, key):
    meta = load_meta(lib)
    del meta[key]
    assert f"missing key: {key}" in validate_meta(meta)


@pytest.mark.parametrize(
    ("key", "value", "fragment"),
    [
        ("device", "linux", "device"),
        ("device", None, "device"),
        ("schema_version", 2, "schema_version"),
        ("schema_version", "1", "schema_version"),
        ("schema_version", True, "schema_version"),
        ("rekordbox_version", "", "rekordbox_version"),
        ("rekordbox_version", 7, "rekordbox_version"),
        ("created", "20 Oct 2026", "created"),
        ("updated", "2026-13-01", "updated"),
        ("structure", None, "structure"),
        ("structure", {"chosen": None, "extra": 1}, "structure: unknown key"),
        ("structure", {}, "structure: missing key"),
        ("structure", {"chosen": ""}, "structure.chosen"),
        ("exports", {"latest": "C:/Users/someone/rekordbox.xml"}, "exports.latest"),
        ("exports", {"latest": "/Users/someone/rekordbox.xml"}, "exports.latest"),
        ("exports", {"latest": "exports\\2026-10-20-collection.xml"}, "exports.latest"),
        ("exports", {"latest": "../elsewhere.xml"}, "exports.latest"),
        # exports.latest names an export, not just any file in the folder
        ("exports", {"latest": "README.md"}, "exports.latest"),
        ("exports", {"latest": "library.yaml"}, "exports.latest"),
        ("exports", {"latest": "log.md"}, "exports.latest"),
        ("exports", {"latest": "rekordbox.xml"}, "exports.latest"),
        ("exports", {"latest": "~/x.xml"}, "exports.latest"),
        ("exports", {"latest": "proposals/bases.xml"}, "exports.latest"),
        ("exports", {"latest": "exports/"}, "exports.latest"),
        ("exports", {"latest": "exports/.xml"}, "exports.latest"),
        ("exports", {"latest": "exports/notes.txt"}, "exports.latest"),
        ("exports", {"latest": "exports/X.XML"}, "exports.latest"),
        ("exports", {"latest": "exports/old/2026-10-20-collection.xml"}, "exports.latest"),
        ("exports", {"latest": "exports/../library.yaml"}, "exports.latest"),
        ("exports", {"latest": "exports/.2026-10-20-collection.xml.k3j2.tmp"}, "exports.latest"),
        ("exports", {"latest": "exports/._2026-10-20-collection.xml"}, "exports.latest"),
        ("exports", {"latest": "exports/C:x.xml"}, "exports.latest"),
        ("exports", {"latest": "./exports/x.xml"}, "exports.latest"),
        ("exports", {"latest": 5}, "exports.latest"),
    ],
)
def test_validate_meta_rejects_a_wrong_value(lib, key, value, fragment):
    meta = load_meta(lib)
    meta[key] = value
    errors = validate_meta(meta)
    assert any(fragment in e for e in errors), errors


@pytest.mark.parametrize(
    "latest", ["exports/2026-10-20-collection.xml", "exports/my export.xml", None]
)
def test_validate_meta_accepts_an_export_or_null_as_latest(lib, latest):
    meta = load_meta(lib)
    meta["exports"] = {"latest": latest}
    assert validate_meta(meta) == []


def test_update_meta_refuses_a_latest_that_is_not_an_export(lib):
    before = (lib / "library.yaml").read_bytes()
    for value in ("README.md", "library.yaml", "~/x.xml"):
        with pytest.raises(LibraryFolderError, match="exports.latest"):
            update_meta(lib, today=DAY, exports={"latest": value})
    assert (lib / "library.yaml").read_bytes() == before


def test_validate_meta_rejects_unknown_keys_and_non_mappings(lib):
    meta = load_meta(lib)
    meta["music_folder"] = "x"
    assert "unknown key: music_folder" in validate_meta(meta)
    assert validate_meta(["not", "a", "mapping"]) != []
    assert validate_meta(None) != []


def test_validate_meta_accepts_unquoted_dates(lib):
    meta = load_meta(lib)
    meta["created"] = DAY
    assert validate_meta(meta) == []


def test_load_meta_needs_the_file_and_valid_yaml(tmp_path, lib):
    with pytest.raises(LibraryFolderError, match="not found"):
        load_meta(tmp_path / "nowhere")
    (lib / "library.yaml").write_text("device: [unclosed\n", encoding="utf-8")
    with pytest.raises(LibraryFolderError, match="YAML"):
        load_meta(lib)
    (lib / "library.yaml").write_text("- a list\n", encoding="utf-8")
    with pytest.raises(LibraryFolderError, match="mapping"):
        load_meta(lib)


def test_update_meta_merges_stamps_and_writes(lib):
    meta = update_meta(
        lib, today=NEXT_DAY, structure={"chosen": "bases"}, rekordbox_version="7.2.8"
    )
    assert meta["structure"] == {"chosen": "bases"}
    assert meta["updated"] == "2026-10-21" and meta["created"] == "2026-10-20"
    assert load_meta(lib) == meta
    text = (lib / "library.yaml").read_text(encoding="utf-8")
    assert text.startswith("# dj-library settings.") and "\r" not in text


def test_update_meta_refuses_an_invalid_change_and_leaves_the_file(lib):
    before = (lib / "library.yaml").read_bytes()
    with pytest.raises(LibraryFolderError, match="device"):
        update_meta(lib, today=NEXT_DAY, device="amiga")
    with pytest.raises(LibraryFolderError, match="no key"):
        update_meta(lib, today=NEXT_DAY, music_folder="x")
    assert (lib / "library.yaml").read_bytes() == before


# -- exports -------------------------------------------------------------------------------


def test_import_export_copies_and_leaves_the_source_untouched(lib, export_file):
    before = export_file.read_bytes()
    mtime = export_file.stat().st_mtime_ns

    target = import_export(lib, export_file, today=DAY)

    assert target == lib / "exports" / "2026-10-20-collection.xml"
    assert target.read_bytes() == before
    assert export_file.is_file()
    assert export_file.read_bytes() == before
    assert export_file.stat().st_mtime_ns == mtime
    assert [p.name for p in export_file.parent.iterdir()] == ["rekordbox.xml"]
    assert [p.name for p in (lib / "exports").iterdir()] == ["2026-10-20-collection.xml"]


def test_import_export_records_latest_and_rekordbox_version(lib, export_file):
    import_export(lib, export_file, today=NEXT_DAY)
    meta = load_meta(lib)
    assert meta["exports"] == {"latest": "exports/2026-10-21-collection.xml"}
    assert meta["rekordbox_version"] == "7.2.8"
    assert meta["updated"] == "2026-10-21"
    assert validate_meta(meta) == []


def test_import_export_same_content_is_skipped(lib, export_file):
    first = import_export(lib, export_file, today=DAY)
    library_yaml = (lib / "library.yaml").read_bytes()

    again = import_export(lib, export_file, today=NEXT_DAY)

    assert again == first
    assert [p.name for p in (lib / "exports").iterdir()] == ["2026-10-20-collection.xml"]
    assert (lib / "library.yaml").read_bytes() == library_yaml  # nothing changed, nothing written


def test_import_export_numbers_a_taken_name(lib, tmp_path):
    src = tmp_path / "export.xml"
    names = []
    for n in range(3):
        src.write_text(collection_xml([f"file://localhost/C:/Music/{n}.mp3"]), encoding="utf-8")
        names.append(import_export(lib, src, today=DAY).name)
    assert names == [
        "2026-10-20-collection.xml",
        "2026-10-20-collection-2.xml",
        "2026-10-20-collection-3.xml",
    ]
    assert load_meta(lib)["exports"]["latest"] == "exports/2026-10-20-collection-3.xml"

    src.write_text(collection_xml(["file://localhost/C:/Music/0.mp3"]), encoding="utf-8")
    assert import_export(lib, src, today=NEXT_DAY).name == "2026-10-20-collection.xml"
    assert load_meta(lib)["exports"]["latest"] == "exports/2026-10-20-collection.xml"


def test_import_export_reads_a_file_dropped_inside_the_folder(lib):
    dropped = lib / "rekordbox.xml"
    dropped.write_text(collection_xml(["file://localhost/C:/Music/one.mp3"]), encoding="utf-8")
    target = import_export(lib, dropped, today=DAY)
    assert target.parent == lib / "exports"
    assert dropped.is_file()


def test_import_export_keeps_the_version_of_another_product(lib, tmp_path):
    src = tmp_path / "other.xml"
    src.write_text(collection_xml([], product="Some Other App", version="3.1"), encoding="utf-8")
    import_export(lib, src, today=DAY)
    assert load_meta(lib)["rekordbox_version"] is None


def test_import_export_refuses_what_is_not_a_rekordbox_export(lib, tmp_path):
    other = tmp_path / "other.xml"
    other.write_text("<?xml version='1.0'?><plist><dict/></plist>", encoding="utf-8")
    with pytest.raises(LibraryFolderError, match="not a rekordbox XML"):
        import_export(lib, other, today=DAY)
    broken = tmp_path / "broken.xml"
    broken.write_text("<DJ_PLAYLISTS><PRODUCT", encoding="utf-8")
    with pytest.raises(LibraryFolderError, match="not readable XML"):
        import_export(lib, broken, today=DAY)
    with pytest.raises(LibraryFolderError, match="not found"):
        import_export(lib, tmp_path / "missing.xml", today=DAY)
    assert list((lib / "exports").iterdir()) == []


@pytest.mark.parametrize(
    "cut",
    [
        # truncated after PRODUCT, as if copied while rekordbox was still exporting
        lambda text: text[: text.index("<TRACK") + len('<TRACK TrackID="1" Loc')],
        lambda text: text[: text.index("</COLLECTION>")],
        lambda text: text[: text.index("</DJ_PLAYLISTS>")],
        # broken in the middle
        lambda text: text.replace("</COLLECTION>", "</COLLECTON>"),
        lambda text: text + "<TRAILING/>",
    ],
)
def test_import_export_refuses_a_truncated_or_broken_export(lib, tmp_path, cut):
    src = tmp_path / "half.xml"
    src.write_text(cut(collection_xml(["file://localhost/C:/Music/1.mp3"])), encoding="utf-8")
    before = (lib / "library.yaml").read_bytes()

    with pytest.raises(LibraryFolderError, match="Nothing was copied"):
        import_export(lib, src, today=DAY)

    assert list((lib / "exports").iterdir()) == []
    assert (lib / "library.yaml").read_bytes() == before
    with pytest.raises(LibraryFolderError, match="not readable XML"):
        libfolder.read_product(src)


def test_read_product_reads_name_and_version(export_file, tmp_path):
    assert libfolder.read_product(export_file) == ("rekordbox", "7.2.8")
    bare = tmp_path / "bare.xml"
    bare.write_text("<DJ_PLAYLISTS><COLLECTION/><PRODUCT Version='9'/></DJ_PLAYLISTS>", "utf-8")
    assert libfolder.read_product(bare) == (None, None)  # PRODUCT must come first


def test_import_export_refuses_a_source_that_changes_during_the_copy(lib, export_file, monkeypatch):
    real_copy = shutil.copyfileobj

    def copy_then_grow(src, dst, *args):
        real_copy(src, dst, *args)
        dst.write(b"<!-- rekordbox was still writing -->")

    monkeypatch.setattr(libfolder.shutil, "copyfileobj", copy_then_grow)
    before = (lib / "library.yaml").read_bytes()
    with pytest.raises(LibraryFolderError, match="changed while it was being copied"):
        import_export(lib, export_file, today=DAY)
    assert list((lib / "exports").iterdir()) == []  # the temp copy is gone too
    assert (lib / "library.yaml").read_bytes() == before


def test_import_export_never_overwrites_a_name_taken_mid_copy(lib, export_file, monkeypatch):
    racing_link(monkeypatch, "2026-10-20-collection.xml", "<DJ_PLAYLISTS/>")

    target = import_export(lib, export_file, today=DAY)

    assert target.name == "2026-10-20-collection-2.xml"
    assert target.read_bytes() == export_file.read_bytes()
    assert (lib / "exports" / "2026-10-20-collection.xml").read_text("utf-8") == "<DJ_PLAYLISTS/>"
    assert load_meta(lib)["exports"]["latest"] == "exports/2026-10-20-collection-2.xml"
    assert sorted(p.name for p in (lib / "exports").iterdir()) == [
        "2026-10-20-collection-2.xml",
        "2026-10-20-collection.xml",
    ]


def test_import_export_on_a_disk_without_hard_links(lib, tmp_path, monkeypatch):
    no_hard_links(monkeypatch)
    src = tmp_path / "export.xml"
    names = []
    for n in range(2):
        src.write_text(collection_xml([f"file://localhost/C:/Music/{n}.mp3"]), encoding="utf-8")
        names.append(import_export(lib, src, today=DAY).name)
    assert names == ["2026-10-20-collection.xml", "2026-10-20-collection-2.xml"]
    assert (lib / "exports" / names[1]).read_bytes() == src.read_bytes()
    assert sorted(p.name for p in (lib / "exports").iterdir()) == sorted(names)


def test_import_export_needs_a_scaffolded_folder(tmp_path, export_file):
    with pytest.raises(LibraryFolderError, match="library.yaml"):
        import_export(tmp_path / "empty", export_file, today=DAY)


def test_import_export_refuses_a_broken_library_yaml_before_copying(lib, export_file):
    text = (lib / "library.yaml").read_text(encoding="utf-8").replace("device: windows", "device: x")
    (lib / "library.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(LibraryFolderError, match="Nothing was copied"):
        import_export(lib, export_file, today=DAY)
    assert list((lib / "exports").iterdir()) == []


def test_latest_export_follows_library_yaml(lib, tmp_path, export_file):
    first = import_export(lib, export_file, today=DAY)
    other = tmp_path / "older.xml"
    other.write_text(collection_xml(["file://localhost/C:/Music/x.mp3"]), encoding="utf-8")
    import_export(lib, other, today=NEXT_DAY)
    update_meta(lib, today=NEXT_DAY, exports={"latest": "exports/2026-10-20-collection.xml"})
    assert latest_export(lib) == first


def test_latest_export_falls_back_to_the_newest_dated_file(lib):
    for name in (
        "2026-10-19-collection.xml",
        "2026-10-20-collection-2.xml",
        "2026-10-20-collection.xml",
        "zz-other.xml",
    ):
        (lib / "exports" / name).write_text("<DJ_PLAYLISTS/>", encoding="utf-8")
    assert latest_export(lib).name == "2026-10-20-collection-2.xml"
    update_meta(lib, today=DAY, exports={"latest": "exports/gone.xml"})
    assert latest_export(lib).name == "2026-10-20-collection-2.xml"


@pytest.mark.parametrize(
    "stored", ["README.md", "library.yaml", "log.md", "~/x.xml", "exports/notes.txt"]
)
def test_latest_export_ignores_a_stored_value_that_is_not_an_export(lib, export_file, stored):
    export = import_export(lib, export_file, today=DAY)
    # A hand-edited library.yaml: update_meta would refuse this value.
    text = (lib / "library.yaml").read_text(encoding="utf-8")
    text = text.replace("latest: exports/2026-10-20-collection.xml", f"latest: '{stored}'")
    (lib / "library.yaml").write_text(text, encoding="utf-8")
    (lib / "exports" / "notes.txt").write_text("not an export\n", encoding="utf-8")
    assert load_meta(lib)["exports"]["latest"] == stored
    assert latest_export(lib) == export


def test_latest_export_skips_hidden_and_temp_files(lib):
    (lib / "exports" / "2026-10-19-collection.xml").write_text("<DJ_PLAYLISTS/>", "utf-8")
    for name in (
        ".2026-10-21-collection.xml.k3j2.tmp",  # a copy a crash left behind
        "._2026-10-21-collection.xml",  # macOS AppleDouble file on a FAT/exFAT drive
        ".2026-10-22-collection.xml",
        "2026-10-23-collection.XML",
    ):
        (lib / "exports" / name).write_text("partial", encoding="utf-8")
    assert latest_export(lib).name == "2026-10-19-collection.xml"


def test_latest_export_without_any_export(lib):
    with pytest.raises(LibraryFolderError, match="No export"):
        latest_export(lib)


# -- log.md (R-904) ------------------------------------------------------------------------


def test_append_log_line_format(lib):
    counts = {"created": 3, "skipped": 1}
    line = append_log(lib, "build", counts, file="proposals/bases.xml", now=NOW)
    assert line == "2026-10-20 14:05 build -> 3 created, 1 skipped; proposals/bases.xml"
    assert (lib / "log.md").read_text(encoding="utf-8") == "# Log\n\n" + line + "\n"


def test_append_log_without_counts_or_file(lib):
    assert append_log(lib, "scaffold", now=NOW) == "2026-10-20 14:05 scaffold"
    line = append_log(lib, "profile", {"files": 2}, now=NOW)
    assert line == "2026-10-20 14:05 profile -> 2 files"
    assert append_log(lib, "report", file="reports/x.html", now=NOW) == (
        "2026-10-20 14:05 report; reports/x.html"
    )


def test_append_log_appends_and_keeps_earlier_lines(lib):
    (lib / "log.md").write_text("# Log\n\nmy own note without a newline", encoding="utf-8")
    append_log(lib, "a", now=NOW)
    append_log(lib, "b", now=datetime(2026, 10, 21, 9, 0))
    assert (lib / "log.md").read_text(encoding="utf-8").splitlines() == [
        "# Log",
        "",
        "my own note without a newline",
        "2026-10-20 14:05 a",
        "2026-10-21 09:00 b",
    ]


def test_append_log_creates_a_missing_log(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    line = append_log(root, "import", {"tracks": 2}, now=NOW)
    text = (root / "log.md").read_bytes().decode("utf-8")
    assert text == "# Log\n\n" + line + "\n"


def test_append_log_writes_files_relative_to_the_folder(lib, tmp_path):
    line = append_log(lib, "x", file=lib / "exports" / "2026-10-20-collection.xml", now=NOW)
    assert line.endswith("; exports/2026-10-20-collection.xml")
    line = append_log(lib, "x", file="structure\\current-tree.yaml", now=NOW)
    assert line.endswith("; structure/current-tree.yaml")
    for outside in (tmp_path / "elsewhere.xml", "../elsewhere.xml", "C:/Music/x.xml"):
        with pytest.raises(LibraryFolderError, match="outside"):
            append_log(lib, "x", file=outside, now=NOW)


@pytest.mark.parametrize(
    ("action", "counts"),
    [("", None), ("two\nlines", None), ("ok", {"tracks": "3"}), ("ok", {"tracks": True}),
     ("ok", {"tracks": -1}), ("ok", {"bad\nkey": 1})],
)  # fmt: skip
def test_append_log_refuses_bad_input(lib, action, counts):
    before = (lib / "log.md").read_bytes()
    with pytest.raises(LibraryFolderError):
        append_log(lib, action, counts, now=NOW)
    assert (lib / "log.md").read_bytes() == before


def test_append_log_needs_the_folder(tmp_path):
    with pytest.raises(LibraryFolderError):
        append_log(tmp_path / "missing", "x", now=NOW)


# -- where the folder is -------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A made-up home folder: Path.home() reads HOME on Mac/Linux, USERPROFILE on Windows."""
    path = tmp_path / "home" / "someone"
    path.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


@pytest.fixture
def fake_repo(tmp_path, monkeypatch, home):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(libfolder, "REPO_ROOT", repo)
    monkeypatch.delenv("DJ_LIBRARY", raising=False)
    return repo


def test_configured_root_default_is_inside_the_repo(fake_repo):
    assert configured_root() == (fake_repo / "dj-library").resolve()


def test_configured_root_uses_the_remembered_path(fake_repo, tmp_path):
    stored = remember_root(tmp_path / "Music Library" / "dj-library")
    assert stored == (tmp_path / "Music Library" / "dj-library").resolve()
    state = fake_repo / "state" / "library-path.txt"
    assert state.read_text(encoding="utf-8") == str(stored) + "\n"
    assert configured_root() == stored


def test_configured_root_env_wins(fake_repo, tmp_path, monkeypatch):
    remember_root(tmp_path / "remembered")
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path / "from-env"))
    assert configured_root() == (tmp_path / "from-env").resolve()
    monkeypatch.setenv("DJ_LIBRARY", "  ")
    assert configured_root() == (tmp_path / "remembered").resolve()


def test_configured_root_ignores_an_empty_state_file(fake_repo):
    (fake_repo / "state").mkdir()
    (fake_repo / "state" / "library-path.txt").write_text("\n", encoding="utf-8")
    assert configured_root() == (fake_repo / "dj-library").resolve()


def test_configured_root_is_always_absolute(fake_repo, tmp_path, home, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DJ_LIBRARY", "rel-lib")
    root = configured_root()
    assert root.is_absolute() and root == (tmp_path / "rel-lib").resolve()
    monkeypatch.setenv("DJ_LIBRARY", "~/dj-library")
    assert configured_root() == (home / "dj-library").resolve()
    monkeypatch.delenv("DJ_LIBRARY")
    (fake_repo / "state").mkdir()
    (fake_repo / "state" / "library-path.txt").write_text("stored-rel\n", encoding="utf-8")
    assert configured_root() == (tmp_path / "stored-rel").resolve()


def too_wide(tmp_path: Path, home: Path) -> list[str]:
    """Folders that would make the library boundary a whole drive or a whole home."""
    return [tmp_path.anchor, str(home), "~", str(home.parent), str(tmp_path), str(home / "..")]


def test_remember_root_refuses_a_drive_root_or_home(fake_repo, tmp_path, home):
    for path in too_wide(tmp_path, home):
        with pytest.raises(LibraryFolderError, match="not a library folder"):
            remember_root(path)
    assert not (fake_repo / "state" / "library-path.txt").exists()  # nothing stored
    assert remember_root(home / "dj-library") == (home / "dj-library").resolve()


def test_configured_root_refuses_a_drive_root_or_home(fake_repo, tmp_path, home, monkeypatch):
    for path in too_wide(tmp_path, home):
        monkeypatch.setenv("DJ_LIBRARY", path)
        with pytest.raises(LibraryFolderError, match="DJ_LIBRARY"):
            configured_root()
    monkeypatch.delenv("DJ_LIBRARY")
    (fake_repo / "state").mkdir()
    for path in too_wide(tmp_path, home):
        (fake_repo / "state" / "library-path.txt").write_text(path + "\n", encoding="utf-8")
        with pytest.raises(LibraryFolderError, match="library-path.txt"):
            configured_root()


def test_relative_gives_posix_paths_inside_the_folder(lib, tmp_path):
    assert relative(lib, lib / "taste" / "lanes.md") == "taste/lanes.md"
    assert relative(lib, "taste/lanes.md") == "taste/lanes.md"
    assert LibraryFolder(lib).relative(lib / "log.md") == "log.md"
    with pytest.raises(LibraryFolderError, match="outside"):
        relative(lib, tmp_path / "other.md")
    with pytest.raises(LibraryFolderError, match="outside"):
        relative(lib, "../other.md")


# -- R-905: git-initialisable, no absolute paths outside library.yaml ---------------------

ABSOLUTE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|/Users/|/home/|file://")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")
def test_r905_folder_commits_without_absolute_paths(tmp_path):
    root = tmp_path / "dj-library"
    scaffold(root, device="windows", rekordbox_version="7.2.8", today=DAY)
    # The DJ drops the export at the top of the folder, as the onboarding asks.
    dropped = root / "rekordbox.xml"
    dropped.write_text(
        collection_xml(
            [
                "file://localhost/C:/Users/someone/Music/one.mp3",
                "file://localhost/Users/someone/Music/two.mp3",
                "file://localhost/home/someone/Music/three.mp3",
                file_url(tmp_path / "Music" / "four.mp3"),
            ]
        ),
        encoding="utf-8",
    )
    export = import_export(root, dropped, today=DAY)
    update_meta(root, today=DAY, structure={"chosen": "bases"})
    append_log(root, "import export", {"tracks": 4}, file=export, now=NOW)
    (root / "proposals" / "bases.xml").write_text(dropped.read_text("utf-8"), encoding="utf-8")

    from dj import treeschema

    inbox = treeschema.TreeNode("playlist", "0_INBOX")
    doc = treeschema.TreeDoc(
        (treeschema.TreeNode("folder", "house_base", (inbox,)),),
        {"name": "Current tree", "source": relative(root, export), "generated": "2026-10-20"},
    )
    treeschema.dump(doc, root / "structure" / "current-tree.yaml")
    # Temp files a hard kill left mid-write (the cleanup never ran): one holds machine paths.
    xml_text = dropped.read_text(encoding="utf-8")
    (root / "exports" / ".collection.xml.k3j2.tmp").write_text(xml_text, encoding="utf-8")
    (root / "proposals" / ".bases.xml.ab12.tmp").write_text(xml_text, encoding="utf-8")
    (root / ".library.yaml.zz99.tmp").write_text("device: windows\n", encoding="utf-8")

    git = git_in(root, tmp_path)
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "library")
    tracked = sorted(git("ls-files").splitlines())

    assert tracked == sorted(
        [".gitignore", "README.md", "library.yaml", "links.yaml", "log.md",
         "structure/current-tree.yaml"]
    )  # fmt: skip
    assert git("status", "--porcelain", "--untracked-files=all") == ""
    assert_no_machine_paths(root, tracked, tmp_path)
    # The XML files did hold absolute paths; git simply never saw them.
    assert ABSOLUTE.search(export.read_text(encoding="utf-8"))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")
def test_r905_holds_when_the_folder_already_had_a_gitignore(tmp_path, export_file):
    root = tmp_path / "dj-library"
    root.mkdir()
    (root / ".gitignore").write_text(".DS_Store\n", encoding="utf-8")

    result = scaffold(root, device="windows", today=DAY)
    assert result.gitignore_added == GITIGNORE_LINES + GITIGNORE_EXTRA
    export_file.write_text(
        collection_xml(["file://localhost/C:/Users/someone/Music/one.mp3"]), encoding="utf-8"
    )
    export = import_export(root, export_file, today=DAY)
    (root / "exports" / ".collection.xml.k3j2.tmp").write_bytes(export.read_bytes())

    git = git_in(root, tmp_path)
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "library")
    tracked = sorted(git("ls-files").splitlines())

    assert tracked == [".gitignore", "README.md", "library.yaml", "links.yaml", "log.md"]
    assert git("status", "--porcelain", "--untracked-files=all") == ""
    assert_no_machine_paths(root, tracked, tmp_path)
    assert (root / ".gitignore").read_text(encoding="utf-8").startswith(".DS_Store\n")


def git_in(root: Path, tmp_path: Path):
    """A git runner for `root` that keeps the machine's own git config out of the test."""
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test DJ",
        "GIT_AUTHOR_EMAIL": "dj@example.invalid",
        "GIT_COMMITTER_NAME": "Test DJ",
        "GIT_COMMITTER_EMAIL": "dj@example.invalid",
    }

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", *args], cwd=root, env=env, capture_output=True, text=True, check=True
        )
        return done.stdout

    return git


def assert_no_machine_paths(root: Path, tracked: list[str], tmp_path: Path) -> None:
    machine = {str(p) for p in (tmp_path, tmp_path.resolve())}
    machine |= {p.as_posix() for p in (tmp_path, tmp_path.resolve())}
    for name in tracked:
        text = (root / name).read_text(encoding="utf-8")
        assert not ABSOLUTE.search(text), (name, ABSOLUTE.search(text))
        for path in machine:
            assert path not in text, name


# -- Door 1: imports without the engine's packages -----------------------------------------

DOOR1 = r"""
import sys
BLOCKED = ("pyrekordbox", "rapidfuzz", "httpx", "typer", "mcp")
for name in BLOCKED:
    sys.modules[name] = None
import dj.libfolder
import dj.treeschema
from datetime import date
from pathlib import Path

root = Path(sys.argv[1])
dj.libfolder.scaffold(root, device="mac", today=date(2026, 10, 20))
doc = dj.treeschema.load(sys.argv[2])
dj.treeschema.dump(doc, root / "structure" / "current-tree.yaml")
dj.libfolder.append_log(root, "door1", {"nodes": len(list(dj.treeschema.walk(doc)))})
loaded = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED and sys.modules[m] is not None)
assert not loaded, loaded
heavy = sorted(m for m in ("dj.tree", "dj.rules", "dj.match", "dj.library") if m in sys.modules)
assert not heavy, heavy
print("door1 ok")
"""


EXAMPLE_TREE = REPO / "examples" / "tree.example.yaml"


def test_door1_imports_without_engine_packages(tmp_path):
    src = str(Path(dj.__file__).resolve().parents[1])
    paths = [src, *filter(None, [os.environ.get("PYTHONPATH")])]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}
    done = subprocess.run(
        [sys.executable, "-c", DOOR1, str(tmp_path / "lib"), str(EXAMPLE_TREE)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert "door1 ok" in done.stdout
    assert (tmp_path / "lib" / "structure" / "current-tree.yaml").is_file()
