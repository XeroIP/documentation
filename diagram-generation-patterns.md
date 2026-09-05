# Diagram generation patterns: WireViz + Graphviz + diagram-qa

Distilled from building out `home-automation/sprinkler-controller`'s wiring
diagrams — five real WireViz diagrams (a full J1/J3 pinout/harness, a
Phase-3 terminal-level wiring diagram, a whole-unit view, a field-wiring
diagram, and a single-zone path), all migrated from or replacing
hand-coordinated SVG. This is the reusable pattern for the next project,
not a sprinkler-controller-specific doc — see that project's
`docs/wireviz/README.md` for the worked, project-specific instance of
everything below.

## Decision matrix: which tool for which diagram

| The diagram shows... | Use | Why |
|---|---|---|
| Real point-to-point wiring — connectors, pins, cables, which wire goes where | **WireViz** | Purpose-built for exactly this. Auto-lays-out connector tables and cable bundles from a YAML spec; correctness follows from the data, not from hand-placed coordinates. |
| A block/flow diagram, state diagram, or decision tree — no physical wires | **Graphviz `dot` directly** | WireViz is a wiring-harness-specific layer on top of Graphviz; skip it when there's no harness, just nodes and edges. Not yet used on sprinkler-controller (its remaining hand-drawn diagrams — `power-chain.svg`, `battery-divider-schematic.svg`, `relay-contact-states.svg`, `esp32-usb-ports.svg`, `ferrule-technique.svg` — are schematic/conceptual/illustrative, not wiring, so none of them were WireViz candidates; `power-chain.svg` specifically was flagged as a `dot` candidate if it's ever revisited). |
| A schematic with real component symbols (resistors, caps, ICs) | **Hand-drawn or a real schematic tool** | Neither WireViz nor plain Graphviz draws schematic symbols. `battery-divider-schematic.svg` (a resistor divider) stayed hand-drawn for exactly this reason. |
| A one-off illustration, physical technique, or annotated photo | **Hand-drawn, or a real photo** | Not a data problem; auto-generation adds nothing. |
| Anything with a numbered build-sequence (Step 1, Step 2...) or "this part is deferred" styling | **Hand-drawn, or accept a flatter WireViz migration** | Neither WireViz nor Graphviz has a concept of sequence callouts or partial/deferred styling. `part3-wiring.svg`'s migration hit this directly — see "What WireViz can't do" below before committing to a migration that needs this. |

Regardless of which generator produces a diagram, run it through
**diagram-qa** (below) before trusting it.

## WireViz

### Setup

```
pip install wireviz pyyaml pillow
```

Plus the Graphviz system binary (WireViz shells out to `dot`, it isn't
bundled):

```
winget install --id Graphviz.Graphviz --silent --accept-package-agreements --accept-source-agreements
```

Make sure `dot.exe` (typically `C:\Program Files\Graphviz\bin`) is on PATH,
or WireViz fails with `ExecutableNotFound: failed to execute WindowsPath('dot')`.

**Windows interpreter fragmentation**: if you have multiple Python
installs, `pip install` and later invocations must use the *same*
interpreter — `python3` on PATH silently resolving to a different install
than the one with `wireviz` installed is a real, previously-hit failure
mode, not a hypothetical one.

### Real gotchas hit building this (in order of how much time each cost)

