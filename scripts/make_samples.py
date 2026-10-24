"""Build docs/samples/ from the synthetic fixture library: the files a DJ gets after the first run,
the sample report, and its screenshots (R-409).

    uv run python scripts/make_samples.py [--today 2026-10-20] [--out docs/samples] [--no-screenshots]
                                          [--height 7000] [--phone FILE]

What it does, start to end, in a temporary folder (deleted afterwards):
1. Writes the export of tests/xml_fixtures.py (invented artists and playlists, nothing personal)
   as collection.xml and runs the skill scripts exactly as dj-start steps 3 and 4 run them:
   dj-start `find-xml` and `init` (Windows, handle "DJ Sample"), dj-profile, dj-structure,
   dj-taste, dj-identity, all with a fixed --today.
2. Writes the two files Claude writes in a real session: profile/habits.md (from the numbers in
   profile/stats.md) and profile/identity.md (the liner notes by the dj-identity template: at
   most 120 words and four lines, never an axis name and a number in one sentence, every number
   one of the values in profile/identity.json: an input, a decade, or a number the archetype or
   an input's own name carries, like the 256 of `under_256`; a count that opens a sentence is a
   word, "Six"). A number in either that is not in its source stops the script: the fixture
   changed and the words must be checked.
3. Runs dj-report (proposals + render) and copies into the output folder: SAMPLE_FILES and the
   report as reports/sample-library.html. The "table" links of the report point at ../profile/...
   and ../structure/..., so they resolve inside docs/samples/ too. No absolute or temporary
   path may appear in any sample file (checked); running the script twice gives the same bytes.
   Writes chat-session-1.md (Q-15, R-1003): the six replies of dj-start as they would be sent in
   that session, chips version, taken from the ```text templates of plugin/skills/dj-start/SKILL.md
   and filled with the values the scripts returned (a template that changes changes the sample;
   a placeholder left unfilled stops the script).
4. Screenshots with headless Microsoft Edge (skipped with a message when Edge is not installed,
   or with --no-screenshots): the full page at 1100 px wide in both themes through the URL hash,
   `#booth` -> report-booth.png, `#day` -> report-day.png (the two R-409 names); and a
   390 px wide Booth screenshot for reviewers, outside the repo (--phone, default: the system
   temp folder). Edge renders into a tall window (--height); Pillow then cuts the rows of plain
   page background below the end of the page. The command, for one theme:
       msedge --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1
              --window-size=1100,7000 --screenshot=<png> file:///<docs/samples/reports/...html>#booth
Nothing here touches rekordbox, Spotify, audio files or the network.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "plugin" / "skills"
sys.path.insert(0, str(REPO / "tests"))

import xml_fixtures as fx  # noqa: E402  (the synthetic export lives with the tests)

HANDLE = "DJ Sample"
TODAY = "2026-10-20"
SAMPLE_FILES = (
    "profile/stats.md",
    "profile/habits.md",
    "profile/identity.json",
    "profile/identity.md",
    "profile/sleeve.svg",
    "structure/analysis.md",
    "structure/graph.json",
    "structure/proposals.yaml",
    "taste/lanes.md",
)
SAMPLE_REPORT = "reports/sample-library.html"
SAMPLE_CHAT = "chat-session-1.md"
START_SKILL = SKILLS / "dj-start" / "SKILL.md"
DEVICE = "windows"
EXPORT_NAME = "collection.xml"  # the name dj-start's export card (step 2) gives the file
SHOTS = {"booth": "report-booth.png", "day": "report-day.png"}
WIDTH, PHONE_WIDTH = 1100, 390
HEIGHT = 7000  # the window height of the full-page shots; a page that reaches it is cut
LINER_MAX_WORDS = 120
EDGE_PATHS = (
    Path(r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path(r"C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
)

# Claude's words for the sample, in the voice (plugin/shared/voice.md), template of dj-profile.
HABITS = """\
# Who you are as a DJ

> Words by Claude, from profile/stats.md and profile/facts.json.

You play house up front and funk and disco underneath: 24 tracks from the 1970s to the 2020s, most \
from the 2010s (6 tracks). The peak sits in 1.2_peak, the warm-up in 1.1_warm_up, the old records in \
funk & disco 78-92.

