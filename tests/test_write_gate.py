"""The write gate on every existing write path (R-1102) and power mode for master.db (R-205).

Per CLI write command - `dj tree`, `dj apply`, `dj copy` (master.db), `dj push`, `dj build`
(Spotify), `dj tidy apply`, `dj tidy undo` (audio files): the dry-run records a preview and returns
its id and writes nothing; `--apply` without the id, with a malformed, unknown, expired or used id,
with another command's or other arguments' id, or after the plan changed, is refused in one
`REFUSED` line (exit 1) with no backup, no `open_db(write=True)`, no Spotify write scope or write
call and no audio file touched; with the right id it writes once and the id is used up.
The master.db commands run through the real `safety.open_db` over a fake database, so "no backup"
and "one commit" are the real protocol. Per MCP write tool: the id is required and checked before
anything runs, power mode first for the three master.db tools, and the preview tools return it.
"""

from __future__ import annotations

import asyncio
import functools
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from test_cli import sessions  # noqa: F401  (fixture used by `env`)
from test_intake import CrateDB, plan_with
from test_playlist_copy import CopyDB, song
from test_push import FakeSpotify, item
from test_tidy_cli import _planned, env  # noqa: F401  (fixture)
from tidy_fixtures import make_audio
from typer.testing import CliRunner

from dj import build as build_mod
from dj import cli, safety, spotify, write_gate
from dj import mcp_server as m
from dj import playlist_copy as copy_mod
from dj import push as push_mod
from dj.gate import Gate, valid_id
from dj.tidy import tags

runner = CliRunner()

POWER_MODE_LINE = ("REFUSED master.db writes are power mode (Windows only): add --power-mode, or build an XML to "
                   "import (dj library build)")  # fmt: skip
NO_SUCH_ID = "0" * 12


def run(*args):
    return runner.invoke(cli.app, [str(a) for a in args])


def refused(result, *, quiet: bool = True) -> str:
    """The one REFUSED line of a refused write (exit 1). `quiet`: a gate refusal comes before the
    plan is printed, so stdout is empty too (a refusal from inside the write session may follow it)."""
    assert result.exit_code == cli.EXIT_ERROR, result.output
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(lines) == 1 and lines[0].startswith("REFUSED "), result.stderr
    assert not quiet or result.stdout.strip() == "", result.stdout
    return lines[0]


def dry_run_id(dry: list) -> str:
    result = run(*dry, "--json")
    assert result.exit_code == 0, result.output
    pid = json.loads(result.stdout)["preview_id"]
    assert valid_id(pid)
    return pid


def record_path(pid: str):
    return write_gate.STATE_DIR / "previews" / f"{pid}.json"


def expire(pid: str) -> str:
    data = json.loads(record_path(pid).read_text(encoding="utf-8"))
    data["created"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec="seconds")
    record_path(pid).write_text(json.dumps(data), encoding="utf-8")
    return pid


def used(pid: str) -> bool:
    return bool(Gate(write_gate.STATE_DIR).load(pid).used)


REFUSALS = {  # case -> a text the REFUSED line holds
    "missing": "No preview id",
    "malformed": "is not a preview id",
    "unknown": "No preview with id",
    "other_command": "write, not",
    "other_args": "Preview this one first",
    "expired": "older than 24 hours",
    "changed": "The plan changed since preview",
}


def bad_id(case: str, pid: str, kind: str, change) -> str | None:
    """The --preview-id a refusal case passes (None: the flag is left out)."""
    if case == "missing":
        return None
    if case == "malformed":
        return "ABC123"
    if case == "unknown":
        return NO_SUCH_ID
    if case == "other_command":
        return write_gate.record("tidy-undo" if kind != "tidy-undo" else "tree", {"x": 1}, []).preview_id
    if case == "other_args":
        return write_gate.record(kind, {"other": True}, []).preview_id
    if case == "expired":
        return expire(pid)
    change()
    return pid


def gated(pid: str | None, *flags: str) -> list[str]:
    return ["--apply", *flags, *([] if pid is None else ["--preview-id", pid])]


# -- master.db: dj tree, dj apply, dj copy ----------------------------------------------------


class Tx:
    """commit / rollback / close for a fake db the real safety.open_db wraps."""

    commits = rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class TxCrateDB(Tx, CrateDB):
    pass


class TxCopyDB(Tx, CopyDB):
    pass


@pytest.fixture
def rb(monkeypatch, tmp_path):
    """The real safety.open_db over a fake database: the write platform open (the platform rule
    is test_platform.py's), rekordbox closed, the backup recorded instead of copied."""
    master = tmp_path / "rekordbox" / "master.db"
    master.parent.mkdir()
    master.write_bytes(b"not a database")
    state = NS(db=None, backups=[], connects=0)

    def connect(path, quiet=False):
        state.connects += 1
        return state.db

    def backup(path, dest=None):
        state.backups.append(path)
        return safety.Backup(timestamp="test")

    monkeypatch.setattr(safety, "DB_WRITE_PLATFORMS", (sys.platform,))
    monkeypatch.setattr(safety, "find_master_db", lambda: master)
    monkeypatch.setattr(safety, "rekordbox_running", lambda: False)
    monkeypatch.setattr(safety, "backup", backup)
    monkeypatch.setattr(safety, "_connect", connect)
    monkeypatch.setattr(cli.intake, "Paths", functools.partial(cli.intake.Paths, tmp_path))
    monkeypatch.setattr(copy_mod, "REPORT_DIR", tmp_path / "reports")
    return state


