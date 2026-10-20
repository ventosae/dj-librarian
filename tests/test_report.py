"""dj.report (W-17): the one-file HTML report (R-401 ... R-407), the CLI `dj library report` and
the skill script plugin/skills/dj-report/scripts/report.py.

One file, opens offline (no http(s)://, no script, no external stylesheet or font), the four
sections, exactly 5 stats, 2-3 proposals with all six parts, every list 5 items or fewer, every
library string escaped, renders without habits.md, a second render goes to -2, never over a file."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml
from reply_checks import report_sections, text_problems
from typer.testing import CliRunner

from dj import cli, libfolder, report
from dj.analysis import common, run_all
from dj.analysis import proposals as P

DAY = date(2026, 10, 20)
REPORT = "reports/2026-10-20-library.html"
REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugin" / "skills" / "dj-report" / "scripts" / "report.py"
SECTIONS = ("who", "structure", "proposals", "next")
PARTS = ["name", "principle", "tree", "lands", "cost", "trigger"]
HOSTILE = "<script>alert(\"x\")</script> & 'q' http://evil.example"
MARKUP = 'Peak <b>"time" & co\'s'
runner = CliRunner()

HABITS = """\
# Who you are as a DJ

> Words by Claude, from profile/stats.md and profile/facts.json.

You play funk and disco from the **1970s to the 2020s**, most of it from the 2010s (6 tracks).
House and techno carry your peak time.

