"""The charts of the library report (dj.report): the crate wall, the six axes, the hover layers
over the sleeves and the colours of the proposal sleeves (R-403, R-404, R-408, R-1405).

Door 1: stdlib only, plus dj.design, dj.sleeve and dj.treeschema. Every function is pure: facts
in, an SVG or HTML string out. The page around them (dj.report) owns the CSS: every mark here
carries classes, never a colour, so the Booth and Day themes of docs/design.md repaint them.

Colour classes: `s1` ... `s8` set `--lane` to categorical slot 1..8, `s0` to the Other grey. A
lane keeps its slot everywhere on the page (dj.analysis.identity gives lanes their slots by BPM,
slowest first). Marks never carry text in their colour; labels use the text classes.

    crate_wall(graph, structure, identity) -> Wall (svg, legend entries, rows, labels, arcs)
        One row per top-level folder (and one "Top level" row for loose playlists), one bar per
        playlist below that folder (any depth), length = its tracks on one shared axis ("tracks,
        playlists end to end": the ticks count along the whole row), bars laid end to end with a
        2 px gap. Every bar of a folder row wears
        the folder's lane: the lane (identity `lanes[].playlists`) that holds most of the row's
        tracks, ties to the slower lane, Other when none. The legend says so ("row colour"), and
        a bar whose own lane differs names both in its tooltip. A loose playlist wears its own
        lane. A dump (dj-structure rule) is hatched with an SVG pattern; an empty or smart
        playlist is an outline. The top overlapping pairs are arcs between the two bars. Direct
        labels on at most 4 marks in all, the arc labels ("5 shared") included: the bars get
        what the arcs leave (dumps, the first overlap pair, then the biggest), never every bar. Drawn twice: a wide layout (names in a column) and a phone layout (each
        row's name left and its counts right on a line above it, a viewBox about as wide as a
        phone draws it); the page's CSS shows one of them. In the phone layout an arc that
        crosses a name line passes through the free space between the name and the counts.
    axes_chart(identity) -> svg
        The six axes, 0-100, one thin bar each. The two that pick the archetype wear the ink,
        the rest the Other grey (emphasis, not a series: slot colours stay with the lanes).
    sleeve_hits(identity) / mini_hits(identity, owners)
        Transparent cells laid over a sleeve (same viewBox) so every fingerprint cell, or every
        band of a proposal sleeve, has a tooltip.
    proposal_colours(nodes, identity, bpm_rows) -> (band -> slot, branches)
        How a proposal recolours the fingerprint, with the lane slots of the page: a colour
        always names a lane. A branch is a top-level node of the proposal's tree. It wears the
        slot of the lane that fills most of it (the lane playlists it copies, by tracks; ties
        to the slower lane), or none when no lane playlist goes into it. Two branches never
        share a slot: the one that takes more of that lane keeps it (ties: tree order), the
        other wears none. Each playlist the proposal copies (`from`) spreads its tracks evenly
        over the BPM bands its range covers (taste/facts.json `bpm_playlists`: lo..hi, each end
        widened by half a BPM as identity does); a band goes to the branch that would receive
        most of those tracks (ties: the earlier branch) and takes that branch's slot, so the
        mini sleeve shows which lanes a proposal keeps apart and which it merges. A band no
        copied playlist reaches, or one that lands in a branch without a slot, is grey.

Every element that answers hover also answers keyboard focus (`tabindex="0"`), carries its
tooltip text in `data-tip` ("value · name · detail": the value leads) and has a hit area larger
than the mark, at least 24 units in its short direction. No id outside the given prefix, no
URL, no script.
"""

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from dj import design
from dj import sleeve as sleeve_mod
from dj.treeschema import TreeNode

# -- escaping ------------------------------------------------------------------------------------

_HTTP = re.compile(r"[hH](?=[tT][tT][pP])")


def defang(text: str) -> str:
    """Write the "h" of any "http" as a character reference: the page holds no "http" at all,
    not even inside a name that happens to contain one. Safe in text and attribute values."""
    return _HTTP.sub(lambda m: f"&#{ord(m.group())};", text)


def esc(text: Any) -> str:
    """HTML-escaped text (quotes too). "://" and "http" are written with character references,
    so a library name can never put a URL into the page."""
    return defang(html.escape(str(text), quote=True).replace("://", ":&#47;&#47;"))


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def width_of(text: str, size: float, bold: bool = False) -> float:
    """Estimated width of text at `size` (viewBox units). dj.sleeve's em table is drawn for a heavy
    display face; the system UI faces run about 10% narrower at text weights, so this stays a
    little generous on every platform and labels never clip."""
    return sleeve_mod.text_em(text, 0.0) * size * (0.98 if bold else 0.9)


def cut(text: str, room: float, size: float, bold: bool = False) -> str:
    """`text` on one line, shortened with an ellipsis to fit `room` at `size`."""
    text = " ".join(str(text).split())
    if width_of(text, size, bold) <= room:
        return text
    out = ""
    for ch in text:
        if width_of(out + ch + "…", size, bold) > room:
            break
        out += ch
    return (out.rstrip() or text[:1]) + "…"


def _n(x: float) -> str:
    """One decimal, no "-0": the same number is written the same way every time."""
    value = round(x, 1)
    if value == 0:
        value = 0.0
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def slot_class(slot: Any) -> str:
    """The colour class of a slot: s1..s8, or s0 (Other) for None and anything past 8."""
    if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= design.SLOTS:
        return "s0"
    return f"s{slot}"


def bar_path(x: float, y: float, w: float, h: float, round_end: bool = True, r: float = 4.0) -> str:
    """A bar square at its baseline (left) and, with `round_end`, rounded 4 px at its data end."""
    if not round_end or w <= r + 0.5:
        return f"M{_n(x)} {_n(y)}h{_n(w)}v{_n(h)}h{_n(-w)}z"
    return (f"M{_n(x)} {_n(y)}h{_n(w - r)}a{_n(r)} {_n(r)} 0 0 1 {_n(r)} {_n(r)}v{_n(h - 2 * r)}"
            f"a{_n(r)} {_n(r)} 0 0 1 {_n(-r)} {_n(r)}h{_n(-(w - r))}z")  # fmt: skip