def db_job(name, tmp_path, fake_db):
    if name == "tree":
        tree_file = tmp_path / "tree.yaml"
        tree_file.write_text("- playlist: inbox\n- folder: sets\n  children:\n    - playlist: a\n", encoding="utf-8")
        return NS(kind="tree", db=fake_db, dry=["tree", "--file", tree_file], file=tree_file,
                  change=lambda: fake_db.seed("playlist", "inbox"), written=lambda: bool(fake_db.calls),
                  writes=lambda: len(fake_db.calls), undo=fake_db.rows.clear)  # fmt: skip
    if name == "apply":
        plan = tmp_path / "x.plan.json"
        plan.write_text(json.dumps(plan_with(("yes", "1"), ("no", "2"))), encoding="utf-8")
        db = TxCrateDB()
        return NS(kind="apply", db=db, dry=["apply", plan], plan=plan,
                  change=lambda: db.crate.Songs.append(NS(ContentID="1")), written=lambda: bool(db.added),
                  writes=lambda: len(db.added), undo=db.crate.Songs.clear)  # fmt: skip
    db = TxCopyDB([song("1", 1), song("2", 2)])
    return NS(kind="copy", db=db, dry=["copy", "jazzy", "jazz_base/2.1_jazzy"],
              change=lambda: db.src.Songs.append(song("3", 3)), written=lambda: bool(db.added),
              writes=lambda: len(db.added), undo=db.dst.Songs.clear)  # fmt: skip


@pytest.fixture(params=["tree", "apply", "copy"])
def job(request, rb, tmp_path, db):
    found = db_job(request.param, tmp_path, db)
    rb.db = found.db
    return found


def test_db_dry_run_returns_a_preview_id_and_writes_nothing(job, rb):
    pid = dry_run_id(job.dry)
    text = run(*job.dry)
    assert text.exit_code == 0, text.output
    lines = text.stdout.splitlines()
    assert f"Preview id: {pid}" in lines
    assert lines[-1].endswith(f"--apply --power-mode --preview-id {pid}") and lines[-1].startswith("DRY-RUN.")
    assert record_path(pid).is_file() and not used(pid)
    assert rb.backups == [] and job.db.commits == 0 and not job.written()


def test_db_write_without_power_mode_is_refused_before_anything(job, rb):
    pid = dry_run_id(job.dry)
    connects = rb.connects
    assert refused(run(*job.dry, *gated(pid))) == POWER_MODE_LINE
    assert refused(run(*job.dry, *gated(None))) == POWER_MODE_LINE  # the flag is checked first
    assert rb.connects == connects  # refused before master.db was even read
    assert rb.backups == [] and job.db.commits == 0 and not job.written() and not used(pid)


@pytest.mark.parametrize("case", list(REFUSALS))
def test_db_write_refusals_take_no_backup_and_write_nothing(job, rb, case):
    pid = dry_run_id(job.dry)
    give = bad_id(case, pid, job.kind, job.change)
    assert REFUSALS[case] in refused(run(*job.dry, *gated(give, "--power-mode")))
    assert rb.backups == [] and job.db.commits == 0 and not job.written()


def test_db_write_with_its_preview_id_writes_once_and_uses_the_id_up(job, rb):
    pid = dry_run_id(job.dry)
    result = run(*job.dry, *gated(pid, "--power-mode"))
    assert result.exit_code == 0, result.output
    assert "APPLIED" in result.stdout
    assert len(rb.backups) == 1 and job.db.commits == 1 and job.written() and used(pid)
    assert "already used" in refused(run(*job.dry, *gated(pid, "--power-mode")))
    assert len(rb.backups) == 1 and job.db.commits == 1


def test_the_same_plan_after_the_dj_removed_the_rows_writes_again_with_a_new_id(job, rb):
    """The DJ removed what the write added (in rekordbox): the same plan again gets a fresh id
    that writes once more, as before the gate. The used id stays refused."""
    pid = dry_run_id(job.dry)
    assert run(*job.dry, *gated(pid, "--power-mode")).exit_code == 0
    writes = job.writes()
    job.undo()
    again = dry_run_id(job.dry)
    assert again != pid and not used(again)
    assert "already used" in refused(run(*job.dry, *gated(pid, "--power-mode")))
    assert len(rb.backups) == 1 and job.db.commits == 1
    result = run(*job.dry, *gated(again, "--power-mode"))
    assert result.exit_code == 0 and "APPLIED" in result.stdout, result.output
    assert len(rb.backups) == 2 and job.db.commits == 2 and job.writes() == 2 * writes and used(again)


