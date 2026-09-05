#!/usr/bin/env python3
"""check_overlaps.py — generic SVG label/shape collision detector.

Catches the class of bug that a fixed-zoom screenshot review can miss: a
text label whose bounding box overlaps a line, polyline, or rectangle it
wasn't meant to sit on top of, or that runs past the SVG's own viewBox.
Rendering the SVG and eyeballing it doesn't scale — every zoom level and
screen size hides some overlaps and exaggerates others; this checks the
actual coordinates instead.

This tool has NO knowledge of any specific project — it only understands
SVG geometry. It works on <text>/<rect>/<polygon>/<line>/<polyline>
elements, including ones nested inside <g transform="..."> groups
(translate/scale/rotate/matrix are composed correctly down the tree — this
matters in practice: Graphviz-generated SVGs, including WireViz's output,
always wrap their whole drawing in one top-level translate, AND render
every table cell as a <polygon> rather than a <rect> — a file with zero
<rect> elements is normal for that kind of SVG, not a sign the parse
failed). See Limitations below for what's still not handled.

Usage:
    python check_overlaps.py <file.svg> [<file2.svg> ...]
    python check_overlaps.py images/*.svg

Exit code is the number of findings (0 = clean), so it can be used as a
pass/fail gate in a script or CI step without any extra plumbing.

How it works
------------
Text bounding box: width is estimated as
    len(text) * font_size * WIDTH_FACTOR
This constant (0.62) is the same heuristic already proven against real
IBM Plex Sans metrics in a sibling project's diagram generator (see
sprinkler-controller/docs/build-part3-wiring.py's tag() helper) — dropped
its "+14" term there since that was padding for a pill-shaped tag
background, not applicable to freeform text. Height is estimated as
font_size * HEIGHT_FACTOR (1.2), a standard line-height approximation.
text-anchor="middle"/"end" is honored when estimating the box's x-origin.

Shape bounding boxes come directly from each element's own coordinates.
<line>/<polyline> get a small pad (STROKE_PAD, default 2px) on all sides
since a zero-width line and a zero-width text box would otherwise never
register as touching even when they visually cross.

A text box is flagged if:
  - it overlaps another, different text box (see below — this is the
    highest-confidence check: two labels sitting on top of each other, like
    a connector's type description running into its pin-count column, is
    essentially never intentional), or
  - it overlaps a <line> or <polyline> at all (these are wires/traces —
    a label should never sit directly on top of one; see Limitations for
    why this specific check is low-value on Graphviz output), or
  - it overlaps a <rect>/<polygon> that is not its own "container" (see
    Limitations: this tool does not know which shape a text label "belongs
    to", so it reports ALL text-vs-shape overlaps and expects a human to
    triage true negatives, e.g. a label deliberately centered in its own
    box or table cell).

Limitations (read before assuming a clean run means a clean diagram)
---------------------------------------------------------------------
- A <rect> whose bbox exactly matches the file's viewBox (a full-canvas
  background fill) is excluded from the text-vs-rect check — every text in
  the file would trivially "overlap" it otherwise, which is noise, not a
  real ambiguity. Any OTHER rect, including large section-background boxes,
  is still checked, per the point below.
- `<g transform>` support covers translate, scale, rotate (including
  rotation about a center point), and raw matrix() — composed correctly
  through arbitrarily nested groups. skewX/skewY are NOT supported (rare
  in generated diagrams) and are silently treated as identity, which will
  produce wrong results for a skewed element specifically.
- Text width is an estimate, not exact glyph metrics — it will not catch a
  wrap/overflow that's within a few pixels of the threshold either way; it
  reliably catches overlaps a fixed-zoom screenshot review would also miss,
  which is the actual goal.
- <path> elements (arrows, curves) are not inspected at all — only
  <line>/<polyline>. A label overlapping a <path> won't be flagged. This
  makes the <line>/<polyline> check specifically LOW-VALUE on Graphviz/
  WireViz output: Graphviz draws actual wire/edge routing as <path> curves,
  so the only <line>/<polyline> elements in that kind of SVG are table-cell
  grid borders — every pin-role label in a WireViz connector table will
  trivially "overlap" its own cell's border rule, producing a wall of
  findings that are all the same false-positive (confirmed by rendering
  and looking — text sitting normally inside its own cell). If most of
  your findings are text-vs-line and the file is Graphviz-generated,
  suspect this class first before triaging each one by hand.
- Every text-vs-rect overlap is reported, including ones a human would call
  "correct" (a label properly centered in its own labeled box). This is
  deliberate: false positives here are cheap to dismiss by eye; false
  negatives (a missed real collision) are the actual risk. Don't try to
  "fix" this by adding a same-rect exclusion without a robust way to know
  which rect a label belongs to — that would risk hiding a real bug.

No external dependencies.
"""
import re
import sys
import glob
import math
import xml.etree.ElementTree as ET

