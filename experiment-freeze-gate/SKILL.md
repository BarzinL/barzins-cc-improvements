---
name: experiment-freeze-gate
description: Pre-compute gate for any experiment-shaped task (evals, benchmarks, A/B tests, training runs, data analyses with a pre-registered verdict). Freezes the spec, then runs a mechanical checklist that catches the failure class no after-the-fact review can - specs that are internally inconsistent or confounded, faithfully built. Invoke before committing compute to any run whose outcome you intend to score against pre-registered criteria.
---

# /experiment-freeze-gate — check the spec against itself before compute

The failure class this targets: **a defective spec, faithfully built.** When the
verdict rule, the recorded artifacts, and the initial conditions don't cohere,
every downstream check passes — the executor's claims are all true, the tests are
green, the code matches the spec — and the run is still unadjudicable or
confounded. No fidelity check (code-vs-spec, claims-vs-repo) can catch it,
because nothing was unfaithful. The check has to run at freeze time, before
compute is committed.

Every rule below was compiled from a real incident, not derived from principle.

## When to invoke

Before launching any run you intend to score against criteria you wrote in
advance: model evals, benchmark sweeps, A/B tests, training experiments,
performance measurements with a pass/fail bar.

## The protocol

1. **Freeze first.** Write the spec: hypothesis and null, success criteria with
   numeric bars, the exact metric formulas (math, not prose), the run matrix,
   seeds, the results-artifact schema (every field the run will record), sanity
   checks with tolerances, and the compute budget. Commit it before any swept
   run executes.
2. **Run the gate below.** A failure means the freeze is defective: fix the
   spec, re-run the gate. Skipping a check is never a scope decision.
3. **After the gate:** any grid / threshold / bar / formula change after first
   contact with results = a new increment with a new frozen spec. The old
   prediction is scored against the old spec and kept verbatim.

## The gate

**G1 — Verdict-schema consistency.** List every quantity the verdict rule
names. Verify each one (a) appears in the results-artifact schema AND (b) is
actually written by the recording code. Grep-level mechanical.
*Incident: an evolution experiment's pre-registered verdict compared the
champion's score-delta against a baseline arm's score-delta. The spec's own
artifact schema omitted the baseline's value — and the build was faithful to
the schema: the eval code computed the number and discarded it. The verdict was
uncomputable from the planned artifacts. Caught only by a pre-launch grep of
"what scalar does the verdict actually compare."*

**G2 — Score the null against the bar first.** For any
emergence / improvement / differentiation claim: score the null (initial
population, control arm, unadapted baseline) against the verdict bar BEFORE the
real run. If the null clears the bar, the design is confounded — stop.
*Incident: a frozen random init already scored 0.258 against a >0.10 verdict
bar. The run would have "confirmed emergence" at generation 0, measuring tuning
of an already-passing population, not discovery. One pre-launch smoke of the
unevolved population caught it.*

**G3 — Contrasts must survive success.** Never define a verdict condition as a
contrast against a state that a successful run erases. Contrast against a
held-out early snapshot or the null instead.
*Incident: a winner-vs-loser trajectory contrast was mooted because the entire
population converged — a fully successful run left no losers to contrast
against. Found only at adjudication.*

**G4 — Audit for degenerate-by-construction comparisons.** For any comparison
between two derived quantities: check at spec time whether one operand is
contained in (or an additive term of) the other. If so the comparison is
degenerate by construction; a uniform-zero or uniform-perfect table is the
diagnostic signature, and the spec should predict it rather than a reviewer
discovering it.
*Incident: a subspace-angle check returned 672/672 zero angles because one
subspace was, by definition, an additive component of the other — principal
angles were 0 by construction, carrying no information. (TT-4b,
https://doi.org/10.5281/zenodo.21309879.)*

**G5 — Resource claims are formulas, never inherited.** Every frozen resource
number (epochs, memory, wall time) is a formula evaluated against THIS run's
actual data, never a value carried over from a previous operating point. Where
feasible, two tiers: a deterministic worst-case calculation, plus a cheap
empirical probe (declared as calibration contact). A large disagreement between
the two tiers is a finding, not a nuisance.
*Incident: an inherited memory estimate concealed both an out-of-memory
condition and an unpredicted numerical degeneracy that the one-step worst-case
probe surfaced immediately.*

**G6 — Grading integrity.** Ground truth is constructed or independently
authored: a model never grades a bench it sat; golds are planted / hand-built
where possible and reproduced exactly by the instrument's self-tests before it
touches real subjects. If the task extracts or attributes content, the gate
must police the SOURCE of each claim, not just its existence — existence checks
auto-pass wrong-attribution errors.
*Incident: a span-existence gate passed 100% of an extractor's outputs while
the extractor was restating one speaker's statements as another's — every span
existed verbatim; the attribution was wrong.*

**G7 — Verbatim quotes for imported directional claims.** Any directional,
sign, or comparative claim imported from literature into the design must carry
a verbatim quote of the sentence or equation it rests on, verified against the
primary text.
*Incident: a literature sweep summarized a paper's fitted law with the sign
inverted ("predicts LOW forgetting" where the fitted coefficient said HIGH).
The design tension it created was fictional; only reading the primary text at
freeze time caught it.*

**G8 — Declare all calibration contacts.** Any pre-freeze run (smoke test,
probe, anchor measurement) is declared in the spec. Self-tests on constructed
inputs are instrument calibration, not experiment contact; running any swept
cell before the freeze commits is contact, and is forbidden.

## The division of labor (if delegating the spec-writing)

The mechanical skeleton is delegable: artifact schema, sanity-check
boilerplate, budget arithmetic, run-matrix bookkeeping. The judgment kernel is
not: hypothesis and null, the bars, the verdict rule, the metric formulas.
Whoever holds the judgment kernel runs the gate.
