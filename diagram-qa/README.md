# diagram-qa

Two small, generic, dependency-free Python tools for catching defects in
technical diagrams (SVG wiring diagrams, pinout charts, schematics, etc.)
that manual "render it and eyeball the screenshot" review reliably misses.
Built for and first proven against the `sprinkler-controller` project's
9-diagram build guide, but nothing in either script is specific to that
project — point them at any SVG files / data sources and they work the
same way.

## `check_overlaps.py` — label/shape collision detector

Parses an SVG's `<text>`, `<rect>`, `<line>`, and `<polyline>` elements
and estimates their bounding boxes to find:
- a text label whose box overlaps a `<line>`/`<polyline>` (a wire/trace) —
  a label should never visually sit on top of one
- a text label whose box overlaps a `<rect>` that isn't obviously its own
  container (reported for a human to triage — see Known false positives)
- a text label whose box runs past the SVG's own `viewBox`

```
python check_overlaps.py images/*.svg
python check_overlaps.py path/to/one-diagram.svg
```

Exit code = number of findings (0 = clean). No auto-fix; every finding is
for a human to look at and either fix or dismiss.

### Known false-positive classes (read before treating every finding as a bug)

1. **Long strings vs. the width heuristic.** Text width is estimated as
   `len(text) * font_size * 0.62` (the same heuristic already proven
   against real IBM Plex Sans metrics in `sprinkler-controller`'s
   `build-part3-wiring.py`). For very long captions (100+ characters) this
   estimate can drift a few percent off real rendered width, which is
   sometimes enough to falsely flag a "past the viewBox" finding for text
   that actually renders fine. **Always render and eyeball anything flagged
   as extending past the viewBox before touching the file** — in practice
   about half of these turn out to be real (text genuinely clipped) and
   half are estimate drift. The tool doesn't know which; you have to look.
2. **A label naturally near where a wire originates.** A label sitting
   right next to (not on top of, but bounding-box-adjacent to) the start
   of a line it's labeling will sometimes register as a technical overlap.
   Harmless in practice; dismiss by eye.
3. **A line hidden behind a later-drawn opaque shape.** SVG paints in
   document order — if a `<rect>` is drawn after a `<line>` that happens to
   run underneath it, the line is 100% invisible in the rendered output
   even though its raw coordinates still "overlap" any text drawn on top of
   that rect. This tool only sees coordinates, not paint order, so it will
   flag these. Confirm with an actual render before worrying about it.
4. **Every text-vs-rect overlap is reported**, full stop — the tool has no
   way to know "this text is supposed to be centered inside this labeled
   box" vs. a real collision with an unrelated box. This is deliberate:
   false positives here are cheap to dismiss by eye; a missed real
   collision is the actual risk this tool exists to reduce. One exception
   is built in — a `<rect>` whose bbox exactly matches the file's viewBox
   (a full-canvas background fill) is excluded, since it would otherwise
   trivially "overlap" every single text label in the file for zero signal.

### Limitations

- Only top-level elements are parsed — **no `<g transform>` support**. If
  your SVG groups/transforms elements, this tool's output on it is
  meaningless; add transform handling before trusting it there.
- `<path>` elements (arrows, curves) aren't inspected — a label overlapping
  a `<path>` won't be flagged.
- A polyline's overlap check is done per-segment (each consecutive point
  pair), not on the polyline's overall bounding box — an early version of
  this tool used the overall bbox and it drowned every real finding in
  false positives for any L-shaped or zigzag wire (its bbox covers nearly
  the whole canvas even though the actual line is thin). Per-segment
  checking is the fix; if you extend this tool, don't revert that.

## `check_cross_reference.py` — multi-source fact cross-checker

Catches a completely different defect class: the same fact (e.g. "zone 5
is on GPIO38") duplicated across multiple source files — a config, a
diagram generator's hardcoded table, a reference doc — that have never
been mechanically checked against each other. No rendering or visual
review can ever catch this; only comparing the actual data can.

Fully config-driven — the script has zero built-in knowledge of GPIO
numbers, zones, or any other project-specific concept. You supply a JSON
config naming 2+ source files, each with a regex (named capture groups)
that pulls "records" out of that file's raw text, a shared join key field
name, and which other fields to compare for agreement.

```
python check_cross_reference.py config.json
```

See `examples/sprinkler-controller-cross-ref.json` for a real, working
example (checks zone→GPIO agreement across an ESPHome YAML config, a
Python diagram-generator script, and an HTML reference table — three
completely different file formats, one shared regex-based approach).
Exit code = number of mismatches found (0 = clean).

**Gotcha when hand-writing a config**: a regex like `\d+` needs to be
written as `"\\d+"` in the JSON file (JSON requires doubling a backslash
to represent one literal backslash). If you generate the JSON file via a
shell heredoc, double-check the result — some shells collapse `\\` to `\`
inside a heredoc even with a quoted delimiter, which produces invalid JSON
that fails with a cryptic `Invalid \escape` error. Writing the file with a
real editor (or a tool that writes file contents directly rather than
piping through shell quoting) avoids this.

## What these tools deliberately don't do

- No auto-fix. Both are pure detectors — a human decides what a finding
  means and how (or whether) to fix it.
- No CI/pre-commit wiring. Nothing stops you from adding that later, but
  it wasn't asked for and isn't included.
- `check_cross_reference.py` doesn't parse YAML/HTML/Python properly (no
  `pyyaml`, no `html.parser`, no `ast`) — it's regex-only, by design, so it
  stays dependency-free and works identically across wildly different file
  formats. This means a source file whose relevant structure changes
  significantly (e.g. reformatted YAML indentation) may need its config
  regex updated to match — this is a scraper, not a real parser.

## If you outgrow the after-the-fact cross-reference approach

`check_cross_reference.py` only detects duplication drift after it
happens. If a project's diagrams end up needing frequent regeneration and
the "same fact in three places" problem keeps recurring, look at
[WireViz](https://github.com/wireviz/WireViz) (open-source, generates
wiring diagrams from a single structured YAML spec via GraphViz) — it
fixes this at the root by having exactly one source of truth that both the
diagram and any downstream check are generated from, instead of comparing
N independently-maintained copies after the fact. Not adopted here; worth
knowing about if the problem recurs badly enough to justify adopting a new
diagramming tool.
