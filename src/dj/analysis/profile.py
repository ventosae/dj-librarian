"""dj-profile: the measured library profile (R-311; numbers from code, R-302; read-only, R-341).

`facts(lib)` measures a `dj.model.Library`; `write(folder, facts, source=...)` renders
`profile/stats.md` and `profile/facts.json`; `run(folder)` reads the folder's latest export,
does both and appends one line to `log.md`. `profile/habits.md` is Claude's (R-312): nothing
here writes it.

Door 1: stdlib + PyYAML only. Works on the Library model alone: never opens master.db, never
talks to Spotify, never opens an audio file (R-341). The only files it writes are the two
above and the log line, all inside the library folder, and only in a scaffolded dj-library
(valid library.yaml; never a drive root or the home folder: `common.library_folder`).

Facts (pure, JSON-serialisable, string keys, deterministic):

- `size`: `tracks`; `hours` (summed playing time, 1 decimal); `gb` (summed file sizes in
  10^9 bytes, 2 decimals).
- `formats`: `{kind: tracks}` for the kinds present (mp3, m4a, flac, wav, aiff, unknown).
- `bitrates`: tracks per bucket, every bucket present: `<192`, `192-255`, `256-319`, `320`,
  `lossless`, `unknown`. flac, wav and aiff are lossless whatever their bitrate; an m4a at
  400 kbps or more is ALAC, so lossless too (AAC stops at 320). Otherwise bitrate 0 is
  `unknown`, and `320` holds 320 kbps and above.
- `bitrate_formats`: `{bucket: {kind: tracks}}` for the buckets present (the stats.md table).
- `eras`: release year by decade, `{"1990s": n, ..., "unknown": n}`. A year outside
  1900-2099 (0 = not set) is unknown. `unknown` is always present.
- `timeline` (date added): `per_year` `{year: tracks}`, `first_added`, `last_added`,
  `busiest_year` `{year, tracks}`, `busiest_month` `{month: YYYY-MM, tracks}`, `undated`, and
  `last_365_days` (added in the 365 days up to `today`). Ties go to the earlier year/month.
- `fields`: `{field: {filled, pct}}` for FIELDS (genre, bpm, key, rating, colour, comment,
  label, my_tags); `null` for a field the source does not carry (the XML has no My Tags).
  Filled = non-empty text, BPM above 0, rating of 1 star or more, at least one My Tag.
- `empty`: tracks with the field empty, for EMPTY_FIELDS (artist, title, album, year and the
  FIELDS); `null` where the source does not carry the field.
- `not_in_source`: the measured fields the source does not carry.
- `duplicates`: `groups` (how many), `tracks` (in them), `top` (the 5 biggest groups:
  `track_ids`, `label_lines`, `formats`, ordered by size, then lowest track id) and `all`
  (every group's track ids). A group = tracks with the same
  `common.dup_key(artist, title, remixer)`: `norm_key`, plus the Remixer field when the title
  does not name that remix, so a remix is never grouped with its original.
- `headline`: exactly 5 `{label, value, note}` for the report (R-402). Rules, always in this
  order:
  1. Collection: value "<n> tracks"; note "<hours> hours, <gb> GB".
  2. Formats: value "<pct>% <kind>" for the most common format (ties: TRACK_KINDS order);
     note "<n> lossless, <n> at 320 kbps, <n> under 256 kbps" (+ ", <n> no bitrate").
  3. Eras: value "<oldest decade> to <newest decade>" (one decade: just it); note "most from
     the <decade> (<n> tracks)" (ties: the older decade) + "; <n> without a year".
  4. Weakest field: the carried field with the lowest share (ties: FIELDS order); value
     "<Field> <pct>%"; note "<n> of <tracks> tracks without it".
  5. Duplicate candidates when there is at least one group: value "<n> groups"; note "<n>
     tracks share an artist and title". Without duplicates, Timeline: value "<first year> to
     <last year>"; note "busiest month <YYYY-MM> (<n> tracks)".
  An empty library still gets all five, with "none" / "unknown" values.
- `reader`: `xml` or `db`, the reader that built the Library.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dj.analysis.common import (
    dup_key,
    library_folder,
    md_table,
    pct,
    provenance_line,
    resolve_xml,
    write_json,
)
from dj.libfolder import (
    LibraryFolder,
    LibraryFolderError,
    append_log,
    latest_export,
    relative,
    write_text,
)
from dj.model import TRACK_KINDS, Library, Track, id_sort_key
from dj.readers.xml import XML_FIELDS_MISSING, read_xml

MODULE = "dj.analysis.profile"
STATS_MD = "profile/stats.md"
FACTS_JSON = "profile/facts.json"
HABITS_MD = "profile/habits.md"  # Claude's (R-312); this module never writes it

FIELDS = ("genre", "bpm", "key", "rating", "colour", "comment", "label", "my_tags")
EMPTY_FIELDS = ("artist", "title", "album", "year") + FIELDS
FIELD_NAMES = {
    "artist": "Artist", "title": "Title", "album": "Album", "year": "Year", "genre": "Genre",
    "bpm": "BPM", "key": "Key", "rating": "Rating", "colour": "Colour", "comment": "Comment",
    "label": "Label", "my_tags": "My Tags",
}  # fmt: skip
BUCKETS = ("<192", "192-255", "256-319", "320", "lossless", "unknown")
BUCKET_NAMES = {
    "lossless": "Lossless", "320": "320 kbps", "256-319": "256-319 kbps",
    "192-255": "192-255 kbps", "<192": "Under 192 kbps",
}  # fmt: skip
LOSSLESS_KINDS = ("flac", "wav", "aiff")
ALAC_MIN_KBPS = 400  # an m4a at this bitrate or above is ALAC (lossless); AAC stops at 320
YEAR_RANGE = (1900, 2099)
RECENT_DAYS = 365
# Fields-used tiers for stats.md: (lowest whole percent, label), checked from the top.
# common.pct gives 100 only when every track has the field.
TIERS = ((100, "Every track"), (80, "Most tracks (80% or more)"), (20, "Some tracks (20% to 79%)"),
         (0, "Few tracks (under 20%)"))  # fmt: skip


# -- measuring -------------------------------------------------------------------------------


def bitrate_bucket(track: Track) -> str:
    """The bitrate bucket of one track (rules in the module docstring)."""
    if track.kind in LOSSLESS_KINDS or (track.kind == "m4a" and track.bitrate >= ALAC_MIN_KBPS):
        return "lossless"
    if track.bitrate <= 0:
        return "unknown"
    if track.bitrate < 192:
        return "<192"
    if track.bitrate < 256:
        return "192-255"
    if track.bitrate < 320:
        return "256-319"
    return "320"


def decade(year: int) -> str:
    """1994 -> "1990s"; 0 or a year outside 1900-2099 -> "unknown"."""
    low, high = YEAR_RANGE
    return f"{year // 10 * 10}s" if low <= year <= high else "unknown"


def filled(track: Track, field: str) -> bool:
    """Whether the DJ (or the file) filled `field` on this track."""
    value = getattr(track, field)
    if field == "year":
        return decade(value) != "unknown"
    if field in ("bpm", "rating"):
        return value > 0
    if field == "my_tags":
        return bool(value)
    return bool(str(value).strip())


def _format_of(track: Track) -> str:
    """"mp3 320 kbps", or the kind alone for lossless files and a missing bitrate."""
    if bitrate_bucket(track) in ("lossless", "unknown"):
        return track.kind
    return f"{track.kind} {track.bitrate} kbps"


def _not_carried(lib: Library) -> tuple[str, ...]:
    missing = set(XML_FIELDS_MISSING) if lib.source == "xml" else set()
    return tuple(f for f in EMPTY_FIELDS if f in missing)


def _size(tracks: list[Track]) -> dict[str, Any]:
    seconds = sum(max(t.duration_s, 0) for t in tracks)
    size = sum(max(t.file_size, 0) for t in tracks)
    return {"tracks": len(tracks), "hours": round(seconds / 3600, 1), "gb": round(size / 1e9, 2)}


def _counts(keys: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(keys).items()))


def _bitrates(tracks: list[Track]) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    counts = {bucket: 0 for bucket in BUCKETS}
    by_format: dict[str, Counter] = {}
    for track in tracks:
        bucket = bitrate_bucket(track)
        counts[bucket] += 1
        by_format.setdefault(bucket, Counter())[track.kind] += 1
    return counts, {b: dict(sorted(c.items())) for b, c in sorted(by_format.items())}


def _eras(tracks: list[Track]) -> dict[str, int]:
    eras = _counts([decade(t.year) for t in tracks])
    eras.setdefault("unknown", 0)
    return eras


def _busiest(counter: Counter) -> tuple[str, int] | None:
    if not counter:
        return None
    return min(counter.items(), key=lambda kv: (-kv[1], kv[0]))


def _timeline(tracks: list[Track], today: date) -> dict[str, Any]:
    dated = sorted(t.date_added for t in tracks if t.date_added is not None)
    years = Counter(str(d.year) for d in dated)
    months = Counter(d.strftime("%Y-%m") for d in dated)
    year, month = _busiest(years), _busiest(months)
    since = today - timedelta(days=RECENT_DAYS)
    return {
        "per_year": dict(sorted(years.items())),
        "first_added": dated[0].isoformat() if dated else None,
        "last_added": dated[-1].isoformat() if dated else None,
        "busiest_year": {"year": year[0], "tracks": year[1]} if year else None,
        "busiest_month": {"month": month[0], "tracks": month[1]} if month else None,
        "undated": len(tracks) - len(dated),
        "last_365_days": sum(since < d <= today for d in dated),
    }


def _fields(tracks: list[Track], missing: tuple[str, ...]) -> tuple[dict, dict]:
    shares: dict[str, Any] = {}
    empty: dict[str, Any] = {}
    for field in EMPTY_FIELDS:
        if field in missing:
            empty[field] = None
            if field in FIELDS:
                shares[field] = None
            continue
        n = sum(filled(t, field) for t in tracks)
        empty[field] = len(tracks) - n
        if field in FIELDS:
            shares[field] = {"filled": n, "pct": pct(n, len(tracks))}
    return shares, empty


def _duplicates(tracks: list[Track]) -> dict[str, Any]:
    groups: dict[str, list[Track]] = {}
    for track in tracks:  # tracks come sorted by id, so each group is too
        key = dup_key(track.artist, track.title, track.remixer)
        if key:
            groups.setdefault(key, []).append(track)
    found = sorted((g for g in groups.values() if len(g) > 1), key=lambda g: (-len(g), id_sort_key(g[0].id)))
    return {
        "groups": len(found),
        "tracks": sum(len(g) for g in found),
        "top": [
            {
                "track_ids": [t.id for t in group],
                "label_lines": [t.label_line for t in group],
                "formats": [_format_of(t) for t in group],
            }
            for group in found[:5]
        ],
        "all": [[t.id for t in group] for group in found],
    }


def dominant_format(formats: dict[str, int]) -> str:
    """The kind with the most tracks; ties go to the earlier kind in TRACK_KINDS."""
    return min(formats, key=lambda k: (-formats[k], TRACK_KINDS.index(k)))


def _n(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _headline(f: dict[str, Any]) -> list[dict[str, str]]:
    """The 5 stats that matter, by the rules in the module docstring."""
    size, total = f["size"], f["size"]["tracks"]
    out = [{
        "label": "Collection",
        "value": _n(total, "track"),
        "note": f"{size['hours']:.1f} hours, {size['gb']:.2f} GB",
    }]  # fmt: skip

    b = f["bitrates"]
    if total:
        kind = dominant_format(f["formats"])
        note = (f"{b['lossless']} lossless, {b['320']} at 320 kbps, "
                f"{b['<192'] + b['192-255']} under 256 kbps")  # fmt: skip
        if b["unknown"]:
            note += f", {b['unknown']} no bitrate"
        out.append({"label": "Formats", "value": f"{pct(f['formats'][kind], total)}% {kind}", "note": note})
    else:
        out.append({"label": "Formats", "value": "none", "note": "no tracks in the source"})

    decades = {k: v for k, v in f["eras"].items() if k != "unknown" and v}
    unknown = f["eras"].get("unknown", 0)
    if decades:
        first, last = min(decades), max(decades)
        top = min(decades, key=lambda k: (-decades[k], k))
        note = f"most from the {top} ({_n(decades[top], 'track')})"
        if unknown:
            note += f"; {unknown} without a year"
        out.append({"label": "Eras", "value": first if first == last else f"{first} to {last}", "note": note})
    else:
        out.append({"label": "Eras", "value": "unknown", "note": "no release years in the source"})

    carried = [k for k in FIELDS if f["fields"].get(k) is not None]
    if total and carried:
        weakest = min(carried, key=lambda k: (f["fields"][k]["pct"], f["fields"][k]["filled"], FIELDS.index(k)))
        share = f["fields"][weakest]
        out.append({
            "label": "Weakest field",
            "value": f"{FIELD_NAMES[weakest]} {share['pct']}%",
            "note": f"{total - share['filled']} of {_n(total, 'track')} without it",
        })  # fmt: skip
    else:
        out.append({"label": "Weakest field", "value": "none", "note": "no tracks to measure"})

    d, t = f["duplicates"], f["timeline"]
    if d["groups"]:
        out.append({
            "label": "Duplicate candidates",
            "value": _n(d["groups"], "group"),
            "note": f"{d['tracks']} tracks share an artist and title",
        })  # fmt: skip
    elif t["first_added"]:
        first, last = t["first_added"][:4], t["last_added"][:4]
        month = t["busiest_month"]
        out.append({
            "label": "Timeline",
            "value": first if first == last else f"{first} to {last}",
            "note": f"busiest month {month['month']} ({_n(month['tracks'], 'track')})",
        })  # fmt: skip
    else:
        out.append({"label": "Timeline", "value": "no dates", "note": "no track has a date added"})
    return out


def facts(lib: Library, *, today: date | None = None) -> dict[str, Any]:
    """Measure `lib`. Pure: the same Library and `today` always give the same dict.
    `today` (default: the current date) only sets the window of `timeline.last_365_days`."""
    today = today or date.today()
    tracks = sorted(lib.tracks.values(), key=lambda t: id_sort_key(t.id))
    missing = _not_carried(lib)
    bitrates, bitrate_formats = _bitrates(tracks)
    shares, empty = _fields(tracks, missing)
    out: dict[str, Any] = {
        "size": _size(tracks),
        "formats": _counts([t.kind for t in tracks]),
        "bitrates": bitrates,
        "bitrate_formats": bitrate_formats,
        "eras": _eras(tracks),
        "timeline": _timeline(tracks, today),
        "fields": shares,
        "empty": empty,
        "not_in_source": list(missing),
        "duplicates": _duplicates(tracks),
        "reader": lib.source,
    }
    out["headline"] = _headline(out)
    return out


# -- writing ---------------------------------------------------------------------------------


def _counted(counts: dict[str, int], limit: int = 5) -> str:
    """"flac 4, aiff 2, wav 2": biggest first (ties by name), at most `limit`, then "and N more"."""
    items = sorted(((k, v) for k, v in counts.items() if v), key=lambda kv: (-kv[1], kv[0]))
    text = ", ".join(f"{k} {v}" for k, v in items[:limit])
    return text + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _section_size(f: dict[str, Any]) -> list[str]:
    s = f["size"]
    rows = [["Tracks", s["tracks"]], ["Playing time", f"{s['hours']:.1f} hours"], ["On disk", f"{s['gb']:.2f} GB"]]
    return ["## Size", "", md_table(["Measure", "Value"], rows)]


def _section_formats(f: dict[str, Any]) -> list[str]:
    total = f["size"]["tracks"]
    lines = ["## Formats and bitrates", ""]
    if not total:
        return lines + ["No tracks in the source."]
    kind = dominant_format(f["formats"])
    lines += [f"Most common format: {kind}, {f['formats'][kind]} of {_n(total, 'track')} "
              f"({pct(f['formats'][kind], total)}%).", ""]  # fmt: skip
    b, by_format = f["bitrates"], f["bitrate_formats"]
    rows = [
        [BUCKET_NAMES[k], b[k], f"{pct(b[k], total)}%", _counted(by_format.get(k, {}))]
        for k in ("lossless", "320", "256-319", "192-255", "<192")
        if b[k]
    ]
    if rows:
        lines.append(md_table(["Quality", "Tracks", "Share", "Formats"], rows, where=FACTS_JSON))
    if b["unknown"]:
        lines += ["", f"{_n(b['unknown'], 'track')} with no bitrate in the source."]
    return lines


def _section_eras(f: dict[str, Any]) -> list[str]:
    total = f["size"]["tracks"]
    lines = ["## Eras", ""]
    decades = sorted(((k, v) for k, v in f["eras"].items() if k != "unknown" and v), key=lambda kv: (-kv[1], kv[0]))
    if decades:
        lines += ["Release year by decade, biggest first.", ""]
        rows = [[k, v, f"{pct(v, total)}%"] for k, v in decades]
        lines.append(md_table(["Decade", "Tracks", "Share"], rows, where=FACTS_JSON))
    else:
        lines.append("No release years in the source.")
    unknown = f["eras"].get("unknown", 0)
    if unknown and decades:
        lines += ["", f"{_n(unknown, 'track')} without a release year."]
    return lines


def _section_timeline(f: dict[str, Any]) -> list[str]:
    t = f["timeline"]
    lines = ["## Timeline", ""]
    if not t["first_added"]:
        return lines + ["No track has a date added."]
    year, month = t["busiest_year"], t["busiest_month"]
    rows = [
        ["First added", t["first_added"]],
        ["Last added", t["last_added"]],
        ["Busiest year", f"{year['year']}, {_n(year['tracks'], 'track')}"],
        ["Busiest month", f"{month['month']}, {_n(month['tracks'], 'track')}"],
        ["Last 365 days", _n(t["last_365_days"], "track")],
    ]
    lines += ["When tracks went into rekordbox (date added).", "", md_table(["Measure", "Value"], rows), ""]
    lines.append(f"Tracks per year ({_n(len(t['per_year']), 'year')}) are in {FACTS_JSON}.")
    if t["undated"]:
        lines.append(f"{_n(t['undated'], 'track')} without a date added.")
    return lines


def _section_fields(f: dict[str, Any]) -> list[str]:
    lines = ["## Fields used", ""]
    if not f["size"]["tracks"]:
        return lines + ["No tracks in the source."]
    tiers: dict[str, list[tuple[str, int]]] = {}
    for field in FIELDS:
        share = f["fields"].get(field)
        if share is None:
            continue
        tier = next(label for low, label in TIERS if share["pct"] >= low)
        tiers.setdefault(tier, []).append((FIELD_NAMES[field], share["pct"]))
    rows = []
    for _low, label in TIERS:
        if label in tiers:
            named = sorted(tiers[label], key=lambda kv: -kv[1])  # stable: FIELDS order on ties
            shown = ", ".join(f"{name} {p}%" for name, p in named[:5])
            rows.append([label, shown + (f" and {len(named) - 5} more" if len(named) > 5 else "")])
    missing = [FIELD_NAMES[k] for k in FIELDS if f["fields"].get(k) is None]
    if missing:
        rows.append(["Not in this source", ", ".join(missing)])
    lines += ["Share of tracks with the field filled in.", "", md_table(["How often", "Fields"], rows)]
    return lines


def _section_empty(f: dict[str, Any]) -> list[str]:
    total = f["size"]["tracks"]
    lines = ["## Empty fields", ""]
    gaps = [(k, n) for k, n in f["empty"].items() if n]
    gaps.sort(key=lambda kv: (-kv[1], EMPTY_FIELDS.index(kv[0])))
    if not gaps:
        return lines + ["No empty fields." if total else "No tracks in the source."]
    rows = [[FIELD_NAMES[k], n, f"{pct(n, total)}%"] for k, n in gaps]
    lines += ["Tracks with the field left empty, most first.", "",
              md_table(["Field", "Empty", "Share"], rows, where=FACTS_JSON)]  # fmt: skip
    return lines


def _section_duplicates(f: dict[str, Any]) -> list[str]:
    d = f["duplicates"]
    lines = ["## Duplicate candidates", ""]
    if not d["groups"]:
        return lines + ["None found: no artist and title appears twice."]
    lines += [
        f"{_n(d['groups'], 'group')}, {d['tracks']} tracks: the same artist and title once case, "
        "accents and (Original Mix) are set aside. Remixes (in the title or the Remixer field), "
        "edits and dubs stay apart. Which copy to keep is your call.",
        "",
    ]
    rows = [[g["label_lines"][0], len(g["track_ids"]), ", ".join(g["formats"])] for g in d["top"]]
    extra = d["groups"] - len(rows)
    table = md_table(["Track", "Copies", "Formats"], rows)
    if extra:
        table += f"\n\nAnd {extra} more in {FACTS_JSON}."
    lines.append(table)
    return lines


def _section_headline(f: dict[str, Any]) -> list[str]:
    rows = [[h["label"], h["value"], h["note"]] for h in f["headline"]]
    return ["## The 5 stats that matter", "", md_table(["Stat", "Value", "Note"], rows)]


def render(f: dict[str, Any], *, source: str, today: date | None = None) -> str:
    """The text of profile/stats.md: title, provenance line, then the sections."""
    blocks = [["# Library profile", "", provenance_line(MODULE, source, today)]]
    for section in (_section_size, _section_formats, _section_eras, _section_timeline, _section_fields,
                    _section_empty, _section_duplicates, _section_headline):  # fmt: skip
        blocks.append(section(f))
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"


def _sidecar(f: dict[str, Any], source: str, today: date | None) -> dict[str, Any]:
    return {**f, "provenance": {"module": MODULE, "source": source, "date": (today or date.today()).isoformat()}}


def write(
    folder: LibraryFolder | str | Path, facts: dict[str, Any], *, source: str, today: date | None = None
) -> list[Path]:
    """Write profile/stats.md and profile/facts.json (replacing the tool's previous ones).
    `source` = the export read, relative to the folder. Never writes profile/habits.md.
    Only into a scaffolded dj-library (`common.library_folder`; NotALibraryFolder otherwise)."""
    folder = library_folder(folder)
    text = render(facts, source=source, today=today)  # checks `source` before anything is written
    folder.profile.mkdir(exist_ok=True)
    stats = write_text(folder.root / STATS_MD, text)
    data = write_json(folder.root / FACTS_JSON, _sidecar(facts, source, today))
    return [stats, data]


def _source_name(folder: LibraryFolder, path: Path) -> str:
    """The export relative to the folder; an XML outside the folder by its file name only, so no
    absolute path goes into a file in the library folder."""
    try:
        return relative(folder.root, path)
    except LibraryFolderError:
        return path.name


def run(folder: LibraryFolder | str | Path, *, xml: str | Path | None = None, today: date | None = None) -> dict[str, Any]:
    """Profile the latest export (or `xml`): facts, write, one log line.
    Returns {"written": [relative paths], "headline": [...], "source": relative export}.

    The folder is resolved and checked first (`common.library_folder`): a folder without a
    valid library.yaml, a drive root or the home folder -> NotALibraryFolder, nothing written.
    A relative `xml` is looked up in the library folder first, then in the current folder;
    the one file found is both read and named in the provenance line."""
    folder = library_folder(folder)
    path = resolve_xml(folder.root, xml) if xml else latest_export(folder.root)
    lib = read_xml(path)
    measured = facts(lib, today=today)
    source = _source_name(folder, path)
    written = write(folder, measured, source=source, today=today)
    counts = {"tracks": measured["size"]["tracks"], "duplicates": measured["duplicates"]["groups"]}
    append_log(folder.root, "profile", counts, STATS_MD)
    return {
        "written": [folder.relative(p) for p in written],
        "headline": measured["headline"],
        "source": source,
    }
