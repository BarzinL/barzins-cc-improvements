# Standing corrections

Three rules to paste into your `CLAUDE.md`. Unlike `stopping-rules/`, these do not target a
moment the model stops too early. Each one targets a **default that is reasonable in general
and wrong in a specific place**, where the wrongness is invisible from the inside because the
default behaviour looks like competence.

| Rule | Default | Why it is wrong here |
|---|---|---|
| [Suspect the code, not the test](#1-suspect-the-code-not-the-test) | trust inherited work, fix the failing assertion | the assertion is the only thing that noticed |
| [Cite the landing page](#2-cite-the-landing-page) | link the artefact you actually opened | the artefact is a pinned snapshot; the page is the paper |
| [One term per concept](#3-one-term-per-concept) | vary word choice for readable prose | in a fixed vocabulary, a synonym reads as a new concept |

All three are self-enforced. No hook checks them.

---

## 1. Suspect the code, not the test

```
When a test or behavior failure surfaces, investigate the code as a suspected real
regression BEFORE touching the test - assuming inherited work is correct is the
failure mode.
```

A failing test has two possible causes: the code broke, or the test is wrong. The second is
cheaper to fix and reads as the more likely one, because the surrounding code arrived already
written and looks deliberate. That asymmetry is the whole problem. Editing the assertion
resolves the symptom, produces a green run, and destroys the only signal that anything was
wrong.

The prior runs the other way. A test that passed before and fails now is reporting a change
in the code, and the code changed more recently than the test did. Inherited work being
plausible is not evidence it is correct; it is the reason nobody has checked it.

So: read the code path the test exercises, decide what the correct behaviour is, and only
then judge the assertion. If you do conclude the test is wrong, say which specific thing it
asserts incorrectly and why - a diagnosis, not a preference. "The test seems outdated" is the
sentence to distrust.

## 2. Cite the landing page

```
**arXiv:** always cite/share the canonical **version-less abstract** URL:
`https://arxiv.org/abs/<id>` (never `/pdf/`, never a `vN` suffix). The abstract page
resolves to the latest version and links every version + the PDF. Pin a version
(`vN`) ONLY when the user explicitly asks for a specific one.

When you download a PDF, the link you hand the user must still be the `/abs/` page -
and if the file you saved is an older version than the abstract page's latest, say so.

Prefer canonical/DOI/landing pages over deep file links for any paper source (not
just arXiv).
```

An agent that fetched `arxiv.org/pdf/2305.12345v2` will cite that URL, because it is the
thing it opened. The user then receives a permanent link to one frozen revision of a document
that is still moving. Later versions can revise the numbers the citation was invoking.

The abstract page is the paper's identity: it resolves to the latest version, links every
prior one, and carries the metadata a reader needs to judge the source. The PDF is one
rendering of one revision of it. This generalises past arXiv - DOIs and publisher landing
pages over direct file links, for the same reason.

The second clause is the one that gets skipped. If you downloaded v1 and the abstract page
now shows v3, the reader must be told, because your summary describes a superseded document
and nothing in the `/abs/` link reveals that.

## 3. One term per concept

```
One term per concept, never a synonym for variety - once a project fixes a word
(rung, stint, freeze, gate), reuse it exactly in prose, code, and docs. Elegant
variation reads as a NEW concept and silently forks the vocabulary.
```

Good prose style says vary your word choice. In a project with a fixed vocabulary this is
actively destructive. If the codebase says `rung` and the summary says `step`, `stage`, and
`phase` for the same thing, a reader cannot tell whether those are four names for one concept
or four distinct concepts - and neither can the next agent reading that summary as context.

This is the one rule here borrowed from an existing standard: ASD-STE100 Simplified Technical
English enforces one-word-one-meaning for exactly this reason, in documentation read by
non-native speakers and fed to machine translation. Ambiguity that a fluent reader resolves
silently is ambiguity a translation engine resolves wrongly. The same holds for an agent
reconstructing your project's model from prose.

The rest of STE does not transfer - its ~900-word approved dictionary is built for aerospace
maintenance procedures, and its fixed reading level cannot adapt to the reader. But the
consistency rule is domain-independent and costs nothing.

Applies to identifiers as much as prose: if the concept is `freeze` in the spec, it is not
`lock` in a function name.

---

## Install

Paste any of the three code blocks above into your `CLAUDE.md` - global (`~/.claude/CLAUDE.md`)
or project-local. They are independent; take one without the others.
