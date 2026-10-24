"""dj.sleeve: the 12-inch sleeve and the mini sleeve (R-1403, docs/design.md, W-31).

Deterministic (the PRNG is seeded only by identity["seed"]), valid XML, no external reference,
every text escaped, a long or non-Latin handle never runs off the sleeve, an empty library
still renders, ids prefixed so several sleeves fit in one page.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET

import pytest

from dj import design, sleeve
from dj.analysis import identity

NS = "{http://www.w3.org/2000/svg}"
DAY = "2026-10-20"


def _identity(handle: str = "You", seed: str = "3f" * 32) -> dict:
    """A small identity in the shape dj.analysis.identity writes (no files needed)."""
    bands = []
    for n, name in enumerate(identity.BANDS):
        lo, hi = identity.band_range(n)
        slot = {0: 1, 1: 1, 3: 2, 4: 3, 5: 3}.get(n)
        bands.append({"band": name, "lo": lo, "hi": hi, "tracks": n + 1, "share": 0.1,
                      "lane": None if slot is None else "x", "slot": slot})  # fmt: skip
    return {
        "schema": 1, "seed": seed, "handle": handle, "date": DAY, "source": "exports/x.xml",
        "counts": {"tracks": 36, "axes": 6, "lanes": 3, "decades": 3, "bands": 8},
        "archetype": {"slug": "crate-archaeologist", "name": "The Crate Archaeologist", "meaning": "m", "booth_line": "b"},
        "lanes": [
            {"label": "100-109", "lo": 100, "hi": 109, "tracks": 7, "playlists": ["funk & disco 78-92"], "slot": 1},
            {"label": "119-122", "lo": 119, "hi": 122, "tracks": 6, "playlists": ["House/1.1_warm_up", "House/Deep/r"], "slot": 2},
            {"label": "122-127", "lo": 122, "hi": 127, "tracks": 9, "playlists": ["House/1.2_peak"], "slot": 3},
        ],
        "fingerprint": {
            "edges": list(identity.BAND_EDGES), "bands": bands,
            "rings": [{"decade": d, "tracks": t, "share": s} for d, t, s in
                      (("1990s", 10, 0.3), ("2000s", 6, 0.2), ("2010s", 16, 0.5))],
            "counts": [[1, 2, 0, 3, 1, 0, 2, 1], [0, 1, 1, 2, 0, 1, 1, 0], [2, 3, 1, 4, 3, 1, 1, 1]],
            "placed": 32, "no_year": 4, "no_bpm": 0,
        },
    }  # fmt: skip


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _ids(svg: str) -> list[str]:
    return re.findall(r'\bid="([^"]+)"', svg)


def _texts(root: ET.Element) -> list[str]:
    return ["".join(el.itertext()) for el in root.iter() if el.tag.endswith("text")]


# -- determinism ------------------------------------------------------------------------------


def test_identical_bytes_for_the_same_identity():
    assert sleeve.sleeve_svg(_identity()) == sleeve.sleeve_svg(copy.deepcopy(_identity()))
    assert sleeve.mini_sleeve_svg(_identity(), {"110-118": 4}, uid="a") == sleeve.mini_sleeve_svg(
        _identity(), {"110-118": 4}, uid="a")


def test_another_seed_gives_other_bytes():
    a, b = sleeve.sleeve_svg(_identity(seed="3f" * 32)), sleeve.sleeve_svg(_identity(seed="a1" * 32))
    assert a != b
    assert sleeve.rotation_of(_identity(seed="3f" * 32)) != sleeve.rotation_of(_identity(seed="a1" * 32))


def test_the_prng_stream_is_pinned():
    """SplitMix64: a change here would change every DJ's sleeve for the same export."""
    rand = sleeve._Rand("0123456789abcdef")
    assert [round(rand.next(), 12) for _ in range(3)] == [round(x, 12) for x in _expected_stream()]