You dig steadily: see [your log](https://example.invalid/log) for when.

- one
- two
- three
- four
- five
- six
"""


def make_library(root: Path, spec: dict | None = None) -> Path:
    libfolder.scaffold(root, device="mac", today=DAY)
    libfolder.import_export(root, fx.write_xml(root.parent / "collection.xml", spec), today=DAY)
    return root


@pytest.fixture(scope="module")
def analysed(tmp_path_factory) -> Path:
    """The fixture library after the whole chain (profile, structure, taste, report), no habits.md."""
    root = make_library(tmp_path_factory.mktemp("analysed") / "dj-library")
    result = run_all.analyze(root, today=DAY)
    assert result["failed"] == [] and result["report"] == REPORT
    return root


@pytest.fixture(scope="module")
def page(analysed) -> str:
    return (analysed / REPORT).read_text(encoding="utf-8")


@pytest.fixture
def folder(tmp_path) -> Path:
    """A fresh analysed copy each test may write into."""
    root = make_library(tmp_path / "dj-library")
    run_all.analyze(root, today=DAY)
    return root


class Lists(HTMLParser):
    """Direct <li> children of every <ul>/<ol>, and the elements carrying data-part per article."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[list] = []
        self.sizes: list[int] = []
        self.articles: list[list[str]] = []
        self.stats = 0
        self.actions = 0
        self.section = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section":
            self.section = a.get("id")
        if tag in ("ul", "ol"):
            self.stack.append([tag, 0])
        elif tag == "li" and self.stack:
            self.stack[-1][1] += 1
        if tag == "article":
            self.articles.append([])
        if "data-part" in a and self.articles:
            self.articles[-1].append(a["data-part"])
        if a.get("class") == "stat":
            self.stats += 1
        if a.get("class") == "action" and self.section == "next":
            self.actions += 1

    def handle_endtag(self, tag):
        if tag in ("ul", "ol") and self.stack:
            self.sizes.append(self.stack.pop()[1])


def parsed(text: str) -> Lists:
    lists = Lists()
    lists.feed(text)
    return lists


def section_html(text: str, name: str) -> str:
    m = re.search(rf'<section id="{name}">(.*?)</section>', text, re.DOTALL)
    assert m, name
    return m.group(1)


# -- one self-contained file (R-401) --------------------------------------------------------------


def test_one_file_in_reports(analysed):
    assert sorted(p.name for p in (analysed / "reports").iterdir()) == ["2026-10-20-library.html"]


def test_self_contained_no_external_request(page):
    """W-31: the page has its own inline script now (toggle, tooltips, copy), and the dump hatch
    is an SVG pattern referenced as url(#...). Nothing else may load or link anything."""
    low = page.lower()
    for banned in ("http", "<link", "@import", "<img", "<iframe", "src="):
        assert banned not in low, banned
    assert low.count("<script") == 1 and "<script>" in low  # the page's own, inline
    assert re.findall(r"url\(([^)]*)\)", low) and all(ref.startswith("#") for ref in re.findall(r"url\(([^)]*)\)", low))
    assert low.startswith("<!doctype html>") and '<meta charset="utf-8">' in low
    assert "<style>" in page and "<svg" in page


def test_light_and_dark(page):
    """W-31: the tokens of docs/design.md; dark declared twice (OS preference, toggle) and the
    light tokens again for print."""
    assert "@media (prefers-color-scheme:dark)" in page
    assert page.count("--surface:") == 4 and len(re.findall(r"[{;]color-scheme:dark", page)) == 2


def test_four_sections_in_order(page):
    positions = [page.index(f'<section id="{s}">') for s in SECTIONS]
    assert positions == sorted(positions)


def test_no_absolute_path_in_the_report(analysed, page):
    assert str(analysed) not in page and analysed.as_posix() not in page
    assert "D:/" not in page and "/Users/" not in page and "file://" not in page


# -- who you are (R-402) ----------------------------------------------------------------------------


def test_exactly_five_stats_from_the_profile(analysed, page):
    assert parsed(section_html(page, "who")).stats == 5
    facts = json.loads((analysed / "profile" / "facts.json").read_text(encoding="utf-8"))
    for stat in facts["headline"]:
        assert html.escape(stat["value"]) in page and html.escape(stat["label"]) in page


def test_without_habits_md_a_placeholder_says_where_the_words_come_from(page):
    who = section_html(page, "who")
    assert "No words on how you work yet. Say \u201cwrite my habits\u201d and I write profile/habits.md" in who


def test_with_habits_md_the_narrative_is_shown(folder):
    (folder / "profile" / "habits.md").write_text(HABITS, encoding="utf-8")
    text = report.render(folder, today=DAY).read_text(encoding="utf-8")
    who = section_html(text, "who")
    assert "Who you are as a DJ" not in who  # the title: the section has its own heading
    assert '<p class="prov">Words by Claude, from profile/stats.md and profile/facts.json.</p>' in who
    assert "<strong>1970s to the 2020s</strong>" in who
    assert "your log" in who and "example.invalid" not in text  # a link keeps its text only
    assert "<li>five</li>" in who and "<li>six</li>" not in who and "and 1 more in profile/habits.md" in who
    assert "No words on how you work yet" not in who


# -- how it's built (R-403) -------------------------------------------------------------------------


def test_the_crate_wall_comes_from_graph_json(analysed, page):
    """W-31: the tree drawing is the crate wall (was: a two-level tree, viewBox 360)."""
    graph = json.loads((analysed / "structure" / "graph.json").read_text(encoding="utf-8"))
    svg = re.search(r'<svg class="wall chart wall-wide".*?</svg>', page, re.DOTALL).group(0)
    assert "<title" in svg
    for node in graph["nodes"]:
        if node["depth"] == 1 and node["kind"] == "folder":
            assert f">{html.escape(node['name'])}</text>" in svg, node["name"]
        elif node["kind"] == "playlist":  # every playlist, at any depth, is a bar with a tooltip
            assert f" · {html.escape(node['path'])}" in svg, node["path"]
    assert "dump · unsorted dump" in svg and 'data-kind="dump"' in svg
    assert "xmlns" not in svg  # inline SVG in HTML needs no namespace URL


def test_overlap_bars_and_reveals(page):
    structure = section_html(page, "structure")
    assert 'data-tip="5 tracks shared · House/1.2_peak + Gigs/Gig 2025-03 Warehouse · 56% overlap"' in structure
    assert 'class="arc"' in structure  # W-31: an arc between the two bars (was: overlap bars)
    reveals = re.search(r'<ul class="reveals">(.*?)</ul>', structure, re.DOTALL).group(1)
    items = re.findall(r"<li>(.*?)</li>", reveals)
    assert 1 <= len(items) <= 5
    assert any("dump" in i for i in items) and any("duplicate" in i for i in items)
    assert any("no playlist" in i for i in items)  # orphans


def test_a_big_tree_is_capped():
    """W-31: the crate wall draws at most MAX_ROWS folders and names the rest in one line."""
    from dj import report_charts

    nodes = [{"id": f"F{i}", "path": f"F{i}", "name": f"F{i}", "kind": "folder", "tracks": 3, "depth": 1}
             for i in range(20)]  # fmt: skip
    nodes += [{"id": f"F0/p{j}", "path": f"F0/p{j}", "name": f"p{j}", "kind": "playlist", "tracks": j, "depth": 2}
              for j in range(7)]  # fmt: skip
    edges = [{"source": "F0", "target": f"F0/p{j}"} for j in range(7)]
    rows, more = report_charts.wall_rows({"nodes": nodes, "edges": edges}, None, None)
    assert len(rows) == report_charts.MAX_ROWS and more == 20 - report_charts.MAX_ROWS
    assert [b.name for b in rows[0].bars] == [f"p{j}" for j in range(7)]
    wall = report_charts.crate_wall({"nodes": nodes, "edges": edges}, None, None)
    assert f"+ {more} more folders: see structure/analysis.md" in wall.svg


# -- proposals (R-404) ------------------------------------------------------------------------------


def test_two_or_three_proposals_with_all_six_parts_in_order(page):
    articles = parsed(page).articles
    assert 2 <= len(articles) <= 3
    assert all(parts == PARTS for parts in articles)


def test_proposals_come_from_the_file(analysed, page):
    entries = P.load(analysed / "structure" / "proposals.yaml")
    proposals = section_html(page, "proposals")
    for entry in entries:
        assert f'<h3 data-part="name">{html.escape(entry["name"])}</h3>' in proposals
        assert f'<pre class="trigger">{html.escape(entry["trigger"])}</pre>' in proposals
        assert f"About {entry['cost_minutes']} minutes in rekordbox" in proposals
        assert html.escape(entry["principle"]) in proposals
    assert proposals.count("and 2 more in structure/proposals.yaml") == 3  # 7 lands, 5 shown


def test_a_renamed_proposal_shows_after_render(folder):
    path = folder / "structure" / "proposals.yaml"
    text = path.read_text(encoding="utf-8").replace("House Bases", "Telepathy Bases")
    path.write_text(text, encoding="utf-8")
    page = report.render(folder, today=DAY).read_text(encoding="utf-8")
    assert "Build me the Telepathy Bases structure" in page and "House Bases" not in page


def test_every_list_has_five_items_or_fewer(page):
    sizes = parsed(page).sizes
    assert sizes and max(sizes) <= 5


# -- next (R-406) and voice (R-407) -----------------------------------------------------------------


def test_exactly_one_next_action_under_two_minutes(page):
    nxt = section_html(page, "next")
    assert parsed(page).actions == 1
    assert 'Pick one: say </span><q>Build me the House Bases structure</q>' in nxt and "under 2 minutes" in nxt


def test_each_section_opens_with_its_point(page):
    for name in SECTIONS:
        body = section_html(page, name)
        after = body.split("</h2>", 1)[1].lstrip()
        assert after.startswith('<p class="lead">') or after.startswith('<p class="action">'), name


def test_section_texts_pass_the_checklist(page):
    texts = report_sections(page)
    assert list(texts) == list(SECTIONS)
    for name, text in texts.items():
        assert text_problems(text) == [], (name, text_problems(text))


# -- escaping ---------------------------------------------------------------------------------------


def test_a_hostile_playlist_name_is_escaped_everywhere(tmp_path):
    spec = fx.spec_copy()
    spec["tree"].insert(0, fx._pl(HOSTILE, [1, 3]))
    spec["tree"].insert(1, fx._pl(MARKUP, [9, 11, 12]))
    root = make_library(tmp_path / "dj-library", spec)
    result = run_all.analyze(root, today=DAY)
    page = (root / result["report"]).read_text(encoding="utf-8")
    assert HOSTILE not in page and page.lower().count("<script") == 1 and "http" not in page.lower()
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;&#x27;/script&gt;" not in page  # no double escaping
    # W-31: the "h" of "http" is a character reference too, so the page holds no "http" at all
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &#x27;q&#x27; &#104;ttp:&#47;&#47;evil.example" in page
    assert html.escape(MARKUP) in page and MARKUP not in page
    assert max(parsed(page).sizes) <= 5 and len(parsed(page).articles) in (2, 3)
    lands = [r for p in P.load(root / "structure" / "proposals.yaml") for r in p["lands"]]
    assert {"from": HOSTILE, "to": P.STAYS} in lands  # a "/" in the name: it cannot be named, it stays


def test_esc():
    assert report.esc('<a href="x">&\'</a>') == "&lt;a href=&quot;x&quot;&gt;&amp;&#x27;&lt;/a&gt;"
    assert report.esc("see https://x.y") == "see &#104;ttps:&#47;&#47;x.y"


# -- create only, and what is missing -----------------------------------------------------------------


def test_a_second_render_goes_to_dash_2_and_never_overwrites(folder):
    first = folder / REPORT
    before = first.read_bytes()
    second = report.render(folder, today=DAY)
    third = report.render(folder, today=DAY)
    assert (second.name, third.name) == ("2026-10-20-library-2.html", "2026-10-20-library-3.html")
    assert first.read_bytes() == before


def test_renders_with_what_there_is(tmp_path):
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="windows", today=DAY)
    page = report.render(root, today=DAY).read_text(encoding="utf-8")
    assert "No profile yet" in page and "No structure data yet" in page and "No proposals yet" in page
    assert "Say run the report again" in section_html(page, "next")
    assert parsed(page).actions == 1 and parsed(page).stats == 0


