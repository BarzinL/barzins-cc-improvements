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
claims are compared with the Read calls. Revised again the same day for scope claims, the
gap the first replay found: reads anywhere in the session count, `cat`, `head`, `tail` and
`sed -n` count as reads, a claim to have read a whole repository is always flagged, "read
through <directory>" and "read all four <documents>" are checked against the reads, and a
measured speed or memory claim needs a timing or benchmark command.

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
| whole file | "I read the whole file", "read parser.rs in full" | the file named (or, if none is named, some file read in this turn) was read in full at some point in the session: by a Read with no line limit, by `cat` or `nl` at the end of a pipeline, or by Reads and `head` / `tail` / `sed -n` ranges that together cover every line. A file the claim names that was never read fails |
| whole repository | "I read through the whole repository", "reviewed the entire codebase", "read every file" | never: reads cannot be shown to cover a repository, so the claim is always flagged and the agent is asked to name what it read |
| directory | "I've read through widget-core", "went through src/" | judged only if the name is a directory of files read in the session; then every file read under it must have been read in full |
| count of documents | "I read all four handoffs", "read both reports" | judged only if at least that many files read in the session have the noun in their names; then at least that many of them must have been read in full |
| speed or memory | "3x faster", "reduced memory usage by 40%", "now runs in 1.2 s", "dropped from 900 ms to 300 ms" | a timing or benchmark program ran in this turn, in command position (`time`, `/usr/bin/time`, `hyperfine`, `perf stat`, `valgrind`, `cargo bench`, `go test -bench`, `pytest --benchmark`, `python -m timeit`, a program or script with `bench` in its name...), and not every such command failed |

   A command **failed** if its result is marked `is_error` (Claude Code records a non-zero
   exit as `is_error: true` with the text `Exit code N`), or if its output contains a failure
   summary such as `test result: FAILED`, `1 failed` or `error[E0308]:`, so `cargo test |
   tail` is caught even though `tail` exits 0.

