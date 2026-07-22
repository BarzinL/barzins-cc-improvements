# Discipline Compliance Scanner - Spec

Measure how well an agent (me, Claude Code) actually obeyed the standing discipline,
by mining its own session transcripts. The disciplines in this repo (`/ground`,
`seam-proof-build`, the `feedback_*` rules in project memory, the `CLAUDE.md` "never do"
list) are all *written*. Nothing checks whether they were *followed*. This closes that
loop: transcripts in, ranked list of violations out, with clickable citations.

The promotion gate is human. The scanner proposes; the operator decides what to fix in the
discipline artifacts (or in behavior). No autonomy.

## The keystone finding (why this is two tools, not one)

Before writing this spec, a throwaway probe tested whether a discipline violation can be
detected mechanically from a transcript. It split the rule set cleanly in two, and the
split is the whole architecture:

**Class 1 - bright-line rules.** A specific token or tool is forbidden outright. Detection
is a deterministic scan over tool calls with ~zero false positives. Proven on 177
transcripts of real work:

| Rule | Raw hits |
|---|---|
| em-dash written into a file | 926 |
| `sqlite3` on `@sessions/` without `-readonly`/`immutable` | 89 |
| `AskUserQuestion` called | 10 |
| `git push` (no-remote repo) | 1 |

**Class 2 - judgment rules.** The violation is defined by *content and reasoning*, not by
any token: `no_reactive_patching`, `grounding_is_default`, `no_false_scoping`. The probe
tried to detect reactive-patching structurally (edit -> failed command -> re-edit of the
same file, no read between). The crude form fired 13 times, all false positives (edits far
apart in long sessions). Tightened to a 3-event window it fired once - on a *prose doc*,
still a false positive. The signal that makes it a violation - is it code, is the second
edit speculative, did the failure cause it - lives in the edit contents and the reasoning
text, which tool names and paths do not carry. **Structural detection fails for this
class.** It needs an LLM-judge reading the actual spans.

Had this been planned as one "grep the transcripts" tool, it would have silently failed on
exactly the judgment rules that matter most. The probe is why we know that up front.

## Increment 1 - bright-line scanner (this directory, built first)

Deterministic. Config-driven rule table. For each transcript, walk the tool-call stream
and fire rules. Output: per-rule count + ranked list + up to N sample citations
(transcript basename, a snippet) so each hit is eyeball-checkable. No LLM, no cost.

Rule types (data, not code, to add a rule):
- `bash_regex` - Bash command text matches `pattern`, optionally not `exclude`.
- `tool_name` - any use of a named tool.
- `write_regex` - authored content (`Edit.new_string` / `Write.content`) matches `pattern`.

Initial rule set is derived from the `CLAUDE.md` "never do" list plus the memory
`feedback_*` bright-line rules. See `RULES` in `scan.py`.

Known false-positive sources, reported not silently dropped:
- em-dash inside content I pasted/quoted from an external source (a paper, a diff) rather
  than authored. Reported with samples so the operator can discount.
- `git push` / `sudo` appearing inside a heredoc or an echo explaining *not* to do it.

These are why the output shows samples, and why counts are labelled "raw".

Later: the same scanner runs as a **pre-commit / pre-write hook** to catch a bright-line
violation *before* it lands (the em-dash before it's written, not 926 times after).

## Increment 2 - LLM-judge miner (not built yet)

For the judgment class. A pass that feeds an LLM bounded transcript spans (a failure and
the surrounding reasoning/edits) and asks whether a named rule was violated, returning a
verdict + the span as citation. This is Self-Harness "weakness mining" applied to our own
discipline: cluster the confirmed violations by rule, rank by frequency, surface clusters
that map to *no* existing rule as candidates for a new one. Needs a cost budget and a
careful judge prompt; deferred until Increment 1 is in use.

## What this deliberately is not

- Not autonomous. It never edits a discipline artifact. It reports; the operator promotes.
- Not a grader the loop optimizes against (that would invite reward-hacking). It is a
  read-only audit run on demand.