1. **`pincolors` only accepts a fixed set of 2-letter IEC-style
   abbreviations (BK, WH, GY, PK, RD, OG, YE, OL, GN, TQ, LB, BU, VT, BN,
   BG, IV, SL, CU, SN, SR, GD) — not arbitrary hex codes**, at least as of
   WireViz 0.4.1. A hex value silently produces an empty color swatch
   instead of an error. If a project already has a hex-based role/color
   palette (ours did — `pin_data.py`'s `ROLE` dict), keep a *separate*
   role→abbreviation mapping rather than trying to derive one from the
   other automatically; the two color spaces don't map cleanly.

2. **An unescaped ASCII `->` in any `notes:` or `type:` text breaks
   Graphviz's HTML label parser** with a misleading error
   (`syntax error in line N near '>'` — the arrow is nowhere near line N,
   because WireViz's rendering collapses the label to one physical line).
   Graphviz's HTML-like labels require `<`, `>`, and `&` to be escaped, and
   WireViz's own text handling does **not** escape user-supplied text for
   you. Use the Unicode arrow `→` instead — never ASCII `->` — anywhere
   user text ends up in a `notes:` or `type:` field. Same for literal `<`
   or `&`.

3. **On Windows, run WireViz with `PYTHONUTF8=1` if any text has
   non-ASCII characters** (arrows, em dashes, `·`, Ω, etc.). WireViz's own
   file I/O uses the OS default codepage rather than UTF-8; on Windows
   (cp1252) this crashes with `UnicodeDecodeError: 'charmap' codec can't
   decode byte ...` the moment enough non-ASCII text accumulates in one
   label (a handful of characters may not trigger it; a multi-line notes
   block reliably will). Just always set it:
   `PYTHONUTF8=1 wireviz file.yml` (bash) or `$env:PYTHONUTF8=1` first
   (PowerShell).

4. **`pt` vs `px` when screenshotting a rendered SVG for QA.** WireViz's
   (Graphviz's) SVG output declares `width="Npt" height="Mpt"`, not
   matching the `viewBox` pixel count 1:1. If you size a headless-browser
   window assuming 1 viewBox unit = 1 px, the render comes out visibly
   cropped. Convert: `px = pt × 96 / 72` before choosing a window size.

5. **Connectors have no per-pin free-text field** — only `pins`,
   `pinlabels`, and `pincolors` per row. If your diagram needs to carry
   descriptive text per pin (why a pin is forbidden, what it's wired to,
   a role-color legend), there's no native column for it. The workaround
   used here: put that text in the connector's `notes:` field — a single
   free-text block that WireViz renders as its own row below the pin
   table (`\n` in the YAML becomes its own line via `<br />`). It reads as
   a text block underneath the pins, not aligned per-row, but it's the
   only mechanism WireViz has, and it's a legitimate way to avoid losing
   information a plain pin table can't carry.

6. **`loops:` is the right tool for a daisy-chain** (the same connector's
   pin *N* jumpered to pin *N+1*, repeated) — e.g. a relay board's
   COM1→COM16 bus. `loops: [[1,2],[2,3],[3,4],...]` on a connector renders
   the jumper arcs directly; don't try to model a daisy-chain as N
   separate cables between two different connectors.

7. **A connector pin (or a cable's pin/wire reference) can be a pin
   *number* or its *pinlabel string*, resolved automatically** — but a
   pinlabel with a comma inside parentheses breaks an inline YAML flow
   sequence (`[A (x, y), B]` silently splits into two items at the
   comma). Quote any pinlabel containing a comma, or avoid the comma in
   the label text entirely.

8. **Reusing the same connector pin across multiple cables/connections is
   valid and often the right model** — e.g. a shared GND pin landing two
   separate wires, or (at larger scale) a single "common bus" connector
   pin that 16 different cables all terminate on. WireViz does not
   complain about a pin being referenced more than once across different
   `connections:` entries; it's a normal way to represent a real shared
   node.

9. **`show_pincount: false` is a structural fix for connector-header text
   overflow, not a cosmetic one.** Graphviz auto-sizes an HTML table to
   its widest content; if a long connector-name label collides with an
   auto-generated "N-pin" count string in the same header row, shortening
   the *name* doesn't help — the table just shrinks to match, and the
   relative overlap persists. Removing the pincount text entirely (rather
   than chasing a shrinking target by editing wording) is the fix that
   actually holds.

### Single-source-of-truth pattern

The moment two WireViz files (or a WireViz file and something else — an
ESPHome config, a reference table) both encode the same underlying fact
(which GPIO is which zone, say), you have the exact "duplicated ground
truth" problem this tooling exists to eliminate elsewhere. Sprinkler
controller's answer: one plain-Python data module (`pin_data.py`) holding
the canonical pin/role table, imported by a small generator script that
splices the derived pin list into the otherwise-hand-maintained `.yml`
between marker comments (`# GENERATED:PINS START` / `# GENERATED:PINS
END`). Everything *not* pin data (cable topology, connections) stays
hand-maintained in the same file. This is the same "generated block
inside a hand-edited file" convention as any other project generator —
nothing WireViz-specific about it, just apply it wherever the same fact
would otherwise live in two places.

**When duplication is accepted anyway**: a true whole-system diagram
(sprinkler-controller's `wiring-diagram.svg`) necessarily re-declares most
of the same connectors/pins that more detailed diagrams already carry —
there's no WireViz mechanism to compose multiple `.yml` files into one
render. If a project wants one big-picture diagram *and* several detailed
ones, that duplication has to be a deliberate, reviewed trade (documented
in the big-picture file's own `metadata.source`, naming the detailed files
as the actual source of truth if they ever disagree) — not something to
discover by accident later.

### What WireViz can't do (decide this *before* migrating a hand-drawn diagram)

- No numbered step/sequence callouts.
- No "this part is deferred/future work" visual treatment (dashed lines,
  greyed-out styling) — a WireViz migration of a diagram that leans on
  this will read flatter than the original. Decide explicitly whether
  that's an acceptable trade before starting, not after.
- No mid-diagram floating prose/notes — only per-connector or per-cable
  `notes:` blocks, always rendered in a fixed position (below that
  connector's pin table).
- No schematic component symbols (resistors, capacitors, etc.).

## Graphviz `dot` directly (no WireViz layer)

Not yet exercised on a real project as of this writing, but the natural
next tool for a block/flow/state diagram that isn't a wiring harness.
Same underlying renderer as WireViz, so the same two gotchas apply
directly: HTML-like labels need `<`/`>`/`&` escaped (no automatic
escaping), and non-ASCII text plus Windows' default codepage means
`PYTHONUTF8=1` (or write the `.dot` file with a script that opens files
with `encoding="utf-8"` explicitly, sidestepping the OS-codepage default
entirely).

## Verifying whatever gets generated: diagram-qa

See `diagram-qa/README.md` in this repo for the two tools
(`check_overlaps.py`, `check_cross_reference.py`) and their documented
false-positive classes. Two additions specific to WireViz/Graphviz output,
learned building this:

- Graphviz renders table cells as `<polygon>`, not `<rect>` — a file with
  zero `<rect>` elements is normal for WireViz/Graphviz output, not a sign
  the checker failed to find anything.
- Every text-vs-rect finding where the rect is a connector's own
  containing box, and every adjacent-row text-vs-text finding within a
  cable's or connector's own multi-line table, is expected noise on this
  kind of diagram — triage by rendering and looking, the same as any other
  finding class, but don't be surprised by the volume.

**Always render and look**, even when `check_overlaps.py` comes back
looking clean or looking like 1000 findings of the known classes — a
tool that misses a genuine collision (as this one did, twice, before its
text-vs-text check and transform support existed) is worse than one that
over-reports.
