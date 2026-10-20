"""dj.report redesign (W-31): the sleeve hero, the theme toggle, the crate wall, the proposal
cards with their mini sleeves, the sticky next action, and the design rules of docs/design.md
(R-401, R-403, R-404, R-406, R-408, R-1405).

The synthetic fixture library (tests/xml_fixtures.py) through the whole chain, a handle in
library.yaml, Claude's two files written by the test, then one render."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest
import xml_fixtures as fx

from dj import design, libfolder, report, report_charts
from dj.analysis import proposals as P
from dj.analysis import run_all

DAY = date(2026, 10, 20)
HANDLE = "DJ Test"
LINER = """# Liner notes

> Words by Claude, from profile/identity.json.

Your crates run 6 decades deep, from the 1970s to the 2020s.

Depth 94 and Breadth 81 carry it.
"""
HABITS = "# Who you are as a DJ\n\n> Words by Claude, from profile/stats.md and profile/facts.json.\n\nHouse up front.\n"


def make_library(root: Path, spec: dict | None = None, dj_name: str | None = HANDLE) -> Path:
    libfolder.scaffold(root, device="windows", today=DAY, dj_name=dj_name)
    libfolder.import_export(root, fx.write_xml(root.parent / "collection.xml", spec), today=DAY)
    return root


@pytest.fixture(scope="module")
def lib(tmp_path_factory) -> Path:
    root = make_library(tmp_path_factory.mktemp("design") / "dj-library")
    result = run_all.analyze(root, today=DAY)
    assert result["failed"] == []
    (root / "profile" / "identity.md").write_text(LINER, encoding="utf-8")
    (root / "profile" / "habits.md").write_text(HABITS, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def page(lib) -> str:
    return report.render(lib, today=DAY).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def identity(lib) -> dict:
    return json.loads((lib / "profile" / "identity.json").read_text(encoding="utf-8"))


def section(text: str, name: str) -> str:
    m = re.search(rf'<section id="{name}">(.*?)</section>', text, re.DOTALL)
    assert m, name
    return m.group(1)


def svg_of(text: str, cls: str) -> str:
    m = re.search(rf'<svg class="{cls}".*?</svg>', text, re.DOTALL)
    assert m, cls
    return m.group(0)


class Tags(HTMLParser):
    """Every start tag with its attributes, and the direct <li> count of every list."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict]] = []
        self.stack: list[list] = []
        self.sizes: list[int] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag in ("ul", "ol"):
            self.stack.append([tag, 0])
        elif tag == "li" and self.stack:
            self.stack[-1][1] += 1

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag in ("ul", "ol") and self.stack:
            self.sizes.append(self.stack.pop()[1])


def tags(text: str) -> Tags:
    parser = Tags()
    parser.feed(text)
    return parser


# -- the hero (R-1405) ------------------------------------------------------------------------------


def test_the_hero_has_the_sleeve_the_handle_and_the_archetype(page, identity):
    who = section(page, "who")
    assert '<div class="sleeve-wrap"><svg viewBox="0 0 1000 1000"' in who
    assert 'id="hero-sleeve-title"' in who  # the inline sleeve, its ids prefixed
    assert re.search(r'<h2 class="handle" style="font-size:min\(\d+px, calc\(100cqi / [\d.]+\)\)">DJ Test</h2>', who)
    assert f'<p class="lead">{identity["archetype"]["name"]}</p>' in who
    assert "Depth 94 and Breadth 81 carry it." in who and '<div class="liner">' in who
    assert who.index('class="handle"') < who.index('class="sleeve"')  # heading first, sleeve placed left by CSS
    # the liner notes say what the archetype means: the meaning line makes way, the name shows once
    text = who[who.index('<div class="hero-text">'):who.index('<figure class="sleeve">')]
    assert '<p class="meaning">' not in who and text.count(identity["archetype"]["name"]) == 1
    # the sleeve in the hero leaves out its small print (the tempo dial, the lane detail lines)
    art = re.search(r'<div class="sleeve-wrap">(<svg viewBox="0 0 1000 1000".*?</svg>)', who, re.DOTALL).group(1)
    assert all(float(size) >= 16 for size in re.findall(r'font-size="([\d.]+)"', art))
    assert ">7 tracks · funk &amp; disco 78-92</text>" not in art and ">100-109 BPM</text>" in art
    # wide: the words column holds the five stats after the liner notes, the art column the
    # sleeve and then the six axes (W-31 review: the stats on the first screen)
    main, art = who.index('<div class="hero-main">'), who.index('<div class="hero-art">')
    assert main < who.index('<div class="liner">') < who.index('<div class="stats-row">') < art
    assert art < who.index('<figure class="sleeve">') < who.index('<figure class="chart card axes-card">')


