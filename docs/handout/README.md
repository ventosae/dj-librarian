# Handout

The A6 card a DJ gets with the plugin: the six steps of the first session on the front, the phrases
to say on the back.

| File | What it is |
|---|---|
| `dj-librarian-a6.html` | The source: two A6 pages. The page size comes from its CSS, `@page { size: 105mm 148mm; margin: 0; }`. |
| `fonts.css` | The fonts, embedded as base64 WOFF2 so the card renders offline: Bangers, Comic Neue (regular and bold) and Patrick Hand, all from Google Fonts under the SIL Open Font License 1.1 (openfontlicense.org). The OFL lets you embed and redistribute them; it does not let you sell the fonts on their own. |
| `dj-librarian-a6.pdf` | The print file, 2 pages of 105 × 148 mm. |
| `preview-front.png`, `preview-back.png` | Each page as an image at 3× (1191 × 1678 px), for looking at a change. Rendered locally with the commands below and gitignored, not committed (W-35). |

Change the HTML, then re-render all three outputs and look at both PNGs: no text may run out of
its panel, bubble or box, and the PDF must still have 2 pages.

## Re-render

Headless Microsoft Edge or Google Chrome writes the PDF (`--print-to-pdf`, with
`--no-pdf-header-footer` so no date or URL is printed on the card) and one screenshot of both pages;
ImageMagick 7 (`magick`) cuts the screenshot into the two previews. A scratch `--user-data-dir`
keeps your own browser profile out of it. Run from the repo root.

Windows, in PowerShell (`| Out-Null` makes PowerShell wait for Edge to finish):

```powershell
$edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
$url = 'file:///' + ((Resolve-Path docs/handout/dj-librarian-a6.html).Path -replace '\\', '/')
$tmp = Join-Path $env:TEMP 'djl-handout'; New-Item -ItemType Directory -Force $tmp | Out-Null
& $edge --headless --disable-gpu --user-data-dir="$tmp/profile" --no-pdf-header-footer --print-to-pdf="$PWD/docs/handout/dj-librarian-a6.pdf" $url | Out-Null
& $edge --headless --disable-gpu --user-data-dir="$tmp/profile" --hide-scrollbars --force-device-scale-factor=3 --window-size=397,1119 --virtual-time-budget=3000 --screenshot="$tmp/both.png" $url | Out-Null
magick "$tmp/both.png" -crop 1191x1678+0+0 +repage docs/handout/preview-front.png
magick "$tmp/both.png" -crop 1191x1678+0+1679 +repage docs/handout/preview-back.png
```

macOS, in Terminal (Linux: the same with `chromium` or `google-chrome` as `$chrome`):

```bash
chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
url="file://$PWD/docs/handout/dj-librarian-a6.html"
tmp=$(mktemp -d)
"$chrome" --headless --disable-gpu --user-data-dir="$tmp/profile" --no-pdf-header-footer --print-to-pdf="$PWD/docs/handout/dj-librarian-a6.pdf" "$url"
"$chrome" --headless --disable-gpu --user-data-dir="$tmp/profile" --hide-scrollbars --force-device-scale-factor=3 --window-size=397,1119 --virtual-time-budget=3000 --screenshot="$tmp/both.png" "$url"
magick "$tmp/both.png" -crop 1191x1678+0+0 +repage docs/handout/preview-front.png
magick "$tmp/both.png" -crop 1191x1678+0+1679 +repage docs/handout/preview-back.png
```

Why these numbers: one A6 page is 396.85 × 559.37 CSS px. The window is one page wide and two
pages tall (397 × 1119), so at 3× the screenshot is 1191 × 3357 px and a page is 1678 px tall. The
back page starts on row 1679; row 1678 is the seam between the pages.

`tests/test_handout.py` checks the page size, the 2 pages of the PDF, the card's "Set me up" line
and that this file keeps the commands.
