# Stopping rules

Four rules to paste into your `CLAUDE.md`. Each one replaces a point where the model stops
working too early.

The default stopping condition is "this output looks sufficient." It gets satisfied long
before the work is done, and from the inside it feels the same as being finished: a plausible
answer to a hard question reads like a correct one, and a number pulled from nowhere reads
like an estimate.

| Rule | Stops when | Should stop when |
|---|---|---|
| [World-state claims have a timestamp](#1-world-state-claims-have-a-timestamp) | it sounds like domain knowledge | verified live |
| [No reactive patching](#2-no-reactive-patching) | the symptom changed | the mechanism is identified |
| [Recursive depth](#3-recursive-depth-on-load-bearing-questions) | the answer is good enough | one more level wouldn't change the decision |
| [Estimating dev timelines](#4-estimating-dev-work-timelines) | a number was requested | the unknowns are enumerated |

All four are self-enforced. No hook enforces them; see the note at the bottom for why.

---

## 1. World-state claims have a timestamp

```
**World-state claims have a timestamp; training data is a prior, not knowledge.**
Separate claims that are *stable* (math, mechanism, physics, code in this repo,
settled law) from claims about the *state of the world* - what products exist, what
they cost, adoption rates, free-tier limits, platform/OS behaviour, market norms, who
the competitors are, what a given profession's workflow looks like. The second class
decays, and it decays fastest exactly where it is most load-bearing. So: when a
decision hinges on a world-state claim, verify it live before stating it - search,
fetch the primary source, or read the current artifact. Do not launder a plausible
prior into an assertion because it sounds like domain knowledge; fluency is not
currency. When a world-state claim cannot be verified, say so and date it ("as of my
training data, which is stale for this"). The tell that this rule is being violated:
a confident, specific, unsourced description of how some part of the world currently
works. If the user challenges an inference on exactly these grounds, treat that as
correct by default and go check, rather than defending the prior.
```

**Why.** A search-fallback architecture got designed around the Brave Search API's free
tier, using a remembered "1,500+ queries/day free." Reality: 5,000/month in mid-2025,
2,000/month after that, then no free tier at all for new signups by early 2026. The
remembered number was wrong about the quota and about the tier existing.

Three things generalize from it:

- **Errors run optimistic**, and optimistic errors survive review. A cost model that comes
  out cheaper than expected doesn't get a second look.
- **Grandfathering splits reality.** Existing accounts keep old terms that new signups
  can't get, so even a true first-hand anecdote doesn't transfer to a recommendation.
- These facts get consulted at **architecture forks**, which is where being wrong costs the
  most.

The rule got written later, after a non-technical version of the same thing: confidently
describing how a particular profession currently handles inbound phone calls, entirely from
priors. The user's objection was the useful part, that training data is static and the world
isn't. Checking found the picture had changed. Producing that description didn't feel like
guessing, which is why the rule names a tell instead of trusting the feeling.

Partly mechanizable in principle (a present-tense pricing or product claim with no tool call
behind it in the same turn), in the spirit of the
[verification-claim gate](../theory-formation-discipline/verification-claim-gate/). Not built.

---

## 2. No reactive patching

```
## ⚠ CRITICAL - NO REACTIVE PATCHING

**When a bug fix doesn't work or produces a new symptom, stop and read the code.** Do
not reach for another patch. Reason from first principles - identify the exact
mechanism, write out the diagnosis explicitly, and confirm it is correct before
implementing anything. Speculative patching causes regressions, wastes time, and
forces code rewinds. If the cause is uncertain, say so and ask.
```

**Why.** A fix lands, the check still fails or fails differently, and the next action is
another edit. Each patch looks reasonable on its own. The damage isn't the wasted attempts:
patch *n* gets written against a mental model that patch *n-1* already invalidated, so you
get regressions in code that worked, and eventually a rewind that throws out the good changes
with the bad.

A new symptom after a fix is evidence about the mechanism. Patching immediately spends that
evidence instead of reading it.

The requirement to **write the diagnosis out** is the part that does the work, because an
unwritten diagnosis is indistinguishable from not having one.

**Deliberately not mechanized, and this was tested.** The
[discipline-compliance-scanner](../discipline-compliance-scanner/) tried to detect this from
transcript shape (`edit → failed command → re-edit of the same region`) and failed. That
signature is identical to ordinary iterative development. The signal is in the edit contents
and the reasoning, so it needs an LLM judge or nothing.

---

## 3. Recursive depth on load-bearing questions

```
**Recursive depth on load-bearing questions.** A first-order answer to anything that
steers real compute, a design that will be built, or a diagnosis that will drive a fix
is a stopping point to NOTICE, not to stop at. Take the next recursion: apply the same
analytical operation to its own output, one level deeper or one domain wider, along
whichever axis is live - evidence (the artifact in hand -> primary sources), mechanism
(the function -> its private internals and the assumption it breaks), implication (the
conclusion -> what it changes downstream), or premise (the claim -> the unstated
assumption holding it up). The recursion often reframes the question into the sharper
one it implies. Base case: recurse until the next level would no longer change the
decision - decision-irrelevance is the stop, NOT "the answer is good enough."
```

**Weaker than the other three, and flagged as such.** There's no single incident behind it.
It came from noticing that first-order answers to load-bearing questions were reliably
improvable on request, which makes the stop a habit rather than a limit. Take it or leave it
on that basis.

What makes it more than "try harder" is the **base case**. "Think more deeply" has no
termination condition and degrades into padding. Decision-irrelevance is checkable: name what
the next level would examine, then ask whether any plausible finding there changes what you
do. If not, stop. It also licenses stopping immediately on questions that aren't load-bearing.

In practice the payoff usually isn't a deeper answer, it's a **reframed question**. Recursing
on premise tends to surface that the original question was the wrong one.

---

## 4. Estimating dev-work timelines

```
**Estimating dev-work timelines.** LLM calendar estimates fail in a predictable
direction: writing the code compresses enormously with LLM assistance, but
**verification cycles do not** - builds against real hardware, driver quirks,
numerical bugs that only show as degraded output, deploy round-trips, anything
wall-clock-bound on an external system. Rules:

1. Never answer in human-calendar units ("a few weeks"). Estimate in **verification
   cycles / work sessions**, and name which loop dominates the wall clock.
2. An estimate for non-trivial work is not quotable until a scoping pass has converted
   its unknowns into an enumerated checklist (diff the op lists, count the call sites,
   list the missing kernels). Before that it is vibes - say so and do the scoping pass
   first.
3. State the conditional the estimate hinges on, explicitly ("2-4 sessions IF the
   hybrid-attention path reuses existing SYCL ops"). The conditional, not the number,
   is the honest content of the estimate.
```

**Why.** Estimating a port of model-inference code to different GPU hardware. Writing the
code is genuinely fast, and the estimate anchors on it because that's the part the model can
simulate. What actually ate the clock: builds against real hardware, driver-specific
behaviour, and numerical bugs that raised no error and only showed up as quietly degraded
output. None of that compresses, and the last kind gets found by noticing, which you can't
schedule.

The general failure is estimating from the part you can see. The model has vivid access to
how long code takes to write and none to how long the hardware takes to disagree with it, so
estimates skew low, worst in the cases with the most external dependencies.

Rule 2 carries the weight: it converts "how long" from a prediction into a question about the
present, namely what specifically is unknown right now, which grounding can answer. Rule 3 is
the honesty clause, since an estimate given without its conditional gets heard as a
commitment.

---

## Why none of these are hooks

The other tools in this repo check a **claim**, so they can be checked against the claim's
content. These check a **stop**, which means checking against work that was never done, and
absent work leaves no trace in a transcript. Section 2 documents the one attempt to do it
anyway and why it failed.

Rule 1 also covers a gap nothing else here reaches. Every other tool grounds a claim against
something local: the code, the run, the artifact, the transcript. A claim about the state of
the world has no local referent, so reading the repository can never catch it.
