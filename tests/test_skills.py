"""Every skill carries the shared voice, the ADHD rules and the pre-send checklist.

R-1001 (voice.md, every skill references it, no book text: C-08) and R-1002 (adhd.md with the 10
rules and attribution: C-09, the pre-send checklist in each SKILL.md).

R-1003's acceptance is a spot check on 3 real outputs (a report, an MD file, a chat reply). The
report is checked by `test_r1003_spot_check_on_the_report` (W-17), the MD file and the chat
replies by `test_r1003_spot_check_on_an_md_file` and `test_r1003_spot_check_on_the_chat_replies`
over docs/samples (W-30b, Q-15). "Both checklists" = the one pre-send block: its Voice line covers voice.md,
the other lines cover adhd.md. The mechanical checks live in tests/reply_checks.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from reply_checks import avoided_words, reply_problems, text_problems

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
SKILLS = PLUGIN / "skills"
SHARED = PLUGIN / "shared"
VOICE = SHARED / "voice.md"
ADHD = SHARED / "adhd.md"

VOICE_REF = "../../shared/voice.md"
ADHD_REF = "../../shared/adhd.md"

# The canonical block from docs/prompts/plans/v0.1-interfaces.md section 3. adhd.md ends with it and
# every SKILL.md ends with it, character for character (line endings normalised).
CHECKLIST = """\
## Pre-send checklist

Before every reply, check:

- [ ] The first line is the next action or the answer. No preamble, no pleasantries.
- [ ] Where we are is restated in one line (for example "Step 2 of 6").
- [ ] Steps are numbered, with one concrete time estimate.
- [ ] Lists have 5 items or fewer.
- [ ] No tangents: only what this step needs.
- [ ] Finished work is visible: name the file that was written.
- [ ] Errors are stated matter-of-fact: what failed, what happens next.
- [ ] It ends with one action that takes under 2 minutes.
- [ ] Voice: a working DJ talking to a DJ. Blunt, practical, no hype (shared/voice.md).
- [ ] Nothing was written to rekordbox, Spotify or audio files without a preview and an explicit yes.
"""

# R-1002, in this order.
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

QUOTE_MARKS = "\"'“”‘’«»„"

SKILL_DIRS = sorted(p for p in SKILLS.iterdir() if p.is_dir() and not p.name.startswith("."))


def _text(path: Path) -> str:
    """File text with line endings normalised to LF (a Windows checkout may carry CRLF)."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _last_section(text: str) -> str:
    """Everything from the last level-2 heading to the end of the file."""
    heads = list(re.finditer(r"^## ", text, re.MULTILINE))
    assert heads, "no '## ' heading"
    return text[heads[-1].start() :].rstrip("\n")


def _frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    assert m, "SKILL.md must start with a YAML frontmatter block between '---' lines"
    meta = yaml.safe_load(m.group(1))
    assert isinstance(meta, dict), "frontmatter must be a mapping"
    return meta, m.group(2)


def _sections(text: str, level: str) -> dict[str, str]:
    """Heading text -> body, for headings of exactly this level ("##" or "###")."""
    parts = re.split(rf"^{level} (.+)$", text, flags=re.MULTILINE)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}


def _do_dont_pairs(text: str) -> list[tuple[str, str]]:
    lines = [line.strip() for line in text.split("\n")]
    pairs = []
    for a, b in zip(lines, lines[1:]):
        if a.startswith("- Do: ") and b.startswith("- Don't: "):
            pairs.append((a[len("- Do: ") :].strip(), b[len("- Don't: ") :].strip()))
    return pairs


# -- every skill folder


