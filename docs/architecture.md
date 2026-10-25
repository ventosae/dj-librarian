# Plugin architecture + repo layout

Agreed 2026-10-20 (D-13…D-17).

## The shape

One core, two doors, writes the DJ pulls the trigger on, data the DJ owns.

```
┌──────── Cowork Project (optional template the DJ pastes) ────────┐
│ instructions: voice · ADHD rules · safety · folder conventions    │
└───────────────┬──────────────────────────────────────────────────┘
                │ the DJ talks here (or in any Cowork task)
┌───────────────▼──────────── Plugin (GitHub → Customize › Plugins) ┐
│ skills/   dj-start · dj-profile · dj-structure · dj-taste         │ ← Claude's behaviour
│           dj-report · dj-build · dj-crate · dj-barber · dj-spotify │
│ shared/   voice.md · adhd.md                                       │
│ hooks/    PreToolUse deny on *_apply / *_write (Claude Code)       │ ← hard gate where hooks run
│ skills/install, uninstall: /dj-librarian:install (Claude Code)     │ ← installs dj-mcp on the DJ's PC
└───────────────┬──────────────────────────────────────────────────┘
                │ runs
┌───────────────▼──────────── Core (Python; PyPI later) ───────────┐
│ model · readers: xml, master.db · analysis: profile, structure,   │ ← tested on Win + Mac + Linux
│ taste · writers: rekordbox xml (default), db (Windows power mode) │
│ cli `dj` · mcp `dj-mcp`                                            │
└───────────────┬──────────────────────────────────────────────────┘
                │ reads / writes text
┌───────────────▼──────────── dj-library/ (DJ's machine) ──────────┐
│ library.yaml · exports/ · profile/ · structure/ · taste/ · crates/│ ← library as code
│ reports/ · proposals/ · wishlist/ · log.md                        │   = the app's future API
└──────────────────────────────────────────────────────────────────┘
```

**Two doors, one core.**
- Door 1, *light*: the DJ exports a rekordbox XML into the folder. The skills run the core in Cowork's sandbox. Out: MD files + the HTML report. No install, Mac and Windows identical. This is first contact (D-10).
- Door 2, *engine*: the MCP server on the DJ's machine reads live master.db (My Tags, history, play counts), runs Spotify, tidy, Crate me on fresh data. It installs with `/dj-librarian:install` from the plugin zip (D-29), or as a standalone MCPB of the `uv` type (the host brings Python): inside the plugin zip, or as `dj-librarian-engine-<version>.mcpb` on its own (D-28). Same core, same files; the report gets richer. Pulled after the wow, never pushed first.

**Why it holds**
1. Wow before install. 3 actions, one wait, one HTML.
2. One core. Every number in a report comes from the same tested code, whichever door it came through.
3. Writes are safe by construction. v0.1 writes an XML the DJ imports. DB writes sit behind a flag and, in Claude Code, a PreToolUse hook.
4. The DJ owns the data. Plain text they can git, grep, back up, or hand to the app.
5. Contributors have lanes. A skill author never touches Python; a reader author never touches skills; CI checks both.
6. Nothing personal ships. Per-DJ config lives in their folder; the repo is clean by construction.

## Install (verified against claude.com/docs/plugins/overview)

- DJ: Claude desktop app → **Customize → Plugins → Add → Add marketplace** → GitHub URL of the repo (once public). Before that: **Add → Upload plugin** with a `.zip` of `plugin/` (D-17). The plugin then loads in Cowork tasks; its MCP connector runs on the DJ's computer in sessions that run there.
- Claude Code: `claude plugin marketplace add <owner>/dj-librarian` → `claude plugin install dj-librarian@dj-librarian`.
- Engine (M1 card, `docs/install.md`): `/dj-librarian:install` in Claude Code copies the engine's source from the plugin zip to `~/dj-librarian`, runs `uv sync`, and adds it to Claude Desktop's config with `DJ_LIBRARY`; the DJ clicks Allow and sets the write tools to "ask every time" (D-29). Second route: the `.mcpb` dragged onto Settings → Extensions → Install (D-28).

