"""The engine as an MCP bundle (W-34, D-28, Q-31): mcpb/manifest.json and scripts/build_mcpb.py.

The manifest is server type `uv` (the host provides Python and the dependencies), names the server
`dj-librarian` (so tool names and the write-gate matcher stay as they are), passes the four
settings to the engine as env, and lists exactly the tools the server registers. The manifest
check is as strict as the MCPB 0.4 schema. The build is a zip with manifest.json at its root and
nothing beyond the allowlist: the same bytes every time, written to plugin/engine.mcpb only when
asked (tests use tmp copies). `--smoke` (handshake) is tested against a fake server bundle; the
real bundle starts only with DJ_MCPB_SMOKE=1 and uv on PATH, from uv's cache (UV_OFFLINE), and CI
starts it in the plugin job. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
import yaml
from test_hook_gate import PREFIXES, WRITE_TOOLS

from dj import mcp_server as m

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_mcpb.py"
MANIFEST = REPO / "mcpb" / "manifest.json"
PLUGIN_JSON = REPO / "plugin" / ".claude-plugin" / "plugin.json"
TOP_FILES = {"manifest.json", "pyproject.toml", "uv.lock", ".python-version", "LICENSE", "README.md"}
ENV = {
    "DJ_LIBRARY": "${user_config.library_folder}",
    "SPOTIFY_CLIENT_ID": "${user_config.spotify_client_id}",
    "SPOTIFY_CLIENT_SECRET": "${user_config.spotify_client_secret}",
    "DJ_POWER_MODE": "${user_config.power_mode}",
    "DJ_ENGINE": "mcpb",
    # uv's own default, said out loud: an inherited UV_PROJECT_ENVIRONMENT (CONTRIBUTING.md has a
    # contributor set one for good) must not put the extension into a clone's shared venv.
    "UV_PROJECT_ENVIRONMENT": "${__dirname}/.venv",
}


@pytest.fixture(scope="module")
def bm():
    spec = importlib.util.spec_from_file_location("build_mcpb", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest() -> dict:
    return _json(MANIFEST)


def _git_checkout() -> bool:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        return False
    done = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--is-inside-work-tree"], capture_output=True,
                          text=True, timeout=60)  # fmt: skip
    return done.returncode == 0 and done.stdout.strip() == "true"


def _ls(*args: str) -> list[str]:
    done = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", *args], capture_output=True, timeout=60,
                          check=True)  # fmt: skip
    return [n for n in done.stdout.decode("utf-8").split("\0") if n]


@pytest.fixture(scope="module")
def built(bm, tmp_path_factory):
    if not _git_checkout():
        pytest.skip("not a git checkout: the bundle is built from the files git tracks")
    out = tmp_path_factory.mktemp("dist")
    result = bm.build(out)
    return result, out / f"dj-librarian-engine-{result['version']}.mcpb"


def _names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.namelist()


def _version() -> str:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


# -- the manifest ----------------------------------------------------------------------------------


def test_the_manifest_identifies_the_engine(manifest):
    plugin = _json(PLUGIN_JSON)
    assert manifest["manifest_version"] == "0.4"  # the first version with server type uv
    assert manifest["name"] == "dj-librarian" == plugin["name"]
    assert manifest["display_name"] == "dj-librarian engine"
    assert manifest["version"] == _version() == plugin["version"]
    assert manifest["author"] == plugin["author"]
    assert manifest["license"] == "Apache-2.0" == plugin["license"]
    assert manifest["repository"] == {"type": "git", "url": plugin["repository"]}
    assert manifest["keywords"] and all(isinstance(k, str) for k in manifest["keywords"])
    for key in ("description", "long_description"):
        text = manifest[key]
        assert isinstance(text, str) and 40 <= len(text) <= 600 and "\n" not in text, key
    assert "icon" not in manifest  # no icon file in the bundle


def test_the_server_is_uv_and_starts_dj_mcp_with_the_settings_as_env(manifest):
    server = manifest["server"]
    assert set(server) == {"type", "entry_point", "mcp_config"}
    assert server["type"] == "uv" and server["entry_point"] == "src/dj/mcp_server.py"
    mcp = server["mcp_config"]
    assert mcp["command"] == "uv"
    assert mcp["args"] == ["run", "--directory", "${__dirname}", "--no-dev", "--frozen", "dj-mcp"]
    assert mcp["env"] == ENV


def test_the_entry_point_and_the_dj_mcp_script_are_this_projects():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["scripts"]["dj-mcp"] == "dj.mcp_server:main"
    entry = (REPO / "src" / "dj" / "mcp_server.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in entry


def test_the_four_settings(manifest):
    config = manifest["user_config"]
    assert list(config) == ["library_folder", "spotify_client_id", "spotify_client_secret", "power_mode"]
    titles = {key: option["title"] for key, option in config.items()}
    assert titles == {"library_folder": "dj-library folder", "spotify_client_id": "Spotify client ID",
                      "spotify_client_secret": "Spotify client secret", "power_mode": "Power mode (Windows)"}  # fmt: skip
    assert config["library_folder"]["type"] == "directory" and config["library_folder"]["required"] is True
    assert not config["library_folder"].get("multiple", False)
    for key in ("spotify_client_id", "spotify_client_secret"):
        assert config[key]["type"] == "string" and config[key]["sensitive"] is True
        assert config[key].get("required", False) is False and "default" not in config[key]
    power = config["power_mode"]
    assert power["type"] == "boolean" and power["default"] is False and power.get("required", False) is False
    for key, option in config.items():
        description = option["description"]
        assert isinstance(description, str) and 20 <= len(description) <= 300 and "\n" not in description, key


def test_the_venv_is_the_extensions_own_whatever_the_host_inherits(manifest):
    """uv obeys UV_PROJECT_ENVIRONMENT: inherited from a contributor's `setx` (CONTRIBUTING.md), it
    would install the extension into the clone's venv and point the editable `dj` at the extension.
    The manifest names uv's default, the bundle's own .venv, so the inherited value never wins."""
    mcp = manifest["server"]["mcp_config"]
    assert mcp["env"]["UV_PROJECT_ENVIRONMENT"] == "${__dirname}/.venv"
    assert mcp["args"][mcp["args"].index("--directory") + 1] == "${__dirname}"  # the same project folder


def test_every_user_config_reference_is_declared_and_every_setting_is_used(manifest):
    text = json.dumps(manifest["server"])
    used = set(re.findall(r"\$\{user_config\.([A-Za-z0-9_]+)\}", text))
    assert used == set(manifest["user_config"])
    assert set(re.findall(r"\$\{([A-Za-z_]+)\}", text)) == {"__dirname"}  # no other host variable


def test_compatibility_and_privacy(manifest):
    assert manifest["compatibility"] == {"platforms": ["darwin", "win32"], "runtimes": {"python": ">=3.12"}}
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert manifest["compatibility"]["runtimes"]["python"] == project["requires-python"]
    # The engine calls the Spotify Web API with the DJ's own app.
    assert manifest["privacy_policies"] == ["https://www.spotify.com/legal/privacy-policy/"]


def test_the_tools_are_exactly_what_the_server_registers(manifest):
    registered = [t.name for t in asyncio.run(m.server.list_tools())]
    listed = [t["name"] for t in manifest["tools"]]
    assert sorted(listed) == sorted(registered) and len(listed) == len(set(listed))
    for tool in manifest["tools"]:
        assert set(tool) == {"name", "description"}
        text = tool["description"]
        assert 20 <= len(text) <= 120 and "\n" not in text and text.endswith("."), tool["name"]
        assert text.startswith("WRITES") == (tool["name"] in WRITE_TOOLS), tool["name"]


def test_the_server_name_keeps_the_tool_names_the_write_gate_matches(manifest):
    assert f"mcp__{manifest['name']}__" in PREFIXES
    assert f"mcp__plugin_{manifest['name']}_{manifest['name']}__" in PREFIXES


def test_the_real_manifest_passes_the_check(bm, manifest):
    assert bm.check_manifest(manifest, names=["src/dj/mcp_server.py"]) == []


@pytest.mark.parametrize(
    "change, why",
    [
        (lambda d: d.pop("author"), "author is missing"),
        (lambda d: d.pop("server"), "server is missing"),
        (lambda d: d.update(manifest_version="0.3"), "manifest_version must be '0.4'"),
        (lambda d: d["server"].update(type="python"), "server.type must be 'uv'"),
        (lambda d: d["server"]["mcp_config"]["env"].update(X="${user_config.nope}"), "user_config.nope"),
        (lambda d: d["user_config"].pop("power_mode"), "user_config.power_mode"),
        (lambda d: d["user_config"]["power_mode"].update(sensitive=True), "only a string can be sensitive"),
        (lambda d: d["user_config"]["power_mode"].update(default="false"), "default must be true or false"),
        (lambda d: d["user_config"]["library_folder"].update(type="folder"), "library_folder.type"),
        (lambda d: d["user_config"]["library_folder"].pop("title"), "library_folder.title is missing"),
        (lambda d: d["tools"].append(dict(d["tools"][0])), "tools lists a name twice"),
        (lambda d: d["compatibility"].update(platforms=["darwin", "ios"]), "compatibility.platforms"),
        (lambda d: d.update(version="9.9.9"), "version 9.9.9 must equal pyproject.toml"),
        (lambda d: d["server"].update(entry_point="src/dj/missing.py"), "is not in the bundle"),
        # The MCPB 0.4 schema's own rules (src/schemas/0.4.ts): strict objects, required fields, URLs.
        (lambda d: d.update(homepage_url="https://example.com"), "the manifest has unknown fields ['homepage_url']"),
        (lambda d: d["server"].pop("mcp_config"), "server.mcp_config is missing"),
        (lambda d: d["server"]["mcp_config"].pop("command"), "server.mcp_config.command is missing"),
        (lambda d: d["server"].update(cwd="x"), "server has unknown fields ['cwd']"),
        (lambda d: d["server"]["mcp_config"].update(cwd="x"), "server.mcp_config has unknown fields ['cwd']"),
        (lambda d: d["server"]["mcp_config"].update(platform_overrides={"win32": {"cwd": "x"}}),
         "platform_overrides.win32 has unknown fields ['cwd']"),
        (lambda d: d["server"]["mcp_config"].update(args="run"), "server.mcp_config.args must be a list of strings"),
        (lambda d: d.update(privacy_policies=["not a url"]), "privacy_policies must be a list of URLs"),
        (lambda d: d["repository"].update(url="nope"), "repository.url must be a URL"),
        (lambda d: d["repository"].update(branch="main"), "repository has unknown fields ['branch']"),
        (lambda d: d["author"].update(github="x"), "author has unknown fields ['github']"),
        (lambda d: d["author"].update(email="not-an-email"), "author.email must be an email address"),
        (lambda d: d["tools"][0].update(inputSchema={}), "has unknown fields ['inputSchema']"),
        (lambda d: d["compatibility"]["runtimes"].update(uv=">=0.4"), "runtimes has unknown fields ['uv']"),
        (lambda d: d["compatibility"].update(os="any"), "compatibility has unknown fields ['os']"),
        (lambda d: d.update(keywords=["dj", 1]), "keywords must be a list of strings"),
        (lambda d: d.update(homepage="example.com"), "homepage must be a URL"),
        (lambda d: d.update(long_description=["a"]), "long_description must be a string"),
        (lambda d: d["user_config"]["power_mode"].update(min=True), "power_mode.min must be a number"),
        (lambda d: d["user_config"]["power_mode"].update(required="no"), "power_mode.required must be true or false"),
        (lambda d: d["user_config"]["library_folder"].update(default={"a": 1}), "library_folder.default must be"),
        (lambda d: d.update(prompts=[{"name": "x"}]), "prompts[0] needs a name and a text"),
        (lambda d: d.update(icons=[{"src": "icon.png", "size": "big"}]), "icons[0] needs a src and a size"),
        (lambda d: d.update(_meta={"x": 1}), "_meta must map names to objects"),
    ],
)  # fmt: skip
def test_the_check_names_what_is_wrong(bm, manifest, change, why):
    broken = json.loads(json.dumps(manifest))
    change(broken)
    problems = bm.check_manifest(broken, names=["src/dj/mcp_server.py"])
    assert any(why in line for line in problems), problems


def test_a_version_that_differs_from_plugin_json_is_refused(bm, manifest, tmp_path):
    (tmp_path / "plugin" / ".claude-plugin").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{_version()}"\n', encoding="utf-8")
    (tmp_path / "plugin" / ".claude-plugin" / "plugin.json").write_text('{"version": "9.9.9"}', encoding="utf-8")
    problems = bm.check_manifest(manifest, repo=tmp_path)
    assert any("plugin.json (9.9.9)" in line for line in problems), problems


# -- the build -------------------------------------------------------------------------------------


def test_the_bundle_holds_the_allowlist_and_nothing_else(built):
    result, path = built
    names = _names(path.read_bytes())
    tracked = {n for n in _ls("--cached", "--", "src/dj") if "__pycache__" not in n and not n.endswith(".pyc")}
    tracked = {n for n in tracked if (REPO / n).is_file()}
    assert sorted(names) == names  # sorted entries
    assert set(names) == TOP_FILES | tracked
    assert result["files"] == len(names) and result["size"] == path.stat().st_size
    assert "src/dj/mcp_server.py" in names and "src/dj/analysis/archetypes.yaml" in names
    for name in names:
        assert name in TOP_FILES or name.startswith("src/dj/"), name
        parts = name.split("/")
        assert not parts[-1].startswith(".env") and "__pycache__" not in parts and not name.endswith(".pyc")
    for banned in ("tests/", "docs/", "local/", "examples/", "plans/", "plugin/", "mcpb/", "dist/", ".github/"):
        assert not any(name.startswith(banned) for name in names), banned


def test_the_manifest_sits_at_the_root_as_written(built):
    _result, path = built
    with zipfile.ZipFile(path) as zf:
        assert zf.read("manifest.json") == MANIFEST.read_bytes()
        assert json.loads(zf.read("manifest.json"))["server"]["entry_point"] in zf.namelist()
        for name in TOP_FILES - {"manifest.json"}:
            assert zf.read(name) == (REPO / name).read_bytes(), name
        infos = zf.infolist()
    assert all(i.compress_type == zipfile.ZIP_DEFLATED and i.date_time == (2026, 1, 1, 0, 0, 0) for i in infos)
    assert all(not i.is_dir() for i in infos)


def test_the_bundle_is_named_for_the_version_and_small(built):
    result, path = built
    assert path.name == f"dj-librarian-engine-{_version()}.mcpb" and result["version"] == _version()
    assert path.stat().st_size < 3 * 1024 * 1024


def test_the_same_files_give_the_same_bundle(bm, built, tmp_path):
    _result, first = built
    bm.build(tmp_path)
    assert (tmp_path / first.name).read_bytes() == first.read_bytes()
    assert [p.name for p in tmp_path.iterdir()] == [first.name]  # its temp file is gone
    data, _info = bm.bundle()
    assert data == first.read_bytes()


def test_nothing_personal_in_the_bundle(built):
    """The owner's name only where licensing puts it: the manifest's author and LICENSE's
    copyright line. The test DJ's name nowhere."""
    spec = importlib.util.spec_from_file_location("check_personal", REPO / "scripts" / "check_personal.py")
    cp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cp)
    words = cp.names()
    assert words
    _result, path = built
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            for line in zf.read(name).decode("utf-8", "replace").splitlines():
                if any(w.casefold() in line.casefold() for w in words):
                    allowed = (name == "manifest.json" and re.fullmatch(r'\s*"name"\s*:\s*".*",?\s*', line)) or (
                        name == "LICENSE" and line.strip().startswith("Copyright "))
                    assert allowed, (name, line)


