# Reference store

A format for a project's local reference of domain knowledge, and a checker for it.
The reference is a directory of Markdown files that a session reads before working in
a domain where recalled facts are often wrong. In it, every claim records where it
came from, when it was read, and how well it was checked.

Targeted at: Opus 5.5

## The failure it targets

Anthropic's system card for Claude Fable 5.2 and Claude Mythos 5.2 (2026-11-09),
section 8.7, on FrontierSWE v2, a benchmark of 34 long engineering and research tasks:

> Claude Fable 5.2 scored 69.9% on FrontierSWE v2, first among the models Proximal
> evaluated. It was ahead of GPT-6 Astra (65.5%), Claude Opus 5.5 (62.3%), [...]
> Its gains over Opus 5.5 were greatest for performance
> optimization, scientific computing, and visual reasoning.

In scientific work the code is often correct as code and wrong about the domain: a
formula recalled with the wrong constant, units mixed, a method applied outside the
conditions it was published for. Reading primary sources before coding closes part of
that gap without a larger model, but each session would have to read them again. A
reference compiled once and kept in the project lets later sessions start from what
was already read.

That creates a second failure. A reference compiled by a model will contain errors,
and a later session reads the file as fact. A summary of a search result, a claim the
model inferred, and a sentence read in the paper itself all look the same once they
are written down as bullet points. So the format requires each claim to say which of
those it is, and the checker refuses a reference in which any claim does not.

## The format

A reference lives in `docs/reference/` (any directory can be passed to the checker).

### INDEX.md

One Markdown table, one row per entry file:

```markdown
| File | Scope | Terms |
|---|---|---|
| [floating-point.md](floating-point.md) | How Python floats store and round decimal values | float, IEEE 754, rounding, fsum |
```

- **File**: the entry's path relative to the reference directory, plain, in backticks,
  or as a Markdown link.
- **Scope**: one line saying what the entry covers, so a session can tell from the
  index alone whether to load it.
- **Terms**: search terms, comma-separated.

Do not put `|` inside a cell. Every `.md` file in the directory and its
subdirectories, other than `INDEX.md`, is an entry and must have a row.

### Entry files

Free Markdown, with exactly one `## Claims` section. Under `## Claims`, every list
item is a claim, nested items included, and each claim ends with one tag:

```markdown
## Claims

- The decimal 0.1 has no exact binary representation; the float stored for it is
  3602879701896397 / 2**55.
  [src: https://docs.python.org/3/tutorial/floatingpoint.html | read: 2026-11-14 | status: source | loc: §15]
```

The tag's fields, separated by `|`:

| Field | Required | Value |
|---|---|---|
| `src` | yes, first | An `http://` or `https://` URL, or a DOI written `doi:10.NNNN/...`. `none` only when the status is `inferred`. |
| `read` | yes, second | The date the source was read, `YYYY-MM-DD`. For an inferred claim with no source, the date it was written. |
| `status` | yes, third | `source`, `secondary` or `inferred` (below). |
| `loc` | no | Where in the source: section, page, table, line. |
| `via` | no | What was actually read, when it was not `src` itself. Use it with `secondary`. |

The three statuses:

- **`source`**: the claim was checked against the text at `src`. A page read through
  a tool that summarises it with another model (a web-fetch tool, a search answer)
  does not count unless the exact wording was seen.
- **`secondary`**: the claim comes from somewhere other than `src`: a search
  summary, an abstract, a review, another paper's account of `src`, a summarising
  fetch. `via` says which.
- **`inferred`**: the model concluded it, from a source or from its own knowledge.
  Placeholders written before any source was read belong here.

Status is relative to the cited source. A benchmark result read in a system card is
`source` when the card is cited, and `secondary` when the benchmark's own paper is
cited and only the card was read.

Headings `###` and deeper can group claims inside `## Claims`. Text that is not part
of a list item is refused there, so nothing untagged sits among the claims. A
continuation line or an indented code block belongs to the item above it. Other
sections (`## Notes`, `## Open questions`) are free text and are not checked.

The tags are plain text so they can be written by hand and searched with grep:

