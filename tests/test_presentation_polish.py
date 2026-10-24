"""W-30b, the PM's polish of the W-31 report and sleeve.

1. The hero and "How you work" show Claude's words without their "Words by Claude, from ..."
   caption; the colophon is the one place that credits them; the "table" links stay.
3. At most 4 categorical slots in any single chart (D-26, Q-29): a fixture of 6 lanes gives 4
   colours + "Other" on the hero sleeve, in the sleeve's lane notes, on the crate wall and its
   legend, and on a proposal's mini sleeve (dj.design.MAX_SLOTS_PER_CHART). W-32 (Q-30, D-27)
   changed which lanes keep a colour: the four biggest, numbered by BPM, assigned once in
   identity.json (tests/test_lane_slots.py runs the whole chain). These tests were rewritten for
   that rule; an identity.json written before it (slots 1-6 by BPM) still draws 4 colours at
   most, through the guard (dj.design.chart_slot), and the page then never calls its grey lanes
   the smaller ones (they are the fastest).
4. Small collections read as a full record: no ring under MIN_RING, the empty cells of a ring
   with fewer than 3 tracks one dim step lighter (cells with tracks keep the brightness scale,
   and the caption and tooltips say why), every ring of a 50-track library named, the labels
   within 45 degrees of level and at least 11 px wherever the hero draws the sleeve (1100 px
   down to a 360 px phone); the same identity still gives the same bytes.
"""

from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import Path

import pytest

from dj import design, report, report_charts, sleeve
from dj.analysis import identity as identity_mod
from dj.treeschema import TreeNode

DAY = date(2026, 10, 20)
REPO = Path(__file__).resolve().parents[1]
BOOTH = design.CATEGORICAL["dark"]
CELL = re.compile(r'<path d="M[^"]*Z" fill="(#[0-9a-f]{6})" fill-opacity="([\d.]+)"/>')


# -- fixtures --------------------------------------------------------------------------------------


def six_lanes() -> dict:
    """An identity in the shape dj.analysis.identity writes, with 6 lanes (one per BPM band from
    the slowest) and the fastest lane the biggest. The slots come from dj.analysis.identity.lanes
    (Q-30, D-27): the four biggest, 96-99, 119-121, 123-124 and 126-127, take slots 1-4 in BPM
    order; 104-108 and 112-116 are Other."""
    ranges = ((96, 99), (104, 108), (112, 116), (119, 121), (123, 124), (126, 127))
    tracks = (12, 5, 6, 8, 9, 30)
    lanes = identity_mod.lanes({"lanes": [
        {"label": f"{lo}-{hi}", "lo": lo, "hi": hi, "tracks": t, "playlists": [f"Lanes/lane{n}"], "key": f"lane:{n}"}
        for n, ((lo, hi), t) in enumerate(zip(ranges, tracks), 1)]})  # fmt: skip
    bands = []
    for n, name in enumerate(identity_mod.BANDS):
        lo, hi = identity_mod.band_range(n)
        lane = lanes[n] if n < 6 else None
        bands.append({"band": name, "lo": lo, "hi": hi, "tracks": 4 + n, "share": 0.1,
                      "lane": lane["label"] if lane else None, "slot": lane["slot"] if lane else None})  # fmt: skip
    return {
        "schema": 1, "seed": "5e" * 32, "handle": "DJ Six", "date": "2026-10-20", "source": "exports/x.xml",
        "counts": {"tracks": 65, "axes": 6, "lanes": 6, "decades": 3, "bands": 8},
        "archetype": {"slug": "omnivore", "name": "The Omnivore", "meaning": "m", "booth_line": "b"},
        "axes": {"depth": {"name": "Depth", "score": 50, "inputs": {}}},
        "order": ["depth"], "top": ["depth"],
        "lanes": lanes,
        "fingerprint": {
            "edges": list(identity_mod.BAND_EDGES), "bands": bands,
            "rings": [{"decade": d, "tracks": t, "share": s} for d, t, s in
                      (("1990s", 20, 0.3), ("2000s", 15, 0.2), ("2010s", 30, 0.5))],
            "counts": [[2, 3, 2, 3, 4, 3, 2, 1], [1, 2, 2, 2, 3, 2, 2, 1], [3, 4, 3, 4, 5, 4, 4, 3]],
            "placed": 65, "no_year": 0, "no_bpm": 0,
        },
    }  # fmt: skip


