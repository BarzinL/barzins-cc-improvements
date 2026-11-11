# Heartbeat: NAME

Fired by a session-only cron job; each fire follows ~/.claude/skills/heartbeat/protocol.md and then this file.
Started DATE by OPERATOR.

## Goal

What this work is for, in one or two sentences: the purpose, not the next task. The zoom-out checks the queue
against this.

## Done when

The observable condition that ends the heartbeat. When it holds, record it, stop the heartbeat, and tell the
operator.

## Constraints

What is never done without the operator's explicit go (for example: push, publish, send, delete, spend, contact
anyone, reboot), and any standing rule of this work (resource caps, files not to touch).

## Allowed without asking

What the agent may do on its own (for example: commit to a branch or to main, start capped jobs, write the log).

## Escalation

When to contact the operator outside the session, and how (a command, an address). Only for a decision only they can
make, a failure that cannot be resolved, or an empty queue.

## Checks

What to look at on every fire before taking a step: jobs to confirm (with the command), external threads to read,
anything that can change without the agent.

## Knowledge log

Optional. The file where what is learned is kept, beyond what is running, and what to read from it each fire. Register
it with `--log` so compaction keeps unrecorded items.

## Fallback work

Commands that list independent work outside the queue, one item per output line and nothing when clean. `HB idle`
runs them before the heartbeat may pause itself. List only sources an owner keeps (a gate, a nag, a ratchet, a
recorded finding), not cleanup chosen by taste. For example:

- review: `python3 tools/review_due.py` (lists changes waiting for a periodic review)
- plans: `python3 tools/stale_plans.py` (lists plan files whose status line is older than their code)

## Queue

1. First step.
2. Next step.

## STATE

One line per fire, appended: time, what was done (with evidence), what is running, next.