def test_a_change_after_the_check_is_caught_inside_the_write_session(job, rb, monkeypatch):
    """Belt and braces: the write session re-plans (as before W-21) and compares with the checked
    plan before the first create or add; a mismatch rolls back."""
    pid = dry_run_id(job.dry)
    recorded_backup = safety.backup

    def backup_then_change(path, dest=None):
        job.change()  # something changes master.db between the gate check and the write
        return recorded_backup(path, dest)

    monkeypatch.setattr(safety, "backup", backup_then_change)
    result = run(*job.dry, *gated(pid, "--power-mode"))
    assert "The plan changed since the preview" in refused(result, quiet=False)  # after the gate: the plan is out
    assert job.db.commits == 0 and job.db.rollbacks >= 1 and not job.written() and not used(pid)


def test_apply_refuses_after_a_decision_changed(rb, tmp_path, db):
    """`dj apply` also records the decisions (match cache, declined): they are in the plan too."""
    job = db_job("apply", tmp_path, db)
    rb.db = job.db
    pid = dry_run_id(job.dry)
    job.plan.write_text(json.dumps(plan_with(("yes", "1"), ("yes", "2"))), encoding="utf-8")
    assert "The plan changed" in refused(run(*job.dry, *gated(pid, "--power-mode")))
    assert rb.backups == [] and job.db.added == [] and not (tmp_path / "state").exists()


def test_tree_with_a_conflict_gets_no_preview_id(rb, tmp_path, db):
    job = db_job("tree", tmp_path, db)
    rb.db = db
    db.seed("playlist", "sets")  # exists as a playlist, wanted a folder
    data = json.loads(run(*job.dry, "--json").stdout)
    assert data["counts"]["CONFLICT"] == 1 and data["preview_id"] is None
    assert not (write_gate.STATE_DIR / "previews").exists()


def test_nothing_to_write_passes_the_gate_and_leaves_the_id_unused(job, rb):
    """A no-op apply (everything already there) writes nothing, so its id is not used up."""
    pid = dry_run_id(job.dry)
    assert run(*job.dry, *gated(pid, "--power-mode")).exit_code == 0
    again = dry_run_id(job.dry)  # the plan is empty now: a new id
    backups = len(rb.backups)
    result = run(*job.dry, *gated(again, "--power-mode"))
    assert result.exit_code == 0, result.output
    assert "Nothing to" in result.stdout or "Added 0 track(s)" in result.stdout, result.stdout
    assert len(rb.backups) == backups and job.db.commits == 1 and not used(again)


# -- Spotify: dj push, dj build ----------------------------------------------------------------


@pytest.fixture
def spot(monkeypatch, tmp_path, rb):
    api = FakeSpotify([item("Track 1", "Artist", 300_000), item("Track 2", "Artist", 300_000)])
    state = NS(scopes=[], api=api)
    monkeypatch.setattr(spotify, "get_token", lambda scopes: state.scopes.append(scopes) or "token")
    monkeypatch.setattr(spotify, "Spotify", lambda token: state.api)
    monkeypatch.setattr(push_mod, "STATE_FILE", tmp_path / "state" / "push.json")
    monkeypatch.setattr(build_mod, "STATE_FILE", tmp_path / "state" / "build.json")
    monkeypatch.setattr(push_mod, "REPORT_DIR", tmp_path / "reports")
    rb.db = TxCopyDB([song("1", 1), song("2", 2)])
    return state


@pytest.fixture(params=["push", "build"])
def sjob(request, spot, tmp_path):
    if request.param == "push":
        return NS(kind="push", dry=["push", "jazzy"], change=spot.api.catalogue.pop)
    tracklist = tmp_path / "set.txt"
    tracklist.write_text("Artist - Track 1\nArtist - Track 2\n", encoding="utf-8")
    return NS(kind="build", dry=["build", tracklist],
              change=lambda: tracklist.write_text("Artist - Track 1\n", encoding="utf-8"))  # fmt: skip


def spotify_untouched(spot) -> bool:
    return spot.api.created == [] and not any(spot.api.playlists.values()) and spotify.WRITE_SCOPES not in spot.scopes


def test_spotify_dry_run_returns_a_preview_id_and_asks_for_read_scopes_only(sjob, spot):
    result = run(*sjob.dry, "--json")
    data = json.loads(result.stdout)
    assert valid_id(data["preview_id"]) and data["selected"] == 2 and data["applied"] is False
    text = run(*sjob.dry)
    assert f"Preview id: {data['preview_id']}" in text.stdout.splitlines()
    assert set(spot.scopes) == {spotify.READ_SCOPES} and spotify_untouched(spot)


