"""Check the colour tokens of docs/design.md (R-408). Stdlib only.

    uv run python scripts/check_palette.py docs/design.md

Reads the one fenced ```yaml block that starts with `tokens:` and checks each mode (light, dark):

- the categorical slots' OKLCH lightness sits in the mode's band (light 0.43-0.77, dark
  0.48-0.67) and their chroma is at least 0.10 (below it a hue reads as grey)        FAIL
- every adjacent pair of slots (1-2, 2-3 ... 7-8) under normal vision: Delta E >= 15    FAIL
- the same pairs under simulated protanopia and deuteranopia (Machado, Oliveira and
  Fernandes 2009, severity 1.0, applied in linear sRGB): Delta E >= 8                  FAIL
- the same pairs under simulated tritanopia: Delta E < 8 is a WARN, never a FAIL (D-26).
  Relief: a chart shows at most 4 slots (dj.design.MAX_SLOTS_PER_CHART), so slots 4 and
  5 never meet in one chart, plus direct labels or the table link (docs/design.md)    WARN
- WCAG contrast of each slot against its surface: under 3:1 is a WARN that names the slots
  whose charts must carry direct labels or the table link                              WARN
- text and secondary text against the surface: at least 4.5:1                          FAIL
- muted text (ticks, axis units) against the surface, when the block has `muted`:
  at least 4.5:1                                                                       FAIL
- the Other grey, a mark colour, against the surface, when the block has `other`:
  at least 3:1                                                                         FAIL
- the sequential ramp: lightness strictly monotone, low to high                        FAIL
- status colours against the surface: under 3:1 is a WARN (icon + label carry them)    WARN

Delta E is the Euclidean distance in OKLab, times 100. Prints a report; exit 0 when nothing
FAILs (WARNs included), 1 otherwise (a missing or malformed token block too).

Importable: `parse_tokens`, `oklab`, `oklch`, `delta_e`, `simulate`, `contrast`, `check`,
`format_report`, `main`.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Any

MODES = ("light", "dark")
BANDS = {"light": (0.43, 0.77), "dark": (0.48, 0.67)}
CHROMA_FLOOR = 0.10
NORMAL_FLOOR = 15.0
CVD_FLOOR = 8.0
CONTRAST_FLOOR = 3.0
TEXT_FLOOR = 4.5
MARK_FLOOR = 3.0  # the Other grey fills marks: the non-text contrast floor
OPTIONAL_KEYS = ("muted", "other")  # checked when the block has them
SLOTS = 8
STATUS_KEYS = ("good", "warning", "critical")
MODE_KEYS = ("surface", "text", "text_secondary", "categorical", "sequential", "status")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# Machado, Oliveira, Fernandes (2009), severity 1.0, on linear sRGB.
CVD = {
    "protan": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "tritan": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}
GATED = ("protan", "deutan")  # FAIL below CVD_FLOOR; tritan only WARNs (docs/design.md, Validation)


class TokenError(ValueError):
    """The token block is missing, appears twice, or does not hold what the checks need."""


# -- the token block ---------------------------------------------------------------------------

_FENCE = re.compile(r"^```yaml[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


def token_block(markdown: str) -> str:
    """The text of the one ```yaml block whose first line is `tokens:`."""
    blocks = [b for b in _FENCE.findall(markdown.replace("\r\n", "\n")) if b.lstrip().startswith("tokens:")]
    if not blocks:
        raise TokenError("no ```yaml block starting with `tokens:` found")
    if len(blocks) > 1:
        raise TokenError(f"{len(blocks)} token blocks found; keep exactly one")
    return blocks[0]


def _strip_comment(line: str) -> str:
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _split_flow(text: str) -> list[str]:
    parts, quote, start = [], "", 0
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == ",":
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _scalar(text: str) -> Any:
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        return [_scalar(p) for p in _split_flow(text[1:-1])]
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    if text in ("null", "~", ""):
        return None
    return text