## Repo layout

Repo root = Python project + docs. Plugin in `plugin/`.
Reason: `claude plugin validate --strict` warns on a `CLAUDE.md` at the plugin root, and the sandbox and the engine then install the same versioned core.

```
dj-librarian/
  .claude-plugin/marketplace.json     self-hosted marketplace, one entry, source "./plugin"
  plugin/
    .claude-plugin/plugin.json        name, version (= pyproject), license, author, repository; no MCP server (D-29)
    skills/<name>/SKILL.md (+ scripts/)
    shared/voice.md  shared/adhd.md
    hooks/hooks.json  hooks/gate.py    PreToolUse deny on write tools without a plan id (Claude Code)
    skills/install/  skills/uninstall/  /dj-librarian:install and :uninstall (D-29)
    engine/                           in the zip only: the engine's source, the one copy of the core
  mcpb/manifest.json                  the standalone engine bundle's manifest: server type uv, dj-mcp, user_config (dj-library folder, Spotify keys, power mode)
  src/dj/                             core
  tests/                              pytest; synthetic XML + DB fixtures; writer tests
  examples/                           .env.example  links/tidy/bases/tree .example.yaml
  templates/project/instructions.md   Cowork Project template for a DJ
  docs/                               requirements plan decisions architecture breadboard lessons prompts/
  .github/workflows/ci.yml            pytest (windows, macos, ubuntu) · claude plugin validate ./plugin --strict · ruff · gitleaks
  .github/workflows/release.yml       on tag vX.Y.Z: CI checks, then a draft GitHub release + plugin zip; PyPI later (D-27). Consent gate
  CLAUDE.md README.md CONTRIBUTING.md LICENSE CHANGELOG.md pyproject.toml uv.lock .gitignore
  local/                              gitignored maintainer files
```

## Dev workflow

| Choice | Decision | Why |
|---|---|---|
| Branching | `main` protected; `feat/`, `fix/`, `docs/`, `chore/` branches; one PR per change; squash merge | Linear history, conventional titles for free |
| Commits | Conventional commits; PR title is the commit | CHANGELOG and semver bumps derive from it |
| Versioning | Semver; `pyproject.version` = `plugin.json.version`; Keep-a-Changelog | One number for both artifacts |
| Release | Tag `vX.Y.Z` → release.yml → CI checks, then a draft GitHub release with the plugin zip, which Anton publishes by hand; PyPI later, on his yes (D-27). Tag only on Anton's yes | Consent gate |
| CI | pytest on `windows-latest`, `macos-latest`, `ubuntu-latest`; `claude plugin validate ./plugin --strict`; ruff; gitleaks | Three runtimes we claim; C-05 enforced by a scanner |
| Backlog | GitHub Issues; labels `epic:E1…E13`, `req:R-xxx`; PR template asks for R-ids and test names | Traceability from R-id to merged code |
| Licence | Apache-2.0 (D-12) | Patent grant + trademark clause; permissive |
| Claude Code use | Plan mode for PRs touching writers, hooks, Spotify (W-18, W-21, W-25); subagents only for the three independent analysis PRs (W-14/15/16) in worktrees | Writes need a reviewed plan; analysis tracks are independent |
| Worker | PM chat writes one prompt per PR → worker (Claude Code on Anton's Windows machine) executes → pastes result back → PM updates plan/decisions | Live checks need native Python |

## Unverified (label stays until checked)

- Plugin hooks in Cowork (Q-03). MCP connectors: verified.
- Core install in Cowork's sandbox at skill run time (Q-06).
- `claude plugin validate` headless in GitHub Actions (Q-07).
- `/dj-librarian:install` on a Mac (Q-32); the standalone `uv`-type engine bundle in the Claude desktop app on Windows, on a Mac and inside a Cowork session (Q-31).
- pyrekordbox master.db discovery and key on macOS (A-C1).
