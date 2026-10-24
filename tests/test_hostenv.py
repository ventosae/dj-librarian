"""W-34 (D-28): what the host tells the engine, and where the engine keeps its files.

`dj.hostenv` reads the extension's settings (DJ_LIBRARY, SPOTIFY_CLIENT_ID/SECRET, DJ_POWER_MODE,
DJ_ENGINE): empty or an unsubstituted `${...}` is unset. In the bundle (DJ_ENGINE=mcpb) the state
that must outlive an update goes to `<dj-library>/.cache/engine/`, reports to `<dj-library>/reports/`,
and `~/.dj-librarian/` without a usable library folder; a clone keeps every path it had. Config
files are read from the library folder first, the repo as the clone's fallback.

Module constants are computed at import, so the bundle's paths are checked in a fresh Python
(`probe`); the functions read the environment at call time and are checked in place.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dj import hostenv, intake, libfolder, safety, spotify
from dj.tidy import config as tidy_config

REPO = Path(__file__).resolve().parents[1]
HOST_VARS = ("DJ_ENGINE", "DJ_LIBRARY", "DJ_POWER_MODE", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET")
SECRET = "s3cr3t-value-never-printed"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A made-up home folder: Path.home() reads HOME on Mac/Linux, USERPROFILE on Windows."""
    path = tmp_path / "home" / "someone"
    path.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


@pytest.fixture
def bundle(monkeypatch, home):
    monkeypatch.setenv("DJ_ENGINE", "mcpb")
    return home


@pytest.fixture
def lib(tmp_path, monkeypatch):
    root = tmp_path / "dj-library"
    root.mkdir()
    monkeypatch.setenv("DJ_LIBRARY", str(root))
    return root.resolve()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A made-up repo root for hostenv (config fallback, the clone's library-path file)."""
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(hostenv, "REPO_ROOT", root)
    return root


# -- values --------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   ", "${user_config.library_folder}", " ${user_config.x} ",
                                 "C:/x/${user_config.library_folder}"])