def test_plugin_writes_engine_mcpb_into_the_given_folder_only(bm, built, tmp_path):
    real = REPO / "plugin" / "engine.mcpb"
    before = real.read_bytes() if real.exists() else None
    plugin = tmp_path / "plugin"
    shutil.copytree(REPO / "plugin" / ".claude-plugin", plugin / ".claude-plugin")
    result = bm.build(tmp_path / "out", plugin_dir=plugin)
    _first, path = built
    assert (plugin / "engine.mcpb").read_bytes() == path.read_bytes()
    assert result["plugin"].endswith("plugin/engine.mcpb")
    assert (real.read_bytes() if real.exists() else None) == before  # the real plugin/ untouched


def test_main_with_plugin_uses_the_plugin_folder(bm, built, tmp_path, monkeypatch, capsys):
    real = REPO / "plugin" / "engine.mcpb"
    before = real.exists()
    monkeypatch.setattr(bm, "PLUGIN", tmp_path / "plugin")
    assert bm.main(["--out", str(tmp_path / "out"), "--plugin"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"path", "size", "files", "version", "plugin"}
    assert (tmp_path / "plugin" / "engine.mcpb").is_file()
    assert out["size"] == (tmp_path / "out" / f"dj-librarian-engine-{_version()}.mcpb").stat().st_size
    assert real.exists() == before


def test_main_prints_one_json_error_and_exits_1(bm, tmp_path, monkeypatch, capsys):
    def refuse(*_a, **_k):
        raise bm.BuildError("no good")

    monkeypatch.setattr(bm, "bundle", refuse)
    assert bm.main(["--out", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out) == {"error": "no good"}
    assert not list(tmp_path.iterdir())


def test_the_script_runs_with_plain_python_and_no_site_packages(built, tmp_path):
    """CI's plugin job runs it with the runner's python3, without uv or a venv."""
    done = subprocess.run([sys.executable, "-S", str(SCRIPT), "--out", str(tmp_path)], capture_output=True,
                          text=True, encoding="utf-8", cwd=REPO, timeout=180)  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    out = json.loads(done.stdout)
    assert set(out) == {"path", "size", "files", "version"}
    _result, first = built
    assert (tmp_path / first.name).read_bytes() == first.read_bytes()


def test_the_script_is_stdlib_only():
    imported = set(re.findall(r"^(?:import|from) (\w+)", SCRIPT.read_text(encoding="utf-8"), re.MULTILINE))
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported - set(sys.stdlib_module_names)


@pytest.mark.parametrize(
    "name, ok",
    [
        ("manifest.json", True), ("pyproject.toml", True), ("uv.lock", True), ("src/dj/cli.py", True),
        ("src/dj/analysis/archetypes.yaml", True), ("tests/test_x.py", False), ("docs/plan.md", False),
        (".env", False), ("src/dj/.env", False), ("src/dj/.env.local", False), ("examples/links.example.yaml", False),
        ("plans/a.plan.json", False), ("local/notes.md", False), ("src/dj/__pycache__/cli.cpython-313.pyc", False),
        ("src/dj/cli.pyc", False), ("src/other/x.py", False), ("src/dj/../../x", False), ("mcpb/manifest.json", False),
        ("plugin/engine.mcpb", False),
    ],
)  # fmt: skip
def test_the_allowlist(bm, name, ok):
    assert bm._allowed(name) is ok


# -- the file list, on a synthetic repo ------------------------------------------------------------


def _fake_repo(tmp_path: Path) -> Path:
    """A git checkout with the top files, a small src/dj, the manifest and plugin.json, all
    tracked, plus the caches and ignored files a local run leaves."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, timeout=60)
    files = {
        ".gitignore": "__pycache__/\nlinks.yaml\n.env\n",
        "pyproject.toml": f'[project]\nname = "dj-librarian"\nversion = "{_version()}"\n',
        "uv.lock": "version = 1\n", ".python-version": "3.13\n", "LICENSE": "license\n", "README.md": "# x\n",
        "src/dj/__init__.py": "", "src/dj/mcp_server.py": "def main(): pass\n", "src/dj/data/a.yaml": "a: 1\n",
        "mcpb/manifest.json": MANIFEST.read_text(encoding="utf-8"),
        "plugin/.claude-plugin/plugin.json": json.dumps({"name": "dj-librarian", "version": _version()}),
        "tests/test_a.py": "", "docs/a.md": "",
    }  # fmt: skip
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True, timeout=60)
    for rel in ("src/dj/__pycache__/mcp_server.cpython-313.pyc", "src/dj/links.yaml", "src/dj/.env"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(b"local")
    return repo


def test_members_are_the_top_files_and_the_tracked_package(bm, tmp_path):
    repo = _fake_repo(tmp_path)
    names = bm.members(repo)
    assert list(names) == sorted(TOP_FILES | {"src/dj/__init__.py", "src/dj/data/a.yaml", "src/dj/mcp_server.py"})
    assert names["manifest.json"] == repo / "mcpb" / "manifest.json"
    data, info = bm.bundle(repo)
    assert sorted(_names(data)) == list(names) and info["files"] == len(names)


def test_an_untracked_file_in_the_package_stops_the_build(bm, tmp_path):
    repo = _fake_repo(tmp_path)
    (repo / "src" / "dj" / "new_module.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(bm.BuildError, match="new_module.py") as refused:
        bm.build(tmp_path / "out", repo=repo)
    assert "links.yaml" not in str(refused.value) and "__pycache__" not in str(refused.value)
    assert not (tmp_path / "out").exists()


def test_an_untracked_top_file_stops_the_build(bm, tmp_path):
    repo = _fake_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "rm", "-q", "--cached", "uv.lock"], check=True, capture_output=True,
                   timeout=60)  # fmt: skip
    with pytest.raises(bm.BuildError, match="uv.lock is not tracked"):
        bm.members(repo)


def test_a_bad_manifest_stops_the_build_before_anything_is_written(bm, tmp_path):
    repo = _fake_repo(tmp_path)
    data = _json(repo / "mcpb" / "manifest.json")
    data["server"]["type"] = "python"
    (repo / "mcpb" / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(bm.BuildError, match="server.type must be 'uv'"):
        bm.build(tmp_path / "out", repo=repo, plugin_dir=tmp_path / "plugin")
    assert not (tmp_path / "out").exists() and not (tmp_path / "plugin").exists()


def test_members_refuse_outside_a_git_checkout(bm, tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    (tmp_path / "src" / "dj").mkdir(parents=True)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    with pytest.raises(bm.BuildError, match="git checkout"):
        bm.members(tmp_path)


# -- --npx: the official CLI, never run here -------------------------------------------------------


def test_npx_is_refused_when_node_is_not_there(bm, tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(bm.shutil, "which", lambda _name: None)
    with pytest.raises(bm.BuildError, match="npx on PATH"):
        bm.build(tmp_path / "out", repo=repo, npx=True)
    assert not (tmp_path / "out").exists()


def _fake_npx(extra: str | None = None):
    calls = []

    def run(cmd, **_kwargs):
        calls.append(cmd)
        stage, out = Path(cmd[-2]), Path(cmd[-1])
        with zipfile.ZipFile(out, "w") as zf:
            for path in sorted(p for p in stage.rglob("*") if p.is_file()):
                zf.write(path, path.relative_to(stage).as_posix())
            if extra:
                zf.writestr(extra, "x")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return run, calls


def test_npx_packs_the_staged_files(bm, tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    names = bm.members(repo)  # the real git first; only the pack step gets the fake npx
    run, calls = _fake_npx()
    monkeypatch.setattr(bm.shutil, "which", lambda _name: "npx")
    monkeypatch.setattr(bm.subprocess, "run", run)
    data = bm.pack_npx(names)
    (cmd,) = calls
    assert cmd[:4] == ["npx", "--yes", "@anthropic-ai/mcpb@2.1.2", "pack"]  # pinned: never npm's latest
    assert bm.MCPB_CLI == "@anthropic-ai/mcpb@2.1.2"
    assert sorted(_names(data)) == list(names)


def test_npx_output_with_another_file_list_is_refused(bm, tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    names = bm.members(repo)
    run, _calls = _fake_npx(extra="tests/leaked.py")
    monkeypatch.setattr(bm.shutil, "which", lambda _name: "npx")
    monkeypatch.setattr(bm.subprocess, "run", run)
    with pytest.raises(bm.BuildError, match="tests/leaked.py"):
        bm.pack_npx(names)


# -- the repo around it ----------------------------------------------------------------------------


def test_the_build_products_are_gitignored():
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/plugin/engine.mcpb" in lines and ".mcpb-cache/" in lines and "dist/" in lines


def _ci() -> dict:
    return yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def test_ci_builds_the_engine_into_the_plugin_before_validating():
    job = _ci()["jobs"]["plugin"]
    runs = [str(step.get("run", "")) for step in job["steps"]]
    build = next(i for i, run in enumerate(runs) if run.strip() == "python3 scripts/build_mcpb.py --plugin")
    validate = next(i for i, run in enumerate(runs) if "claude plugin validate ./plugin --strict" in run)
    assert build < validate


def test_ci_checks_the_manifest_with_the_pinned_official_cli(bm):
    """`claude plugin validate` only checks that ./engine.mcpb exists; the MCPB CLI checks the
    manifest against the schema the host installs it with. The same pin as --npx."""
    job = _ci()["jobs"]["plugin"]
    runs = [str(step.get("run", "")).strip() for step in job["steps"]]
    assert f"npx --yes {bm.MCPB_CLI} validate mcpb/manifest.json" in runs
    assert any("actions/setup-node" in str(step.get("uses", "")) for step in job["steps"])


def test_ci_starts_the_built_engine_with_uv():
    """The tests read the bundle's bytes; only a start shows that `uv run` finds every file it
    needs. CI starts it in the plugin job with --smoke, after setup-uv (the test job's pin)."""
    ci = _ci()["jobs"]
    steps = ci["plugin"]["steps"]
    uses = [str(step.get("uses", "")) for step in steps]
    runs = [str(step.get("run", "")) for step in steps]
    setup = next(i for i, use in enumerate(uses) if use.startswith("astral-sh/setup-uv@"))
    smoke = next(i for i, run in enumerate(runs) if "scripts/build_mcpb.py" in run and "--smoke" in run)
    assert setup < smoke and "--plugin" not in runs[smoke]
    assert uses[setup] in {str(step.get("uses", "")) for step in ci["test"]["steps"]}


# -- --smoke: start a bundle the way a host does ------------------------------------------------------


def test_launch_fills_the_real_manifest_as_a_host_would(bm, manifest, tmp_path):
    ext, folders = tmp_path / "extension", tmp_path / "settings"
    command, env = bm.launch(manifest, ext, folders)
    assert command == ["uv", "run", "--directory", str(ext), "--no-dev", "--frozen", "dj-mcp"]
    assert env == {"DJ_LIBRARY": str(folders / "library_folder"), "SPOTIFY_CLIENT_ID": "", "SPOTIFY_CLIENT_SECRET": "",
                   "DJ_POWER_MODE": "false", "DJ_ENGINE": "mcpb", "UV_PROJECT_ENVIRONMENT": f"{ext}/.venv"}  # fmt: skip
    assert (folders / "library_folder").is_dir() and not list((folders / "library_folder").iterdir())


FAKE_SERVER = r'''
import json, os, sys
mode = os.environ["FAKE_MODE"]
keys = ("DJ_LIBRARY", "DJ_POWER_MODE", "SPOTIFY_CLIENT_ID", "DJ_ENGINE", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV",
        "UV_OFFLINE")
for line in sys.stdin:
    msg = json.loads(line)
    if mode == "exit":
        print("boom: the engine fell over", file=sys.stderr, flush=True)
        sys.exit(3)
    if mode == "silent":
        continue
    if msg.get("method") == "initialize":
        seen = {key: os.environ.get(key) for key in keys}
        seen["library_is_a_folder"] = os.path.isdir(os.environ["DJ_LIBRARY"])
        venv = os.environ["UV_PROJECT_ENVIRONMENT"]
        seen["venv_beside_the_manifest"] = os.path.isfile(os.path.join(os.path.dirname(venv), "manifest.json"))
        print("a line that is not JSON", flush=True)
        print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                          "result": {"serverInfo": {"name": "fake", "version": json.dumps(seen)}}}), flush=True)
    elif msg.get("method") == "tools/list":
        tools = [{"name": name} for name in os.environ["FAKE_TOOLS"].split(",")]
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": tools}}), flush=True)
'''


def _fake_bundle(manifest: dict, *, mode: str = "ok", tools: list[str] | None = None,
                 command: str | None = None) -> bytes:  # fmt: skip
    """A bundle with the real manifest's settings and env, whose server is FAKE_SERVER run by this
    Python: what handshake() does around the server, without uv or the network."""
    fake = json.loads(json.dumps(manifest))
    mcp = fake["server"]["mcp_config"]
    mcp["command"] = command or sys.executable
    mcp["args"] = ["-I", "${__dirname}${/}server.py"]
    names = [tool["name"] for tool in fake["tools"]] if tools is None else tools
    mcp["env"].update(FAKE_MODE=mode, FAKE_TOOLS=",".join(names))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(fake))
        zf.writestr("server.py", FAKE_SERVER)
    return buf.getvalue()


def test_handshake_starts_the_bundle_with_the_hosts_command_and_env(bm, manifest, monkeypatch):
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(REPO / ".shared-venv"))  # a contributor's setx
    monkeypatch.setenv("VIRTUAL_ENV", str(REPO / ".venv"))
    monkeypatch.delenv("UV_OFFLINE", raising=False)
    out = bm.handshake(_fake_bundle(manifest), timeout=60)
    assert out["tools"] == len(manifest["tools"]) and out["server"]["name"] == "fake"
    seen = json.loads(out["server"]["version"])
    assert seen["library_is_a_folder"] and not Path(seen["DJ_LIBRARY"]).resolve().is_relative_to(REPO)
    assert seen["DJ_POWER_MODE"] == "false" and seen["SPOTIFY_CLIENT_ID"] == "" and seen["DJ_ENGINE"] == "mcpb"
    assert seen["venv_beside_the_manifest"] and seen["UV_PROJECT_ENVIRONMENT"].endswith("/.venv")
    assert seen["VIRTUAL_ENV"] is None and seen["UV_OFFLINE"] is None


def test_handshake_offline_keeps_uv_to_its_cache(bm, manifest):
    out = bm.handshake(_fake_bundle(manifest), offline=True, timeout=60)
    assert json.loads(out["server"]["version"])["UV_OFFLINE"] == "1"


def test_handshake_refuses_tools_that_differ_from_the_manifest(bm, manifest):
    names = [tool["name"] for tool in manifest["tools"]]
    with pytest.raises(bm.BuildError, match=r"not in the manifest \['dj_extra'\], missing \['dj_status'\]"):
        bm.handshake(_fake_bundle(manifest, tools=[n for n in names if n != "dj_status"] + ["dj_extra"]), timeout=60)


def test_handshake_reports_a_server_that_stops(bm, manifest):
    with pytest.raises(bm.BuildError, match="stopped before it answered") as refused:
        bm.handshake(_fake_bundle(manifest, mode="exit"), timeout=60)
    assert "boom: the engine fell over" in str(refused.value)


def test_handshake_gives_up_on_a_silent_server(bm, manifest):
    with pytest.raises(bm.BuildError, match="did not answer within 2 s"):
        bm.handshake(_fake_bundle(manifest, mode="silent"), timeout=2)


def test_handshake_refuses_a_command_that_is_not_on_path(bm, manifest):
    with pytest.raises(bm.BuildError, match="'no-such-uv-here', which is not on PATH"):
        bm.handshake(_fake_bundle(manifest, command="no-such-uv-here"), timeout=5)


def test_build_with_smoke_starts_the_bundle_before_writing(bm, built, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(bm, "handshake", lambda data: seen.append(data) or {"tools": 30, "server": {}})
    result = bm.build(tmp_path / "ok", smoke=True)
    assert result["smoke"] == {"tools": 30, "server": {}}
    assert seen == [(tmp_path / "ok" / built[1].name).read_bytes()]

    def refuse(_data):
        raise bm.BuildError("the engine stopped before it answered.")

    monkeypatch.setattr(bm, "handshake", refuse)
    with pytest.raises(bm.BuildError):
        bm.build(tmp_path / "bad", plugin_dir=tmp_path / "plugin", smoke=True)
    assert not (tmp_path / "bad").exists() and not (tmp_path / "plugin").exists()


@pytest.mark.skipif(os.environ.get("DJ_MCPB_SMOKE") != "1" or shutil.which("uv") is None,
                    reason="opt-in: DJ_MCPB_SMOKE=1 and uv on PATH start the real bundle (uv's cache only)")  # fmt: skip
def test_the_built_bundle_starts_and_lists_the_manifests_tools(bm, built, manifest):
    """The real thing, from uv's cache only (no network): unpacked outside the checkout, started
    with the manifest's own command and env, initialize and tools/list answered."""
    _result, path = built
    out = bm.handshake(path.read_bytes(), offline=True)
    assert out["tools"] == len(manifest["tools"]) and out["server"]["name"] == "dj-librarian"
