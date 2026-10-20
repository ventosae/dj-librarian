"""The sleeve: a 12-inch record sleeve drawn from profile/identity.json (R-1403, docs/design.md).

Door 1: stdlib only. Two functions, both pure and deterministic:

    sleeve_svg(identity, *, inline=False, uid="", small_print=True) -> str
        The full sleeve, square viewBox 0 0 1000 1000: a dark finish with a fine grain, the
        radial fingerprint as the artwork (rings = decades, oldest inside; segments = BPM
        bands; ring thickness follows the decade's share, cell opacity the cell's share; cell
        colour = the slot of the lane that owns the band, in the Booth values of dj.design),
        a centre label, the DJ's handle in heavy display type, the archetype under it and the
        three biggest lanes as liner notes. `small_print=False` leaves out the two kinds of
        text that only read on a big sleeve, the tempo dial at the edge of the disc and the
        detail line under each lane: the report draws its hero copy at about 40% of the
        viewBox and states both elsewhere (the tooltips, the crate wall legend). Every text
        that stays is at least 16 units tall, the header and the lane labels 24.
    mini_sleeve_svg(identity, slots, *, size=240, uid="") -> str
        The fingerprint alone at `size` px, re-coloured: `slots` maps a band name (BANDS of
        dj.analysis.identity, e.g. "118-122") to a palette slot 1..8, or None for the Other
        grey; bands not named keep the identity's own slot. For proposal cards.

Every variation (the disc's rotation, the grain, the wear ring) comes from a small PRNG seeded
only by identity["seed"], so the same export gives the same bytes. Nothing outside the document
is referenced: no href, no url(), no font file, no script. The standalone file carries the SVG
namespace declaration (an identifier, never fetched); `inline=True` and the mini sleeve leave it
out, so an HTML page that embeds them holds no "http" at all. Text is XML-escaped and stripped
of characters XML cannot hold. Every id is `<uid>sleeve-...` or `<uid>mini-...`, so several
sleeves can sit inline in one HTML page with distinct `uid`s. A long handle scales down, then
wraps to two lines, and is clamped with textLength, so it never runs off the sleeve.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Mapping, Sequence

from dj import design

VIEW = 1000
CX, CY = 500.0, 402.0
R_OUT = 286.0
R_LABEL = 76.0
LABEL_GAP = 12.0
GAP = 2.0  # surface gap between touching cells (docs/design.md, Marks)
MARGIN = 64.0
TEXT_W = VIEW - 2 * MARGIN
HANDLE_MAX_SIZE = 104.0
HANDLE_MIN_ONE_LINE = 56.0
HANDLE_MAX_TWO_LINES = 56.0  # line 1's capitals then stay under a dial label straight below the disc
HANDLE_MIN = 26.0
HANDLE_BASE = 824.0  # the baseline of the handle's last line
HANDLE_LEAD = 1.0  # line pitch of a two-line handle, in em
SUB_SIZE = 34.0  # the archetype line under the handle
SUB_BASE = 884.0  # its baseline; the rule under it sits at 908
OTHER_DIM = 0.7  # an unowned band (Other) recedes behind the lanes
GRAIN = 900
MINI_GRAIN = 160
BAND_EDGES = (100, 110, 118, 122, 125, 128, 135)  # as dj.analysis.identity; the dial labels
BANDS_DEFAULT = len(BAND_EDGES) + 1

SVG_NS = "http://www.w3.org/2000/svg"  # the namespace of the standalone file: an identifier, not a link
DARK = "dark"  # the sleeve keeps its dark finish in both page themes
FINISH = "#121211"
INK = design.TEXT[DARK]
INK_2 = design.TEXT_2[DARK]
GROOVE = "#000000"
_UID = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_-]*)?$")
# The characters XML 1.0 allows (tab, line feed, carriage return, then three ranges); the rest is dropped.
_XML_OK = "".join((chr(9), chr(10), chr(13), " -", chr(0xD7FF), chr(0xE000), "-", chr(0xFFFD), chr(0x10000), "-", chr(0x10FFFF)))
_BAD_XML = re.compile("[^" + _XML_OK + "]")


# -- deterministic randomness -------------------------------------------------------------------


class _Rand:
    """SplitMix64 on the first 16 hex digits of the seed: the same seed, the same stream on
    every Python and every machine."""

    MASK = (1 << 64) - 1

    def __init__(self, seed: str, salt: int = 0) -> None:
        text = re.sub(r"[^0-9a-fA-F]", "", str(seed or ""))[:16] or "0"
        self.state = (int(text, 16) ^ (salt * 0x9E3779B97F4A7C15)) & self.MASK

    def next(self) -> float:
        self.state = (self.state + 0x9E3779B97F4A7C15) & self.MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.MASK
        z ^= z >> 31
        return (z >> 11) / float(1 << 53)

    def between(self, low: float, high: float) -> float:
        return low + (high - low) * self.next()


# -- text and numbers ---------------------------------------------------------------------------


def _num(x: float) -> str:
    """One decimal, no "-0.0": numbers in the SVG are written the same way every time."""
    value = round(x, 1)
    if value == 0:
        value = 0.0
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def clean(text: Any) -> str:
    """One line of text an XML document can hold: control characters removed, spaces collapsed."""
    return " ".join(_BAD_XML.sub("", str(text if text is not None else "")).split())


def esc(text: Any) -> str:
    """XML-escaped, for text and attribute values (quotes too)."""
    value = clean(text)
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))  # fmt: skip


def _char_em(ch: str) -> float:
    """Rough advance width of a character in a heavy sans, in em."""
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    if ch == " ":
        return 0.3
    if ch in "iljI.,:;'|!`":
        return 0.32
    if ch in "mwMW@":
        return 0.92
    if ch.isupper() or ch.isdigit():
        return 0.7
    return 0.6


def text_em(text: str, tracking: float = -0.04) -> float:
    """Estimated width of `text` in em at the given letter-spacing (em per character)."""
    return sum(_char_em(ch) + tracking for ch in text) if text else 0.0


def handle_lines(handle: str, width: float = TEXT_W) -> tuple[list[str], float]:
    """(lines, font size) for the handle: one line as large as fits up to HANDLE_MAX_SIZE; when
    that falls under HANDLE_MIN_ONE_LINE, two lines (split at the space nearest the middle, or
    mid-word when there is none), at most HANDLE_MAX_TWO_LINES."""
    text = clean(handle) or "You"
    one = min(HANDLE_MAX_SIZE, width / max(text_em(text), 0.1))
    if one >= HANDLE_MIN_ONE_LINE or len(text) < 2:
        return [text], max(HANDLE_MIN, one)
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if spaces:
        cut = min(spaces, key=lambda i: (abs(text_em(text[:i]) - text_em(text[i + 1:])), i))
        lines = [text[:cut].strip(), text[cut + 1:].strip()]
    else:
        middle = len(text) // 2
        lines = [text[:middle], text[middle:]]
    lines = [line for line in lines if line] or [text]
    size = min(HANDLE_MAX_TWO_LINES, width / max(max(text_em(line) for line in lines), 0.1))
    return lines, max(HANDLE_MIN, size)


# -- geometry -----------------------------------------------------------------------------------


def _point(r: float, a: float) -> tuple[float, float]:
    return CX + r * math.cos(a), CY + r * math.sin(a)


def _cell(r0: float, r1: float, a0: float, a1: float) -> str:
    """An annular sector with straight GAP-wide spokes between neighbours: the angular inset is
    GAP/2 of arc length at each radius."""
    o0, o1 = a0 + GAP / 2 / r1, a1 - GAP / 2 / r1
    i0, i1 = a0 + GAP / 2 / r0, a1 - GAP / 2 / r0
    if o1 <= o0 or i1 <= i0:
        return ""
    large = 1 if (o1 - o0) > math.pi else 0
    p = [_point(r1, o0), _point(r1, o1), _point(r0, i1), _point(r0, i0)]
    return (f"M{_num(p[0][0])} {_num(p[0][1])}A{_num(r1)} {_num(r1)} 0 {large} 1 {_num(p[1][0])} {_num(p[1][1])}"
            f"L{_num(p[2][0])} {_num(p[2][1])}A{_num(r0)} {_num(r0)} 0 {large} 0 {_num(p[3][0])} {_num(p[3][1])}Z")  # fmt: skip


def _rings(identity: Mapping[str, Any]) -> tuple[list[str], list[float], list[list[int]]]:
    """(ring names, ring shares, counts rows x bands). No dated tracks: one ring of all tracks
    per band; no tracks at all: one empty ring."""
    fp = identity.get("fingerprint") or {}
    bands = fp.get("bands") or []
    n_bands = len(bands) or BANDS_DEFAULT
    rings = fp.get("rings") or []
    counts = fp.get("counts") or []
    if rings and len(counts) == len(rings):
        return [str(r.get("decade", "")) for r in rings], [float(r.get("share", 0) or 0) for r in rings], counts
    row = [int(b.get("tracks", 0) or 0) for b in bands] or [0] * n_bands
    return ["all years"], [1.0], [row]


def _slots(identity: Mapping[str, Any], overrides: Mapping[str, int | None] | None) -> list[int | None]:
    bands = (identity.get("fingerprint") or {}).get("bands") or []
    slots = [b.get("slot") for b in bands] or [None] * BANDS_DEFAULT
    if overrides:
        names = [str(b.get("band")) for b in bands]
        for key, slot in overrides.items():
            if key not in names:
                raise ValueError(f"no BPM band {key!r} in this identity (bands: {', '.join(names)})")
            if slot is not None and (isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= design.SLOTS):
                raise ValueError(f"slot for {key} must be 1..{design.SLOTS} or None, got {slot!r}")
            slots[names.index(key)] = slot
    return slots


def rotation_of(identity: Mapping[str, Any], n_bands: int = BANDS_DEFAULT) -> float:
    """The disc's rotation in radians, 0 up to one band: its own stream of the seed."""
    return math.radians(_Rand(identity.get("seed", ""), salt=1).between(0, 360 / max(n_bands, 1)))


