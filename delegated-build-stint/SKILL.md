---
name: delegated-build-stint
description: Contract for delegating a build task to a subagent (or running one yourself as the delegate) against a frozen plan or spec, with machine-checkable acceptance and honest handoff reporting. Invoke when spawning an agent to build a harness, kit, runner, or feature from a plan it must not reinterpret.
---

# /delegated-build-stint — build against a frozen plan, hand back evidence

A build stint executes a frozen plan with **zero design discretion**. It never
changes the plan's constants, interfaces, thresholds, or scope; a plan problem
is an escalation, not a judgment call. Its output is the built artifact plus a
report the delegator can audit in minutes.

Every rule below was compiled from a real incident.

## Build rules

**S1 — Machine-checkable acceptance ONLY.** Acceptance = tests green on
constructed inputs with stated tolerances, integrity checks green, every
entry point exercised. "Looks right" and "should work" are not acceptance
states.

**S2 — Import-check EVERY CLI path.** Every flag combination the deliverable
exposes (`--all`, `--check-only`, `--smoke`, ...) gets at least an
import-and-parse exercise before the stint reports done. Modules imported by
only one path are exactly where this bites.
*Incident: a runner's `--all` mode crashed in production on a wrong import in
a module that only `--all` loaded — the stint had exercised only the
`--check-only` and `--smoke` paths, both green.*

**S3 — Config-integrity test.** Every frozen constant in the plan (grids,
thresholds, anchors, magic numbers, seeds) is duplicated verbatim in a test
that fails if the built config drifts from the plan.

**S4 — Declared-deviations report.** Any place the implementation differs in
FORM from the plan's stated formula or structure — while being algebraically or
behaviorally equivalent — is listed explicitly, with the equivalence argument
and the test that certifies it. Silent equivalences are audit debt.
*Worked example: a stint implemented a mathematical quantity in a rearranged
but equivalent form, declared it, and attached a 1e-12 numerical-equality test.
Audit took one read instead of a derivation.*

**S5 — NEVER take custody of a long run.** The stint's acceptance ends at
"machine certified": self-tests plus a fast, declared smoke. The long or
unattended run is launched by the delegator (or the human), or — only if short
enough to block on — run as a blocking call whose completion is inside
acceptance. A stint never spawns a detached run and reports complete.
*The mechanic, three real incidents: a subagent that spawns a detached child
process has no live children of its own, so the harness sees it idle and
reports the stint finished — while the real run is un-run or half-run. Each
instance cost the delegator a disk-verification and relaunch pass. The build
was fine every time; the custody handoff was the failure.*

**S6 — Prior deliverables are READ-ONLY.** Frozen artifacts from earlier
increments are never edited; reuse is by import. `git status` at stint end must
show changes confined to the new deliverable's own directory — and the report
quotes it.

**S7 — House conventions still bind.** File-size caps, typing discipline,
dependency policy, formatting. Delegation is not an exemption.

## Reporting (the handoff)

The stint ends by emitting three artifacts:

1. **Compact report** — claims WITH evidence pointers (`file:line`, command +
   captured output). Never a narrative summary. *Why: the report is written by
   the agent that did the work, and the residual failure mode of self-reporting
   is mis-attribution rather than invention — a claim can be verbatim-true and
   still credited to the wrong source or scope. Evidence pointers make
   spot-audits nearly free; narrative makes them archaeology.*
2. **Trace index** — one line per step: action, files touched, outcome. The
   delegator greps it on any discrepancy.
3. **Full transcript / logs** — untouched on disk for deep dips.

The report states plainly what was NOT done. Incomplete work is reported as
"incomplete, X remains" — never dressed up as a scope decision.

## Escalation (the ONLY pings allowed)

1. Plan ambiguity that blocks execution (not "could be nicer").
2. A sanity check named in the plan fails (abort and say which).
3. Infrastructure failure after 2 retries.
4. Runtime exceeds the plan's budget by more than 3×.

Nothing else. No mid-run status pings; design suggestions go in the report's
observations section, not into the code.