def test_a_broken_proposals_file_stops_the_render_and_writes_nothing(folder):
    path = folder / "structure" / "proposals.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("trigger: Build me the House", "trigger: Make the House"),
                    encoding="utf-8")  # fmt: skip
    before = sorted(p.name for p in (folder / "reports").iterdir())
    with pytest.raises(P.ProposalsError, match="proposal 1: trigger"):
        report.render(folder, today=DAY)
    assert sorted(p.name for p in (folder / "reports").iterdir()) == before


def test_one_proposal_or_an_empty_file_stops_the_render(folder):
    """R-404: 2 or 3 proposals. A cut-down or emptied file is an error, not 'missing'."""
    path = folder / "structure" / "proposals.yaml"
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    before = sorted(p.name for p in (folder / "reports").iterdir())
    path.write_text(yaml.safe_dump(entries[:1], sort_keys=False), encoding="utf-8")
    with pytest.raises(P.ProposalsError, match="1 proposals; the report shows 2 or 3"):
        report.render(folder, today=DAY)
    path.write_text("", encoding="utf-8")
    with pytest.raises(P.ProposalsError, match="0 proposals"):
        report.render(folder, today=DAY)
    assert sorted(p.name for p in (folder / "reports").iterdir()) == before


BAD_FACTS = [
    pytest.param("profile/facts.json", lambda d: d.update(headline=["x", 1]), "who", id="headline-not-mappings"),
    pytest.param("profile/facts.json", lambda d: d.update(duplicates=[1]), "who", id="duplicates-a-list"),
    pytest.param("structure/facts.json", lambda d: d["overlap"].update(top=[1]), "structure", id="overlap-top-ints"),
    pytest.param("structure/facts.json", lambda d: d["dumps"].update(top=[{"path": ["a"]}]), "structure",
                 id="dump-path-a-list"),
    pytest.param("structure/facts.json", lambda d: d["overlap"]["top"][0].update(shared="many"), "structure",
                 id="shared-not-a-number"),
]  # fmt: skip