def parse_tokens(text: str) -> dict[str, Any]:
    """The YAML subset of the token block: nested mappings by two-space indentation, quoted or
    bare scalars, flow lists `[a, b]`, comments after `#` outside quotes. Returns the mapping
    under `tokens:`. Anything else (tabs, block lists, odd indentation) -> TokenError."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for number, raw in enumerate(text.split("\n"), 1):
        if "\t" in raw:
            raise TokenError(f"token block line {number}: tabs are not allowed")
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        match = re.fullmatch(r"([A-Za-z_][\w-]*):(?:\s+(.*))?", body)
        if not match:
            raise TokenError(f"token block line {number}: expected `key: value`, got {body!r}")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise TokenError(f"token block line {number}: bad indentation")
        parent = stack[-1][1]
        key, value = match.group(1), match.group(2)
        if key in parent:
            raise TokenError(f"token block line {number}: {key} given twice")
        if value is None or value == "":
            parent[key] = {}
            stack.append((indent, parent[key]))
        else:
            parent[key] = _scalar(value)
    tokens = root.get("tokens")
    if not isinstance(tokens, dict):
        raise TokenError("the block must start with `tokens:` and hold a mapping")
    return tokens


def validate(tokens: dict[str, Any]) -> None:
    """The shape the checks need; TokenError naming the first problem."""
    names = tokens.get("names")
    if not isinstance(names, list) or len(names) != SLOTS:
        raise TokenError(f"names: expected {SLOTS} slot names")
    for mode in MODES:
        block = tokens.get(mode)
        if not isinstance(block, dict):
            raise TokenError(f"{mode}: missing")
        for key in MODE_KEYS:
            if key not in block:
                raise TokenError(f"{mode}.{key}: missing")
        hexes = [block["surface"], block["text"], block["text_secondary"]]
        hexes += [block[key] for key in OPTIONAL_KEYS if key in block]
        if not isinstance(block["categorical"], list) or len(block["categorical"]) != SLOTS:
            raise TokenError(f"{mode}.categorical: expected {SLOTS} hexes in slot order")
        if not isinstance(block["sequential"], list) or len(block["sequential"]) < 2:
            raise TokenError(f"{mode}.sequential: expected a ramp of 2 or more hexes")
        status = block["status"]
        if not isinstance(status, dict) or any(k not in status for k in STATUS_KEYS):
            raise TokenError(f"{mode}.status: expected {', '.join(STATUS_KEYS)}")
        hexes += block["categorical"] + block["sequential"] + [status[k] for k in STATUS_KEYS]
        for value in hexes:
            if not isinstance(value, str) or not HEX.match(value):
                raise TokenError(f"{mode}: {value!r} is not a #rrggbb hex")


# -- colour maths ------------------------------------------------------------------------------


def srgb(hex_colour: str) -> tuple[float, float, float]:
    """#rrggbb -> sRGB channels 0..1."""
    if not HEX.match(hex_colour):
        raise TokenError(f"{hex_colour!r} is not a #rrggbb hex")
    value = hex_colour[1:]
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear(hex_colour: str) -> tuple[float, float, float]:
    return tuple(to_linear(c) for c in srgb(hex_colour))  # type: ignore[return-value]


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def linear_to_oklab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """Linear sRGB -> OKLab (L, a, b)."""
    r, g, b = rgb
    l_ = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m_ = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s_ = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab(hex_colour: str) -> tuple[float, float, float]:
    return linear_to_oklab(linear(hex_colour))


def oklch(hex_colour: str) -> tuple[float, float, float]:
    """(L, C, hue in degrees)."""
    L, a, b = oklab(hex_colour)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def simulate(hex_colour: str, kind: str) -> tuple[float, float, float]:
    """OKLab of `hex_colour` as seen with `kind` (protan, deutan, tritan) at severity 1.0."""
    matrix = CVD[kind]
    rgb = linear(hex_colour)
    seen = tuple(min(1.0, max(0.0, sum(row[j] * rgb[j] for j in range(3)))) for row in matrix)
    return linear_to_oklab(seen)  # type: ignore[arg-type]