def test_skill_folders_exist():
    names = {p.name for p in SKILL_DIRS}
    assert {"dj-sync", "dj-tidy"} <= names


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_skill_md_exists(skill_dir):
    assert (skill_dir / "SKILL.md").is_file()


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_frontmatter_name_and_description(skill_dir):
    meta, _ = _frontmatter(_text(skill_dir / "SKILL.md"))
    assert meta.get("name") == skill_dir.name
    description = meta.get("description")
    assert isinstance(description, str) and description.strip()


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_frontmatter_passes_the_claude_ai_upload_check(skill_dir):
    """claude.ai's Upload plugin refused the zip over `<slug>` in a description: no XML tags, a
    lowercase-hyphen name of at most 64 characters, a description of at most 1,024 (Q-21)."""
    meta, _ = _frontmatter(_text(skill_dir / "SKILL.md"))
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", meta["name"]) and len(meta["name"]) <= 64
    assert "<" not in meta["description"] and ">" not in meta["description"], skill_dir.name
    assert len(meta["description"]) <= 1024


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_body_names_requirement_ids(skill_dir):
    _, body = _frontmatter(_text(skill_dir / "SKILL.md"))
    assert re.search(r"R-[0-9]{3,4}", body), "the body must name the R-ids it serves"


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_references_voice_and_adhd(skill_dir):
    _, body = _frontmatter(_text(skill_dir / "SKILL.md"))
    for ref, target in ((VOICE_REF, VOICE), (ADHD_REF, ADHD)):
        assert ref in body, f"{skill_dir.name}/SKILL.md must reference {ref}"
        resolved = (skill_dir / ref).resolve()
        assert resolved.is_file(), f"{ref} does not resolve from {skill_dir.name}/"
        assert resolved == target.resolve()


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_ends_with_the_canonical_checklist(skill_dir):
    last = _last_section(_text(skill_dir / "SKILL.md"))
    assert last.startswith("## Pre-send checklist"), "the last section must be the checklist"
    assert last == _last_section(_text(ADHD)), "checklist differs from plugin/shared/adhd.md"


def test_no_bin_directory_in_plugin():
    found = [p.relative_to(PLUGIN).as_posix() for p in PLUGIN.rglob("bin") if p.is_dir()]
    assert found == []


# -- adhd.md (R-1002, C-09)


def test_adhd_ends_with_the_canonical_checklist():
    text = _text(ADHD)
    assert _last_section(text) == CHECKLIST.rstrip("\n")
    assert text.rstrip("\n").endswith(CHECKLIST.rstrip("\n")), "the checklist is the last thing"


def test_adhd_has_the_ten_rules_in_order():
    rules = _sections(_text(ADHD), "##")["The 10 rules"]
    numbered = re.findall(r"^(\d+)\. (.+)$", rules, re.MULTILINE)
    assert [int(n) for n, _ in numbered] == list(range(1, 11))
    for (n, line), rule in zip(numbered, RULES):
        m = re.match(r"\*\*(.+?)\.?\*\* (\S.*)$", line)
        assert m, f"rule {n}: expected '**Title.** how-to'"
        assert m.group(1).lower() == rule, f"rule {n} must be '{rule}'"
        assert len(m.group(2)) > 15, f"rule {n} needs a line of how-to"


def test_adhd_attribution():
    assert ATTRIBUTION in _text(ADHD).split("\n")


# -- voice.md (R-1001, C-08)


def test_voice_has_do_dont_pairs():
    pairs = _do_dont_pairs(_text(VOICE))
    assert len(pairs) >= 5
    assert all(do and dont for do, dont in pairs)


@pytest.mark.parametrize(
    "topic", ["opening", "number", "saying no", "error", "praise", "jargon"]
)
def test_voice_pairs_cover_topic(topic):
    sections = _sections(_text(VOICE), "###")
    hits = [body for head, body in sections.items() if topic in head.lower()]
    assert hits, f"no '### ' section about {topic}"
    assert any(_do_dont_pairs(body) for body in hits), f"no do/don't pair about {topic}"


def test_voice_no_quoted_book_text():
    lines = _text(VOICE).split("\n")
    offending = [line for line in lines if "Fresh" in line and any(q in line for q in QUOTE_MARKS)]
    assert offending == []
    # The one line that names the book also says nothing from it is reproduced (C-08).
    named = [line for line in lines if "Fresh" in line]
    assert len(named) == 1 and "C-08" in named[0]


def test_voice_word_lists_capped_at_five():
    section = _sections(_text(VOICE), "##")["Words we use / words we avoid"]
    rows = [line for line in section.split("\n") if line.startswith("|")]
    header, separator, *body = rows
    assert [c.strip().lower() for c in header.strip("|").split("|")] == ["use", "avoid"]
    assert set(separator.replace("|", "").strip()) <= {"-", ":", " "}
    assert 1 <= len(body) <= 5
    for row in body:
        use, avoid = (c.strip() for c in row.strip("|").split("|"))
        assert use and avoid


