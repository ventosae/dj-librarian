# Design system

Every HTML page and SVG this tool renders follows this file: the library report
(`reports/<date>-library.html`), the sleeve (`profile/sleeve.svg`) and anything added later.
It is the source for R-408. The colour values live in one machine-readable block at the end of
the [Tokens](#the-token-block) section; `scripts/check_palette.py` validates that block in CI and
`src/dj/design.py` holds the same values for code (a test keeps the two equal).

The idea in one line: the library is the loud part. Everything around it is quiet, thin and
consistent, so a DJ reads the data and not the decoration.

## Pages are self-contained

- One file. Inline CSS, inline SVG, inline JS. No URL anywhere: no web font, no script, no
  image, no stylesheet link, no `@import`. The page opens offline and in Cowork's side panel
  (R-401).
- No chart library. Marks are hand-built SVG; the page's own JS (theme toggle, tooltips, copy
  buttons) stays under 200 lines in total.
- Every string that came from the library is escaped before it reaches the page. Tooltips set
  text with `textContent`, never by building HTML from strings.

## Tokens

Colours are CSS custom properties on `:root`. Markup and SVG use the properties, never a raw
hex (the one exception is the sleeve, which is an object with its own finish; see
[The sleeve](#the-sleeve)).

Both themes are **selected**, not computed: the dark values are their own steps, chosen for the
dark surface, not an inversion of the light ones. The dark theme is **Booth** and is the
default; the light theme is **Day**.

How a page declares them:

```css
:root {
  color-scheme: light;
  --surface: #fcfcfb;  --page: #f9f9f7;
  --text: #0b0b0b;     --text-2: #52514e;  --muted: #6e6d68;  --grid: #e1e0d9;
  --other: #8f8e88;
  --c1: #2a78d6; --c2: #eb6834; --c3: #1baf7a; --c4: #eda100;
  --c5: #e87ba4; --c6: #008300; --c7: #6250d6; --c8: #e34948;
  --good: #0ca30c; --warning: #fab219; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface: #1a1a19;  --page: #0d0d0d;
    --text: #f0efec;     --text-2: #c3c2b7;  --muted: #898781;  --grid: #2c2c2a;
    --other: #6b6a65;
    --c1: #3987e5; --c2: #d95926; --c3: #199e70; --c4: #c98500;
    --c5: #d55181; --c6: #008300; --c7: #9085e9; --c8: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  /* the same dark values again */
}
body { background: var(--page); color: var(--text); }
```

Why twice: the media query follows the operating system when the page carries no theme; the
`data-theme` rule follows the toggle. The `:not([data-theme="light"])` guard lets a Day choice
win over a dark OS, and `:where()` keeps the media rule weaker than the toggle rule.

The theme toggle sits in the page header: two buttons, **Booth** and **Day**, that set
`data-theme` on `<html>`. The page ships with `data-theme="dark"`. The choice is remembered in
`localStorage` inside `try`/`catch` (a private window may refuse storage; the page still works).
A `#booth` or `#day` in the URL wins over the stored choice, which is how the screenshots pick a
theme. `body` always has an explicit background, so nothing shows through in either theme.

### Surfaces and ink

| Role | Day (light) | Booth (dark) |
|---|---|---|
| Page plane | `#f9f9f7` | `#0d0d0d` |
| Card / chart surface | `#fcfcfb` | `#1a1a19` |
| Text | `#0b0b0b` | `#f0efec` |
| Secondary text | `#52514e` | `#c3c2b7` |
| Muted (axis, ticks) | `#6e6d68` | `#898781` |
| Grid hairline | `#e1e0d9` | `#2c2c2a` |
| Other (lanes outside the 4 biggest, unowned band) | `#8f8e88` | `#6b6a65` |

### Categorical: eight slots in a fixed order

| Slot | Hue | Day | Booth |
|---|---|---|---|
| 1 | blue | `#2a78d6` | `#3987e5` |
| 2 | orange | `#eb6834` | `#d95926` |
| 3 | aqua | `#1baf7a` | `#199e70` |
| 4 | yellow | `#eda100` | `#c98500` |
| 5 | magenta | `#e87ba4` | `#d55181` |
| 6 | green | `#008300` | `#008300` |
| 7 | violet | `#6250d6` | `#9085e9` |
| 8 | red | `#e34948` | `#e66767` |

- The order is part of the colour-blind safety: neighbours were chosen to stay apart. Never
  reorder, never skip, never cycle.
- A slot belongs to a thing, not a rank. **Slots are assigned once, by lane size, in
  `profile/identity.json`** (Q-30, D-27; `dj.analysis.identity`): the 4 lanes with the most
  tracks get a colour (ties: the slower lane, then the label), and those four take slots 1-4 in
  BPM order, the slowest of them slot 1. Size picks which lanes are coloured; BPM picks which
  colour, so the biggest lane is not blue by rank. Every other lane is **Other** (`--other`,
  `slot: null`). Every chart (the sleeve, the crate wall, a mini sleeve, any legend) reads the
  slot from `identity.json` and never re-assigns it per chart. A lane keeps its slot in every
  chart on the page; filtering or sorting never repaints a lane.
- **At most 4 colours in one chart** (D-26, Q-29): `identity.json` colours 4 lanes at most, so
  no chart draws a fifth. A legend counts the grey lanes in its Other key ("Other (2 lanes)");
  the tooltip still names the lane, and a sleeve lane note in the grey says it after the BPM
  ("126-127 BPM · Other"). So yellow (slot 4) and magenta (slot 5), the light-mode tritan pair,
  never sit side by side in one chart. Code: `dj.design.MAX_SLOTS_PER_CHART` is the cap and
  `dj.design.chart_slot` the guard every chart applies to the slot it reads (anything that is
  not 1-4 draws as Other). An `identity.json` written before Q-30 (slots 1-8 by BPM) still
  draws 4 colours at most, but its grey lanes are the fastest, not the smallest, so the page
  then says only that a chart colours four lanes at most and how to colour the four biggest
  ("draw my sleeve"), never "only your four biggest lanes get a colour".
- A proposal's mini sleeve uses the same slots: a branch of the proposed tree wears the slot of
  the lane that fills most of it, a tempo band the slot of the branch it lands in. Two branches
  never share a lane (the one that takes more of the lane keeps it); a branch filled most by an
  Other lane, a branch without a lane, or one that lost its lane that way, is Other. So a colour
  names the same lane on every chart.
- A bar coloured by something other than its own lane (a crate-wall row wears its folder's
  main lane) says so in the legend, and its tooltip names its own lane too.
- A chart with one series uses slot 1 and no legend box (its title says what it shows),
  unless a slot already names a lane on the page. A chart that highlights a subset draws it in
  `--text` and the rest in `--other` (the six axes).

### Sequential: one blue ramp

Magnitude (how much) is one hue, light to dark: `#cde2fb` `#b7d3f6` `#9ec5f4` `#86b6ef`
`#6da7ec` `#5598e7` `#3987e5` `#2a78d6` `#256abf` `#1c5cab` `#184f95` `#104281` `#0d366b`.
On Day, low values take the light end; on Booth the ramp runs the other way so low values sink
into the dark surface. Never a rainbow, never a second hue for "more".

### Status

Three states, reserved: good `#0ca30c`, warning `#fab219`, critical `#d03b3b`, the same in both
themes. A status colour always comes with an icon (✓, !, ×) and a word ("good", "check",
"broken"), never alone, and is never used as a series colour. When a value means good or bad
(a dump, a dead playlist) it wears a status; when it is just "lane 4" it wears its slot.

### The token block

`scripts/check_palette.py` reads this block, and only this one. Hexes are quoted; `names` are
the slot hues in order; `sequential` runs low to high for that theme.

```yaml
tokens:
  names: [blue, orange, aqua, yellow, magenta, green, violet, red]
  light:
    surface: "#fcfcfb"
    page: "#f9f9f7"
    text: "#0b0b0b"
    text_secondary: "#52514e"
    muted: "#6e6d68"
    grid: "#e1e0d9"
    other: "#8f8e88"
    categorical: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
    sequential: ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
    status:
      good: "#0ca30c"
      warning: "#fab219"
      critical: "#d03b3b"
  dark:
    surface: "#1a1a19"
    page: "#0d0d0d"
    text: "#f0efec"
    text_secondary: "#c3c2b7"
    muted: "#898781"
    grid: "#2c2c2a"
    other: "#6b6a65"
    categorical: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
    sequential: ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"]
    status:
      good: "#0ca30c"
      warning: "#fab219"
      critical: "#d03b3b"
```

## Marks

- **Thin.** Bars are at most 24 px thick and never fill their slot; the leftover is air.
- **Ends.** A bar grows from one baseline, square at the baseline and rounded 4 px at its
  data end.
- **Gaps, not borders.** Touching fills (stacked segments, adjacent bars, fingerprint cells)
  are separated by a 2 px gap in the surface colour. No outline is drawn around a mark.
- **Lines** are 2 px with round joins; **markers** are at least 8 px across, with a 2 px ring
  in the surface colour where they cross something.
- **Labels are sparing.** Direct labels on at most 4 marks per chart: the end, the extreme,
  the one the story is about. Never a number on every point; the tooltip and the table carry
  the rest.
- **One axis per chart.** Never two scales on one plot. The grid is a recessive 1 px solid
  hairline (`--grid`), never dashed.
- **Text wears text tokens** (`--text`, `--text-2`, `--muted`), never the series colour.
  Identity comes from a swatch, a dot or a line key next to the text.
- **Legend** for two or more series, always, in slot order. Direct labels supplement it.

## Interaction

- Every mark has a hover tooltip, and the same tooltip on keyboard focus (`tabindex="0"` on
  the hit area). The value leads, the name follows.
- The hit target is bigger than the mark: an invisible rect or a wider stroke around it, at
  least 24 px in its short direction. Where marks sit closer than that, it reaches halfway to
  the neighbour and never covers another mark.
- A chart is drawn in a viewBox about as wide as it shows, so its text keeps the sizes below
  (a 13 px label stays near 13 px); a sleeve drawn small leaves out its small print.
- Tooltips enhance, they never gate: every value is also in a direct label or in the table.
- Each chart has a **table** link to the MD or JSON file it was drawn from (for example
  `structure/analysis.md`, `profile/identity.json`), next to its title. That link is also the
  relief channel for slots under 3:1 contrast and for the tritan pair (see Validation).
- Copy buttons (trigger prompts) copy plain text and say "Copied" for a moment; without
  clipboard access the text stays selectable.

## Typography

No font file and no font URL. Everything uses the system stack:

```css
font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
```

Size, weight and letter-spacing do the work:

| Use | Size | Weight | Letter-spacing |
|---|---|---|---|
| Hero handle (the DJ's name) | 56-96 px, scaled to fit | 900 | -0.04em |
| Section heading | 22 px | 700 | -0.01em |
| Body | 16 px, line height 1.5 | 400 | normal |
| Stat value | 28 px (22 px in the hero's 3 + 2 grid) | 700 | -0.02em |
| Labels, captions | 13 px | 500 | 0.01em |
| Small caps line (header, kicker) | 12 px, uppercase | 600 | 0.12em |

Big standalone numbers use proportional figures; `font-variant-numeric: tabular-nums` only
where numbers line up in a column. A long name scales down, then wraps; it never overflows or
gets clipped.

## Layout

- Wide screens: content up to 1100 px; cards side by side where the brief says so.
- Phone width: 16 px side gutters, one column, no horizontal scroll.
- Print: one column, the Day theme, no toggle, no sticky footer.

## The sleeve

`profile/sleeve.svg` (dj-identity, R-1403) is an object, like a record sleeve on a table: it
keeps its dark finish in both themes and colours its lanes with the **Booth** slot values. It
follows the same rules otherwise: the lane slots of `profile/identity.json` (the 4 biggest lanes
in colour, the rest Other; its lane notes are the three biggest lanes, so always in colour from W-32 on; an older
identity.json can leave one grey, marked Other), text
in the dark text tokens, a 2 px gap between cells, no URL, no script, no
font file, every id prefixed so several sleeves can sit in one page.

- Each ring is named (its decade) along one spoke: the middle of the BPM band with the fewest
  tracks (so the labels hide the least) among the bands within 45 degrees of the top or the
  bottom, so the labels, which run along the rings, are never turned more than 45 degrees from
  level; kept upright, haloed in the record's black. The oldest and the newest are always named,
  and every ring when the room allows (two rings at the thinnest, side by side, are 28 units
  apart centre to centre, the label pitch). The labels are 26 units tall: the report hero draws
  the sleeve about 456 px wide on a 1100 px page, so they render at about 12 px. Where the hero
  draws it narrower (a two-column hero at mid width, a phone), the report's CSS raises them so
  they stay at least 11 px down to a 360 px phone (`dj.report.decade_css`).
- Small collections still read as a full record: no ring is drawn thinner than 26 units (about
  12 px in the hero); an empty cell is a faint groove on every ring; and in a ring that holds
  fewer than 3 tracks the empty cells are one dim step lighter, which the caption and the
  cell's tooltip say. A cell with tracks is never lifted: the brighter the cell, the more
  tracks, on every ring.

## Validation

`scripts/check_palette.py` (stdlib only) reads the token block above and checks each theme:

| Check | Rule | Result when broken |
|---|---|---|
| Lightness band | each slot's OKLCH L in 0.43-0.77 (Day) or 0.48-0.67 (Booth) | FAIL |
| Chroma floor | each slot's OKLCH C at least 0.10 | FAIL |
| Normal vision | every adjacent slot pair Delta E at least 15 | FAIL |
| Protanopia, deuteranopia | every adjacent pair, simulated, Delta E at least 8 | FAIL |
| Tritanopia | every adjacent pair, simulated, Delta E at least 8 | WARN |
| Contrast | each slot against its surface at least 3:1 | WARN |
| Text | text and secondary text against the surface at least 4.5:1 | FAIL |
| Muted | muted text (ticks, axis units, small print) against the surface at least 4.5:1 | FAIL |
| Other | the Other grey, a mark colour (uncoloured lanes, unowned band, the quiet axes), against the surface at least 3:1 | FAIL |
| Sequential | the ramp's lightness strictly monotone | FAIL |
| Status | each status colour against the surface at least 3:1 | WARN |

Delta E is the straight-line distance in OKLab, times 100. Colour vision deficiency is
simulated with the Machado, Oliveira and Fernandes (2009) matrices at full severity, applied to
linear sRGB. "Adjacent" means slot n and slot n+1: on the charts here only neighbours touch.

```text
uv run python scripts/check_palette.py docs/design.md
```

It prints a table per theme and exits 0 when nothing FAILs, 1 otherwise. CI runs it on every
push.

What it reports for this palette, and what that obliges:

- Normal vision: worst adjacent pair 19.6 (Day) and 19.3 (Booth). Protan and deutan: worst
  9.1 (Day) and 8.4 (Booth). All pass.
- **Tritanopia is a WARN, by decision (W-31).** On Day the yellow / magenta pair (slots 4 and
  5) measures about 5.8 under simulated tritanopia, and green / violet (slots 6 and 7) about
  7.6; on Booth every adjacent pair clears 8 (worst about 8.7, yellow / magenta). The
  colour method this palette comes from gates protan and deutan, and its thresholds are
  calibrated to those two simulations; tritanopia is rare and the fixed palette cannot clear
  it on Day without changing the brief's hexes. So the checker reports it and every chart that
  seats slots 4 and 5 (or 6 and 7) side by side carries relief: direct labels, or the table
  link (every chart here has one). **Accepted (D-26, Q-29):** tritan stays a WARN with relief,
  never a FAIL, and the relief includes the 4-slot cap: no chart shows slot 5 (magenta), so the
  yellow / magenta pair never meets in one chart; green / violet (slots 6 and 7) never shows
  either.
- Contrast: on Day, aqua, yellow and magenta sit under 3:1 on the surface. A chart that uses
  them carries direct labels or the table link (again: every chart here has the link).
- Muted and Other: Day muted is `#6e6d68` (5.1:1) and Day Other `#8f8e88` (3.2:1); Booth muted
  `#898781` (4.9:1) and Booth Other `#6b6a65` (3.2:1). All pass.

## Anti-patterns

Refuse these in review:

- Two y-axes on one chart. Use two charts, or index both series to one base.
- A pie or donut with more than 3 slices. Use a bar.
- A rainbow, or any multi-hue ramp, for magnitude.
- Colour as the only identity: a series needs a legend entry or a direct label too.
- A number on every point.
- Colours by rank (the biggest lane gets blue): size picks which 4 lanes get a colour, BPM order
  picks which colour, and the lane keeps it on every chart.
- A hue at the midpoint of a diverging scale: the midpoint is grey.
- A ninth generated hue, or slots reused or cycled: lanes outside the four biggest are Other (D-27).
- A fifth colour in one chart (D-26), or slots re-assigned per chart: they come from
  `identity.json`, 4 at most (D-27).
- A status colour used as a series, or a series colour used for status.
- Text in the series colour; dashed gridlines; outlines around marks.
- A web font, an external script or image, any `http` reference.

## Design checklist

Copy into the PR description and tick each line:

```markdown
- [ ] Colours only through the tokens of docs/design.md; `uv run python scripts/check_palette.py docs/design.md` passes.
- [ ] Booth (default) and Day both render; the toggle works; `body` has an explicit background.
- [ ] Each lane keeps its `identity.json` slot in every chart; slots never cycle; the 4 biggest lanes in colour, the rest "Other".
- [ ] Thin marks, 2 px surface gaps, at most 4 direct labels per chart, one axis per chart.
- [ ] Every chart: legend for 2+ series, hover and focus tooltip, a table link to its MD/JSON file.
- [ ] Text in text tokens, never in a series colour; status only with icon + label.
- [ ] No URL of any kind in the page; no font file; inline JS under 200 lines.
- [ ] Phone width: 16 px gutters, no horizontal scroll. Print: one column, Day.
- [ ] docs/samples screenshots are current (R-409).
```