You have been digging since 2019-04-12. The busiest year is 2026 with 4 tracks, and the last 365 \
days brought 4 tracks.

You keep the tags tight: BPM on every track, Genre 96%, Key 92%. Colour is the field you skip, 71%.

One thing to watch: 2 groups of duplicate candidates, 4 tracks. Grid Saint - Pressure Vessel is in \
there as a flac and an mp3 at 128 kbps. Which copy stays is your call.
"""

# The liner notes for the sample, by the dj-identity template (R-1404, W-30b): four lines under
# the heading. (1) The two strong axes in booth words, one fact each, no axis name and no score;
# (2) the booth line in quotes; (3) the weakest axis as a fact and the DJ's call; (4) what the
# library is good at on a floor, from the strongest axis, standing on its own ("On a floor: ...",
# never "that means", which would point back at the weak spot). {placeholders} are inputs of that axis
# in identity.json; {x_s} is "s" unless input x is 1.
STRONG = {
    "depth": "{decades} decades in the crates, centred on the {median_decade}",
    "selectivity": "{lossless} lossless tracks and {at_320} at 320",
    "discipline": "{in_folders} of {playlists} playlists filed in folders",
    "breadth": "{genres} genres across {lanes} BPM lanes",
    "momentum": "{added_last_365_days} tracks added in the last 365 days",
    "memory": "ratings on {rating}% of the tracks",
}
WEAK = {
    "depth": "The crates stay close to now: {decades} decade{decades_s} in all. Digging back is your call.",
    "selectivity": "The soft spot is the files: {under_256} track{under_256_s} under 256 kbps. Better copies or "
                   "not, your call.",
    "discipline": "The soft spot is the filing: {dumps} dump{dumps_s} to split. When is your call.",
    "breadth": "The sound runs narrow: {genres} genre{genres_s} across {lanes} BPM lane{lanes_s}. Wider or not "
               "is your call.",
    "momentum": "The digging has slowed: the last add was {days_since_last_add} days ago. Your call.",
    "memory": "The mark-up is thin: comments on {comment}% of the tracks. Your call.",
}  # fmt: skip
FLOOR = {
    "depth": "On a floor: an answer to any request back to the {oldest}.",
    "selectivity": "On a floor: files that hold up on a big system.",
    "discipline": "On a floor: the next record is where you left it.",
    "breadth": "On a floor: you follow the room across {lanes} BPM lanes.",
    "momentum": "On a floor: records the room has not heard yet.",
    "memory": "On a floor: your marks find the next record fast.",
}
LINER_LINES = 4
# A count that opens a sentence is a word ("Six decades"); the number check reads these words as
# their digits (not "one": "that one" is not a count).
NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                "nineteen", "twenty")  # fmt: skip
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,:-]\d+)*")
_WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS[2:]) + r")\b", re.IGNORECASE)


def _opening(text: str) -> str:
    """A sentence start: a leading count up to twenty as a word, the first letter capitalised."""
    m = re.match(r"(\d+) ", text)
    if m and int(m.group(1)) < len(NUMBER_WORDS):
        text = NUMBER_WORDS[int(m.group(1))] + text[m.end(1):]
    return text[:1].upper() + text[1:]


def _fields(axis: dict) -> dict:
    out = {"score": axis["score"], "name": axis["name"], **axis["inputs"]}
    for key, value in axis["inputs"].items():
        out[f"{key}_s"] = "" if value == 1 else "s"
    return out


def liner_notes(identity: dict) -> str:
    """profile/identity.md for the sample, from identity.json only (the dj-identity template)."""
    axes = identity["axes"]
    first, second = identity["top"]
    lowest = min(identity["order"], key=lambda a: (axes[a]["score"], identity["order"].index(a)))
    fields = {a: _fields(axes[a]) for a in axes}
    strong = _opening(STRONG[first].format(**fields[first])) + ", and " + STRONG[second].format(**fields[second]) + "."
    lines = [
        "# Liner notes",
        "",
        "> Words by Claude, from profile/identity.json.",
        "",
        strong,
        "",
        f"\u201c{identity['archetype']['booth_line']}\u201d",
        "",
        WEAK[lowest].format(**fields[lowest]),
        "",
        FLOOR[first].format(**fields[first]),
        "",
    ]
    return "\n".join(lines)


def check_booth_words(words: str, identity: dict, what: str) -> None:
    """The liner-notes rules a script can see (R-1404, W-30b): at most LINER_LINES lines under the
    heading and its "Words by Claude" line, and never an axis name in a sentence that holds a
    number (no "Depth 94"). The booth line is the archetype's own and is not judged."""
    body = [line for line in words.split("\n")[1:] if line.strip() and not line.startswith(">")]
    if len(body) > LINER_LINES:
        raise SystemExit(f"{what}: {len(body)} lines under the heading, at most {LINER_LINES}")
    names = [axis["name"] for axis in identity["axes"].values()]
    for line in body:
        if line.startswith("\u201c"):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            named = [n for n in names if re.search(rf"\b{re.escape(n)}\b", sentence, re.IGNORECASE)]
            if named and _numbers(sentence):
                raise SystemExit(f"{what}: an axis name and a number in one sentence ({named[0]}): {sentence}")