def legacy_six_lanes() -> dict:
    """The same identity as identity.json was written before W-32: slots 1-6 by BPM, slowest first."""
    data = copy.deepcopy(six_lanes())
    for n, lane in enumerate(data["lanes"], 1):
        lane["slot"] = n
    for n, band in enumerate(data["fingerprint"]["bands"]):
        band["slot"] = n + 1 if band["lane"] else None
    return data


def six_lane_graph() -> dict:
    """One top-level folder per lane, each holding that lane's one playlist, plus a loose playlist
    in no lane."""
    nodes, edges = [], []
    for n in range(1, 7):
        nodes.append({"id": f"f{n}", "name": f"Folder {n}", "path": f"Lanes{n}", "kind": "folder", "depth": 1,
                      "tracks": 3 + n})  # fmt: skip
        nodes.append({"id": f"p{n}", "name": f"lane{n}", "path": f"Lanes/lane{n}", "kind": "playlist", "depth": 2,
                      "tracks": 3 + n})  # fmt: skip
        edges.append({"source": f"f{n}", "target": f"p{n}"})
    nodes.append({"id": "loose", "name": "loose", "path": "loose", "kind": "playlist", "depth": 1, "tracks": 4})
    return {"nodes": nodes, "edges": edges}


def small_library(rings=(("1960s", 1), ("1970s", 2), ("1980s", 5), ("1990s", 12), ("2000s", 14), ("2010s", 16))) -> dict:
    """A 50-track identity: the two oldest decades hold 1 and 2 tracks (sparse rings)."""
    data = copy.deepcopy(six_lanes())
    total = sum(t for _d, t in rings)
    counts = []
    for _decade, t in rings:
        row = [0] * 8
        for k in range(t):
            row[(k * 3) % 8] += 1
        counts.append(row)
    data["fingerprint"].update(rings=[{"decade": d, "tracks": t, "share": round(t / total, 4)} for d, t in rings],
                               counts=counts, placed=total)  # fmt: skip
    data["counts"].update(tracks=total, decades=len(rings))
    return data


def cells(svg: str) -> list[tuple[str, float]]:
    return [(hexa, float(opacity)) for hexa, opacity in CELL.findall(svg)]


def lane_note_swatches(svg: str) -> list[str]:
    return re.findall(r'<rect x="[\d.]+" y="\d+" width="16" height="16" rx="3" fill="(#[0-9a-f]{6})"/>', svg)


# -- 1. no "Words by Claude" caption in the hero or in "How you work" ------------------------------

LINER = "# Liner notes\n\n> Words by Claude, from profile/identity.json.\n\nSix decades in the crates.\n"
HABITS = "# Who you are as a DJ\n\n> Words by Claude, from profile/stats.md and profile/facts.json.\n\nHouse up front.\n"


def test_the_hero_and_how_you_work_carry_no_words_by_caption():
    page = report.page(day=DAY, profile=None, habits=HABITS, structure=None, graph=None, entries=[],
                       identity=six_lanes(), liner=LINER)  # fmt: skip
    who = re.search(r'<section id="who">(.*?)</section>', page, re.DOTALL).group(1)
    assert "Words by Claude" not in who and 'class="prov"' not in who
    assert "<p>Six decades in the crates.</p>" in who and "<p>House up front.</p>" in who
    assert '<a class="table-link" href="../profile/identity.json">table</a>' in who  # the table links stay
    colophon = re.search(r'<footer class="colophon">(.*?)</footer>', page, re.DOTALL).group(1)
    assert "Words about you by Claude, from profile/identity.md and profile/habits.md." in colophon
    assert ".liner .prov" not in page