def band_words(band: str) -> str:
    """A BPM band as a DJ says it: "<100" -> "under 100 BPM", "135+" -> "135 BPM and up"."""
    if band.startswith("<"):
        return f"under {band[1:]} BPM"
    if band.endswith("+"):
        return f"{band[:-1]} BPM and up"
    return f"{band} BPM"


# -- lanes ---------------------------------------------------------------------------------------


def lane_rows(identity: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    return [lane for lane in (identity or {}).get("lanes") or [] if isinstance(lane, Mapping)]


def lane_of(identity: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    """playlist path -> the lane that lists it (the first one, lanes in BPM order)."""
    out: dict[str, Mapping[str, Any]] = {}
    for lane in lane_rows(identity):
        for path in lane.get("playlists") or []:
            out.setdefault(str(path), lane)
    return out


# -- the crate wall ------------------------------------------------------------------------------

STRIP = 16  # bar thickness (thin: at most 24, docs/design.md)
SEG_GAP = 2  # surface gap between touching bars
OUTLINE_W, OUTLINE_STEP = 14, 24  # an empty playlist: its outline, and the room its hit area gets
MAX_OUTLINES = 5  # outlines drawn per row; the rest are counted in the row's tooltip
MAX_ROWS = 10  # folder rows; the rest are named in a closing line
MAX_LABELS = 4
MAX_ARCS = 3
NAME_SIZE, SUB_SIZE, LABEL_SIZE = 13, 11, 11
TOP = 2
AXIS_H = 26
HIT_MIN = 24  # the short side of a hit area (docs/design.md, Interaction), room allowing
LOOSE = "Top level"
UNIT = "tracks, playlists end to end"  # the ticks run along a whole row, bar after bar


@dataclass(frozen=True)
class Geometry:
    """Where things sit in one layout of the wall (viewBox units)."""

    width: float
    bar_x: float
    bar_w: float
    label_w: float  # room for the folder name: a column left of the bars, or a line above them
    name_line: float  # height of the name line above each row (0: the names sit in a column)
    above: float = 15  # room for a label above a bar
    below: float = 15  # room for a label below a bar
    gap: float = 8
    unit_line: float = 0  # a line of its own under the ticks for the axis unit (0: left of the axis)

    @property
    def pitch(self) -> float:
        return self.name_line + self.above + STRIP + self.below + self.gap

    def row_top(self, i: int) -> float:
        return TOP + i * self.pitch

    def strip_top(self, i: int) -> float:
        return self.row_top(i) + self.name_line + self.above


# Wide: names in a column left of the bars. Narrow (phones): each row's name left and its counts
# right on a line above it, and a viewBox about as wide as a phone draws it, so the text keeps
# its size.
WIDE = Geometry(width=560, bar_x=140, bar_w=404, label_w=128, name_line=0, unit_line=16)
NARROW = Geometry(width=330, bar_x=0, bar_w=322, label_w=330, name_line=18, above=16, gap=10, unit_line=18)


@dataclass
class Bar:
    path: str
    name: str
    tracks: int | None
    slot: int | None  # the colour it wears: its row's lane in a folder row, its own lane when loose
    row: int
    dump: bool = False
    share: float | None = None
    lane: str | None = None  # its own lane's label
    own: int | None = None  # its own lane's slot
    x: float = 0.0
    w: float = 0.0
    outline: bool = False


@dataclass
class Row:
    kind: str  # "folder" | "loose"
    name: str
    path: str
    tracks: int | None  # the folder's distinct tracks (graph.json), loose: sum of its playlists
    bars: list[Bar] = field(default_factory=list)
    slot: int | None = None
    lane: str | None = None  # the label of the row's lane (folder rows)
    hidden_outlines: int = 0


@dataclass
class Wall:
    svg: str
    legend: list[tuple[str, str]]  # (kind, label): "head", "s1".."s8"/"s0", "dump", "empty", "arc"
    rows: list[Row]
    labels: list[str]
    arcs: int
    more_folders: int


def _graph_index(graph: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], dict[Any, Mapping[str, Any]], dict[Any, list]]:
    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, Mapping) and n.get("id") is not None]
    by_id = {n["id"]: n for n in nodes}
    kids: dict[Any, list] = {}
    for edge in graph.get("edges") or []:
        if isinstance(edge, Mapping) and edge.get("target") in by_id:
            kids.setdefault(edge.get("source"), []).append(edge["target"])
    return nodes, by_id, kids


def _playlists_below(node_id: Any, by_id: Mapping[Any, Mapping[str, Any]], kids: Mapping[Any, list]) -> list[Mapping[str, Any]]:
    out, seen = [], set()

    def visit(nid: Any) -> None:
        for child in kids.get(nid, []):
            if child in seen:
                continue
            seen.add(child)
            node = by_id[child]
            if node.get("kind") in ("playlist", "smart"):
                out.append(node)
            visit(child)

    visit(node_id)
    return out


def wall_rows(graph: Mapping[str, Any], structure: Mapping[str, Any] | None,
              identity: Mapping[str, Any] | None) -> tuple[list[Row], int]:  # fmt: skip
    """The rows of the crate wall and how many folder rows were left out (MAX_ROWS)."""
    nodes, by_id, kids = _graph_index(graph)
    dumps = {}
    for d in (((structure or {}).get("dumps") or {}).get("top") or []):
        if isinstance(d, Mapping) and d.get("path") is not None:
            dumps[str(d["path"])] = d.get("share")
    lanes = lane_of(identity)
    by_slot = {lane.get("slot"): lane for lane in lane_rows(identity)}
    has_lanes = bool(by_slot)

    def bar(node: Mapping[str, Any], row: int) -> Bar:
        path = str(node.get("path", node.get("id")))
        tracks = node.get("tracks") if node.get("kind") == "playlist" else None
        lane = lanes.get(path)
        own = (lane.get("slot") if lane else None) if has_lanes else 1
        return Bar(path=path, name=str(node.get("name", path)), tracks=tracks, row=row, slot=own, own=own,
                   dump=path in dumps, share=dumps.get(path), lane=str(lane.get("label")) if lane else None)  # fmt: skip

    rows: list[Row] = []
    tops = [n for n in nodes if n.get("depth") == 1]
    folders = [n for n in tops if n.get("kind") == "folder"]
    loose = [n for n in tops if n.get("kind") in ("playlist", "smart")]
    for node in folders[:MAX_ROWS]:
        row = Row("folder", str(node.get("name", "")), str(node.get("path", node["id"])), node.get("tracks"))
        row.bars = [bar(p, len(rows)) for p in _playlists_below(node["id"], by_id, kids)]
        if has_lanes:
            weight: dict[int, int] = {}
            for b in row.bars:
                if isinstance(b.own, int) and isinstance(b.tracks, int):
                    weight[b.own] = weight.get(b.own, 0) + b.tracks
            row.slot = min(weight, key=lambda s: (-weight[s], s)) if weight else None
            row.lane = str(by_slot[row.slot].get("label")) if row.slot in by_slot else None
        else:
            row.slot = 1
        for b in row.bars:
            b.slot = row.slot
        rows.append(row)
    if loose:
        row = Row("loose", LOOSE, "", None)
        row.bars = [bar(p, len(rows)) for p in loose]
        row.tracks = sum(b.tracks or 0 for b in row.bars)
        rows.append(row)
    return rows, max(0, len(folders) - MAX_ROWS)