def _numbers(text: str) -> set[str]:
    """The numbers in `text`: digits as written, and the count words two to twenty as digits."""
    return set(_NUMBER.findall(text)) | {str(NUMBER_WORDS.index(w.lower())) for w in _WORD.findall(text)}


def identity_numbers(identity: dict) -> set[str]:
    """The numbers liner notes may hold (R-1404, R-302): each numeric input as identity.json
    writes it, the number in a decade ("1970s" -> "1970"), and the numbers the archetype's own
    lines and the inputs' names carry ("320" of `at_320`, "365" of `added_last_365_days`). Never
    an axis score (the notes hold no score at all, dj-identity/SKILL.md), unless the same value
    is also one of those. Nothing else: a count that is not one of these values fails."""
    allowed: set[str] = set()
    for axis in identity["axes"].values():
        for key, value in axis["inputs"].items():
            allowed |= _numbers(key.replace("_", " "))
            if isinstance(value, bool) or value is None:
                continue
            allowed |= _numbers(str(value))
    for text in identity["archetype"].values():
        allowed |= _numbers(str(text))
    return allowed


def check_identity_numbers(words: str, identity: dict, what: str) -> None:
    """Every number in the liner notes is one of identity.json's values (identity_numbers)."""
    missing = sorted(_numbers(words) - identity_numbers(identity))
    if missing:
        raise SystemExit(f"{what}: numbers that are not values in profile/identity.json: {', '.join(missing)}. "
                         "The fixture changed; update the sample words in scripts/make_samples.py.")  # fmt: skip


def check_numbers(words: str, source: str, what: str) -> None:
    """Every number in Claude's words is in the file it came from (R-302)."""
    missing = sorted(n for n in _numbers(words) if n not in source)
    if missing:
        raise SystemExit(f"{what}: numbers not in the source file: {', '.join(missing)}. The fixture changed; "
                         "update the sample words in scripts/make_samples.py.")  # fmt: skip


