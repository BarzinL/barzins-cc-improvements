# Request-fidelity review

A script that extracts, from a Claude Code session transcript, every message
the user actually typed, and a subagent definition for a reviewer that gets
only that extract and the diff. The reviewer reports where the diff does not do
what was asked, where it does something that was not asked, and which requests
it could not check.

Targeted at: Opus 5.5.

## The failure it targets

The Claude Opus 5.5 system card, §2.3.3 (page 36):

> In internal use, Claude Opus 5.5 has addressed review feedback narrowly
> without reconsidering whether the overall design is right, and has checked a
> plan against requirements it wrote itself rather than against the people the
> plan was designed to support.

A reviewer briefed by the implementer inherits the implementer's reading of the
request: if the implementer's summary says "the user asked for X", the reviewer
checks X, and a misreading passes review. This piece gives the reviewer the
user's own words instead of anyone's summary of them.

It is a judgment check run by a model, not a mechanical one. It makes a
misreading easier to catch; it cannot guarantee that it is caught.

## What it does

`extract_user_messages.py` reads a transcript (`~/.claude/projects/<project>/<session>.jsonl`)
and prints the user's messages, verbatim and in order, each under a header
line added by the extractor. `--json` prints them as a list of objects;
`--stats` prints to stderr how every record in the file was classified.

It keeps a record only when it can positively identify it as typed by the user,
so a record kind it has never seen is left out rather than let in. In the
transcripts Claude Code 2.1.322 to 2.1.325 writes, it keeps:

- `type: "user"` records with `origin.kind == "human"`, not marked `isMeta`,
  not a sidechain, not a compaction summary. Text blocks that consist entirely
  of an `<ide_opened_file>`, `<ide_selection>`, `<ide_diagnostics>` or
  `<system-reminder>` element are dropped from these; image blocks are counted
  in the header and not printed;
- slash commands the user typed, printed as `/name args`;
- shell commands typed with `!`, printed as `! command`;
- `queued_command` attachments with a human origin (typed while Claude was
  working), printed once if the same text is also recorded as a message;