@pytest.mark.parametrize("case", list(REFUSALS))
def test_spotify_refusals_ask_for_no_write_token_and_write_nothing(sjob, spot, case):
    pid = dry_run_id(sjob.dry)
    give = bad_id(case, pid, sjob.kind, sjob.change)
    spot.scopes.clear()
    spot.api.searches.clear()
    assert REFUSALS[case] in refused(run(*sjob.dry, *gated(give)))
    assert spotify_untouched(spot)
    if case != "changed":  # only the plan's digest needs the matches: every other refusal comes first
        assert spot.scopes == [] and spot.api.searches == []


def test_spotify_write_with_its_preview_id_writes_once_and_uses_the_id_up(sjob, spot):
    pid = dry_run_id(sjob.dry)
    result = run(*sjob.dry, *gated(pid), "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["applied"] is True and data["result"]["added"] == 2 and used(pid)
    assert spot.scopes[-1] == spotify.WRITE_SCOPES and spot.scopes.count(spotify.WRITE_SCOPES) == 1
    assert len(spot.api.created) == 1
    scopes, searches = len(spot.scopes), len(spot.api.searches)
    assert "already used" in refused(run(*sjob.dry, *gated(pid)))
    assert len(spot.api.created) == 1 and spot.scopes.count(spotify.WRITE_SCOPES) == 1
    assert (len(spot.scopes), len(spot.api.searches)) == (scopes, searches)  # no token, no search


def test_the_same_push_after_the_dj_deleted_the_playlist_writes_again_with_a_new_id(sjob, spot):
    """One preview, one write, and a new preview may write again (as before the gate): the DJ
    deleted the Spotify playlist, the same dry-run gives a fresh id that makes a new one. The used
    id stays refused."""
    pid = dry_run_id(sjob.dry)
    assert run(*sjob.dry, *gated(pid)).exit_code == 0
    spot.api.playlists.clear()  # the DJ deleted it on Spotify
    again = dry_run_id(sjob.dry)
    assert again != pid and not used(again) and used(pid)
    assert "already used" in refused(run(*sjob.dry, *gated(pid)))
    data = json.loads(run(*sjob.dry, *gated(again), "--json").stdout)
    assert data["applied"] is True and data["result"]["created"] is True and data["result"]["added"] == 2
    assert len(spot.api.created) == 2 and used(again)
    assert dry_run_id(sjob.dry) not in (pid, again)  # previewed after its write once more: another id


def test_the_same_push_after_the_dj_removed_its_tracks_on_spotify_adds_them_back(sjob, spot):
    """The DJ kept the Spotify playlist but removed its tracks: the same dry-run gives a fresh id
    that adds them back to that playlist (no second playlist). The used id stays refused."""
    pid = dry_run_id(sjob.dry)
    assert run(*sjob.dry, *gated(pid)).exit_code == 0
    for uris in spot.api.playlists.values():
        uris.clear()  # the DJ removed every track on Spotify
    again = dry_run_id(sjob.dry)
    assert again != pid and not used(again) and used(pid)
    text = run(*sjob.dry)
    assert text.exit_code == 0, text.output
    assert text.stdout.splitlines()[-1].endswith(f"--apply --preview-id {again}")
    assert "already used" in refused(run(*sjob.dry, *gated(pid)))
    data = json.loads(run(*sjob.dry, *gated(again), "--json").stdout)
    assert data["applied"] is True and data["result"]["created"] is False and data["result"]["added"] == 2
    assert len(spot.api.created) == 1 and used(again)


def test_push_preview_arguments_must_match_the_write(spot):
    pid = dry_run_id(["push", "jazzy"])
    assert "Preview this one first" in refused(run("push", "jazzy", "--name", "Other", *gated(pid)))
    assert "Preview this one first" in refused(run("push", "jazzy", "--include-ambiguous", *gated(pid)))
    assert spotify_untouched(spot)


# -- audio files: dj tidy apply, dj tidy undo --------------------------------------------------


def _tidy(command, plan_path, env, *extra):  # noqa: F811
    return run("tidy", command, plan_path, *extra, "--config", env.yaml)


@pytest.fixture
def tidy_apply(env):  # noqa: F811
    audio = make_audio(env.root / "Huerta - Low Five.mp3")
    plan_path = _planned(env)

    def change():  # the DJ flips the decision after the preview
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        for entry in data["items"]:
            if entry["decision"]:
                entry["decision"] = "no"
        plan_path.write_text(json.dumps(data), encoding="utf-8")

    return NS(kind="tidy-apply", command="apply", plan=plan_path, audio=audio, before=audio.read_bytes(),
              dry=["tidy", "apply", plan_path, "--config", env.yaml], change=change, env=env)  # fmt: skip


def no_undo_file(env) -> bool:  # noqa: F811
    return not list(env.tmp.rglob("*.undo.json"))


def test_tidy_apply_dry_run_returns_a_preview_id_and_writes_nothing(tidy_apply):
    pid = dry_run_id(tidy_apply.dry)
    text = run(*tidy_apply.dry)
    assert f"Preview id: {pid}" in text.stdout.splitlines()
    assert text.stdout.splitlines()[-1].endswith(f"--apply --preview-id {pid}")
    assert tidy_apply.audio.read_bytes() == tidy_apply.before and no_undo_file(tidy_apply.env)


@pytest.mark.parametrize("case", list(REFUSALS))
def test_tidy_apply_refusals_touch_no_audio_file(tidy_apply, case):
    pid = dry_run_id(tidy_apply.dry)
    give = bad_id(case, pid, tidy_apply.kind, tidy_apply.change)
    assert REFUSALS[case] in refused(run(*tidy_apply.dry, *gated(give)))
    assert tidy_apply.audio.read_bytes() == tidy_apply.before and no_undo_file(tidy_apply.env)


def test_tidy_apply_with_its_preview_id_writes_once_and_uses_the_id_up(tidy_apply):
    pid = dry_run_id(tidy_apply.dry)
    result = run(*tidy_apply.dry, *gated(pid))
    assert result.exit_code == 0, result.output
    assert tags.read(tidy_apply.audio)[0].artist == ("Huerta",) and used(pid)
    written = tidy_apply.audio.read_bytes()
    assert "already used" in refused(run(*tidy_apply.dry, *gated(pid)))
    assert tidy_apply.audio.read_bytes() == written


def _fail_every(monkeypatch, name: str):
    """tags.<name> fails for every file (a lock, say); returns the call that puts it back."""
    real = getattr(tags, name)

    def boom(*args, **kwargs):
        raise cli.TidyError("simulated: the file is locked")

    monkeypatch.setattr(tags, name, boom)
    return lambda: monkeypatch.setattr(tags, name, real)


def test_tidy_apply_where_every_item_failed_leaves_the_id_for_a_retry(tidy_apply, monkeypatch):
    """Only a write uses the id up: when every item failed, nothing was written, and the same
    preview (a new dry-run gives the same id) writes once the cause is gone."""
    pid = dry_run_id(tidy_apply.dry)
    put_back = _fail_every(monkeypatch, "write")
    failed = run(*tidy_apply.dry, *gated(pid))
    assert failed.exit_code == 1 and "FAILED" in failed.stdout and "1 failed" in failed.stdout, failed.output
    assert tidy_apply.audio.read_bytes() == tidy_apply.before and not used(pid)
    put_back()
    assert dry_run_id(tidy_apply.dry) == pid
    retry = run(*tidy_apply.dry, *gated(pid))
    assert retry.exit_code == 0, retry.output
    assert tags.read(tidy_apply.audio)[0].artist == ("Huerta",) and used(pid)


def test_tidy_apply_undo_apply_again_gets_a_new_id(tidy_apply):
    """Undo puts the plan back where it was: applying it again needs a fresh preview, which gets a
    new id that writes once more, as before the gate. The used id stays refused."""
    pid = dry_run_id(tidy_apply.dry)
    assert run(*tidy_apply.dry, *gated(pid)).exit_code == 0
    undo = ["tidy", "undo", tidy_apply.plan, "--config", tidy_apply.env.yaml]
    assert run(*undo, *gated(dry_run_id(undo))).exit_code == 0
    assert tags.read(tidy_apply.audio)[0] == tags.Tags()
    again = dry_run_id(tidy_apply.dry)
    assert again != pid and not used(again)
    assert "already used" in refused(run(*tidy_apply.dry, *gated(pid)))
    assert tags.read(tidy_apply.audio)[0] == tags.Tags()
    result = run(*tidy_apply.dry, *gated(again))
    assert result.exit_code == 0, result.output
    assert tags.read(tidy_apply.audio)[0].artist == ("Huerta",) and used(again)


@pytest.fixture
def tidy_undo(tidy_apply):
    pid = dry_run_id(tidy_apply.dry)
    assert run(*tidy_apply.dry, *gated(pid)).exit_code == 0
    audio = tidy_apply.audio
    after = audio.read_bytes()

    def change():  # the file changes after the undo preview: undo would skip it now
        audio.write_bytes(audio.read_bytes() + b"\x00")

    return NS(kind="tidy-undo", audio=audio, after=after, change=change, env=tidy_apply.env,
              dry=["tidy", "undo", tidy_apply.plan, "--config", tidy_apply.env.yaml])  # fmt: skip


def test_tidy_undo_dry_run_returns_a_preview_id_and_writes_nothing(tidy_undo):
    pid = dry_run_id(tidy_undo.dry)
    assert f"Preview id: {pid}" in run(*tidy_undo.dry).stdout.splitlines()
    assert tidy_undo.audio.read_bytes() == tidy_undo.after


@pytest.mark.parametrize("case", list(REFUSALS))
def test_tidy_undo_refusals_touch_no_audio_file(tidy_undo, case):
    pid = dry_run_id(tidy_undo.dry)
    give = bad_id(case, pid, tidy_undo.kind, tidy_undo.change)
    expected = tidy_undo.audio.read_bytes()  # after `change`, if this case made one
    assert REFUSALS[case] in refused(run(*tidy_undo.dry, *gated(give)))
    assert tidy_undo.audio.read_bytes() == expected


def test_tidy_undo_with_its_preview_id_restores_once_and_uses_the_id_up(tidy_undo):
    pid = dry_run_id(tidy_undo.dry)
    result = run(*tidy_undo.dry, *gated(pid))
    assert result.exit_code == 0 and "UNDONE" in result.stdout, result.output
    assert tags.read(tidy_undo.audio)[0] == tags.Tags() and used(pid)
    assert "already used" in refused(run(*tidy_undo.dry, *gated(pid)))


def test_tidy_undo_where_every_item_failed_leaves_the_id_for_a_retry(tidy_undo, monkeypatch):
    pid = dry_run_id(tidy_undo.dry)
    put_back = _fail_every(monkeypatch, "restore")
    failed = run(*tidy_undo.dry, *gated(pid))
    assert failed.exit_code == 1 and "FAILED" in failed.stdout, failed.output
    assert tidy_undo.audio.read_bytes() == tidy_undo.after and not used(pid)
    put_back()
    assert dry_run_id(tidy_undo.dry) == pid
    retry = run(*tidy_undo.dry, *gated(pid))
    assert retry.exit_code == 0 and "UNDONE" in retry.stdout, retry.output
    assert tags.read(tidy_undo.audio)[0] == tags.Tags() and used(pid)


# -- MCP: every write tool needs its preview id; every preview tool returns it -------------------


@pytest.fixture
def calls(monkeypatch, tmp_path):
    """The command line instead of a run; tool file arguments exist in a fake repo."""
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return NS(returncode=0, stdout=json.dumps({"counts": {}, "preview_id": "0123456789ab"}), stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)
    for name in ("bases.yaml", "p.plan.json", "set.txt"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "lib").mkdir()
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path / "lib"))
    return seen


