# Barzin's Claude Code Improvements

Skills, hooks, and standing rules that make Claude Code verify things instead of guessing.
Each one was written after a specific failure in real production work with Opus 4.8, Opus 5
or Opus 5.5, and each says which failure. The Contents table names the model each one was
written against.

## What's new

Added in the Opus 5.5 era. Older additions and changes are in [`CHANGELOG.md`](CHANGELOG.md).

| Date | Directory | What it does |
|---|---|---|
| 2026-11-15 | [`hook-trial/`](hook-trial/) | Measures four hooks (claim gate, plan-reconciliation, placeholder-disclosure, task-grounding) on your own work. An optional trial file switches all four off in a random half of sessions, chosen from the session id; `compare_arms.py` then compares the two halves from the transcripts: unsupported completion claims that reached the user (judged by the claim gate itself), hook firings, output tokens per turn and follow-up messages, each with a bootstrap interval over sessions. Off by default; no trial has been run yet. |
| 2026-11-14 | [`task-grounding/`](task-grounding/) | A UserPromptSubmit hook that recognises performance, visual, scientific, multi-step and reader work from the prompt's words and adds one short directive per category, once per session: measure before and after, render and look, read sources before coding, write a plan file, and for a course, guide or long report, state the reading and the reader and show one piece before building the rest (added 2026-11-15). Keyword-matched with narrow patterns, so it misses some prompts and still misfires on others; not yet run live or measured. |
| 2026-11-14 | [`reference-store/`](reference-store/) | A format for a project's compiled domain reference (`docs/reference/`), in which every claim carries its source, the date it was read, and whether it was read at the source, taken from a secondary source, or inferred; and a checker that refuses untagged claims and finds the one entry a task needs. |
| 2026-11-14 | [`theory-formation-discipline/verification-claim-gate/`](theory-formation-discipline/verification-claim-gate/) | The claim gate, revised for Opus 5.5, now ties each claim to the check that would support it: a test claim needs a test command that did not fail, and a whole-file claim is compared with the reads. Reads count across the session and include `cat`, `head`, `tail` and `sed -n`, parsed per pipeline; whole-repository claims are flagged; "read through <directory>" and "read all four <documents>" are checked against the reads; speed and memory claims need a timing command. Adds `replay.py` to run a gate offline over your own transcripts. |
| 2026-11-14 | [`plan-reconciliation/`](plan-reconciliation/) | A Stop hook: when the session has a checklist at `<scratchpad>/plan.md`, a final report that leaves open items unmentioned is paused once, listing them to be reported as done, deferred or dropped. |
| 2026-11-14 | [`placeholder-disclosure/`](placeholder-disclosure/) | A Stop hook: placeholder code written this turn (`todo!()`, `NotImplementedError`, pass-only bodies, TODO/FIXME comments) that the final message does not disclose is listed by file and line, once. Includes a draft "blocked" `CLAUDE.md` rule, not installed. |
| 2026-11-14 | [`pasted-text-guard/`](pasted-text-guard/) | Finds invisible and bidirectional-control characters in text while keeping the joiners Persian, Arabic, Indic scripts and emoji need. A library and command line, not a hook: Claude Code 2.1.277+ already strips these before a hook would run. The README records that evidence and that pasted text goes unmarked when editor telemetry is off. |
| 2026-11-14 | [`request-fidelity-review/`](request-fidelity-review/) | Extracts the messages the user actually typed from a session transcript, and a reviewer subagent that gets only that extract and the diff, so review is against the user's words, not the implementer's summary. Trialled 2026-11-15 on five past cases of misread intent and three controls: caught 1 of 5, and most other flags were noise. Not recommended for installation as it is: its prompt forbids judging level, register and order, and run after the work is built it saves little. It must run as an agent type that does not load the user's memory. |
| 2026-11-11 | [`heartbeat/`](heartbeat/) | `/heartbeat` keeps a session working between operator messages. A session-only cron job fires a fixed protocol (count, orient from a file, run checks, zoom out against the goal, take one verified step, record STATE) against a per-work file, so the work survives compaction. A hook re-creates the job after a restart and makes compaction summaries carry unrecorded state. |
| 2026-11-11 | [`context-winddown/`](context-winddown/) | A mod that, past a context threshold (default 450000 tokens), asks the agent to finish its step and save state, then compacts when the agent calls `ready_to_compact` and ends its turn. Automatic compaction can fire between two tool calls with no chance to save anything. |
| 2026-10-23 | [`deneuralyzer/`](deneuralyzer/) | After shipping: each stop on a real input is recorded as a fixture and fixed at the owner of its class, and fixes are judged by how they do on inputs they were not made from. |

The entries address three kinds of failure.

Most target a capable model stating an inference as a fact without checking it. It describes
how code is wired without reading it, and reports work as verified without running it. When
challenged it finds its own error at once, so the capability is present; what is missing is a
check that runs before the claim is made. `ground-skill-verifier`, `seam-proof-build`,
`theory-formation-discipline`, `literature-scope-discipline`, `experiment-freeze-gate`,
`delegated-build-stint`, `stopping-rules` and `standing-corrections` each place such a check
at one stage of the work, and `discipline-compliance-scanner` reads transcripts afterwards to
find where one was skipped.