def test_markdown_keeps_a_quote_that_is_not_provenance():
    text = "# Title\n\n> Words by Claude, from x.md.\n\n> Measured by code: y.\n\n> A line the DJ quoted.\n"
    shown = report.markdown(text, provenance=False)
    assert "Words by" not in shown and "Measured by" not in shown
    assert '<p class="prov">A line the DJ quoted.</p>' in shown
    assert report.markdown(text).count('<p class="prov">') == 3  # elsewhere the line stays


# -- 3. at most 4 colours per chart (D-26, Q-29) ---------------------------------------------------


def test_the_cap_is_one_constant():
    assert design.MAX_SLOTS_PER_CHART == 4
    assert [design.chart_slot(s) for s in (None, 0, 1, 4, 5, 8, 9, True, "2")] == [None, None, 1, 4, None, None,
                                                                                  None, None, None]  # fmt: skip
    assert [report_charts.slot_class(s) for s in (1, 4, 5, 8, None)] == ["s1", "s4", "s0", "s0", "s0"]
    text = (REPO / "docs" / "design.md").read_text(encoding="utf-8")
    assert "At most 4 colours in one chart" in text and "MAX_SLOTS_PER_CHART" in text and "D-26" in text


def test_six_lanes_give_four_colours_and_other_on_the_hero_sleeve():
    data = six_lanes()
    assert [lane["slot"] for lane in data["lanes"]] == [1, None, None, 2, 3, 4]
    svg = sleeve.sleeve_svg(data, inline=True, uid="hero-", small_print=False)
    fills = {hexa for hexa, _o in cells(svg)}
    assert fills - {design.TEXT["dark"]} == set(BOOTH[:4]) | {design.OTHER["dark"]}  # 4 colours + Other
    assert not fills & set(BOOTH[4:])
    # the lane notes (the sleeve's legend): the three biggest lanes, always among the coloured four,
    # each in its identity.json slot (the biggest, the fastest, is slot 4: W-30 drew it grey)
    for drawn in (svg, sleeve.sleeve_svg(data)):
        notes = re.findall(r'font-size="24" font-weight="700" fill="#[0-9a-f]{6}">([^<]+)</text>', drawn)
        assert notes == ["126-127 BPM", "96-99 BPM", "123-124 BPM"]
        assert lane_note_swatches(drawn) == [BOOTH[3], BOOTH[0], BOOTH[2]]
    # the centre label's ring wears the biggest lane, in its colour
    assert f'r="76" fill="{design.SURFACE["dark"]}" stroke="{BOOTH[3]}"' in svg
    assert "126-127 BPM, 30 tracks" in svg and "(Other)" not in svg  # the description says it too


def test_a_grey_lane_note_keeps_the_word_other():
    """The label fits its column: " BPM" goes before "Other" does; a label too long for either is
    cut in the BPM part and keeps " · Other"; a lane in colour never says Other. (A lane note in
    the grey needs a slot the guard refuses or None: never one of the three biggest from W-32 on.)"""
    width = sleeve.TEXT_W / 3 - 36
    assert sleeve._lane_label({"label": "96-99", "slot": 5}, width, 24) == "96-99 BPM · Other"
    assert sleeve._lane_label({"label": "126-127", "slot": 6}, width, 24) == "126-127 · Other"
    assert sleeve._lane_label({"label": "126-127", "slot": None}, width, 24) == "126-127 · Other"
    long = sleeve._lane_label({"label": "1" * 40, "slot": 7}, width, 24)
    assert long.endswith("… · Other") and sleeve.text_em(long, 0.0) * 24 <= width
    assert sleeve._lane_label({"label": "126-127", "slot": 4}, width, 24) == "126-127 BPM"