@pytest.mark.parametrize(("name", "change", "section"), BAD_FACTS)
def test_a_facts_file_in_another_shape_is_left_out_not_a_crash(folder, name, change, section):
    path = folder / name
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    page = report.render(folder, today=DAY).read_text(encoding="utf-8")
    lead = section_html(page, section).split("</h2>", 1)[1]
    assert f"{name} does not read" in lead and "Run dj-" in lead
    assert f"Left out, does not read: {name}." in page
    assert len(parsed(page).articles) == 3  # the rest of the report is still there
    for text in report_sections(page).values():
        assert text_problems(text) == []


def test_broken_json_and_a_broken_graph_are_left_out(folder):
    (folder / "profile" / "facts.json").write_text("{not json", encoding="utf-8")
    graph = folder / "structure" / "graph.json"
    data = json.loads(graph.read_text(encoding="utf-8"))
    data["nodes"][0]["tracks"] = "lots"
    graph.write_text(json.dumps(data), encoding="utf-8")
    page = report.render(folder, today=DAY).read_text(encoding="utf-8")
    assert 'class="wall' not in page and parsed(page).stats == 0  # W-31: the hero sleeve still shows
    assert "Left out, does not read: profile/facts.json, structure/graph.json." in page
    done = run_script("render", "--library", str(folder), "--today", "2026-10-20", cwd=folder.parent)
    assert done.returncode == 0 and json.loads(done.stdout)["ok"] is True  # one JSON object, no traceback


