---
name: literature-scope-discipline
description: Read the research literature without being fooled by it. The source-facing sibling of theory-formation-discipline - that one keeps you honest while REASONING; this one keeps you honest while READING papers, running novelty checks, and citing sources. Compiled from real failures where a capable model treated a formally-presented paper (LaTeX, theorems, an arXiv ID) as MORE authoritative and read its actual reach LESS critically - transmitting an existence proof as a universal claim, and an architecture-specific result as a general one. Seven moves, one bias to name, and a novelty-sweep protocol. Invoke before citing a paper as settling a question, before declaring a research gap open, when running a literature/novelty sweep, or whenever a decision is about to rest on "the paper says X."
---

# literature-scope-discipline - read papers without being fooled by them

`theory-formation-discipline` keeps a capable model honest while it *reasons*.
This is its source-facing sibling: it keeps the same model honest while it
*reads the literature* - citing papers, running novelty checks, deciding whether
a research direction is open. Both target one failure with one origin: **a claim
stated as fact without the check that would ground it.** Here the claim is about
what a paper *says* and *covers*, and the check is reading its actual scope.

Every move below was compiled from a real research session, not derived from
principle. The session was an AI-assisted research program moving from the
software layer into the model layer and academic publishing - exactly the setting
where reading papers wrong is most expensive and least visible.

## The bias this exists to catch (name it every time)

**The surface markers of rigor make the reader LESS critical when they should
make them MORE.** LaTeX typesetting, a theorem-lemma-proof skeleton, heavy formal
apparatus, an arXiv ID, a `.tex`-compiled look - these are evidence of *effort and
formalism*, not of *correctness* and *especially not of relevance to your
question*. A capable model reliably inverts this: the more authoritative a paper
looks, the more it adopts the authors' own framing of how far the result reaches.
The authority is typographic.

The tell that it is happening: you find yourself writing "the paper proves X" or
"this is settled" or "the field has shown Y," about a document you were impressed
by, without having asked what population X is actually about. The correct reflex on
an impressive-looking paper is *more* scope-suspicion, not less.

Two failure incidents this was compiled from, both in one session:
- An **existence proof** about generic-parameter three-layer bottleneck ReLU
  networks ("there exists a network where composition is non-local") got
  transmitted as a **universal** claim ("composition doesn't compose"), closing a
  research question it did not close.
- An **architecture-specific** result (symmetry readout on positional-encoding
  neural fields, demonstrated on 2D signed-distance functions) got generalized to
  **language models**, which the paper never touched.

Both were caught only when a human pushed back. The point of this skill is to move
that catch to before-send.

## The seven moves

Run these as a standing self-check before any turn that rests on a paper. They are
a posture, not a checklist to recite - they only have content when a real decision
is about to rest on the reading.

### 1. Name the population. Is it yours?

Before transmitting anything from a paper, answer: *what population of objects is
this result actually about?* Generic (random) parameters, or trained networks? One
constructed example, or a class? A specific architecture (this activation, this
depth, this positional encoding), or all of them? Then: **is that population the
one my question is about?** A result about generic parameters says little about
trained networks; a result about neural fields says little about transformers. The
words can match while the populations do not.

### 2. Existence or universal?

"There exists an X where P" is not "P holds for all X." A single constructed
counterexample proves existence, not universality - and the interesting case (the
structured, trained, or deliberately-built object) is often exactly the one the
existence proof excludes. Do not let "they showed P can happen" become "P is how it
works." Read the quantifier, not the abstract's summary of it.

### 3. Is there code? A pure-theory negative result is weaker than it looks.

A theoretical result that was never checked against a real trained system is
weaker, for engineering purposes, than its formal confidence implies - and its
*absence of code is often the empirical test you can run*. If a paper proves
something cannot work but never built it, "build it and measure" is an open path,
not a closed one. Check for a repo before treating a negative result as a wall.

### 4. Same-author / same-machinery cross-check.

Two papers that look like a field consensus - or a field *tension* - may be one
lab's narrow program using one apparatus. Check authorship and method before
weighting a cluster as "the field has shown." A tension between two papers by the
same two authors, same month, same formalism, same parameter regime, is one
program's internal structure, not a community result. It also tells you the scope
is narrow: a lab exploring its own machinery, not a broad finding.

### 5. Does the machinery point at what you care about?

Sophisticated apparatus can be aimed at a question adjacent to yours. A paper can
be rigorous, impressive, and *orthogonal*. Ask what the formalism actually
delivers - is it about what the network *computes* (often what you care about), or
about its *parameterization* / identifiability / redundancy (often not)? Heavy
tools pointed at the wrong target should lower your use of the paper, not raise it
because they are heavy.

### 6. Watch for the vocabulary collision.

The sharpest disorientation comes when a paper uses your exact words for a
different referent. "Compose," "symmetry," "capability," "representation" each name
more than one thing. A paper can be *locally* about "symmetry composition" in every
sentence while *globally* answering a different question than yours. When a paper
feels like it is subtracting clarity rather than adding it, suspect a term doing
double duty - and pin down which meaning each side is using before citing it.

### 7. Say what you actually verified.

Mark every transmitted claim with how you know it. Read the full text, or only the
abstract? (Abstracts systematically overstate reach.) Full-text via a parser that
actually rendered it, or a fetch that returned partial/corrupted content? If you
could only read the abstract, say so and treat the reading as provisional. "The
abstract says" and "I read the paper and it establishes" are different evidence
classes and must not be collapsed.

## The novelty-sweep protocol

Declaring a research direction *open* (unoccupied by prior art) is a load-bearing
claim that decides whether real work goes forward. It has a symmetric failure to
the bias above: there, impressive *presence* fooled the reader; here, shallow
*absence* fools them. **One search returning nothing is weak evidence of a gap, not
proof of one.** A gap declared on a single query framing is how a program gets
built on ground someone already occupied under different vocabulary.

To claim a gap is open:

1. **Run at least 5-6 different query framings**, varying vocabulary aggressively
   (synonyms for the concept, the method, and the object). The thing you are
   looking for, if it exists, was likely named differently than you would name it.
2. **Full-text every on-target hit** before concluding - abstracts overstate.
3. **Apply moves 1-6** to each hit: scope, quantifier, code, authorship, target,
   vocabulary.
4. **Distinguish adjacent-but-distinct from the actual claim.** The nearest
   existing field is usually a cousin of your idea, not your idea - state the
   crisp line between what exists and what would be novel.
5. **A found prior-art is a good outcome.** It saves wasted work. Do not read
   optimistically toward "open"; the encouraging reading is the dangerous one.
6. **State the verdict with its confidence and what would falsify it.** "Not
   found in a thorough multi-framing sweep, gap plausible" is honest; "the ground
   is open" on one search is not.

Run this in a **fresh context** (a cold subagent) when possible - a tired session
at the end of a long thread will pattern-match toward the conclusion it already
wants. Cold execution is closer to an independent check.

## Relation to the other disciplines

- `theory-formation-discipline` is the reasoning-facing half; this is the
  source-facing half. Same origin failure (unverified claim shipped as fact),
  different object (a paper's content and reach rather than your own inference).
- `ground` / `seam-proof-build` verify claims about *your code*. This verifies
  claims about *someone else's paper*. All three drive the same column - "things I
  asserted but did not check" - to empty.
- The general rule underneath all of them: **verification that depends on
  remembering to be careful is not verification.** This skill is the standing
  check that fires before a paper-based claim ships, so the care does not depend on
  a human pushing back to trigger it.