def delta_e(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Euclidean distance in OKLab, times 100."""
    return 100 * math.dist(a, b)


def luminance(hex_colour: str) -> float:
    r, g, b = linear(hex_colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two hexes (1..21)."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# -- the checks --------------------------------------------------------------------------------


def _result(check: str, status: str, detail: str) -> dict[str, str]:
    return {"check": check, "status": status, "detail": detail}


def check_mode(block: dict[str, Any], names: list[str], mode: str) -> dict[str, Any]:
    """Every check for one mode: the slots, the adjacent pairs, the worst values, the results."""
    surface, cats = block["surface"], block["categorical"]
    low, high = BANDS[mode]
    slots = []
    for n, (name, hex_colour) in enumerate(zip(names, cats), 1):
        L, C, h = oklch(hex_colour)
        slots.append({"slot": n, "name": name, "hex": hex_colour, "L": L, "C": C, "hue": h,
                      "contrast": contrast(hex_colour, surface)})  # fmt: skip
    pairs = []
    for a, b in zip(slots, slots[1:]):
        row = {"pair": f"{a['slot']}-{b['slot']}", "names": f"{a['name']}/{b['name']}",
               "normal": delta_e(oklab(a["hex"]), oklab(b["hex"]))}  # fmt: skip
        for kind in CVD:
            row[kind] = delta_e(simulate(a["hex"], kind), simulate(b["hex"], kind))
        pairs.append(row)
    worst = {key: min(pairs, key=lambda p: p[key]) for key in ("normal", *CVD)}

    results = []
    out_of_band = [s for s in slots if not low <= s["L"] <= high]
    results.append(_result(
        "lightness band", "FAIL" if out_of_band else "PASS",
        f"OKLCH L {low:.2f}-{high:.2f}" + (": " + ", ".join(f"{s['name']} {s['L']:.3f}" for s in out_of_band) if out_of_band else ""),
    ))  # fmt: skip
    grey = [s for s in slots if s["C"] < CHROMA_FLOOR]
    results.append(_result(
        "chroma floor", "FAIL" if grey else "PASS",
        f"OKLCH C >= {CHROMA_FLOOR:.2f}" + (": " + ", ".join(f"{s['name']} {s['C']:.3f}" for s in grey) if grey else ""),
    ))  # fmt: skip
    for key, floor, failing in (("normal", NORMAL_FLOOR, "FAIL"), ("protan", CVD_FLOOR, "FAIL"),
                                ("deutan", CVD_FLOOR, "FAIL"), ("tritan", CVD_FLOOR, "WARN")):  # fmt: skip
        pair = worst[key]
        status = failing if pair[key] < floor else "PASS"
        detail = f"worst adjacent {pair[key]:.1f} ({pair['names']}), floor {floor:g}"
        if status == "WARN":
            detail += ": relief required, direct labels or the table link"
            if key == "tritan":
                detail += "; at most 4 slots in one chart (D-26)"
        results.append(_result(f"adjacent Delta E, {key}", status, detail))
    dim = [s for s in slots if s["contrast"] < CONTRAST_FLOOR]
    results.append(_result(
        "contrast vs surface", "WARN" if dim else "PASS",
        f">= {CONTRAST_FLOOR:g}:1 on {surface}"
        + (": " + ", ".join(f"{s['name']} {s['contrast']:.2f}" for s in dim)
           + " must carry direct labels or the table link" if dim else ""),
    ))  # fmt: skip
    for key in ("text", "text_secondary"):
        ratio = contrast(block[key], surface)
        results.append(_result(f"{key} contrast", "FAIL" if ratio < TEXT_FLOOR else "PASS",
                               f"{block[key]} on {surface}: {ratio:.2f}:1, floor {TEXT_FLOOR:g}:1"))  # fmt: skip
    for key, floor, what in (("muted", TEXT_FLOOR, "text"), ("other", MARK_FLOOR, "mark")):
        if key in block:
            ratio = contrast(block[key], surface)
            results.append(_result(f"{key} contrast", "FAIL" if ratio < floor else "PASS",
                                   f"{block[key]} on {surface}: {ratio:.2f}:1, {what} floor {floor:g}:1"))  # fmt: skip
    ramp = [oklch(h)[0] for h in block["sequential"]]
    rising = ramp[-1] > ramp[0]
    monotone = all((b > a) if rising else (b < a) for a, b in zip(ramp, ramp[1:]))
    results.append(_result("sequential ramp", "PASS" if monotone else "FAIL",
                           f"{len(ramp)} steps, lightness {'rising' if rising else 'falling'} low to high"
                           + ("" if monotone else ": not monotone")))  # fmt: skip
    dim_status = [k for k in STATUS_KEYS if contrast(block["status"][k], surface) < CONTRAST_FLOOR]
    results.append(_result("status contrast", "WARN" if dim_status else "PASS",
                           ("under 3:1: " + ", ".join(dim_status) + " (icon + label carry them)") if dim_status
                           else "every status colour >= 3:1"))  # fmt: skip
    return {"surface": surface, "slots": slots, "pairs": pairs, "worst": worst, "results": results,
            "relief": [s["name"] for s in dim]}  # fmt: skip


def check(tokens: dict[str, Any]) -> dict[str, Any]:
    """All checks, both modes. `fails` and `warns` count the FAIL and WARN results."""
    validate(tokens)
    modes = {mode: check_mode(tokens[mode], tokens["names"], mode) for mode in MODES}
    statuses = [r["status"] for m in modes.values() for r in m["results"]]
    return {"modes": modes, "fails": statuses.count("FAIL"), "warns": statuses.count("WARN")}


def format_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for mode, data in report["modes"].items():
        lines += [f"## {mode} (surface {data['surface']})", "",
                  "slot  name      hex      L      C      contrast",
                  "----  --------  -------  -----  -----  --------"]  # fmt: skip
        for s in data["slots"]:
            lines.append(f"{s['slot']:<4}  {s['name']:<8}  {s['hex']}  {s['L']:.3f}  {s['C']:.3f}  {s['contrast']:.2f}:1")
        lines += ["", "pair  names            normal  protan  deutan  tritan",
                  "----  ---------------  ------  ------  ------  ------"]  # fmt: skip
        for p in data["pairs"]:
            lines.append(f"{p['pair']:<4}  {p['names']:<15}  {p['normal']:6.1f}  {p['protan']:6.1f}  "
                         f"{p['deutan']:6.1f}  {p['tritan']:6.1f}")  # fmt: skip
        lines.append("")
        for r in data["results"]:
            lines.append(f"{r['status']:<4}  {r['check']}: {r['detail']}")
        lines.append("")
    verdict = "FAIL" if report["fails"] else "PASS"
    lines.append(f"{verdict}: {report['fails']} FAIL, {report['warns']} WARN")
    return "\n".join(lines)


def check_file(path: str | Path) -> dict[str, Any]:
    return check(parse_tokens(token_block(Path(path).read_text(encoding="utf-8"))))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else Path(__file__).resolve().parents[1] / "docs" / "design.md"
    try:
        report = check_file(path)
    except (OSError, TokenError) as exc:
        print(f"FAIL: {path.name}: {exc}")
        return 1
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    print(f"# Palette check: {path.name}\n")
    print(format_report(report))
    return 1 if report["fails"] else 0


if __name__ == "__main__":
    sys.exit(main())
