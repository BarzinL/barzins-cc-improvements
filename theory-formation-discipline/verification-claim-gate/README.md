# Verification-claim gate (Claude Code Stop hook)

A Claude Code **Stop hook** that pauses a turn once when the final message claims a check
that the turn's own tool calls do not support.

It targets the failure that frontier-model system cards report as the most frequent in
internal use: **stating an unverified inference as established fact**. "All tests pass" when
no test ran, or when the last test run failed; "I read the whole file" when the read stopped at
line 200. The model corrects such a claim at once when a person points at it; this hook does
the pointing before the turn ends.

Written against Opus 4.8. Revised against Opus 5.5 (2026-11-14): the claim is now tied to the
check that would support it, tool results are read as well as tool calls, and whole-file
claims are compared with the Read calls.

## What it does

When the main agent finishes a turn, the hook:

1. takes the final message from the payload's `last_assistant_message`, or from the
   transcript if that field is absent;
2. collects the turn's tool calls and their results from the transcript, from the prompt
   that opened the turn (the user record carrying `turnPosition`; injected `isMeta` records
   such as system reminders do not start a turn);
3. finds claims in the message, sentence by sentence;
4. for each kind of claim, checks whether the turn supports it:

| Claim | Examples | Supported when |
|---|---|---|
| test | "all tests pass", "12 passed", "the test suite passes" | a test command ran, and the last one did not fail |
| build | "the build passes", "compiles cleanly", "every check passed" | a build, check or test command ran, and the last one did not fail |
| named command | "`make check` passes" | that command ran, and its last run did not fail |
| works | "verified it works", "tested end-to-end", "I tested" | a command ran that does more than inspect files (not only `ls`, `cat`, `grep`, `git`...), and not every such command failed; or an HTTP fetch |
| observation | "no errors", "the service is healthy", "I checked" | any observing tool call: a command, a Read, a search, a fetch |
| whole file | "I read the whole file", "read parser.rs in full" | the file named (or, if none is named, some file) was read with no line limit, or by Reads that together cover every line |

   A command **failed** if its result is marked `is_error` (Claude Code records a non-zero
   exit as `is_error: true` with the text `Exit code N`), or if its output contains a failure
   summary such as `test result: FAILED`, `1 failed` or `error[E0308]:`, so `cargo test |
   tail` is caught even though `tail` exits 0.

