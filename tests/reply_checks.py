"""The mechanical part of the pre-send checklist, for spot checks on DJ-facing text.

One checklist covers both checks R-1003 names: the pre-send block at the end of
plugin/shared/adhd.md. Its Voice line points to plugin/shared/voice.md; the part of the voice a
regex can see is the Avoid column of its word table. Everything else on the checklist (first
person, numbers from the tool, no tangents) is a reviewer's read.

Used by tests/test_skills.py (W-19) on the style guide's own example, and for R-1003's spot check
on 3 real outputs: the dj-report HTML (W-17; `report_sections` turns it into the plain text of
each section, the shape `text_problems` reads), and since W-30b the generated MD file
docs/samples/profile/stats.md and the six replies of docs/samples/chat-session-1.md
(`session_replies` reads them out, `step_reply_problems` checks each one).
"""

from __future__ import annotations

import re
from functools import cache
from html.parser import HTMLParser
from pathlib import Path

VOICE = Path(__file__).resolve().parents[1] / "plugin" / "shared" / "voice.md"

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


@cache
def avoided_words() -> tuple[str, ...]:
    """The Avoid column of the word table in voice.md, lower case."""
    text = VOICE.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.search(
        r"^## Words we use / words we avoid\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    if not m:
        raise ValueError("voice.md has no '## Words we use / words we avoid' section")
    rows = [line for line in m.group(1).split("\n") if line.startswith("|")][2:]
    return tuple(row.strip("|").split("|")[1].strip().lower() for row in rows)


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


def reply_problems(reply: str) -> list[str]:
    """`text_problems` plus the checks that only a chat reply has to pass."""
    problems = text_problems(reply)
    if problems == ["empty text"]:
        return problems
    lines = [line for line in reply.strip().split("\n") if line.strip()]
    if not STATE.search(reply):
        problems.append("rule 5: no 'Step N of M' (or 'Question N of M')")
    if not FILE_NAMED.search(reply):
        problems.append("rule 7: no file named")
    if not TIME.search(lines[-1]):
        problems.append("rules 3/6: last line has no concrete time estimate")
    return problems


def step_reply_problems(reply: str) -> list[str]:
    """`text_problems` plus the shape every reply of a step-by-step skill has (dj-start, Rules):
    the lead line starts with the step counter ("Step 2 of 6 · ") and holds one concrete time
    estimate. For the replies of a session, where `reply_problems` is too strict (a hello names
    no file; an export card ends on its last numbered step, not on a time)."""
    problems = text_problems(reply)
    if problems == ["empty text"]:
        return problems
    lead = reply.strip().split("\n")[0]
    if not LEAD.match(lead):
        problems.append("rule 5: the lead line does not start with 'Step N of M · '")
    if len(TIME.findall(lead)) != 1:
        problems.append("rule 6: the lead line holds no time estimate, or more than one")
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