PID = "0123456789ab"
DB_TOOLS = {
    "dj_tree_apply": lambda pid, **kw: m.dj_tree_apply(preview_id=pid, file="bases.yaml", **kw),
    "dj_apply_write": lambda pid, **kw: m.dj_apply_write("p.plan.json", preview_id=pid, **kw),
    "dj_copy_apply": lambda pid, **kw: m.dj_copy_apply("a", "b", preview_id=pid, **kw),
}
OTHER_TOOLS = {
    "dj_push_apply": lambda pid: m.dj_push_apply("p", preview_id=pid),
    "dj_build_apply": lambda pid: m.dj_build_apply("set.txt", preview_id=pid),
    "dj_tidy_apply": lambda pid: m.dj_tidy_apply("p.plan.json", preview_id=pid),
    "dj_tidy_undo": lambda pid: m.dj_tidy_undo("p.plan.json", preview_id=pid),
    "dj_structure_write": lambda pid: m.dj_structure_write("lanes", preview_id=pid),
    "dj_crate_write": lambda pid: m.dj_crate_write("saturday", preview_id=pid),
}
ALL_TOOLS = {**{n: functools.partial(f, power_mode=True) for n, f in DB_TOOLS.items()}, **OTHER_TOOLS}
PREVIEWS = {
    "dj_tree_preview": lambda: m.dj_tree_preview("bases.yaml"),
    "dj_apply_preview": lambda: m.dj_apply_preview("p.plan.json"),
    "dj_copy_preview": lambda: m.dj_copy_preview("a", "b"),
    "dj_push_preview": lambda: m.dj_push_preview("p"),
    "dj_build_preview": lambda: m.dj_build_preview("set.txt"),
    "dj_tidy_apply_preview": lambda: m.dj_tidy_apply_preview("p.plan.json"),
    "dj_tidy_undo_preview": lambda: m.dj_tidy_undo_preview("p.plan.json"),
    "dj_structure_preview": lambda: m.dj_structure_preview("lanes"),
    "dj_crate_preview": lambda: m.dj_crate_preview("saturday"),
}


