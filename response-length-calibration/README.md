# Response-length calibration

A `CLAUDE.md` rule for a failure that is not epistemic. Every other entry in this
repository checks a **claim** - was it verified, was the run real. This one checks
**form**: an answer that is correct in every sentence and still unreadable.

The failure, in the operator's words after three corrections in one day: *"too verbose,
hard to read, doesn't cut to the point, responses are almost anxious about what my intent
might be even though it's fairly clear... the coding is excellent, but the responses are
like a punch in the face every time."*

That is the shape worth naming. The coding was not the problem. Strong technical output
arrived wrapped in structured essay prose - bolded lead-ins, sectioned arguments,
three-part framings, enumerated caveats, defensive qualifiers about what the request might
have meant - and the wrapper became the bottleneck. A chat message is read as
conversation, not as a document, so document furniture in a two-sentence exchange costs
the reader real time and conveys nothing.

It is a plausible side effect of training for epistemic care. Hedging, disclaiming, and
laying out the option space are the right moves when a claim is uncertain and the wrong
ones when the answer is short and known. The reflex does not distinguish.

## The rule

Copy into `CLAUDE.md`:

> **Length tracks new information, not thoroughness.** A discussion question gets a
> conversational answer, not a document. Answer the literal question in the first line -
> no setup, no restating the question, no "this splits three ways". Default ceiling is a
> few lines; length is earned by an explicit request for a write-up, spec, or plan, never
> by a rich topic. No bold lead-ins, section headers, or three-part framings in
> conversation; those belong in READMEs, specs, and commit messages. Do not restate a
> stated constraint back before acting on it - let it silently prune the option space. Do
> not pre-empt intent that is already plain, and do not close with "does that land?" when
> the constraint already answers it.
>
> Keep, at whatever length it takes: measured numbers, file:line evidence, the causal
> mechanism stated once, decisions and why, anything that changes what the reader does
> next, and honest uncertainty. Cut: the same mechanism restated in different words,
> recaps of what the reader just said, lists of what you are *not* doing, unrequested lay
> analogies, closing summaries.
>
> Reports of completed work stay short - the detail belongs in the commit message, the
> code comments, or a README.
>
> **The tell that this is about to go wrong:** you have written a sentence whose job is to
> organise the answer rather than to be part of it.

Two things that keep the rule from over-correcting. Brevity is a ceiling on *packaging*,
not on evidence: numbers, mechanisms and uncertainty stay in at full length. And it
applies to conversation, not to the artifacts - a spec, a plan, or a README that was
asked for should be as long as it needs to be.

## Enforcing it per model

Prose in `CLAUDE.md` applies to every model that reads it, including the small ones being
handed procedural work, and to whatever the harness surfaces it to. If you want it gated
to one family and kept out of subagent contexts, `../per-model-discipline/` injects a
compressed version of this rule as `model-discipline-payloads/opus.md` at
`cadence: every-turn`.

That file is the injectable form; this README is the canonical statement. Edit the payload
to match if you change the wording here.

## Which is it

Self-enforced. The hook route makes the rule *present* on every turn, which is more than a
memory note that decays at the first compaction, but nothing mechanically checks the shape
of the prose that comes out. Response length is at least measurable from transcripts -
assistant characters per user character, header and bold density in turns that are not
documents, share of turns ending in a confirmation question - which is more than can be
said for the disciplines in `../stopping-rules/`. No scanner rule ships for it yet.