def test_after_a_rename_render_only_and_the_newest_report_is_the_one_found(folder):
    """The rename flow of SKILL.md step 5: render only, the -2 file shows the new name, and
    dj-start (onboarding.folder_state) names that file, not the first of the day."""
    from dj import onboarding

    path = folder / "structure" / "proposals.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("House Bases", "Telepathy Bases"), encoding="utf-8")
    edited = path.read_bytes()
    done = runner.invoke(cli.app, ["library", "report", "--library", str(folder), "--today", "2026-10-20",
                                   "--render-only", "--json"])  # fmt: skip
    assert done.exit_code == 0, done.output
    data = json.loads(done.output)
    assert data["report"] == "reports/2026-10-20-library-2.html" and data["counts"] == {"proposals": 3, "files": 1}
    assert path.read_bytes() == edited and not list((folder / "structure").glob("proposals.edited-*"))
    page = (folder / data["report"]).read_text(encoding="utf-8")
    assert "Build me the Telepathy Bases structure" in page
    assert onboarding.folder_state(folder)["latest_report"] == data["report"]
    text = runner.invoke(cli.app, ["library", "report", "--library", str(folder), "--today", "2026-10-20",
                                   "--render-only"])  # fmt: skip
    assert text.exit_code == 0
    assert text.output.startswith("report: reports/2026-10-20-library-3.html (3 proposals from structure/proposals.yaml)")
    assert onboarding.folder_state(folder)["latest_report"] == "reports/2026-10-20-library-3.html"


def test_render_refuses_a_folder_that_is_not_a_library(tmp_path):
    with pytest.raises(common.NotALibraryFolder):
        report.render(tmp_path, today=DAY)
    assert list(tmp_path.iterdir()) == []


