# Contributing to dj-librarian

Thanks for helping. This tool touches people's DJ libraries, so the rules on writes are strict. Read [CLAUDE.md](CLAUDE.md) and [docs/requirements.md](docs/requirements.md) before your first change.

## Development setup

You need [uv](https://docs.astral.sh/uv/). It installs Python 3.13 for you (see `.python-version`).

Keep the virtual environment outside any cloud-synced folder (Dropbox, iCloud Drive and the like). Syncing a venv corrupts it, and on Windows a synced venv breaks hardlinks. Point uv at a folder outside the sync with `UV_PROJECT_ENVIRONMENT`.

**Windows (PowerShell).** Use native Windows Python, not WSL: SQLite across the WSL mount is unsafe and the rekordbox process check is per-OS.

```powershell
setx UV_PROJECT_ENVIRONMENT "$env:USERPROFILE\.venvs\dj-librarian"
```

Open a new terminal, then:

```powershell
uv sync --group dev
```

**macOS and Linux (bash or zsh).**

```bash
echo 'export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/dj-librarian"' >> ~/.zshrc
```

Open a new terminal, then:

```bash
uv sync --group dev
```

If the repo is not in a synced folder, you can skip `UV_PROJECT_ENVIRONMENT` and let uv use `.venv/`.

While Claude Desktop has the MCP server open, the venv's `dj-mcp` binary is locked. Use `uv run --no-sync ...`, or quit Claude Desktop before `uv sync` or `uv add`.

## Run the checks

```bash
uv run pytest
```

```bash
uv run ruff check .
```

`plugin.json` points its MCP server at `./engine.mcpb`, a build product git ignores. Build it into the plugin before you validate, or both validate commands fail with `Path not found: ./engine.mcpb`:

```bash
uv run python scripts/build_mcpb.py --plugin
```

```bash
claude plugin validate ./plugin --strict
```

```bash
claude plugin validate .
```

Then remove `plugin/engine.mcpb` again (and a `plugin/.mcpb-cache/` if Claude Code made one), so nobody tests against a stale engine. `uv run python scripts/build_mcpb.py --smoke` also starts the built engine with the command and env `mcpb/manifest.json` gives a host, and compares its tools with the manifest's.

`tests/conftest.py` blocks the real rekordbox database and all network sockets. No test may open a real database or an audio file outside `tmp_path`. After any pyrekordbox upgrade, run `tests/test_contract.py` before any write.

## Branches, commits and pull requests

- One branch and one pull request per change. Branch names: `feat/`, `fix/`, `docs/`, `chore/`, `test/`.
- Conventional commit titles: `feat:`, `fix:`, `docs:`, `chore:`, `test:`. Pull requests are squash-merged; the PR title becomes the commit.
- **Every PR cites the requirement ids it satisfies** (`R-…`, `NFR-…`, `C-…`) from [docs/requirements.md](docs/requirements.md). A change with no requirement starts as an issue.
- Update [CHANGELOG.md](CHANGELOG.md) under `[Unreleased]`.
- The versions in `pyproject.toml`, `plugin/.claude-plugin/plugin.json` and `mcpb/manifest.json` stay equal (`scripts/build_mcpb.py` refuses to build otherwise).
- Run `uv run python scripts/build_mcpb.py --plugin`, then `claude plugin validate ./plugin --strict`, before opening a PR that touches `plugin/` or `mcpb/`.

## Writes: the safety rule

Anything that writes to rekordbox, Spotify or audio files must follow these rules and must have tests, including the XML writer.

- Create and add only. Never delete, rename, move or reorder what exists.
- Dry-run by default. Real writes only behind `--apply`, after a preview the user said yes to.
- Before a `master.db` write: rekordbox closed, verified backup, one commit, rollback on any exception. All database access goes through `dj.safety.open_db()`.
- Only the pyrekordbox calls listed in [CLAUDE.md](CLAUDE.md) may mutate. Never `delete_*`, `move_*`, `rename_*` or `update_*`.
- MCP tools are a fixed list. A write tool has a matching preview tool and refuses without a plan or preview id. Arguments are passed as a list, never through a shell.
- The dry-run records a preview id and `--apply` checks it, through `dj.write_gate` (`record`, `check`, `consume`; the CLI's `--preview-id`). Anything that changed since the preview refuses the write (R-1102).
- A `master.db` write also needs `--power-mode` and runs on Windows only (`write_gate.require_power_mode`, R-205).
- A writing command appends its own `log.md` line through `dj.activity_log` (R-904); a dry-run or a refusal appends none.
- An MCP tool whose list grows with the library returns it through `paginate` / `run_paged`: counts first, pages under the tool-result limit (NFR-03).

PRs that touch writers, hooks or Spotify get an extra review.

## No personal data

Nothing personal goes into the repository: no library paths, playlist names, inbox data, Spotify ids, or names of real users. Tests use synthetic data under `tmp_path`. Configuration ships as `examples/*.example.yaml`; your own `links.yaml`, `tidy.yaml`, `bases.yaml`, `tree.yaml` and `.env` are gitignored. Check `git status` before every commit. CI runs a secret scanner on every PR.

## Licence

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