def test_the_hero_shows_the_six_axes_with_the_top_two_in_ink(page, identity):
    axes = svg_of(page, "axes chart")
    for axis in identity["order"]:
        score = identity["axes"][axis]["score"]
        assert f'data-tip="{score} · {identity["axes"][axis]["name"]} · ' in axes
    assert axes.count('class="mark emph"') == 2 and axes.count('class="mark rest"') == 4
    assert len(re.findall(r'class="t-value"', axes)) <= 4  # direct labels on at most 4 marks


def test_every_sleeve_cell_has_a_tooltip(page, identity):
    hits = re.search(r'<svg class="hits" viewBox="0 0 1000 1000".*?</svg>', page, re.DOTALL).group(0)
    rings, bands = len(identity["fingerprint"]["rings"]), len(identity["fingerprint"]["bands"])
    assert hits.count('data-kind="cell"') == rings * bands
    assert 'data-tip="4 tracks · 1990s · 118-122 BPM · lane 119-122"' in hits


# -- the toggle and the tokens (R-408) --------------------------------------------------------------


def test_booth_is_the_default_and_the_toggle_switches_and_remembers(page):
    assert '<html lang="en" data-theme="dark">' in page
    assert '<button type="button" data-set-theme="dark" aria-pressed="true">Booth</button>' in page
    assert '<button type="button" data-set-theme="light" aria-pressed="false">Day</button>' in page
    script = re.search(r"<script>(.*?)</script>", page, re.DOTALL).group(1)
    assert 'try { localStorage.setItem(KEY, theme); }' in script and "try { stored = localStorage.getItem(KEY); }" in script
    assert 'hash === "day"' in script and 'hash === "booth"' in script  # the URL hash wins


def test_tokens_for_both_themes_exactly_from_the_design_system(page):
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL).group(1)
    light, dark_media, dark_toggle = re.findall(r"\{(color-scheme:[a-z]+;[^{}]*)\}", style)[:3]
    for block, mode in ((light, "light"), (dark_media, "dark"), (dark_toggle, "dark")):
        for i, hexa in enumerate(design.CATEGORICAL[mode], 1):
            assert f"--c{i}:{hexa}" in block, (mode, i)
        for name, table in (("surface", design.SURFACE), ("page", design.PAGE), ("text", design.TEXT),
                            ("text-2", design.TEXT_2), ("grid", design.GRID), ("other", design.OTHER)):  # fmt: skip
            assert f"--{name}:{table[mode]}" in block, (mode, name)
    assert '@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;' in style
    assert ':root[data-theme="dark"]{color-scheme:dark;' in style
    assert "body{margin:0;background:var(--page)" in style  # an explicit background


def test_marks_never_carry_a_raw_colour_and_text_wears_text_tokens(page):
    body = page.split("</style>", 1)[1]
    sleeves = re.findall(r'<div class="sleeve-wrap">.*?</div>', body, re.DOTALL)
    rest = body
    for art in sleeves:  # the sleeve is the one object with its own finish (docs/design.md)
        rest = rest.replace(art, "")
    assert not re.search(r"#[0-9a-fA-F]{6}\b", rest)
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL).group(1)
    for rule in re.findall(r"\.t-[a-z]+(?:\.[a-z]+)?\{([^}]*)\}", style):
        fill = re.search(r"fill:([^;]+)", rule)
        assert not fill or fill.group(1) in ("var(--text)", "var(--text-2)", "var(--muted)"), rule


# -- the page is one file, no URL, no library (R-401) ------------------------------------------------


def test_no_http_anywhere(page):
    assert "http" not in page.lower()  # not even the SVG namespace: inline SVG in HTML needs none
    assert "xmlns" not in page


def test_one_inline_script_under_200_lines(page):
    scripts = re.findall(r"<script([^>]*)>(.*?)</script>", page, re.DOTALL)
    assert len(scripts) == 1 and scripts[0][0] == ""
    lines = [line for line in scripts[0][1].strip().split("\n") if line.strip()]
    assert len(lines) <= report.SCRIPT_LINES_MAX


def test_svg_ids_are_unique_and_every_reference_resolves(page):
    ids = [a["id"] for _tag, a in tags(page).tags if "id" in a]
    assert ids and [i for i, n in Counter(ids).items() if n > 1] == []
    for ref in re.findall(r"url\(#([^)]+)\)", page):
        assert ref in ids, ref
    for refs in re.findall(r'aria-labelledby="([^"]+)"', page):
        assert all(r in ids for r in refs.split()), refs


def test_four_sections_in_order_and_next_is_a_sticky_footer(page):
    positions = [page.index(f'<section id="{s}">') for s in ("who", "structure", "proposals", "next")]
    assert positions == sorted(positions)
    assert page.rstrip().endswith("</html>") and page.index('<section id="next">') > page.index('class="colophon"')
    assert "#next{position:sticky;bottom:0" in page
    # a band the width of the window, after <main>; its content as wide as the page (W-31 review)
    assert page.index("</main>") < page.index('<section id="next">\n<div class="next-in">')
    assert ".next-in{max-width:1100px;margin:0 auto;padding:14px 32px;display:flex" in page
    assert ':root:not([data-theme="dark"]) #next{box-shadow:' in page  # Day: the bar lifts off the page
    nxt = section(page, "next")
    assert '<p class="action"><span class="long">Pick one: say </span><q>Build me the House Bases structure</q>' in nxt
    assert '<button type="button" class="copy" data-copy="trigger-1">Copy</button>' in nxt


