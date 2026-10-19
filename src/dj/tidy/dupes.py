"""Duplicate detection. Pure. Report only: nothing here deletes, moves or decides."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from dj.match import normalise_artist, parse_title, versions_compatible
from dj.tidy.checks import Item

EXACT, FUZZY = "exact", "fuzzy"
LOSSLESS = {"flac", "wav", "aiff"}


@dataclass(frozen=True)
class DupeGroup:
    kind: str
    members: tuple[Item, ...]
    keeper: Item | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "keeper": str(self.keeper.file.path) if self.keeper else None,
            "reason": self.reason,
            "members": [member_dict(m) for m in self.members],
        }


def member_dict(item: Item) -> dict[str, Any]:
    s = item.file.stream
    return {
        "file": str(item.file.path),
        "rb_content_id": item.rb.content_id if item.rb else None,
        "container": item.file.container,
        "bitrate_kbps": s.bitrate_kbps if s else None,
        "duration_s": round(item.duration_s, 1) if item.duration_s else None,
        "cues": item.rb.cue_count if item.rb else None,
        "size": item.file.size,
        "sha256": item.file.sha256,
    }


def exact_groups(items: Sequence[Item]) -> list[DupeGroup]:
    by_hash: dict[str, list[Item]] = {}
    for it in items:
        if it.file.sha256:
            by_hash.setdefault(it.file.sha256, []).append(it)
    out = []
    for members in by_hash.values():
        if len(members) >= 2:
            keeper, reason = suggest_keeper(members)
            out.append(DupeGroup(EXACT, tuple(members), keeper, reason))
    return out


def fuzzy_key(item: Item) -> tuple[str, str, str] | None:
    """(artist bag, base title, version) from tags, else the rekordbox row, else the filename."""
    tags, rb, parsed = item.file.tags, item.rb, item.parsed
    artist = title = mix = ""
    if tags and tags.artist and tags.title:
        artist, title, mix = " ".join(tags.artist), tags.title, tags.mix
    elif rb and rb.artist and rb.title:
        artist, title, mix = rb.artist, rb.title, rb.subtitle
    elif parsed and parsed.artist and parsed.title:
        artist, title, mix = parsed.artist, parsed.title, parsed.mix or ""
    if not artist or not title:
        return None
    text = f"{title} ({mix})" if mix and mix.lower() not in title.lower() else title
    base, version = parse_title(text, artist)
    return normalise_artist(artist), base, version


def fuzzy_groups(items: Sequence[Item], tolerance_s: int = 2, skip: Sequence[DupeGroup] = ()) -> list[DupeGroup]:
    """Same artist bag + base title, compatible version words, durations within tolerance."""
    exact_sets = {frozenset(id(m) for m in g.members) for g in skip}
    buckets: dict[tuple[str, str], list[tuple[Item, str]]] = {}
    for it in items:
        key = fuzzy_key(it)
        if key:
            buckets.setdefault((key[0], key[1]), []).append((it, key[2]))
    out = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        clusters: list[list[tuple[Item, str]]] = []
        for it, version in sorted(members, key=lambda m: m[0].duration_s):
            for cluster in clusters:
                if all(versions_compatible(version, v) and _close(it, other, tolerance_s) for other, v in cluster):
                    cluster.append((it, version))
                    break
            else:
                clusters.append([(it, version)])
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            group_items = tuple(m for m, _ in cluster)
            if frozenset(id(m) for m in group_items) in exact_sets:
                continue
            keeper, reason = suggest_keeper(group_items)
            out.append(DupeGroup(FUZZY, group_items, keeper, reason))
    return out


def _close(a: Item, b: Item, tolerance_s: int) -> bool:
    if not a.duration_s or not b.duration_s:
        return True  # unknown length never blocks a match; the report shows both
    return abs(a.duration_s - b.duration_s) <= tolerance_s


def _quality_rank(item: Item) -> int:
    c = item.file.container
    if c in LOSSLESS:
        return 3
    kbps = item.file.stream.bitrate_kbps if item.file.stream and item.file.stream.bitrate_kbps else 0
    if c == "mp3" and kbps >= 320:
        return 2
    return 1 if c else 0


def _tag_completeness(item: Item) -> int:
    t = item.file.tags
    if not t:
        return 0
    return int(bool(t.artist)) + int(bool(t.title)) + int(t.has_art)


def suggest_keeper(members: Sequence[Item]) -> tuple[Item | None, str]:
    """lossless > 320 MP3 > rest; then the copy rekordbox knows, more cues, higher rating,
    fuller tags, shorter path. Suggests only: the DJ decides, rekordbox deletes."""
    if not members:
        return None, ""

    def key(it: Item):
        rb = it.rb
        return (
            _quality_rank(it),
            1 if rb else 0,
            rb.cue_count if rb else 0,
            rb.rating if rb else 0,
            _tag_completeness(it),
            -len(str(it.file.path)),
        )

    best = max(members, key=key)
    why = []
    c = best.file.container
    if c in LOSSLESS:
        why.append(f"lossless {c}")
    elif c == "mp3" and best.file.stream and best.file.stream.bitrate_kbps:
        why.append(f"{best.file.stream.bitrate_kbps} kbps mp3")
    if best.rb:
        why.append("in rekordbox")
        if best.rb.cue_count:
            why.append(f"{best.rb.cue_count} cue(s)")
        if best.rb.rating:
            why.append(f"rating {best.rb.rating}")
    if _tag_completeness(best) == 3:
        why.append("full tags + art")
    return best, "; ".join(why) or "first by path"
