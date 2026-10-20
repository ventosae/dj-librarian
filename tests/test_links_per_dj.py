"""R-802: the inbox loop for any DJ, with links.yaml in their own dj-library folder.

The loop pull -> match -> plan -> apply (dry-run) -> wishlist runs with the repo paths patched
to an empty folder: nothing reads or writes the repo. Spotify is a MockTransport, rekordbox the
synthetic library of tests/xml_fixtures.py. No network, no real master.db.
"""

from __future__ import annotations

import functools
import json
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner
from xml_fixtures import fake_db

from dj import cli, intake, libfolder, safety, spotify
from dj import mcp_server as m

runner = CliRunner()
REAL_PATHS = intake.Paths
REAL_SPOTIFY = spotify.Spotify
CRATE = "House/1.1_warm_up"  # fixture playlist: tracks 8, 21, 10, 11
SLUG = "House_1.1_warm_up"
PLAYLIST_ID = "4iNbOxPl4yLiStIdAbCdEf"  # 22 characters, invented


def item(uri, name, artists, ms, isrc=None, label=None):
    album = {"name": "Some Album"} | ({"label": label} if label else {})
    track = {"type": "track", "uri": uri, "name": name, "duration_ms": ms,
             "artists": [{"name": a} for a in artists], "album": album}
    if isrc:
        track["external_ids"] = {"isrc": isrc}
    return {"added_at": "2026-10-01T00:00:00Z", "item": track}


ROWS = [
    item("spotify:track:p1", "Open Plan", ["Tessa Quorum"], 213_000, isrc="ZZA011700009"),  # PROPOSE (9)
    item("spotify:track:c1", "Concrete Garden", ["Dub Atelier"], 250_000),  # IN_CRATE (10)
    item("spotify:track:a1", "Sunday Sermon - Extended Mix", ["Okoro Lane"], 217_000),  # AMBIGUOUS (1)
    item("spotify:track:m1", "Quiet Machinery", ["Fennel Arcade"], 301_000, label="Harbour Light Records"),
    item("spotify:track:m2", "Two/Three (Dub?)", ["Rook & Ash", "Vey"], 280_000),
]


