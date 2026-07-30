# Per-model discipline (Claude Code UserPromptSubmit hook)

Project instructions are written once, for whichever model normally drives the session.
Nothing in `CLAUDE.md` knows which model is reading it, so two things go wrong: a rule
that raises a frontier model's ceiling keeps costing a smaller one after `/model`, and a
rule that only one family needs has nowhere to live except everyone's context.

This hook injects a short, per-family payload into the user turn. Payloads are files, so
adding or editing one is not a code change.

```
model-discipline-payloads/
  opus.md      every turn - the chat-register rule (see ../response-length-calibration/)
  sonnet.md    on model change - drop the ceiling-raising rules, execute procedurally
  haiku.md     `<!-- same-as: sonnet -->`
```

## Install

```bash
python3 install.py --scope global            # show the file copies and a settings diff
python3 install.py --scope global --apply    # do it, then run the acceptance check
```

`--scope global` installs into `~/.claude`, which covers the CLI, the desktop app and the
IDE extensions - they read the same settings files. Web sessions have no local filesystem
for a hook to live in, so that surface is out. Use `--scope project --project <path>` for
one repository instead.

Merging into a live `settings.json` is the only destructive thing in this repository, so
the installer is narrow about it: dry run by default, a unified diff before anything is
written, a timestamped `settings.json.bak-*`, and the existing `hooks.UserPromptSubmit`
array appended to rather than rewritten. Running it twice does not duplicate the entry. A
`settings.json` that is not valid JSON is refused rather than repaired.

**Hooks bind at session start**, so it activates in your *next* session. Confirm with
`/hooks` (it should appear under `UserPromptSubmit`).

Pure Python stdlib, no dependencies.

## Writing a payload

`model-discipline-payloads/<family>.md`, injected when that family is live. Two optional
directives on the leading lines:

```
<!-- cadence: every-turn -->   inject on every user prompt (default: on-change)
<!-- same-as: sonnet -->       use another family's payload and cadence
```

Cadence is the part worth thinking about, and the part that fails invisibly if you get it
wrong. An injection lands once, early, and is summarized away by the first compaction,
after which the family has not changed so nothing re-fires. Measured: a state file still
read `opus` across a compaction, with the payload long gone from context. So:

- **`on-change`** suits a rule about a *stint* - you switched models, here is what differs.
- **`every-turn`** is required for a rule needed on every substantive turn, such as an
  output-format rule. Set this wrong and the rule decays out of context while the hook
  still looks installed.

Dropping in `newfamily.md` is the whole of adding a family; the matcher picks up the
filename. Keep payloads short - they are ambient cost on every turn they fire.

## Two things that look right and are not

**There is no `model` field in the `UserPromptSubmit` payload.** Only `SessionStart`
receives one, and it does not re-fire on `/model`, so a session that starts on Opus and
switches to Sonnet never sees a second `SessionStart`. The live value is
`message.model` on the most recent assistant record in the transcript, which is what this
reads. The obvious implementation - `json.load(sys.stdin)["model"]` - fails open: prints
nothing, exits 0, and looks installed.

**The model field is not a closed set of strings.** Measured across every transcript on
one machine (2026-07-26): versioned IDs (`claude-opus-5`), dated IDs
(`claude-haiku-4-5-20251001`), bare aliases from `settings.json` (`opus`, `sonnet`,
`haiku` - 341 occurrences), and 552 records literally labelled `<synthetic>`. Bracket
suffixes such as `claude-opus-5[1m]` did not appear there but are a documented form. So
the matcher normalizes to a family and never compares against a list. This is also why
matching is by family and not by version: `claude-opus-4-8` and `claude-opus-5` both map
to `opus`, and isolating one version means parsing a version out of an open set.

## Subagents

Payloads reach the main conversation only. This fires on `UserPromptSubmit`, which is a
real user prompt; a subagent's prompt arrives as an Agent/Task tool call instead, and its
transcript is a separate file under `<session>/subagents/`. In a sampled subagent
transcript the first message was the parent's prompt verbatim, with no injected content
and no system-reminder.

That is evidence, not proof - transcripts do not record system prompts, so this does not
establish what a subagent's system prompt contains. It is the reason to put a
model-gated rule here rather than in `CLAUDE.md`: `CLAUDE.md` persists across compaction
but has no model gate and no delegation boundary, while this has both and needs
`every-turn` to survive. Neither route gives you all three.

## Fails open, always

Any surprise - unparseable stdin, missing transcript, unrecognized model string, a
`same-as` cycle, a payload directory that is not there - prints nothing and exits 0.
Injecting the wrong discipline is worse than injecting none, and a hook must never wedge
a prompt.

## Test

The installer's acceptance check needs no test framework and runs against whatever is
actually registered:

```bash
python3 install.py --scope global --verify-only
```

It asserts the real command string exits 0, prints for `claude-opus-5` on two
consecutive turns (the every-turn cadence), prints once and then stops for a Sonnet
switch, and stays silent for an unrecognized model, a `<synthetic>` record and a missing
transcript. The full suite additionally covers payload parsing, the settings merge and
the installer's own failure modes:

```bash
python3 -m pytest test_model_discipline.py -q     # 46 tests, needs pytest
```

Four of those exist to make the acceptance check fail on purpose: a wrong hook path, a
missing payload directory, an `opus.md` marked `on-change`, and a `settings.json`
containing invalid JSON. A check that has never been seen to fail is indistinguishable
from one that cannot fail.