def test_empty_or_unsubstituted_values_are_unset(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("DJ_LIBRARY", raising=False)
    else:
        monkeypatch.setenv("DJ_LIBRARY", raw)
    assert hostenv.env_value("DJ_LIBRARY") is None


def test_a_value_is_stripped(monkeypatch):
    monkeypatch.setenv("DJ_LIBRARY", "  /music/dj-library \n")
    assert hostenv.env_value("DJ_LIBRARY") == "/music/dj-library"


@pytest.mark.parametrize(("raw", "expected"), [
    ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True), (" True ", True),
    ("false", False), ("False", False), ("0", False), ("no", False), ("off", False),
    (None, None), ("", None), ("${user_config.power_mode}", None),
])
def test_power_mode_setting(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("DJ_POWER_MODE", raising=False)
    else:
        monkeypatch.setenv("DJ_POWER_MODE", raw)
    assert hostenv.power_mode_setting() is expected
    assert hostenv.power_mode_refusal() == (hostenv.POWER_MODE_OFF if expected is False else None)


@pytest.mark.parametrize("raw", ["maybe", "2", "enabled"])
def test_a_power_mode_that_is_neither_true_nor_false_is_refused_in_one_line(monkeypatch, raw):
    monkeypatch.setenv("DJ_POWER_MODE", raw)
    with pytest.raises(hostenv.HostSettingError) as info:
        hostenv.power_mode_setting()
    text = str(info.value)
    assert "\n" not in text and "DJ_POWER_MODE" in text and raw in text
    assert hostenv.power_mode_refusal() == text


def test_power_mode_off_names_the_engine_settings_in_one_line():
    assert hostenv.POWER_MODE_OFF.startswith("power mode is off in the engine settings")
    assert hostenv.POWER_MODE_UNSET.startswith("power mode is off")
    assert "engine settings" in hostenv.POWER_MODE_UNSET
    assert "\n" not in hostenv.POWER_MODE_OFF + hostenv.POWER_MODE_UNSET


@pytest.mark.parametrize(("raw", "refusal"), [
    (None, "unset"), ("", "unset"), ("   ", "unset"), ("${user_config.power_mode}", "unset"),
    ("false", "off"), ("0", "off"), ("true", None), ("1", None),
])
def test_the_bundle_fails_closed_when_no_power_mode_value_arrived(bundle, monkeypatch, raw, refusal):
    """The extension's form defaults Power mode to off: a value that did not reach the engine (a
    host that left it empty or did not fill in `${user_config.power_mode}`) refuses like off.
    True still only lifts the settings' veto: the call's own flag stays needed (write_gate)."""
    if raw is None:
        monkeypatch.delenv("DJ_POWER_MODE", raising=False)
    else:
        monkeypatch.setenv("DJ_POWER_MODE", raw)
    expected = {"unset": hostenv.POWER_MODE_UNSET, "off": hostenv.POWER_MODE_OFF, None: None}[refusal]
    assert hostenv.power_mode_refusal() == expected


@pytest.mark.parametrize(("raw", "expected"), [
    (None, False), ("", False), ("mcpb", True), ("MCPB", True), (" mcpb ", True), ("clone", False),
    ("${user_config.engine}", False),
])
def test_bundle_mode(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("DJ_ENGINE", raising=False)
    else:
        monkeypatch.setenv("DJ_ENGINE", raw)
    assert hostenv.bundle_mode() is expected


# -- where files go ------------------------------------------------------------------------------


def test_a_clone_keeps_the_repo_as_the_home_of_its_files(lib):
    assert hostenv.state_root() == hostenv.REPO_ROOT
    assert hostenv.home_root() == hostenv.REPO_ROOT
    assert hostenv.machine_root() == hostenv.REPO_ROOT
    assert hostenv.report_root() == hostenv.REPO_ROOT / "reports"
    assert hostenv.library_path_file() == hostenv.REPO_ROOT / "state" / "library-path.txt"


def test_the_bundle_keeps_its_state_in_the_library_folder(bundle, lib):
    assert hostenv.state_root() == lib / ".cache" / "engine"
    assert hostenv.home_root() == lib
    assert hostenv.report_root() == lib / "reports"
    assert hostenv.library_path_file() == bundle / ".dj-librarian" / "state" / "library-path.txt"
    # what belongs to this computer (the Spotify token) never follows a synced or mounted library
    assert hostenv.machine_root() == bundle / ".dj-librarian"


@pytest.mark.parametrize("setting", ["missing", "unset", "placeholder", "home"])
def test_the_bundle_without_a_usable_library_folder_uses_the_home_fallback(bundle, tmp_path, monkeypatch, setting):
    value = {"missing": str(tmp_path / "gone"), "placeholder": "${user_config.library_folder}",
             "home": str(bundle)}.get(setting)
    if value is None:
        monkeypatch.delenv("DJ_LIBRARY", raising=False)
    else:
        monkeypatch.setenv("DJ_LIBRARY", value)
    assert hostenv.state_root() == hostenv.home_root() == hostenv.machine_root() == bundle / ".dj-librarian"
    assert hostenv.report_root() == bundle / ".dj-librarian" / "reports"


def test_the_bundle_has_no_default_library_folder_in_its_install_folder(bundle, monkeypatch):
    monkeypatch.delenv("DJ_LIBRARY", raising=False)
    with pytest.raises(libfolder.LibraryFolderError, match="engine settings"):
        libfolder.configured_root()
    assert hostenv.configured_library() is None


def test_the_bundle_reads_a_library_folder_stored_by_dj_library_use(bundle, tmp_path, monkeypatch):
    monkeypatch.delenv("DJ_LIBRARY", raising=False)
    stored = tmp_path / "stored-lib"
    stored.mkdir()
    remembered = libfolder.remember_root(stored)
    assert remembered == stored.resolve()
    assert (bundle / ".dj-librarian" / "state" / "library-path.txt").read_text(encoding="utf-8").strip() == str(remembered)
    assert libfolder.configured_root() == stored.resolve()
    assert hostenv.state_root() == stored.resolve() / ".cache" / "engine"


def test_the_bundle_setting_wins_and_a_wide_one_is_refused_by_its_settings_name(bundle, monkeypatch):
    monkeypatch.setenv("DJ_LIBRARY", str(bundle))
    with pytest.raises(libfolder.LibraryFolderError, match=r"engine settings \(DJ_LIBRARY\)"):
        libfolder.configured_root()


@pytest.mark.parametrize("raw", ["", "   ", "${user_config.library_folder}"])
def test_an_empty_or_placeholder_dj_library_is_unset_not_a_path(monkeypatch, tmp_path, raw):
    """Today an unsubstituted placeholder would be refused (or used) as a path; now it is unset,
    so the next step decides: the stored folder, then the clone's default."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "state").mkdir(parents=True)
    monkeypatch.setattr(libfolder, "REPO_ROOT", fake_repo)
    monkeypatch.setenv("DJ_LIBRARY", raw)
    assert libfolder.configured_root() == (fake_repo / "dj-library").resolve()
    stored = tmp_path / "stored"
    (fake_repo / "state" / "library-path.txt").write_text(f"{stored}\n", encoding="utf-8")
    assert libfolder.configured_root() == stored.resolve()


def test_dj_library_use_reads_the_setting_the_same_way(monkeypatch, tmp_path):
    """`dj library use` checks a set DJ_LIBRARY before it stores anything: a placeholder is unset."""
    from typer.testing import CliRunner

    from dj import cli

    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    monkeypatch.setattr(libfolder, "REPO_ROOT", fake_repo)
    folder = tmp_path / "lib"
    folder.mkdir()
    (folder / "library.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    monkeypatch.setenv("DJ_LIBRARY", "${user_config.library_folder}")
    result = CliRunner().invoke(cli.app, ["library", "use", str(folder), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["library"] == data["in_use"] == str(folder.resolve())


# -- config files: the library folder first, the repo as the clone's fallback ---------------------


@pytest.mark.parametrize("name", ["tidy.yaml", "bases.yaml", "tree.yaml"])
def test_a_config_file_in_the_library_wins(repo, lib, name):
    (repo / name).write_text("repo\n", encoding="utf-8")
    (lib / name).write_text("library\n", encoding="utf-8")
    assert hostenv.config_file(name) == lib / name


@pytest.mark.parametrize("name", ["tidy.yaml", "bases.yaml", "tree.yaml"])
def test_the_repo_file_is_used_when_the_library_has_none(repo, lib, name):
    (repo / name).write_text("repo\n", encoding="utf-8")
    assert hostenv.config_file(name) == repo / name


def test_a_clone_without_either_file_names_the_repo(repo, lib):
    assert hostenv.config_file("tidy.yaml") == repo / "tidy.yaml"


def test_the_bundle_without_either_file_names_the_library_folder(repo, lib, bundle):
    assert hostenv.config_file("tidy.yaml") == lib / "tidy.yaml"  # never the install folder


@pytest.mark.parametrize("name", ["tidy.yaml", "bases.yaml", "tree.yaml"])
def test_the_bundle_never_reads_a_config_file_from_its_install_folder(repo, lib, bundle, name):
    """A stray file in the install folder (it holds only the shipped code) never supplies tidy
    write roots or a tree: the library folder's path, there or not, even with a fallback given."""
    (repo / name).write_text("install folder\n", encoding="utf-8")
    assert hostenv.config_file(name) == lib / name
    assert hostenv.config_file(name, fallback=repo / name) == lib / name


def test_the_bundle_without_a_library_folder_names_the_engine_settings(repo, bundle, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from dj import cli

    monkeypatch.delenv("DJ_LIBRARY", raising=False)
    (repo / "tidy.yaml").write_text(TIDY_TEXT.format(root=tmp_path.as_posix()), encoding="utf-8")
    with pytest.raises(hostenv.HostSettingError, match="engine settings"):
        hostenv.config_file("tidy.yaml")
    for call in (tidy_config.default_path, tidy_config.load_config, lambda: tidy_config.load_config("")):
        with pytest.raises(tidy_config.TidyError, match="engine settings"):
            call()
    with pytest.raises(hostenv.HostSettingError, match="engine settings"):
        cli._config_arg(Path("bases.yaml"))
    monkeypatch.chdir(repo)
    (repo / "bases.yaml").write_text("- playlist: from_the_install_folder\n", encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["tree", "--file", "bases.yaml"])
    assert result.exit_code == cli.EXIT_ERROR and result.stderr.startswith("ERROR No dj-library folder is set")


TIDY_TEXT = "roots: ['{root}']\nprofiles:\n  - name: cdj\n    formats: [mp3]\n    max_bit_depth: 24\n    sample_rates: [44100]\n"


def test_tidy_yaml_is_read_from_the_library_first_then_the_repo(repo, lib, tmp_path):
    music_lib, music_repo = tmp_path / "music-lib", tmp_path / "music-repo"
    music_lib.mkdir()
    music_repo.mkdir()
    (repo / "tidy.yaml").write_text(TIDY_TEXT.format(root=music_repo.as_posix()), encoding="utf-8")
    assert tidy_config.default_path() == repo / "tidy.yaml"
    assert tidy_config.load_config().roots == (music_repo,)
    (lib / "tidy.yaml").write_text(TIDY_TEXT.format(root=music_lib.as_posix()), encoding="utf-8")
    assert tidy_config.default_path() == lib / "tidy.yaml"
    cfg = tidy_config.load_config()
    assert cfg.roots == (music_lib,) and cfg.source == lib / "tidy.yaml"


def test_the_mcp_music_folder_check_reads_the_library_tidy_yaml(repo, lib, tmp_path):
    from dj import mcp_server as m

    music = tmp_path / "music-lib"
    (music / "house").mkdir(parents=True)
    (lib / "tidy.yaml").write_text(TIDY_TEXT.format(root=music.as_posix()), encoding="utf-8")
    assert m.music_folder(str(music / "house")) == str((music / "house").resolve())


def test_the_tree_command_reads_a_bare_tree_file_from_the_library_first(lib, tmp_path, monkeypatch):
    from dj import cli

    monkeypatch.chdir(tmp_path)
    (tmp_path / "bases.yaml").write_text("[]\n", encoding="utf-8")
    assert cli._config_arg(Path("bases.yaml")) == Path("bases.yaml")  # as before: from the working folder
    (lib / "bases.yaml").write_text("[]\n", encoding="utf-8")
    assert cli._config_arg(Path("bases.yaml")) == lib / "bases.yaml"
    absolute = tmp_path / "bases.yaml"
    assert cli._config_arg(absolute) == absolute  # an absolute path is taken as given


def test_the_tree_command_uses_the_library_tree_file(lib, tmp_path, monkeypatch):
    """`dj tree` (dry-run) with a bare name plans from the library folder's file."""
    from typer.testing import CliRunner

    from dj import cli

    monkeypatch.chdir(tmp_path)
    (tmp_path / "tree.yaml").write_text("- playlist: from_the_working_folder\n", encoding="utf-8")
    (lib / "tree.yaml").write_text("- playlist: from_the_library\n", encoding="utf-8")
    seen = []

    def load_tree(path):
        seen.append(Path(path))
        raise cli.tree_mod.TreeError("stop here")

    monkeypatch.setattr(cli.tree_mod, "load_tree", load_tree)
    result = CliRunner().invoke(cli.app, ["tree", "--file", "tree.yaml"])
    assert result.exit_code == cli.EXIT_ERROR and seen == [lib / "tree.yaml"]


# -- links.yaml and the inbox loop ----------------------------------------------------------------


def test_the_bundle_uses_the_library_layout_even_before_the_first_link(bundle, lib):
    (lib / "links.yaml").write_text(libfolder.LINKS_TEXT, encoding="utf-8")  # comments only
    paths = intake.default_paths()
    assert (paths.root, paths.library, paths.carry_from) == (lib, True, None)  # nothing carried from the install folder
    assert paths.links == lib / "links.yaml"


def test_the_bundle_without_a_library_folder_keeps_the_inbox_in_the_home_fallback(bundle, monkeypatch):
    monkeypatch.delenv("DJ_LIBRARY", raising=False)
    paths = intake.default_paths()
    assert (paths.root, paths.library) == (bundle / ".dj-librarian", False)


def test_tidy_files_go_to_the_library_in_the_bundle(bundle, lib):
    from dj.tidy import plan as tidy_plan

    paths = intake.tidy_paths()
    assert paths.plans == lib / "plans"
    assert paths.report_root / "tidy" == lib / "reports" / "tidy"
    # the undo records sit with the engine's other state (previews, backups), not the inbox's .cache/state
    assert tidy_plan.undo_path_for(Path("x.plan.json"), paths) == lib / ".cache" / "engine" / "state" / "tidy" / "x.undo.json"
    assert tidy_plan.undo_path_for(Path("x.plan.json"), paths).parent.parent.parent == hostenv.state_root()


def test_tidy_undo_records_without_a_library_folder_go_to_the_home_fallback(bundle, monkeypatch):
    from dj.tidy import plan as tidy_plan

    monkeypatch.delenv("DJ_LIBRARY", raising=False)
    paths = intake.tidy_paths()
    expected = bundle / ".dj-librarian" / "state" / "tidy" / "x.undo.json"
    assert tidy_plan.undo_path_for(Path("x.plan.json"), paths) == expected


def test_tidy_files_in_a_library_folder_stay_out_of_git(bundle, lib):
    """Plans and reports name music files by their paths (R-905): in the library folder their lines
    go into its .gitignore, added once, the DJ's own lines kept."""
    from dj.tidy import plan as tidy_plan
    from dj.tidy import report as tidy_report

    (lib / ".gitignore").write_text("my-own-line\n", encoding="utf-8")
    paths = intake.tidy_paths()
    written = tidy_plan.write_plan({"plan_id": "2026-10-24-tidy-all", "items": []}, paths)
    assert written == lib / "plans" / "2026-10-24-tidy-all.plan.json"
    assert (lib / "plans" / ".gitignore").is_file()
    tidy_report.keep_reports_out_of_git(paths)  # what the audit, apply-report and relocate writers call first
    tidy_report.keep_reports_out_of_git(paths)  # twice: added once
    lines = (lib / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "my-own-line"
    for line in (intake.PLANS_IGNORE_LINE, *tidy_report.REPORT_IGNORE_LINES):
        assert lines.count(line) == 1, line


def test_tidy_files_stay_in_the_repo_in_a_clone(lib):
    from dj.tidy import plan as tidy_plan

    paths = intake.tidy_paths()
    assert (paths.root, paths.library) == (intake.REPO_ROOT, False)
    assert paths.report_root / "tidy" == intake.REPO_ROOT / "reports" / "tidy"
    assert tidy_plan.undo_path_for(Path("x.plan.json"), paths) == intake.REPO_ROOT / "state" / "tidy" / "x.undo.json"


# -- Spotify keys: the environment, then the library's .env, then the repo's ----------------------


@pytest.fixture
def keys(tmp_path, monkeypatch):
    """A repo .env and a library .env with different keys; the environment holds none."""
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    monkeypatch.setattr(spotify, "REPO_ROOT", fake_repo)
    (fake_repo / ".env").write_text("SPOTIFY_CLIENT_ID=repo-id\nSPOTIFY_CLIENT_SECRET=repo-secret\n", encoding="utf-8")
    library = tmp_path / "dj-library"
    library.mkdir()
    monkeypatch.setenv("DJ_LIBRARY", str(library))
    return fake_repo, library


def test_the_environment_wins_and_no_file_is_needed(keys, monkeypatch):
    fake_repo, library = keys
    (fake_repo / ".env").unlink()
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", SECRET)
    env = spotify.load_env()
    assert (env["SPOTIFY_CLIENT_ID"], env["SPOTIFY_CLIENT_SECRET"]) == ("env-id", SECRET)


def test_the_library_env_file_comes_before_the_repos(keys):
    fake_repo, library = keys
    assert spotify.load_env()["SPOTIFY_CLIENT_ID"] == "repo-id"
    (library / ".env").write_text("SPOTIFY_CLIENT_ID=lib-id\nSPOTIFY_CLIENT_SECRET=lib-secret\n", encoding="utf-8")
    env = spotify.load_env()
    assert (env["SPOTIFY_CLIENT_ID"], env["SPOTIFY_CLIENT_SECRET"]) == ("lib-id", "lib-secret")


def test_one_key_in_the_environment_takes_the_other_from_a_file(keys, monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-id")
    env = spotify.load_env()
    assert (env["SPOTIFY_CLIENT_ID"], env["SPOTIFY_CLIENT_SECRET"]) == ("env-id", "repo-secret")


@pytest.mark.parametrize("raw", ["", "${user_config.spotify_client_id}"])
def test_an_empty_or_placeholder_key_in_the_environment_is_unset(keys, monkeypatch, raw):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", raw)
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", raw)
    assert spotify.load_env()["SPOTIFY_CLIENT_ID"] == "repo-id"


def test_missing_keys_in_a_clone_point_at_env(keys):
    fake_repo, _ = keys
    (fake_repo / ".env").unlink()
    with pytest.raises(spotify.SpotifyError, match=r"\.env"):
        spotify.load_env()


def test_missing_keys_in_the_bundle_point_at_the_engine_settings(keys, bundle, monkeypatch):
    fake_repo, _ = keys
    (fake_repo / ".env").unlink()
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", SECRET)  # the ID is missing
    with pytest.raises(spotify.SpotifyError) as info:
        spotify.load_env()
    text = str(info.value)
    assert "engine settings" in text and "Spotify client ID" in text and SECRET not in text
    assert "\n" not in text


def test_an_empty_key_in_a_file_never_echoes_the_other(keys):
    fake_repo, _ = keys
    (fake_repo / ".env").write_text(f"SPOTIFY_CLIENT_ID=\nSPOTIFY_CLIENT_SECRET={SECRET}\n", encoding="utf-8")
    with pytest.raises(spotify.SpotifyError) as info:
        spotify.load_env()
    assert SECRET not in str(info.value) and "SPOTIFY_CLIENT_ID" in str(info.value)


def test_a_library_env_without_the_keys_does_not_hide_the_repos(keys):
    """Each key comes from the first file that has a value for it: a library .env made for
    something else (or the scaffold's empty one) leaves the repo's keys in use."""
    fake_repo, library = keys
    (library / ".env").write_text("OTHER=1\n", encoding="utf-8")
    env = spotify.load_env()
    assert (env["SPOTIFY_CLIENT_ID"], env["SPOTIFY_CLIENT_SECRET"]) == ("repo-id", "repo-secret")
    (library / ".env").write_text("SPOTIFY_CLIENT_ID=lib-id\nSPOTIFY_CLIENT_SECRET=\n", encoding="utf-8")
    env = spotify.load_env()
    assert (env["SPOTIFY_CLIENT_ID"], env["SPOTIFY_CLIENT_SECRET"]) == ("lib-id", "repo-secret")


def test_an_empty_key_names_every_env_file_it_read_by_its_full_path(keys):
    fake_repo, library = keys
    (library / ".env").write_text(f"SPOTIFY_CLIENT_SECRET={SECRET}\n", encoding="utf-8")
    (fake_repo / ".env").write_text("SPOTIFY_CLIENT_ID=\n", encoding="utf-8")
    with pytest.raises(spotify.SpotifyError) as info:
        spotify.load_env()
    text = str(info.value)
    assert text.startswith("SPOTIFY_CLIENT_ID is empty in ") and SECRET not in text and "\n" not in text
    assert str(library.resolve() / ".env") in text and str(fake_repo / ".env") in text


def test_the_bundle_never_reads_the_env_file_in_its_install_folder(keys, bundle):
    """The repo .env (here with keys) is the install folder's in the extension: never read, so a
    stray file there cannot supply credentials. The library's .env still counts."""
    fake_repo, library = keys
    assert spotify.env_files() == [library.resolve() / ".env"]
    with pytest.raises(spotify.SpotifyError, match="engine settings") as info:
        spotify.load_env()
    assert "repo-" not in str(info.value)
    (library / ".env").write_text("SPOTIFY_CLIENT_ID=lib-id\nSPOTIFY_CLIENT_SECRET=lib-secret\n", encoding="utf-8")
    assert spotify.load_env()["SPOTIFY_CLIENT_ID"] == "lib-id"


def test_the_bundle_without_a_library_folder_reads_no_env_file(keys, bundle, monkeypatch):
    monkeypatch.delenv("DJ_LIBRARY")
    assert spotify.env_files() == []
    with pytest.raises(spotify.SpotifyError, match="Spotify client ID and Spotify client secret not set: add them"):
        spotify.load_env()


# -- master.db backups in the bundle's place are still verified (hard rule 3) ---------------------


BACKUP_RUN = """
    import datetime as dt
    import json
    import sys
    from pathlib import Path
    from dj import safety

    opened = []
    safety._verify_opens = opened.append  # pyrekordbox's open of the copy; the copy's hash is checked for real
    db_path = Path(sys.argv[1])
    done = safety.backup(db_path)
    out = {"backup_dir": str(safety.BACKUP_DIR), "copies": sorted(str(c) for c in done.files.values()),
           "db_copy": str(done.db_copy), "opened": [str(p) for p in opened],
           "changed": [str(p) for p in done.changed_sources()]}

    class Later(dt.datetime):  # a second backup with its own time stamp, so only the copy can fail
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2030, 1, 1)

    safety.datetime = Later
    safety.shutil.copy2 = lambda src, dst: Path(dst).write_bytes(b"truncated")
    try:
        safety.backup(db_path)
        out["truncated"] = "accepted"
    except safety.BackupError as exc:
        out["truncated"] = str(exc)
    print(json.dumps(out))
"""


def test_a_backup_in_the_bundle_folder_is_still_verified(tmp_path):
    """Hard rule 3 in the extension: `safety.backup` with the module's own BACKUP_DIR, as a bundle
    process computes it, copies into <dj-library>/.cache/engine/backups and checks every copy."""
    library = tmp_path / "dj-library"
    library.mkdir()
    db_path = tmp_path / "rb" / "master.db"
    db_path.parent.mkdir()
    db_path.write_bytes(b"not a real database")
    (db_path.parent / safety.PLAYLIST_XML).write_text("<MASTER_PLAYLIST/>", encoding="utf-8")
    got = json.loads(run_python(tmp_path, BACKUP_RUN, str(db_path), DJ_ENGINE="mcpb", DJ_LIBRARY=str(library)))
    folder = library.resolve() / ".cache" / "engine" / "backups"
    assert got["backup_dir"] == str(folder)
    assert len(got["copies"]) == 2 and all(Path(c).parent == folder and Path(c).is_file() for c in got["copies"])
    assert got["opened"] == [got["db_copy"]] and got["changed"] == []
    assert got["truncated"].startswith("Backup copy differs from source")


# -- every module constant, and a real `dj` run, in a fresh Python ---------------------------------


PROBE = """
    import json
    from pathlib import Path
    from dj import activity_log, analyze, build, hostenv, intake, libfolder, playlist_copy, push, safety, spotify
    from dj import write_gate
    from dj.tidy import config as tidy_config
    from dj.tidy import plan as tidy_plan

    inbox = intake.default_paths()
    tidy = intake.tidy_paths()
    print(json.dumps({
        "backups": str(safety.BACKUP_DIR),
        "previews": str(write_gate.STATE_DIR),
        "build_state": str(build.STATE_FILE),
        "push_state": str(push.STATE_FILE),
        "push_reports": str(push.REPORT_DIR),
        "copy_reports": str(playlist_copy.REPORT_DIR),
        "analyze_cache": str(analyze.CACHE_DIR),
        "analyze_reports": str(analyze.REPORT_DIR),
        "spotify_token": str(spotify.TOKEN_CACHE),
        "log_fallback": str(activity_log.REPO_DIR),
        "library_path_file": str(libfolder._state_file()),
        "tidy_yaml": str(tidy_config.DEFAULT_PATH),
        "inbox_root": str(inbox.root),
        "inbox_library": inbox.library,
        "carry_from": None if inbox.carry_from is None else str(inbox.carry_from),
        "tidy_plans": str(tidy.plans),
        "tidy_reports": str(tidy.report_root / "tidy"),
        "tidy_undo": str(tidy_plan.undo_path_for(Path("x.plan.json"), tidy)),
        "repo": str(safety.REPO_ROOT),
    }))
"""


def fresh_env(tmp_path: Path, **env: str) -> dict[str, str]:
    """The environment of a fresh `dj` process: none of the host settings but `env`, a made-up
    home folder (`probe-home`), and this checkout's src/ on the import path."""
    home = tmp_path / "probe-home"
    home.mkdir(exist_ok=True)
    clean = {k: v for k, v in os.environ.items() if k not in HOST_VARS}
    paths = [str(REPO / "src")] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    clean |= {"HOME": str(home), "USERPROFILE": str(home), "PYTHONPATH": os.pathsep.join(paths), "PYTHONUTF8": "1"}
    return clean | env


def run_python(tmp_path: Path, code: str, *args: str, **env: str) -> str:
    """stdout of `python -c <code> <args>` in a fresh process with these host settings."""
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(code), *args], cwd=tmp_path, capture_output=True,
                          text=True, encoding="utf-8", timeout=120, env=fresh_env(tmp_path, **env))
    assert done.returncode == 0, done.stderr
    return done.stdout


def probe(tmp_path: Path, **env: str) -> dict:
    """The constants a fresh `dj` process computes with exactly these host settings."""
    return json.loads(run_python(tmp_path, PROBE, **env)) | {"home": str(tmp_path / "probe-home")}


def test_a_clone_process_keeps_every_path_it_had(tmp_path):
    got = probe(tmp_path, DJ_LIBRARY=str(tmp_path / "no-library"))
    repo = Path(got["repo"])
    assert got == got | {
        "backups": str(repo / "backups"),
        "previews": str(repo / "state"),
        "build_state": str(repo / "state" / "build.json"),
        "push_state": str(repo / "state" / "push.json"),
        "push_reports": str(repo / "reports"),
        "copy_reports": str(repo / "reports"),
        "analyze_cache": str(repo / ".cache" / "library"),
        "analyze_reports": str(repo / "reports" / "library"),
        "spotify_token": str(repo / ".cache" / "spotify_token.json"),
        "log_fallback": str(repo),
        "library_path_file": str(repo / "state" / "library-path.txt"),
        "tidy_yaml": str(repo / "tidy.yaml"),
        "inbox_root": str(repo),
        "inbox_library": False,
        "carry_from": None,
        "tidy_plans": str(repo / "plans"),
        "tidy_reports": str(repo / "reports" / "tidy"),
        "tidy_undo": str(repo / "state" / "tidy" / "x.undo.json"),
    }


def test_a_bundle_process_keeps_nothing_in_its_install_folder(tmp_path):
    library = tmp_path / "dj-library"
    library.mkdir()
    got = probe(tmp_path, DJ_ENGINE="mcpb", DJ_LIBRARY=str(library), DJ_POWER_MODE="false")
    lib = library.resolve()
    state = lib / ".cache" / "engine"
    assert got == got | {
        "backups": str(state / "backups"),
        "previews": str(state / "state"),
        "build_state": str(state / "state" / "build.json"),
        "push_state": str(state / "state" / "push.json"),
        "push_reports": str(lib / "reports"),
        "copy_reports": str(lib / "reports"),
        "analyze_cache": str(state / ".cache" / "library"),
        "analyze_reports": str(lib / "reports" / "library"),
        # per computer, never in the (synced, mounted) library folder; it outlives an update too
        "spotify_token": str(Path(got["home"]) / ".dj-librarian" / ".cache" / "spotify_token.json"),
        "log_fallback": str(lib),  # log.md in the library folder even before it is set up
        "library_path_file": str(Path(got["home"]) / ".dj-librarian" / "state" / "library-path.txt"),
        "tidy_yaml": str(lib / "tidy.yaml"),
        "inbox_root": str(lib),
        "inbox_library": True,
        "carry_from": None,
        "tidy_plans": str(lib / "plans"),
        "tidy_reports": str(lib / "reports" / "tidy"),
        "tidy_undo": str(state / "state" / "tidy" / "x.undo.json"),
    }
    repo = Path(got["repo"])
    for key, value in got.items():
        if key not in ("repo", "home", "inbox_library", "carry_from"):
            assert not Path(value).is_relative_to(repo), (key, value)


def test_a_bundle_process_without_a_library_folder_uses_the_home_fallback(tmp_path):
    got = probe(tmp_path, DJ_ENGINE="mcpb", DJ_LIBRARY="${user_config.library_folder}")
    fallback = Path(got["home"]) / ".dj-librarian"
    assert got == got | {
        "backups": str(fallback / "backups"),
        "previews": str(fallback / "state"),
        "spotify_token": str(fallback / ".cache" / "spotify_token.json"),
        "push_reports": str(fallback / "reports"),
        "analyze_reports": str(fallback / "reports" / "library"),
        "log_fallback": str(fallback),
        "inbox_root": str(fallback),
        "inbox_library": False,
        "tidy_plans": str(fallback / "plans"),
        "tidy_undo": str(fallback / "state" / "tidy" / "x.undo.json"),
        "tidy_yaml": "None",  # no tidy.yaml default: load_config names the engine settings
    }


def test_a_bundle_cli_run_writes_under_the_library_folder_and_never_in_the_install_folder(tmp_path):
    """A real `dj` command in a bundle process: `dj tidy apply` (dry-run, no master.db, no audio
    file) reads the library's tidy.yaml by default and records its preview under
    <dj-library>/.cache/engine/state/previews; `dj library use` stores its path under
    ~/.dj-librarian. Nothing is created in the install folder (this checkout)."""
    library, music = tmp_path / "dj-library", tmp_path / "music"
    (library / "plans").mkdir(parents=True)
    music.mkdir()
    (library / "tidy.yaml").write_text(TIDY_TEXT.format(root=music.as_posix()), encoding="utf-8")
    plan = library / "plans" / "t.plan.json"
    plan.write_text(json.dumps({"kind": "tidy-plan", "plan_id": "t", "items": []}), encoding="utf-8")
    other = tmp_path / "other-library"
    other.mkdir()
    (other / "library.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    stored_in_repo = REPO / "state" / "library-path.txt"
    repo_before = (sorted(p.name for p in REPO.iterdir()), stored_in_repo.is_file() and stored_in_repo.read_bytes())
    env = fresh_env(tmp_path, DJ_ENGINE="mcpb", DJ_LIBRARY=str(library), DJ_POWER_MODE="false")

    def dj(*args: str) -> dict:
        done = subprocess.run([sys.executable, "-m", "dj.cli", *args], cwd=tmp_path, capture_output=True, text=True,
                              encoding="utf-8", timeout=120, env=env)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    pid = dj("tidy", "apply", "--json", "--", str(plan))["preview_id"]
    previews = library.resolve() / ".cache" / "engine" / "state" / "previews"
    assert [p.name for p in previews.iterdir()] == [f"{pid}.json"]
    assert not (REPO / "state" / "previews" / f"{pid}.json").exists()
    home = Path(env["HOME"])
    assert not (home / ".dj-librarian").exists()  # the library folder is usable: nothing in the fallback

    used = dj("library", "use", str(other), "--json")
    stored = home / ".dj-librarian" / "state" / "library-path.txt"
    assert used["stored_in"] == str(stored) and used["in_use"] == str(library.resolve())  # DJ_LIBRARY wins
    assert stored.read_text(encoding="utf-8").strip() == str(other.resolve())
    assert (sorted(p.name for p in REPO.iterdir()), stored_in_repo.is_file() and stored_in_repo.read_bytes()) == repo_before