def test_the_write_tools_here_are_all_the_write_tools():
    from test_hook_gate import WRITE_TOOLS

    assert set(ALL_TOOLS) == WRITE_TOOLS


@pytest.mark.parametrize("tool", sorted(ALL_TOOLS))
@pytest.mark.parametrize("bad", ["", "   ", None, "ABCDEF123456", "0123456789a", 123456789012])
def test_every_write_tool_refuses_a_missing_or_malformed_preview_id_before_running(calls, tool, bad):
    answer = json.loads(ALL_TOOLS[tool](bad))
    assert answer["ok"] is False and "preview" in answer["error"].lower()
    assert calls == []


@pytest.mark.parametrize("tool", sorted(DB_TOOLS))
def test_master_db_write_tools_need_power_mode_first(calls, tool):
    for pid in (PID, ""):
        answer = json.loads(DB_TOOLS[tool](pid))
        assert answer["ok"] is False and answer["error"] == m.POWER_MODE_REFUSAL
    assert "XML" in m.POWER_MODE_REFUSAL and "power_mode=true" in m.POWER_MODE_REFUSAL
    description = " ".join({t.name: t for t in asyncio.run(m.server.list_tools())}[tool].description.split())
    assert "power_mode=true" in description and "default write path is an XML" in description
    assert calls == []