def _ticks(top: float) -> list[int]:
    """Clean tick values from 0 to at most `top`: 3 to 5 of them, steps of 1, 2 or 5 x 10^k."""
    if top <= 0:
        return [0]
    raw = top / 4
    power = 10 ** math.floor(math.log10(raw)) if raw >= 1 else 1
    step = next((m * power for m in (1, 2, 5, 10) if m * power >= raw), 10 * power)
    step = max(1, int(step))
    return list(range(0, int(top) + 1, step))


def _filled(b: Bar) -> bool:
    return isinstance(b.tracks, int) and b.tracks > 0


def _layout(rows: Sequence[Row], geo: Geometry) -> float:
    """Place every bar; returns the scale (viewBox units per track) shared by all rows."""
    scale = None
    for row in rows:
        row.hidden_outlines = 0
        total = sum(b.tracks for b in row.bars if _filled(b))
        outlines = min(MAX_OUTLINES, sum(1 for b in row.bars if not _filled(b)))
        extra = outlines * OUTLINE_STEP + (6 if outlines and total else 0)
        if total:
            fit = (geo.bar_w - extra) / total
            scale = fit if scale is None else min(scale, fit)
    scale = scale or 1.0
    for row in rows:
        cum, end = 0, geo.bar_x
        filled = [b for b in row.bars if _filled(b)]
        for b in filled:
            b.outline = False
            b.x = geo.bar_x + cum * scale
            b.w = max(1.0, b.tracks * scale - SEG_GAP)
            cum += b.tracks
            end = b.x + b.w
        x = end + (6 + (OUTLINE_STEP - OUTLINE_W) / 2 if filled else 0)  # its hit area clears the last bar
        drawn = 0
        for b in row.bars:
            if _filled(b):
                continue
            b.outline = True
            if drawn >= MAX_OUTLINES:
                row.hidden_outlines += 1
                b.w = 0
                continue
            b.x, b.w = x, OUTLINE_W
            x += OUTLINE_STEP
            drawn += 1
    return scale


def _bar_tip(b: Bar, row: Row | None = None) -> str:
    """The tooltip of a bar: tracks, path, dump share, lane. In a folder row whose colour (the
    folder's lane) is not the playlist's own lane, both are named."""
    if b.tracks is None:
        return f"smart · {b.path} · tracks not listed in this source"
    if b.tracks == 0:
        return f"0 tracks · {b.path} · empty"
    parts = [plural(b.tracks, "track"), b.path]
    if b.dump:
        share = f": {round(float(b.share) * 100)}% of the collection" if isinstance(b.share, (int, float)) else ""
        parts.append(f"a dump{share}")
    own = f"lane {b.lane} BPM" if b.lane else "no lane"
    if row is not None and row.kind == "folder" and row.lane and b.own != row.slot:
        parts.append(f"{own} (row colour: {row.name}, {row.lane} BPM)")
    elif b.lane:
        parts.append(own)
    return " · ".join(parts)


class _Boxes:
    """Where text and arcs already sit: a label is placed only where it touches none of them."""

    def __init__(self) -> None:
        self.boxes: list[tuple[float, float, float, float]] = []

    def free(self, box: tuple[float, float, float, float], pad: float = 6, vpad: float = 2) -> bool:
        x0, y0, x1, y1 = box
        return all(x1 + pad <= a or x0 - pad >= c or y1 + vpad <= b or y0 - vpad >= d for a, b, c, d in self.boxes)

    def add(self, box: tuple[float, float, float, float]) -> None:
        self.boxes.append(box)


def _row_sub(row: Row) -> str:
    n = len(row.bars)
    if row.kind == "loose":
        return plural(n, "loose playlist")
    if isinstance(row.tracks, int):
        return f"{plural(n, 'playlist')} · {plural(row.tracks, 'track')}"
    return plural(n, "playlist")


Point = tuple[float, float]
Segment = tuple[Point, Point, Point, Point]  # a cubic: start, two controls, end


def _straight(p: Point, q: Point) -> Segment:
    return (p, (p[0] + (q[0] - p[0]) / 3, p[1] + (q[1] - p[1]) / 3),
            (p[0] + 2 * (q[0] - p[0]) / 3, p[1] + 2 * (q[1] - p[1]) / 3), q)  # fmt: skip


def _path_d(segments: Sequence[Segment]) -> str:
    out = [f"M{_n(segments[0][0][0])} {_n(segments[0][0][1])}"]
    for _p0, c1, c2, p3 in segments:
        out.append(f"C{_n(c1[0])} {_n(c1[1])} {_n(c2[0])} {_n(c2[1])} {_n(p3[0])} {_n(p3[1])}")
    return "".join(out)


def _samples(segments: Sequence[Segment], steps: int = 12) -> list[Point]:
    """Points along the path, `steps` per segment: for keeping labels off the arc."""
    out: list[Point] = []
    for p0, c1, c2, p3 in segments:
        for i in range(steps + 1):
            t = i / steps
            u = 1 - t
            x = u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p3[0]
            y = u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p3[1]
            out.append((x, y))
    return out