Two target the shape of the answer rather than its truth. Trained-in epistemic care is the
right reflex when a claim is uncertain and the wrong one when the answer is short and known,
and the model applies it to both: the output arrives correct, hedged, structured and hard to
read. `response-length-calibration` is the rule, and `per-model-discipline` delivers it to one
model family without imposing it on the others.

The Opus 5.5 entries target work that runs longer than one conversation can hold.
`deneuralyzer` covers a pipeline after it ships: a fix made where a real input failed tends to
encode that input rather than its class, so the next unforeseen input fails too. `heartbeat`
and `context-winddown` cover a session working unattended for hours. Whatever the agent knows
only from the conversation survives a compaction only as far as the summary keeps it, so the
goal, queue and state live in a file the agent re-reads on every fire, and compaction runs
after the agent has written to that file rather than between two tool calls.

`task-grounding` and `reference-store` target the categories where Anthropic's Fable 5.2
system card reports Opus 5.5 furthest behind: performance optimisation, scientific
computing and visual work (§8.7). The category is decided by the prompt's words rather than
by the model noticing it is out of its depth, and domain facts come from a local reference
in which every claim says where it came from.

## Contents

| Directory | What it does | Form | Targeted at |
|---|---|---|---|
| [`hook-trial/`](hook-trial/) | Switches four hooks off in a random half of sessions and compares the two halves from the transcripts, with intervals over sessions. | switch in four hooks + script | Opus 5.5 |
| [`task-grounding/`](task-grounding/) | Adds one directive per category of work (performance, visual, scientific, multi-step, work for a reader), chosen by keywords in the prompt, once per session. | hook | Opus 5.5 |
| [`reference-store/`](reference-store/) | A compiled domain reference in which every claim records its source, read date and how well it was checked, with a checker and a `--find` lookup. | format + script | Opus 5.5 |
| [`plan-reconciliation/`](plan-reconciliation/) | Pauses a turn once when the final report does not account for every open item of the session's plan checklist. | hook | Opus 5.5 |
| [`placeholder-disclosure/`](placeholder-disclosure/) | Pauses a turn once when placeholder code written this turn is not disclosed in the final message. | hook | Opus 5.5 |
| [`pasted-text-guard/`](pasted-text-guard/) | Detects hidden Unicode in text without flagging Persian, Arabic or emoji. | script | Opus 5.5 |
| [`request-fidelity-review/`](request-fidelity-review/) | Reviews a diff against only the user's own typed messages. Trialled: caught 1 of 5 misreadings; not recommended as it is. | script + agent | Opus 5.5 |
| [`context-winddown/`](context-winddown/) | At a context threshold, asks the agent to finish its step and save state, then compacts when the agent says it is ready, instead of wherever automatic compaction fires. | mod | Opus 5.5 |
| [`heartbeat/`](heartbeat/) | `/heartbeat` keeps a session working between operator messages: a session-only cron job fires a fixed protocol against a per-work file of goal, constraints, checks, queue and STATE, and a hook re-creates the job after restarts and compactions. | skill + hook | Opus 5.5 |
| [`deneuralyzer/`](deneuralyzer/) | After shipping: treats each stop on a real input as a training example and the code as the model, so fixes are mechanisms that generalize to unseen inputs, not special cases. | skill | Opus 5.5 |
| [`standing-corrections/`](standing-corrections/) | Three `CLAUDE.md` rules for defaults that are reasonable in general and wrong in one specific place: trusting inherited code over a failing test, citing the PDF instead of the paper, varying wording inside a fixed vocabulary. | prose | Opus 5 |
| [`literature-scope-discipline/`](literature-scope-discipline/) | The source-facing sibling of `theory-formation-discipline`: read papers without being fooled by them. Names the bias that formal presentation lowers scrutiny, seven scope-checking moves, and a novelty-sweep protocol for the symmetric failure of declaring a gap open on shallow absence. | skill | Opus 5 |
| [`response-length-calibration/`](response-length-calibration/) | The counterpart of `stopping-rules`: the moment the model stops too late. A correct answer wrapped in document prose - bolded lead-ins, three-part framings, hedges about intent that was already plain. | prose | Opus 5 |
| [`per-model-discipline/`](per-model-discipline/) | Per-model-family instructions injected into the user turn, read from payload files. Gates a rule to one family, and keeps it out of subagent contexts. | hook + installer | Opus 5 |
| [`stopping-rules/`](stopping-rules/) | Four `CLAUDE.md` rules for the moments the model stops too early: stale world facts, patching without a diagnosis, shallow answers, made-up estimates. | prose | Opus 5 |
| [`discipline-compliance-scanner/`](discipline-compliance-scanner/) | Mines your session transcripts and reports where standing rules were actually broken, with citations. | script | Opus 5 |
| [`seam-proof-build/`](seam-proof-build/) | Keeps the `/ground` discipline running *during* the build: every load-bearing step proven by a real run that could have failed. | skill | Opus 5 |
| [`experiment-freeze-gate/`](experiment-freeze-gate/) | Eight checks between freezing an experiment design and spending compute on it. Catches specs that are internally broken but pass every downstream check. | skill | Opus 4.8 |
| [`delegated-build-stint/`](delegated-build-stint/) | Contract for handing build work to a subagent. Headline rule: a stint never takes custody of a long run. | skill + agent | Opus 4.8 |
| [`ground-skill-verifier/`](ground-skill-verifier/) | `/ground` turns assumptions about your codebase into verified facts before any code is written. A cold verifier subagent then re-checks the evidence. | skill + agent | Opus 4.8 |
| [`theory-formation-discipline/`](theory-formation-discipline/) | Nine moves for reasoning like a researcher without fooling yourself, plus a Stop hook that pauses a turn once when its final message claims a check (tests pass, build passes, whole file or repository read, a measured speed-up) that the session's tool calls do not support. | prose + hook | Opus 4.8; hook revised for Opus 5.5 |