@pytest.mark.parametrize("tool", sorted(ALL_TOOLS))
def test_every_write_tool_passes_its_preview_id(calls, tool):
    ALL_TOOLS[tool](PID)
    (cmd,) = calls
    options = cmd[3:cmd.index("--")] if "--" in cmd else cmd[3:]
    assert "--apply" in options and options[options.index("--preview-id") + 1] == PID
    assert ("--power-mode" in options) is (tool in DB_TOOLS)


@pytest.mark.parametrize("tool", sorted(PREVIEWS))
def test_every_preview_tool_returns_the_preview_id(calls, tool):
    answer = json.loads(PREVIEWS[tool]())
    assert answer["result"]["preview_id"] == PID
    (cmd,) = calls
    options = cmd[3:cmd.index("--")] if "--" in cmd else cmd[3:]
    assert "--apply" not in options and "--json" in options


def test_each_write_tool_names_its_preview_and_asks_for_a_yes():
    tools = {t.name: t for t in asyncio.run(m.server.list_tools())}
    pairs = {"dj_tree_apply": "dj_tree_preview", "dj_apply_write": "dj_apply_preview",
             "dj_copy_apply": "dj_copy_preview", "dj_push_apply": "dj_push_preview",
             "dj_build_apply": "dj_build_preview", "dj_tidy_apply": "dj_tidy_apply_preview",
             "dj_tidy_undo": "dj_tidy_undo_preview", "dj_structure_write": "dj_structure_preview"}  # fmt: skip
    for write, preview in pairs.items():
        text = " ".join(tools[write].description.split())
        assert preview in text and "preview_id" in text and "yes" in text, write
        assert tools[preview].annotations.read_only_hint or preview == "dj_structure_preview"
        assert "preview_id" in tools[write].input_schema["required"], write


def test_mcp_preview_then_write_end_to_end(monkeypatch, rb):
    """dj_copy_preview -> the CLI's preview_id -> dj_copy_apply with it writes; a wrong id is
    refused (exit 1, one REFUSED line) and writes nothing. The CLI runs in-process."""
    rb.db = TxCopyDB([song("1", 1), song("2", 2)])

    def in_process(cmd, **kwargs):
        result = runner.invoke(cli.app, cmd[3:])
        return NS(returncode=result.exit_code, stdout=result.stdout, stderr=result.stderr)

    monkeypatch.setattr(m.subprocess, "run", in_process)
    preview = json.loads(m.dj_copy_preview("jazzy", "jazz_base/2.1_jazzy"))
    pid = preview["result"]["preview_id"]
    wrong = json.loads(m.dj_copy_apply("jazzy", "jazz_base/2.1_jazzy", preview_id=NO_SUCH_ID, power_mode=True))
    assert (wrong["ok"], wrong["exit_code"]) == (False, 1) and wrong["stderr"][0].startswith("REFUSED")
    assert rb.db.added == [] and rb.backups == []
    done = json.loads(m.dj_copy_apply("jazzy", "jazz_base/2.1_jazzy", preview_id=pid, power_mode=True))
    assert done["ok"] is True and done["result"]["added"] == 2 and rb.db.added == ["1", "2"]
    assert len(rb.backups) == 1 and used(pid)


# -- MCP end to end: each preview tool's arguments give the gate arguments its write tool checks --


@pytest.fixture
def in_process(monkeypatch, tmp_path):
    """The MCP tools run the CLI in this process; the repo is tmp_path. Returns the options put in
    front of `--` of every `dj tidy` command (the test's tidy.yaml, as the DJ's repo has one)."""
    tidy_options: list[str] = []

    def run_in_process(cmd, **kwargs):
        args = cmd[3:]
        if args[0] == "tidy":
            cut = args.index("--") if "--" in args else len(args)
            args = args[:cut] + tidy_options + args[cut:]
        result = runner.invoke(cli.app, args)
        return NS(returncode=result.exit_code, stdout=result.stdout, stderr=result.stderr)

    monkeypatch.setattr(m.subprocess, "run", run_in_process)
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)
    return tidy_options


def _undoable(apply_change, undo_change):
    """A change to the plan's inputs, and the call that takes it back."""

    def change():
        apply_change()
        return undo_change

    return change


