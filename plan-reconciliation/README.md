# Plan reconciliation (Claude Code Stop hook)

A Stop hook that, when the session has a written plan, pauses the turn once if the
final message does not account for every plan item that is still open.

Targeted at: Opus 5.5

## The failure it targets

The Opus 5.5 system card, section 2.3.3, on flagged behaviour in internal agent
deployments:

> The second most common subcategory was dismissing its
> own doubts or abandoning its own stated plan, which also rose in frequency relative to
> previous models.

An abandoned step rarely shows in the final report. The report describes what was done,
and a step that was dropped is simply absent from it. This hook makes the absence
visible. It does not judge whether dropping a step was right.

## What it does

When a turn ends, the hook:

1. reads the session's plan file, `<scratchpad_dir>/plan.md` (see "Where the plan
   lives" below). No file, or no open items: it stays silent;
2. takes the final message from the payload's `last_assistant_message`, or, if that is
   missing, from the transcript (the assistant text after the turn's last tool call);
3. stays silent if the message ends with a question, since the turn is handing back to
   the user rather than reporting the work as finished;
4. stays silent if the turn made no tool calls and the message has no completion word
   ("done", "finished", "implemented" and a few others), so a conversational reply does
   not trigger a plan check;
5. otherwise checks each open item against the message, and if any item is not
   mentioned, pauses the turn once and lists those items, asking for each to be
   reported as done, deferred with a reason, or dropped with a reason.

The pause is returned as `hookSpecificOutput.additionalContext`, which the current hooks
documentation describes as non-error feedback that continues the conversation under the
same loop protections as `decision: "block"`. It is advisory, fires at most once per
stop cycle (`stop_hook_active`), is silent when it passes, and fails open: any malformed
payload, unreadable file or unexpected error ends in exit 0 with no output.

### The plan file

A Markdown checklist, one item per line:

```markdown
- [x] B2: revise the claim gate
- [ ] B3: plan reconciliation hook
- [ ] Update the API docs
```

`[x]` or `[X]` is done; any other mark (a space, `~`, `-`) is open. Numbered items
(`1. [ ] ...`) are read too. Other lines are ignored.

An item counts as mentioned when:

- it starts with a short key followed by a colon (`B3:`), and the key appears in the
  message as a whole token (`B3`, not `B33`); purely numeric keys do not count as keys;
  or
- at least two thirds of its significant words (three letters or more, common words
  removed, simple suffixes stripped), capped at four, appear in the message.

Keys are the reliable route. Word matching is a fallback for plans written as prose.

### Where the plan lives

The plan's B3 step said to use the harness's task list if the transcript exposes it,
and a checklist file otherwise. The evidence, checked on 2026-11-14:

- The Claude Code tools reference, "Task tool availability": the task tools
  (`TaskCreate`, `TaskGet`, `TaskUpdate`, `TaskList`, `TodoWrite`) "are available by
  default only on Opus 4.7, Sonnet 4.6, Haiku 4.5, and earlier models", and on other
  models "Claude adds nothing to the task list while it works" unless the user opts in
  with `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` or `--allowedTools`.
- No recorded example of a `TaskCreate`, `TaskUpdate` or `TodoWrite` call on this model
  was available, so there was nothing to base a parser for those tools' input format on.
- The hooks reference lists `scratchpad_dir` among the common input fields of every
  hook: "Path to the session's scratchpad directory, where Claude keeps temporary
  working files." The agent is given the same path in its system prompt. The path
  contains the session id.

So the plan is a checklist file at `<scratchpad_dir>/plan.md`. The agent can write it
without being told a session id, the hook finds it without guessing, the file belongs
to one session by construction, and nothing is added to the project's tree.

To use it, tell the agent (in a prompt, or in a project `CLAUDE.md`) something like:
"For multi-step work, write the plan as a checklist in `plan.md` in your scratchpad
directory, give each item a short key (`S1:`), and mark items `[x]` when done."

## What it cannot catch

- **A false `[x]`.** An item marked done that was not done passes. The hook checks the
  report against the file, not the work.
- **A mention that is not an account.** "I looked at the migration script" counts as a
  mention of "Write the migration script" even if it says nothing of its status.
- **Paraphrase.** An item described in different words than the plan used is not
  recognised, and is listed as unmentioned. Keys avoid this.
- **A plan that exists only in the conversation.** If the agent states a plan in prose
  and never writes the file, there is nothing to check. Abandoning a plan that was
  never written down is outside its reach.
- **Ending on a question.** Any message whose last line ends in `?` passes, including a
  completion report that ends "Shall I do the rest?".
- **Subagents.** A Stop hook runs for the main agent only. Subagents appear to share the
  parent's scratchpad directory, so a subagent that writes `plan.md` there would put
  its plan in front of the parent's hook.
- **Missing scratchpad.** `scratchpad_dir` is absent when the session has no scratchpad
  (the documentation says it needs Claude Code v2.1.257 or later). The hook is then
  silent. The scratchpad is temporary storage and can be cleared by a reboot.

**Limits that come from Claude Code itself.** The hook reads the session transcript. The official documentation says the transcript is written asynchronously and may not yet include the turn's latest messages when a hook fires, and that the transcript format is internal and changes between versions. So the hook can miss a tool call made at the very end of a turn, and a Claude Code update can break its reading of the transcript without warning. Rerun the tests after an update.

**No scratchpad, no check.** Per the official documentation a session has a scratchpad only when it is signed in with a claude.ai account (not an API key), uses the Anthropic API (not Bedrock, Google Cloud or Foundry), and `enableArtifact` is not `false`. In other sessions the hook stays silent.

## Install

1. Copy `plan_reconciliation.py` into the project, for example
   `.claude/hooks/plan_reconciliation.py`.
2. Register it as a `Stop` hook in `.claude/settings.json`, alongside any existing Stop
   hooks:

   ```json
   {
     "hooks": {
       "Stop": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/plan_reconciliation.py\""
             }
           ]
         }
       ]
     }
   }
   ```

3. Claude Code watches settings files and normally applies hook edits to the running session without a restart; if `/hooks` does not list it, restart the session. In an interactive session, hooks do not run until the workspace trust dialog has been accepted.

Python standard library only.

## Test

```bash
python3 test_plan_reconciliation.py
```

Standalone, no pytest. The six acceptance cases from the plan are marked `[plan]`;
the rest cover keys, numbered items, the conversational-reply rule, the transcript
fallback, a harness meta message in the middle of a turn, and fail-open on bad input.

## Status

The tests feed recorded-shape payloads to the script. The hook has not been run in a
live Claude Code session, and its firing rate on real work is unmeasured.
