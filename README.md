# Barzin's Claude Code Improvements

Skills, hooks, and standing rules that make Claude Code verify things instead of guessing.
Each one was written after a specific failure in real production work with Opus 4.8, Opus 5
or Opus 5.5, and each says which failure. The Contents table names the model each one was
written against.

## What's new

Added in the Opus 5.5 era. Older additions and changes are in [`CHANGELOG.md`](CHANGELOG.md).

| Date | Directory | What it does |
|---|---|---|
| 2026-11-11 | [`heartbeat/`](heartbeat/) | `/heartbeat` keeps a session working between operator messages. A session-only cron job fires a fixed protocol (count, orient from a file, run checks, zoom out against the goal, take one verified step, record STATE) against a per-work file, so the work survives compaction. A hook re-creates the job after a restart and makes compaction summaries carry unrecorded state. |
| 2026-11-11 | [`context-winddown/`](context-winddown/) | A mod that, past a context threshold (default 450000 tokens), asks the agent to finish its step and save state, then compacts when the agent calls `ready_to_compact` and ends its turn. Automatic compaction can fire between two tool calls with no chance to save anything. |
| 2026-10-23 | [`deneuralyzer/`](deneuralyzer/) | After shipping: each stop on a real input is recorded as a fixture and fixed at the owner of its class, and fixes are judged by how they do on inputs they were not made from. |

Most of them target the same behaviour: **a capable model states an inference as a fact
without checking.** It will describe how your code is wired without reading it, and report
work as verified without running it. Push back and it identifies its own error immediately,
which means the capability was there the whole time. What's missing is something that fires
before the claim ships.

Two entries target a different failure with the same origin. Trained-in epistemic care is
the right reflex when a claim is uncertain and the wrong one when the answer is short and
known, and it does not distinguish: the output arrives correct, hedged, structured, and
unreadable. `response-length-calibration/` is that rule, and `per-model-discipline/` is the
mechanism for applying it to one model family without imposing it on the others.

## Contents

| Directory | What it does | Form | Targeted at |
|---|---|---|---|
| [`ground-skill-verifier/`](ground-skill-verifier/) | `/ground` turns assumptions about your codebase into verified facts before any code is written. A cold verifier subagent then re-checks the evidence. | skill + agent | Opus 4.8 |
| [`seam-proof-build/`](seam-proof-build/) | Keeps that discipline running *during* the build: every load-bearing step proven by a real run that could have failed. | skill | Opus 5 |
| [`deneuralyzer/`](deneuralyzer/) | After shipping: treats each stop on a real input as a training example and the code as the model, so fixes are mechanisms that generalize to unseen inputs, not special cases. | skill | Opus 5.5 |
| [`theory-formation-discipline/`](theory-formation-discipline/) | Nine moves for reasoning like a researcher without fooling yourself, plus a Stop hook that blocks "verified" claims with no verification behind them. | prose + hook | Opus 4.8 |
| [`literature-scope-discipline/`](literature-scope-discipline/) | The source-facing sibling of the above: read papers without being fooled by them. Names the bias that formal presentation lowers scrutiny, seven scope-checking moves, and a novelty-sweep protocol for the symmetric failure of declaring a gap open on shallow absence. | skill | Opus 5 |
| [`experiment-freeze-gate/`](experiment-freeze-gate/) | Eight checks between freezing an experiment design and spending compute on it. Catches specs that are internally broken but pass every downstream check. | skill | Opus 4.8 |
| [`delegated-build-stint/`](delegated-build-stint/) | Contract for handing build work to a subagent. Headline rule: a stint never takes custody of a long run. | skill + agent | Opus 4.8 |
| [`discipline-compliance-scanner/`](discipline-compliance-scanner/) | Mines your session transcripts and reports where standing rules were actually broken, with citations. | script | Opus 5 |
| [`stopping-rules/`](stopping-rules/) | Four `CLAUDE.md` rules for the moments the model stops too early: stale world facts, patching without a diagnosis, shallow answers, made-up estimates. | prose | Opus 5 |
| [`response-length-calibration/`](response-length-calibration/) | The moment it stops too late. A correct answer wrapped in document prose - bolded lead-ins, three-part framings, hedges about intent that was already plain. | prose | Opus 5 |
| [`standing-corrections/`](standing-corrections/) | Three `CLAUDE.md` rules for defaults that are reasonable in general and wrong in one specific place: trusting inherited code over a failing test, citing the PDF instead of the paper, varying wording inside a fixed vocabulary. | prose | Opus 5 |
| [`heartbeat/`](heartbeat/) | `/heartbeat` keeps a session working between operator messages: a session-only cron job fires a fixed protocol against a per-work file of goal, constraints, checks, queue and STATE, and a hook re-creates the job after restarts and compactions. | skill + hook | Opus 5.5 |
| [`context-winddown/`](context-winddown/) | At a context threshold, asks the agent to finish its step and save state, then compacts when the agent says it is ready, instead of wherever automatic compaction fires. | mod | Opus 5.5 |
| [`per-model-discipline/`](per-model-discipline/) | Per-model-family instructions injected into the user turn, read from payload files. Gates a rule to one family, and keeps it out of subagent contexts. | hook + installer | Opus 5 |

## Install

**[`INSTALL.md`](INSTALL.md) is written to be executed by an agent.** Point your Claude Code
at it and it will do the rest:

```
Read https://raw.githubusercontent.com/BarzinL/barzins-cc-improvements/main/INSTALL.md
and install the parts that fit this project.
```

By hand: skills go in `.claude/skills/<name>/SKILL.md`, project-local or global
(`~/.claude/skills/`), agent definitions in `.claude/agents/`, prose into your `CLAUDE.md`.
Each directory's README has the exact paths and an example invocation. Three that differ:

```bash
# per-model-discipline - has an installer; dry run by default, self-checks after applying
python3 per-model-discipline/install.py --scope global
python3 per-model-discipline/install.py --scope global --apply

# discipline-compliance-scanner - just run it
python3 discipline-compliance-scanner/scan.py --all

# verification-claim-gate - a Stop hook, needs registering in .claude/settings.json
# see theory-formation-discipline/verification-claim-gate/README.md
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

## Caveats

None of this makes the model smarter. It makes it more honest about what it actually knows,
by moving self-correction from after-you-push-back to before-it-speaks.

Most of these are self-enforced, meaning the agent walks itself through them and can skip
them. Only the two hooks and the scanner are mechanical, and one of those two only delivers
a rule rather than checking it. Each README labels which kind it is, because calling a
self-enforced discipline a guarantee would be the exact failure these exist to prevent. That
is also why `discipline-compliance-scanner` exists: run against real work, it found
bright-line rules broken hundreds of times by an agent that had "known" them throughout.

MIT licensed. Written against Opus 4.8, Opus 5 and Opus 5.5; the disciplines are model-agnostic, and
the transcript paths and payload shapes are Claude Code specific.
`response-length-calibration` came out of Opus 5 work specifically - the coding was strong
enough that response verbosity became the bottleneck, which is not where the earlier entries
were aimed.