def test_six_lanes_give_four_colours_and_other_on_the_crate_wall_and_its_legend():
    data = six_lanes()
    wall = report_charts.crate_wall(six_lane_graph(), {}, data)
    classes = set(re.findall(r'class="mark (?:lane|outline) (s\d)"', wall.svg))
    assert classes == {"s1", "s2", "s3", "s4", "s0"}
    keys = [(kind, label) for kind, label in wall.legend if kind.startswith("s")]
    assert keys == [("s1", "96-99 BPM"), ("s2", "119-121 BPM"), ("s3", "123-124 BPM"), ("s4", "126-127 BPM"),
                    ("s0", "Other (2 lanes), or no lane")]  # fmt: skip
    # a grey (Other) lane is still named in its tooltip
    assert 'data-tip="5 tracks · Lanes/lane2 · lane 104-108 BPM"' in wall.svg
    assert re.search(r'data-tip="5 tracks · Lanes/lane2 · [^"]*"><path class="mark lane s0"', wall.svg)
    without_loose = six_lane_graph()
    without_loose["nodes"] = [n for n in without_loose["nodes"] if n["id"] != "loose"]
    legend = report_charts.crate_wall(without_loose, {}, data).legend
    assert legend[-1] == ("s0", "Other (2 lanes)")


def test_six_lanes_give_four_colours_and_other_on_a_mini_sleeve():
    data = six_lanes()
    nodes = [TreeNode("folder", f"base{n}", children=(TreeNode("playlist", "p", fill_from=(f"Lanes/lane{n}",)),))
             for n in range(1, 7)]  # fmt: skip
    taste = {"bpm_playlists": [{"path": f"Lanes/lane{n}", "tracks": 3 + n, "lo": b["lo"] or 90, "hi": (b["hi"] or 140) - 1}
                               for n, b in zip(range(1, 7), data["fingerprint"]["bands"])]}  # fmt: skip
    slots, branches = report_charts.proposal_colours(nodes, data, taste)
    assert [b.slot for b in branches] == [1, None, None, 2, 3, 4]  # each base wears its lane's identity slot
    mini, _branches = report._mini(1, nodes, data, taste)
    fills = {hexa for hexa, _o in cells(mini)} - {design.TEXT["dark"]}
    assert fills == set(BOOTH[:4]) | {design.OTHER["dark"]}  # 4 colours + Other
    tree = report._tree_part(branches, True)
    assert set(re.findall(r'<span class="sw (s\d)">', tree)) <= {"s1", "s2", "s3", "s4", "s0"}
    assert "lane 104-108 BPM (Other)" in tree  # an Other lane says it wears the Other grey


def test_a_page_with_six_lanes_says_once_why_two_lanes_are_grey():
    page = report.page(day=DAY, profile=None, habits=None, structure={"reveals": ["x"]}, graph=six_lane_graph(),
                       entries=[], identity=six_lanes(), liner=None)  # fmt: skip
    assert "grey for tracks outside your lanes and in your smaller lanes (only your four biggest lanes get a " \
           "colour)" in page  # fmt: skip
    body = page.split("</style>", 1)[1]
    assert not re.search(r'class="[^"]*\bs[5-8]\b', body)  # no slot past 4 anywhere on the page
    for colour in BOOTH[4:]:
        assert colour not in body
    three = identity_mod.lanes({"lanes": six_lanes()["lanes"][:3]})  # three lanes: all in colour
    assert [lane["slot"] for lane in three] == [1, 2, 3]
    page = report.page(day=DAY, profile=None, habits=None, structure=None, graph=None, entries=[],
                       identity={**six_lanes(), "lanes": three}, liner=None)  # fmt: skip
    assert report.OTHER_LANES not in page and "smaller lanes" not in page


def test_an_older_identity_json_still_draws_four_colours_at_most():
    """An identity.json written before W-32 numbers six lanes 1-6 by BPM. The charts read those
    slots as they are and the guard (dj.design.chart_slot) draws 5 and 6 grey, so no chart shows a
    fifth colour, and the legend still counts them as Other, until identity runs again."""
    data = legacy_six_lanes()
    svg = sleeve.sleeve_svg(data, inline=True, uid="hero-", small_print=False)
    assert {hexa for hexa, _o in cells(svg)} - {design.TEXT["dark"]} == set(BOOTH[:4]) | {design.OTHER["dark"]}
    wall = report_charts.crate_wall(six_lane_graph(), {}, data)
    assert set(re.findall(r'class="mark (?:lane|outline) (s\d)"', wall.svg)) == {"s1", "s2", "s3", "s4", "s0"}
    assert wall.legend[-1] == ("s0", "Other (2 lanes), or no lane")
    page = report.page(day=DAY, profile=None, habits=None, structure={"reveals": ["x"]}, graph=six_lane_graph(),
                       entries=[], identity=data, liner=None)  # fmt: skip
    body = page.split("</style>", 1)[1]
    assert not re.search(r'class="[^"]*\bs[5-8]\b', body) and not any(c in body for c in BOOTH[4:])