def _arc_path(a: Bar, b: Bar, geo: Geometry,
              bands: Mapping[int, tuple[float, float, float, float]]) -> tuple[list[Segment], Point]:  # fmt: skip
    """The arc between two bars (segments, its middle). Same row: a low hump above the strip.
    Two rows: from the bottom of the upper bar to the top of the lower one. A name line it has
    to cross (the phone layout: `bands`, row -> (top, bottom, free x from, free x to)) is crossed
    in the free space between the row's name and its counts."""
    ax, bx = a.x + a.w / 2, b.x + b.w / 2
    if a.row == b.row:
        y = geo.strip_top(a.row)
        lift = min(geo.above + 4, 10 + abs(bx - ax) * 0.12)
        return [((ax, y), (ax, y - lift), (bx, y - lift), (bx, y))], ((ax + bx) / 2, y - lift * 0.75)
    y0, y1 = geo.strip_top(a.row) + STRIP, geo.strip_top(b.row)
    crossed = [bands[r] for r in range(a.row + 1, b.row + 1) if r in bands]
    lo, hi = min(ax, bx), max(ax, bx)
    g0 = max((c[2] for c in crossed), default=-math.inf)
    g1 = min((c[3] for c in crossed), default=math.inf)
    if not crossed or g0 > g1 or (g0 <= lo and hi <= g1):
        bend = (y1 - y0) * 0.55
        return [((ax, y0), (ax, y0 + bend), (bx, y1 - bend), (bx, y1))], ((ax + bx) / 2, (y0 + y1) / 2)
    xc = min(max((ax + bx) / 2, g0), g1)
    top, bottom = crossed[0][0] - 1, crossed[-1][1] + 1
    d1, d2 = (top - y0) * 0.55, (y1 - bottom) * 0.55
    segments = [((ax, y0), (ax, y0 + d1), (xc, top - d1), (xc, top)), _straight((xc, top), (xc, bottom)),
                ((xc, bottom), (xc, bottom + d2), (bx, y1 - d2), (bx, y1))]  # fmt: skip
    return segments, (xc, (top + bottom) / 2)


def _hit_rect(b: Bar, row: Row, strip: float, geo: Geometry) -> str:
    """The hit area of a bar: HIT_MIN wide at least, centred on the bar, but never over a
    neighbour's mark (it stops halfway to it), and STRIP + 12 tall."""
    drawn = sorted((x for x in row.bars if x.w > 0), key=lambda x: x.x)
    i = drawn.index(b)
    left = (drawn[i - 1].x + drawn[i - 1].w + b.x) / 2 if i else 0.0
    right = (b.x + b.w + drawn[i + 1].x) / 2 if i + 1 < len(drawn) else geo.width
    half = max(b.w + 2, HIT_MIN) / 2
    x0, x1 = max(left, b.x + b.w / 2 - half), min(right, b.x + b.w / 2 + half)
    return f'<rect class="hit-area" x="{_n(x0)}" y="{_n(strip - 6)}" width="{_n(x1 - x0)}" height="{STRIP + 12}"/>'


