"""The optional Cowork Project template, templates/project/instructions.md (R-107, C-04, D-16).

R-107 acceptance: the template exists (voice, ADHD rules, safety, folder conventions) and the flow
works without it. "Works without it" is checked here as: nothing in the plugin (skills, shared/,
config, hooks) and no core code depends on the template; a Markdown line in the plugin may mention
it only to say the template is optional (not negated), and nothing else in the plugin mentions it
at all. The voice and the rules stay
in the plugin (`plugin/shared/voice.md`, `plugin/shared/adhd.md`, W-19); the template points there
and does not copy the pre-send checklist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dj.libfolder import DIRS, FILES

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "templates" / "project" / "instructions.md"
README = REPO / "README.md"
REQUIREMENTS = REPO / "docs" / "requirements.md"
PLUGIN = REPO / "plugin"
SRC = REPO / "src"
ADHD = PLUGIN / "shared" / "adhd.md"
VOICE = PLUGIN / "shared" / "voice.md"

MAX_LINES = 120

# R-901, spelled out so a change to DIRS/FILES cannot quietly drop an entry from the template.
R901_DIRS = (
    "exports", "profile", "structure", "taste", "crates", "reports", "proposals", "wishlist",
)  # fmt: skip
R901_FILES = ("README.md", "library.yaml", "links.yaml", "log.md")

# R-1002, in this order (the same titles as plugin/shared/adhd.md).
RULES = (
    "lead with the next action",
    "number steps",
    "end with one action under 2 minutes",
    "no tangents",
    "restate state",
    "concrete time estimates",
    "make finished work visible",
    "matter-of-fact errors",
    "cap lists at 5",
    "no preamble or pleasantries",
)

ATTRIBUTION = "Rules adapted from the i-have-adhd skill by ayghri (MIT licence)."
START = "Say hi. The dj-start skill takes it from there."

# The Avoid column of voice.md's word table at W-19; voice.md's own table is added when present.
AVOIDED = ("amazing", "journey", "seamless", "simply", "unfortunately")

# A line that talks about the template (not `UV_PROJECT_ENVIRONMENT` and the like).
MENTION = re.compile(
    r"templates/project|project template|project instructions|cowork project|instructions\.md"
    r"|project(?:'|’)?s instructions",
    re.IGNORECASE,
)

# The one thing the plugin may say about the template: that it is optional (W-13's dj-start: "The
# Cowork Project template `templates/project/instructions.md` is optional; nothing in this skill
# depends on it"). "Optional" must qualify the template itself, in the same clause: "the template
# ... is optional" or "the optional Project template". An "optional" elsewhere on the line, or a
# negated one ("not optional", "non-optional"), exempts nothing.
_REFERENT = r"\b(?:template|instructions(?:\.md)?)"
SAYS_OPTIONAL = re.compile(
    rf"{_REFERENT}[^.;:!?]*?\b(?:is|are)\s+optional\b"
    r"|(?<![\w-])optional\s+(?:[\w-]+\s+){0,2}(?:template|instructions)\b",
    re.IGNORECASE,
)
NEGATED = re.compile(
    r"\b(?:not|never|isn't|aren't|isn’t|aren’t|no\s+longer)\s+optional\b"
    r"|\bnon-?optional\b",
    re.IGNORECASE,
)


def _text(path: Path) -> str:
    """File text with line endings normalised to LF (a Windows checkout may carry CRLF)."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _sections(text: str) -> dict[str, str]:
    """Level-2 heading -> body."""
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}


@pytest.fixture(scope="module")
def text() -> str:
    return _text(TEMPLATE)


@pytest.fixture(scope="module")
def sections(text) -> dict[str, str]:
    return _sections(text)


# -- R-107: the template exists, is short, and says it is optional


def test_template_exists():
    assert TEMPLATE.is_file()
    assert _text(TEMPLATE).startswith("# ")


def test_template_at_most_120_lines(text):
    assert len(text.splitlines()) <= MAX_LINES


def test_template_has_the_r107_sections(sections):
    assert list(sections) == [
        "Who you talk to",
        "Reply rules",
        "Safety",
        "Folder conventions",
        "How to start",
    ]
    assert all(body.strip() for body in sections.values())


def test_template_says_it_is_optional(text):
    # C-04 / D-16: the DJ pastes it if they want; the plugin carries everything without it.
    intro = text.split("\n## ", 1)[0].lower()
    assert "optional" in intro
    assert "works without it" in intro
    assert "plugin" in intro
    assert "dj-library/" in intro


# -- who you talk to: the voice in our own words, pointing to the plugin (R-1001, C-08)


