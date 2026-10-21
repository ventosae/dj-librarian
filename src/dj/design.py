"""The design tokens every page this tool renders uses (docs/design.md, R-408).

Door 1: stdlib only. The single source for code is this module; the single source for people is
the token block in docs/design.md. `tests/test_check_palette.py` checks the two hold the same
values, and `scripts/check_palette.py` validates the block (OKLab distance, simulated colour
vision deficiency, contrast).

- `CATEGORICAL[mode]`: the eight categorical hexes in their fixed slot order (slot 1 first).
  A slot follows the thing it names (a BPM lane) everywhere on a page; it is never assigned by
  rank and never cycled. Past eight, things fold into `OTHER`.
- `SEQUENTIAL[mode]`: one blue ramp for magnitude, low to high. In the light mode low is the
  lightest step; in the dark mode the ramp is reversed so low recedes into the dark surface.
- `STATUS`: good / warning / critical, mode-invariant, always shown with an icon and a label,
  never used as a series.
- `SURFACE`, `TEXT`, `TEXT_2`, `MUTED`, `GRID`: page surface and ink per mode.

`slot_hex(slot, mode)` gives a slot's hex (1..8), or the "Other" grey for None or anything
outside 1..8.

`MAX_SLOTS_PER_CHART` (D-26, Q-29): a single chart (a sleeve, the crate wall, a mini sleeve, any
legend) shows at most 4 categorical slots. A lane keeps its slot (1..8 by BPM, slowest first, in
profile/identity.json), but a chart draws only slots 1..4 in colour; a lane past slot 4 folds into
"Other", the same rule as past eight, only sooner. So the light-mode tritan pair, yellow (slot 4)
and magenta (slot 5), never sit side by side in one chart. `chart_slot(slot)` is that rule.
"""

from __future__ import annotations

MODES = ("light", "dark")
SLOT_NAMES = ("blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red")
SLOTS = len(SLOT_NAMES)
MAX_SLOTS_PER_CHART = 4  # D-26: at most 4 colours per chart; lanes past slot 4 are "Other"

SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
PAGE = {"light": "#f9f9f7", "dark": "#0d0d0d"}
TEXT = {"light": "#0b0b0b", "dark": "#f0efec"}
TEXT_2 = {"light": "#52514e", "dark": "#c3c2b7"}
MUTED = {"light": "#6e6d68", "dark": "#898781"}
GRID = {"light": "#e1e0d9", "dark": "#2c2c2a"}
OTHER = {"light": "#8f8e88", "dark": "#6b6a65"}

CATEGORICAL = {
    "light": ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
    "dark": ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
}

_RAMP = (
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
    "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
)  # fmt: skip
SEQUENTIAL = {"light": _RAMP, "dark": tuple(reversed(_RAMP))}

STATUS = {"good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b"}
STATUS_ICONS = {"good": "✓", "warning": "!", "critical": "×"}

FONT_STACK = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'


def slot_hex(slot: int | None, mode: str = "dark") -> str:
    """The hex of categorical slot `slot` (1..8) in `mode`; None or past 8 -> the "Other" grey."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}, got {mode!r}")
    if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= SLOTS:
        return OTHER[mode]
    return CATEGORICAL[mode][slot - 1]


def chart_slot(slot: int | None) -> int | None:
    """The slot a chart draws for a lane's `slot`: 1..MAX_SLOTS_PER_CHART as it is; None,
    anything past MAX_SLOTS_PER_CHART or not a slot at all -> None, the "Other" grey (D-26)."""
    if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= MAX_SLOTS_PER_CHART:
        return None
    return slot


def tokens() -> dict:
    """The tokens in the shape of the docs/design.md token block (`tokens:` mapping)."""
    return {
        mode: {
            "surface": SURFACE[mode],
            "page": PAGE[mode],
            "text": TEXT[mode],
            "text_secondary": TEXT_2[mode],
            "muted": MUTED[mode],
            "grid": GRID[mode],
            "other": OTHER[mode],
            "categorical": list(CATEGORICAL[mode]),
            "sequential": list(SEQUENTIAL[mode]),
            "status": dict(STATUS),
        }
        for mode in MODES
    } | {"names": list(SLOT_NAMES)}