def _wall_svg(rows: Sequence[Row], more: int, structure: Mapping[str, Any] | None, geo: Geometry, uid: str,
              cls: str) -> tuple[str, list[str], int]:  # fmt: skip
    """One layout of the wall: (svg, labelled paths, arcs drawn)."""
    scale = _layout(rows, geo)
    bars = [b for row in rows for b in row.bars]
    by_path = {b.path: b for b in bars if b.w > 0}
    height = TOP + len(rows) * geo.pitch + AXIS_H + geo.unit_line + (18 if more else 0)
    hatch = f"{uid}hatch"
    out = [
        f'<svg class="{cls}" viewBox="0 0 {_n(geo.width)} {_n(height)}" role="img" '
        f'aria-labelledby="{uid}title {uid}desc">',
        f'<title id="{uid}title">Crate wall: your top-level folders and the playlists in them</title>',
        f'<desc id="{uid}desc">One row per top-level folder, one bar per playlist, the longer the bar the more '
        "tracks; hatched bars are dumps, outlines are empty playlists, arcs join playlists that share tracks.</desc>",
        f'<defs><pattern id="{hatch}" patternUnits="userSpaceOnUse" width="6" height="6" '
        'patternTransform="rotate(45)"><rect class="hatch-line" width="2.4" height="6"/></pattern></defs>',
    ]
    # the recessive grid and the one axis
    longest = max((sum(b.tracks for b in r.bars if _filled(b)) for r in rows), default=0)
    axis_y = TOP + len(rows) * geo.pitch - geo.gap + 2
    grid = []
    for value in _ticks(longest):
        x = geo.bar_x + value * scale
        grid.append(f'<path class="gridline" d="M{_n(x)} {_n(geo.strip_top(0) - 6)}V{_n(axis_y)}"/>')
        anchor = "start" if geo.bar_x == 0 and value == 0 else "middle"
        grid.append(f'<text class="t-tick" x="{_n(x)}" y="{_n(axis_y + 15)}" text-anchor="{anchor}">{value}</text>')
    if geo.unit_line:
        unit_x, unit_y = geo.width, axis_y + 15 + geo.unit_line
    else:
        unit_x, unit_y = geo.bar_x - 10, axis_y + 15
    grid.append(f'<text class="t-tick" x="{_n(unit_x)}" y="{_n(unit_y)}" text-anchor="end">{UNIT}</text>')
    out.append(f'<g class="grid">{"".join(grid)}</g>')

    # the rows
    names = []
    boxes = _Boxes()  # where text and arcs already sit: arc and bar labels keep clear of them
    bands: dict[int, tuple[float, float, float, float]] = {}  # phone: row -> its name line, free x
    for i, row in enumerate(rows):
        strip = geo.strip_top(i)
        mid = strip + STRIP / 2
        sub = _row_sub(row)
        out.append(f'<g class="row" data-row="{row.kind}">')
        if geo.name_line:  # one line above the row: the name left, its counts right
            y = geo.row_top(i) + 13
            name = cut(row.name, geo.width * 0.55, NAME_SIZE, bold=True)
            name_w = width_of(name, NAME_SIZE, bold=True)
            sub = cut(sub, geo.width - name_w - 16, SUB_SIZE)
            sub_w = width_of(sub, SUB_SIZE)
            names.append(f'<text class="t-name" x="0" y="{_n(y)}">{esc(name)}</text>'
                         f'<text class="t-sub" x="{_n(geo.width)}" y="{_n(y)}" text-anchor="end">{esc(sub)}</text>')  # fmt: skip
            boxes.add((0, y - 11, name_w, y + 4))
            boxes.add((geo.width - sub_w, y - 11, geo.width, y + 4))
            bands[i] = (y - 11, y + 4, name_w + 6, geo.width - sub_w - 6)
        else:  # a column left of the bars
            name = cut(row.name, geo.label_w, NAME_SIZE, bold=True)
            sub = cut(sub, geo.label_w, SUB_SIZE)
            names.append(f'<text class="t-name" x="0" y="{_n(mid - 2)}">{esc(name)}</text>'
                         f'<text class="t-sub" x="0" y="{_n(mid + 14)}">{esc(sub)}</text>')  # fmt: skip
            boxes.add((0, mid - 13, max(width_of(name, NAME_SIZE, True), width_of(sub, SUB_SIZE)), mid + 17))
        if not row.bars:
            out.append(f'<text class="t-sub" x="{_n(geo.bar_x)}" y="{_n(mid + 4)}">no playlists inside</text>')
        filled = [b for b in row.bars if not b.outline]
        outlines = [b for b in row.bars if b.outline and b.w > 0]
        for b in row.bars:
            if b.w <= 0:
                continue
            colour = slot_class(b.slot)
            tip = _bar_tip(b, row)
            if row.hidden_outlines and outlines and b is outlines[-1]:
                tip += f" · and {row.hidden_outlines} more without tracks"
            hit = _hit_rect(b, row, strip, geo)
            if b.outline:
                kind = "smart" if b.tracks is None else "empty"
                mark = (f'<rect class="mark outline {colour}" x="{_n(b.x + 0.75)}" y="{_n(strip + 0.75)}" '
                        f'width="{_n(b.w - 1.5)}" height="{_n(STRIP - 1.5)}" rx="2"/>')  # fmt: skip
            else:
                d = bar_path(b.x, strip, b.w, STRIP, round_end=b is filled[-1])
                mark = f'<path class="mark lane {colour}" d="{d}"/>'
                if b.dump:
                    mark += f'<path class="hatch" d="{d}" fill="url(#{hatch})"/>'
                kind = "dump" if b.dump else "playlist"
            out.append(f'<g class="hit" tabindex="0" data-kind="{kind}" data-tip="{esc(tip)}">{mark}{hit}</g>')
        out.append("</g>")
    if more:
        y = TOP + len(rows) * geo.pitch + AXIS_H + geo.unit_line + 12
        out.append(f'<text class="t-sub" x="0" y="{_n(y)}">+ {plural(more, "more folder")}: see structure/analysis.md</text>')

    # arcs: the top overlapping pairs whose two playlists are both drawn
    labelled: list[Bar] = []
    above: set[str] = set()
    arcs = []
    for pair in (((structure or {}).get("overlap") or {}).get("top") or []):
        if len(arcs) >= MAX_ARCS:
            break
        if not isinstance(pair, Mapping):
            continue
        a, b = by_path.get(str(pair.get("a"))), by_path.get(str(pair.get("b")))
        if not a or not b or a is b or a.outline or b.outline:
            continue
        if (b.row, b.x) < (a.row, a.x):
            a, b = b, a
        segments, middle = _arc_path(a, b, geo, bands)
        arcs.append((a, b, pair, segments, middle))
    for _a, _b, _pair, segments, _middle in arcs:  # every arc is known before any label is placed
        for x, y in _samples(segments):
            boxes.add((x - 1.5, y - 1.5, x + 1.5, y + 1.5))
    arc_svg = []
    arc_labels = 0  # an arc's "N shared" is a direct label too: it counts toward MAX_LABELS
    for n, (a, b, pair, segments, middle) in enumerate(arcs):
        d = _path_d(segments)
        ends = (segments[0][0], segments[-1][3])
        if a.row != b.row and n == 0:
            above.add(a.path)  # the upper end's label goes above its bar, clear of the arc
        share = round(float(pair.get("jaccard") or 0) * 100)
        shared = int(pair.get("shared") or 0)
        tip = f"{plural(shared, 'track')} shared · {a.path} + {b.path} · {share}% overlap"
        dots = "".join(f'<circle class="arc-end" cx="{_n(x)}" cy="{_n(y)}" r="4"/>' for x, y in ends)
        arc_svg.append(f'<g class="hit arc-hit" tabindex="0" data-kind="arc" data-tip="{esc(tip)}">'
                       f'<path class="arc" d="{d}"/>{dots}<path class="hit-line" d="{d}"/></g>')  # fmt: skip
        word = f"{shared} shared"
        lw = width_of(word, LABEL_SIZE, bold=True)
        # beside the middle of the arc first, then beside the points nearest to it
        points = sorted(_samples(segments, 8), key=lambda p: math.dist(p, middle))
        for px, py in [middle, *points]:
            spot = next(((lx, py + 4) for lx in (px + 9, px - 9 - lw)
                         if 0 <= lx and lx + lw <= geo.width and boxes.free((lx, py - 5, lx + lw, py + 7), 2)), None)  # fmt: skip
            if spot:
                lx, ly = spot
                boxes.add((lx, ly - 9, lx + lw, ly + 3))
                arc_svg.append(f'<text class="t-label t-arc" x="{_n(lx)}" y="{_n(ly)}">{esc(word)}</text>')
                arc_labels += 1
                break
        if n == 0:
            labelled += [a, b]

    # direct labels: dumps first, then the first overlap pair, then the biggest bars
    picks = sorted((b for b in bars if b.dump and not b.outline and b.w > 0), key=lambda b: -(b.tracks or 0))
    picks += labelled
    picks += sorted((b for b in bars if not b.outline and b.w > 0), key=lambda b: (-(b.tracks or 0), b.row, b.x))
    labels_svg, labels = [], []
    seen: set[str] = set()
    budget = max(0, MAX_LABELS - arc_labels)
    for b in picks:
        if len(labels) >= budget:
            break
        if b.path in seen:
            continue
        seen.add(b.path)
        icon = 13 if b.dump else 0
        text = cut(b.name, min(geo.width - 2 - icon - geo.bar_x, 260), LABEL_SIZE)
        if b.dump:
            text = f"dump · {text}"
        lw = width_of(text, LABEL_SIZE) + icon
        x = max(0.0, min(b.x, geo.width - 2 - lw))
        strip = geo.strip_top(b.row)
        spots = (strip - 4, strip + STRIP + 11)  # above the bar, below it
        y = next((y for y in (spots if b.path in above else spots[::-1]) if boxes.free((x, y - 9, x + lw, y + 3))), None)
        if y is None:
            continue
        boxes.add((x, y - 9, x + lw, y + 3))
        parts = ""
        if b.dump:
            parts = (f'<g class="status warning"><circle class="ring" cx="{_n(x + 5)}" cy="{_n(y - 3.5)}" r="5"/>'
                     f'<text class="t-icon" x="{_n(x + 5)}" y="{_n(y)}" text-anchor="middle">!</text></g>')  # fmt: skip
        labels_svg.append(f'{parts}<text class="t-label" x="{_n(x + icon)}" y="{_n(y)}">{esc(text)}</text>')
        labels.append(b.path)
    out += arc_svg
    out.append(f'<g class="names">{"".join(names)}</g>')  # names and labels drawn over the arcs
    out.append(f'<g class="labels">{"".join(labels_svg)}</g>')
    out.append("</svg>")
    return "".join(out), labels, len(arcs)


