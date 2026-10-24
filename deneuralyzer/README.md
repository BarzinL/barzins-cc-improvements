# Claude Code: `/deneuralyzer` skill

The after-ship companion to [`/seam-proof-build`](../seam-proof-build/). A pipeline
running on real inputs keeps meeting inputs nobody foresaw, and the usual patch
encodes the example rather than the class, so the next unforeseen input fails too.

The name: it takes what a neural network would learn and moves it into explicit
code, with a nod to the Men in Black device. This skill treats the code as a model being trained and each failure as a labelled
example. The rules stay explicit and inspectable, and each change is judged the way
a model is: by whether it improves behaviour on inputs it was not fitted to.

## The six moves

1. **Record the stop as a fixture**, rather than fixing it where it happened.
2. **Name the class and fix it at its owner**, keeping the cases as tests.
3. **Move the check to the earliest cheap stage**: a preflight against the real
   target catches failure classes nobody predicted.
4. **Make every classifier total**: "no rule matched" routes to a proposer and a
   human confirmation, and the answer is stored as a readable rule.
5. **Measure generalization on unseen inputs**, such as stops per batch on new
   targets, not on the input a fix came from.
6. **Keep operating separate from building**, so operating stays cheap and fixes
   are made with the fixtures in hand.

See [`SKILL.md`](SKILL.md) for each move with the incident it came from.

## Install

    cp -r deneuralyzer ~/.claude/skills/