# -- the crate wall (R-403) -------------------------------------------------------------------------


def test_the_crate_wall_has_one_row_per_top_level_folder(page, lib):
    graph = json.loads((lib / "structure" / "graph.json").read_text(encoding="utf-8"))
    folders = [n["name"] for n in graph["nodes"] if n["depth"] == 1 and n["kind"] == "folder"]
    loose = [n for n in graph["nodes"] if n["depth"] == 1 and n["kind"] != "folder"]
    for cls in ("wall chart wall-wide", "wall chart wall-narrow"):  # one layout per width
        wall = svg_of(page, cls)
        assert wall.count('data-row="folder"') == len(folders) == 2
        assert wall.count('data-row="loose"') == (1 if loose else 0)
        for name in folders:
            assert f">{name}</text>" in wall or f">{name}<tspan" in wall


def test_dumps_are_hatched_and_empty_playlists_are_outlines(page):
    wall = svg_of(page, "wall chart wall-wide")
    assert '<pattern id="cw-hatch" patternUnits="userSpaceOnUse"' in wall
    dump = re.search(r'<g class="hit" tabindex="0" data-kind="dump" data-tip="([^"]+)">(.*?)</g>', wall)
    assert dump and dump.group(1) == "16 tracks · unsorted dump · a dump: 67% of the collection"
    assert 'fill="url(#cw-hatch)"' in dump.group(2)
    empty = re.search(r'data-kind="empty" data-tip="0 tracks · House/Deep/empty_ideas · empty">(<rect class="mark outline)', wall)
    assert empty
    assert '<g class="status warning"><circle class="ring"' in wall and ">dump · unsorted dump</text>" in wall


def test_the_overlap_is_an_arc_between_the_two_playlists(page):
    wall = svg_of(page, "wall chart wall-wide")
    arcs = re.findall(r'data-kind="arc" data-tip="([^"]+)"><path class="arc" d="M[\d.]+ [\d.]+C', wall)
    assert arcs == ["5 tracks shared · House/1.2_peak + Gigs/Gig 2025-03 Warehouse · 56% overlap"]
    assert wall.count('class="arc-end"') == 2 and ">5 shared</text>" in wall
    assert ">1.2_peak</text>" in wall and ">Gig 2025-03 Warehouse</text>" in wall  # both names on the wall


def test_wall_bars_wear_the_folder_lane_and_the_legend_names_the_lanes(page, identity):
    wall = svg_of(page, "wall chart wall-wide")
    slots = {lane["label"]: lane["slot"] for lane in identity["lanes"]}
    house = re.search(r'data-row="folder">(.*?)</g>\s*<g class="row" data-row="folder">', wall, re.DOTALL).group(1)
    assert set(re.findall(r'class="mark lane (s\d)"', house)) == {f"s{slots['119-122']}"}  # 8 of its 14 tracks
    assert len(re.findall(r'<text class="t-label[ "]', wall)) <= report_charts.MAX_LABELS  # arc labels count
    legend = re.search(r'<div class="legend".*?</div>', page, re.DOTALL).group(0)
    for label, slot in slots.items():
        assert f'<span class="sw s{slot}"></span>{label} BPM' in legend
    assert "dump</span>" in legend or "</span>dump</span>" in legend


def test_every_bar_and_arc_has_a_tooltip_and_a_hit_area_bigger_than_the_mark(page):
    wall = svg_of(page, "wall chart wall-wide")
    marks = re.findall(r'<g class="hit[^"]*" tabindex="0" data-kind="(\w+)" data-tip="[^"]+">(.*?)</g>', wall)
    assert len(marks) == 8 + 1  # 8 playlists and 1 arc
    for kind, inner in marks:
        assert 'class="hit-area"' in inner or 'class="hit-line"' in inner, kind
    for height in re.findall(r'class="hit-area" x="[\d.]+" y="[\d.]+" width="[\d.]+" height="([\d.]+)"', wall):
        assert float(height) >= 24 > report_charts.STRIP


def test_every_chart_has_a_table_link_to_its_file(page):
    links = re.findall(r'<a class="table-link" href="([^"]+)">table</a>', page)
    assert set(links) == {"../profile/identity.json", "../profile/stats.md", "../structure/graph.json",
                          "../structure/proposals.yaml"}  # fmt: skip  # graph.json: every playlist's tracks
    assert links.count("../structure/proposals.yaml") == 3  # one per card


