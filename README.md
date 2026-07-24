# Barzin's Claude Code Improvements

Skills, hooks, and standing rules that make Claude Code verify things instead of guessing.
Each one was written after a specific failure in real production work with Opus 4.8, and
each says which failure.

They all target the same behaviour: **a capable model states an inference as a fact without
checking.** It will describe how your code is wired without reading it, and report work as
verified without running it. Push back and it identifies its own error immediately, which
means the capability was there the whole time. What's missing is something that fires before
the claim ships.

## Contents

| Directory | What it does | Form |
|---|---|---|
| [`ground-skill-verifier/`](ground-skill-verifier/) | `/ground` turns assumptions about your codebase into verified facts before any code is written. A cold verifier subagent then re-checks the evidence. | skill + agent |
| [`seam-proof-build/`](seam-proof-build/) | Keeps that discipline running *during* the build: every load-bearing step proven by a real run that could have failed. | skill |
| [`theory-formation-discipline/`](theory-formation-discipline/) | Nine moves for reasoning like a researcher without fooling yourself, plus a Stop hook that blocks "verified" claims with no verification behind them. | prose + hook |
| [`experiment-freeze-gate/`](experiment-freeze-gate/) | Eight checks between freezing an experiment design and spending compute on it. Catches specs that are internally broken but pass every downstream check. | skill |
| [`delegated-build-stint/`](delegated-build-stint/) | Contract for handing build work to a subagent. Headline rule: a stint never takes custody of a long run. | skill + agent |
| [`discipline-compliance-scanner/`](discipline-compliance-scanner/) | Mines your session transcripts and reports where standing rules were actually broken, with citations. | script |
| [`stopping-rules/`](stopping-rules/) | Four `CLAUDE.md` rules for the moments the model stops too early: stale world facts, patching without a diagnosis, shallow answers, made-up estimates. | prose |

## Install

Skills go in `.claude/skills/<name>/SKILL.md`, project-local or global (`~/.claude/skills/`).
Agent definitions go in `.claude/agents/`. Each directory's README has the exact paths and an
example invocation. Two that differ:

```bash
# discipline-compliance-scanner - just run it
python3 discipline-compliance-scanner/scan.py --all

# verification-claim-gate - a Stop hook, needs registering in .claude/settings.json
# see theory-formation-discipline/verification-claim-gate/README.md
```

The prose pieces (`stopping-rules/`, the nine-move discipline) are meant to be copied into
your own `CLAUDE.md`.

## Where each one fires

- Before writing code: `ground-skill-verifier`
- While building: `seam-proof-build`
- Before spending compute: `experiment-freeze-gate`
- Across a delegation boundary: `delegated-build-stint`
- When reporting results: `theory-formation-discipline`
- After the fact, from transcripts: `discipline-compliance-scanner`
- At the moment of stopping: `stopping-rules`

The first six check a **claim**, so parts of them can be enforced mechanically: the
verification-claim gate is a hook, the scanner is a program. `stopping-rules` checks a
**stop**, which means checking against work that was never done. One attempt to detect such
a rule from transcripts (reactive patching, from the shape `edit → failed command → re-edit`)
failed, because that pattern is indistinguishable from normal iteration. That line is where
hooks stop working and discipline is all you have.

## Caveats

None of this makes the model smarter. It makes it more honest about what it actually knows,
by moving self-correction from after-you-push-back to before-it-speaks.

Most of these are self-enforced, meaning the agent walks itself through them and can skip
them. Only the hook and the scanner are mechanical. Each README labels which kind it is,
because calling a self-enforced discipline a guarantee would be the exact failure these
exist to prevent. That is also why `discipline-compliance-scanner` exists: run against real
work, it found bright-line rules broken hundreds of times by an agent that had "known" them
throughout.

MIT licensed. Built against Opus 4.8; the disciplines are model-agnostic, the transcript
paths in the scanner are Claude Code specific.
