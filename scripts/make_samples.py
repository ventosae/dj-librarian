"""Build docs/samples/ from the synthetic fixture library: the files a DJ gets after the first run,
the sample report, and its screenshots (R-409).

    uv run python scripts/make_samples.py [--today 2026-10-20] [--out docs/samples] [--no-screenshots]
                                          [--height 7000] [--phone FILE]

What it does, start to end, in a temporary folder (deleted afterwards):
1. Writes the export of tests/xml_fixtures.py (invented artists and playlists, nothing personal)
   and runs the skill scripts exactly as dj-start step 4 runs them: dj-start `init` (handle
   "DJ Sample"), dj-profile, dj-structure, dj-taste, dj-identity, all with a fixed --today.
2. Writes the two files Claude writes in a real session: profile/habits.md (from the numbers in
   profile/stats.md) and profile/identity.md (the liner notes, at most 120 words, every number
   one of the values in profile/identity.json: a score, an input, a decade, or a number the
   archetype or an input's own name carries, like the 256 of `under_256`). A number in either
   that is not in its source stops the script: the fixture changed and the words must be checked.
3. Runs dj-report (proposals + render) and copies into the output folder: SAMPLE_FILES and the
   report as reports/sample-library.html. The "table" links of the report point at ../profile/...
   and ../structure/..., so they resolve inside docs/samples/ too. No absolute or temporary
   path may appear in any sample file (checked); running the script twice gives the same bytes.
4. Screenshots with headless Microsoft Edge (skipped with a message when Edge is not installed,
   or with --no-screenshots): the full page at 1100 px wide in both themes through the URL hash,
   `#booth` -> report-booth.png (and its copy report.png, R-409), `#day` -> report-day.png; and a
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
SHOTS = {"booth": "report-booth.png", "day": "report-day.png"}
R409 = "report.png"  # the screenshot R-409 names: a copy of the Booth one
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

# The liner notes for the sample, by the dj-identity template: an opening fact from the strongest
# axis (never the archetype's name or meaning: the report prints the name right above the notes),
# then the two top axes, each with a fact the opening did not use, the booth line, the lowest
# axis. {placeholders} are inputs of that axis in identity.json.
OPENINGS = {
    "depth": "Your crates run {decades} decades deep, from the {oldest} to the {newest}.",
    "selectivity": "{lossless} lossless tracks and {at_320} at 320 in your crates.",
    "discipline": "{in_folders} of your {playlists} playlists sit in folders.",
    "breadth": "Your crates cover {genres} genres.",
    "momentum": "{added_last_365_days} tracks added in the last 365 days.",
    "memory": "Ratings on {rating}% of your tracks.",
}
AXIS_LINES = {
    "depth": "Depth {score}: the middle of the crates sits in the {median_decade}.",
    "selectivity": "Selectivity {score}: {lossless} lossless tracks and {at_320} at 320.",
    "discipline": "Discipline {score}: {in_folders} of {playlists} playlists sit in folders.",
    "breadth": "Breadth {score}: {genres} genres across {lanes} BPM lanes.",
    "momentum": "Momentum {score}: {added_last_365_days} tracks added in the last 365 days.",
    "memory": "Memory {score}: ratings on {rating}% of the tracks, colours on {colour}%.",
}
AXIS_AFTER_OPENING = {  # the line of the opening's own axis, without the fact the opening used
    "depth": AXIS_LINES["depth"],
    "selectivity": "Selectivity {score}: {under_256} tracks under 256 kbps.",
    "discipline": "Discipline {score}.",
    "breadth": "Breadth {score}: {lanes} BPM lanes.",
    "momentum": "Momentum {score}.",
    "memory": "Memory {score}: colours on {colour}%.",
}
LOW_LINES = {
    "depth": "{name} sits lowest at {score}.",
    "selectivity": "{name} sits lowest at {score}: {under_256} tracks under 256 kbps. Your call.",
    "discipline": "{name} sits lowest at {score}: {dumps} dump to split. Your call.",
    "breadth": "{name} sits lowest at {score}: {lanes} BPM lanes.",
    "momentum": "{name} sits lowest at {score}: last add {days_since_last_add} days ago.",
    "memory": "{name} sits lowest at {score}: comments on {comment}% of the tracks. Your call.",
}
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,:-]\d+)*")


def liner_notes(identity: dict) -> str:
    """profile/identity.md for the sample, from identity.json only (the dj-identity template)."""
    axes = identity["axes"]
    arch = identity["archetype"]
    first, second = identity["top"]
    lowest = min(identity["order"], key=lambda a: (axes[a]["score"], identity["order"].index(a)))
    fields = {a: {"score": axes[a]["score"], "name": axes[a]["name"], **axes[a]["inputs"]} for a in axes}
    lines = [
        "# Liner notes",
        "",
        "> Words by Claude, from profile/identity.json.",
        "",
        OPENINGS[first].format(**fields[first]),
        "",
        AXIS_AFTER_OPENING[first].format(**fields[first]) + " " + AXIS_LINES[second].format(**fields[second]),
        "",
        f"\u201c{arch['booth_line']}\u201d",
        "",
        LOW_LINES[lowest].format(**fields[lowest]),
        "",
    ]
    return "\n".join(lines)


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def identity_numbers(identity: dict) -> set[str]:
    """The numbers liner notes may hold (R-1404, R-302): each axis score and numeric input as
    identity.json writes it, the number in a decade ("1970s" -> "1970"), and the numbers the
    archetype's own lines and the inputs' names carry ("320" of `at_320`, "365" of
    `added_last_365_days`). Nothing else: a count that is not one of these values fails."""
    allowed: set[str] = set()
    for axis in identity["axes"].values():
        allowed.add(str(axis["score"]))
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


def build_library(work: Path, today: str) -> Path:
    """The fixture library after a whole first run (dj-start step 4). Returns the report path."""
    lib = work / "dj-library"
    lib.mkdir()
    fx.write_xml(lib / "rekordbox.xml")
    run("dj-start/scripts/start.py", "init", "--library", lib, "--device", "windows", "--today", today,
        "--dj-name", HANDLE)  # fmt: skip
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
    words = len(notes.split())
    if words > LINER_MAX_WORDS:
        raise SystemExit(f"profile/identity.md: {words} words, at most {LINER_MAX_WORDS}")
    (lib / "profile" / "identity.md").write_text(notes, encoding="utf-8", newline="\n")
    out = run("dj-report/scripts/report.py", "--library", lib, "--today", today)
    return lib / out["report"]


def copy_samples(lib: Path, report: Path, out: Path, work: Path) -> list[Path]:
    """Copy the sample files; refuse any that names an absolute or temporary path."""
    written = []
    leaks = {str(work), work.as_posix(), str(lib), lib.as_posix(), str(REPO), REPO.as_posix(), "file:/"}
    for rel, src in [(rel, lib / rel) for rel in SAMPLE_FILES] + [(SAMPLE_REPORT, report)]:
        data = src.read_bytes()
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
        shutil.copyfile(out / SHOTS["booth"], out / R409)
        written.append(out / R409)
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
        report = build_library(work, args.today)
        written = copy_samples(work / "dj-library", report, out, work)
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