# -- the proposal cards (R-404) ---------------------------------------------------------------------


def test_three_cards_each_with_a_mini_sleeve_recoloured_by_its_proposal(page, lib, identity):
    proposals = section(page, "proposals")
    cards = re.findall(r'<article class="proposal card.*?</article>', proposals, re.DOTALL)
    assert len(cards) == 3 and '<div class="cards cards-3">' in proposals
    entries = P.load(lib / "structure" / "proposals.yaml")
    for n, (card, entry) in enumerate(zip(cards, entries), 1):
        assert f'id="p{n}-mini-title"' in card and '<svg class="hits"' in card
        slots, branches = report_charts.proposal_colours(list(entry["tree"].nodes), identity,
                                                         json.loads((lib / "taste" / "facts.json").read_text("utf-8")))  # fmt: skip
        lane_slots = {lane["slot"] for lane in identity["lanes"]}
        kept = [b.slot for b in branches if b.slot is not None]
        assert set(kept) <= lane_slots and len(kept) == len(set(kept))  # a lane's slot, never shared
        assert set(slots.values()) <= lane_slots | {None}
        for b in branches[:5]:
            swatch = f"sw s{b.slot or 0}" if b.bands else "sw outline"  # a filled swatch keys a band
            assert f'<span class="{swatch}"></span><span class="branch"><strong>{b.name}' in card
        assert f'<pre class="trigger">{entry["trigger"]}</pre>' in card and 'class="copy" data-copy=' in card
        assert 'class="mini-note"' not in card  # said once for the section, not on every card
    assert proposals.count('<p class="mini-note">') == 1
    minis = re.findall(r'<div class="mini"><div class="sleeve-wrap">(<svg .*?</svg>)', proposals, re.DOTALL)
    assert len(set(re.sub(r'id="p\d-|"p\d-', "", m) for m in minis)) >= 2  # proposals that split lanes differently


def test_the_first_card_keeps_every_lane_on_its_own_slot(page, lib, identity):
    """House Bases puts each lane in its own base: each base wears its lane's slot, so a band has
    the colour it has on the hero sleeve and in the crate wall legend; bases no lane fills get a
    hollow swatch; the band no copied playlist reaches stays grey."""
    entry = P.load(lib / "structure" / "proposals.yaml")[0]
    taste = json.loads((lib / "taste" / "facts.json").read_text("utf-8"))
    slots, branches = report_charts.proposal_colours(list(entry["tree"].nodes), identity, taste)
    assert [(b.name, b.slot, b.lane) for b in branches] == [
        ("house_base", 3, "122-127"), ("techno_base", None, None), ("deep_house_base", 2, "119-122"),
        ("disco_base", None, None), ("funk_base", 1, "100-109")]  # fmt: skip
    hero = {band["band"]: band["slot"] for band in identity["fingerprint"]["bands"]}
    for band, slot in slots.items():
        if hero[band] is not None and slot is not None:
            assert slot == hero[band], band  # the same colour for the same lane as the hero sleeve
    assert slots["128-135"] is None
    card = re.findall(r'<article class="proposal card.*?</article>', section(page, "proposals"), re.DOTALL)[0]
    assert '<span class="sw outline"></span><span class="branch"><strong>techno_base/' in card
    assert 'data-tip="5 tracks · 128-135 BPM · none of the copied playlists reach it"' in card


def test_proposal_colours_follow_the_copied_playlists():
    """House Bases on the fixture: the 122-127 lane (1.2_peak, Gig 2025-03 Warehouse) lands in
    house_base, the 119-122 lane (1.1_warm_up, deep_rollers) in deep_house_base; a band no copied
    playlist reaches stays grey."""
    from dj.treeschema import TreeNode

    nodes = [
        TreeNode("folder", "house_base", children=(TreeNode("playlist", "peak", fill_from=("House/1.2_peak",)),)),
        TreeNode("folder", "techno_base"),
        TreeNode("folder", "deep_house_base", children=(TreeNode("playlist", "warm", fill_from=("House/1.1_warm_up",)),)),
    ]
    identity = {"fingerprint": {"bands": [{"band": "118-122", "lo": 118, "hi": 122}, {"band": "122-125", "lo": 122, "hi": 125},
                                          {"band": "135+", "lo": 135, "hi": None}]}}  # fmt: skip
    taste = {"bpm_playlists": [{"path": "House/1.2_peak", "tracks": 6, "lo": 122, "hi": 124},
                               {"path": "House/1.1_warm_up", "tracks": 4, "lo": 119, "hi": 121}]}  # fmt: skip
    identity["lanes"] = [
        {"label": "119-122", "lo": 119, "hi": 122, "slot": 2, "tracks": 4, "playlists": ["House/1.1_warm_up"]},
        {"label": "122-127", "lo": 122, "hi": 127, "slot": 3, "tracks": 6, "playlists": ["House/1.2_peak"]},
    ]
    slots, branches = report_charts.proposal_colours(nodes, identity, taste)
    assert slots == {"118-122": 2, "122-125": 3, "135+": None}  # each band keeps its lane's colour
    assert [(b.name, b.slot, b.bands) for b in branches] == [
        ("house_base", 3, ["122-125"]), ("techno_base", None, []), ("deep_house_base", 2, ["118-122"])]  # fmt: skip
    # two branches fed by one lane: the one that takes more of it keeps the slot, the other is grey
    both = [TreeNode("folder", "a", children=(TreeNode("playlist", "p", fill_from=("House/1.2_peak",)),)),
            TreeNode("folder", "b", children=(TreeNode("playlist", "p", fill_from=("House/1.2_peak", "House/1.1_warm_up")),))]  # fmt: skip
    _slots, branches = report_charts.proposal_colours(both, identity, taste)
    assert [(b.name, b.slot) for b in branches] == [("a", 3), ("b", None)]  # b: 6 of lane 3 against 4 of lane 2 ...
    assert [b.slot for b in report_charts.proposal_colours(both[::-1], identity, taste)[1]] == [3, None]
    assert report_charts.band_ranges(["<100", "100-110", "118-122", "122-125", "135+"]) == \
        "under 110, 118-125, 135 and up BPM"  # fmt: skip


