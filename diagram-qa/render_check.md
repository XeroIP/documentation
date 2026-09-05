# Render-check checklist

A repeatable, mostly-manual checklist for the parts of diagram QA that
aren't worth scripting — visual triage and picking which diagrams matter
most don't reduce to a deterministic pass/fail the way `check_overlaps.py`
and `check_cross_reference.py` do. Run this once per diagram (or per batch
of diagrams) after any edit, in addition to the two scripts in this folder.

## 1. Font-corrected render (do this first)

Standalone SVG files that reference a web font (e.g.
`font-family="'IBM Plex Sans', sans-serif"`) have no `@font-face`/webfont
import of their own — that only exists in the HTML pages that embed them.
Rendering the bare `.svg` file directly in a headless browser silently
falls back to a generic sans-serif, which has different letter widths than
the real font. **Any render taken this way is measuring the wrong font**,
and a close-call label that's fine in the real font might look clipped (or
vice versa) in the fallback.

Fix: wrap the target SVG in a tiny local HTML file that pulls in the same
font the real page uses, then screenshot the HTML wrapper instead of the
bare `.svg`:

```html
<!doctype html>
<html><head>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>body{margin:0}</style>
</head><body>
<img src="file:///ABSOLUTE/PATH/TO/diagram.svg">
</body></html>
```

(Match the actual `<link>` tag from whatever page embeds the diagram —
the snippet above is what `sprinkler-controller`'s pages use.)

Then, e.g. with headless Chrome:
```
chrome.exe --headless --disable-gpu --screenshot=out.png --window-size=W,H file:///path/to/wrapper.html
```
Pick `--window-size` a bit larger than the SVG's `viewBox` dimensions.

## 2. Structural validation (cheap, run on every file)

- `xmllint --noout <file>.svg` — well-formedness with precise line/column
  errors (better than a bare `ElementTree.parse`, no extra dependency
  beyond having `xmllint` on PATH — ships with Strawberry Perl on Windows,
  or `libxml2-utils` on Debian/Ubuntu).
- `inkscape <file>.svg --export-type=png --export-filename=<tmp>.png` — a
  second, independent SVG parser/renderer (Inkscape). Anything it errors
  on that `xmllint`/`ElementTree` didn't is worth a look.
- `npx svglint <file>.svg` — an actual rule-based linter (unlike `svgo`,
  which only minifies). Start with its default rule set; add a project
  `.svglintrc` later only if a specific recurring issue justifies one.

## 3. Cross-renderer diff (highest-stakes diagrams only — this is expensive per-file, don't do all of them)

For the 1-2 diagrams where an error would be most costly (e.g. the one a
builder is most likely to wire straight off of), render the same
font-corrected wrapper in a second engine (Firefox: `firefox --headless
--screenshot=out2.png file:///path/to/wrapper.html`) and diff the two
screenshots with Pixelmatch instead of eyeballing both side by side:
```
npx pixelmatch chrome.png firefox.png diff.png
```
A non-trivial diff image usually means a font-metric or kerning
difference that shifted something right up to (or past) an edge —
worth a manual look at `diff.png` to see exactly where.

## 4. Contrast pass (optional, cheap, worth doing at least once)

```
npx pa11y file:///path/to/wrapper.html
```
Flags WCAG contrast failures. Muted background tints (a pale color used as
a label's background fill) against colored text is exactly where this
kind of bug tends to hide, and nothing else in this checklist checks for
it.

## 5. Manual fact spot-checks

For anything a diagram states as a fact that also appears in a reference
table elsewhere (a wire color legend, a fuse rating, a resistor value) but
isn't worth writing a `check_cross_reference.py` config for (a short,
stable table, unlikely to drift) — just read them side by side once. Not
every fact-duplication needs scripting; use judgment.
