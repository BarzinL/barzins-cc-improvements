# Performance grounding kit

A command-line timer that keeps a record of each measurement and compares two of them,
and a one-page playbook for performance work. The `task-grounding/` hook names both, by
absolute path, in its performance directive when it finds this directory.

Targeted at: Opus 5.5

## What it is for

The performance directive in `task-grounding/` asks the agent to measure before and
after a change. That asks for the behaviour; it does not make it cheap. Done by hand, a
measurement is often one run of each version, on inputs that differ, with the numbers
kept only in the conversation. `measure.py` does the careful version in one call and
leaves a file that shows afterwards what was measured, how often and on what.

## Files

- `measure.py`: the tool. Python standard library only.
- `PLAYBOOK.md`: the procedure and the mistakes to avoid, with the standard profiler
  invocation for five languages, each cited to its official documentation.
- `test_measure.py`: tests.

## How the agent is expected to use it

```bash
python3 measure.py run --out-dir <scratchpad>/perf --name before --input big-file-v1 -- ./parse big.csv
# ... profile, change the code, check the output ...
python3 measure.py run --out-dir <scratchpad>/perf --name after --input big-file-v1 -- ./parse big.csv
python3 measure.py compare <scratchpad>/perf/before-*.json <scratchpad>/perf/after-*.json
```

`run` executes the command (no shell; wrap a pipeline in `sh -c '...'`) once untimed
and 10 times timed by default (`--warmup`, `--runs`), prints the median, minimum,
maximum and interquartile range, and writes one JSON record: the command, the working
directory relative to the record, the declared inputs (`--input` text, or
`--input-file`, which records the file's path and SHA-256), the UTC timestamp, every
sample, and the SHA-256 of stdout. `--memory` adds the peak resident memory of each
timed run. If any run exits non-zero, it reports the failure with the end of stderr and
writes no record. The record's name is checked so that nothing is written outside
`--out-dir`; temporary capture files are also made there.

`compare` reports the ratio of medians (after / before), a 95% bootstrap interval for
it (2000 resamples, seed 0 by default, so the output is repeatable), whether stdout was
identical, and a verdict:

- `faster` when the whole interval is below 1, `slower` when it is above 1;
- `not distinguishable at this sample size` otherwise, and always when either record
  has fewer than 5 runs.

It refuses (exit 2) records whose command or declared inputs differ, unless given
`--allow-mismatch`, in which case it compares and prints a warning. With `--out-dir` it
also writes the comparison as a JSON record.

Exit codes: 0 done, 1 the command failed, 2 refused or a usage error.

## What it cannot do

- **It times whole processes.** Start-up is included. For work of a few milliseconds the
  start-up can be most of what is measured.
- **It cannot see conditions it is not told about:** build mode, cache state, other load
  on the machine, CPU frequency changes, a changed input file declared with the same
  `--input` text (use `--input-file` to catch that).
- **The interval assumes the runs are independent draws.** Drift during the
  measurement (a machine warming up, another job starting) breaks that, and the
  interval does not show it.
- **The verdict is about the machine the records were made on and the input they
  declare.** It says nothing about other inputs or about how the change scales.
- **Peak memory** is `ru_maxrss` for the child process as returned by `wait4`
  (converted from kilobytes on Linux, taken as bytes on macOS). Whether it includes
  processes the command starts in turn depends on the platform and was not checked.
  Not available on Windows, where `measure.py` does not run (it uses `os.wait4`).
- **Correctness is only compared as identical stdout.** A program whose output
  legitimately varies, or that writes its result to a file, needs its own check.
- **Nothing makes the agent use it.** The hook directive names it; whether the agent
  runs it is up to the agent.

## Status

The tool and its tests run. **It has not yet been evaluated for effect on outcomes**:
no comparison of agent sessions with and without the kit has been made.

## Install

Copy this directory to `grounding-kits/performance/` beside `task_grounding.py` (for
example `.claude/hooks/grounding-kits/performance/`). The hook then names `measure.py`
and `PLAYBOOK.md` in its performance directive. The tool also works on its own.

## Test

```bash
python3 -I test_measure.py
```

Standalone, no pytest; takes a few seconds, since it times real commands. 22 cases: a
record's contents, a clear speed-up and a clear slow-down from real timed runs (a Python
program that sleeps for 0.2 s, then 0.02 s, with the same command line and input),
overlapping samples judged not distinguishable, one run each never given a verdict, the
seeded bootstrap repeating exactly, refusal of a different command and of different
inputs, `--allow-mismatch`, stdout identical and different, the comparison record, a
failing command and a missing program reported as failed with no record, a name that
would leave the directory, `--runs 0`, `--input-file` hashing, and (on Linux) peak
memory above a 100 MiB allocation. `MEASURE=/path/to/copy.py python3 -I test_measure.py`
runs the same cases against another copy.