def test_an_older_identity_json_never_calls_its_grey_lanes_the_smaller_ones():
    """Its grey lanes are the fastest (slots 5 and 6 by BPM), and here the fastest is the biggest
    lane (30 tracks): the page says only that a chart colours four lanes at most and how to colour
    the four biggest, on the sleeve caption, the proposals note and the mini sleeve's tooltip."""
    data = legacy_six_lanes()
    assert report_charts.stale_slots(data) and not report_charts.stale_slots(six_lanes())
    assert not report_charts.stale_slots(None) and not report_charts.stale_slots({"lanes": [{"slot": None}]})
    page = report.page(day=DAY, profile=None, habits=None, structure={"reveals": ["x"]}, graph=six_lane_graph(),
                       entries=[], identity=data, liner=None)  # fmt: skip
    assert report.OTHER_LANES not in page and "smaller lanes" not in page and "not one of your four" not in page
    assert f"grey for tracks outside your lanes and in 2 of your lanes ({report.OLD_SLOTS})" in page
    assert "say “draw my sleeve” to colour your four biggest" in report.OLD_SLOTS
    nodes = [TreeNode("folder", f"base{n}", children=(TreeNode("playlist", "p", fill_from=(f"Lanes/lane{n}",)),))
             for n in range(1, 7)]  # fmt: skip
    taste = {"bpm_playlists": [{"path": f"Lanes/lane{n}", "tracks": 3 + n, "lo": b["lo"] or 90, "hi": (b["hi"] or 140) - 1}
                               for n, b in zip(range(1, 7), data["fingerprint"]["bands"])]}  # fmt: skip
    _slots, branches = report_charts.proposal_colours(nodes, data, taste)
    assert [b.slot for b in branches] == [1, 2, 3, 4, 5, 6]  # read as identity.json holds them
    mini, _branches = report._mini(1, nodes, data, taste)
    assert f"lands in base6 (lane 126-127 BPM, Other: {report.OLD_OWNER})" in mini
    assert "not one of your four biggest" not in mini
    entry = {"slug": "x", "family": "bases", "name": "X", "principle": "p", "cost_minutes": 5, "lands": [],
             "trigger": "build x", "tree": type("Tree", (), {"nodes": tuple(nodes)})()}  # fmt: skip
    note = re.search(r'<p class="mini-note">(.*?)</p>', report._proposals([entry], data, taste)).group(1)
    assert note.endswith(f"or a branch with no lane colour of its own ({report.OLD_SLOTS}). Outline: a branch no "
                         "tempo band lands in, so it has no colour on the sleeve.")  # fmt: skip
    # the current identity.json keeps the reason Q-30 gives
    fresh = report._proposals([entry], six_lanes(), taste)
    assert f"no lane colour of its own ({report.OTHER_LANES})" in fresh and report.OLD_SLOTS not in fresh


# -- 4. small collections read as a full record ---------------------------------------------------


def hero_sleeve_px() -> float:
    """The rendered width of the hero sleeve on a 1100 px page, from the report's own CSS."""
    css = report.CSS
    page_w, pad = map(int, re.search(r"\.top,main\{max-width:(\d+)px;margin:0 auto;padding-left:(\d+)px", css).groups())
    art, words, gap = map(int, re.search(r'\.hero\{display:grid;grid-template-columns:minmax\(0,(\d+)fr\) '
                                         r'minmax\(0,(\d+)fr\);grid-template-areas:"art main";\ncolumn-gap:(\d+)px', css).groups())  # fmt: skip
    return (page_w - 2 * pad - gap) * art / (art + words)