5. If any claim is unsupported, it returns `{"decision": "block", "reason": ...}` once,
   naming the claim and what is missing (for example "the last test command in this turn,
   `cargo test`, failed", or "the Read calls on parser.rs in this turn covered lines 1-200 of
   850"). The agent can then run the check, restate the claim as what was done, or say why
   the hook is wrong, and end the turn.

Not counted as claims: text inside code blocks or quotation marks; negated, conditional or
prospective uses ("once all tests pass", "should build cleanly"); questions; and sentences
that hedge ("haven't run it") or attribute the claim ("the subagent reported that all tests
pass"). A hedge excuses only the sentence it is in. "Healthy" counts only next to a word for a
running system (service, server, build, deployment...), not about a person or a design.

Properties:

- **Advisory.** It pauses at most once per stop cycle: when `stop_hook_active` is true it
  does nothing. Claude Code also caps consecutive stop-hook continuations at eight.
- **Fails open.** A malformed payload, a missing or unreadable transcript, or any exception
  ends the hook silently with exit 0.
- **Silent when it passes.** It prints nothing unless it pauses the turn.
- Python standard library only.

## What it cannot catch

- **Claims outside its phrase lists.** It matches fixed patterns. Scope claims over several
  files or a directory ("I went over every module in src/", "I read both config files") are
  not matched, nor is a paraphrase it has no pattern for.
- **A partial check described as a full one, when the check was a command.** Reading a file
  with `sed -n 1,200p` or `head` is a command, not a Read; only Read calls are compared with
  whole-file claims. A command that checks one property ("the binary exists") supports any
  observation claim, including one about a different property ("I checked that it is the
  release build").
- **Whether the check matches the claim's scope.** A test command that ran one test file
  supports "all tests pass". The last run of a kind decides, so a full-suite failure followed
  by a single passing test file reads as a pass.
- **Work from earlier turns.** Only the current turn counts. A claim backed by a test run two
  turns ago will be flagged; the agent should say it relies on that run.
- **Subagent work.** A subagent's tool calls are in its own transcript, not the turn's. A
  relayed claim passes only if the message attributes it.
- **Failures the output does not show.** A command whose result was cut off, that ran in the
  background, or that reports failure in an unrecognised format reads as not failed.
- **Truth.** It checks that a check of the right kind ran and did not visibly fail, not that
  the claim is correct.

## Install

1. Copy `verification_claim_gate.py` into your project's hooks directory, e.g.
   `.claude/hooks/verification_claim_gate.py`.

2. Register it as a `Stop` hook in `.claude/settings.json` (add alongside any existing
   Stop hooks - they all run):

   ```json
   {
     "hooks": {
       "Stop": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/verification_claim_gate.py\"",
               "statusMessage": "Send-time verification-claim check"
             }
           ]
         }
       ]
     }
   }
   ```

3. **Hooks bind at session start**, so it activates in your *next* session, not the one
   where you added it. Confirm with `/hooks` (it should appear under `Stop`).

## Tune it to your stack

The patterns are module-level regexes:

- `_TEST_CMD`, `_BUILD_CMD`: what counts as a test or build command. Add your project's
  runners if they are not covered. A command quoted in backticks in the final message that
  ran and did not fail also counts, so `./run_checks.sh` works without editing anything if
  the message names it.
- `_INSPECT_PROGRAMS`: programs that only inspect or move files and never count as a run.
- `_FAIL_OUTPUT`: failure summaries recognised in output.
- `_TEST_CLAIM`, `_BUILD_CLAIM`, `_RUN_CLAIM`, `_OBSERVE_CLAIM`, `_SCOPE_CLAIM`: claim
  phrasings, by kind.

## Test

```bash
python3 test_verification_claim_gate.py
```

Standalone (no pytest). Feeds the hook synthetic transcripts shaped like current Claude Code
transcripts and checks whether it pauses. Covers the original cases, the ten acceptance cases
the revision was written against (`B2-1` to `B2-10`), and further cases for the transcript
shape (results linked by `tool_use_id`, `isMeta` records, `last_assistant_message` without
the final message in the transcript), shell parsing (quoted pipes, heredoc bodies), hedges,
conditionals, code blocks, and fail-open on malformed input.

## Replay over recorded transcripts

`replay.py` runs a gate offline over your own transcripts. At every point where the main
agent finished a turn, it builds the payload the Stop hook would have received (the
transcript cut off at that point, `last_assistant_message`, `stop_hook_active: false`), runs
the gate, and records whether it paused.

```bash
python3 -I replay.py run --out ~/claim-gate-eval --label current
python3 -I replay.py run --out ~/claim-gate-eval --label old --gate /path/to/old_gate.py
python3 -I replay.py sample --out ~/claim-gate-eval --old ~/claim-gate-eval/replay-old.jsonl \
    --new ~/claim-gate-eval/replay-current.jsonl
python3 -I replay.py score --out ~/claim-gate-eval --labels ~/claim-gate-eval/labels.csv
```

`sample` writes a blind labelling sample (message text and tool calls, no verdicts) with a
blank `labels.csv`; `score` reports false positives and misses for each gate from the
filled-in labels. The output contains your conversation text, so `--out` must be outside this
repository; the script refuses a path inside it.

## Why a hook and not a memory instruction

Because system cards document a "correction fails" category: the corrective instruction
was present in a memory file, and the behaviour recurred anyway. A memory note is recalled
context the model can drift from. A Stop hook is executed by the harness, whether or not the
model remembered the rule.

The tradeoff: a hook can only enforce what is mechanically detectable. This one covers the
frequent, detectable slice. The rest of the discipline (see the parent directory) stays
self-enforced.
