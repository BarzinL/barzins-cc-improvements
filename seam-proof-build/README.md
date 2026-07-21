# Claude Code: `/seam-proof-build` skill

The through-build companion to [`/ground`](../ground-skill-verifier/). Grounding
turns the agent's assertions about the code into verified knowledge *before* it
writes. This keeps that same discipline running *during* the build: every
load-bearing step is proven by a real run that could have failed, at the seam, the
moment construction reaches it.

## The failure it closes

`/ground` fixes the agent guessing about the codebase before it acts. But the same
disease - stating an inference as a fact without checking - walks back in the door
the instant coding starts, now wearing build-shaped clothes:

- "the supervisor returns the right shape" - never run
- "Firefox gets past the wall" - tried once, on one URL, generalized to always
- "the containment gate passes" - never checked that it *can* fail
- "the refactor is harmless" - the test that proved the seam was never re-run

Each is a claim the build rests on. Each is settleable by one command that either
passes or fails. The discipline is firing that command when the build reaches the
claim, not hoping at the end.

## The six moves

Each was compiled from a real build session, not derived from principle.

1. **Prove the keystone seam with a throwaway, before you formalize.** Find the
   single seam the whole design rests on and prove it with a disposable prototype
   first. If the architecture is wrong, you learn it at prototype cost - not after
   nine files exist on top of a false assumption.
2. **Probe generality - find where the claim stops being true.** A capability
   confirmed on one input is an anecdote. Run varied real inputs to find the case
   that breaks it; the boundary is the finding that changes the spec (a browser
   engine that beats a TLS-fingerprint wall but not a behavioral one - the *bound*
   is what stops the tool overclaiming).
3. **Negative-control every gate - prove the test can fail.** Run a gate against
   the exact thing it exists to catch and confirm it goes red. A gate you have
   never watched fail is theater; its later green proves nothing. Highest value on
   anything security- or correctness-critical, where a rubber-stamp check
   manufactures false confidence at the worst possible spot.
4. **Verify each seam bottom-up, in isolation, before stacking the next.** Prove
   each layer at its own boundary; then an end-to-end break localizes to the one
   seam you had not turned green yet. A seam you genuinely cannot exercise yet
   (needs a credential or privileged step) is named *blocked*, never assumed.
5. **Re-prove any seam you change.** A green test certifies the code it ran
   against. Edit that code - even a rename or import reorder - and the
   certification is stale until you re-run. A pass carried across a change is
   inference-as-fact with a time delay.
6. **Operational and security seams get proven too - by proxy if you can't run
   them.** A privileged command, a deploy step, a reboot/reload/crash transition, a
   service dependency, a persistence guarantee is a seam even though it doesn't look
   like code. If you can't run it (no sudo, needs a reboot), the obligation converts
   rather than disappears: author the exact check plus its pass/fail criterion, hand
   it to whoever can run it, and gate on the result - never a confident "run X" with
   no verification attached. For a security boundary the mandatory seam is the
   *failure* mode: put the system in the container-absent state and prove the
   contained process fails closed. The seams you can't run yourself get more rigor,
   not a pass - they're usually the highest-risk ones, and the ones that ship green
   and open.

The core rule underneath all six: **no step is done on the strength of reading
the code you just wrote.** A step is done when a command that was capable of
failing passed - and for the steps you can't run yourself, when the check you
authored was run by someone who could and came back green.

## How to use

1. Drop `SKILL.md` into `.claude/skills/seam-proof-build/` (project or global).
2. Invoke alongside grounding for build work, e.g.:

   `Build this with /ground then /seam-proof-build - prototype the load-bearing
   seam first, and test every step with a real run.`

   Or lean on it directly mid-build: `before you call that done, seam-proof it -
   what command did you run that could have failed?`

It pairs naturally with Ceiling 2 (stage for review before commit): the seam
proofs are exactly the evidence a reviewer needs, so a Ceiling-2 handoff becomes
"here is each seam and the run that proves it" instead of a narrative.

## What this is (and is not)

A **self-walked discipline**, not a harness guarantee - the same honesty label the
rest of this repo uses. It has one harness backstop: the
[verification-claim gate](../theory-formation-discipline/) Stop hook fires when the
agent claims "verified" without a run, which is the core rule here enforced from
the outside. This skill is the agent-side discipline that keeps the hook from ever
needing to fire.

## How it relates to the other pieces

Same disease - an inference stated as fact without checking - caught at a different
point in the lifecycle:

- **`ground-skill-verifier`** grounds the agent's claims about the code *before it
  writes* them.
- **`seam-proof-build`** (this) grounds the agent's claims about what it *just
  built*, seam by seam, as it builds.
- **`experiment-freeze-gate`** grounds a design against itself before compute.
- **`delegated-build-stint`** grounds claims that cross a delegation seam.

`/ground` and `/seam-proof-build` are the matched pair for a single feature: one
owns the pass before the first line of code, the other owns every seam after it.