def test_every_list_has_five_items_or_fewer_on_a_big_library(tmp_path):
    spec = fx.spec_copy()
    for i in range(7):  # 7 more top-level folders, each with 6 playlists: lists and rows get capped
        spec["tree"].append(fx._folder(f"Crate {i}", [fx._pl(f"c{i}_{j}", [1 + j, 2 + j]) for j in range(6)]))
    root = make_library(tmp_path / "dj-library", spec)
    page = (root / run_all.analyze(root, today=DAY)["report"]).read_text(encoding="utf-8")
    parsed = tags(page)
    assert parsed.sizes and max(parsed.sizes) <= 5
    wall = svg_of(page, "wall chart wall-wide")
    assert wall.count('data-row="folder"') == 9 and "http" not in page.lower()


# -- what is missing, what does not read, what is hostile ------------------------------------------


def test_renders_without_identity_json_or_identity_md(tmp_path):
    root = make_library(tmp_path / "dj-library")
    run_all.analyze(root, today=DAY)
    (root / "profile" / "identity.json").unlink()
    page = report.render(root, today=DAY).read_text(encoding="utf-8")
    who = section(page, "who")
    assert '<h2 class="handle"' in who and ">DJ Test</h2>" in who  # the handle from library.yaml
    assert "No sleeve yet: dj-identity has not run. Say \u201cdraw my sleeve\u201d and I run it" in who
    assert "No liner notes yet" not in who and who.count("dj-identity") == 1  # one line, not three
    assert '<div class="sleeve-empty"><p>No sleeve yet.</p></div>' in who and '<svg class="axes' not in who
    assert page.count('<article class="proposal') == 3 and '<div class="mini">' not in page
    assert 'class="wall chart wall-wide"' in page  # one colour, no lanes, still drawn
    assert "http" not in page.lower()


def test_a_broken_identity_json_is_left_out_and_named(tmp_path):
    root = make_library(tmp_path / "dj-library", dj_name=None)
    run_all.analyze(root, today=DAY)
    path = root / "profile" / "identity.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["axes"]["depth"]["score"] = "high"
    path.write_text(json.dumps(data), encoding="utf-8")
    page = report.render(root, today=DAY).read_text(encoding="utf-8")
    who = section(page, "who")
    assert ">You</h2>" in who  # no dj_name: "You"
    assert "No sleeve: profile/identity.json does not read as dj-identity writes it. Say \u201cdraw my sleeve\u201d" in who
    assert "Left out, does not read: profile/identity.json." in page


def test_a_hostile_handle_and_playlist_name_are_escaped(tmp_path):
    hostile = '<b onmouseover="x">http://evil</b>'
    spec = fx.spec_copy()
    spec["tree"].insert(0, fx._folder("<i>Crates & co</i>", [fx._pl('peak "x" <script>', [1, 3, 9])]))
    root = make_library(tmp_path / "dj-library", spec, dj_name=hostile)
    page = (root / run_all.analyze(root, today=DAY)["report"]).read_text(encoding="utf-8")
    low = page.lower()
    assert "http" not in low and low.count("<script") == 1 and "<b onmouseover" not in low and "<i>crates" not in low
    assert "&lt;b onmouseover=&quot;x&quot;&gt;&#104;ttp:&#47;&#47;evil&lt;/b&gt;</h2>" in page
    assert "&lt;i&gt;Crates &amp; co&lt;/i&gt;" in svg_of(page, "wall chart wall-wide")
    assert 'peak &quot;x&quot; &lt;script&gt;' in page