```bash
grep -rn "status: inferred" docs/reference     # claims nobody has checked against a source
grep -rn "status: secondary" docs/reference    # claims to check at their source
grep -rn "read: 2025-" docs/reference          # claims read in 2025
```

## The checker

```bash
python3 check_reference.py [DIR]               # DIR defaults to docs/reference
python3 check_reference.py [DIR] --find TERM
```

Without `--find` it checks:

- every claim has exactly one tag, at its end, with text before it;
- the tag has `src`, `read` and `status` in that order, no unknown or repeated
  fields, and no empty optional field;
- `status` is one of the three, `src` is a URL or `doi:` (or `none` with
  `inferred`), and `read` is a real date not later than today;
- each entry has one `## Claims` section with at least one claim, and no untagged
  text in it;
- `INDEX.md` exists, has the `File | Scope | Terms` header, each row has all three
  cells, every listed file exists inside the directory and is Markdown, no file is
  listed twice, and every entry file is listed.

It prints each violation as `path:line: message`, then the number of entries and the
number of claims by status, and exits 1 if there was any violation, 0 if not, 2 if
the directory does not exist.

```
docs/reference: 2 entries, 11 claims
  source     9
  secondary  1
  inferred   1
0 violations
```

`--find TERM` prints the index rows whose file, scope or terms contain every word of
TERM (case-insensitive), with the entry's path and its claim counts, so a session can
load one entry instead of the whole reference:

```
docs/reference/floating-point.md | How Python floats ... | float, IEEE 754, ... | claims: 6 source, 0 secondary, 1 inferred
```

It exits 0 when a row matches, 1 when none does, and 2 when there is no reference
directory or no `INDEX.md`.

`example/` is a small reference that passes: one entry from the Python floating-point
tutorial and one from the Fable 5.2 system card, with claims of all three statuses.

## What it cannot do

- **It checks that provenance is recorded, not that a claim is true.** It does not
  fetch the URL, and it cannot tell whether the source says what the claim says. A
  claim with a real URL and `status: source` can still misquote the source.
- **The status is self-reported.** A model that took a claim from a search summary
  and wrote `status: source` passes. The format makes that a specific, checkable
  statement rather than an unmarked one; a person or a cold reviewer still has to
  check it. `inferred` and `secondary` claims are where to start, and they can be
  listed with grep.
- **Only `## Claims` is checked.** A fact stated in a free-text section carries no
  tag and is not caught. The rule that facts go in `## Claims` is a convention.
- **Dates show age, nothing more.** There is no expiry. A claim read in 2024 about a
  library's behaviour passes in 2027.
- **`--find` matches substrings of the index.** If the index row does not use the
  word a session searches for, the entry is not found. Terms have to be chosen with
  that in mind.
- **It does not make a session use the reference.** The scientific directive in
  `task-grounding/` tells the agent to run `--find` before domain work; nothing checks
  that it did, or that it read the entry it found.
- **Contradictions and duplicates** between claims are not detected.

## Install

1. Copy `check_reference.py` into the project. If you use `task-grounding/`, put it
   beside `task_grounding.py`: the hook finds it there and names it by absolute path in
   the scientific directive.
2. Create `docs/reference/INDEX.md` with the header row. `example/` shows the shape.
3. Optionally run the checker in CI or a pre-commit hook, so a reference with an
   untagged claim cannot be committed.

Python standard library only. No network access.

## Test

```bash
python3 test_check_reference.py
```

Standalone, no pytest. 40 cases on synthetic reference directories: valid
references, each kind of tag and index violation, `--find` matching, exit codes, and
the shipped `example/`. Then a mutation check: ten copies of the checker, each with
one rule switched off (status set, future dates, impossible dates, untagged claims,
source format, `src: none`, unindexed entries, missing index targets, prose under
Claims, `--find` filtering), are run against the same cases, and each must make at
least one case fail.

## Status

The checker and its tests run. The format has not been used on a real project yet:
no session has compiled a reference with it, and whether reading a reference before
domain work changes the outcome of a task is unmeasured.
