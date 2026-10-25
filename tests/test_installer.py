"""dj.installer and scripts/merge_desktop_config.py (W-35): the engine's entry in Claude Desktop's
config. Only mcpServers["dj-librarian"] changes; a backup comes first; the same entry twice writes
nothing; a malformed file is refused and left alone. Everything under tmp_path."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from dj import installer

REPO = Path(__file__).resolve().parents[1]
DAY = date(2026, 10, 25)
# what Claude Desktop writes (JSON.stringify(obj, null, 2)): two spaces, raw non-ASCII
OTHERS = {
    "globalShortcut": "Ctrl+Space",
    "mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\x\\Music"]}},
    "preferences": {"theme": "dark", "name": "Zoë", "ratio": 1.5},
}


@pytest.fixture
def setup(tmp_path):
    engine = tmp_path / "dj-librarian"
    engine.mkdir()
    (engine / "pyproject.toml").write_text("[project]\nname='dj-librarian'\n", encoding="utf-8")
    library = tmp_path / "dj-library"
    library.mkdir()
    (library / "library.yaml").write_text("schema: 1\n", encoding="utf-8")
    uv = tmp_path / "bin" / "uv"
    return {"config": tmp_path / "Claude" / installer.CONFIG_NAME, "uv": uv, "folder": engine, "library": library}


def merge(s, **kw):
    return installer.merge_desktop_config(s["config"], s["uv"], s["folder"], s["library"], today=DAY, **kw)


def ours(s, platform: str = sys.platform):
    power = "true" if platform == "win32" else "false"  # W-38: writes into rekordbox on Windows only (Q-35)
    return {"command": str(s["uv"]), "args": ["run", "--directory", str(s["folder"]), "--no-sync", "dj-mcp"],
            "env": {"UV_PROJECT_ENVIRONMENT": str(s["folder"] / ".venv"), "DJ_POWER_MODE": power,
                    "DJ_LIBRARY": str(s["library"].resolve())}}  # fmt: skip


@pytest.mark.parametrize("platform, power", [("win32", "true"), ("darwin", "false")])
def test_the_entry_sets_power_mode_per_os(setup, platform, power):
    """D-32: on Windows the engine may write a previewed proposal or crate into rekordbox; on a Mac
    it stays off until the live Mac write test (Q-35)."""
    result = merge(setup, platform=platform)
    entry = json.loads(setup["config"].read_text(encoding="utf-8"))["mcpServers"]["dj-librarian"]
    assert entry["env"]["DJ_POWER_MODE"] == power and result["entry"] == entry
    assert entry == ours(setup, platform) | {"command": entry["command"]}  # Windows may add uv's .exe


def test_no_file_yet_gets_one_with_only_our_entry(setup):
    result = merge(setup)
    assert result["status"] == "added" and result["backup"] is None
    assert json.loads(setup["config"].read_text(encoding="utf-8")) == {"mcpServers": {"dj-librarian": ours(setup)}}


def test_an_empty_file_gets_our_entry_and_a_backup(setup):
    setup["config"].parent.mkdir(parents=True)
    setup["config"].write_text("", encoding="utf-8")
    result = merge(setup)
    assert result["status"] == "added"
    assert Path(result["backup"]).name == f"{installer.CONFIG_NAME}.bak-2026-10-25"
    assert json.loads(setup["config"].read_text(encoding="utf-8"))["mcpServers"] == {"dj-librarian": ours(setup)}


def test_other_servers_and_keys_stay_byte_for_byte(setup):
    setup["config"].parent.mkdir(parents=True)
    before = json.dumps(OTHERS, indent=2, ensure_ascii=False) + "\n"
    setup["config"].write_text(before, encoding="utf-8")
    result = merge(setup)
    after = setup["config"].read_text(encoding="utf-8")
    data = json.loads(after)
    assert result["status"] == "added" and list(data) == list(OTHERS)
    assert data["mcpServers"] == {**OTHERS["mcpServers"], "dj-librarian": ours(setup)}
    for key in ("globalShortcut", "preferences"):  # the untouched keys: the same text, not just the same value
        block = json.dumps({key: OTHERS[key]}, indent=2, ensure_ascii=False)[2:-2]
        assert block in before and block in after, key
    assert Path(result["backup"]).read_text(encoding="utf-8") == before


def test_our_entry_again_writes_nothing(setup):
    merge(setup)
    stamp = setup["config"].stat().st_mtime_ns
    result = merge(setup)
    assert result["status"] == "unchanged" and result["backup"] is None
    assert setup["config"].stat().st_mtime_ns == stamp
    assert not list(setup["config"].parent.glob("*.bak-*"))


def test_an_old_entry_of_ours_is_replaced_in_place(setup):
    setup["config"].parent.mkdir(parents=True)
    old = {"mcpServers": {"a": {"command": "x"}, "dj-librarian": {"command": "uv", "args": []}, "z": {"command": "y"}}}
    setup["config"].write_text(json.dumps(old, indent=2), encoding="utf-8")
    assert merge(setup)["status"] == "replaced"
    servers = json.loads(setup["config"].read_text(encoding="utf-8"))["mcpServers"]
    assert list(servers) == ["a", "dj-librarian", "z"] and servers["dj-librarian"] == ours(setup)
    assert merge(setup)["status"] == "unchanged"


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", '{"mcpServers": []}', '"just a string"'])
def test_a_malformed_file_is_refused_and_left_alone(setup, text):
    setup["config"].parent.mkdir(parents=True)
    setup["config"].write_text(text, encoding="utf-8")
    with pytest.raises(installer.InstallerError, match="Nothing was written"):
        merge(setup)
    assert setup["config"].read_text(encoding="utf-8") == text
    assert not list(setup["config"].parent.glob("*.bak-*"))
    with pytest.raises(installer.InstallerError):
        installer.remove_desktop_config(setup["config"], today=DAY)


def test_relative_paths_and_a_folder_without_library_yaml_are_refused(setup, tmp_path):
    with pytest.raises(installer.InstallerError, match="absolute"):
        installer.merge_desktop_config(setup["config"], "uv", setup["folder"], setup["library"])
    with pytest.raises(installer.InstallerError, match="no library.yaml"):
        installer.merge_desktop_config(setup["config"], setup["uv"], setup["folder"], tmp_path)
    with pytest.raises(installer.InstallerError, match="no pyproject.toml"):
        installer.merge_desktop_config(setup["config"], setup["uv"], tmp_path, setup["library"])
    assert not setup["config"].exists()


def test_windows_gets_uv_exe_when_it_sits_there(setup):
    exe = setup["uv"].with_suffix(".exe")
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert installer.entry(setup["uv"], setup["folder"], platform="win32")["command"] == str(exe)
    assert installer.entry(setup["uv"], setup["folder"], platform="darwin")["command"] == str(setup["uv"])


def test_backups_never_overwrite_an_older_one(setup):
    setup["config"].parent.mkdir(parents=True)
    setup["config"].write_text("{}", encoding="utf-8")
    merge(setup)
    installer.remove_desktop_config(setup["config"], today=DAY)
    names = sorted(p.name for p in setup["config"].parent.glob("*.bak-*"))
    assert names == [f"{installer.CONFIG_NAME}.bak-2026-10-25", f"{installer.CONFIG_NAME}.bak-2026-10-25-2"]


def test_remove_takes_out_only_our_entry(setup):
    setup["config"].parent.mkdir(parents=True)
    setup["config"].write_text(json.dumps(OTHERS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    merge(setup)
    result = installer.remove_desktop_config(setup["config"], today=DAY)
    assert result["status"] == "removed" and result["backup"]
    assert json.loads(setup["config"].read_text(encoding="utf-8")) == OTHERS
    assert installer.remove_desktop_config(setup["config"], today=DAY)["status"] == "absent"


def test_the_config_path_per_os():
    mac = installer.default_config_path("darwin", {"HOME": "/Users/dj"})
    assert mac.as_posix() == "/Users/dj/Library/Application Support/Claude/claude_desktop_config.json"
    win = installer.default_config_path("win32", {"APPDATA": "C:\\Users\\dj\\AppData\\Roaming"})
    assert win.name == installer.CONFIG_NAME and win.parent.name == "Claude"
    with pytest.raises(installer.InstallerError, match="macOS and Windows only"):
        installer.default_config_path("linux", {})


def test_the_script_merges_and_removes_with_one_json_line(setup):
    script = REPO / "scripts" / "merge_desktop_config.py"
    base = [sys.executable, str(script)]
    common = ["--config", str(setup["config"])]
    done = subprocess.run([*base, "merge", "--uv", str(setup["uv"]), "--folder", str(setup["folder"]),
                           "--library", str(setup["library"]), *common], capture_output=True, text=True, timeout=60)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["status"] == "added"
    setup["config"].write_text("{broken", encoding="utf-8")
    bad = subprocess.run([*base, "remove", *common], capture_output=True, text=True, timeout=60)
    assert bad.returncode == 1 and "Nothing was written" in json.loads(bad.stdout)["error"]