WIDTH_FACTOR = 0.62
HEIGHT_FACTOR = 1.2
STROKE_PAD = 2.0

NS = {"svg": "http://www.w3.org/2000/svg"}


def local_tag(elem):
    return elem.tag.split("}")[-1]


def _f(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)  # (a, b, c, d, e, f): x'=a*x+c*y+e, y'=b*x+d*y+f


def mat_multiply(m1, m2):
    """m1 ∘ m2 — apply m2 first, then m1 (matches SVG's left-to-right
    transform-list semantics, where each subsequent transform acts in the
    coordinate system established by the ones before it)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1,
    )


def apply_matrix(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def parse_transform(s):
    """Parse an SVG transform attribute into one composed 2x3 matrix.
    Supports translate/scale/rotate(incl. about a center point)/matrix.
    skewX/skewY are not supported and are treated as identity (see
    module docstring's Limitations section)."""
    m = IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", args)]
        if name == "translate":
            tx = nums[0] if nums else 0.0
            ty = nums[1] if len(nums) > 1 else 0.0
            step = (1, 0, 0, 1, tx, ty)
        elif name == "scale":
            sx = nums[0] if nums else 1.0
            sy = nums[1] if len(nums) > 1 else sx
            step = (sx, 0, 0, sy, 0, 0)
        elif name == "rotate":
            if not nums:
                continue
            ang = math.radians(nums[0])
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            rot = (cos_a, sin_a, -sin_a, cos_a, 0, 0)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                step = mat_multiply(mat_multiply((1, 0, 0, 1, cx, cy), rot), (1, 0, 0, 1, -cx, -cy))
            else:
                step = rot
        elif name == "matrix" and len(nums) == 6:
            step = tuple(nums)
        else:
            continue  # skewX/skewY/unrecognized — identity (see Limitations)
        m = mat_multiply(m, step)
    return m


def transformed_bbox(m, x0, y0, x1, y1):
    """Transform all 4 corners of a local-space rect through m and return
    the axis-aligned bbox of the result — correct even under rotation,
    unlike transforming just two opposite corners."""
    corners = [apply_matrix(m, x0, y0), apply_matrix(m, x1, y0), apply_matrix(m, x1, y1), apply_matrix(m, x0, y1)]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def text_bbox(elem, m):
    x = _f(elem.get("x"))
    y = _f(elem.get("y"))
    size = _f(elem.get("font-size"), 12.0)
    anchor = elem.get("text-anchor", "start")
    content = "".join(elem.itertext())
    width = len(content) * size * WIDTH_FACTOR
    height = size * HEIGHT_FACTOR
    if anchor == "middle":
        x0 = x - width / 2
    elif anchor == "end":
        x0 = x - width
    else:
        x0 = x
    # y is the text baseline; approximate the box as sitting above it
    y0 = y - height
    tx0, ty0, tx1, ty1 = transformed_bbox(m, x0, y0, x0 + width, y0 + height)
    return (tx0, ty0, tx1, ty1, content)


def rect_bbox(elem, m):
    x = _f(elem.get("x"))
    y = _f(elem.get("y"))
    w = _f(elem.get("width"))
    h = _f(elem.get("height"))
    return transformed_bbox(m, x, y, x + w, y + h)


def polyline_segment_bboxes(points_attr, m, pad=STROKE_PAD):
    """One bbox per consecutive point-pair, NOT one bbox for the whole
    polyline. A polyline's overall min/max bounding box hugely
    over-approximates an L-shaped or zigzag wire — e.g. a wire that runs
    down the left edge, across the bottom, and up the right edge has a
    bounding box covering nearly the entire canvas, even though the actual
    line only occupies a thin path through it. Per-segment bboxes track
    the real geometry instead and avoid that false-positive flood."""
    coords = re.findall(r"-?\d+(?:\.\d+)?", points_attr or "")
    nums = [float(n) for n in coords]
    xs = nums[0::2]
    ys = nums[1::2]
    points = [apply_matrix(m, x, y) for x, y in zip(xs, ys)]
    boxes = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        boxes.append((min(x1, x2) - pad, min(y1, y2) - pad, max(x1, x2) + pad, max(y1, y2) + pad))
    return boxes


def line_bbox(elem, m, pad=STROKE_PAD):
    x1, y1 = apply_matrix(m, _f(elem.get("x1")), _f(elem.get("y1")))
    x2, y2 = apply_matrix(m, _f(elem.get("x2")), _f(elem.get("y2")))
    return (min(x1, x2) - pad, min(y1, y2) - pad, max(x1, x2) + pad, max(y1, y2) + pad)


def polygon_bbox(points_attr, m):
    """Graphviz's HTML-like <table> labels (used for WireViz connector/cable
    boxes) render every cell as a <polygon>, not a <rect> — a diagram with
    zero <rect> elements is normal for Graphviz output, not a parse failure.
    Treated identically to a rect for overlap purposes: axis-aligned bbox of
    all points after transform."""
    coords = re.findall(r"-?\d+(?:\.\d+)?", points_attr or "")
    nums = [float(n) for n in coords]
    xs = nums[0::2]
    ys = nums[1::2]
    if not xs:
        return None
    points = [apply_matrix(m, x, y) for x, y in zip(xs, ys)]
    pxs = [p[0] for p in points]
    pys = [p[1] for p in points]
    return (min(pxs), min(pys), max(pxs), max(pys))


def overlaps(a, b):
    ax0, ay0, ax1, ay1 = a[:4]
    bx0, by0, bx1, by1 = b[:4]
    return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0


def parse_viewbox(root):
    vb = root.get("viewBox")
    if not vb:
        return None
    parts = [float(p) for p in vb.replace(",", " ").split()]
    if len(parts) != 4:
        return None
    x, y, w, h = parts
    return (x, y, x + w, y + h)


def check_file(path):
    findings = []
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        return [f"{path}: XML PARSE ERROR: {e}"]
    root = tree.getroot()

    texts, rects, lines = [], [], []

    def walk(elem, m):
        local_m = m
        t = elem.get("transform")
        if t:
            local_m = mat_multiply(m, parse_transform(t))
        tag = local_tag(elem)
        if tag == "text":
            texts.append(text_bbox(elem, local_m))
            return  # text children (tspans) are covered by itertext() already
        elif tag == "rect":
            rects.append(rect_bbox(elem, local_m))
        elif tag == "polygon":
            bb = polygon_bbox(elem.get("points"), local_m)
            if bb:
                rects.append(bb)
        elif tag == "line":
            lines.append(line_bbox(elem, local_m))
        elif tag == "polyline":
            lines.extend(polyline_segment_bboxes(elem.get("points"), local_m))
        for child in elem:
            walk(child, local_m)

    walk(root, IDENTITY)

    viewbox = parse_viewbox(root)

    # A rect spanning the full viewBox is almost always a page-background
    # fill, not a "container" any text is meaningfully inside/outside of —
    # every text in the file would trivially "overlap" it, which is pure
    # noise rather than a real ambiguity for a human to triage. Drop it.
    if viewbox:
        EPS = 1.0
        rects = [
            r for r in rects
            if not (abs(r[0] - viewbox[0]) < EPS and abs(r[1] - viewbox[1]) < EPS
                    and abs(r[2] - viewbox[2]) < EPS and abs(r[3] - viewbox[3]) < EPS)
        ]

    for t in texts:
        tx0, ty0, tx1, ty1, content = t
        if viewbox and (tx0 < viewbox[0] or ty0 < viewbox[1] or tx1 > viewbox[2] or ty1 > viewbox[3]):
            findings.append(
                f"{path}: text {content!r} bbox ({tx0:.0f},{ty0:.0f},{tx1:.0f},{ty1:.0f}) "
                f"extends past viewBox {viewbox}"
            )
        for r in rects:
            if overlaps(t, r):
                findings.append(
                    f"{path}: text {content!r} overlaps a <rect> at "
                    f"({r[0]:.0f},{r[1]:.0f},{r[2]:.0f},{r[3]:.0f}) — verify this is the label's own box"
                )
        for l in lines:
            if overlaps(t, l):
                findings.append(
                    f"{path}: text {content!r} overlaps a <line>/<polyline> at "
                    f"({l[0]:.0f},{l[1]:.0f},{l[2]:.0f},{l[3]:.0f})"
                )

    # Text-vs-text: two DIFFERENT labels overlapping each other has no
    # "this is the label's own container" ambiguity the way text-vs-shape
    # does, so a finding here is much more likely to be a real bug — subject
    # still to the same width-estimate imprecision noted in the docstring
    # (rare, but two labels that just barely touch may be a heuristic
    # overestimate rather than a true collision — still worth a quick look).
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if overlaps(a, b):
                findings.append(
                    f"{path}: text {a[4]!r} overlaps text {b[4]!r} "
                    f"(bboxes ({a[0]:.0f},{a[1]:.0f},{a[2]:.0f},{a[3]:.0f}) and "
                    f"({b[0]:.0f},{b[1]:.0f},{b[2]:.0f},{b[3]:.0f}))"
                )

    return findings


def main(argv):
    # Windows consoles often default to a legacy codepage (cp1252 etc.) that
    # can't encode diagram text containing Ω, em-dashes, or other non-ASCII
    # characters — force UTF-8 on stdout so a finding never crashes the run.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    if not argv:
        print(__doc__)
        return 1
    files = []
    for pattern in argv:
        matched = glob.glob(pattern)
        files.extend(matched if matched else [pattern])

    total = 0
    for path in files:
        findings = check_file(path)
        for f in findings:
            print(f)
        total += len(findings)

    if total == 0:
        print(f"clean — {len(files)} file(s) checked, 0 findings")
    else:
        print(f"\n{total} finding(s) across {len(files)} file(s) — triage each by eye before dismissing")
    return total


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