def test_phone_and_print_layouts(page):
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL).group(1)
    phone = re.search(r"@media \(max-width:600px\)\{(.*?)\n\}", style, re.DOTALL).group(1)
    assert ".top,main{padding-left:16px;padding-right:16px}" in phone
    assert "svg.wall-wide{display:none}svg.wall-narrow{display:block}" in phone
    assert "svg.chart{display:block;width:100%;height:auto" in style  # every chart scales with its viewBox
    printed = style[style.rindex("@media print{"):]  # the layout block (the first one holds the Day tokens)
    assert "#next{position:static" in printed and ".toggle,button.copy,#tip,.hits{display:none}" in printed
    assert re.search(r'@media print\{:root,:root\[data-theme\]\{color-scheme:light;--surface:#fcfcfb', style)
    assert "@media (max-width:959px){\n.cards-3,.cards-2{grid-template-columns:minmax(0,1fr)}" in style
    # a phone: the sticky next action is one row (the trigger on up to two lines, the copy button)
    assert "#next .long,#next .after{display:none}" in phone and ".next-in{flex-wrap:nowrap;gap:10px}" in phone
    assert "-webkit-line-clamp:2" in phone and "ellipsis" not in phone


def test_the_sleeve_hover_cells_sit_exactly_on_the_drawn_cells(identity):
    """The hover layer mirrors dj.sleeve's disc: the same ring radii, ring by ring."""
    from dj import sleeve

    art = sleeve.sleeve_svg(identity, inline=True, uid="t-")
    drawn = sorted({(float(r0), float(r1)) for r1, r0 in re.findall(
        r'<path d="M[\d.]+ [\d.]+A([\d.]+) [\d.]+ 0 [01] 1 [\d.]+ [\d.]+L[\d.]+ [\d.]+A([\d.]+) ', art)})  # fmt: skip
    _names, bounds, _counts = report_charts._ring_bounds(identity)
    assert drawn == [(round(r0, 1), round(r1, 1)) for r0, r1 in bounds]


# -- W-31 review: colour meaning, phone wall, hit areas, names, colophon, empty states ---------------


def test_the_wall_legend_and_tooltips_say_the_row_colour_is_the_folder_lane(page):
    """Every bar of a folder row wears the folder's main lane: the legend says so, and a bar whose
    own lane differs names both (House/1.2_peak sits in the 122-127 lane in an 119-122 row)."""
    legend = re.search(r'<div class="legend".*?</div>', page, re.DOTALL).group(0)
    assert legend.index('<span class="legend-head">Row colour = the folder&#x27;s main BPM lane') < legend.index('class="sw s1"')
    wall = svg_of(page, "wall chart wall-wide")
    assert 'data-tip="6 tracks · House/1.2_peak · lane 122-127 BPM (row colour: House, 119-122 BPM)"' in wall
    assert 'data-tip="6 tracks · Gigs/Gig 2025-11 Rooftop · no lane (row colour: Gigs, 122-127 BPM)"' in wall
    assert 'data-tip="4 tracks · House/1.1_warm_up · lane 119-122 BPM"' in wall  # its own lane: said once
    sub = re.search(r'<p class="chart-sub">(.*?)</p>', page).group(1)
    assert "takes the colour of the folder’s main BPM lane" in sub and "counts in both bars" in sub
    assert ">tracks, playlists end to end</text>" in wall  # the ticks count along the whole row


def _text_boxes(svg: str) -> list[tuple[str, str, tuple[float, float, float, float]]]:
    """(class, text, box) of every text in an SVG of the wall, widths as report_charts estimates."""
    sizes = {"t-name": (13, True), "t-sub": (11, False), "t-label": (11, False), "t-tick": (11, False)}
    out = []
    for cls, x, y, anchor, body in re.findall(
            r'<text class="([a-z- ]+)" x="([\d.]+)" y="([\d.]+)"(?: text-anchor="(\w+)")?>(.*?)</text>', svg):
        kind = cls.split()[0]
        if kind not in sizes:
            continue
        text = html.unescape(body)
        size, bold = sizes[kind]
        w = report_charts.width_of(text, size, bold or "t-arc" in cls)
        x0 = float(x) - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
        out.append((kind, text, (x0, float(y) - size * 0.75, x0 + w, float(y) + size * 0.2)))
    return out


def _arc_points(svg: str) -> list[tuple[float, float]]:
    points = []
    for d in re.findall(r'<path class="arc" d="([^"]+)"', svg):
        nums = [float(n) for n in re.findall(r"-?[\d.]+", d)]
        start, rest = (nums[0], nums[1]), nums[2:]
        for i in range(0, len(rest), 6):
            c1, c2, end = (rest[i], rest[i + 1]), (rest[i + 2], rest[i + 3]), (rest[i + 4], rest[i + 5])
            for k in range(21):
                t = k / 20
                u = 1 - t
                points.append(tuple(u**3 * start[j] + 3 * u * u * t * c1[j] + 3 * u * t * t * c2[j] + t**3 * end[j]
                                    for j in (0, 1)))  # fmt: skip
            start = end
    return points


