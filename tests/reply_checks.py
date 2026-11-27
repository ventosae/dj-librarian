"""Spot checks on DJ-facing text the engine writes: no pleasantry first, lists of 5 at most, no
avoided word. Used by test_barber, test_identity and test_report."""

from __future__ import annotations

import re
from html.parser import HTMLParser

AVOIDED = ('amazing', 'journey', 'seamless', 'simply', 'unfortunately')  # the word table of the old voice.md (D-36)

PREAMBLE = re.compile(
    r"^(hi|hello|hey|great|sure|certainly|of course|absolutely|thanks|thank you|happy to)\b",
    re.IGNORECASE,
)
# Rule 5 restates where we are. The checklist's "Step 2 of 6" is an example; a question session
# (dj-barber) says "Question 3 of 8".
STATE = re.compile(r"\b(?:Step|Question) \d+ of \d+\b")
TIME = re.compile(
    r"\b(under|about|around) (a|an|one|two|\d+) (minute|minutes|hour|hours)\b|\b\d+ ?min\b",
    re.IGNORECASE,
)
FILE_NAMED = re.compile(r"[\w./-]+\.(md|json|xml|yaml|html)\b")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
HEADING = re.compile(r"^\s*#{1,6} ")
# dj-start's own rule: "Every reply starts with the step counter and a time estimate".
LEAD = re.compile(r"^(?:Step|Question) \d+ of \d+ · ")


def avoided_words() -> tuple[str, ...]:
    return AVOIDED


def text_problems(text: str) -> list[str]:
    """Checks that hold for any DJ-facing text: a chat reply, an MD file, the words of a report."""
    lines = [line for line in text.replace("\r\n", "\n").strip().split("\n") if line.strip()]
    if not lines:
        return ["empty text"]
    problems = []
    first = next((line for line in lines if not HEADING.match(line)), "")
    if PREAMBLE.match(first.strip()):
        problems.append("rule 10: opens with a pleasantry")
    run = 0
    for line in lines:
        run = run + 1 if LIST_ITEM.match(line) else 0
        if run > 5:
            problems.append("rule 9: a list longer than 5")
            break
    for word in avoided_words():
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            problems.append(f"voice: uses the avoided word '{word}'")
    return problems


def session_replies(md: str) -> list[tuple[str, list[str]]]:
    """The replies of a sample session (docs/samples/chat-session-1.md): for each "## Reply"
    section, (the reply as sent: its ```text block, the widgets that came with it: every list
    item under the block)."""
    out = []
    for part in re.split(r"^## Reply \d+ of \d+\s*$", md.replace("\r\n", "\n"), flags=re.MULTILINE)[1:]:
        m = re.search(r"```text\n(.*?)\n```(.*)\Z", part, re.DOTALL)
        if not m:
            raise ValueError("a reply without its ```text block")
        widgets = [line.strip()[2:] for line in m.group(2).split("\n") if LIST_ITEM.match(line)]
        out.append((m.group(1), widgets))
    return out


class _SectionText(HTMLParser):
    """The text of each `<section id=...>`: headings as `# ` lines, `<li>` as `- ` lines, other
    blocks as plain lines. An `<li>` that holds a list is the label of that list: a plain line,
    so a nested list counts as its own list. The SVG drawing and `<style>` are not text."""

    BLOCKS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "figcaption", "article",
              "ul", "ol", "section", "figure", "header", "footer", "br"}  # fmt: skip
    SKIP = {"svg", "style", "script", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: dict[str, list[str]] = {}
        self.current: str | None = None
        self.stack: list[str] = []
        self.buffer: list[str] = []
        self.prefix = ""
        self.skipping = 0

    def _flush(self, prefix: str | None = None) -> None:
        text = " ".join("".join(self.buffer).split())
        if text and self.current is not None:
            self.sections[self.current].append((self.prefix if prefix is None else prefix) + text)
        self.buffer, self.prefix = [], ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skipping += 1
            return
        if self.skipping:
            return
        if tag == "section":
            self._flush()
            self.current = dict(attrs).get("id") or ""
            self.sections.setdefault(self.current, [])
        if tag in ("ul", "ol") and self.stack and self.stack[-1] == "li":
            self._flush(prefix="")  # the label of the nested list
        elif tag in self.BLOCKS:
            self._flush()
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.prefix = "# "
        elif tag == "li":
            self.prefix = "- "
        if tag in ("li", "ul", "ol"):
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
            return
        if self.skipping:
            return
        if tag in self.BLOCKS:
            self._flush()
        if tag in ("li", "ul", "ol") and self.stack:
            self.stack.pop()
        if tag == "section":
            self.current = None

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.buffer.append(data)


def report_sections(page: str) -> dict[str, str]:
    """{section id: its text, one line per block} of an HTML report."""
    parser = _SectionText()
    parser.feed(page)
    parser.close()
    return {key: "\n".join(lines) for key, lines in parser.sections.items()}