def test_markdown_lists_and_headings():
    out = report.markdown("## Sound\n\nA *warm* `set`.\n\n1. a\n2. b\n")
    assert "<h3>Sound</h3>" in out and "<em>warm</em>" in out and "<code>set</code>" in out
    assert "<ul><li>a</li><li>b</li></ul>" in out


# -- run_report, run_render, CLI, script ------------------------------------------------------------


def test_run_report_writes_proposals_and_report_and_one_log_line(tmp_path):
    root = make_library(tmp_path / "dj-library")
    result = report.run_report(root, today=DAY)
    assert list(result)[0] == "counts" and result["counts"] == {"proposals": 3, "files": 2}
    assert result["written"] == ["structure/proposals.yaml", REPORT] and result["report"] == REPORT
    assert result["log"] == f"2026-10-20 00:00 report -> 3 proposals, 2 files; {REPORT}"
    assert [p["family"] for p in result["proposals"]] == ["bases", "facets", "gig-first"]
    page = (root / REPORT).read_text(encoding="utf-8")
    assert "No profile yet" in page and len(parsed(page).articles) == 3  # the report needs only the export


def test_run_render_logs_one_line(folder):
    result = report.run_render(folder, today=DAY)
    assert result == {"counts": {"proposals": 3, "files": 1}, "report": "reports/2026-10-20-library-2.html",
                      "log": "2026-10-20 00:00 report -> 3 proposals, 1 files; reports/2026-10-20-library-2.html"}


def test_cli_report_json_and_text(tmp_path):
    root = make_library(tmp_path / "dj-library")
    done = runner.invoke(cli.app, ["library", "report", "--library", str(root), "--today", "2026-10-20", "--json"])
    assert done.exit_code == 0, done.output
    data = json.loads(done.output)
    assert data["report"] == REPORT and data["counts"]["proposals"] == 3
    text = runner.invoke(cli.app, ["library", "report", "--library", str(root), "--today", "2026-10-20"])
    assert text.exit_code == 0
    assert text.output.startswith("report: reports/2026-10-20-library-2.html (3 proposals from exports/")
    assert "Build me the House Bases structure (about 23 minutes, bases)" in text.output
    assert "Nothing was written to rekordbox." in text.output


def test_cli_report_refuses_a_plain_folder(tmp_path):
    done = runner.invoke(cli.app, ["library", "report", "--library", str(tmp_path)])
    assert done.exit_code == 2 and "REFUSED" in done.output
    assert list(tmp_path.iterdir()) == []


def run_script(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=env)  # fmt: skip


def test_script_propose_render_and_both(tmp_path):
    root = make_library(tmp_path / "dj-library")
    done = run_script("propose", "--library", str(root), "--today", "2026-10-20", cwd=tmp_path)
    out = json.loads(done.stdout)
    assert done.returncode == 0 and out["ok"] is True and out["written"] == ["structure/proposals.yaml"]
    assert not (root / "reports" / "2026-10-20-library.html").exists()
    done = run_script("render", "--library", str(root), "--today", "2026-10-20", cwd=tmp_path)
    assert done.returncode == 0 and json.loads(done.stdout)["report"] == REPORT
    done = run_script("--library", str(root), "--today", "2026-10-20", cwd=tmp_path)
    out = json.loads(done.stdout)
    assert done.returncode == 0 and out["report"] == "reports/2026-10-20-library-2.html"
    assert out["counts"] == {"proposals": 3, "files": 2}
    log = (root / "log.md").read_text(encoding="utf-8").splitlines()
    assert [line.split(" ", 3)[2] for line in log[-3:]] == ["proposals", "report", "report"]