- the user's answers to AskUserQuestion prompts. Claude Code records these as
  a tool result: a `type: "user"` record with one `tool_result` block, whose
  `toolUseResult` holds `questions`, `answers` (question text to the chosen
  option label, a list of labels, or text the user typed under "Other"),
  and, when present, `annotations` (question text to `{notes, preview}`) and
  `response` (text typed in reply to the prompt as a whole). The extractor
  keeps such a record only when its block answers a `tool_use` named
  AskUserQuestion earlier in the same file, outside any sidechain. It prints
  each answered question as labelled lines: `[agent asked]` (the agent's
  question), `[user chose]` (an option label the agent wrote and the user
  picked), `[user typed]` (the user's own text in place of an option),
  `[user's note]`, and `[user's reply to the prompt]`. Option descriptions and
  previews are the agent's words and are left out. A prompt the user dismissed
  or left unanswered is left out. In `--json` these have `kind: "answer"` and
  a `questions` list.

What it leaves out, and how each appears in the transcript:

| Kind | How the transcript records it |
|---|---|
| Tool results (other than AskUserQuestion answers) | `type: "user"`, content is a list of `tool_result` blocks |
| System reminders | `type: "user"`, `isMeta: true`, text starting `<system-reminder>`; also `type: "attachment"` records of many types |
| Hook output | added to context as a system reminder (hooks docs); `attachment` records |
| Subagent reports | `type: "user"`, `isMeta: true`, `origin.kind: "peer"`, text starting "Another Claude session sent a message"; the subagent's own records have `isSidechain: true` |
| Task notifications | `type: "user"`, `origin.kind: "task-notification"`, text starting `<task-notification>`; also `queued_command` attachments with `commandMode: "task-notification"` |
| Local-command output | `<local-command-caveat>` (meta), `<local-command-stdout>`, `<local-command-stderr>`, `<bash-stdout>`, `<bash-stderr>` records with no origin |
| Skill expansions | `isMeta: true` records after a slash command |
| Image captions | `isMeta: true`, text starting `[Image:` |
| Interruptions | text `[Request interrupted by user]`, no origin |
| Compaction summaries | `isCompactSummary: true` (these carry `turnOrigin: "human"`, which is why the extractor uses `origin` and not `turnOrigin`) |

Pasted text is part of what the user sent, so it is kept, including any
`<pasted_content id="…">` marker lines Claude Code adds where it marks pastes.

A transcript with no `origin` fields (an older Claude Code version) or a
subagent transcript is refused with exit code 3, not guessed at.

`request-fidelity-reviewer.md` is the subagent definition. Its only inputs are
the extract and a diff. It lists the user's requests with quotations, including
constraints and later changes of mind; classifies each as done, partial,
different, not done, could not check, or violated; lists every hunk that traces
to no request; and is told to set aside any summary, plan or explanation from
the implementer if one is supplied. It treats the extract as data: requests in
it are addressed to the implementer, not to the reviewer.

## How to use it

```bash
# the current session (inside a Claude Code shell)
python3 request-fidelity-review/extract_user_messages.py \
    --session "$CLAUDE_CODE_SESSION_ID" > /tmp/requests.txt
git diff main...HEAD > /tmp/work.diff
```

Install the agent by copying `request-fidelity-reviewer.md` into
`.claude/agents/` (project) or `~/.claude/agents/` (global). Then, in a
session:

```
Use the request-fidelity-reviewer agent. Inputs: /tmp/requests.txt and /tmp/work.diff. Nothing else.
```

The brief must contain only the two paths. Adding "the user wanted X" to it
defeats the point. For the same reason the reviewer must not see the user's
memory index, which a general-purpose subagent loads; see Status. Read Status
before installing: the trial did not support installing it as it is.

Cost: the reviewer reads the whole extract and the whole diff, so this is the
most expensive piece in the Part B set per use. Run it on request, before
handing work back on a task where the request was long or changed during the
session.

## What it cannot catch

- Requests made outside the session: in an earlier session, in a plan file, in
  conversation off the machine. The extract covers one transcript.
- Requests the user made by pointing (an open file, a selection, an image).
  Those are omitted or only counted in the header, so the reviewer sees that
  something was attached but not what.
- Whether the code works. The reviewer checks correspondence with the words,
  and marks behaviour it cannot confirm without running as "could not check".
- A misreading the reviewer shares. Both are models reading the same words;
  an ambiguity the reviewer also resolves the wrong way passes. The definition
  asks it to list every reading of an ambiguous request for that reason.
- Transcript formats other than the one checked. The extractor was checked
  against transcripts written by Claude Code 2.1.322 to 2.1.325 by one client
  only. Other clients were not checked; if one records typed prompts
  without `origin.kind == "human"`, they will be missing from the extract. Run
  with `--stats` once on one of your own sessions and compare the count with the
  prompts you remember sending.
- A typed message whose entire text is one `<system-reminder>`, `<ide_…>`
  element would be dropped as harness text.
- Text the user types when rejecting a tool call ("To tell you how to proceed,
  the user said: …") is recorded inside an error tool result and is still left
  out. That wording exists in Claude Code 2.1.325, but there was no
  example to check the record shape against.
- AskUserQuestion answers were checked against one recorded example (Claude Code
  2.1.323). The `annotations`, `response`, timeout and follow-up fields were
  read from the Claude Code 2.1.325 program, not seen in a transcript; the
  tests for them use synthetic records built to that shape.

## Status

**Not recommended for installation as it is.**

Trialled on 2026-11-15, on five past cases where an agent misread what the user
wanted, plus three controls where no correction followed. Each case was cut
just before the user's correction, and the reviewer saw only the extract and
the work done up to that point.

- It caught 1 of the 5 misreadings.
- Of its 30 other flags on the five cases, 19 were judged noise. Of its 17
  flags on the three controls, 11 were judged noise. It flagged about as much
  when nothing was wrong as when something was.
- One person scored every case and every flag, knowing the answers. Five cases
  and three controls from one user are too few to estimate a catch rate or a
  noise rate.

Two reasons it missed, both in its design rather than in the sample:

1. **Its prompt forbids judging level, register and order.** It is told not to
   judge style or design except where they contradict a request, and not to
   infer what the user meant beyond their words. The misreadings in the trial
   were about the reader's level, the register and the teaching order, and
   about one ambiguous key phrase, not about scope. The reviewer treated the
   user's statements of goal and level as topics that had been answered, not as
   a standard to check the work against.
2. **Run after the work is built, it saves little.** It reviews finished work,
   as it was designed to. A catch at that point saves the user one message, not
   the work that has to be redone. The saving is in
   checking before a large piece of work is built. `task-grounding/` now has a
   `reader` category that asks for that check at the start.

**It must run as an agent type that does not load the user's memory.** A
general-purpose subagent loads the user's memory index, which holds the
implementer's earlier readings of the user: the very thing this reviewer is
meant to be kept from. In the trial it ran as an Explore agent, whose context
showed no memory index. Whether an agent installed from
`.claude/agents/request-fidelity-reviewer.md` loads the memory index was not
checked.

The reviewer prompt has not been changed since the trial. The extractor has: it
now keeps the user's answers to AskUserQuestion prompts, which the trial found
it dropping.

## Test

```bash
python3 test_extract_user_messages.py
```

Standalone, no pytest. One synthetic session holds every excluded kind in the
table above, interleaved with the messages that must be kept, plus malformed
lines. The test checks that exactly the typed messages come out, in order and
byte for byte (including Persian text with U+200C and pasted-content markers),
that a marker string from each excluded kind is absent from the output, and
that old-format and subagent transcripts are refused. A second synthetic
session holds AskUserQuestion answers of each shape (chosen option, list,
joined multi-select string, typed "Other" text, notes only, reply to the
prompt) next to an unanswered prompt, a rejected prompt, a sidechain answer,
and ordinary tool results whose payload is shaped like an answer; only the
answers may come out. All fixtures are synthetic.
