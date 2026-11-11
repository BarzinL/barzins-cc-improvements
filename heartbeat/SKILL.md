---
name: heartbeat
description: Keep a Claude Code session making progress on its own between operator messages - a session-only cron job fires every ~20 minutes, and each fire follows a fixed protocol (count, orient from a state file, run checks, zoom out against the goal every few fires, take one verified step, record STATE and findings) against a per-work file holding goal, constraints, escalation, checks and an ordered queue. Survives compaction and resume through a registry and a hook. Invoke as /heartbeat start, pause, resume, cadence, status or stop, or when the operator asks the agent to keep working autonomously, check in periodically, or carry a long task forward unattended. Not for watching one process's output (use Monitor) or a single reminder (use a one-shot CronCreate).
---

# /heartbeat - unattended progress, one verified step at a time

A heartbeat has three parts:

- **A file** for the work, made from `template.md`: goal, done condition, constraints, what is allowed without
  asking, escalation, checks, an optional knowledge log, an ordered queue, and STATE lines. It is the only state a
  fire relies on, so the work survives compaction.
- **A cron job** in the session (session-only, recurring) whose prompt names the heartbeat and points at
  `protocol.md` and the file. Every fire follows `protocol.md`, so improving the protocol improves every heartbeat.
- **A registry entry** (`heartbeat.py`, in `~/.claude/heartbeats/registry.json`). The hook reads it at SessionStart,
  to have the session re-create jobs that died with a restart or expire after 7 days, and at PreCompact, to make the
  summary carry unrecorded state and findings.

`HB` below is `python3 ~/.claude/skills/heartbeat/heartbeat.py`.

## One-time setup

The hook must be registered once in `~/.claude/settings.json`, for both `SessionStart` and `PreCompact`, as the
command `python3 ~/.claude/skills/heartbeat/heartbeat.py hook`. Check with `grep heartbeat.py ~/.claude/settings.json`;
add it if missing (the update-config skill covers editing settings). Without it a heartbeat stops at the first
compaction or restart.

## Commands

**start NAME** (or "keep working on this while I'm away"):

1. Draft the file from `template.md`, filling it from the conversation: the goal as the operator stated it, the
   constraints they have given, how they want to be reached. Put it where the work lives (a repository's docs, or a
   working directory the operator uses for notes); not in /tmp.
2. Show the operator the Goal, Done when, Constraints, Allowed without asking and Escalation sections inline and ask
   them, in prose, to correct anything. These decide what the agent does unattended, so do not start on guesses for
   them. Checks and the queue can be the agent's own first draft.
3. Register: `HB start NAME --file PATH [--cron '7,27,47 * * * *'] [--log PATH] [--zoom-every 6]` (the session id is
   read from `CLAUDE_CODE_SESSION_ID`). It prints the cron and the prompt.
4. CronCreate with that cron and prompt, recurring, durable false. Then `HB renewed NAME --job JOB_ID`.
5. Tell the operator the job's next run time from CronCreate's result, that it runs only while this session is open
   and idle, and how to pause it.

**pause NAME**: finish and record the step in progress, CronDelete the job (id in `HB status`, or from CronList),
`HB pause NAME`.

The agent pauses a heartbeat on its own only through `HB idle NAME --blocked q1=REASON ...` (protocol.md step 5),
which refuses while a queue item has no stated blocker or a Fallback work command lists an item; its STATE line
records what was checked.

**resume NAME**: `HB resume NAME`, then CronCreate with `HB prompt NAME` and the registered cron, then
`HB renewed NAME --job JOB_ID`.

**cadence NAME CRON**: `HB cadence NAME --cron CRON` (keeps the fire count, log and zoom-out interval), CronCreate
with the cron and prompt it prints, CronDelete the old job, `HB renewed NAME --job JOB_ID`.

**status**: `HB status` and CronList side by side; say which registered heartbeats have no live job and why
(paused, or needing re-creation).

**stop NAME**: CronDelete the job, `HB stop NAME`, and add a final STATE line to the file saying it was stopped and
why.

## Choosing the cadence

Pick minutes off :00 and :30. Twenty minutes suits work with runs or reviews to watch; hourly suits slow external
waits. The protocol slows a job down after three quiet fires in a row.

## Limits to tell the operator

- It runs only while the Claude Code session is open, and a fire waits until the session is idle.
- Every fire costs tokens, quiet ones included.
- Tool permissions must already allow the work, or each fire stops at a prompt nobody answers.
- The agent acts within the file's Constraints and Allowed sections; anything else waits for the operator.

## Maintaining this skill

`heartbeat.py` is checked by `python3 ~/.claude/skills/heartbeat/test_heartbeat.py` (each check on a temporary
registry). Run it after any change, and see a check fail on a wrong version before trusting a new one.