def _disc(identity: Mapping[str, Any], slots: Sequence[int | None], rotation: float, *, grooves: bool = True) -> list[str]:
    """The fingerprint: cells, grooves and the edge."""
    names, shares, counts = _rings(identity)
    n_rings, n_bands = len(names), len(slots)
    space = R_OUT - R_LABEL - LABEL_GAP - GAP * (n_rings - 1)
    total = sum(shares) or 1.0
    widths = [space * (0.3 / n_rings + 0.7 * s / total) for s in shares]
    widths = [w * space / (sum(widths) or 1.0) for w in widths]
    step = 2 * math.pi / n_bands
    biggest = max((c for row in counts for c in row), default=0)
    out = [f'<circle cx="{_num(CX)}" cy="{_num(CY)}" r="{_num(R_OUT + 10)}" fill="#0b0b0a"/>']
    r0 = R_LABEL + LABEL_GAP
    for ring, width in enumerate(widths):
        r1 = r0 + width
        for band in range(n_bands):
            a0 = -math.pi / 2 + rotation + band * step
            path = _cell(r0, r1, a0, a0 + step)
            if not path:
                continue
            count = counts[ring][band] if band < len(counts[ring]) else 0
            if count and biggest:
                colour = design.slot_hex(slots[band], DARK)
                opacity = (0.3 + 0.7 * count / biggest) * (1.0 if slots[band] else OTHER_DIM)
            else:
                colour, opacity = INK, 0.04
            out.append(f'<path d="{path}" fill="{colour}" fill-opacity="{opacity:.2f}"/>')
        r0 = r1 + GAP
    if grooves:
        r = R_LABEL + LABEL_GAP + 3
        rings = []
        while r < R_OUT:
            rings.append(f'<circle cx="{_num(CX)}" cy="{_num(CY)}" r="{_num(r)}"/>')
            r += 6.5
        out.append(f'<g fill="none" stroke="{GROOVE}" stroke-opacity="0.16" stroke-width="0.7">{"".join(rings)}</g>')
    out.append(f'<circle cx="{_num(CX)}" cy="{_num(CY)}" r="{_num(R_OUT + 10)}" fill="none" stroke="{INK}" '
               f'stroke-opacity="0.14" stroke-width="1"/>')  # fmt: skip
    return out