def mcp_pair(name: str, request, tmp_path, tidy_options: list[str]) -> NS:
    """One preview tool / write tool pair: preview(), write(pid), change() -> revert, state()."""
    if name in ("tree", "apply", "copy"):
        rb = request.getfixturevalue("rb")
        found = db_job(name, tmp_path, request.getfixturevalue("db"))
        rb.db, db = found.db, found.db
        state = lambda: (len(rb.backups), db.commits, found.writes())  # noqa: E731
        if name == "tree":
            file = str(found.file)
            rows: list = []
            return NS(preview=lambda: m.dj_tree_preview(file), state=state,
                      write=lambda pid: m.dj_tree_apply(preview_id=pid, file=file, power_mode=True),
                      change=_undoable(lambda: rows.append(db.seed("playlist", "inbox")),
                                       lambda: db.rows.remove(rows.pop())))  # fmt: skip
        if name == "apply":
            plan = str(found.plan)
            return NS(preview=lambda: m.dj_apply_preview(plan), state=state,
                      write=lambda pid: m.dj_apply_write(plan, preview_id=pid, power_mode=True),
                      change=_undoable(found.change, db.crate.Songs.pop))  # fmt: skip
        target = ("jazzy", "jazz_base/2.1_jazzy")
        return NS(preview=lambda: m.dj_copy_preview(*target), state=state,
                  write=lambda pid: m.dj_copy_apply(*target, preview_id=pid, power_mode=True),
                  change=_undoable(found.change, db.src.Songs.pop))  # fmt: skip
    if name.startswith(("push", "build")):
        spot = request.getfixturevalue("spot")
        options = {"name": "On Spotify", "include_ambiguous": True} if name.endswith("_named") else {}
        state = lambda: (list(spot.api.created), spot.scopes.count(spotify.WRITE_SCOPES),  # noqa: E731
                         json.dumps(spot.api.playlists, sort_keys=True))  # fmt: skip
        if name.startswith("push"):
            taken: list = []
            return NS(preview=lambda: m.dj_push_preview("jazzy", **options), state=state,
                      write=lambda pid: m.dj_push_apply("jazzy", preview_id=pid, **options),
                      change=_undoable(lambda: taken.append(spot.api.catalogue.pop()),
                                       lambda: spot.api.catalogue.append(taken.pop())))  # fmt: skip
        tracklist = tmp_path / "set.txt"
        text = "Artist - Track 1\nArtist - Track 2\n"
        tracklist.write_text(text, encoding="utf-8")
        return NS(preview=lambda: m.dj_build_preview(str(tracklist), **options), state=state,
                  write=lambda pid: m.dj_build_apply(str(tracklist), preview_id=pid, **options),
                  change=_undoable(lambda: tracklist.write_text("Artist - Track 1\n", encoding="utf-8"),
                                   lambda: tracklist.write_text(text, encoding="utf-8")))  # fmt: skip
    if name.startswith("tidy_apply"):
        job = request.getfixturevalue("tidy_apply")
        tidy_options += ["--config", job.env.yaml]
        plan, options = str(job.plan), ({"strict": True} if name.endswith("_strict") else {})
        original = job.plan.read_text(encoding="utf-8")
        return NS(preview=lambda: m.dj_tidy_apply_preview(plan, **options), state=job.audio.read_bytes,
                  write=lambda pid: m.dj_tidy_apply(plan, preview_id=pid, **options),
                  change=_undoable(job.change, lambda: job.plan.write_text(original, encoding="utf-8")))  # fmt: skip
    job = request.getfixturevalue("tidy_undo")
    tidy_options += ["--config", job.env.yaml]
    plan = str(job.dry[2])
    return NS(preview=lambda: m.dj_tidy_undo_preview(plan), state=job.audio.read_bytes,
              write=lambda pid: m.dj_tidy_undo(plan, preview_id=pid),
              change=_undoable(job.change, lambda: job.audio.write_bytes(job.after)))  # fmt: skip


MCP_PAIRS = ["tree", "apply", "copy", "push", "push_named", "build", "build_named", "tidy_apply",
             "tidy_apply_strict", "tidy_undo"]  # fmt: skip


@pytest.mark.parametrize("name", MCP_PAIRS)
def test_mcp_each_preview_id_writes_through_its_write_tool_once(name, request, tmp_path, in_process):
    """Per preview/write tool pair, the CLI in-process: the preview's arguments give the gate
    arguments the write checks. A plan that changed since the preview is refused and writes
    nothing; back as previewed, the id writes once; the same id again is refused."""
    pair = mcp_pair(name, request, tmp_path, in_process)
    pid = json.loads(pair.preview())["result"]["preview_id"]
    assert valid_id(pid)

    revert = pair.change()
    before = pair.state()
    changed = json.loads(pair.write(pid))
    assert (changed["ok"], changed["exit_code"]) == (False, 1), changed
    assert changed["stderr"][-1].startswith("REFUSED The plan changed since") and not used(pid), changed
    assert pair.state() == before
    revert()

    before = pair.state()
    done = json.loads(pair.write(pid))
    assert done["ok"] is True, done
    assert pair.state() != before and used(pid)

    before = pair.state()
    again = json.loads(pair.write(pid))
    assert (again["ok"], again["exit_code"]) == (False, 1) and "already used" in again["stderr"][-1], again
    assert pair.state() == before
