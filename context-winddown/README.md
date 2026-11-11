# Claude Code: `context-winddown` mod

Compacts the conversation when the agent says it is ready, instead of wherever automatic
compaction happens to fire.

Automatic compaction checks the context size before each model request, so it can fire
between two tool calls in the middle of a piece of work. The `PreCompact` hook can steer
what the summary keeps, but no tool runs before the summary is written: the agent gets no
chance to finish its step, write its state file or commit. Asking for a wind-down by hand
works, but needs the operator to watch the token count.

## How it works

1. After each main-thread turn, the mod reads the context size with `$.session.usage()`.
2. At or above the threshold (`CONTEXT_WINDDOWN_TOKENS`, default 450000), it queues one
   prompt asking the agent to finish and verify the step in progress, start no new work,
   save state the way its work protocol says, commit finished work, call the
   `ready_to_compact` tool and end its turn.
3. The tool only sets a flag, because a compaction cannot start while a turn is running.
4. When that turn completes, the mod calls `$.session.compact()` with instructions to keep
   the goal, the state file paths, the last verified step, the next step and any open
   question. Existing `PreCompact` hooks run as they do for a typed `/compact`.

Automatic compaction stays on as the backstop. The mod checks only at the end of a turn, so
a single turn that grows past the automatic threshold on its own still compacts there.

## Why a mod

There is no other way to start a compaction from inside a session. A cron job whose prompt
is `/compact` delivers the text to the model as an ordinary message (tested: the model
replied to it and nothing was compacted). Hooks have no output field that triggers one, and
skills cannot invoke built-in commands. A mod's `$.session.compact()` makes the same call
`/compact` makes. Mods need a Claude Code build with the mod API; the full cycle was tested on
2.1.322 in a terminal session, and the mod also loads in the VS Code extension.

## Install

```bash
cp -r context-winddown ~/.claude/skills/
```

A plugin folder under `~/.claude/skills/` loads in every new session. A different threshold
goes in the `env` block of `~/.claude/settings.json`:

```json
{ "env": { "CONTEXT_WINDDOWN_TOKENS": "300000" } }
```

Check it: `claude plugin validate ~/.claude/skills/context-winddown`, then ask a new session
whether `mcp__context-winddown__ready_to_compact` is in its tool list. To see the whole cycle,
start a session with `CONTEXT_WINDDOWN_TOKENS=1000`: the first turn crosses the threshold, and
`claude --debug-file FILE` logs the wind-down prompt, the tool call and
`context-winddown: compaction done (BEFORE -> AFTER tokens)`.

## With `/heartbeat`

[`heartbeat`](../heartbeat/)'s `protocol.md` has a "Wind-down before compaction" section: the
wind-down prompt is not a fire, the agent runs the record step in full, then calls the tool.
After the compaction the next fire re-orients from the heartbeat file.
