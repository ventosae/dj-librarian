"""One clock for every log.md line (Q-28, W-30 item 2).

A sample run once logged `2026-10-21 13:20`, `2026-10-20 13:20` and `2026-10-21 00:00` across five
lines: some writers took the date from --today at midnight, others the clock's date. Now every line
starts with `libfolder.log_clock`: the --today date when given, else the local date, and always the
local wall-clock HH:MM. The clock is pinned in these tests, so they never flake at midnight.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import xml_fixtures as fx

from dj import activity_log, libfolder, onboarding
from dj.analysis import identity, profile, structure, taste
from dj.analysis import proposals as proposals_mod

DAY = date(2026, 10, 20)


def pin_clock(monkeypatch, *moments: datetime) -> list[datetime]:
    """The wall clock reads `moments` in turn (the last one again after that)."""
    left = list(moments)

    def clock() -> datetime:
        return left.pop(0) if len(left) > 1 else left[0]

    monkeypatch.setattr(libfolder, "_wall_clock", clock)
    return left


def log_lines(root: Path) -> list[str]:
    return [line for line in (root / "log.md").read_text(encoding="utf-8").splitlines() if line[:1].isdigit()]


def test_log_clock_takes_the_date_from_today_and_the_time_from_the_wall_clock(monkeypatch):
    pin_clock(monkeypatch, datetime(2026, 10, 21, 13, 20, 59))
    assert libfolder.log_clock(DAY) == "2026-10-20 13:20"
    assert libfolder.log_clock() == "2026-10-21 13:20"  # no --today: the local date


def test_log_clock_shows_an_aware_moment_in_local_time():
    moment = datetime(2026, 10, 20, 12, 5, tzinfo=timezone.utc)
    local = moment.astimezone()
    assert libfolder.log_clock(now=moment) == local.strftime("%Y-%m-%d %H:%M")
    assert libfolder.log_clock(DAY, moment) == f"2026-10-20 {local.strftime('%H:%M')}"
    assert libfolder.log_clock(DAY, datetime(2026, 10, 25, 7, 9)) == "2026-10-20 07:09"


def test_five_consecutive_writes_with_today_share_one_date_and_carry_the_wall_clock(tmp_path, monkeypatch):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac", today=DAY)
    start = datetime(2026, 10, 21, 23, 58)  # the run crosses the clock's midnight
    pin_clock(monkeypatch, *(start + timedelta(minutes=n) for n in range(5)))
    lines = [libfolder.append_log(root, f"step {n}", {"files": 1}, today=DAY) for n in range(5)]
    assert lines == log_lines(root)
    assert [line[:16] for line in lines] == [
        "2026-10-20 23:58", "2026-10-20 23:59", "2026-10-20 00:00", "2026-10-20 00:01", "2026-10-20 00:02",
    ]  # fmt: skip


def test_the_first_contact_chain_with_today_logs_one_date_at_the_wall_clock(tmp_path, monkeypatch):
    """dj-start init, profile, structure, taste, identity, proposals: every log line the same way."""
    root = tmp_path / "dj-library"
    root.mkdir()
    xml = fx.write_xml(root / "collection.xml")
    pin_clock(monkeypatch, datetime(2026, 10, 21, 13, 20))
    onboarding.init(root, device="mac", xml=xml, today=DAY)
    profile.run(root, today=DAY)
    structure.run(root, today=DAY)
    taste.run(root, today=DAY)
    identity.run(root, today=DAY)
    proposals_mod.run(root, today=DAY)
    lines = log_lines(root)
    assert len(lines) >= 6
    assert {line[:16] for line in lines} == {"2026-10-20 13:20"}, lines
    assert [line.split(" ")[2] for line in lines][:6] == ["start", "profile", "structure", "taste", "identity",
                                                          "proposals"]  # fmt: skip


def test_without_today_the_date_is_the_local_date(tmp_path, monkeypatch):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac", today=DAY)
    pin_clock(monkeypatch, datetime(2026, 11, 2, 9, 5))
    assert libfolder.append_log(root, "report", {"files": 1}).startswith("2026-11-02 09:05 report")


def test_log_time_for_callers_that_pass_a_moment(monkeypatch):
    pin_clock(monkeypatch, datetime(2026, 10, 21, 13, 20, 30))
    assert proposals_mod.log_time(DAY) == datetime(2026, 10, 20, 13, 20, 30)
    assert proposals_mod.log_time(None) is None


def test_activity_log_passes_today_through(tmp_path, monkeypatch):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac", today=DAY)
    monkeypatch.setenv(libfolder.ENV_VAR, str(root))
    pin_clock(monkeypatch, datetime(2026, 10, 21, 8, 1))
    logged = activity_log.log_write("tree", {"created": 2}, today=DAY)
    assert logged.warning is None and logged.line.startswith("2026-10-20 08:01 tree -> 2 created")


@pytest.mark.parametrize("module", ["crate", "build_structure"])
def test_no_writer_formats_its_own_log_time(module):
    """The by-hand fallback lines in crate and build use the same clock."""
    text = (Path(__file__).resolve().parents[1] / "src" / "dj" / f"{module}.py").read_text(encoding="utf-8")
    assert "log_clock(today, now)" in text
    assert "strftime('%Y-%m-%d %H:%M')} crate" not in text and "strftime('%Y-%m-%d %H:%M')} build" not in text
