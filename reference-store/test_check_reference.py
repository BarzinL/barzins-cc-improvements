#!/usr/bin/env python3
"""Standalone tests for check_reference.py - no pytest, just run it:

    python3 test_check_reference.py

Each case writes a synthetic reference directory, runs the checker on it as a
subprocess, and compares the exit code and output with what is expected. Then the
mutation check: each of several deliberately broken copies of the checker (one rule
switched off in each) is run against the same cases, and at least one case must fail
for every mutant. If a mutant passes every case, the cases cannot detect that rule
being lost. Exit 0 when every case passes and every mutant is caught, 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "check_reference.py"
EXAMPLE = HERE / "example"

URL = "https://example.org/paper"
GOOD_TAG = f"[src: {URL} | read: 2026-01-05 | status: source]"


def tag(src: str = URL, read: str = "2026-01-05", status: str = "source", extra: str = "") -> str:
    return f"[src: {src} | read: {read} | status: {status}{extra}]"


def entry(*claims: str, title: str = "# Entry", before: str = "", after: str = "") -> str:
    body = "\n".join(claims)
    return f"{title}\n\nScope: test.\n{before}\n## Claims\n\n{body}\n{after}"


INDEX_HEAD = "# Index\n\n| File | Scope | Terms |\n|---|---|---|\n"


def index(*rows: tuple[str, str, str]) -> str:
    return INDEX_HEAD + "".join(f"| {f} | {s} | {t} |\n" for f, s, t in rows)


def one(text: str, name: str = "a.md") -> dict[str, str]:
    """A reference with one entry file, correctly indexed."""
    return {"INDEX.md": index((name, "scope", "term")), name: text}


def run(checker: Path, files: dict[str, str], *args: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as d:
        ref = Path(d) / "ref"
        ref.mkdir()
        for name, text in files.items():
            p = ref / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        r = subprocess.run([sys.executable, str(checker), str(ref), *args], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr


# (name, files, extra args, expected exit code, text that must appear in output)
CASES: list[tuple[str, dict[str, str], tuple[str, ...], int, str]] = [
    ("valid: one claim per status -> exit 0, counts by status",
     one(entry(f"- A read claim. {GOOD_TAG}",
               f"- A summary claim. {tag(status='secondary', extra=' | via: a review')}",
               f"- A guess. {tag(src='none', status='inferred')}")),
     (), 0, "source     1"),
    ("valid: counts list inferred",
     one(entry(f"- A guess. {tag(src='none', status='inferred')}", f"- Another. {tag(status='inferred')}")),
     (), 0, "inferred   2"),
    ("valid: DOI source, loc field, wrapped claim with the tag on a continuation line",
     one(entry("- A claim that runs over\n  two lines.\n  " + tag(src="doi:10.1038/nature12373", extra=" | loc: p. 4"))),
     (), 0, "0 violations"),
    ("valid: nested items each tagged, ### grouping, other sections free text",
     one(entry(f"### Group\n\n- Parent. {GOOD_TAG}\n  - Child. {GOOD_TAG}", before="\nAnything here is free text.\n",
               after="\n## Notes\n\nUntagged prose is allowed outside Claims.\n")),
     (), 0, "2 claims"),
    ("valid: a '## Claims' line inside a code fence elsewhere is not a section",
     one("# E\n\n```\n## Claims\nnot a claim\n```\n\n## Claims\n\n- Real. " + GOOD_TAG + "\n"),
     (), 0, "1 claims"),
    ("valid: the shipped example reference passes", {}, ("--example",), 0, "0 violations"),

    ("claim with no tag -> violation", one(entry("- The sky is green.")), (), 1, "has no [src:"),
    ("status outside the set -> violation", one(entry(f"- X. {tag(status='verified')}")), (), 1, "status 'verified'"),
    ("status missing -> violation", one(entry(f"- X. [src: {URL} | read: 2026-01-05]")), (), 1, "src, read, status"),
    ("fields out of order -> violation", one(entry(f"- X. [src: {URL} | status: source | read: 2026-01-05]")),
     (), 1, "in that order"),
    ("unknown field -> violation", one(entry(f"- X. {tag(extra=' | confidence: high')}")), (), 1, "unknown tag field"),
    ("field given twice -> violation", one(entry(f"- X. {tag(extra=' | loc: a | loc: b')}")), (), 1, "more than once"),
    ("date that does not parse -> violation", one(entry(f"- X. {tag(read='2026-02-30')}")), (), 1, "not a real date"),
    ("date in another format -> violation", one(entry(f"- X. {tag(read='14/11/2026')}")), (), 1, "not YYYY-MM-DD"),
    ("date in the future -> violation", one(entry(f"- X. {tag(read='2999-01-01')}")), (), 1, "in the future"),
    ("source that is not a URL or DOI -> violation", one(entry(f"- X. {tag(src='Smith et al. 2020')}")), (), 1,
     "is not an http(s) URL"),
    ("src: none with status source -> violation", one(entry(f"- X. {tag(src='none')}")), (), 1,
     "only with status: inferred"),
    ("src: none with status secondary -> violation", one(entry(f"- X. {tag(src='none', status='secondary')}")),
     (), 1, "only with status: inferred"),
    ("tag not at the end of the claim -> violation", one(entry(f"- X {GOOD_TAG} and more text.")), (), 1,
     "end the claim"),
    ("two tags on one claim -> violation", one(entry(f"- X. {GOOD_TAG} {GOOD_TAG}")), (), 1, "more than one tag"),
    ("tag with no claim text -> violation", one(entry(f"- {GOOD_TAG}")), (), 1, "no claim text"),
    ("empty optional field -> violation", one(entry(f"- X. {tag(extra=' | via:')}")), (), 1, "'via' is empty"),
    ("nested child without a tag -> violation", one(entry(f"- Parent. {GOOD_TAG}\n  - Child with none.")), (), 1,
     "has no [src:"),
    ("plain paragraph under Claims -> violation", one(entry(f"- X. {GOOD_TAG}", "\nAn untagged sentence.")), (), 1,
     "not a list item"),
    ("unindented code block under Claims -> violation", one(entry(f"- X. {GOOD_TAG}", "```\ncode\n```")), (), 1,
     "must be indented"),
    ("no Claims section -> violation", one("# E\n\nJust prose.\n"), (), 1, "no '## Claims' section"),
    ("empty Claims section -> violation", one("# E\n\n## Claims\n\n## Notes\n"), (), 1, "has no claims"),
    ("two Claims sections -> violation", one(entry(f"- X. {GOOD_TAG}") + f"\n## Claims\n\n- Y. {GOOD_TAG}\n"),
     (), 1, "more than one '## Claims'"),

    ("INDEX missing -> violation", {"a.md": entry(f"- X. {GOOD_TAG}")}, (), 1, "INDEX.md: missing"),
    ("entry not listed in INDEX -> violation",
     {"INDEX.md": index(("a.md", "s", "t")), "a.md": entry(f"- X. {GOOD_TAG}"), "sub/b.md": entry(f"- Y. {GOOD_TAG}")},
     (), 1, "not listed in INDEX.md"),
    ("INDEX lists a file that does not exist -> violation",
     {"INDEX.md": index(("a.md", "s", "t"), ("gone.md", "s", "t")), "a.md": entry(f"- X. {GOOD_TAG}")},
     (), 1, "'gone.md' does not exist"),
    ("INDEX lists a file twice -> violation",
     {"INDEX.md": index(("a.md", "s", "t"), ("[a](a.md)", "s2", "t2")), "a.md": entry(f"- X. {GOOD_TAG}")},
     (), 1, "already listed"),
    ("INDEX row pointing outside the directory -> violation",
     {"INDEX.md": index(("a.md", "s", "t"), ("../x.md", "s", "t")), "a.md": entry(f"- X. {GOOD_TAG}")},
     (), 1, "outside the reference directory"),
    ("INDEX row missing its terms -> violation",
     {"INDEX.md": INDEX_HEAD + "| a.md | scope |  |\n", "a.md": entry(f"- X. {GOOD_TAG}")}, (), 1,
     "needs a file, a scope and search terms"),
    ("INDEX with the wrong header -> violation",
     {"INDEX.md": "| Path | About |\n|---|---|\n| a.md | s |\n", "a.md": entry(f"- X. {GOOD_TAG}")}, (), 1,
     "header must be"),

    ("--find: matching row printed with its path and claim counts",
     {"INDEX.md": index(("[a](a.md)", "Methylation clocks", "epigenetic, clock"), ("b.md", "FFT", "fourier")),
      "a.md": entry(f"- X. {GOOD_TAG}", f"- Y. {tag(src='none', status='inferred')}"),
      "b.md": entry(f"- Z. {GOOD_TAG}")},
     ("--find", "Epigenetic"), 0, "a.md | Methylation clocks | epigenetic, clock | claims: 1 source, 0 secondary, 1 inferred"),
    ("--find: every word must match; a row matching one word only is not printed",
     {"INDEX.md": index(("a.md", "Methylation clocks", "epigenetic"), ("b.md", "FFT", "fourier, clock")),
      "a.md": entry(f"- X. {GOOD_TAG}"), "b.md": entry(f"- Z. {GOOD_TAG}")},
     ("--find", "clock epigenetic"), 0, "1 source"),
    ("--find: no match -> exit 1",
     {"INDEX.md": index(("a.md", "s", "t")), "a.md": entry(f"- X. {GOOD_TAG}")}, ("--find", "quantum"), 1,
     "no INDEX row matches"),
    ("--find: no INDEX -> exit 2", {"a.md": entry(f"- X. {GOOD_TAG}")}, ("--find", "x"), 2, "missing"),
]


def run_cases(checker: Path, verbose: bool) -> int:
    failures = 0
    for name, files, args, want_code, want_text in CASES:
        if args == ("--example",):
            r = subprocess.run([sys.executable, str(checker), str(EXAMPLE)], capture_output=True, text=True)
            code, out = r.returncode, r.stdout + r.stderr
        else:
            code, out = run(checker, files, *args)
        ok = code == want_code and want_text in out
        if name.startswith("--find: every word"):
            ok = ok and "b.md" not in out
        if not ok:
            failures += 1
        if verbose:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}")
            if not ok:
                print(f"       want exit {want_code} and {want_text!r}; got exit {code}:\n       "
                      + out.strip().replace("\n", "\n       "))
    # A missing directory is a usage error, not a violation.
    r = subprocess.run([sys.executable, str(checker), "/nonexistent/reference"], capture_output=True, text=True)
    ok = r.returncode == 2
    failures += 0 if ok else 1
    if verbose:
        print(f"[{'PASS' if ok else 'FAIL'}] missing directory -> exit 2")
    return failures


# Each mutant switches off one rule. (description, text in the checker, replacement)
MUTANTS = [
    ("status set not enforced", "if status is not None and status not in STATUSES:", "if False:"),
    ("future dates accepted", "if d > today:", "if False:"),
    ("impossible dates accepted", "d = dt.date.fromisoformat(read)", "d = dt.date(2000, 1, 1)"),
    ("untagged claims accepted", 'return None, ["claim has no [src: ... | read: ... | status: ...] tag"]',
     'return "source", []'),
    ("src not validated", "elif not (_URL.match(src) or _DOI.match(src)):", "elif False:"),
    ("src: none allowed with any status", 'if status not in (None, "inferred"):', "if False:"),
    ("unindexed entries accepted", "if index.is_file() and p.resolve() not in listed:", "if False:"),
    ("missing INDEX targets accepted", "elif not target.is_file():", "elif False:"),
    ("prose under Claims accepted", 'problems.append(f"{path}:{n}: text under ## Claims', 'pass  # ('),
    ("--find ignores the term", "if all(w in f\"{r[1]} {r[2]} {r[3]}\".lower() for w in words)", "if True"),
]


def mutation_check() -> int:
    source = CHECKER.read_text(encoding="utf-8")
    failures = 0
    with tempfile.TemporaryDirectory() as d:
        for desc, old, new in MUTANTS:
            if old not in source:
                print(f"[FAIL] mutant '{desc}': target text not found in the checker; update MUTANTS")
                failures += 1
                continue
            mutant = Path(d) / "check_reference.py"
            mutant.write_text(source.replace(old, new, 1), encoding="utf-8")
            caught = run_cases(mutant, verbose=False)
            ok = caught > 0
            failures += 0 if ok else 1
            print(f"[{'PASS' if ok else 'FAIL'}] mutant '{desc}' is caught ({caught} case(s) fail against it)")
    return failures


def main() -> int:
    failures = run_cases(CHECKER, verbose=True)
    print()
    failures += mutation_check()
    print()
    if failures:
        print(f"{failures} FAILED")
        return 1
    print("all cases passed; every mutant caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