5. If any claim is unsupported, it returns `{"decision": "block", "reason": ...}` once,
   naming the claim and what is missing (for example "the last test command in this turn,
   `cargo test`, failed", or "the reads of parser.rs in this session covered lines 1-200 of
   850"). The agent can then run the check, restate the claim as what was done, or say why
   the hook is wrong, and end the turn.

Read coverage is collected from every turn of the session, not only the last one: a file
read in two halves in two turns counts as read. All other claim kinds still need their
support in the current turn.

How command reads are counted:

- Commands are split into pipelines outside quotes, after heredoc bodies and multi-line
  strings are removed, so a `cat` inside a script passed to `python3` is not a read.
- What the agent sees is the output of a pipeline's last stage. `cat FILE...` and `nl FILE`
  (with or without options) read each file in full when they end the pipeline, or when
  only `cat`, `tee`, `less` or `more` follows. Piped into `head -n N` they read lines 1-N.
  Piped into anything else (`grep`, `wc`, `python3`...) they read an unknown part.
- `head -n N FILE` reads lines 1-N, `tail -n +K FILE` lines K to the end, any other `tail`
  an unknown part, and `sed -n 'A,Bp' FILE` (several ranges joined by `;` too) lines A-B.
  A `head` or `sed` range of 500 lines or more that printed fewer lines than it asked for is
  taken as the whole file, since the file ended first. Smaller ranges are taken as samples.
- Output written to a file (`cat a > b`), output that Claude Code cut short and saved
  (`<persisted-output>`, `Output too large`), and a command that failed count as no read or
  a read of an unknown part. File arguments with a glob or a variable (`*.md`, `"$f"`) are
  ignored.
- Paths are resolved against the working directory the transcript records on each tool
  call, including a `cd DIR` earlier in the same command. A relative path with no recorded
  directory is merged into the one absolute path it is a suffix of (`docs/notes.md` into
  `/w/docs/notes.md`); otherwise files are kept apart, so `a/config.py` and `b/config.py`
  never add up.
- A file named in the claim is matched by path suffix, component by component: `b/config.py`
  matches only paths ending in `b/config.py`, and `a.py` does not match `data.py`. A bare
  name that matches several files read in the session counts as read if any one of them was
  read in full.

Not counted as claims: text inside code blocks or quotation marks; negated, conditional or
prospective uses ("once all tests pass", "should build cleanly"); a claim followed by
"means", "counts as", "implies", "is required" and the like, which states a rule rather than
reports a run ("all pass means the task counts as solved"); questions; and sentences
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

- **Claims outside its phrase lists.** It matches fixed patterns. "I went over every module
  in src/" or "I read both config files" (a count with a two-word noun) are not matched, nor
  is a paraphrase it has no pattern for.
- **A check of one property described as a check of another.** A command that checks one
  property ("the binary exists") supports any observation claim, including one about a
  different property. The case from the labelled sample, "I checked that each folder is a
  working git repo with its full history" after a command that checked only
  `is-inside-work-tree`, is not caught and is left that way: telling which property a
  command checked would need a model of each command, and a pattern for "full history" alone
  would fire on every honest use of the phrase. The same holds for the speed check: any
  timing command supports any speed claim, whatever it timed.
- **Whether the check matches the claim's scope.** A test command that ran one test file
  supports "all tests pass". The last run of a kind decides, so a full-suite failure followed
  by a single passing test file reads as a pass.
- **Work from earlier turns, except reads.** Reads count across the session; tests, builds,
  runs and timings count only in the current turn. A claim backed by a test run two turns
  ago will be flagged; the agent should say it relies on that run.
- **Reads it does not parse.** `less`, `awk`, `python -c "print(open(...).read())"`, a read
  in a shell loop (`for f in *.md; do head -60 "$f"; done`), and reads by subagents are not
  counted. A claim that names such a file is flagged as "not read in this session"; the agent
  can say how it read the file.
- **The 500-line rule is a heuristic.** A `head -n 400` that printed the whole of a 300-line
  file counts as lines 1-400, so a true whole-file claim after it is flagged. The rule counts
  output lines, so stderr mixed into the output can shift the count.
- **Same-named files, when the claim gives a bare name.** "I read config.py in full" passes
  if any `config.py` read in the session was read in full.
- **Directory and count claims, judged leniently.** "Read through <dir>" passes if every file
  read under the directory was read in full, however few were read; it cannot know about the
  files never opened. A count claim is judged only when at least that many files carry the
  noun in their names. If "I read all four handoffs" refers to four documents
  only two of which have "handoff" in the file name, the count
  is not judged, so a real undercount of documents named differently is missed.
- **Speed claims without a number or a "now".** "It runs in 40 minutes" is taken as
  background and not checked, so a measurement phrased that way is missed.
- **Subagent work.** A subagent's tool calls are in its own transcript, not the turn's. A
  relayed claim passes only if the message attributes it.
- **Failures the output does not show.** A command whose result was cut off, that ran in the
  background, or that reports failure in an unrecognised format reads as not failed.
- **Truth.** It checks that a check of the right kind ran and did not visibly fail, not that
  the claim is correct.

**Limits that come from Claude Code itself.** The hook reads the session transcript. The official documentation says the transcript is written asynchronously and may not yet include the turn's latest messages when a hook fires, and that the transcript format is internal and changes between versions. So the hook can miss a tool call made at the very end of a turn, and a Claude Code update can break its reading of the transcript without warning. Rerun the tests after an update.

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

3. Claude Code watches settings files and normally applies hook edits to the running session without a restart; if `/hooks` does not list it, restart the session. In an interactive session, hooks do not run until the workspace trust dialog has been accepted. It should appear under `Stop`.

## Tune it to your stack

The patterns are module-level regexes:

- `_TEST_CMD`, `_BUILD_CMD`: what counts as a test or build command. Add your project's
  runners if they are not covered. A command quoted in backticks in the final message that
  ran and did not fail also counts, so `./run_checks.sh` works without editing anything if
  the message names it.
- `_INSPECT_PROGRAMS`: programs that only inspect or move files and never count as a run.
- `_FAIL_OUTPUT`: failure summaries recognised in output.
- `_TEST_CLAIM`, `_BUILD_CLAIM`, `_RUN_CLAIM`, `_OBSERVE_CLAIM`, `_SCOPE_CLAIM`,
  `_REPO_CLAIM`, `_DIR_CLAIM`, `_COUNT_CLAIM`, `_PERF_CLAIM`: claim phrasings, by kind.
- `_GENERIC_AFTER`: words after a claim that make it a rule rather than a report.
- `_TIMERS`, `_TIMED_RUN`: what counts as a timing or benchmark command.
- `_stage_reads`, `_LARGE_RANGE`: the shell commands recognised as reads.

## Test

```bash
python3 test_verification_claim_gate.py
```

Standalone (no pytest). Feeds the hook synthetic transcripts shaped like current Claude Code
transcripts and checks whether it pauses. Covers the original cases, the ten acceptance cases
the revision was written against (`B2-1` to `B2-10`), and further cases for the transcript
shape (results linked by `tool_use_id`, `isMeta` records, `last_assistant_message` without
the final message in the transcript), shell parsing (quoted pipes, heredoc bodies), hedges,
conditionals, code blocks, and fail-open on malformed input. `S-1` to `S-7` and `S-5b` cover
scope claims (a file read across two turns, `sed -n`, `cat`, `cat | head` alone and with a
second command, a whole-repository claim) and `P-1` to `P-4` speed and memory claims.
`G-1` to `G-13` were written from the defects a review of the second revision found, each
from the input that showed it; each defect case failed against the gate before its fix.
`CLAIM_GATE=/path/to/other/gate.py python3 test_verification_claim_gate.py` runs the same
cases against another copy of the gate.

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
