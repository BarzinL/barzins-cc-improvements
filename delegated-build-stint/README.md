# Claude Code: `/delegated-build-stint` skill + `build-stint` subagent

A contract for delegating build work to a subagent against a frozen plan - and
for auditing what comes back in minutes instead of re-reading the work.

## The two failure modes this closes

**1. The detached-run custody hole (the headline).** A subagent that spawns a
detached child process has no live children of its own - so the Claude Code
harness sees it idle and reports the stint **complete while the real run is
un-run or half-run**. We hit this three times in one research session: each
time the build itself was correct, the stint's claims were all true
("self-tests green, calibration PASS"), and the actual experiment silently
wasn't running. Each instance cost a manual disk-verification and relaunch
pass. The fix is a custody rule, not a code rule: a stint's acceptance ends at
"machine certified," and long runs are launched by the delegator or run as
blocking calls inside acceptance. Detached-and-report-done is banned.

**2. The unexercised-path crash.** A stint that tests `--check-only` and
`--smoke` and ships green can still have `--all` crash on its first real
invocation - on a wrong import in a module only `--all` loads. Happened
verbatim. Hence: import-check every CLI path before reporting done.

The reporting format closes a subtler third: the residual failure mode of a
self-reporting agent is **mis-attribution rather than invention** - claims that
are verbatim-true but credited to the wrong source or scope, which pass every
mechanical existence check. So reports are claims-with-evidence-pointers
(`file:line`, command + captured output), never narrative summaries: pointers
make spot-audits nearly free.

## What's in the box

- `SKILL.md` - the contract as a skill, for when the main agent runs a stint
  itself or briefs one: rules S1–S7 (machine-checkable acceptance, import-check
  every CLI path, config-integrity test, declared deviations, **no custody of
  long runs**, prior deliverables read-only, house conventions bind), the
  three-artifact handoff (compact claims report / trace index / full
  transcript), and a four-item escalation whitelist.
- `build-stint.md` - the same contract as a subagent definition, ready for
  `.claude/agents/`.

## How to use

1. Drop `SKILL.md` into `.claude/skills/delegated-build-stint/` and
   `build-stint.md` into `.claude/agents/`.
2. Freeze the plan first (constants, interfaces, acceptance criteria - if it's
   experiment-shaped, run `/experiment-freeze-gate` on it).
3. Spawn: `Use the build-stint agent to implement <plan file>.`
4. Audit the report by spot-checking evidence pointers, not by re-reading the
   diff top to bottom. Grep the trace index on any discrepancy.

## Honest status

Every rule is failure-compiled - it exists because a real incident demonstrated
its shape (three custody incidents, one unexercised-path crash, one worked
declared-deviation example). The packaging as skill + agent definition is newer
than the rules; no throughput/efficiency claims are made for it.

## Relation to the rest of this repo

Same disease, third organ. `ground-skill-verifier` checks an agent's claims
about the *code*; `theory-formation-discipline` checks its claims about its
*own work and reasoning*; this package checks claims that cross a
**delegation seam** - where the agent that did the work writes the report the
delegator will trust.
