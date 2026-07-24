# Claude Code: `/experiment-freeze-gate` skill

A pre-compute checklist for experiment-shaped work - evals, benchmarks, A/B
tests, training runs, anything scored against pre-registered criteria.

## The failure class

There's a class of experiment failure that **no code review, no test suite, and
no claims-vs-repo audit can catch: a defective spec, faithfully built.** The
verdict rule names a quantity the artifact schema forgot; the initial condition
already clears the success bar; the pre-registered contrast is against a state
that a successful run erases. In every one of these, the executor's claims are
all true and the tests are all green - the defect lives in the spec's relation
to itself.

Both real near-misses that motivated this skill came from exactly there. In one,
the pre-registered verdict compared an experimental arm against a baseline whose
value the results schema never recorded - and the eval code, built faithfully to
the schema, computed the number and threw it away. In the other, a pre-launch
smoke showed the *random, unevolved* initial population already scoring 2.5×
above the verdict bar: the run would have "confirmed emergence" at generation
zero. Both were caught minutes before compute was committed, by checks that are
purely mechanical once you know to run them.

## What's in the box

`SKILL.md` - the freeze protocol plus an eight-check gate (G1–G8), each check
compiled from a real incident:

| Check | One line |
|---|---|
| G1 | Every quantity the verdict names must be recorded by the code |
| G2 | Score the null against the bar *before* the real run |
| G3 | Contrasts must survive success |
| G4 | Hunt comparisons that are degenerate by construction |
| G5 | Resource numbers are formulas against this run's data, never inherited |
| G6 | No subject grades a bench it sat; police attribution, not just existence |
| G7 | Imported directional claims carry verbatim quotes from the primary text |
| G8 | Declare every pre-freeze calibration contact |

## How to use

1. Drop `experiment-freeze-gate/` into your project's `.claude/skills/`.
2. When you're about to freeze an experiment design, prompt:

   `Freeze this design and run /experiment-freeze-gate before we commit compute.`

3. Treat a gate failure as a spec bug: fix the spec, re-run the gate. Changing
   any bar or grid *after* seeing results means a new frozen spec, with the old
   prediction scored against the old spec and kept verbatim.

## Honest status

The individual rules are battle-tested - each exists because a real incident
demonstrated its shape, and the two headline incidents were caught *by* these
checks running as a pre-launch pass. The packaging as a standalone skill is
newer than the rules; no throughput/efficiency claims are made for it.

## Relation to the rest of this repo

`ground-skill-verifier` checks claims about *code* against the code.
`theory-formation-discipline` checks claims about *your own work and reasoning*.
This skill checks an experiment's spec against *itself*, before compute - the
one place where "everything downstream verified clean" can still mean the run
was worthless.
