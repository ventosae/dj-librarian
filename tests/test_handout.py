"""The A6 handout, docs/handout/ (W-34 item 5).

The card's "Set me up" line says the engine is already in (D-28). The PDF is 2 pages of 105 × 148 mm,
the size the HTML's `@page` sets; the two previews are its pages at 3×; docs/handout/README.md names
the files, the OFL fonts embedded in fonts.css and the exact commands that re-render all three.
"""

from __future__ import annotations

import re
import struct
from html.parser import HTMLParser
from pathlib import Path

HANDOUT = Path(__file__).resolve().parents[1] / "docs" / "handout"
HTML = HANDOUT / "dj-librarian-a6.html"
PDF = HANDOUT / "dj-librarian-a6.pdf"
README = HANDOUT / "README.md"
SET_ME_UP = "It’s already in — say set me up and point me at your dj-library folder."
PT_PER_MM = 72 / 25.4


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


class _Rows(HTMLParser):
    """(bubble, what) for every row of the back page's "say these" list."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.cls: str | None = None

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if cls == "row":
            self.rows.append([])
        if cls in ("bubble", "what"):
            self.cls = cls
            self.rows[-1].append("")

    def handle_endtag(self, tag):
        if tag == "div":
            self.cls = None

    def handle_data(self, data):
        if self.cls and self.rows:
            self.rows[-1][-1] += data


def _rows() -> dict[str, str]:
    parser = _Rows()
    parser.feed(_text(HTML))
    return {bubble.strip(): " ".join(what.split()) for bubble, what in parser.rows}


def test_the_set_me_up_line_says_the_engine_is_already_in():
    rows = _rows()
    assert rows["Set me up"] == SET_ME_UP
    assert "Installs the engine" not in _text(HTML) and "10 min)" not in _text(HTML)


def test_the_page_size_is_a6_from_the_css():
    html = _text(HTML)
    assert "@page { size: 105mm 148mm; margin: 0; }" in html
    assert html.count('<section class="page">') == 2


def test_the_pdf_has_two_a6_pages():
    data = PDF.read_bytes()
    assert data.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s*/Page(?!s)", data)) == 2
    boxes = re.findall(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", data)
    assert len(boxes) == 2
    for width, height in boxes:
        assert abs(float(width) / PT_PER_MM - 105) < 0.5 and abs(float(height) / PT_PER_MM - 148) < 0.5


def test_the_previews_are_the_two_pages_at_3x():
    for name in ("preview-front.png", "preview-back.png"):
        head = (HANDOUT / name).read_bytes()[:24]
        assert head[:8] == b"\x89PNG\r\n\x1a\n", name
        assert struct.unpack(">II", head[16:24]) == (1191, 1678), name


def test_the_readme_names_the_files_and_the_ofl_fonts():
    readme = _text(README)
    for name in ("dj-librarian-a6.html", "fonts.css", "dj-librarian-a6.pdf", "preview-front.png", "preview-back.png"):
        assert f"`{name}`" in readme, name
    families = set(re.findall(r"font-family:'([^']+)'", _text(HANDOUT / "fonts.css")))
    assert families == {"Bangers", "Comic Neue", "Patrick Hand"}
    for family in families:
        assert family in readme, family
    assert "SIL Open Font License 1.1" in readme and "@page { size: 105mm 148mm; margin: 0; }" in readme


def test_the_readme_keeps_the_exact_render_commands():
    readme = _text(README)
    blocks = dict(re.findall(r"```(powershell|bash)\n(.*?)\n```", readme, re.DOTALL))
    assert set(blocks) == {"powershell", "bash"}
    assert "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" in blocks["powershell"]
    assert "Google Chrome.app" in blocks["bash"]
    for block in blocks.values():
        for part in ("--headless", "--user-data-dir=", "--no-pdf-header-footer",
                     "--print-to-pdf=\"$PWD/docs/handout/dj-librarian-a6.pdf\"", "--force-device-scale-factor=3",
                     "--window-size=397,1119", "--screenshot=", "-crop 1191x1678+0+0 +repage docs/handout/preview-front.png",
                     "-crop 1191x1678+0+1679 +repage docs/handout/preview-back.png"):  # fmt: skip
            assert part in block, part
    assert "| Out-Null" in blocks["powershell"]  # PowerShell waits for Edge only when piped