def test_voice_section_is_short_and_points_to_voice_md(sections):
    body = sections["Who you talk to"]
    lines = [line for line in body.split("\n") if line.strip()]
    assert 1 <= len(lines) <= 5
    assert "working DJ" in body
    assert "shared/voice.md" in body


def test_no_book_text(text):
    # C-08: the voice is style only. The template does not name the book, so nothing from it can
    # creep in; the one line that names it lives in plugin/shared/voice.md.
    assert "Fresh" not in text
    assert "how to be a dj" not in text.lower()


def test_template_avoids_the_voice_words(text):
    words = set(AVOIDED)
    if VOICE.is_file():  # plugin/shared/voice.md (W-19): its own Avoid column
        for row in re.findall(r"^\|([^|\n]*)\|([^|\n]*)\|\s*$", _text(VOICE), re.MULTILINE):
            word = row[1].strip().lower()
            if word and word != "avoid" and not set(word) <= {"-", ":"}:
                words.add(word)
    lower = text.lower()
    assert [w for w in sorted(words) if re.search(rf"\b{re.escape(w)}\b", lower)] == []


# -- reply rules: the 10 rules of R-1002, one line each, with the attribution (C-09)


def test_reply_rules_ten_in_order_one_line_each(sections):
    body = sections["Reply rules"]
    lines = body.split("\n")
    numbered = [(i, m) for i, line in enumerate(lines) if (m := re.match(r"^(\d+)\. (.+)$", line))]
    assert [int(m.group(1)) for _, m in numbered] == list(range(1, 11))
    for (i, m), rule in zip(numbered, RULES):
        title = re.match(r"\*\*(.+?)\.?\*\* (\S.*)$", m.group(2))
        assert title, f"rule {m.group(1)}: expected '**Title.** how-to'"
        assert title.group(1).lower() == rule, f"rule {m.group(1)} must be '{rule}'"
        assert len(title.group(2)) > 15, f"rule {m.group(1)} needs a line of how-to"
        after = lines[i + 1] if i + 1 < len(lines) else ""
        assert after == "" or re.match(r"^\d+\. ", after), f"rule {m.group(1)} is one line"


def test_reply_rules_titles_match_adhd_md(sections):
    ours = re.findall(r"^\d+\. \*\*(.+?)\.?\*\*", sections["Reply rules"], re.MULTILINE)
    assert [t.lower() for t in ours] == list(RULES)
    if ADHD.is_file():  # plugin/shared/adhd.md (W-19) is the canonical wording
        theirs = re.findall(r"^\d+\. \*\*(.+?)\.?\*\*", _text(ADHD), re.MULTILINE)
        assert [t.lower() for t in theirs] == [t.lower() for t in ours]


def test_reply_rules_attribution(text, sections):
    assert ATTRIBUTION in text.split("\n")
    assert ATTRIBUTION in sections["Reply rules"]


def test_checklist_is_referenced_not_copied(text, sections):
    assert "shared/adhd.md" in sections["Reply rules"]
    assert "Pre-send checklist" not in text
    assert "- [ ]" not in text


# -- safety (C-01, C-02, hard rules 1, 2, 4, 6)


@pytest.mark.parametrize(
    "statement",
    [
        "create and add only",
        "never delete, rename, move or reorder anything that exists in rekordbox",
        "dry-run by default",
        "preview, then an explicit yes",
        "is not a yes",
        "the default write path is a rekordbox xml the dj imports",
        "never open or print `.env`",
    ],
)
def test_safety_statement(sections, statement):
    body = " ".join(sections["Safety"].lower().split())  # wrapped lines read as one
    assert statement in body


def _bullets(body: str) -> list[str]:
    """Top-level '- ' bullets of a section, wrapped lines joined, lower case."""
    items: list[str] = []
    for line in body.split("\n"):
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("  ") and items:
            items[-1] += " " + line.strip()
    return [" ".join(item.lower().split()) for item in items]


def test_safety_exception_is_only_dj_tidy_and_says_all_it_writes(sections):
    # dj-tidy (src/dj/tidy/plan.py) fills EMPTY tags only, embeds artwork only where there is none
    # (art="local" is the default), renames inside the file's own folder, and renames a file
    # rekordbox already knows only with --rename-imported; every apply leaves an undo record.
    # The exception names all of that and nothing wider: standing instructions read as permission.
    body = " ".join(sections["Safety"].lower().split())
    assert body.count("exception") == 1
    exception = next(b for b in _bullets(sections["Safety"]) if "exception" in b)
    assert exception.startswith("create and add only.")
    after = exception.split("exception", 1)[1]
    assert "dj-tidy" in after
    assert "when the dj asks" in after
    assert "empty tags" in after
    assert "missing artwork" in after
    assert "own folder" in after
    assert "files rekordbox already knows only when the dj says so" in after
    assert "undo" in after
    widening = r"\b(any|all|every|overwrite\w*|rewrite\w*|replace\w*|fix\w*|correct\w*|chang\w*)\b"
    assert re.findall(widening, after) == []


