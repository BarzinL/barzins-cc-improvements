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

- **The eight-move theorist discipline** - a reusable behavioral contract reconstructed
  from an agent session where one model did months of experimental theory-formation
  unusually well. Concede precisely, name the category error before the fix, factor fuzzy
  criteria onto real machinery, name the one fork you might be wrong about, let grounding
  overturn the plan out loud, pre-register and report refutations first-class, promote the
  surprise over the headline, fold every finding back into a standing law.
- **The verification-claim gate** - a Claude Code Stop hook that pauses a turn when the
  agent claims it "verified" something it never ran. Advisory, loop-safe, fails open,
  fully tested. Targets the single highest-frequency honesty failure documented in
  frontier-model system cards.

## How the pieces relate

Same disease, different organs - a capable model stating an inference as a fact without
checking:

- **`ground-skill-verifier`** grounds the agent *inward* - its claims about how the code
  is wired, verified against the actual code before it acts.
- **`theory-formation-discipline`** grounds the agent *outward* - its claims about its own
  work ("done / verified / healthy"), and its reasoning when forming an understanding.

One stops the agent from guessing about the codebase; the other stops it from guessing
about its own results.

## Philosophy

Nothing here tries to make the model *smarter*. Each piece makes it *more honest about
what it actually knows* - by moving self-correction from after-you-push-back to
before-it-speaks. Some of that is enforceable by the harness (hooks); most of it is a
discipline the agent walks itself through. Both are here, and each is labeled for which it
is - because pretending a self-enforced discipline is a hard guarantee would be exactly
the failure these tools exist to catch.