def handler_for(requests):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.spotify.com"
        path = request.url.path
        if path == "/v1/me/playlists":
            return httpx.Response(200, json={"items": [{"id": PLAYLIST_ID, "name": "warmup_inbox"}],
                                             "next": None})
        if path == f"/v1/playlists/{PLAYLIST_ID}/items":
            return httpx.Response(200, json={"items": ROWS, "next": None})
        return httpx.Response(404, json={"error": {"status": 404}})

    return handler


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An empty stand-in for the repo. intake.Paths() (the repo layout) fails the test."""
    empty = tmp_path / "repo"
    empty.mkdir()
    for module in (safety, intake, libfolder, spotify, m):
        monkeypatch.setattr(module, "REPO_ROOT", empty)

    def library_paths_only(root=None, library=False, carry_from=None):
        if root is None:
            pytest.fail("the repo layout was used although the library folder has links")
        return REAL_PATHS(root, library, carry_from)

    monkeypatch.setattr(intake, "Paths", library_paths_only)
    return empty


@pytest.fixture
def lib(tmp_path, monkeypatch):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="windows", today=date(2026, 10, 20))
    (root / "links.yaml").write_text(f"- spotify: warmup_inbox\n  crate: {CRATE}\n", encoding="utf-8")
    monkeypatch.setenv("DJ_LIBRARY", str(root))
    return root


@pytest.fixture
def world(monkeypatch):
    """Fake rekordbox (read sessions only) and a Spotify behind a MockTransport."""
    state = {"writes": [], "requests": []}

    @contextmanager
    def fake_open_db(write=False, db_path=None):
        state["writes"].append(write)
        yield fake_db()

    monkeypatch.setattr(safety, "open_db", fake_open_db)
    def get_token(scopes):
        state["scopes"] = scopes
        return "tok"

    monkeypatch.setattr(spotify, "get_token", get_token)
    client = httpx.Client(transport=httpx.MockTransport(handler_for(state["requests"])))
    monkeypatch.setattr(spotify, "Spotify", lambda token: REAL_SPOTIFY(token, client))
    return state


def repo_paths(repo):
    """intake.Paths with `repo` standing in for the repo root (Paths() = the repo layout)."""

    def paths(root=None, library=False, carry_from=None):
        return REAL_PATHS(repo if root is None else root, library, carry_from)

    return paths


def run(*args):
    result = runner.invoke(cli.app, [str(a) for a in args])
    return result, (json.loads(result.output) if result.exit_code == 0 and "--json" in args else None)


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# -- where the files go --------------------------------------------------------------------


def test_library_with_a_link_is_used_and_its_machine_state_sits_in_cache(lib):
    paths = intake.default_paths()
    assert (paths.root, paths.library) == (lib.resolve(), True)
    assert paths.links == lib.resolve() / "links.yaml"
    assert paths.plans == lib.resolve() / "plans" and paths.wishlist == lib.resolve() / "wishlist"
    assert paths.reports == lib.resolve() / "reports" / "apply"  # the DJ reads it: visible
    cache = lib.resolve() / ".cache"
    assert paths.inbox == cache / "inbox"
    assert (paths.cache, paths.declined) == (cache / "state" / "match_cache.json", cache / "state" / "declined.json")


@pytest.mark.parametrize("text", [None, libfolder.LINKS_TEXT, "[]\n", "# only a comment\n"])
def test_without_a_link_in_the_library_the_repo_layout_stays(tmp_path, monkeypatch, text):
    root = tmp_path / "dj-library"
    root.mkdir()
    if text is not None:
        (root / "links.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setenv("DJ_LIBRARY", str(root))
    monkeypatch.setattr(intake, "Paths", functools.partial(REAL_PATHS, tmp_path / "repo"))
    paths = intake.default_paths()
    assert (paths.root, paths.library) == (tmp_path / "repo", False)
    assert paths.inbox == tmp_path / "repo" / "inbox"  # exactly the old layout
    assert paths.cache == tmp_path / "repo" / "state" / "match_cache.json"


def test_tests_never_see_the_library_folder_of_the_machine_they_run_on():
    # tests/conftest.py points DJ_LIBRARY at a folder that does not exist (real data stays out)
    assert not libfolder.configured_root().exists()
    assert intake.default_paths().library is False


def test_an_unusable_library_setting_falls_back_to_the_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(intake.libfolder, "configured_root",
                        lambda: (_ for _ in ()).throw(libfolder.LibraryFolderError("too wide")))
    monkeypatch.setattr(intake, "Paths", functools.partial(REAL_PATHS, tmp_path))
    assert intake.default_paths().library is False


@pytest.mark.parametrize(("data", "error"), [
    ("- spotify: [unclosed\n".encode(), "not valid YAML"),
    # Notepad's ANSI save of a crate name with an accent
    ("- spotify: warmup_inbox\n  crate: Café/warm\n".encode("cp1252"), "not UTF-8"),
])
def test_a_broken_links_yaml_in_the_library_is_reported_not_skipped(lib, data, error, tmp_path, monkeypatch):
    repo = tmp_path / "repo"  # a repo with links of its own must not be used instead
    repo.mkdir()
    (repo / "links.yaml").write_text("- spotify: repo_inbox\n  crate: Repo/crate\n", encoding="utf-8")
    monkeypatch.setattr(intake, "Paths", repo_paths(repo))
    (lib / "links.yaml").write_bytes(data)
    paths = intake.default_paths()
    assert (paths.root, paths.library) == (lib.resolve(), True)
    with pytest.raises(intake.IntakeError, match=error) as info:
        intake.load_links(paths)
    assert str(lib.resolve() / "links.yaml") in str(info.value)
    result = runner.invoke(cli.app, ["pull", "warmup_inbox", "--json"])
    assert result.exit_code == cli.EXIT_ERROR and error in result.output
    assert "repo_inbox" not in result.output and "Traceback" not in result.output


def test_record_in_a_library_writes_machine_state_under_cache(lib):
    paths = intake.default_paths()
    plan = {"spotify": "warmup_inbox", "crate": CRATE, "items": [
        {"spotify": "a", "spotify_uri": "u0", "decision": "yes", "pick": "9"},
        {"spotify": "b", "spotify_uri": "u1", "decision": "no", "pick": None}]}
    report = intake.record(plan, paths.plans / "p.plan.json", [plan["items"][0]], paths)
    assert report.parent == lib.resolve() / "reports" / "apply"  # visible: the DJ reads it
    assert json.loads(report.read_text(encoding="utf-8"))["plan"] == "plans/p.plan.json"  # library-relative
    assert json.loads(paths.cache.read_text(encoding="utf-8")) == {"u0": "9"}
    assert (lib / ".cache" / "state" / "declined.json").is_file()
    assert ".cache/" in (lib / ".gitignore").read_text(encoding="utf-8")  # machine state stays out of git


# -- the loop with the repo removed --------------------------------------------------------


def test_the_loop_runs_from_the_library_folder_with_the_repo_empty(repo, lib, world):
    # pull: Spotify -> <library>/.cache/inbox/<crate>.json, read scopes only
    result, out = run("pull", "warmup_inbox", "--json")
    assert result.exit_code == 0, result.output
    assert out["pulled"][0]["tracks"] == 5
    inbox = lib / ".cache" / "inbox" / f"{SLUG}.json"
    assert inbox.is_file() and world["scopes"] == spotify.READ_SCOPES
    pulled = json.loads(inbox.read_text(encoding="utf-8"))
    assert pulled["tracks"][3]["label"] == "Harbour Light Records"
    assert [r.url.path for r in world["requests"]] == ["/v1/me/playlists", f"/v1/playlists/{PLAYLIST_ID}/items"]

    # match: counts from the last pull, nothing written
    before = files(lib)
    result, out = run("match", "warmup_inbox", "--json")
    assert result.exit_code == 0, result.output
    assert out["counts"] == {"IN_CRATE": 1, "PROPOSE": 1, "AMBIGUOUS": 1, "MISSING": 2, "DECLINED": 0}
    assert files(lib) == before

    # plan: plans/ and wishlist/ in the library, machine paths kept out of git
    result, out = run("plan", "warmup_inbox", "--json")
    assert result.exit_code == 0, result.output
    plan_path = lib.resolve() / "plans" / f"{date.today().isoformat()}-{SLUG}.plan.json"
    assert out["plan"] == str(plan_path) and plan_path.is_file()
    assert out["wishlist"] == str(lib.resolve() / "wishlist" / f"{SLUG}.md")
    assert "*.plan.json" in (lib / "plans" / ".gitignore").read_text(encoding="utf-8")
    assert intake.PLANS_IGNORE_LINE in (lib / ".gitignore").read_text(encoding="utf-8").splitlines()

    # the DJ says yes to the proposal; apply is a dry-run: one read session, no write
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for entry in plan["items"]:
        if entry["status"] == intake.PROPOSE:
            entry["decision"] = "yes"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    world["writes"].clear()
    result, out = run("apply", plan_path, "--json")
    assert result.exit_code == 0, result.output
    assert (out["applied"], out["would_add"], out["yes"]) == (False, 1, 1)
    assert world["writes"] == [False]

    # wishlist: the shopping list for the crate, with a log.md line
    result, out = run("wishlist", "shop", "warmup_inbox", "--json")
    assert result.exit_code == 0, result.output
    assert (out["missing"], out["file"]) == (2, f"wishlist/{SLUG}.shopping.md")
    assert out["log"] in (lib / "log.md").read_text(encoding="utf-8")

    # nothing touched the repo; everything the DJ reads sits in the library folder
    assert files(repo) == []
    visible = [f for f in files(lib) if not f.startswith(".cache/")]
    assert f"plans/{plan_path.name}" in visible and f"wishlist/{SLUG}.md" in visible
    assert f"wishlist/{SLUG}.shopping.md" in visible
    assert not any(f.startswith(("inbox/", "state/")) for f in files(lib))
    assert all(r.method == "GET" for r in world["requests"])  # Spotify only read


def test_status_names_the_library_links_file(repo, lib, world, monkeypatch, tmp_path):
    monkeypatch.setattr(safety, "find_master_db", lambda: tmp_path / "master.db")
    (tmp_path / "master.db").write_bytes(b"")  # dj status copies it into a snapshot first (R-202)
    monkeypatch.setattr(safety, "rekordbox_running", lambda: False)
    assert run("pull", "warmup_inbox", "--json")[0].exit_code == 0
    result, out = run("status", "--json")
    assert result.exit_code == 0, result.output
    assert out["links_file"] == str(lib.resolve() / "links.yaml")
    assert out["links"][0]["counts"]["MISSING"] == 2 and out["links"][0]["last_pull"]


def test_pull_of_a_playlist_the_app_may_not_read_says_what_to_do(repo, lib, world, monkeypatch):
    def forbidden(request):
        if request.url.path == "/v1/me/playlists":
            return httpx.Response(200, json={"items": [{"id": PLAYLIST_ID, "name": "warmup_inbox"}]})
        return httpx.Response(403, json={"error": {"status": 403, "message": "Forbidden"}})

    client = httpx.Client(transport=httpx.MockTransport(forbidden))
    monkeypatch.setattr(spotify, "Spotify", lambda token: REAL_SPOTIFY(token, client))
    result, _ = run("pull", "warmup_inbox", "--json")
    assert result.exit_code == cli.EXIT_ERROR
    assert "own or collaborate on" in result.output and "Traceback" not in result.output
    assert not (lib / ".cache" / "inbox").exists()


# -- MCP: files from the library folder ------------------------------------------------------


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    return seen


PID = "0123456789ab"  # a well-formed preview id; the CLI run is faked here (W-21 gate tested elsewhere)

def test_mcp_plan_and_tracklist_files_may_live_in_the_library(repo, lib, calls, tmp_path):
    plan = lib / "plans" / "2026-10-20-x.plan.json"
    plan.parent.mkdir()
    plan.write_text("{}", encoding="utf-8")
    tracklist = lib / "crates" / "saturday.txt"
    tracklist.write_text("A - B\n", encoding="utf-8")
    outside = tmp_path / "elsewhere.plan.json"
    outside.write_text("{}", encoding="utf-8")

    assert json.loads(m.dj_apply_preview("plans/2026-10-20-x.plan.json"))["ok"] is True
    assert calls[-1][3:] == ["apply", "--json", "--", str(plan.resolve())]
    assert json.loads(m.dj_apply_write(str(plan), preview_id=PID, power_mode=True))["ok"] is True
    assert calls[-1][3:] == ["apply", "--apply", "--power-mode", "--preview-id", PID, "--json", "--",
                             str(plan.resolve())]
    assert json.loads(m.dj_build_preview("crates/saturday.txt"))["ok"] is True
    assert calls[-1][3:] == ["build", "--json", "--", str(tracklist.resolve())]
    n = len(calls)
    for bad in (str(outside), "../elsewhere.plan.json"):
        assert json.loads(m.dj_apply_write(bad, preview_id=PID, power_mode=True))["ok"] is False
    assert len(calls) == n  # nothing ran for a file outside both folders


def test_mcp_repo_plans_still_work(repo, calls, tmp_path, monkeypatch):
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path / "no-library"))
    plan = repo / "plans" / "2026-10-20-x.plan.json"
    plan.parent.mkdir()
    plan.write_text("{}", encoding="utf-8")
    assert json.loads(m.dj_apply_preview("plans/2026-10-20-x.plan.json"))["ok"] is True
    assert calls[-1][-1] == str(plan.resolve())


def test_mcp_repo_files_still_work_when_the_library_setting_is_unusable(repo, calls, tmp_path, monkeypatch):
    """DJ_LIBRARY pointing at the home folder: the CLI falls back to the repo, so must MCP."""
    home = tmp_path / "home" / "someone"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("DJ_LIBRARY", str(home))
    plan = repo / "plans" / "2026-10-20-x.plan.json"
    plan.parent.mkdir()
    plan.write_text("{}", encoding="utf-8")
    tracklist = repo / "tracklists" / "saturday.txt"
    tracklist.parent.mkdir()
    tracklist.write_text("A - B\n", encoding="utf-8")

    assert intake.library_links_root() is None  # the CLI side: default_paths() = the repo layout
    for tool, arg, target in ((m.dj_apply_preview, "plans/2026-10-20-x.plan.json", plan),
                              (lambda a: m.dj_apply_write(a, preview_id=PID, power_mode=True), str(plan), plan),
                              (m.dj_build_preview, "tracklists/saturday.txt", tracklist),
                              (lambda a: m.dj_build_apply(a, preview_id=PID), "tracklists/saturday.txt", tracklist)):
        answer = json.loads(tool(arg))
        assert answer["ok"] is True, (tool.__name__, answer)
        assert calls[-1][-1] == str(target.resolve())

    n = len(calls)
    outside = tmp_path / "elsewhere.plan.json"
    outside.write_text("{}", encoding="utf-8")
    for bad in (str(outside), "plans/missing.plan.json"):
        answer = json.loads(m.dj_apply_preview(bad))
        assert answer["ok"] is False
        assert "library folder setting is not used" in answer["error"] and "DJ_LIBRARY" in answer["error"]
    assert len(calls) == n  # nothing ran


# -- the switch from the repo: the DJ's declined list and match memory come along -----------


def test_the_repo_declined_list_and_match_memory_carry_over_to_the_library(repo, lib, world):
    state = repo / "state"
    state.mkdir()
    declined = [{"crate": CRATE, "spotify_uri": "spotify:track:p1", "spotify": "Tessa Quorum - Open Plan",
                 "date": "2026-09-01"}]
    (state / "declined.json").write_text(json.dumps(declined), encoding="utf-8")
    (state / "match_cache.json").write_text(json.dumps({"spotify:track:a1": "1"}), encoding="utf-8")  # an AMBIGUOUS pick
    before = {p.name: p.read_bytes() for p in state.iterdir()}

    assert run("pull", "warmup_inbox", "--json")[0].exit_code == 0
    paths = intake.default_paths()
    assert paths.carry_from == repo and paths.carried_state() == ["match_cache.json", "declined.json"]
    result, out = run("match", "warmup_inbox", "--json")
    assert result.exit_code == 0, result.output
    # declined stays declined, the remembered pick is proposed again, nothing asked twice
    assert out["counts"] == {"IN_CRATE": 1, "PROPOSE": 1, "AMBIGUOUS": 0, "MISSING": 2, "DECLINED": 1}

    # the first apply writes the library's own copies, with the repo entries in them
    plan = {"spotify": "warmup_inbox", "crate": CRATE, "items": [
        {"spotify": "Fennel Arcade - Quiet Machinery", "spotify_uri": "spotify:track:m1", "decision": "no", "pick": None}]}
    intake.record(plan, lib / "plans" / "p.plan.json", [], paths)
    carried = json.loads(paths.declined.read_text(encoding="utf-8"))
    assert [d["spotify_uri"] for d in carried] == ["spotify:track:p1", "spotify:track:m1"]
    assert json.loads(paths.cache.read_text(encoding="utf-8")) == {"spotify:track:a1": "1"}
    assert paths.carried_state() == []
    assert {p.name: p.read_bytes() for p in state.iterdir()} == before  # the repo files only read

    result, out = run("match", "warmup_inbox", "--json")
    assert out["counts"]["DECLINED"] == 2 and out["counts"]["PROPOSE"] == 1


def test_status_says_when_the_repo_state_is_still_in_use(repo, lib, world, monkeypatch, tmp_path):
    monkeypatch.setattr(safety, "find_master_db", lambda: tmp_path / "master.db")
    (tmp_path / "master.db").write_bytes(b"")  # dj status copies it into a snapshot first (R-202)
    monkeypatch.setattr(safety, "rekordbox_running", lambda: False)
    result, out = run("status", "--json")
    assert result.exit_code == 0, result.output
    assert out["state_from_repo"] == []
    (repo / "state").mkdir()
    (repo / "state" / "declined.json").write_text("[]", encoding="utf-8")
    result, out = run("status", "--json")
    assert out["state_from_repo"] == ["declined.json"]
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0, result.output
    assert "declined.json read from the repo's state/" in result.output


def test_the_library_state_wins_once_it_exists(tmp_path):
    repo, root = tmp_path / "repo", tmp_path / "lib"
    (repo / "state").mkdir(parents=True)
    (repo / "state" / "declined.json").write_text('[{"crate": "a", "spotify_uri": "old"}]', encoding="utf-8")
    paths = REAL_PATHS(root, library=True, carry_from=repo)
    assert paths.state_source(paths.declined) == repo / "state" / "declined.json"
    paths.declined.parent.mkdir(parents=True)
    paths.declined.write_text("[]", encoding="utf-8")
    assert paths.state_source(paths.declined) == paths.declined
    assert REAL_PATHS(root, library=True).state_source(paths.cache) == paths.cache  # no repo to carry from
    assert REAL_PATHS(repo).carried_state() == []  # the repo layout carries nothing


# -- plans hold local file paths: kept out of git even with a DJ-owned plans/.gitignore ------


def test_a_plan_adds_its_ignore_line_to_the_library_gitignore(lib):
    (lib / "plans").mkdir()
    own = "# my own rules\n*.bak\n"
    (lib / "plans" / ".gitignore").write_text(own, encoding="utf-8")
    top_before = (lib / ".gitignore").read_text(encoding="utf-8")
    paths = intake.default_paths()
    link = intake.Link("warmup_inbox", CRATE)
    intake.write_plan(link, [], set(), paths)
    intake.write_plan(link, [], set(), paths)  # twice: the line is added once
    top = (lib / ".gitignore").read_text(encoding="utf-8")
    assert top.startswith(top_before)  # add only: the DJ's lines stay as they were
    assert top.splitlines().count(intake.PLANS_IGNORE_LINE) == 1
    assert (lib / "plans" / ".gitignore").read_text(encoding="utf-8") == own  # never overwritten


def test_the_repo_layout_writes_no_gitignore(tmp_path):
    paths = REAL_PATHS(tmp_path)
    intake.write_plan(intake.Link("warmup_inbox", CRATE), [], set(), paths)
    assert not (tmp_path / ".gitignore").exists() and not (tmp_path / "plans" / ".gitignore").exists()


def test_the_apply_report_never_names_an_absolute_path_in_the_library(lib, tmp_path):
    paths = intake.default_paths()
    plan = {"spotify": "warmup_inbox", "crate": CRATE, "items": []}
    outside = tmp_path / "elsewhere" / "2026-10-20-x.plan.json"
    report = json.loads(intake.record(plan, outside, [], paths).read_text(encoding="utf-8"))
    assert report["plan"] == "2026-10-20-x.plan.json"  # a plan from outside: its name only
    repo_report = intake.record(plan, outside, [], REAL_PATHS(tmp_path / "repo"))
    assert json.loads(repo_report.read_text(encoding="utf-8"))["plan"] == str(outside)  # repo layout as before
    assert repo_report.parent == tmp_path / "repo" / "reports"
