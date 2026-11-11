# Claude Code: `/heartbeat` skill

Keeps a Claude Code session making progress between operator messages. A session-only cron
job fires a fixed prompt every twenty minutes or so, and each fire follows the same protocol
against a per-work file.

Without this, unattended work tends to fail in two ways. The session stops as soon as the
operator stops prompting. And when it is kept going by a bare repeating prompt, the agent
works from its memory of the conversation, which a compaction replaces with a summary, so
the goal, constraints and queue survive only as far as the summary happens to keep them.

## Parts

- **A file per piece of work**, made from [`template.md`](template.md): goal, done
  condition, constraints, what is allowed without asking, escalation, checks, an optional
  knowledge log, fallback work, an ordered queue, and one STATE line per fire. It is the
  only state a fire relies on.
- **A cron job** whose prompt names the heartbeat and points at [`protocol.md`](protocol.md)
  and the file. Every fire runs the protocol: count the fire, orient from the file, run the
  checks, zoom out against the goal every few fires, take one verified step, record STATE and
  findings, reply.
- **A registry and a hook** ([`heartbeat.py`](heartbeat.py)). Session-only cron jobs die
  with the session and recurring ones expire after seven days. The hook runs at
  `SessionStart`, where it tells the session to re-create jobs that died, and at
  `PreCompact`, where it tells the summary to carry unrecorded state and findings.

The agent pauses a heartbeat on its own only through `heartbeat.py idle`, which refuses
while a queue item has no stated blocker or a fallback-work command still lists something.
That keeps "nothing to do" a checked claim rather than an assertion.

## Install

```bash
cp -r heartbeat ~/.claude/skills/
```

Then register the hook in `~/.claude/settings.json` under both `SessionStart` and
`PreCompact`, with the command `python3 /home/YOU/.claude/skills/heartbeat/heartbeat.py hook`
(an absolute path; see the scope note in [`INSTALL.md`](../INSTALL.md)). Without the hook a
heartbeat stops at the first compaction or restart.

Check the script with `python3 ~/.claude/skills/heartbeat/test_heartbeat.py`.

## Use

`/heartbeat start NAME` drafts the file from the conversation and asks the operator to
correct the goal, constraints, allowed actions and escalation before anything runs. The other
commands are `pause`, `resume`, `cadence`, `status` and `stop`; [`SKILL.md`](SKILL.md) has
each one.

Pair it with [`context-winddown`](../context-winddown/) so a long-running heartbeat session
compacts at a point the agent chose, after saving state.

## Limits

- It runs only while the Claude Code session is open, and a fire waits until the session is
  idle.
- Every fire costs tokens, quiet ones included.
- Tool permissions must already allow the work, or each fire stops at a prompt nobody
  answers.
- The protocol is self-enforced: the agent walks itself through it and can skip a step. The
  mechanical parts are the registry checks (`tick`, `idle`) and the hook.