def _expected_stream() -> list[float]:
    mask = (1 << 64) - 1
    state, out = 0x0123456789ABCDEF, []
    for _ in range(3):
        state = (state + 0x9E3779B97F4A7C15) & mask
        z = state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & mask
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
        z ^= z >> 31
        out.append((z >> 11) / float(1 << 53))
    return out


# -- valid, self-contained XML ----------------------------------------------------------------


def test_the_file_parses_and_is_a_square_12_inch_sleeve():
    root = _parse(sleeve.sleeve_svg(_identity()))
    assert root.tag == f"{NS}svg" and root.get("viewBox") == "0 0 1000 1000"
    assert root.find(f"{NS}title").text == "You: The Crate Archaeologist"
    desc = root.find(f"{NS}desc").text
    assert "rings are decades, 1990s inside to 2010s outside" in desc and "122-127 BPM, 9 tracks" in desc
    labelled = root.get("aria-labelledby").split()
    assert labelled == ["sleeve-title", "sleeve-desc"] and set(labelled) <= set(_ids(sleeve.sleeve_svg(_identity())))


def test_no_external_reference_anywhere():
    for svg in (sleeve.sleeve_svg(_identity()), sleeve.sleeve_svg(_identity(), inline=True, uid="hero"),
                sleeve.mini_sleeve_svg(_identity(), {}, uid="m")):  # fmt: skip
        body = svg.replace(f'xmlns="{sleeve.SVG_NS}"', "")
        assert "http" not in body
        assert not re.search(r"href|url\(|<script|<image|<use|@import|<foreignObject|<style", body, re.I)


def test_only_the_file_carries_the_namespace():
    assert svg_ns_count(sleeve.sleeve_svg(_identity())) == 1
    inline = sleeve.sleeve_svg(_identity(), inline=True)
    assert "http" not in inline and _parse(inline).tag == "svg"
    assert "http" not in sleeve.mini_sleeve_svg(_identity())


def svg_ns_count(svg: str) -> int:
    return svg.count("http")


def test_the_tempo_dial_matches_the_identity_bands():
    assert sleeve.BAND_EDGES == identity.BAND_EDGES and sleeve.BANDS_DEFAULT == len(identity.BANDS)
    texts = _texts(_parse(sleeve.sleeve_svg(_identity())))
    assert [t for t in texts if t in {str(e) for e in identity.BAND_EDGES}] == [str(e) for e in identity.BAND_EDGES]


def test_cells_wear_booth_slot_colours_and_text_wears_text_tokens():
    svg = sleeve.sleeve_svg(_identity())
    fills = set(re.findall(r'<path d="M[^"]*Z" fill="(#[0-9a-f]{6})"', svg))
    allowed = set(design.CATEGORICAL["dark"]) | {design.OTHER["dark"], design.TEXT["dark"]}
    assert fills and fills <= allowed
    assert {design.slot_hex(1), design.slot_hex(2), design.slot_hex(3)} <= fills
    text_fills = set(re.findall(r'<text [^>]*fill="(#[0-9a-f]{6})"', svg))
    assert text_fills <= {design.TEXT["dark"], design.TEXT_2["dark"]}


# -- text: escaped, never off the sleeve ------------------------------------------------------


@pytest.mark.parametrize("handle", ['<b>"Rock" & Roll\'s</b>', "Jørn Ébène 夜のDJ", "DJ \x07Bell\x00", "Ünïcødé ☃"])
def test_handles_are_escaped_and_parse(handle):
    svg = sleeve.sleeve_svg(_identity(handle=handle))
    root = _parse(svg)
    shown = " ".join(_texts(root))
    assert sleeve.clean(handle) in shown or all(part in shown for part in sleeve.clean(handle).split())
    assert "\x07" not in svg and "\x00" not in svg and "<b>" not in svg


def test_a_long_handle_wraps_and_is_clamped():
    handle = "Selector Marlo Venn and the Midnight Roller"
    lines, size = sleeve.handle_lines(handle)
    assert len(lines) == 2 and " ".join(lines) == handle
    assert size <= sleeve.HANDLE_MAX_TWO_LINES
    assert all(sleeve.text_em(line) * size <= sleeve.TEXT_W + 0.01 for line in lines)
    svg = sleeve.sleeve_svg(_identity(handle=handle))
    assert sum(1 for t in _texts(_parse(svg)) if t in lines) == 2