def test_script_refuses_and_errors(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    done = run_script("--library", str(plain), cwd=tmp_path)
    assert done.returncode == 2 and "library.yaml" in json.loads(done.stdout)["refused"]
    assert list(plain.iterdir()) == []
    empty = tmp_path / "dj-library"
    libfolder.scaffold(empty, device="mac", today=DAY)
    done = run_script("--library", str(empty), cwd=tmp_path)  # scaffolded, no export yet
    assert done.returncode == 1 and "export" in json.loads(done.stdout)["error"].lower()
    done = run_script("--library", str(empty), "--today", "soon", cwd=tmp_path)
    assert done.returncode == 1 and json.loads(done.stdout)["ok"] is False
    done = run_script("draw", "--library", str(empty), cwd=tmp_path)
    assert done.returncode == 1 and json.loads(done.stdout)["error"].startswith("usage:")
    done = run_script(cwd=tmp_path)
    assert done.returncode == 1 and "--library" in json.loads(done.stdout)["error"]


def test_script_runs_without_engine_packages(tmp_path):
    root = make_library(tmp_path / "dj-library")
    code = textwrap.dedent(f"""
        import runpy, sys
        for name in ("pyrekordbox", "rapidfuzz", "httpx", "typer", "mcp"):
            sys.modules[name] = None
        sys.argv = ["report.py", "--library", {str(root)!r}, "--today", "2026-10-20"]
        runpy.run_path({str(SCRIPT)!r}, run_name="__main__")
    """)
    env = dict(os.environ, PYTHONUTF8="1")
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=env)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["report"] == REPORT


def test_the_script_is_thin():
    text = SCRIPT.read_text(encoding="utf-8")
    for logic in ("read_xml", "append_log", "write_text", "import yaml", "<section"):
        assert logic not in text, logic


def test_proposals_file_is_valid_yaml_for_the_build_step(analysed):
    """What dj-build (W-18) reads: valid slugs, exact triggers, every `from` a real playlist of the
    latest export, and a tree that, diffed against structure/current-tree.yaml, creates every
    node (no SKIP, no CONFLICT), so `lands` and the cost on the page are what the build does."""
    from dj import treeschema
    from dj.readers.xml import read_xml

    data = yaml.safe_load((analysed / "structure" / "proposals.yaml").read_text(encoding="utf-8"))
    assert all(re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", entry["slug"]) for entry in data)
    lib = read_xml(libfolder.latest_export(analysed))
    current = treeschema.load(analysed / "structure" / "current-tree.yaml")
    for entry in P.load(analysed / "structure" / "proposals.yaml"):
        assert entry["trigger"] == f"Build me the {entry['name']} structure"
        rows = treeschema.diff(entry["tree"], current)
        assert {r.op for r in rows} == {treeschema.CREATE}, (entry["slug"], [r for r in rows if r.op != "CREATE"])
        assert all(lib.tracks_in(s) for _path, node in treeschema.walk(entry["tree"]) for s in node.fill_from)


def test_the_url_check_reads_the_page_not_the_library_text():
    """W-31 review: a name like "Curl(ed) Up" in text or a data-tip never stops a report; a tag,
    attribute, link or CSS rule that would load something always does."""
    head = "<!doctype html><html><head><style>.x{fill:url(#h)}</style><script>var a = 1;</script></head><body>"
    report._check(head + '<p data-tip="Curl(ed) Up · Bass src=dub · @import edits">Curl(ed) Up src=dub @import x</p>'
                  '<svg><path fill="url(#h)"/></svg><a href="../profile/stats.md">table</a></body></html>')
    bad = {
        "<img>": '<img alt="x">',
        "a src attribute": '<audio src="x"></audio>',
        "@import": "<style>@import 'x.css';</style>",
        "url() to anything but the page itself": '<p style="background:url(x.png)">',
        "a link out of the library folder": '<a href="javascript:x">x</a>',
        "an onclick handler": '<p onclick="x">',
        "a script other than the page's own": "<script>var b = 2;</script>",
        "http": "<p>http</p>",
    }
    for problem, markup in bad.items():
        with pytest.raises(report.ReportError, match=re.escape(problem)):
            report._check(head + markup + "</body></html>")
