"""NFR-05: a bare file name resolves under its folder, with an example in the tool description.

`repo_file` / `library_file` take the tool's default folder (`folder=`): tracklists/ for
dj_build_*, plans/ for dj_apply_* and the tidy plan tools, exports/ for dj_library_inspect. An
existing exact path still wins; a path outside the repo (or the library folder) is refused as
before; a name that is found nowhere says where it looked.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dj import mcp_server as m

PID = "0123456789ab"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "tracklists").mkdir(parents=True)
    (root / "plans").mkdir()
    monkeypatch.setattr(m, "REPO_ROOT", root)
    library = tmp_path / "dj-library"
    (library / "exports").mkdir(parents=True)
    monkeypatch.setenv("DJ_LIBRARY", str(library))
    return NS(root=root, library=library, outside=tmp_path)


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return NS(returncode=0, stdout=json.dumps({"counts": {}, "preview_id": PID}), stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    return seen


def write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# -- repo_file -----------------------------------------------------------------------------------


def test_a_bare_name_resolves_under_the_tools_folder(repo):
    target = write(repo.root / "tracklists" / "set.txt")
    assert m.repo_file("set.txt", (".txt",), folder=m.TRACKLISTS) == str(target.resolve())
    nested = write(repo.root / "tracklists" / "gigs" / "friday.txt")
    assert m.repo_file("gigs/friday.txt", (".txt",), folder=m.TRACKLISTS) == str(nested.resolve())


def test_an_existing_exact_path_wins_over_the_folder(repo):
    top = write(repo.root / "set.txt")
    write(repo.root / "tracklists" / "set.txt")
    assert m.repo_file("set.txt", (".txt",), folder=m.TRACKLISTS) == str(top.resolve())
    plan = write(repo.root / "plans" / "a.plan.json")
    assert m.repo_file("plans/a.plan.json", (".json",), folder=m.PLANS) == str(plan.resolve())
    assert m.repo_file(str(plan), (".json",), folder=m.PLANS) == str(plan.resolve())


@pytest.mark.parametrize("bad", ["../evil.txt", "tracklists/../../evil.txt"])
def test_outside_the_repo_is_refused_as_before(repo, bad):
    write(repo.outside / "evil.txt")
    with pytest.raises(m.ToolInputError, match="is outside the dj-librarian folder"):
        m.repo_file(bad, (".txt",), folder=m.TRACKLISTS)
    with pytest.raises(m.ToolInputError, match="is outside the dj-librarian folder"):
        m.repo_file(str(repo.outside / "evil.txt"), (".txt",), folder=m.TRACKLISTS)


def test_a_name_found_nowhere_says_where_it_looked(repo):
    with pytest.raises(m.ToolInputError) as found:
        m.repo_file("set.txt", (".txt",), folder=m.TRACKLISTS)
    assert str(found.value) == "'set.txt' not found: looked in tracklists/ and the repo root."
    assert "does not exist" not in str(found.value)
    with pytest.raises(m.ToolInputError, match="looked in the repo root"):
        m.repo_file("tree.yaml", (".yaml",))  # a tool without a default folder
    with pytest.raises(m.ToolInputError, match="no file at that path"):
        m.repo_file(str(repo.root / "plans" / "gone.plan.json"), (".json",), folder=m.PLANS)


def test_the_wrong_type_is_still_refused_first(repo):
    write(repo.root / "tracklists" / "notes.env")
    with pytest.raises(m.ToolInputError, match="expected one of .txt"):
        m.repo_file("notes.env", (".txt",), folder=m.TRACKLISTS)


def _env_behind(monkeypatch, link):
    """`link` resolves to the repo's .env, as a file symlink would (os.symlink needs a privilege
    on Windows, so the link is emulated through Path.resolve)."""
    real_resolve = Path.resolve
    target = link.parent.parent / ".env"

    def resolve(self, strict=False):
        done = real_resolve(self, strict)
        return real_resolve(target) if done == real_resolve(link) else done

    monkeypatch.setattr(Path, "resolve", resolve)
    return target


def test_a_name_in_the_folder_that_resolves_to_another_type_is_refused_like_the_exact_path(repo, monkeypatch):
    link = write(repo.root / "tracklists" / "set.txt")
    write(repo.root / ".env", "SPOTIFY_CLIENT_SECRET=x")
    _env_behind(monkeypatch, link)
    with pytest.raises(m.ToolInputError, match="expected one of .txt"):
        m.repo_file("tracklists/set.txt", (".txt", ".md"), folder=m.TRACKLISTS)
    with pytest.raises(m.ToolInputError) as found:
        m.repo_file("set.txt", (".txt", ".md"), folder=m.TRACKLISTS)
    assert "not found: looked in tracklists/ and the repo root" in str(found.value)


def test_a_real_symlink_to_another_type_is_refused(repo):
    target = write(repo.root / ".env", "SPOTIFY_CLIENT_SECRET=x")
    link = repo.root / "tracklists" / "set.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test make a symlink")
    with pytest.raises(m.ToolInputError):
        m.repo_file("set.txt", (".txt", ".md"), folder=m.TRACKLISTS)


# -- library_file --------------------------------------------------------------------------------


def test_library_file_looks_in_the_folder_of_the_library_then_of_the_repo(repo):
    export = write(repo.library / "exports" / "2026-10-20-collection.xml")
    assert m.library_file("2026-10-20-collection.xml", (".xml",), folder=m.EXPORTS) == str(export.resolve())
    in_repo = write(repo.root / "exports" / "old.xml")
    assert m.library_file("old.xml", (".xml",), folder=m.EXPORTS) == str(in_repo.resolve())
    top = write(repo.library / "2026-10-20-collection.xml")  # an exact path wins
    assert m.library_file("2026-10-20-collection.xml", (".xml",), folder=m.EXPORTS) == str(top.resolve())


def test_library_file_not_found_names_the_folder_and_both_roots(repo):
    with pytest.raises(m.ToolInputError) as found:
        m.library_file("missing.xml", (".xml",), folder=m.EXPORTS)
    text = str(found.value)
    assert text.startswith("'missing.xml' not found: looked in exports/ and the top of ")
    assert str(repo.library.resolve()) in text and str(repo.root.resolve()) in text
    with pytest.raises(m.ToolInputError, match="outside the dj-library folder"):
        m.library_file("../elsewhere.xml", (".xml",), folder=m.EXPORTS)


# -- the tools -----------------------------------------------------------------------------------


TOOLS = {  # tool -> (call with a bare name, the folder, the file's name)
    "dj_build_preview": (lambda name: m.dj_build_preview(name), "tracklists", "set.txt"),
    "dj_build_apply": (lambda name: m.dj_build_apply(name, preview_id=PID), "tracklists", "set.txt"),
    "dj_apply_preview": (lambda name: m.dj_apply_preview(name), "plans", "a.plan.json"),
    "dj_apply_write": (lambda name: m.dj_apply_write(name, preview_id=PID, power_mode=True), "plans", "a.plan.json"),
    "dj_tidy_apply_preview": (lambda name: m.dj_tidy_apply_preview(name), "plans", "t.plan.json"),
    "dj_tidy_apply": (lambda name: m.dj_tidy_apply(name, preview_id=PID), "plans", "t.plan.json"),
    "dj_tidy_undo_preview": (lambda name: m.dj_tidy_undo_preview(name), "plans", "t.plan.json"),
    "dj_tidy_undo": (lambda name: m.dj_tidy_undo(name, preview_id=PID), "plans", "t.plan.json"),
}


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_each_file_tool_resolves_a_bare_name_in_its_folder(repo, calls, tool):
    call, folder, name = TOOLS[tool]
    answer = json.loads(call(name))
    # repo_file names "the repo root"; library_file (sync plans and tracklists, W-25) names both roots
    assert answer["ok"] is False and answer["error"].startswith(f"{name!r} not found: looked in {folder}/ and ")
    assert calls == []  # refused before anything ran
    target = write(repo.root / folder / name, "{}")
    assert json.loads(call(name))["ok"] is True
    assert calls[-1][-1] == str(target.resolve())


def test_inspect_resolves_a_bare_export_name(repo, calls):
    export = write(repo.library / "exports" / "2026-10-20-collection.xml")
    assert json.loads(m.dj_library_inspect("2026-10-20-collection.xml"))["ok"] is True
    assert calls[-1][-1] == str(export.resolve())


def test_each_description_shows_one_example():
    tools = {t.name: " ".join(t.description.split()) for t in asyncio.run(m.server.list_tools())}
    for name in ("dj_build_preview", "dj_build_apply"):
        assert '"set.txt" -> tracklists/set.txt' in tools[name], name
    for name in ("dj_apply_preview", "dj_tidy_apply_preview", "dj_tidy_undo_preview", "dj_apply_write",
                 "dj_tidy_apply", "dj_tidy_undo"):
        assert "a bare name is looked up" in tools[name], name
        example = re.search(r'"([\w.-]+\.plan\.json)" -> plans/([\w.-]+\.plan\.json)', tools[name])
        assert example and example.group(1) == example.group(2), name
    assert '"2026-10-20-collection.xml" -> exports/2026-10-20-collection.xml' in tools["dj_library_inspect"]
    assert "set.txt -> tracklists/set.txt" in m.server.instructions