# -- folder conventions: every R-901 entry, one line each; library as code; tool-written log


def test_r901_spelled_out_matches_the_scaffold():
    assert set(R901_DIRS) == set(DIRS)
    assert set(R901_FILES) <= set(FILES)


def test_folder_conventions_list_every_r901_entry(sections):
    body = sections["Folder conventions"]
    entries = [f"{d}/" for d in R901_DIRS] + list(R901_FILES) + [".gitignore"]
    for entry in entries:
        lines = [line for line in body.split("\n") if line.startswith(f"- `{entry}`")]
        assert len(lines) == 1, f"{entry}: expected exactly one line"
        assert len(lines[0]) > len(f"- `{entry}`: ") + 10, f"{entry}: say what it holds"


def test_folder_conventions_library_as_code_and_tool_log(sections):
    body = sections["Folder conventions"]
    assert "library as code" in " ".join(body.split())
    assert "dj-library/" in body
    log = next(line for line in body.split("\n") if line.startswith("- `log.md`"))
    assert "tool writes it" in log.lower()


def test_lists_have_at_most_five_items_except_the_rules(sections):
    # R-1002 rule 9 for the template's own bullet lists; the 10 rules are the one numbered list.
    for head, body in sections.items():
        run = 0
        for line in body.split("\n"):
            run = run + 1 if line.startswith("- ") else (run if line.startswith("  ") else 0)
            assert run <= 5, f"'{head}' has a list longer than 5"


# -- how to start


def test_how_to_start(sections):
    assert START in sections["How to start"]


def test_how_to_start_is_addressed_to_the_dj(sections):
    # Every other "you" in the template is Claude, and rule 10 forbids greetings: the "Say hi"
    # line must be marked as the DJ's, or Claude reads it as an order to greet.
    lines = [line.strip() for line in sections["How to start"].split("\n")]
    assert f"For the DJ: {START}" in lines


# -- R-107 "the flow works without it": nothing in the plugin or the core needs the template


def _says_template_is_optional(line: str) -> bool:
    return bool(SAYS_OPTIONAL.search(line)) and not NEGATED.search(line)


def _template_mentions(root: Path) -> list[str]:
    """Lines under `root` that could make the template a prerequisite.

    Markdown (skills, shared/voice.md, shared/adhd.md, ...) may mention it only on a line that says
    the template is optional; any other text file (config, hooks, scripts) must not mention it.
    """
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = _text(path)
        except UnicodeDecodeError:  # binary: an icon or the like
            continue
        markdown = path.suffix.lower() in {".md", ".markdown"}
        for n, line in enumerate(text.split("\n"), start=1):
            if not MENTION.search(line):
                continue
            if not markdown or not _says_template_is_optional(line):
                found.append(f"{path.relative_to(root).as_posix()}:{n}")
    return found


def test_nothing_in_the_plugin_requires_the_template():
    found = _template_mentions(PLUGIN)
    assert found == [], "the plugin mentions the Project template without saying it is optional"


# Lines that make the template a prerequisite: each must be flagged, wherever it sits.
REQUIRES_IT = (
    "First read the Project template instructions the DJ pasted.",
    "Load templates/project/instructions.md first.",
    "Before step 1, read the instructions.md the DJ pasted into the Project.",
    "Follow the Project's instructions first.",
    "Follow the Project’s instructions first.",
    "Optional flags aside, load templates/project/instructions.md before anything else.",
    "Not optional: read templates/project/instructions.md before anything else.",
    "The Cowork Project instructions are non-optional; stop if missing.",
    "The Project template is not optional here.",
    "Stop unless the Project's instructions are pasted.",
    "Optional: load the Project template, then go to step 2.",
)

# Lines that only say the template is optional: each may stay.
SAYS_OPTIONAL_LINES = (
    "The Cowork Project template is optional; nothing needs it.",
    "The Cowork Project template `templates/project/instructions.md` is optional; nothing in this"
    " skill depends on it (R-107).",
    "The optional Cowork Project template repeats the voice; the skill works without it.",
    "The Project instructions are optional.",
)


