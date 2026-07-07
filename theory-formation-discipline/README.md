# Theory-formation discipline

Tools and writeups for getting a capable model (Opus 4.8 and similar) to reason like a
good researcher - to *form* understanding without fooling itself along the way.

## The problem this addresses

Read the published system cards for recent frontier models and one pattern stands out.
The model's *capacity* for honest self-correction is essentially total: challenge an
overconfident claim and it will name its own error with precision. The problem is the
**trigger** - that correction fires *after* a human pushes back, not before the claim
ships. The cards document this as the family's highest-frequency failure surface: stating
an unverified guess as fact, reporting work as "verified end-to-end" when only static
checks ran, concluding a finding from a test that was never executed.

The fix isn't more capability - the capability is already there. The fix is **moving the
self-correction from post-pushback to pre-send.**

## What's here

- **[`theory-formation-method.md`](theory-formation-method.md)** - the nine-move
  discipline, reconstructed by mining a long-running agent session where one model held a
  *theorist* role and did the job unusually well. Two registers (open-ended reasoning vs.
  adjudicating a frozen experiment), nine nameable moves, and a through-line: treat the
  frame itself as the object under test, drive the "unverified" column to empty, and
  localize every remaining uncertainty to a single named fork. This half is
  self-enforced - a discipline you walk yourself through.

- **[`verification-claim-gate/`](verification-claim-gate/)** - a Claude Code Stop hook
  that *mechanically* enforces the single most frequent and most detectable slice of the
  above: "verified / tested / healthy" claims with no verification action behind them get
  a hard send-time pause. This half is machine-enforced - a wall, not a poster.

## How the two halves relate

The discipline doc is the theory; the hook is the one piece of it that a machine can
actually police. A regex can't tell whether your *reasoning* was honest - but it can tell
whether you said "all tests pass" without running any tests. So the split is deliberate:
the hook takes the frequent, detectable failure off your plate entirely, and the
discipline handles everything a hook can't reach.

## Relationship to the `/ground` skill + verifier subagent

This is a companion to the [ground skill and verifier
subagent](../ground-skill-verifier/) in this same repo. Same disease, two organs:

- **`/ground`** makes the agent verify its claims *about the codebase* before acting -
  grounding assumptions about how the code is wired in the actual code.
- **This** makes the agent verify its claims *about its own work* before reporting -
  grounding assertions of "done / verified / healthy" in an action that actually ran.

Both attack the same root failure: a capable model stating an inference as a fact without
checking. One grounds inward (the code), one grounds outward (the report).