def test_decade_labels_are_at_least_11_px_in_the_hero():
    px_per_unit = hero_sleeve_px() / sleeve.VIEW
    assert round(hero_sleeve_px()) == 456
    svg = sleeve.sleeve_svg(small_library(), inline=True, uid="hero-", small_print=False)
    group = re.search(r'<g class="decades" text-anchor="middle" font-size="([\d.]+)" font-weight="700"[^>]*>(.*?)</g>',
                      svg).group  # fmt: skip
    assert float(group(1)) * px_per_unit >= 11
    # every ring of the 50-track library is named, the sparse 1960s and 1970s included
    assert re.findall(r">(\d{4}s)</text>", group(2)) == ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s"]
    assert sleeve.DECADE_PITCH <= sleeve.MIN_RING + sleeve.GAP  # two floor rings side by side: both named


def decade_units(css: str, width: float) -> float:
    """The decade labels' size in viewBox units for a hero sleeve `width` px wide, by the rule in
    the report's CSS: max(Apx, calc(Bpx - Ccqi)), 1cqi = width / 100."""
    a, b, c = map(float, re.search(r"\.sleeve \.decades\{font-size:max\(([\d.]+)px,calc\(([\d.]+)px - "
                                   r"([\d.]+)cqi\)\)\}", css).groups())  # fmt: skip
    return max(a, b - c * width / 100)


def test_decade_labels_stay_at_least_11_px_on_a_narrower_hero():
    """At mid width (a two-column hero) and on a phone the hero sleeve is narrower than at 1100 px:
    the report's CSS raises the labels so they stay at least 11 px down to a 360 px phone, and
    leaves them at the drawn size from a sleeve 424 px wide up (the 1100 px hero, 456 px)."""
    page = report.page(day=DAY, profile=None, habits=None, structure=None, graph=None, entries=[],
                       identity=small_library(), liner=None)  # fmt: skip
    css = page.split("</style>", 1)[0]
    assert ".sleeve .sleeve-wrap{container-type:inline-size}" in css
    for width in range(report.DECADE_NARROW, 1101):
        assert decade_units(css, width) * width / sleeve.VIEW >= 11, width
    assert decade_units(css, 456) == sleeve.DECADE_SIZE  # the 1100 px hero: as drawn
    assert decade_units(css, 390 - 2 * 16) * (390 - 2 * 16) / sleeve.VIEW >= 11  # a 390 px phone
    assert '<g class="decades"' in page


def level_bands(data: dict) -> list[int]:
    """The bands whose middle lies within 45 degrees of the top or the bottom of the disc."""
    import math

    n = len(data["fingerprint"]["bands"])
    rotation = sleeve.rotation_of(data, n)
    out = []
    for k in range(n):
        d = math.degrees(rotation + (k + 0.5) * 2 * math.pi / n) % 360
        if min(d, 360 - d) <= 45 or abs(d - 180) <= 45:
            out.append(k)
    return out