def test_template_mention_scan_covers_the_whole_plugin(tmp_path):
    # The guard itself: shared/ files count as much as skills, and config may not mention it.
    plugin = tmp_path / "plugin"
    files = {
        "shared/adhd.md": REQUIRES_IT[0] + "\n",
        "shared/voice.md": SAYS_OPTIONAL_LINES[0] + "\n",
        "skills/dj-x/SKILL.md": "\n".join(REQUIRES_IT[1:]) + "\n",
        "skills/dj-y/SKILL.md": "\n".join(SAYS_OPTIONAL_LINES) + "\n",
        "skills/dj-x/scripts/x.py": '"""Optional: reads templates/project/x.md."""\n',
        ".mcp.json": '{"env": {"UV_PROJECT_ENVIRONMENT": "x"}}\n',
        "hooks/hooks.json": '{"note": "the project template is optional"}\n',
    }
    for rel, content in files.items():
        (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
        (plugin / rel).write_text(content, encoding="utf-8")
    (plugin / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
    assert sorted(_template_mentions(plugin)) == sorted(
        ["hooks/hooks.json:1", "shared/adhd.md:1", "skills/dj-x/scripts/x.py:1"]
        + [f"skills/dj-x/SKILL.md:{n}" for n in range(1, len(REQUIRES_IT))]
    )


@pytest.mark.parametrize("line", REQUIRES_IT)
def test_a_line_that_requires_the_template_is_flagged(line):
    assert MENTION.search(line), "the scan must see this line at all"
    assert not _says_template_is_optional(line)


@pytest.mark.parametrize("line", SAYS_OPTIONAL_LINES)
def test_a_line_that_says_the_template_is_optional_passes(line):
    assert MENTION.search(line)
    assert _says_template_is_optional(line)


def test_core_code_does_not_reference_the_template():
    for path in sorted(SRC.rglob("*.py")):
        assert "templates/project" not in _text(path), path.relative_to(REPO).as_posix()
        assert "instructions.md" not in _text(path), path.relative_to(REPO).as_posix()


# -- nothing personal (C-05, hard rule 7)


def _persona_names() -> list[str]:
    """The bold names in the personas table of docs/requirements.md (read, not hard-coded)."""
    return re.findall(r"^\| P-\d+ \| \*\*(.+?)\*\*", _text(REQUIREMENTS), re.MULTILINE)


PERSONAL = {
    "an email address": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "a Windows path": r"\b[A-Za-z]:[\\/]",
    "a UNC path": r"\\\\[\w.$-]+\\",
    "a home or mount path": r"(^|[\s`(\"'])(/Users/|/home/|/Volumes/|/mnt/|/media/|/run/media/|~/)",
    "a URL": r"://",
    "something shaped like a Spotify id": r"\b[A-Za-z0-9]{22}\b",
}


def _personal_data(text: str) -> list[str]:
    """What in `text` looks personal: paths, addresses, ids, and the personas' names in any case."""
    found = [what for what, pattern in PERSONAL.items() if re.search(pattern, text)]
    names = _persona_names()
    assert names, "personas table not found in docs/requirements.md"
    found += [
        f"a persona's name ({n})"
        for n, name in enumerate(names, start=1)
        if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE)
    ]
    return found


def test_no_personal_data():
    # templates/ is outside R-1206's acceptance grep (src tests plugin README.md CONTRIBUTING.md
    # examples), so this is its guard: every file under templates/, not only instructions.md.
    files = sorted(p for p in (REPO / "templates").rglob("*") if p.is_file())
    assert TEMPLATE in files
    for path in files:
        assert _personal_data(_text(path)) == [], path.relative_to(REPO).as_posix()


@pytest.mark.parametrize(
    "line, what",
    [
        ("Library at \\\\nas\\music\\dj-library.", "a UNC path"),
        ("Library at /mnt/music/dj-library.", "a home or mount path"),
        ("Library at /media/usb/dj-library.", "a home or mount path"),
        ("Library at `/Users/x/Music`.", "a home or mount path"),
        ("Library at D:/Music.", "a Windows path"),
        ("Share it at smb://nas/music.", "a URL"),
        ("Mail dj@example.org.", "an email address"),
    ],
)
def test_personal_data_check_catches(line, what):
    assert what in _personal_data(line)


@pytest.mark.parametrize("case", [str.lower, str.upper, str.title])
def test_personal_data_check_ignores_case_of_persona_names(case):
    # The names are read from docs/requirements.md, so none is written into this file (R-1206).
    for n, name in enumerate(_persona_names(), start=1):
        assert f"a persona's name ({n})" in _personal_data(f"Ask {case(name)} first.")


# -- README: one line in the plugin section


def test_readme_points_to_the_optional_template():
    section = _sections(_text(README))["Claude plugin"]
    lines = [line for line in section.split("\n") if "templates/project/instructions.md" in line]
    assert len(lines) == 1
    assert "optional" in lines[0].lower()
    assert "works without it" in lines[0]
