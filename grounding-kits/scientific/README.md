# Scientific grounding kit

A command-line tool for keeping a validation record of numerical results, and a
one-page playbook for scientific and numerical work. The `task-grounding/` hook names
both, by absolute path, in its scientific directive when it finds this directory.

Targeted at: Opus 5.5

## What it is for

The scientific directive in `task-grounding/` asks the agent to validate code against a
case with a known answer. Without somewhere to put the check, a validation tends to be
a sentence in the reply ("matches the analytic solution") with no number, no tolerance
and nothing to look at later. `validate.py` makes each check a recorded line with the
expected value, the observed value, the tolerance and the units, decides pass or fail
from those numbers itself, and gives one command whose exit status says whether every
recorded check passed. It does no domain science: choosing the expectation and the
tolerance is still the agent's work.

## Files

- `validate.py`: the tool. Python standard library only.
- `PLAYBOOK.md`: what to check before reporting a computed result, and what to do when
  the method or domain is unfamiliar.
- `test_validate.py`: tests.

## How the agent is expected to use it

```bash
# one check of one result against an independent expectation
python3 validate.py add --record <scratchpad>/validation.jsonl --name "decay at t=1" \
    --kind analytic --expected 0.367879 --observed 0.367901 --rel-tol 1e-4 --units 1 \
    --note "exp(-1) for k=1"

# refinement: three or more (spacing, value) pairs with a constant ratio
python3 validate.py convergence --pair 0.04 1.00321 --pair 0.02 1.00080 --pair 0.01 1.00020 \
    --expected-order 2 --record <scratchpad>/validation.jsonl --name "grid" --units m

# before reporting
python3 validate.py summary --record <scratchpad>/validation.jsonl
```

`add` takes a name, a kind (`analytic`, `limit`, `conservation`, `second-method`,
`refinement`, `reference-data`, `other`), the expected and observed values, a units
string (`1` for dimensionless), an optional note, and an absolute tolerance, a relative
tolerance or both. It passes when |observed − expected| ≤ the absolute tolerance, or ≤
the relative tolerance × |expected|; with both, when either holds. It refuses (exit 2,
nothing written) an entry with no tolerance, a negative or non-finite tolerance, a
non-finite expected value, missing units, or a relative tolerance alone when the
expected value is zero. A NaN or infinite observed value is recorded as a failure. Exit
0 on pass, 1 on fail.

`convergence` sorts the pairs from coarse to fine, requires a constant refinement ratio
r, and for each three successive values reports the observed order
p = ln(|v₁ − v₂| / |v₂ − v₃|) / ln r. It says "converging" only if every successive
difference is smaller in size than the one before, and notes when the differences change
sign. With `--expected-order` it also checks the last observed order is within
`--order-tol` (default 0.2) of it. With `--record` it appends a `refinement` entry that
passes only if the sequence converges (and agrees, when an order was given). Exit 0 if
converging (and agreeing), 1 if not, 2 if refused.

`summary` prints every entry and the counts, and exits 1 if any check failed or the
record is empty, 2 if the file is missing or a line is not a validation entry.

## What it cannot do

- **It cannot tell whether the expectation is independent or correct.** An "analytic"
  value taken from the same wrong formula as the code passes.
- **It cannot tell whether a tolerance is reasonable.** It requires one and records it,
  so a loose tolerance is visible to a reader; it does not judge it.
- **The convergence check needs a constant refinement ratio** and values in the
  asymptotic range. Pre-asymptotic or noisy values give orders that mean little; a
  sequence whose differences shrink can still converge to the wrong answer.
- **Records are self-reported.** Nothing stops an agent from typing an observed value
  that its code did not produce, or from deleting a failed line.
- **Nothing makes the agent use it.** The hook directive names it and asks for a summary
  before reporting; whether the agent does is up to the agent.

## Status

The tool and its tests run. **It has not yet been evaluated for effect on outcomes**: no
comparison of agent sessions with and without the kit has been made.

## Install

Copy this directory to `grounding-kits/scientific/` beside `task_grounding.py` (for
example `.claude/hooks/grounding-kits/scientific/`). The hook then names `validate.py`
and `PLAYBOOK.md` in its scientific directive. The playbook refers to the
`reference-store/` format for recording sources; install that too if you use the
reference. The tool also works on its own.

## Test

```bash
python3 -I test_validate.py
```

Standalone, no pytest. 31 cases: absolute and relative tolerances inside, outside and at
the boundary, a negative expected value, expected zero with both tolerances and with
only a relative one (refused), a NaN observed value (a recorded failure), refusal of a
missing tolerance, a negative tolerance, a NaN expected value, missing units and an
unknown kind, the fields of an entry, `summary` exit codes for failed, passing, empty,
missing and malformed records, the observed order of a synthetic second-order sequence
(3 + 0.5h²), with the expected order agreeing and not agreeing and with the pairs out of
order, an oscillating and a growing sequence flagged as not converging, fewer than three
pairs and a non-constant ratio refused, and convergence entries written to a record.
`VALIDATE=/path/to/copy.py python3 -I test_validate.py` runs the same cases against
another copy.