@pytest.mark.parametrize("cls", ["wall chart wall-narrow", "wall chart wall-wide"])
def test_the_wall_keeps_its_text_apart_and_its_arc_off_the_names(page, cls):
    """The phone layout puts each row's name left and its counts right on the line above the row;
    an arc that crosses that line passes between them, and no two texts touch (W-31 review)."""
    wall = svg_of(page, cls)
    boxes = _text_boxes(wall)
    for i, (_k1, t1, a) in enumerate(boxes):
        for _k2, t2, b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (t1, t2)
    names = [box for kind, _t, box in boxes if kind in ("t-name", "t-sub")]
    points = _arc_points(wall)
    assert points
    for x, y in points:
        assert not any(x0 < x < x1 and y0 < y < y1 for x0, y0, x1, y1 in names), (x, y)
    if "narrow" in cls:
        assert re.search(r'<text class="t-sub" x="330" y="[\d.]+" text-anchor="end">2 playlists · 12 tracks</text>', wall)


def test_hit_areas_are_24_wide_where_there_is_room_and_never_cover_a_neighbour(page):
    wall = svg_of(page, "wall chart wall-wide")
    empty = re.search(r'data-kind="empty"[^>]*>.*?class="hit-area" x="[\d.]+" y="[\d.]+" width="([\d.]+)"', wall)
    assert float(empty.group(1)) >= report_charts.HIT_MIN  # the outline of an empty playlist
    for chunk in wall.split('<g class="row"')[1:]:
        row = re.split(r'<g class="hit arc-hit"|<g class="names">', chunk)[0]
        spans = [(float(x), float(x) + float(w)) for x, w in re.findall(r'class="hit-area" x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', row)]
        spans.sort()
        assert all(a[1] <= b[0] + 0.11 for a, b in zip(spans, spans[1:])), spans


@pytest.mark.parametrize("name", ["Curl(ed) Up", "Bass src=dub", "@import edits"])
def test_a_name_that_looks_like_css_or_an_attribute_still_renders(tmp_path, name):
    """The URL check reads the page's HTML (tags, attribute names, CSS), never the library's text:
    a playlist (in a lane, so on the sleeve too) or a handle with these characters renders."""
    spec = fx.spec_copy()
    for node in spec["tree"]:
        if node.get("name") == "funk & disco 78-92":  # the one playlist of the slowest lane
            node["name"] = name
    root = make_library(tmp_path / "dj-library", spec, dj_name=f"DJ {name}")
    result = run_all.analyze(root, today=DAY)
    assert result["failed"] == [] and result["report"]
    page = (root / result["report"]).read_text(encoding="utf-8")
    assert html.escape(name) in page and "http" not in page.lower()


def test_the_colophon_names_only_the_files_this_render_read(tmp_path):
    root = make_library(tmp_path / "dj-library")
    run_all.analyze(root, today=DAY)
    (root / "profile" / "identity.json").unlink()
    page = report.render(root, today=DAY).read_text(encoding="utf-8")
    colophon = re.search(r'<footer class="colophon">(.*?)</footer>', page, re.DOTALL).group(1)
    assert "profile/identity.json" not in colophon and "Words about you" not in colophon  # no MD files either
    assert "Measured by code: dj.report from profile/facts.json, structure/facts.json" in colophon
    (root / "profile" / "habits.md").write_text(HABITS, encoding="utf-8")
    page = report.render(root, today=DAY).read_text(encoding="utf-8")
    assert "Words about you by Claude, from profile/habits.md.</p>" in page


def test_with_identity_but_no_liner_notes_the_meaning_stands_in(tmp_path, identity):
    root = make_library(tmp_path / "dj-library")
    run_all.analyze(root, today=DAY)
    who = section(report.render(root, today=DAY).read_text(encoding="utf-8"), "who")
    assert f'<p class="meaning">{identity["archetype"]["meaning"]}</p>' in who
    assert ("No liner notes yet. Say “write my liner notes” and I write profile/identity.md from your six "
            "axes (about 2 minutes).") in who  # fmt: skip
    assert "No words on how you work yet. Say “write my habits”" in who


def test_hover_cells_with_tracks_are_focusable_images_and_empty_ones_are_hidden(page):
    hits = re.search(r'<svg class="hits" viewBox="0 0 1000 1000"[^>]*>', page).group(0)
    assert "aria-hidden" not in hits and 'role="group"' in hits
    focusable = re.findall(r'<path class="hit cell" tabindex="0" role="img" aria-label="([^"]+)" data-kind="\w+" data-tip="([^"]+)"', page)
    assert focusable and all(label == tip for label, tip in focusable)
    assert not re.search(r'aria-hidden="true"[^>]*tabindex', page) and not re.search(r'tabindex="0"[^>]*aria-hidden', page)