def test_a_long_handle_without_spaces_still_fits():
    handle = "X" * 60
    lines, size = sleeve.handle_lines(handle)
    assert "".join(lines) == handle and len(lines) == 2
    assert all(sleeve.text_em(line) * size <= sleeve.TEXT_W + 0.01 or size == sleeve.HANDLE_MIN for line in lines)
    svg = sleeve.sleeve_svg(_identity(handle=handle))
    assert 'textLength="872"' in svg  # clamped to the text width whatever the font


def test_a_short_handle_is_big_display_type():
    lines, size = sleeve.handle_lines("You")
    assert lines == ["You"] and size == sleeve.HANDLE_MAX_SIZE
    svg = sleeve.sleeve_svg(_identity())
    assert 'font-weight="900"' in svg and 'letter-spacing="-4.2"' in svg  # tight tracking
    assert "ui-sans-serif, system-ui" in svg


def _handle_and_archetype(svg: str) -> tuple[list[tuple[float, float]], float]:
    """((baseline, size) of every handle line, the archetype's baseline) of a sleeve."""
    handle = [(float(y), float(s)) for y, s in re.findall(r'<text x="64" y="([\d.]+)" font-size="([\d.]+)" '
                                                        r'font-weight="900"', svg)]  # fmt: skip
    sub = re.search(rf'<text x="64" y="([\d.]+)" font-size="{sleeve.SUB_SIZE:g}" font-weight="600"', svg)
    return handle, float(sub.group(1))


@pytest.mark.parametrize("handle", ["Peggy Gyu", "Jayjay", "DJ Sample", "Selector Marlo Venn and the Midnight Roller",
                                    "Gypsy jig quay spy jpg yogurt typography"])  # fmt: skip
def test_descenders_of_the_handle_clear_the_archetype_line(handle):
    """g, j, p, q, y reach about 0.23 em below the baseline; the archetype's ascenders about 0.75
    of its size above its own: 6 units at least between them, and between the two handle lines
    (a descender, then the next line's capitals at about 0.72 em). W-31 review."""
    handle_rows, sub_y = _handle_and_archetype(sleeve.sleeve_svg(_identity(handle=handle)))
    assert handle_rows
    last_y, size = handle_rows[-1]
    assert sub_y - last_y >= 0.23 * size + 0.75 * sleeve.SUB_SIZE + 6
    for (y0, s0), (y1, _s1) in zip(handle_rows, handle_rows[1:]):
        assert y1 - y0 >= 0.23 * s0 + 0.72 * s0
    top = handle_rows[0][0] - 0.72 * handle_rows[0][1]  # cap height of the first line
    assert top > sleeve.CY + sleeve.R_OUT + 30 + 5  # under the disc and the dial labels around it
    assert sub_y + 0.23 * sleeve.SUB_SIZE < 908  # the archetype's descenders stay above the rule


def test_liner_notes_are_the_three_biggest_lanes():
    texts = _texts(_parse(sleeve.sleeve_svg(_identity())))
    notes = [t for t in texts if t.endswith(" BPM") and t[0].isdigit()]
    assert notes == ["122-127 BPM", "100-109 BPM", "119-122 BPM"]
    assert "6 tracks · 1.1_warm_up +1" in texts


# -- edge cases -------------------------------------------------------------------------------