def test_the_labels_run_along_the_emptiest_band_and_stay_upright():
    """The decade labels hide the least: they run along the middle of the band with the fewest
    tracks among the bands near the top or the bottom (the sample's 135+ holds none), each on its
    own ring, turned along the ring, never more than 45 degrees from level."""
    import json
    import math

    sample = json.loads((REPO / "docs" / "samples" / "profile" / "identity.json").read_text(encoding="utf-8"))
    for data in (sample, small_library()):
        bands = data["fingerprint"]["bands"]
        rotation = sleeve.rotation_of(data, len(bands))
        angle = sleeve.label_spoke(data, rotation, len(bands))
        totals = [sum(row[k] for row in data["fingerprint"]["counts"]) for k in range(len(bands))]
        k = round((angle + math.pi / 2 - rotation) / (2 * math.pi / len(bands)) - 0.5)
        level = level_bands(data)
        assert k in level and totals[k] == min(totals[j] for j in level), (totals, k, level)
        svg = sleeve.sleeve_svg(data)
        placed = re.findall(r'<text x="([\d.-]+)" y="([\d.-]+)" transform="rotate\(([\d.-]+) [\d.-]+ [\d.-]+\)">(\d{4}s)</text>', svg)
        mids = dict(sleeve.decade_labels(data))
        assert [name for *_xy, name in placed] == list(mids)
        for x, y, turn, name in placed:
            r = math.hypot(float(x) - sleeve.CX, float(y) - sleeve.CY)
            assert abs(abs(r - mids[name]) - sleeve.DECADE_SIZE * 0.36) < 0.2  # the digits sit on the ring
            assert abs(math.atan2(float(y) - sleeve.CY, float(x) - sleeve.CX) - math.atan2(math.sin(angle), math.cos(angle))) < 0.01
            assert abs((float(turn) + 180) % 360 - 180) <= 45 + 1e-6, (name, turn)  # upright, near level
    assert totals  # the sample's 135+ band is empty: the labels sit there
    # the 50-track library's emptiest bands sit near 3 and 9 o'clock: the labels go elsewhere
    small = small_library()
    small_totals = [sum(row[k] for row in small["fingerprint"]["counts"]) for k in range(8)]
    assert not set(level_bands(small)) & {k for k, t in enumerate(small_totals) if t == min(small_totals)}
    assert sleeve.label_spoke(sample, sleeve.rotation_of(sample), 8) == pytest.approx(
        -math.pi / 2 + sleeve.rotation_of(sample) + 7.5 * 2 * math.pi / 8)


def test_every_ring_is_at_least_the_minimum_width_and_thickness_follows_the_share():
    data = small_library()
    names, bounds, _counts = sleeve.ring_bounds(data)
    widths = [r1 - r0 for r0, r1 in bounds]
    assert names[:2] == ["1960s", "1970s"] and min(widths) >= sleeve.MIN_RING - 1e-9
    assert widths[0] == pytest.approx(sleeve.MIN_RING) and widths[1] == pytest.approx(sleeve.MIN_RING)
    shares = [r["share"] for r in data["fingerprint"]["rings"]]
    order = sorted(range(len(shares)), key=lambda i: shares[i])
    assert all(widths[a] <= widths[b] + 1e-9 for a, b in zip(order, order[1:]))
    assert bounds[-1][1] == pytest.approx(sleeve.R_OUT)  # the disc stays the same size
    assert report_charts._ring_bounds(data) == (names, bounds, _counts)  # the hover cells sit on them


def test_a_sparse_ring_has_its_empty_cells_one_dim_step_lighter():
    data = small_library()
    svg = sleeve.sleeve_svg(data)
    drawn = cells(svg)
    n_bands = len(data["fingerprint"]["bands"])
    rows = [drawn[i * n_bands:(i + 1) * n_bands] for i in range(len(data["fingerprint"]["rings"]))]
    empty = design.TEXT["dark"]
    lifted = round(sleeve.EMPTY_OPACITY + sleeve.DIM_STEP, 2)
    assert sleeve.sparse_rings(data) == [0, 1]
    for ring, row in enumerate(rows):
        sparse = sum(data["fingerprint"]["counts"][ring]) < sleeve.SPARSE_TRACKS
        empties = [o for hexa, o in row if hexa == empty]
        assert set(empties) <= ({lifted} if sparse else {sleeve.EMPTY_OPACITY}), ring
        assert empties or not sparse, ring  # a sparse ring is mostly empty cells, all lifted
    # a cell with tracks is never lifted: the 1-track cell of the 1-track ring is as bright as a
    # 1-track cell anywhere
    biggest = max(c for row in data["fingerprint"]["counts"] for c in row)
    assert [o for hexa, o in rows[0] if hexa != empty] == [round(0.3 + 0.7 * 1 / biggest, 2)]


