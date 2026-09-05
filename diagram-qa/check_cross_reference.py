#!/usr/bin/env python3
"""check_cross_reference.py — generic multi-source fact cross-checker.

Catches a defect class no amount of rendering/visual inspection can ever
find: the same fact (e.g. "zone 5 is on GPIO38") duplicated across several
source files that were never mechanically checked against each other — a
YAML config, a diagram generator's hardcoded table, an HTML reference page.
One of them drifts (a copy-paste slip, an edit applied to only one place)
and nothing catches it until a builder wires the wrong pin.

This tool has NO built-in knowledge of any specific project's data shapes
(GPIO numbers, zone numbers, whatever). It is driven entirely by a JSON
config that tells it, per source file, a single regular expression with
NAMED capture groups to pull "records" out of that file's raw text. Every
source's regex must use the same group name for the field you want to
join on (e.g. "zone"); any other shared group names are compared for
agreement across sources.

Usage:
    python check_cross_reference.py <config.json>

Config format
-------------
{
  "join_key": "zone",
  "compare_fields": ["gpio"],
  "sources": [
    {
      "name": "human-readable label, shown in mismatch reports",
      "path": "relative/or/absolute/path/to/file",
      "pattern": "a Python regex with (?P<zone>...) and (?P<gpio>...) named groups",
      "flags": ["DOTALL", "MULTILINE"]   // optional, names from the re module
    },
    ...  // 2 or more sources
  ]
}

Each source's `pattern` is run with re.finditer() against that file's raw
text (no per-format parsing — no YAML/HTML/Python-AST parser involved, on
purpose: these source shapes vary too much project to project for a fixed
parser to stay generic, but they've all been "regular enough to scrape with
a regex" in every case surveyed so far). Every match becomes one record:
{group_name: matched_value, ...}, keyed by that record's `join_key` value.

For every join_key value seen in 2+ sources, the tool compares each
`compare_fields` value across those sources. Any disagreement is reported
with the source name, file path, and approximate line number (computed
from the match's character offset) for all sources holding a value for
that key — including which ones AGREE, so a human can quickly see which
source is the outlier.

A join_key value appearing in only one source is reported as "only found
in" that source — this is not necessarily a bug (maybe that source covers
extra ground the others don't), but it's surfaced so a human can judge.

Exit code is the number of mismatches found (0 = clean).

Example
-------
See examples/ in this folder for a real, working config (built against
the sprinkler-controller project's three-way GPIO/zone duplication).

No external dependencies (uses only json, re, and the stdlib).
"""
import json
import re
import sys


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def load_source(source):
    with open(source["path"], encoding="utf-8") as f:
        text = f.read()
    flags = 0
    for flag_name in source.get("flags", []):
        flags |= getattr(re, flag_name)
    pattern = re.compile(source["pattern"], flags)
    records = []
    for m in pattern.finditer(text):
        records.append({"groups": m.groupdict(), "line": line_of(text, m.start())})
    return records


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    if len(argv) != 1:
        print(__doc__)
        return 1

    with open(argv[0], encoding="utf-8") as f:
        config = json.load(f)

    join_key = config["join_key"]
    compare_fields = config["compare_fields"]
    sources = config["sources"]

    if len(sources) < 2:
        print("Need at least 2 sources to cross-reference.")
        return 1

    # key_value -> source_name -> {field: value, "line": n}
    by_key = {}
    for source in sources:
        name = source["name"]
        records = load_source(source)
        if not records:
            print(f"WARNING: {name} ({source['path']}) matched zero records — check the pattern")
        for rec in records:
            g = rec["groups"]
            if join_key not in g or g[join_key] is None:
                continue
            key_val = g[join_key]
            by_key.setdefault(key_val, {})[name] = {
                field: g.get(field) for field in compare_fields
            } | {"line": rec["line"]}

    mismatches = 0
    all_source_names = [s["name"] for s in sources]

    for key_val in sorted(by_key.keys(), key=lambda k: (len(k), k)):
        present = by_key[key_val]
        missing = [n for n in all_source_names if n not in present]
        if missing:
            print(f"{join_key}={key_val}: only found in {sorted(present.keys())} "
                  f"(missing from {missing})")

        for field in compare_fields:
            values = {name: data[field] for name, data in present.items()}
            distinct = set(v for v in values.values() if v is not None)
            if len(distinct) > 1:
                mismatches += 1
                print(f"{join_key}={key_val}: MISMATCH on '{field}':")
                for name, data in present.items():
                    print(f"    {name} (line {data['line']}): {field}={data[field]!r}")

    if mismatches == 0:
        print(f"\nclean — {len(by_key)} distinct '{join_key}' value(s) checked across "
              f"{len(sources)} source(s), 0 mismatches")
    else:
        print(f"\n{mismatches} mismatch(es) found — fix whichever source is stale, then re-run")
    return mismatches


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