def test_the_axes_are_drawn_about_as_wide_as_they_show(page):
    """A viewBox near the column's width keeps the 13 px labels near 13 px (W-31 review)."""
    axes = svg_of(page, "axes chart")
    width = float(re.search(r'viewBox="0 0 ([\d.]+) ', axes).group(1))
    assert width == report_charts.AXES_W <= 340 and ".axes-card svg.axes{max-width:340px}" in page


def test_the_hero_has_no_dead_gap_and_the_handle_is_sized_by_its_column(page):
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL).group(1)
    assert 'grid-template-areas:"art main";' in style and ".hero-art{grid-area:art;min-width:0;display:flex" in style
    narrow = re.search(r"@media \(max-width:959px\)\{(.*?)\n\}", style, re.DOTALL).group(1)
    assert 'grid-template-areas:"text text" "sleeve axes" "stats stats"' in narrow  # stacked as before
    assert ".hero-main,.hero-art{display:contents}" in narrow
    assert ".hero .stats{grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:repeat(6,auto)" in style
    assert ".hero-text{grid-area:text;min-width:0;padding-top:6px;container-type:inline-size}" in style
    assert ".narrative p{margin:0 0 10px;break-inside:avoid}" in style
    assert ".stat-value{display:block;font-size:28px" in style  # docs/design.md, Typography


# -- W-31 second visual review ------------------------------------------------------------------------


def test_the_wall_labels_count_the_arc_and_the_legend_keys_only_drawn_marks(page):
    """At most 4 direct labels with the arc's "5 shared" among them; the solid grey "no lane" key
    only when a solid grey bar is drawn (the fixture's one grey bar is the hatched dump)."""
    wall = svg_of(page, "wall chart wall-wide")
    assert len(re.findall(r'<text class="t-label t-arc"', wall)) == 1
    labels = re.findall(r'<text class="t-label" x="[\d.]+" y="[\d.]+">([^<]+)</text>', wall)
    assert labels == ["dump · unsorted dump", "1.2_peak", "Gig 2025-03 Warehouse"]
    assert ">funk &amp; disco 78-92</text>" not in wall  # in its tooltip instead
    legend = re.search(r'<div class="legend".*?</div>', page, re.DOTALL).group(0)
    assert "no lane" not in legend and '<span class="sw hatched"></span>dump' in legend


def test_the_proposal_cards_line_up_part_by_part(page):
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL).group(1)
    assert ".cards-3,.cards-2{grid-template-rows:repeat(6,auto)}" in style
    assert "grid-row:span 6;grid-template-rows:subgrid;row-gap:0" in style
    narrow = re.search(r"@media \(max-width:959px\)\{(.*?)\n\}", style, re.DOTALL).group(1)
    assert ".proposal{display:block;grid-row:auto}" in narrow  # one column: each card on its own
    assert ".cost{font-size:14px;margin:0;" in style  # no auto margin pooling space above the cost
    for card in re.findall(r'<article class="proposal card.*?</article>', section(page, "proposals"), re.DOTALL):
        parts = re.findall(r'<(?:div|p) (?:class="card-head[^"]*"|data-part="(\w+)")', card)
        assert parts == ["", "principle", "tree", "lands", "cost", "trigger"]  # the six rows of the subgrid


def test_a_branch_bpm_line_leads_with_the_lane_its_swatch_keys(page):
    """The swatch of house_base is the 122-127 lane's colour: its line says so before the bands, so
    the numbers match the sleeve and the crate wall legend; an outline is explained once."""
    card = re.findall(r'<article class="proposal card.*?</article>', section(page, "proposals"), re.DOTALL)[0]
    assert '<strong>house_base/</strong>' in card
    assert '<span class="bpm"><span>lane 122-127 BPM</span> · <span>bands 122-128</span></span>' in card
    assert '<span class="bpm"><span>lane 100-109 BPM</span> · <span>bands under 118</span></span>' in card
    grey = re.findall(r'<article class="proposal card.*?</article>', section(page, "proposals"), re.DOTALL)[1]
    assert '<span class="sw s0"></span><span class="branch"><strong>0_INBOX</strong>' in grey  # grey: no lane named
    assert '<span class="bpm"><span>bands 110-118 BPM</span></span>' in grey
    assert ".branches .bpm span{white-space:nowrap}" in page  # "118-125" never breaks at its hyphen
    note = re.search(r'<p class="mini-note">(.*?)</p>', page).group(1)
    assert "Outline: a branch no tempo band lands in, so it has no colour on the sleeve." in note


def test_axis_values_and_section_two_cards(page):
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL).group(1)
    assert ".names text,.labels text,.axes .t-value{paint-order:stroke;stroke:var(--surface)" in style
    assert ".built{display:grid;grid-template-columns:minmax(0,1.75fr) minmax(0,1fr);gap:20px;align-items:stretch}" in style
