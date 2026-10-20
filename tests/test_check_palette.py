"""scripts/check_palette.py and docs/design.md (R-408, W-31).

The checker reads the one token block of docs/design.md, converts each hex to OKLab, and checks
the adjacent categorical pairs under normal vision (FAIL < 15) and simulated protan / deutan
(Machado 2009, severity 1.0; FAIL < 8), tritan (WARN < 8), contrast against the surface (WARN
< 3:1), the OKLCH lightness band and the chroma floor (FAIL). dj.design holds the same values for
code.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from dj import design

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_palette.py"
DESIGN = REPO / "docs" / "design.md"


@pytest.fixture(scope="module")
def cp():
    spec = importlib.util.spec_from_file_location("check_palette", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_palette"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report(cp):
    return cp.check_file(DESIGN)


def _tokens(cp) -> dict:
    return cp.parse_tokens(cp.token_block(DESIGN.read_text(encoding="utf-8")))


def _status(report, mode: str, check: str) -> dict:
    return next(r for r in report["modes"][mode]["results"] if r["check"] == check)


def _bad_block(tokens: dict) -> str:
    """A design.md-like text holding `tokens` as its token block."""
    lines = ["tokens:", f"  names: [{', '.join(tokens['names'])}]"]
    for mode in ("light", "dark"):
        block = tokens[mode]
        lines.append(f"  {mode}:")
        for key in ("surface", "text", "text_secondary"):
            lines.append(f'    {key}: "{block[key]}"')
        for key in ("categorical", "sequential"):
            lines.append(f"    {key}: [" + ", ".join(f'"{h}"' for h in block[key]) + "]")
        lines.append("    status:")
        for key, value in block["status"].items():
            lines.append(f'      {key}: "{value}"')
    return "# Design\n\n```yaml\n" + "\n".join(lines) + "\n```\n"


# -- the documented palette -------------------------------------------------------------------


def test_the_documented_palette_passes(report):
    assert report["fails"] == 0, [r for m in report["modes"].values() for r in m["results"] if r["status"] == "FAIL"]


def test_worst_adjacent_values_match_the_documented_figures(report):
    expected = {"light": (19.6, 9.1), "dark": (19.3, 8.4)}  # docs/design.md, Validation
    for mode, (normal, cvd) in expected.items():
        worst = report["modes"][mode]["worst"]
        assert abs(worst["normal"]["normal"] - normal) <= 0.3, (mode, worst["normal"])
        gated = min(worst["protan"]["protan"], worst["deutan"]["deutan"])
        assert abs(gated - cvd) <= 0.3, (mode, gated)


def test_light_tritan_is_a_warn_on_yellow_and_magenta(report):
    worst = report["modes"]["light"]["worst"]["tritan"]
    assert worst["names"] == "yellow/magenta" and abs(worst["tritan"] - 5.8) <= 0.3
    result = _status(report, "light", "adjacent Delta E, tritan")
    assert result["status"] == "WARN" and "relief" in result["detail"]
    assert _status(report, "dark", "adjacent Delta E, tritan")["status"] == "PASS"  # about 8.7


def test_contrast_warn_names_the_slots_that_need_relief(report):
    assert report["modes"]["light"]["relief"] == ["aqua", "yellow", "magenta"]
    assert "direct labels or the table link" in _status(report, "light", "contrast vs surface")["detail"]
    assert report["modes"]["dark"]["relief"] == []


def test_band_and_chroma_pass_in_both_modes(report):
    for mode in ("light", "dark"):
        for check in ("lightness band", "chroma floor", "adjacent Delta E, normal", "adjacent Delta E, protan",
                      "adjacent Delta E, deutan", "text contrast", "sequential ramp"):  # fmt: skip
            assert _status(report, mode, check)["status"] == "PASS", (mode, check)


def test_the_script_runs_and_exits_0(tmp_path):
    done = subprocess.run([sys.executable, str(SCRIPT), str(DESIGN)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, cwd=tmp_path)  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASS: 0 FAIL" in done.stdout and "WARN" in done.stdout
    assert re.search(r"4-5\s+yellow/magenta", done.stdout)


# -- bad palettes FAIL -------------------------------------------------------------------------


def test_two_near_identical_slots_fail(cp, tmp_path):
    tokens = _tokens(cp)
    tokens["light"]["categorical"][1] = "#2b79d5"  # slot 2 a hair away from slot 1
    path = tmp_path / "design.md"
    path.write_text(_bad_block(tokens), encoding="utf-8")
    report = cp.check_file(path)
    assert report["fails"] >= 1
    assert _status(report, "light", "adjacent Delta E, normal")["status"] == "FAIL"
    assert cp.main([str(path)]) == 1


def test_a_grey_slot_under_the_chroma_floor_fails(cp, tmp_path, capsys):
    tokens = _tokens(cp)
    tokens["dark"]["categorical"][4] = "#8f8f8c"  # a grey: no hue left to tell it apart
    path = tmp_path / "design.md"
    path.write_text(_bad_block(tokens), encoding="utf-8")
    assert cp.main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL  chroma floor" in out and "magenta" in out


def test_a_slot_outside_the_lightness_band_fails(cp, tmp_path):
    tokens = _tokens(cp)
    tokens["light"]["categorical"][6] = "#ffe680"  # far too light for the light surface
    path = tmp_path / "design.md"
    path.write_text(_bad_block(tokens), encoding="utf-8")
    assert _status(cp.check_file(path), "light", "lightness band")["status"] == "FAIL"


def test_a_missing_or_doubled_token_block_fails(cp, tmp_path):
    none = tmp_path / "none.md"
    none.write_text("# nothing\n\n```yaml\nother: 1\n```\n", encoding="utf-8")
    assert cp.main([str(none)]) == 1
    text = DESIGN.read_text(encoding="utf-8")
    block = re.search(r"```yaml\ntokens:.*?```\n", text, re.DOTALL).group(0)
    twice = tmp_path / "twice.md"
    twice.write_text(text + "\n" + block, encoding="utf-8")
    with pytest.raises(cp.TokenError, match="2 token blocks"):
        cp.check_file(twice)
    broken = tmp_path / "broken.md"
    broken.write_text(_bad_block(_tokens(cp)).replace('"#fcfcfb"', '"#fcfcfz"'), encoding="utf-8")
    assert cp.main([str(broken)]) == 1


# -- the parser and the maths ------------------------------------------------------------------


def test_the_small_parser_reads_the_block_as_yaml_does(cp):
    block = cp.token_block(DESIGN.read_text(encoding="utf-8"))
    assert cp.parse_tokens(block) == yaml.safe_load(block)["tokens"]


def test_dj_design_holds_the_same_tokens_as_docs_design_md(cp):
    parsed = _tokens(cp)
    assert parsed == design.tokens()
    assert design.SLOT_NAMES == tuple(parsed["names"])
    assert design.SEQUENTIAL["dark"] == tuple(reversed(design.SEQUENTIAL["light"]))


def test_brief_hexes_in_slot_order():
    assert design.CATEGORICAL["light"] == ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300",
                                           "#6250d6", "#e34948")  # fmt: skip
    assert design.CATEGORICAL["dark"] == ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300",
                                          "#9085e9", "#e66767")  # fmt: skip
    assert (design.SEQUENTIAL["light"][0], design.SEQUENTIAL["light"][-1]) == ("#cde2fb", "#0d366b")
    assert design.slot_hex(1, "light") == "#2a78d6" and design.slot_hex(9) == design.OTHER["dark"]
    assert design.slot_hex(None, "light") == design.OTHER["light"]
    with pytest.raises(ValueError):
        design.slot_hex(1, "sepia")


def test_colour_maths_reference_points(cp):
    L, a, b = cp.oklab("#ffffff")
    assert abs(L - 1) < 1e-3 and abs(a) < 1e-3 and abs(b) < 1e-3
    assert cp.oklab("#000000") == pytest.approx((0, 0, 0), abs=1e-9)
    assert cp.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert cp.delta_e(cp.oklab("#2a78d6"), cp.oklab("#2a78d6")) == 0
    grey = cp.oklab("#808080")
    for kind in ("protan", "deutan", "tritan"):  # a grey stays (almost) grey under every simulation
        assert cp.delta_e(cp.simulate("#808080", kind), grey) < 1.5


# -- docs/design.md and CI ---------------------------------------------------------------------


def test_design_md_covers_the_system():
    text = DESIGN.read_text(encoding="utf-8")
    for needle in (
        ':root:where(:not([data-theme="light"]))', ':root[data-theme="dark"]', "@media (prefers-color-scheme: dark)",
        "Booth", "Day", "body { background", "ui-sans-serif, system-ui", "Other", "## Anti-patterns",
        "## Design checklist", "Tritanopia is a WARN", "scripts/check_palette.py", "localStorage",
    ):  # fmt: skip
        assert needle in text, needle
    assert "@font-face" not in text and "fonts.googleapis" not in text
    checklist = text.split("## Design checklist", 1)[1]
    assert len(re.findall(r"^- \[ \] ", checklist, re.MULTILINE)) >= 8


def test_ci_runs_the_palette_check():
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/check_palette.py docs/design.md" in workflow


def test_muted_text_and_the_other_grey_are_held_to_their_floors(cp, report):
    """W-31 review: muted text (ticks) at 4.5:1 and the Other grey (a mark) at 3:1, both themes."""
    for mode in ("light", "dark"):
        assert _status(report, mode, "muted contrast")["status"] == "PASS"
        assert _status(report, mode, "other contrast")["status"] == "PASS"
    tokens = _tokens(cp)
    tokens["light"]["muted"], tokens["light"]["other"] = "#898781", "#a8a7a0"  # the values before the review
    result = cp.check(tokens)
    statuses = {r["check"]: r["status"] for r in result["modes"]["light"]["results"]}
    assert statuses["muted contrast"] == "FAIL" and statuses["other contrast"] == "FAIL"
    assert design.MUTED["light"] == "#6e6d68" and design.OTHER["light"] == "#8f8e88"
