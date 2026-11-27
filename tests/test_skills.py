"""The seven skills (D-35, D-36): each SKILL.md starts with the reply rules and stays under its limit."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

SKILLS = Path(__file__).resolve().parents[1] / "plugin" / "skills"

# name -> the most lines its SKILL.md may have; rare detail goes in a file beside the skill.
LIMITS = {"dj-start": 300, "dj-crate": 200, "dj-build": 200, "dj-barber": 200, "dj-tidy": 200,
          "dj-spotify": 200, "install": 200}  # fmt: skip

REPLY_RULES = """\
## How to reply
1. First line is the answer or the next move. No greeting, no recap, no sign-off.
2. A working DJ talking to a DJ, first person: "I matched 41 of 48." Blunt, no hype. Booth words (crate, set, floor), never developer words.
3. Say where we are in one line: "Step 2 of 4".
4. Number the steps, one action each, with a real time: "about 2 minutes".
5. One question per reply, with choices to tap.
6. Lists stop at 5. The rest goes in a file; name the file.
7. Every number comes from the tool. Not measured, not said.
8. Taste is the DJ's call: versions, keepers, deletions. Offer, don't pick.
9. Errors in one line: what failed, what happens next. No apology.
10. End with one thing the DJ can do in under 2 minutes. Nothing is written to rekordbox, Spotify or audio files without a preview and a yes.
"""


def test_the_seven_skills_start_with_the_reply_rules_and_stay_under_their_limit():
    assert {p.name for p in SKILLS.iterdir() if p.is_dir()} == set(LIMITS)
    for name, limit in LIMITS.items():
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        found = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
        assert found, f"{name}: no frontmatter"
        meta, body = yaml.safe_load(found.group(1)), found.group(2)
        # claude.ai's upload check: the folder's name, a description without angle brackets, at most 1,024
        assert meta["name"] == name
        assert "<" not in meta["description"] and ">" not in meta["description"], name
        assert 0 < len(meta["description"]) <= 1024, name
        assert body.strip().startswith(REPLY_RULES), f"{name}: the body does not start with the reply rules"
        assert len(text.splitlines()) <= limit, f"{name}: {len(text.splitlines())} lines, at most {limit}"