def crate_wall(graph: Mapping[str, Any], structure: Mapping[str, Any] | None,
               identity: Mapping[str, Any] | None, *, uid: str = "cw-") -> Wall | None:  # fmt: skip
    """The crate wall as inline SVG, in two layouts: wide (class "wall-wide", ids start with
    `uid`) and phone (class "wall-narrow", ids start with `uid` + "n-"); the page shows one of the
    two by its width. None when the graph has no rows. What it draws: the module docstring."""
    rows, more = wall_rows(graph, structure, identity)
    if not rows:
        return None
    narrow, _labels, _arcs = _wall_svg(rows, more, structure, NARROW, f"{uid}n-", "wall chart wall-narrow")
    wide, labels, arcs = _wall_svg(rows, more, structure, WIDE, uid, "wall chart wall-wide")
    bars = [b for row in rows for b in row.bars if b.w > 0]

    # the legend: what a bar's colour means, the lanes that show (slot order), then the marks.
    # A grey dump or a grey outline is keyed by "dump" or "empty or smart": the solid grey "no
    # lane" key shows only when a solid grey bar is drawn.
    def slot(b: Bar) -> int:
        return b.slot if isinstance(b.slot, int) and 1 <= b.slot <= design.SLOTS else 0

    shown = sorted({slot(b) for b in bars if slot(b) or not (b.dump or b.outline)}, key=lambda s: (s == 0, s))
    legend: list[tuple[str, str]] = []
    lanes = {lane.get("slot"): lane for lane in lane_rows(identity)}
    if lanes and len(shown) >= 2:
        folder_rows = any(r.kind == "folder" and r.bars for r in rows)
        head = "Row colour = the folder's main BPM lane" if folder_rows else "Colour = the playlist's BPM lane"
        if folder_rows and any(r.kind == "loose" for r in rows):
            head += " (a loose playlist: its own)"
        legend.append(("head", head))
        for s in shown:
            legend.append((f"s{s}", f"{lanes[s].get('label', '?')} BPM") if s in lanes else ("s0", "no lane"))
    if any(b.dump for b in bars):
        legend.append(("dump", "dump"))
    if any(b.outline for b in bars):
        legend.append(("empty", "empty or smart"))
    if arcs:
        legend.append(("arc", "shared tracks"))
    return Wall(wide + narrow, legend, rows, labels, arcs, more)


# -- the six axes --------------------------------------------------------------------------------

# Drawn about as wide as it shows on a 1100 px page and on a phone (the page caps it at 340 px),
# so its text stays near its CSS size instead of growing or shrinking with the viewBox.
AXES_W = 330
AXES_LABEL = 86
AXES_X = 94
AXES_BW = 200  # 0..100
AXES_ROW = 26
AXES_BAR = 10
AXIS_HINTS = {
    "depth": "how far back your crates go",
    "selectivity": "how picky you are about files",
    "discipline": "how tidy the crates are",
    "breadth": "how wide your sound is",
    "momentum": "how hard you are still digging",
    "memory": "how much you mark up",
}


def axes_chart(identity: Mapping[str, Any], *, uid: str = "ax-") -> str:
    """The six axes as inline SVG: thin bars 0-100, the top two in ink, values on at most 4."""
    order = [a for a in (identity.get("order") or list(AXIS_HINTS)) if a in (identity.get("axes") or {})]
    axes = identity.get("axes") or {}
    top = set(identity.get("top") or [])
    if not order:
        return ""
    scores = {a: int(axes[a].get("score") or 0) for a in order}
    lowest = min(order, key=lambda a: (scores[a], order.index(a)))
    labelled = [a for a in order if a in top] + ([lowest] if lowest not in top else [])
    height = 6 + len(order) * AXES_ROW + 22
    base = 6 + len(order) * AXES_ROW
    out = [f'<svg class="axes chart" viewBox="0 0 {AXES_W} {height}" role="img" aria-labelledby="{uid}title">',
           f'<title id="{uid}title">Six axes, 0 to 100: '
           + esc(", ".join(f"{axes[a].get('name', a.title())} {scores[a]}" for a in order)) + "</title>"]
    grid = []
    for value in (0, 50, 100):
        x = AXES_X + value * AXES_BW / 100
        grid.append(f'<path class="gridline" d="M{_n(x)} 2V{base}"/>')
        grid.append(f'<text class="t-tick" x="{_n(x)}" y="{base + 15}" text-anchor="middle">{value}</text>')
    out.append(f'<g class="grid">{"".join(grid)}</g>')
    for i, axis in enumerate(order):
        y = 6 + i * AXES_ROW
        mid = y + AXES_ROW / 2
        name = str(axes[axis].get("name") or axis.title())
        score = scores[axis]
        w = max(1.5, score * AXES_BW / 100)
        cls = "mark emph" if axis in top else "mark rest"
        tip = f"{score} · {name} · {AXIS_HINTS.get(axis, '')}".rstrip(" ·")
        out.append(f'<text class="t-axis{" strong" if axis in top else ""}" x="{AXES_LABEL - 8}" y="{_n(mid + 4)}" '
                   f'text-anchor="end">{esc(name)}</text>')  # fmt: skip
        hit = f'<rect class="hit-area" x="{AXES_X - 2}" y="{_n(mid - 12)}" width="{AXES_BW + 4}" height="24"/>'
        out.append(f'<g class="hit" tabindex="0" data-kind="axis" data-tip="{esc(tip)}">'
                   f'<path class="{cls}" d="{bar_path(AXES_X, mid - AXES_BAR / 2, w, AXES_BAR)}"/>{hit}</g>')  # fmt: skip
        if axis in labelled:
            out.append(f'<text class="t-value" x="{_n(AXES_X + w + 6)}" y="{_n(mid + 4)}">{score}</text>')
    out.append("</svg>")
    return "".join(out)