def _grain(rand: _Rand, dots: int) -> list[str]:
    """Fine speckle over the finish: zero-length round-capped strokes, three layers."""
    layers = (("#ffffff", 1.6, 0.05), ("#ffffff", 0.9, 0.08), ("#000000", 1.8, 0.22))
    out = []
    for colour, width, opacity in layers:
        moves = []
        for _ in range(dots // len(layers)):
            moves.append(f"M{_num(rand.between(0, VIEW))} {_num(rand.between(0, VIEW))}h0")
        out.append(f'<path d="{"".join(moves)}" stroke="{colour}" stroke-width="{width}" stroke-linecap="round" '
                   f'stroke-opacity="{opacity}" fill="none"/>')  # fmt: skip
    return out


def _finish(rand: _Rand, dots: int) -> list[str]:
    """The dark board: base, a soft lift toward the middle, the ring wear a record leaves, grain."""
    out = [f'<rect width="{VIEW}" height="{VIEW}" fill="{FINISH}"/>']
    lift = "".join(f'<circle cx="{_num(CX)}" cy="{_num(CY)}" r="{r}"/>' for r in range(760, 200, -40))
    out.append(f'<g fill="#ffffff" fill-opacity="0.0065">{lift}</g>')
    dx, dy = rand.between(-8, 8), rand.between(-8, 8)
    out.append(f'<circle cx="{_num(CX + dx)}" cy="{_num(500 + dy)}" r="476" fill="none" stroke="#ffffff" '
               f'stroke-opacity="0.035" stroke-width="22"/>')  # fmt: skip
    out += _grain(rand, dots)
    return out


def _lane_lines(identity: Mapping[str, Any]) -> list[dict[str, Any]]:
    lanes = [lane for lane in identity.get("lanes") or [] if isinstance(lane, Mapping)]
    biggest = sorted(lanes, key=lambda l: (-(l.get("tracks") or 0), l.get("lo") or 0, str(l.get("label", ""))))
    return biggest[:3]


def _leaf(path: str) -> str:
    return str(path).rstrip("/").rsplit("/", 1)[-1]


def _svg_open(
    size: int | None, uid: str, kind: str, title: str, desc: str, *, inline: bool, view: str = f"0 0 {VIEW} {VIEW}"
) -> list[str]:
    dims = f' width="{size}" height="{size}"' if size else ""
    ns = "" if inline else f' xmlns="{SVG_NS}"'
    return [
        f'<svg{ns} viewBox="{view}"{dims} role="img" '
        f'aria-labelledby="{uid}{kind}-title {uid}{kind}-desc" '
        f'font-family="{esc(design.FONT_STACK)}">',
        f'<title id="{uid}{kind}-title">{esc(title)}</title>',
        f'<desc id="{uid}{kind}-desc">{esc(desc)}</desc>',
    ]


def _description(identity: Mapping[str, Any]) -> str:
    names, _shares, _counts = _rings(identity)
    if names and names != ["all years"]:
        rings = f"rings are decades, {names[0]} inside to {names[-1]} outside"
    else:
        rings = "one ring, no release years"
    lanes = _lane_lines(identity)
    lane_text = "; ".join(f"{l.get('label')} BPM, {l.get('tracks', 0)} tracks" for l in lanes) or "no BPM lanes yet"
    return (f"Record sleeve drawn from the library: {rings}; segments are BPM bands; the brighter "
            f"the cell, the more tracks. Biggest lanes: {lane_text}.")  # fmt: skip


def _check_uid(uid: str) -> str:
    if not isinstance(uid, str) or not _UID.match(uid):
        raise ValueError(f"uid must be letters, digits, '-' or '_', starting with a letter; got {uid!r}")
    return uid


def sleeve_svg(identity: Mapping[str, Any], *, inline: bool = False, uid: str = "", small_print: bool = True) -> str:
    """The full sleeve (see the module docstring). `inline=False`: the profile/sleeve.svg file,
    which carries the SVG namespace (an identifier, never fetched; the only "http" in it).
    `inline=True`: the same drawing for an HTML page, without the namespace (the HTML parser
    supplies it), so the page holds no "http" at all. Every id starts with `uid`.
    `small_print=False`: no tempo dial and no lane detail lines (a sleeve drawn small)."""
    uid = _check_uid(uid)
    rand = _Rand(identity.get("seed", ""))
    handle = clean(identity.get("handle")) or "You"
    archetype = clean((identity.get("archetype") or {}).get("name")) or ""
    counts = identity.get("counts") or {}
    title = f"{handle}: {archetype}" if archetype else handle
    out = _svg_open(None, uid, "sleeve", title, _description(identity), inline=inline)
    out += _finish(rand, GRAIN)
    slots = _slots(identity, None)
    rotation = rotation_of(identity, len(slots))
    out += _disc(identity, slots, rotation)

    lanes = _lane_lines(identity)
    home = lanes[0] if lanes else None
    ring = design.slot_hex(home.get("slot"), DARK) if home else design.OTHER[DARK]
    out.append(f'<circle cx="{_num(CX)}" cy="{_num(CY)}" r="{_num(R_LABEL)}" fill="{design.SURFACE[DARK]}" '
               f'stroke="{ring}" stroke-width="5"/>')  # fmt: skip
    big, small = (str(home.get("label", "")), "BPM") if home else (str(counts.get("tracks", 0)), "TRACKS")
    out.append(f'<text x="{_num(CX)}" y="{_num(CY - 6)}" text-anchor="middle" font-size="27" font-weight="800" '
               f'letter-spacing="-0.5" fill="{INK}">{esc(big)}</text>')  # fmt: skip
    out.append(f'<text x="{_num(CX)}" y="{_num(CY + 24)}" text-anchor="middle" font-size="16" font-weight="600" '
               f'letter-spacing="3" fill="{INK_2}">{esc(small)}</text>')  # fmt: skip

    # tempo dial: the band edges at the spokes between the segments, clockwise from the top
    edges = list((identity.get("fingerprint") or {}).get("edges") or BAND_EDGES) if small_print else []
    n_bands = len(slots)
    for b, edge in enumerate(edges[: n_bands - 1], 1):
        x, y = _point(R_OUT + 30, -math.pi / 2 + rotation + b * 2 * math.pi / n_bands)
        out.append(f'<text x="{_num(x)}" y="{_num(y + 5)}" text-anchor="middle" font-size="14" font-weight="600" '
                   f'fill="{INK_2}" fill-opacity="0.75">{esc(edge)}</text>')  # fmt: skip

    # header
    out.append(f'<text x="{_num(MARGIN)}" y="72" font-size="24" font-weight="700" letter-spacing="3" '
               f'fill="{INK_2}">DJ-LIBRARIAN</text>')  # fmt: skip
    decades = counts.get("decades", 0)
    head = f"{counts.get('tracks', 0)} TRACKS · {decades} DECADE{'' if decades == 1 else 'S'}"
    out.append(f'<text x="{_num(VIEW - MARGIN)}" y="72" text-anchor="end" font-size="24" font-weight="600" '
               f'letter-spacing="2" fill="{INK_2}">{esc(head)}</text>')  # fmt: skip

    # the handle, display type: its last baseline sits far enough above the archetype line that a
    # descender (about 0.23 em) clears that line's ascenders (about 0.75 of SUB_SIZE), and a
    # two-line handle is led at 1 em so line 1's descenders clear line 2's capitals
    lines, size = handle_lines(handle)
    lead = size * HANDLE_LEAD
    base = HANDLE_BASE - (len(lines) - 1) * lead
    for n, line in enumerate(lines):
        width = text_em(line) * size
        fit = f' textLength="{_num(TEXT_W)}" lengthAdjust="spacingAndGlyphs"' if width > TEXT_W * 0.9 else ""
        out.append(f'<text x="{_num(MARGIN)}" y="{_num(base + n * lead)}" font-size="{_num(size)}" font-weight="900" '
                   f'letter-spacing="{_num(-0.04 * size)}" fill="{INK}"{fit}>{esc(line)}</text>')  # fmt: skip
    if archetype:
        width = text_em(archetype, 0.0) * SUB_SIZE
        fit = f' textLength="{_num(TEXT_W)}" lengthAdjust="spacingAndGlyphs"' if width > TEXT_W else ""
        out.append(f'<text x="{_num(MARGIN)}" y="{_num(SUB_BASE)}" font-size="{_num(SUB_SIZE)}" font-weight="600" '
                   f'fill="{INK_2}"{fit}>{esc(archetype)}</text>')  # fmt: skip
    out.append(f'<path d="M{_num(MARGIN)} 908H{_num(VIEW - MARGIN)}" stroke="{INK}" stroke-opacity="0.16" stroke-width="1"/>')

    # liner notes: the three biggest lanes
    col = TEXT_W / 3
    for n, lane in enumerate(lanes):
        x = MARGIN + n * col
        colour = design.slot_hex(lane.get("slot"), DARK)
        playlists = list(lane.get("playlists") or [])
        where = _leaf(playlists[0]) if playlists else ""
        if len(playlists) > 1:
            where += f" +{len(playlists) - 1}"
        label = str(lane.get("label", "")) + " BPM"
        label = label if text_em(label, 0.0) * 24 <= col - 36 else _cut(label, col - 36, 24)
        base = 944 if small_print else 952
        out.append(f'<rect x="{_num(x)}" y="{base - 17}" width="16" height="16" rx="3" fill="{colour}"/>')
        out.append(f'<text x="{_num(x + 26)}" y="{base}" font-size="24" font-weight="700" fill="{INK}">'
                   f'{esc(label)}</text>')  # fmt: skip
        if small_print:
            detail = f"{lane.get('tracks', 0)} tracks" + (f" · {where}" if where else "")
            detail = detail if text_em(detail, 0.0) * 16 <= col - 30 else _cut(detail, col - 30, 16)
            out.append(f'<text x="{_num(x + 26)}" y="970" font-size="16" font-weight="500" fill="{INK_2}">'
                       f'{esc(detail)}</text>')  # fmt: skip
    if not lanes:
        out.append(f'<text x="{_num(MARGIN)}" y="950" font-size="24" font-weight="500" fill="{INK_2}">'
                   "No BPM lanes yet: playlists need 3 or more BPM-tagged tracks.</text>")  # fmt: skip
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _cut(text: str, width: float, size: float) -> str:
    out = ""
    for ch in text:
        if text_em(out + ch + "…", 0.0) * size > width:
            return out.rstrip() + "…"
        out += ch
    return out


def mini_sleeve_svg(
    identity: Mapping[str, Any], slots: Mapping[str, int | None] | None = None, *, size: int = 240, uid: str = ""
) -> str:
    """The fingerprint alone, re-coloured by `slots` (band -> slot 1..8 or None), `size` px
    square, for inline use in an HTML page (no namespace, no "http"). Every id starts with `uid`."""
    uid = _check_uid(uid)
    if isinstance(size, bool) or not isinstance(size, int) or not 16 <= size <= 2000:
        raise ValueError(f"size must be 16..2000 px, got {size!r}")
    rand = _Rand(identity.get("seed", ""))
    handle = clean(identity.get("handle")) or "You"
    view = f"{_num(CX - R_OUT - 24)} {_num(CY - R_OUT - 24)} {_num(2 * R_OUT + 48)} {_num(2 * R_OUT + 48)}"
    out = _svg_open(size, uid, "mini", f"{handle}: fingerprint", _description(identity), inline=True, view=view)
    out += _finish(rand, MINI_GRAIN)
    colours = _slots(identity, slots)
    out += _disc(identity, colours, rotation_of(identity, len(colours)), grooves=False)
    out.append(f'<circle cx="{_num(CX)}" cy="{_num(CY)}" r="{_num(R_LABEL)}" fill="{design.SURFACE[DARK]}"/>')
    out.append(f'<circle cx="{_num(CX)}" cy="{_num(CY)}" r="9" fill="{FINISH}"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
