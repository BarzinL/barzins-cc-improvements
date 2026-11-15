#!/usr/bin/env python3
"""Check a local compiled reference: every claim says where it came from and how
well it was checked.

A reference is a directory (default `docs/reference`) holding `INDEX.md` and entry
files in Markdown. In an entry, every claim is a list item under the `## Claims`
heading and ends with one tag:

    - The stored double for 0.1 is 3602879701896397 / 2**55.
      [src: https://docs.python.org/3/tutorial/floatingpoint.html | read: 2026-11-14 | status: source | loc: §15]

Required fields, in this order: `src` (an http(s) URL, or `doi:10.NNNN/...`; `none`
only when the status is `inferred`), `read` (the ISO date the source was read, or
for an inferred claim with no source, the date it was written), `status` (one of
STATUSES). Optional, after them: `loc` (where in the source) and `via` (what was
actually read, for a claim taken from a secondary source).

    python3 check_reference.py [DIR]              validate, print counts by status
    python3 check_reference.py [DIR] --find TERM  print the INDEX rows matching TERM

Validation exits 0 when there are no violations, 1 when there are, 2 when DIR does
not exist. `--find` exits 0 when a row matches, 1 when none does, 2 when DIR or its
INDEX.md is missing. It checks that provenance is recorded, not that a claim is
true. Python standard library only. See README.md in this directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

STATUSES = ("source", "secondary", "inferred")
REQUIRED = ("src", "read", "status")
OPTIONAL = ("loc", "via")
INDEX_NAME = "INDEX.md"
INDEX_COLUMNS = ("file", "scope", "terms")

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
_TAG = re.compile(r"\[src:(?P<body>[^\[\]]*)\]\s*$")
_URL = re.compile(r"^https?://[^\s|]+$")
_DOI = re.compile(r"^doi:10\.\d{4,9}/[^\s|]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LINK = re.compile(r"^\[[^\]]*\]\(([^)\s]+)\)$")


class Claim:
    def __init__(self, path: Path, line: int, text: str):
        self.path = path
        self.line = line
        self.text = text
        self.status: str | None = None


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------

def check_tag(text: str, today: dt.date) -> tuple[str | None, list[str]]:
    """(status, problems) for one claim's full text."""
    count = text.count("[src:")
    if count == 0:
        return None, ["claim has no [src: ... | read: ... | status: ...] tag"]
    if count > 1:
        return None, ["claim has more than one tag; split it into one claim per source"]
    m = _TAG.search(text)
    if m is None:
        return None, ["the tag must close with ] and end the claim"]
    if not text[: m.start()].strip():
        return None, ["tag with no claim text before it"]
    fields: list[tuple[str, str]] = []
    problems: list[str] = []
    for i, part in enumerate(("src:" + m.group("body")).split("|")):
        key, sep, value = part.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not sep or not key:
            problems.append(f"tag field {i + 1} is not 'key: value'")
            continue
        fields.append((key, value))
    keys = [k for k, _ in fields]
    if keys[:3] != list(REQUIRED):
        problems.append("tag must start with src, read, status in that order")
    for k in keys:
        if k not in REQUIRED + OPTIONAL:
            problems.append(f"unknown tag field '{k}'")
    for k in set(keys):
        if keys.count(k) > 1:
            problems.append(f"tag field '{k}' given more than once")
    values = dict(fields)
    status = values.get("status")
    if status is not None and status not in STATUSES:
        problems.append(f"status '{status}' is not one of {', '.join(STATUSES)}")
        status = None
    src = values.get("src")
    if src is not None:
        if src == "none":
            if status not in (None, "inferred"):
                problems.append("src: none is allowed only with status: inferred")
        elif not (_URL.match(src) or _DOI.match(src)):
            problems.append(f"src '{src}' is not an http(s) URL, doi:10.NNNN/..., or none")
    read = values.get("read")
    if read is not None:
        if not _DATE.match(read):
            problems.append(f"read date '{read}' is not YYYY-MM-DD")
        else:
            try:
                d = dt.date.fromisoformat(read)
            except ValueError:
                problems.append(f"read date '{read}' is not a real date")
            else:
                if d > today:
                    problems.append(f"read date {read} is in the future")
    for k in OPTIONAL:
        if k in values and not values[k]:
            problems.append(f"tag field '{k}' is empty")
    return (status if not problems else None), problems


# --------------------------------------------------------------------------
# Entries
# --------------------------------------------------------------------------