## Install

**[`INSTALL.md`](INSTALL.md) is written to be executed by an agent.** Point your Claude Code
at it and it will do the rest:

```
Read https://raw.githubusercontent.com/BarzinL/barzins-cc-improvements/main/INSTALL.md
and install the parts that fit this project.
```

By hand: skills go in `.claude/skills/<name>/SKILL.md`, project-local or global
(`~/.claude/skills/`), agent definitions in `.claude/agents/`, prose into your `CLAUDE.md`.
Each directory's README has the exact paths and an example invocation. Some that differ:

```bash
# per-model-discipline - has an installer; dry run by default, self-checks after applying
python3 per-model-discipline/install.py --scope global
python3 per-model-discipline/install.py --scope global --apply

# discipline-compliance-scanner - just run it
python3 discipline-compliance-scanner/scan.py --all

# verification-claim-gate - a Stop hook, needs registering in .claude/settings.json
# see theory-formation-discipline/verification-claim-gate/README.md

# task-grounding - a UserPromptSubmit hook, needs registering in .claude/settings.json
# see task-grounding/README.md

# reference-store - check a project's docs/reference/, or find the entry for a term
python3 reference-store/check_reference.py docs/reference
python3 reference-store/check_reference.py docs/reference --find "methylation"
```

## Where each one fires

- Before writing code: `ground-skill-verifier`
- While building: `seam-proof-build`
- After shipping, as real inputs fail: `deneuralyzer`
- Before spending compute: `experiment-freeze-gate`
- Across a delegation boundary: `delegated-build-stint`
- When reporting results: `theory-formation-discipline`
- After the fact, from transcripts: `discipline-compliance-scanner`
- At the moment of stopping: `stopping-rules`
- On every reply to you: `response-length-calibration`, delivered by `per-model-discipline`
- On a failing test, a citation, or a fixed term: `standing-corrections`
- Between operator messages, on a timer: `heartbeat`
- As the context fills: `context-winddown`
- When a prompt arrives, by category of work: `task-grounding`
- Before domain work, and whenever a source has been read: `reference-store`
- Across weeks of sessions, to measure four of the hooks: `hook-trial`

The first six check a **claim**, so parts of them can be enforced mechanically: the
verification-claim gate is a hook, the scanner is a program. `stopping-rules` checks a
**stop**, which means checking against work that was never done. One attempt to detect such
a rule from transcripts (reactive patching, from the shape `edit → failed command → re-edit`)
failed, because that pattern is indistinguishable from normal iteration. That line is where
hooks stop working and discipline is all you have.

`per-model-discipline` sits outside that split. It is mechanical about *delivery* - the
harness runs it, so the rule is present on every turn and does not decay at the first
compaction the way a memory note does - and says nothing about whether the rule was
followed. Worth keeping straight: a hook that reliably delivers an instruction is not a hook
that enforces one.

`task-grounding` is the same kind: it delivers a directive when the prompt's words put the
work in a category, and checks nothing. `reference-store` is mechanical about provenance
only. Its checker refuses a reference claim that does not say where it came from and how
well it was checked, and cannot tell whether the claim is true.

## Caveats

None of this makes the model smarter. It makes it more honest about what it actually knows,
by moving self-correction from after-you-push-back to before-it-speaks.

Most of these are self-enforced, meaning the agent walks itself through them and can skip
them. Only the hooks and the scanner are mechanical, the hooks added on 2026-11-14 have not yet
run in a live session, and the `per-model-discipline` hook only delivers
a rule rather than checking it. Each README labels which kind it is, because calling a
self-enforced discipline a guarantee would be the exact failure these exist to prevent. That
is also why `discipline-compliance-scanner` exists: run against real work, it found
bright-line rules broken hundreds of times by an agent that had "known" them throughout.

MIT licensed. Written against Opus 4.8, Opus 5 and Opus 5.5; the disciplines are model-agnostic, and
the transcript paths and payload shapes are Claude Code specific.
`response-length-calibration` came out of Opus 5 work specifically - the coding was strong
enough that response verbosity became the bottleneck, which is not where the earlier entries
were aimed.
