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
  working), printed once if the same text is also recorded as a message.

What it leaves out, and how each appears in the transcript:

| Kind | How the transcript records it |
|---|---|
| Tool results | `type: "user"`, content is a list of `tool_result` blocks |
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
defeats the point.

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

## Status

Steps 1 and 2 of plan item B6 are built. Step 3, a trial on three past
sessions where the user corrected the agent's reading of a request, has not
been run: it depends on the Phase 1 rework list, which comes from a
measurement that has not been run yet. Until that trial, there is no evidence
on how often the reviewer raises the point the user later raised.

## Test

```bash
python3 test_extract_user_messages.py
```

Standalone, no pytest. One synthetic session holds every excluded kind in the
table above, interleaved with the messages that must be kept, plus malformed
lines. The test checks that exactly the typed messages come out, in order and
byte for byte (including Persian text with U+200C and pasted-content markers),
that a marker string from each excluded kind is absent from the output, and
that old-format and subagent transcripts are refused. All fixtures are
synthetic.