def test_voice_says_how_a_reply_is_checked():
    # "Both checklists" (R-1003) is one block: the Voice line of the pre-send checklist points here.
    section = _sections(_text(VOICE), "##")["Checking a reply"]
    assert "adhd.md" in section
    checks = [line for line in section.split("\n") if line.startswith("- ")]
    assert 1 <= len(checks) <= 5
    assert "shared/voice.md" in CHECKLIST


def test_voice_does_not_deny_tidy_renames():
    # dj tidy renames files when the DJ asks (--rename); the voice guide must not say it never does.
    tidy = _text(SKILLS / "dj-tidy" / "SKILL.md")
    assert "--rename" in tidy
    assert not re.search(r"never renames? anything", _text(VOICE), re.IGNORECASE)


# -- the mechanical checks (tests/reply_checks.py)


def test_voice_example_reply_passes_the_checklist():
    # The style guide's own example models the checklist. This is not the R-1003 spot check.
    section = _sections(_text(VOICE), "##")["Example reply"]
    m = re.search(r"```text\n(.*?)\n```", section, re.DOTALL)
    assert m, "the example reply sits in a ```text block"
    reply = m.group(1)
    assert len([line for line in reply.split("\n") if line.strip()]) == 3
    assert reply_problems(reply) == []


def test_avoided_words_come_from_the_voice_table():
    section = _sections(_text(VOICE), "##")["Words we use / words we avoid"]
    words = avoided_words()
    assert 1 <= len(words) <= 5
    assert all(f"| {w} |" in section.lower() for w in words)


def test_reply_check_catches_a_bad_reply():
    bad = "Great question! Here is an amazing find.\n" + "\n".join(f"- item {i}" for i in range(7))
    problems = reply_problems(bad)
    assert any(p.startswith("rule 10") for p in problems)
    assert any(p.startswith("rule 5") for p in problems)
    assert any(p.startswith("rule 7") for p in problems)
    assert any(p.startswith("rules 3/6") for p in problems)
    assert any(p.startswith("rule 9") for p in problems)
    assert "voice: uses the avoided word 'amazing'" in problems


def test_text_check_on_an_md_file():
    items = "\n".join(f"- track {i}" for i in range(5))
    good = f"# Profile\n\n> Measured by code.\n\n## Formats\n\n{items}\n\n## Keys\n\n{items}\n"
    assert text_problems(good) == []
    bad = "# Profile\n\nHello! A seamless library.\n\n" + items + "\n- track 5\n"
    problems = text_problems(bad)
    assert "rule 10: opens with a pleasantry" in problems
    assert "rule 9: a list longer than 5" in problems
    assert "voice: uses the avoided word 'seamless'" in problems
    assert text_problems("  \n") == ["empty text"]


# -- R-1003: spot check on 3 outputs: the report (W-17), a generated MD file and the chat replies of
# session 1 (W-30b, Q-15: docs/samples, built by scripts/make_samples.py from the real scripts and
# the dj-start reply templates).

SAMPLES = REPO / "docs" / "samples"


def test_r1003_spot_check_on_an_md_file():
    """A generated MD file: profile/stats.md of the sample library (dj-profile's own output)
    passes the checklist: no pleasantry first, no list over 5, no word from the Avoid column."""
    stats = _text(SAMPLES / "profile" / "stats.md")
    assert stats.startswith("# Library profile\n\n> Measured by code: dj.analysis.profile")
    assert text_problems(stats) == []