def test_the_brighter_the_cell_the_more_tracks_on_every_ring():
    """W-30b review: a 1-track cell in a sparse ring next to rings of 40 and 500 tracks is never
    brighter than a cell with more tracks in the same colour, and every empty cell, lifted or
    not, stays under the dimmest cell with tracks."""
    data = small_library(rings=(("1990s", 1), ("2000s", 40), ("2010s", 500)))
    data["fingerprint"]["counts"] = [[1, 0, 0, 0, 0, 0, 0, 0], [5, 1, 2, 3, 4, 10, 15, 0],
                                     [30, 40, 60, 70, 80, 90, 100, 30]]  # fmt: skip
    drawn = cells(sleeve.sleeve_svg(data))
    counts = [c for row in data["fingerprint"]["counts"] for c in row]
    assert len(drawn) == len(counts)
    by_colour: dict[str, list[tuple[int, float]]] = {}
    for (hexa, opacity), count in zip(drawn, counts):
        if count:
            by_colour.setdefault(hexa, []).append((count, opacity))
    for hexa, pairs in by_colour.items():
        for count_a, op_a in pairs:
            for count_b, op_b in pairs:
                assert not (count_a < count_b and op_a > op_b), (hexa, count_a, op_a, count_b, op_b)
    dimmest = min(o for (_hexa, o), count in zip(drawn, counts) if count)
    assert max(o for (_hexa, o), count in zip(drawn, counts) if not count) < dimmest


def test_the_caption_and_the_tooltips_say_why_a_sparse_ring_is_lighter():
    page = report.page(day=DAY, profile=None, habits=None, structure=None, graph=None, entries=[],
                       identity=small_library(), liner=None)  # fmt: skip
    caption = re.search(r'<figure class="sleeve">.*?<figcaption>(.*?)</figcaption>', page, re.DOTALL).group(1)
    assert f"the more tracks; {sleeve.SPARSE_NOTE}." in caption
    assert "a decade with under 3 tracks has its empty cells drawn a step lighter, so it shows" in caption
    hits = report_charts.sleeve_hits(small_library())
    note = "drawn a step lighter: the decade has under 3 tracks"
    assert 'data-tip="0 tracks · 1960s · ' in hits
    tips = re.findall(r'data-tip="([^"]+)"', hits)
    assert all((note in tip) == (tip.startswith("0 tracks · 1960s") or tip.startswith("0 tracks · 1970s"))
               for tip in tips)  # fmt: skip
    full = report.page(day=DAY, profile=None, habits=None, structure=None, graph=None, entries=[],
                       identity=six_lanes(), liner=None)  # fmt: skip
    assert sleeve.SPARSE_NOTE not in full and "step lighter" not in full  # no sparse ring, no note


def test_many_decades_share_the_room_and_labels_skip_rather_than_touch():
    rings = tuple((f"{1930 + 10 * n}s", 5 + n) for n in range(10))
    data = small_library(rings)
    _names, bounds, _counts = sleeve.ring_bounds(data)
    widths = [r1 - r0 for r0, r1 in bounds]
    assert max(widths) - min(widths) < 1e-6  # all at the floor the room allows
    labels = sleeve.decade_labels(data)
    assert labels[0][0] == "1930s" and labels[-1][0] == "2020s" and len(labels) < 10
    mids = [mid for _name, mid in labels]
    assert all(b - a >= sleeve.DECADE_PITCH for a, b in zip(mids, mids[1:]))


def test_a_small_library_still_gives_the_same_bytes():
    a = sleeve.sleeve_svg(small_library())
    b = sleeve.sleeve_svg(copy.deepcopy(small_library()))
    assert a == b and sleeve.mini_sleeve_svg(small_library()) == sleeve.mini_sleeve_svg(small_library())
    assert ">1960s</text>" in a and ">1960s</text>" not in sleeve.mini_sleeve_svg(small_library())


def test_no_labels_without_release_years():
    data = small_library()
    data["fingerprint"].update(rings=[], counts=[])
    assert sleeve.decade_labels(data) == []
    assert "s</text>" not in sleeve.sleeve_svg(data).split("DJ-LIBRARIAN")[0]