def run(script: str, *args: object) -> dict:
    """One skill script, as the DJ's Claude runs it: one JSON object, exit 0."""
    done = subprocess.run(
        [sys.executable, str(SKILLS / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO, timeout=300,
        env=dict(os.environ, PYTHONUTF8="1"),
    )  # fmt: skip
    try:
        out = json.loads(done.stdout)
    except ValueError:
        raise SystemExit(f"{script}: no JSON ({done.returncode}): {done.stdout}{done.stderr}") from None
    if done.returncode != 0:
        raise SystemExit(f"{script}: exit {done.returncode}: {out}")
    return out


# -- the chat: the six dj-start replies (Q-15, R-1003) ------------------------------------------


def _blocks(body: str) -> list[tuple[str, str]]:
    """(the last line of prose before it, the block) for each ```text block in `body`."""
    out: list[tuple[str, str]] = []
    lines, last, i = body.split("\n"), "", 0
    while i < len(lines):
        if lines[i].strip() == "```text":
            end = lines.index("```", i + 1)
            out.append((last, "\n".join(lines[i + 1:end])))
            i, last = end + 1, ""
            continue
        if lines[i].strip():
            last = lines[i].strip()
        i += 1
    return out


def skill_steps(text: str) -> dict[int, str]:
    """{N: the body of "### Step N: ..."} of dj-start/SKILL.md."""
    text = text.replace("\r\n", "\n")
    found = re.finditer(r"^### Step (\d+):[^\n]*\n(.*?)(?=^#{2,3} |\Z)", text, re.MULTILINE | re.DOTALL)
    return {int(m.group(1)): m.group(2) for m in found}


def _template(steps: dict[int, str], step: int, fits, what: str) -> str:
    for before, block in _blocks(steps.get(step, "")):
        if fits(before, block):
            return block
    raise SystemExit(f"plugin/skills/dj-start/SKILL.md: step {step} has no {what} any more; "
                     "update chat_session in scripts/make_samples.py")  # fmt: skip


def _numbered(block: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^\d+\. (.+)$", block, re.MULTILINE)]


def chat_session(skill: str, *, start: dict, report: dict) -> str:
    """chat-session-1.md: the six replies dj-start sends in session 1 (chips version), from the
    ```text templates of its SKILL.md, filled with what the scripts returned (`start`: the init
    JSON, `report`: the dj-report JSON). The widgets (chips, the task list, the file card) are
    listed under the reply they come with; the DJ's moves are the lines in italics."""
    steps = skill_steps(skill)

    def chips_only(before: str, _block: str) -> bool:  # not the "No chips" / "No task list" version
        return not before.startswith("No ")

    hello = _template(steps, 1, chips_only, "chips reply")
    hello_chips = _numbered(_template(steps, 1, lambda b, _t: b.startswith("No chips"), "numbered reply"))
    export = _template(steps, 2, lambda b, _t: b == f"{DEVICE.title()}:", f"{DEVICE.title()} card")
    folder = _template(steps, 3, lambda _b, _t: True, "folder line")  # the first block of step 3
    done = _template(steps, 3, lambda _b, t: t.startswith("Step 3 of 6 · done"), "done line")
    counts = start["counts"]
    done = (done.replace("<n>", str(len(start["created"]))).replace("<export>", start["export"])
            .replace("<tracks>", str(counts["tracks"])).replace("<playlists>", str(counts["playlists"])))  # fmt: skip
    working = _template(steps, 4, chips_only, "working line")
    tasks = [m.group(1) for m in re.finditer(r"^\d+\. (\w+): ", steps.get(4, ""), re.MULTILINE)]
    delivered = _template(steps, 5, lambda _b, t: "<date>-library.html" in t, "report line")
    delivered = delivered.replace("reports/<date>-library.html", report["report"])
    nxt = _template(steps, 6, chips_only, "chips reply")
    later = re.search(r"plus `([^`]+)`", steps.get(6, ""))
    next_chips = [p["trigger"] for p in report["proposals"]] + ([later.group(1)] if later else [])
    replies = [
        (hello, [("Chips", hello_chips)], f"The DJ types: {DEVICE.title()}, {HANDLE}"),
        (export, [], f"The DJ exports {EXPORT_NAME} and says: done"),
        (folder, [], f"The DJ connects a folder called dj-library and drops {EXPORT_NAME} into it."),
        (done, [], ""),
        (working, [("Task list, each item ticked off as it finishes", [f"[x] {t}" for t in tasks])], ""),
        (f"{delivered}\n{nxt}", [("File card", [report["report"]]), ("Chips", next_chips)], ""),
    ]
    lines = [
        "# Session 1: the six dj-start replies",
        "",
        "> Written by scripts/make_samples.py from the reply templates in plugin/skills/dj-start/SKILL.md "
        f"(chips version), with the sample library's values: {DEVICE.title()}, handle {HANDLE}. Each reply "
        "is the text as sent, the widgets that come with it are listed under it, and the DJ's moves are in "
        f"italics. The report the last reply names is {SAMPLE_REPORT} here.",
    ]
    for n, (text, widgets, move) in enumerate(replies, 1):
        lines += ["", f"## Reply {n} of {len(replies)}", "", "```text", text, "```"]
        for title, items in widgets:
            lines += ["", f"{title}:", "", *(f"- {item}" for item in items)]
        if move:
            lines += ["", f"*{move}*"]
    chat = "\n".join(lines) + "\n"
    left = re.findall(r"<[a-z][a-z0-9 _]*>", chat)
    if left or not tasks or not hello_chips or len(next_chips) < 2:
        raise SystemExit(f"{SAMPLE_CHAT}: dj-start/SKILL.md templates changed (unfilled: {', '.join(left) or '-'}); "
                         "update chat_session in scripts/make_samples.py")  # fmt: skip
    return chat


def build_library(work: Path, today: str) -> tuple[Path, str]:
    """The fixture library after a whole first run (dj-start steps 3 to 5). Returns the report
    path and the chat of that session (chat_session)."""
    lib = work / "dj-library"
    lib.mkdir()
    fx.write_xml(lib / EXPORT_NAME)
    found = run("dj-start/scripts/start.py", "find-xml", "--library", lib)
    start = run("dj-start/scripts/start.py", "init", "--library", lib, "--device", DEVICE, "--today", today,
                "--dj-name", HANDLE, "--xml", found["xml"])  # fmt: skip
    for script in ("dj-profile/scripts/profile.py", "dj-structure/scripts/structure.py",
                   "dj-taste/scripts/taste.py", "dj-identity/scripts/identity.py"):  # fmt: skip
        run(script, "--library", lib, "--today", today)
    # numbers from stats.md; playlist names (which hold digits too) from the other MD files
    sources = "\n".join((lib / rel).read_text(encoding="utf-8") for rel in (
        "profile/stats.md", "structure/analysis.md", "taste/lanes.md", "taste/vocabulary.md"))  # fmt: skip
    check_numbers(HABITS.split("\n", 3)[3], sources, "profile/habits.md")
    (lib / "profile" / "habits.md").write_text(HABITS, encoding="utf-8", newline="\n")
    identity = json.loads((lib / "profile" / "identity.json").read_text(encoding="utf-8"))
    notes = liner_notes(identity)
    check_identity_numbers(notes, identity, "profile/identity.md")
    check_booth_words(notes, identity, "profile/identity.md")
    words = len(notes.split())
    if words > LINER_MAX_WORDS:
        raise SystemExit(f"profile/identity.md: {words} words, at most {LINER_MAX_WORDS}")
    (lib / "profile" / "identity.md").write_text(notes, encoding="utf-8", newline="\n")
    out = run("dj-report/scripts/report.py", "--library", lib, "--today", today)
    chat = chat_session(START_SKILL.read_text(encoding="utf-8"), start=start, report=out)
    return lib / out["report"], chat


def copy_samples(lib: Path, report: Path, out: Path, work: Path, chat: str) -> list[Path]:
    """Copy the sample files and write the chat; refuse any that names an absolute or temporary path."""
    written = []
    leaks = {str(work), work.as_posix(), str(lib), lib.as_posix(), str(REPO), REPO.as_posix(), "file:/"}
    files = [(rel, (lib / rel).read_bytes()) for rel in SAMPLE_FILES]
    files += [(SAMPLE_REPORT, report.read_bytes()), (SAMPLE_CHAT, chat.encode("utf-8"))]
    for rel, data in files:
        text = data.decode("utf-8")
        found = [leak for leak in leaks if leak and leak in text]
        if found or re.search(r"\b[A-Za-z]:[\\/]|/Users/|/home/|/tmp/", text):
            raise SystemExit(f"{rel}: holds an absolute or temporary path ({found or 'drive or home path'})")
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written.append(dest)
    return written


# -- screenshots ---------------------------------------------------------------------------------


def find_edge() -> Path | None:
    for path in EDGE_PATHS:
        if path.is_file():
            return path
    found = shutil.which("msedge") or shutil.which("microsoft-edge")
    return Path(found) if found else None


EDGE_MIN_WIDTH = 500  # Edge will not open a narrower window: a phone shot goes through a frame


def shoot(edge: Path, page: Path, png: Path, *, width: int, height: int, theme: str, profile: Path) -> None:
    """One full-page screenshot of `page` in `theme`, `width` CSS px wide, cut to the end of the
    page. Below EDGE_MIN_WIDTH the page is laid out in a frame of that width inside a wider
    window (a temporary wrapper page next to the Edge profile), and the shot is cropped to it."""
    url = page.resolve().as_uri() + f"#{theme}"
    png.parent.mkdir(parents=True, exist_ok=True)
    if png.exists():
        png.unlink()
    window = width
    if width < EDGE_MIN_WIDTH:
        frame = profile / "frame.html"
        frame.write_text(
            "<!doctype html><meta charset=\"utf-8\"><style>html,body{margin:0;background:#000}"
            f"iframe{{display:block;border:0;width:{width}px;height:{height}px}}</style>"
            f'<iframe src="{url}"></iframe>',
            encoding="utf-8",
        )
        url, window = frame.resolve().as_uri(), EDGE_MIN_WIDTH
    command = [
        str(edge), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
        "--no-default-browser-check", "--disable-extensions", "--force-device-scale-factor=1",
        f"--user-data-dir={profile}", "--virtual-time-budget=3000",
        f"--window-size={window},{height}", f"--screenshot={png}", url,
    ]  # fmt: skip
    subprocess.run(command, capture_output=True, timeout=180)
    if not png.is_file():
        raise SystemExit(f"Edge wrote no screenshot for {theme} ({png.name}). In a sandboxed shell Edge may "
                         "exit at once: run the script from a normal terminal.")  # fmt: skip
    trim(png, width, height)


def trim(png: Path, width: int, height: int) -> None:
    """Crop to `width` and cut the rows of plain page background at the bottom (Pillow, a
    project dependency), so the PNG ends where the page ends."""
    from PIL import Image, ImageChops

    with Image.open(png) as img:
        rgb = img.convert("RGB").crop((0, 0, width, img.height))
    background = rgb.getpixel((0, rgb.height - 1))
    box = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background)).getbbox()
    bottom = box[3] if box else rgb.height
    if bottom >= height:
        print(f"warning: {png.name}: the page may be taller than the {height} px window; raise --height")
    rgb.crop((0, 0, rgb.width, bottom)).save(png, optimize=True)


def screenshots(out: Path, phone: Path, height: int) -> list[Path]:
    edge = find_edge()
    if not edge:
        print("screenshots skipped: Microsoft Edge (msedge) not found. Install Edge or pass --no-screenshots.")
        return []
    page = out / SAMPLE_REPORT
    written = []
    with tempfile.TemporaryDirectory(prefix="djl-edge-", ignore_cleanup_errors=True) as profile:
        for theme, name in SHOTS.items():
            png = out / name
            shoot(edge, page, png, width=WIDTH, height=height, theme=theme, profile=Path(profile))
            written.append(png)
        shoot(edge, page, phone, width=PHONE_WIDTH, height=height + 4000, theme="booth", profile=Path(profile))
        written.append(phone)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--today", default=TODAY, help="the date every step runs at (YYYY-MM-DD)")
    parser.add_argument("--out", default=str(REPO / "docs" / "samples"), help="where the samples go")
    parser.add_argument("--no-screenshots", action="store_true", help="text samples only")
    parser.add_argument("--height", type=int, default=HEIGHT, help="window height for the full-page shots")
    parser.add_argument("--phone", default=str(Path(tempfile.gettempdir()) / "djl-w31" / "report-phone.png"),
                        help="the 390 px wide screenshot for reviewers (kept out of the repo)")  # fmt: skip
    args = parser.parse_args(argv)
    out = Path(args.out)
    work = Path(tempfile.mkdtemp(prefix="djl-samples-"))
    try:
        report, chat = build_library(work, args.today)
        written = copy_samples(work / "dj-library", report, out, work, chat)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not args.no_screenshots:
        written += screenshots(out, Path(args.phone), args.height)
    for path in written:
        try:
            print(path.relative_to(REPO).as_posix())
        except ValueError:
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