def test_an_empty_library_still_renders():
    empty = _identity()
    empty.update(lanes=[], counts={"tracks": 0, "axes": 6, "lanes": 0, "decades": 0, "bands": 8})
    empty["fingerprint"] = {**empty["fingerprint"], "rings": [], "counts": [], "placed": 0,
                            "bands": [{**b, "tracks": 0, "slot": None} for b in empty["fingerprint"]["bands"]]}  # fmt: skip
    svg = sleeve.sleeve_svg(empty)
    texts = _texts(_parse(svg))
    assert "No BPM lanes yet: playlists need 3 or more BPM-tagged tracks." in texts and "TRACKS" in texts
    assert _parse(sleeve.mini_sleeve_svg(empty)) is not None
    bare = sleeve.sleeve_svg({"seed": "", "handle": ""})  # nearly nothing at all
    assert "You" in _texts(_parse(bare))


# -- the mini sleeve --------------------------------------------------------------------------


def test_mini_ids_are_prefixed_and_distinct_per_uid():
    a = sleeve.mini_sleeve_svg(_identity(), {}, uid="p1")
    b = sleeve.mini_sleeve_svg(_identity(), {}, uid="p2")
    assert _ids(a) and all(i.startswith("p1") for i in _ids(a))
    assert not set(_ids(a)) & set(_ids(b))
    hero = sleeve.sleeve_svg(_identity(), inline=True, uid="hero-")
    assert all(i.startswith("hero-") for i in _ids(hero))
    root = _parse(a)
    assert root.get("width") == "240" and root.get("height") == "240"


def test_mini_recolours_bands_by_the_slots_given():
    plain = sleeve.mini_sleeve_svg(_identity(), {}, uid="a")
    recoloured = sleeve.mini_sleeve_svg(_identity(), {"110-118": 4, "128-135": 3, "<100": None}, uid="a")
    assert design.slot_hex(4) not in plain and design.slot_hex(4) in recoloured
    # Other cells: plain = bands 110-118, 128-135, 135+ (7 cells with tracks); recoloured = <100, 135+ (4)
    assert (plain.count(design.OTHER["dark"]), recoloured.count(design.OTHER["dark"])) == (7, 4)
    # slot 5 is a palette slot but past the 4 a chart shows: the guard (dj.design.chart_slot, D-26)
    # draws its band in the Other grey (identity.json itself never gives a lane slot 5, D-27)
    folded = sleeve.mini_sleeve_svg(_identity(), {"110-118": 4, "128-135": 5, "<100": None}, uid="a")
    assert design.slot_hex(5) not in folded and folded.count(design.OTHER["dark"]) == 7  # <100, 128-135, 135+


@pytest.mark.parametrize(("slots", "uid", "size"), [
    ({"999-1000": 1}, "a", 240), ({"110-118": 9}, "a", 240), ({"110-118": True}, "a", 240),
    ({}, "1bad", 240), ({}, "has space", 240), ({}, "a", 4), ({}, "a", True),
])  # fmt: skip
def test_mini_refuses_bad_arguments(slots, uid, size):
    with pytest.raises(ValueError):
        sleeve.mini_sleeve_svg(_identity(), slots, uid=uid, size=size)


def test_a_sleeve_drawn_small_leaves_out_its_small_print():
    """The report's hero copy (about 40% of the viewBox) drops the tempo dial and the lane detail
    lines, keeps the lane labels, and every text left is at least 16 units tall (W-31 review)."""
    data = _identity("DJ Test")
    full, small = sleeve.sleeve_svg(data), sleeve.sleeve_svg(data, inline=True, small_print=False)
    root = _parse(small.replace("<svg ", f'<svg xmlns="{NS[1:-1]}" ', 1))
    texts = _texts(root)
    assert "7 tracks · funk & disco 78-92" in _texts(_parse(full)) and "7 tracks · funk & disco 78-92" not in texts
    assert "100-109 BPM" in texts and "DJ Test" in texts and "DJ-LIBRARIAN" in texts
    assert not any(t in texts for t in ("110", "118", "125", "128", "135"))  # the dial is gone
    sizes = [float(s) for s in re.findall(r'font-size="([\d.]+)"', small)]
    assert sizes and min(sizes) >= 16
    header = re.findall(r'font-size="([\d.]+)"[^>]*>(?:DJ-LIBRARIAN|\d+ TRACKS)', full)
    assert header and all(float(s) >= 24 for s in header)