# -- hover layers over the sleeves ---------------------------------------------------------------


def _sector(r0: float, r1: float, a0: float, a1: float) -> str:
    """A full annular sector (no gap: the hit area covers the gap too)."""
    cx, cy = sleeve_mod.CX, sleeve_mod.CY
    large = 1 if (a1 - a0) > math.pi else 0
    p = [(cx + r1 * math.cos(a0), cy + r1 * math.sin(a0)), (cx + r1 * math.cos(a1), cy + r1 * math.sin(a1)),
         (cx + r0 * math.cos(a1), cy + r0 * math.sin(a1)), (cx + r0 * math.cos(a0), cy + r0 * math.sin(a0))]  # fmt: skip
    return (f"M{_n(p[0][0])} {_n(p[0][1])}A{_n(r1)} {_n(r1)} 0 {large} 1 {_n(p[1][0])} {_n(p[1][1])}"
            f"L{_n(p[2][0])} {_n(p[2][1])}A{_n(r0)} {_n(r0)} 0 {large} 0 {_n(p[3][0])} {_n(p[3][1])}Z")  # fmt: skip


def _ring_bounds(identity: Mapping[str, Any]) -> tuple[list[str], list[tuple[float, float]], list[list[int]]]:
    """(ring names, (inner, outer) radius per ring, counts) exactly as dj.sleeve draws the disc."""
    names, shares, counts = sleeve_mod._rings(identity)  # the sleeve's own reading of the rings
    n_rings = len(names)
    space = sleeve_mod.R_OUT - sleeve_mod.R_LABEL - sleeve_mod.LABEL_GAP - sleeve_mod.GAP * (n_rings - 1)
    total = sum(shares) or 1.0
    widths = [space * (0.3 / n_rings + 0.7 * s / total) for s in shares]
    widths = [w * space / (sum(widths) or 1.0) for w in widths]
    bounds = []
    r0 = sleeve_mod.R_LABEL + sleeve_mod.LABEL_GAP
    for width in widths:
        bounds.append((r0, r0 + width))
        r0 += width + sleeve_mod.GAP
    return names, bounds, counts


