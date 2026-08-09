# Literature scope discipline

A skill for reading the research literature without being fooled by it - the
source-facing sibling of [`theory-formation-discipline`](../theory-formation-discipline/).
That one keeps a capable model honest while it *reasons*; this one keeps it honest
while it *reads papers, runs novelty checks, and cites sources*.

## The problem this addresses

A capable model (Opus 4.8 and similar) inverts the correct reading reflex on
formal sources. The more a document carries the surface markers of rigor - LaTeX,
theorem-lemma-proof structure, heavy formal apparatus, an arXiv ID - the *less*
critically the model reads its actual reach, adopting the authors' own framing of
how far the result extends. The authority is typographic, and the model treats it
as epistemic.

Compiled from two real failures in one session, both caught only after a human
pushed back:

- An **existence proof** (generic-parameter three-layer ReLU networks) transmitted
  as a **universal** claim, closing a research question it did not close.
- An **architecture-specific** result (positional-encoding neural fields, 2D
  signed-distance functions) generalized to **language models** the paper never
  touched.

Both are the repo's signature failure - an inference stated as fact without the
check - wearing literature-shaped clothes.

## What's here

- **[`SKILL.md`](SKILL.md)** - the discipline: one bias to name (formal
  presentation lowers scrutiny when it should raise it), seven moves (name the
  population; existence-vs-universal; is there code; same-author cross-check; does
  the machinery point at your question; watch the vocabulary collision; say what
  you verified), and a **novelty-sweep protocol** for the symmetric failure -
  declaring a research gap open on shallow absence. Run in a fresh/cold context
  when the stakes are a novelty verdict.

## When it fires

Before citing a paper as settling a question; before declaring a research
direction open; when running a literature or novelty sweep; whenever a decision is
about to rest on "the paper says X." Especially relevant once AI-assisted work
moves from the software layer into the model layer and academic publishing, where
reading papers wrong is most expensive and least visible.