def test_r1003_spot_check_on_the_chat_replies():
    """The six dj-start replies of session 1, chips version (docs/samples/chat-session-1.md): each
    passes the checklist and dj-start's shape (the step counter and one time estimate on the lead
    line), widgets included (at most 5 chips or tasks); the steps run 1 to 6 in order, the hello
    asks for the handle, the last reply names the report and offers each proposal's trigger. No
    personal data: the sample handle only, no path outside the library folder, no address."""
    from reply_checks import session_replies, step_reply_problems

    chat, engine = _text(SAMPLES / "chat-session-1.md").split("\n# Session 1b: with the engine\n")
    replies = session_replies(chat)
    assert len(replies) == 6
    for text, widgets in replies:
        assert step_reply_problems(text) == [], (text, step_reply_problems(text))
        assert text_problems("\n".join([text, *(f"- {w}" for w in widgets)])) == []
        assert len(widgets) <= 5
    leads = [re.match(r"Step (\d) of 6", text).group(1) for text, _w in replies]
    assert leads == ["1", "2", "3", "3", "4", "5"] and "\nStep 6 of 6 · under 2 minutes." in replies[5][0]
    hello, chips = replies[0]
    assert "What do they call you in the booth?" in hello and chips == ["Mac", "Windows"]
    assert "DJ Sample" in chat and "*The DJ types: Windows, DJ Sample*" in chat
    report, widgets = replies[5]
    assert re.search(r"Your report: reports/\d{4}-\d{2}-\d{2}-library\.html", report)
    assert widgets[1:] == [f"Build me the {n} structure" for n in ("House Bases", "Deep Facets", "Warehouse Gigs")] + ["not yet"]
    assert widgets[0] in report  # the file card is the file the line names
    assert not re.search(r"\b[A-Za-z]:[\\/]|/Users/|/home/|/tmp/|@|<[a-z]", chat)
    # session 1b (W-36, D-30): with the engine, three replies for four steps, the same report and chips
    with_engine = session_replies(engine)
    assert [re.match(r"Step (\d) of 4", t).group(1) for t, _w in with_engine] == ["1", "2", "3"]
    for text, widgets in with_engine:
        assert step_reply_problems(text) == [] and text_problems(text) == [] and len(widgets) <= 5
    assert "\nStep 4 of 4 · under 2 minutes." in with_engine[2][0] and with_engine[2][1][1:] == widgets[1:]
    assert "export" not in engine.lower().split("> the same session")[0] and "Connect a folder" not in engine


def test_r1003_spot_check_on_the_report(tmp_path):
    """R-1003, report slot (W-17): a real dj-report HTML, the synthetic library through the whole
    chain (profile, structure, taste, proposals, render). The words of each of its four sections
    pass the mechanical checklist: no pleasantry first, no list over 5, no word from the Avoid
    column of voice.md. The rest of the checklist (first person, numbers from the tool) is the
    report code itself: every number in it comes from the facts files."""
    from datetime import date

    import xml_fixtures as fx
    from reply_checks import report_sections

    from dj import libfolder
    from dj.analysis import run_all

    day = date(2026, 10, 20)
    root = tmp_path / "dj-library"
    libfolder.scaffold(root, device="mac", today=day)
    libfolder.import_export(root, fx.write_xml(tmp_path / "collection.xml"), today=day)
    result = run_all.analyze(root, today=day)
    sections = report_sections((root / result["report"]).read_text(encoding="utf-8"))
    assert list(sections) == ["who", "structure", "proposals", "next"]
    for name, text in sections.items():
        assert text.split("\n")[0].startswith("# "), name  # each section has its heading ...
        assert not text.split("\n")[1].startswith(("# ", "- ")), name  # ... and then its point
        assert text_problems(text) == [], (name, text_problems(text))


EXPECTED_SKILLS = {
    "dj-start", "dj-profile", "dj-structure", "dj-taste", "dj-report", "dj-build",
    "dj-crate", "dj-barber", "dj-spotify", "dj-sync", "dj-tidy", "dj-identity", "install", "uninstall", "backup",
}  # fmt: skip


def test_the_v01_skill_set_is_complete():
    """BUILD-v0.1 success criterion, plus dj-identity (W-31): these twelve skills, plus install and uninstall (W-35, the DJ types them as
    /dj-librarian:install and :uninstall) and backup (W-37), no more, no fewer."""
    folders = {p.name for p in (Path(__file__).resolve().parents[1] / "plugin" / "skills").iterdir() if p.is_dir()}
    assert folders == EXPECTED_SKILLS


def test_skill_scripts_run_with_python3_not_a_bare_python():
    """macOS ships no `python` command (only python3), nor do many Linux sandboxes: a script line
    says python3, with `python` named as the Windows form (as dj-start does)."""
    for skill in sorted(SKILLS.glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        bare = re.findall(r"`python (?!3)[^`]*scripts/[^`]*`", text)
        assert not bare, (skill.parent.name, bare)
        if "python3 " in text and "scripts/" in text:
            assert "`python` on Windows" in text, skill.parent.name
