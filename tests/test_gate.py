"""dj.gate: a real write needs the id of a fresh, unused preview of the same content (R-1102)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from dj.gate import (
    MAX_AGE,
    Gate,
    GateError,
    canonical,
    preview_id_for,
    require_id,
    valid_id,
)

T0 = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)
ARGS = {"proposal": "lanes"}
DIGEST = "d" * 64


@pytest.fixture
def gate(tmp_path):
    return Gate(tmp_path / ".cache")


def test_record_returns_the_sha256_prefix_and_stores_a_json_record(gate, tmp_path):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    expected = hashlib.sha256(f"build\n{canonical(ARGS)}\n{DIGEST}".encode()).hexdigest()[:12]
    assert pid == expected == preview_id_for("build", ARGS, DIGEST)
    assert valid_id(pid)
    path = tmp_path / ".cache" / "previews" / f"{pid}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"id": pid, "kind": "build", "args": ARGS, "digest": DIGEST,
                    "created": "2026-10-20T14:00:00+00:00", "used": None, "written": None}  # fmt: skip


def test_the_same_preview_gets_the_same_id_whatever_the_key_order(gate):
    a = gate.record("build", {"a": 1, "b": [1, 2]}, DIGEST, now=T0)
    b = gate.record("build", {"b": [1, 2], "a": 1}, DIGEST, now=T0)
    assert a == b
    assert gate.record("build", {"a": 1, "b": [1, 2]}, "e" * 64, now=T0) != a
    assert gate.record("crate", {"a": 1, "b": [1, 2]}, DIGEST, now=T0) != a


def test_check_passes_for_a_fresh_preview(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    record = gate.check(pid, "build", dict(ARGS), DIGEST, now=T0 + timedelta(minutes=3))
    assert record.id == pid and record.used is None


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_check_refuses_no_id(gate, bad):
    with pytest.raises(GateError, match="No preview id"):
        gate.check(bad, "build", ARGS, DIGEST, now=T0)
    with pytest.raises(GateError, match="No preview id"):
        require_id(bad)


@pytest.mark.parametrize("bad", ["../../etc/x", "ABCDEF012345", "0123456789a", "0123456789abc", "--apply"])
def test_check_refuses_a_malformed_id_and_never_builds_a_path_from_it(gate, bad):
    with pytest.raises(GateError, match="not a preview id"):
        gate.check(bad, "build", ARGS, DIGEST, now=T0)
    with pytest.raises(GateError):
        gate.path_for(bad)


def test_check_refuses_an_unknown_id(gate):
    with pytest.raises(GateError, match="No preview with id 0123456789ab"):
        gate.check("0123456789ab", "build", ARGS, DIGEST, now=T0)


def test_check_refuses_another_kind_or_other_args(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    with pytest.raises(GateError, match="for a build write, not crate"):
        gate.check(pid, "crate", ARGS, DIGEST, now=T0)
    with pytest.raises(GateError, match="not .*other"):
        gate.check(pid, "build", {"proposal": "other"}, DIGEST, now=T0)


def test_check_refuses_when_the_content_changed_since_the_preview(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    with pytest.raises(GateError, match="changed since preview"):
        gate.check(pid, "build", ARGS, "e" * 64, now=T0)


def test_a_consumed_preview_is_refused(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    gate.check(pid, "build", ARGS, DIGEST, now=T0)
    used = gate.consume(pid, now=T0 + timedelta(minutes=1), written="proposals/lanes.xml")
    assert (used.used, used.written) == ("2026-10-20T14:01:00+00:00", "proposals/lanes.xml")
    with pytest.raises(GateError, match=r"already used \(2026-10-20T14:01:00\+00:00, wrote proposals/lanes.xml\)"):
        gate.check(pid, "build", ARGS, DIGEST, now=T0 + timedelta(minutes=2))


def test_consume_needs_a_record(gate):
    with pytest.raises(GateError, match="No preview with id"):
        gate.consume("0123456789ab", now=T0)


def test_a_preview_expires_after_24_hours(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    gate.check(pid, "build", ARGS, DIGEST, now=T0 + MAX_AGE)  # exactly 24 h: still fine
    with pytest.raises(GateError, match="older than 24 hours"):
        gate.check(pid, "build", ARGS, DIGEST, now=T0 + MAX_AGE + timedelta(seconds=1))


def test_a_preview_dated_in_the_future_is_refused(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0 + timedelta(hours=2))
    with pytest.raises(GateError, match="future"):
        gate.check(pid, "build", ARGS, DIGEST, now=T0)


def test_a_zone_aware_clock_compares_with_the_stored_time(gate):
    aware = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    pid = gate.record("build", ARGS, DIGEST, now=aware)
    gate.check(pid, "build", ARGS, DIGEST, now=aware + timedelta(minutes=1))


def test_times_are_stored_in_utc_and_a_naive_time_is_local(gate):
    local = datetime(2026, 10, 20, 14, 0)  # naive: the wall clock of this computer
    pid = gate.record("build", ARGS, DIGEST, now=local)
    stored = datetime.fromisoformat(gate.load(pid).created)
    assert stored.utcoffset() == timedelta(0) and stored == local.astimezone(timezone.utc)
    gate.check(pid, "build", ARGS, DIGEST, now=local + timedelta(minutes=1))


CEST, CET = timezone(timedelta(hours=2)), timezone(timedelta(hours=1))


def test_the_clock_going_back_does_not_date_a_preview_in_the_future(gate):
    # Daylight saving ends: 02:30 CEST, then 30 minutes later the wall clock reads 02:00 CET.
    pid = gate.record("build", ARGS, DIGEST, now=datetime(2026, 10, 25, 2, 30, tzinfo=CEST))
    gate.check(pid, "build", ARGS, DIGEST, now=datetime(2026, 10, 25, 2, 0, tzinfo=CET))


def test_the_clock_going_back_does_not_stretch_the_24_hours(gate):
    pid = gate.record("build", ARGS, DIGEST, now=datetime(2026, 10, 25, 0, 0, tzinfo=CEST))
    # 23:30 on the wall clock, but 24.5 hours have passed.
    with pytest.raises(GateError, match="older than 24 hours"):
        gate.check(pid, "build", ARGS, DIGEST, now=datetime(2026, 10, 25, 23, 30, tzinfo=CET))


def test_the_clock_going_forward_does_not_expire_a_preview_early(gate):
    pid = gate.record("build", ARGS, DIGEST, now=datetime(2026, 3, 29, 0, 30, tzinfo=CET))
    # 24:15 apart on the wall clock (one hour skipped), 23.25 hours in real time.
    gate.check(pid, "build", ARGS, DIGEST, now=datetime(2026, 3, 30, 0, 45, tzinfo=CEST))


def test_an_old_record_with_a_naive_time_still_reads(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    path = gate.path_for(pid)
    data = json.loads(path.read_text(encoding="utf-8"))
    local = datetime(2026, 10, 20, 14, 0)
    data["created"] = local.isoformat()  # written before times were stored in UTC
    path.write_text(json.dumps(data), encoding="utf-8")
    gate.check(pid, "build", ARGS, DIGEST, now=local + timedelta(hours=1))


def test_previewing_again_keeps_a_used_id_used(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    gate.consume(pid, now=T0, written="proposals/lanes.xml")
    again = gate.record("build", ARGS, DIGEST, now=T0 + timedelta(hours=1))
    assert again == pid
    record = gate.load(pid)
    assert record.used == T0.isoformat() and record.written == "proposals/lanes.xml"
    with pytest.raises(GateError, match="already used"):
        gate.check(pid, "build", ARGS, DIGEST, now=T0 + timedelta(hours=1))
    other = gate.record("build", ARGS, "e" * 64, now=T0 + timedelta(hours=1))  # changed content
    assert other != pid and gate.check(other, "build", ARGS, "e" * 64, now=T0 + timedelta(hours=1))


def test_previewing_unused_content_again_refreshes_its_time(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    gate.record("build", ARGS, DIGEST, now=T0 + timedelta(hours=20))
    gate.check(pid, "build", ARGS, DIGEST, now=T0 + timedelta(hours=30))  # 10 h after the second


def test_rearm_gives_a_used_plan_a_new_id_for_one_more_write(gate):
    """The dj CLI's writers: the target can return to its earlier state, so the same plan must be
    writable again after a new preview. The used id stays refused; the new one allows one write."""
    later = T0 + timedelta(hours=1)
    first = gate.record("push", ARGS, DIGEST, now=T0, rearm=True)
    assert first == preview_id_for("push", ARGS, DIGEST)  # an unused plan: the plain id
    assert gate.record("push", ARGS, DIGEST, now=T0, rearm=True) == first  # still unused: same id
    gate.consume(first, now=T0)
    second = gate.record("push", ARGS, DIGEST, now=later, rearm=True)
    assert second != first and second == preview_id_for("push", ARGS, DIGEST, 1) and valid_id(second)
    assert gate.record("push", ARGS, DIGEST, now=later, rearm=True) == second  # unused: same id again
    assert gate.check(second, "push", ARGS, DIGEST, now=later).used is None
    with pytest.raises(GateError, match="already used"):
        gate.check(first, "push", ARGS, DIGEST, now=later)  # a replay of the used id
    gate.consume(second, now=later)
    third = gate.record("push", ARGS, DIGEST, now=later, rearm=True)
    assert third not in (first, second) and third == preview_id_for("push", ARGS, DIGEST, 2)
    assert gate.load(first).used and gate.load(second).used and not gate.load(third).used


def test_without_rearm_a_used_plan_keeps_its_used_id(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    gate.consume(pid, now=T0)
    assert gate.record("build", ARGS, DIGEST, now=T0) == pid and gate.load(pid).used


def test_a_trailing_newline_is_not_a_preview_id():
    assert not valid_id("0123456789ab\n") and not valid_id("0123456789ab\r\n") and valid_id("0123456789ab")
    with pytest.raises(GateError, match="not a preview id"):
        require_id("0123456789ab\n")


@pytest.mark.parametrize("content", ["{not json", "[]", '{"id": "0123456789ab"}', ""])
def test_an_unreadable_record_is_refused(gate, content):
    gate.previews.mkdir(parents=True)
    (gate.previews / "0123456789ab.json").write_text(content, encoding="utf-8")
    with pytest.raises(GateError, match="unreadable"):
        gate.check("0123456789ab", "build", ARGS, DIGEST, now=T0)


def test_a_record_naming_another_id_is_refused(gate):
    pid = gate.record("build", ARGS, DIGEST, now=T0)
    other = gate.previews / "0123456789ab.json"
    other.write_text((gate.previews / f"{pid}.json").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(GateError, match="unreadable"):
        gate.check("0123456789ab", "build", ARGS, DIGEST, now=T0)


@pytest.mark.parametrize(("kind", "args", "digest"), [
    ("", ARGS, DIGEST), (None, ARGS, DIGEST), ("build", ["x"], DIGEST),
    ("build", {"x": object()}, DIGEST), ("build", ARGS, ""),
])  # fmt: skip
def test_record_refuses_bad_input(gate, kind, args, digest):
    with pytest.raises(GateError):
        gate.record(kind, args, digest, now=T0)
    assert not gate.previews.exists()