def parse_entry(path: Path, today: dt.date) -> tuple[list[Claim], list[str]]:
    """Claims of one entry file, and its violations as 'path:line: message'."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return [], [f"{path}: cannot read: {e}"]
    problems: list[str] = []
    claims: list[Claim] = []
    sections: list[int] = []
    in_claims = in_fence = False
    current: Claim | None = None
    for n, raw in enumerate(lines, 1):
        if _FENCE.match(raw):
            if in_claims and not in_fence and not raw[:1].isspace():
                problems.append(f"{path}:{n}: a code block under ## Claims must be indented inside a claim")
            in_fence = not in_fence
            if current is not None:
                current.text += " " + raw.strip()
            continue
        if in_fence:
            if current is not None:
                current.text += " " + raw.strip()
            continue
        h = _HEADING.match(raw)
        if h and len(h.group(1)) <= 2:
            current = None
            in_claims = len(h.group(1)) == 2 and h.group(2).strip().lower() == "claims"
            if in_claims:
                sections.append(n)
            continue
        if not in_claims:
            continue
        if h:  # ### and deeper: grouping inside Claims
            current = None
            continue
        if not raw.strip():
            continue
        item = _ITEM.match(raw)
        if item:
            current = Claim(path, n, item.group(2).strip())
            claims.append(current)
        elif raw[:1].isspace() and current is not None:
            current.text += " " + raw.strip()
        else:
            problems.append(f"{path}:{n}: text under ## Claims that is not a list item; make it a claim or move it")
    if not sections:
        problems.append(f"{path}: no '## Claims' section")
    elif len(sections) > 1:
        problems.append(f"{path}:{sections[1]}: more than one '## Claims' section")
    elif not claims:
        problems.append(f"{path}:{sections[0]}: '## Claims' has no claims")
    for c in claims:
        status, issues = check_tag(c.text, today)
        c.status = status
        problems.extend(f"{path}:{c.line}: {msg}" for msg in issues)
    return claims, problems


# --------------------------------------------------------------------------
# INDEX
# --------------------------------------------------------------------------

def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _file_cell(cell: str) -> str:
    cell = cell.strip()
    m = _LINK.match(cell)
    if m:
        cell = m.group(1)
    return cell.strip("`").strip()


def parse_index(path: Path) -> tuple[list[tuple[int, str, str, str]], list[str]]:
    """Rows (line, file, scope, terms) of INDEX.md, and its violations."""
    rows: list[tuple[int, str, str, str]] = []
    problems: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return [], [f"{path}: cannot read: {e}"]
    header_seen = False
    for n, line in enumerate(lines, 1):
        if not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue  # separator row
        if not header_seen:
            header_seen = True
            if tuple(c.lower() for c in cells) != INDEX_COLUMNS:
                problems.append(f"{path}:{n}: header must be | File | Scope | Terms |")
            continue
        if len(cells) != 3:
            problems.append(f"{path}:{n}: row has {len(cells)} cells, expected 3 (do not use | inside a cell)")
            continue
        f, scope, terms = _file_cell(cells[0]), cells[1], cells[2]
        if not f or not scope or not terms:
            problems.append(f"{path}:{n}: row needs a file, a scope and search terms")
            continue
        rows.append((n, f, scope, terms))
    if not header_seen:
        problems.append(f"{path}: no table; expected | File | Scope | Terms |")
    return rows, problems


# --------------------------------------------------------------------------
# Whole reference
# --------------------------------------------------------------------------

def check(ref: Path, today: dt.date) -> tuple[list[Claim], list[str], int]:
    """(claims, violations, number of entry files)."""
    problems: list[str] = []
    claims: list[Claim] = []
    index = ref / INDEX_NAME
    entries = sorted(p for p in ref.rglob("*.md") if p.is_file() and p.resolve() != index.resolve())
    listed: dict[Path, int] = {}
    if not index.is_file():
        problems.append(f"{index}: missing")
    else:
        rows, issues = parse_index(index)
        problems.extend(issues)
        root = ref.resolve()
        for n, f, _, _ in rows:
            target = (ref / f).resolve()
            if root not in target.parents:
                problems.append(f"{index}:{n}: '{f}' is outside the reference directory")
            elif not target.is_file():
                problems.append(f"{index}:{n}: '{f}' does not exist")
            elif target.suffix.lower() != ".md":
                problems.append(f"{index}:{n}: '{f}' is not a Markdown file")
            elif target in listed:
                problems.append(f"{index}:{n}: '{f}' is already listed on line {listed[target]}")
            else:
                listed[target] = n
    for p in entries:
        if index.is_file() and p.resolve() not in listed:
            problems.append(f"{p}: not listed in {INDEX_NAME}")
        found, issues = parse_entry(p, today)
        claims.extend(found)
        problems.extend(issues)
    return claims, problems, len(entries)


def counts(claims: list[Claim]) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    out["invalid"] = 0
    for c in claims:
        out[c.status or "invalid"] += 1
    return out


def find(ref: Path, term: str, today: dt.date) -> int:
    index = ref / INDEX_NAME
    if not index.is_file():
        print(f"{index}: missing", file=sys.stderr)
        return 2
    rows, _ = parse_index(index)
    words = term.lower().split()
    hits = [r for r in rows if all(w in f"{r[1]} {r[2]} {r[3]}".lower() for w in words)]
    if not hits:
        print(f"no INDEX row matches '{term}' in {index}")
        return 1
    for _, f, scope, terms in hits:
        path = ref / f
        if path.is_file():
            c = counts(parse_entry(path, today)[0])
            tally = ", ".join(f"{c[s]} {s}" for s in STATUSES) + (f", {c['invalid']} invalid" if c["invalid"] else "")
        else:
            tally = "file missing"
        print(f"{path} | {scope} | {terms} | claims: {tally}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check a compiled reference directory.")
    ap.add_argument("directory", nargs="?", default="docs/reference")
    ap.add_argument("--find", metavar="TERM", help="print the INDEX rows whose file, scope or terms contain every word of TERM")
    args = ap.parse_args(argv)
    ref = Path(args.directory)
    today = dt.date.today()
    if not ref.is_dir():
        print(f"{ref}: not a directory; this project has no reference there yet", file=sys.stderr)
        return 2
    if args.find is not None:
        return find(ref, args.find, today)
    claims, problems, n_entries = check(ref, today)
    for p in problems:
        print(p)
    c = counts(claims)
    print(f"{ref}: {n_entries} entries, {len(claims)} claims")
    for s in STATUSES:
        print(f"  {s:<10} {c[s]}")
    if c["invalid"]:
        print(f"  {'invalid':<10} {c['invalid']}")
    print(f"{len(problems)} violation{'s' if len(problems) != 1 else ''}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
