# Barzin's Claude Code Improvements

A collection of practical tools and disciplines for getting more honest, more grounded
work out of Claude Code - built and battle-tested against real production development with
Opus 4.8.

The common thread across everything here: **capable models state inferences as facts
without checking.** They'll tell you how the code is wired without reading it, and tell
you work is verified without running it - then, once you push back, name their own error
with perfect precision. The capability to be honest is already there. What's missing is a
principle that fires *before* the claim ships. Each tool here closes one slice of that
gap.

## Contents

### [`ground-skill-verifier/`](ground-skill-verifier/)

The `/ground` skill and verifier subagent - grounds the agent in your codebase's actual
wiring so it stops making assumptions about how things work without checking. Consistently
produces near-bug-free code with Opus 4.8 by turning assertions and inferences about the
code into verified knowledge before acting. Configurable autonomy ceilings.

### [`theory-formation-discipline/`](theory-formation-discipline/)

Two paired pieces for reasoning like a good researcher without fooling yourself:

- **The nine-move theorist discipline** - a reusable behavioral contract reconstructed
  from an agent session where one model did months of experimental theory-formation
  unusually well. Concede precisely, name the category error before the fix, factor fuzzy
  criteria onto real machinery, name the one fork you might be wrong about, let grounding
  overturn the plan out loud, pre-register and report refutations first-class, promote the
  surprise over the headline, fold every finding back into a standing law, and deflate a
  seductive framing to what is actually true instead of agreeing with the exciting story.
- **The verification-claim gate** - a Claude Code Stop hook that pauses a turn when the
  agent claims it "verified" something it never ran. Advisory, loop-safe, fails open,
  fully tested. Targets the single highest-frequency honesty failure documented in
  frontier-model system cards.

### [`experiment-freeze-gate/`](experiment-freeze-gate/)

A pre-compute gate for experiment-shaped work (evals, benchmarks, A/B tests, training
runs). Targets the failure class no after-the-fact review can catch: **a defective spec,
faithfully built** - the verdict rule names a quantity the artifact schema never records,
or the initial condition already clears the success bar, so every downstream check passes
and the run is still worthless. Eight mechanical checks, each compiled from a real
incident, run after the design freezes and before compute is committed.

### [`delegated-build-stint/`](delegated-build-stint/)

A contract (skill + subagent definition) for delegating build work against a frozen plan.
Headline rule: a stint **never takes custody of a long run** - a subagent that spawns a
detached child has no live children of its own, so the harness reports it complete while
the real run is half-done (hit three times in one session). Plus: import-check every CLI
path before reporting done, duplicate frozen constants into a config-integrity test,
declare every formal deviation, and hand back claims-with-evidence-pointers instead of a
narrative summary.

## How the pieces relate

Same disease, different organs - a capable model stating an inference as a fact without
checking:

- **`ground-skill-verifier`** grounds the agent *inward* - its claims about how the code
  is wired, verified against the actual code before it acts.
- **`theory-formation-discipline`** grounds the agent *outward* - its claims about its own
  work ("done / verified / healthy"), and its reasoning when forming an understanding.
- **`experiment-freeze-gate`** grounds a design *against itself* - upstream of everything,
  where a spec can be internally inconsistent and every downstream check still passes.
- **`delegated-build-stint`** grounds claims that cross a *delegation seam* - the report an
  executor agent writes is the delegator's only view of the work, so it must be evidence
  pointers, honest custody, and declared deviations rather than a story.

One stops the agent from guessing about the codebase; one from guessing about its own
results; one from burning compute on a self-contradictory design; one from trusting a
subagent's narrative over its evidence.

## Philosophy

Nothing here tries to make the model *smarter*. Each piece makes it *more honest about
what it actually knows* - by moving self-correction from after-you-push-back to
before-it-speaks. Some of that is enforceable by the harness (hooks); most of it is a
discipline the agent walks itself through. Both are here, and each is labeled for which it
is - because pretending a self-enforced discipline is a hard guarantee would be exactly
the failure these tools exist to catch.
