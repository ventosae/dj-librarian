"""tree.yaml smart rules -> pyrekordbox SmartList. v1 rule types only, no My Tag."""

from __future__ import annotations

from typing import Any, Callable

from pyrekordbox.db6.smartlist import LogicalOperator, Operator, Property, SmartList

# Encodings. pyrekordbox passes these strings straight into rekordbox's rule XML and
# does not test them against rekordbox itself, so they are calibrated against a smart
# playlist made in the rekordbox GUI (`dj status --smart-xml`). CALIBRATED says which
# ones have been confirmed that way.
BPM_SCALE = 100  # DjmdContent.BPM stores 120 BPM as 12000
RATING_STEP = 51  # stars are stored as 0, 51, 102, 153, 204, 255
DATE_ADDED = Property.STOCK_DATE  # rekordbox "Date Added" column
AUTO_UPDATE = 0  # what rekordbox 7.2.18 itself writes for a GUI-made smart playlist
NEEDS_CALIBRATION = {"bpm_range", "rating_min", "added_last_days"}
CALIBRATED: set[str] = set()  # rule types confirmed against rekordbox-made XML


def uncalibrated(rules: Any) -> set[str]:
    """Rule types in `rules` whose encoding is still inferred, not confirmed."""
    used = {key for rule in rules or [] for key in rule}
    return (used & NEEDS_CALIBRATION) - CALIBRATED

Condition = tuple[Property, Operator, str, str, str]  # prop, op, left, right, unit


def _text(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}: expected a non-empty string, got {value!r}")
    return value


def _whole(value: Any, key: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{key}: expected a whole number {low}-{high}, got {value!r}")
    return value


def _genre_contains(value: Any) -> Condition:
    return (Property.GENRE, Operator.CONTAINS, _text(value, "genre_contains"), "", "")


def _comment_contains(value: Any) -> Condition:
    return (Property.COMMENTS, Operator.CONTAINS, _text(value, "comment_contains"), "", "")


def _bpm_range(value: Any) -> Condition:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"bpm_range: expected [low, high], got {value!r}")
    low, high = (_whole(v, "bpm_range", 1, 999) for v in value)
    if low >= high:
        raise ValueError(f"bpm_range: low must be below high, got {value!r}")
    return (Property.BPM, Operator.IN_RANGE, str(low * BPM_SCALE), str(high * BPM_SCALE), "")


def _rating_min(value: Any) -> Condition:
    stars = _whole(value, "rating_min", 1, 5)
    # rekordbox has no >= operator: "at least N stars" is "more than N-1 stars".
    return (Property.RATING, Operator.GREATER, str((stars - 1) * RATING_STEP), "", "")


def _added_last_days(value: Any) -> Condition:
    days = _whole(value, "added_last_days", 1, 3650)
    return (DATE_ADDED, Operator.IN_LAST, str(days), "", "day")


RULE_TYPES: dict[str, Callable[[Any], Condition]] = {
    "genre_contains": _genre_contains,
    "comment_contains": _comment_contains,
    "bpm_range": _bpm_range,
    "rating_min": _rating_min,
    "added_last_days": _added_last_days,
}


def conditions(rules: Any) -> list[Condition]:
    """Validate the `rules:` list of a smart node and encode it."""
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules: expected a non-empty list")
    out = []
    for rule in rules:
        if not isinstance(rule, dict) or len(rule) != 1:
            raise ValueError(f"rules: each rule is a single `type: value` pair, got {rule!r}")
        ((key, value),) = rule.items()
        if key not in RULE_TYPES:
            known = ", ".join(RULE_TYPES)
            raise ValueError(f"rules: unknown rule type {key!r} (v1 supports: {known})")
        out.append(RULE_TYPES[key](value))
    return out


def build_smartlist(rules: Any) -> SmartList:
    """All rules must match (AND)."""
    smart = SmartList(logical_operator=LogicalOperator.ALL, auto_update=AUTO_UPDATE)
    for prop, operator, left, right, unit in conditions(rules):
        smart.add_condition(prop, operator, left, value_right=right, unit=unit)
    return smart


def describe(rules: Any) -> str:
    """The encoded conditions exactly as they will be written, for the dry-run."""
    parts = []
    for prop, operator, left, right, unit in conditions(rules):
        value = f"{left}..{right}" if right else left
        parts.append(f"{prop.value} {operator.name} {value}{' ' + unit if unit else ''}")
    return "[" + " AND ".join(parts) + "]"