def fingerprint_bands(identity: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [b for b in ((identity.get("fingerprint") or {}).get("bands") or []) if isinstance(b, Mapping)]


def _hit_cell(kind: str, tip: str, d: str, focusable: bool) -> str:
    """One transparent cell of a hover layer. A cell that holds tracks takes keyboard focus and
    is announced as an image named by its tooltip; an empty one is hidden from assistive tech."""
    if focusable:
        return (f'<path class="hit cell" tabindex="0" role="img" aria-label="{esc(tip)}" data-kind="{kind}" '
                f'data-tip="{esc(tip)}" d="{d}"/>')  # fmt: skip
    return f'<path class="hit cell" aria-hidden="true" data-kind="{kind}" data-tip="{esc(tip)}" d="{d}"/>'


def sleeve_hits(identity: Mapping[str, Any]) -> str:
    """Transparent cells over the hero sleeve (viewBox 0 0 1000 1000): one per fingerprint cell,
    each with its tooltip ("4 tracks · 1990s · 118-122 BPM · lane 119-122")."""
    bands = fingerprint_bands(identity)
    if not bands:
        return ""
    names, bounds, counts = _ring_bounds(identity)
    n_bands = len(bands)
    step = 2 * math.pi / n_bands
    rotation = sleeve_mod.rotation_of(identity, n_bands)
    out = [f'<svg class="hits" viewBox="0 0 {sleeve_mod.VIEW} {sleeve_mod.VIEW}" role="group" '
           'aria-label="The sleeve, cell by cell">']
    for ring, (r0, r1) in enumerate(bounds):
        outer = r1 + (sleeve_mod.GAP if ring < len(bounds) - 1 else 6)
        for k, band in enumerate(bands):
            count = counts[ring][k] if ring < len(counts) and k < len(counts[ring]) else 0
            a0 = -math.pi / 2 + rotation + k * step
            lane = f"lane {band.get('lane')}" if band.get("lane") else "no lane"
            tip = f"{plural(int(count or 0), 'track')} · {names[ring]} · {band_words(str(band.get('band', '')))} · {lane}"
            out.append(_hit_cell("cell", tip, _sector(r0, outer, a0, a0 + step), bool(count)))
    out.append("</svg>")
    return "".join(out)


def mini_view() -> str:
    """The viewBox dj.sleeve.mini_sleeve_svg uses (the disc and a margin)."""
    cx, cy, r = sleeve_mod.CX, sleeve_mod.CY, sleeve_mod.R_OUT
    return f"{_n(cx - r - 24)} {_n(cy - r - 24)} {_n(2 * r + 48)} {_n(2 * r + 48)}"


def mini_hits(identity: Mapping[str, Any], owners: Mapping[str, str | None]) -> str:
    """Transparent band wedges over a proposal sleeve: "118-122 BPM · 9 tracks · lands in house_base"."""
    bands = fingerprint_bands(identity)
    if not bands:
        return ""
    n_bands = len(bands)
    step = 2 * math.pi / n_bands
    rotation = sleeve_mod.rotation_of(identity, n_bands)
    r0, r1 = sleeve_mod.R_LABEL, sleeve_mod.R_OUT + 10
    out = [f'<svg class="hits" viewBox="{mini_view()}" role="group" aria-label="Where each tempo band lands">']
    for k, band in enumerate(bands):
        name = str(band.get("band", ""))
        tracks = int(band.get("tracks") or 0)
        where = owners.get(name)
        land = f"lands in {where}" if where else "none of the copied playlists reach it"
        tip = f"{plural(tracks, 'track')} · {band_words(name)} · {land}"
        a0 = -math.pi / 2 + rotation + k * step
        out.append(_hit_cell("band", tip, _sector(r0, r1, a0, a0 + step), bool(tracks)))
    out.append("</svg>")
    return "".join(out)


# -- proposals: how each one recolours the fingerprint -------------------------------------------


@dataclass
class Branch:
    name: str
    kind: str
    slot: int | None  # the slot of the lane that fills most of it (None: no lane, or taken)
    children: list[str]
    sources: int
    bands: list[str]  # the BPM bands that land in it, so wear its slot on the mini sleeve
    lane: str | None = None  # the label of that lane


def _bpm_rows(identity: Mapping[str, Any] | None, taste: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Playlists with a BPM range: taste/facts.json `bpm_playlists`, else the identity lanes
    (each lane's tracks shared evenly by its playlists, over the lane's range)."""
    rows = []
    for row in ((taste or {}).get("bpm_playlists") or []):
        if isinstance(row, Mapping) and isinstance(row.get("lo"), (int, float)) and isinstance(row.get("hi"), (int, float)):
            rows.append({"path": str(row.get("path")), "lo": float(row["lo"]), "hi": float(row["hi"]),
                         "tracks": float(row.get("tracks") or 0)})  # fmt: skip
    if rows:
        return rows
    for lane in lane_rows(identity):
        playlists = list(lane.get("playlists") or [])
        if not playlists or not isinstance(lane.get("lo"), (int, float)) or not isinstance(lane.get("hi"), (int, float)):
            continue
        each = float(lane.get("tracks") or 0) / len(playlists)
        rows += [{"path": str(p), "lo": float(lane["lo"]), "hi": float(lane["hi"]), "tracks": each} for p in playlists]
    return rows


def _walk(node: TreeNode):
    yield node
    for child in node.children:
        yield from _walk(child)


def band_ranges(names: Sequence[str]) -> str:
    """Contiguous bands as one range: ["118-122", "122-125"] -> "118-125 BPM"; "" for none."""
    if not names:
        return ""
    spans: list[list[str]] = []
    for name in names:
        lo = None if name.startswith("<") else name.rstrip("+").split("-")[0]
        if spans and spans[-1][1] is not None and lo == spans[-1][1]:
            spans[-1][1] = None if name.endswith("+") else (name.split("-")[1] if "-" in name else None)
            continue
        hi = None if name.endswith("+") else (name[1:] if name.startswith("<") else name.split("-")[1])
        spans.append([lo, hi])
    words = []
    for lo, hi in spans:
        if lo is None:
            words.append(f"under {hi}")
        elif hi is None:
            words.append(f"{lo} and up")
        else:
            words.append(f"{lo}-{hi}")
    return ", ".join(words) + " BPM"


def proposal_colours(nodes: Sequence[TreeNode], identity: Mapping[str, Any] | None,
                     taste: Mapping[str, Any] | None) -> tuple[dict[str, int | None], list[Branch]]:  # fmt: skip
    """(band -> slot for dj.sleeve.mini_sleeve_svg, the branches in tree order). The rule is in
    the module docstring: a branch wears the slot of the lane that fills most of it, a band the
    slot of the branch it lands in, so a colour names the same lane as everywhere on the page."""
    rows = _bpm_rows(identity, taste)
    tracks_of = {row["path"]: row["tracks"] for row in rows}
    lanes = lane_of(identity)
    dest: dict[str, list[int]] = {}
    branches = []
    fills: list[dict[int, float]] = []  # per branch: lane slot -> tracks it would take from that lane
    for i, node in enumerate(nodes):
        sources, fill = 0, {}
        for inner in _walk(node):
            for src in inner.fill_from:
                dest.setdefault(str(src), []).append(i)
                sources += 1
                lane = lanes.get(str(src))
                slot = lane.get("slot") if lane else None
                if isinstance(slot, int) and not isinstance(slot, bool) and 1 <= slot <= design.SLOTS:
                    share = float(lane.get("tracks") or 0) / max(1, len(lane.get("playlists") or []))
                    fill[slot] = fill.get(slot, 0.0) + tracks_of.get(str(src), share)
        fills.append(fill)
        branches.append(Branch(node.name, node.kind, None, [c.name for c in node.children], sources, []))
    by_slot = {lane.get("slot"): lane for lane in lane_rows(identity)}
    claims: dict[int, list[int]] = {}
    for i, fill in enumerate(fills):
        if fill:
            claims.setdefault(min(fill, key=lambda s: (-fill[s], s)), []).append(i)  # ties: the slower lane
    for slot, claimants in claims.items():
        keeper = min(claimants, key=lambda i: (-fills[i][slot], i))  # two branches never share a slot
        branches[keeper].slot = slot
        branches[keeper].lane = str(by_slot[slot].get("label")) if slot in by_slot else None
    bands = fingerprint_bands(identity or {})
    weights = [[0.0] * len(nodes) for _ in bands]
    for row in rows:
        targets = dest.get(row["path"])
        if not targets or row["tracks"] <= 0:
            continue
        a, b = row["lo"] - 0.5, row["hi"] + 0.5
        for k, band in enumerate(bands):
            lo = band.get("lo") if isinstance(band.get("lo"), (int, float)) else -math.inf
            hi = band.get("hi") if isinstance(band.get("hi"), (int, float)) else math.inf
            part = max(0.0, min(b, hi) - max(a, lo)) / (b - a)
            for i in targets:
                weights[k][i] += row["tracks"] * part
    slots: dict[str, int | None] = {}
    for k, band in enumerate(bands):
        name = str(band.get("band"))
        best = max(range(len(nodes)), key=lambda i: (weights[k][i], -i)) if nodes else None
        if best is None or weights[k][best] <= 1e-9:
            slots[name] = None
            continue
        slots[name] = branches[best].slot
        branches[best].bands.append(name)
    return slots, branches
