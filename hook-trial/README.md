# Hook trial (measure four hooks on your own work)

An optional on/off switch built into four hooks of this repository, and a script that
compares the two groups of sessions afterwards. In a random half of sessions all four hooks
stay silent; in the other half they work as usual. After a few weeks of ordinary work,
`compare_arms.py` reads the session transcripts and reports, per group, how often a final
message made a completion claim the claim gate finds unsupported, how often each hook fired,
output tokens per turn, and user follow-up messages, each with an interval.

The hooks that take part:

- [`theory-formation-discipline/verification-claim-gate/`](../theory-formation-discipline/verification-claim-gate/) (Stop)
- [`plan-reconciliation/`](../plan-reconciliation/) (Stop)
- [`placeholder-disclosure/`](../placeholder-disclosure/) (Stop)
- [`task-grounding/`](../task-grounding/) (UserPromptSubmit)

Targeted at: Opus 5.5

## Why

None of these hooks had been measured. Their tests show that each one fires on the inputs it
was written for and stays silent on others; they do not show that a session goes better with
the hooks than without them. Running a set of benchmark tasks twice answers a different
question (other people's tasks, one attempt each). This compares sessions of your own work,
where the only systematic difference between the groups is whether the hooks were on.

## The switch

Each of the four hooks has the same function, `trial_arm`, word for word; a test checks
that the four copies are identical. The directories still share no code.

**Off by default.** With no trial file, each hook behaves exactly as before.

**The trial file** is JSON:

```json
{"enabled": true, "salt": "any string, chosen once", "start": "2026-11-16"}
```

- `enabled` must be `true` (the JSON boolean) for the trial to run.
- `salt` is any non-empty string. It decides which sessions fall in which arm; keep it
  unchanged for the whole trial.
- `start` (optional) is a date, `YYYY-MM-DD`, in UTC. Before that date the hooks behave
  normally.

**Where it is looked for.** `<project>/.claude/hook-trial.json`, where `<project>` is the
`CLAUDE_PROJECT_DIR` environment variable, or the payload's `cwd` when that variable is not
set; if that file does not exist, `~/.claude/hook-trial.json`. The first file that exists
decides, so a project file with `"enabled": false` takes that project out of a trial set up
in the home directory.

`CLAUDE_PROJECT_DIR` comes first because the hooks reference says the payload's `cwd`
"follows Claude into worktrees and after `cd`", while `${CLAUDE_PROJECT_DIR}` "stays at the
project root where the session started". Looking only at `cwd` would let one session read
different trial files at different times, and so be partly on and partly off. The reference
shows `$CLAUDE_PROJECT_DIR` used in hook commands; that it is set in the hook process's own
environment is inferred from that, not stated, which is why `cwd` is the fallback.

**The arm** is the lowest bit of `sha256(salt + ":" + session_id)`: 0 is "on", 1 is "off".
`session_id` is a common input field of every hook event, so the four hooks compute the same
arm for the same session, and the analysis can compute it again from the session id alone.
In the "off" arm a hook exits 0 with no output before doing anything else (task-grounding
does not even record which directives it would have sent).

**Fail safe.** Anything unexpected means "on": no session id, a trial file that is
unreadable, a directory, not JSON, not an object, `enabled` not exactly `true`, a missing or
empty salt, a `start` that is not a `YYYY-MM-DD` date. A hook never crashes or blocks because
of the trial file. The worst a broken trial file can do is leave every session on.

**Nothing extra is written.** The hooks record nothing about the trial.

`HOOK_TRIAL_IGNORE=1` in the environment makes a hook ignore the trial file. `replay.py` sets
it when it runs the claim gate over old transcripts, since it asks what the gate would have
done. Set it too when running the hooks' own test suites while a trial file is enabled in
your home directory; the older test cases run the hooks with your real `HOME`, and in the
off arm they would see silence.

## Running a trial

1. Install the four hooks from this repository as each README describes, in versions that
   have `trial_arm` (2026-11-15 or later).
2. Choose a salt, for example with
   `python3 -c "import secrets; print(secrets.token_hex(8))"`, and write
   `~/.claude/hook-trial.json` with `"enabled": true`, the salt, and a `start` date of the
   next day, so that no session already running is split across the start.
3. Work as usual. Do not change the salt, the hooks or the trial file during the trial.
4. Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30 days,
   according to its documentation). Raise that setting before a long trial, or run the
   analysis before the first sessions age out.
5. At the end, set `"enabled": false` (or delete the file) and run the analysis with `--end`
   set to the day after the last day of the trial.

```bash
python3 -I compare_arms.py --trial-file ~/.claude/hook-trial.json --end 2026-12-14
python3 -I compare_arms.py --salt SALT --start 2026-11-16 --end 2026-12-14 --json
python3 -I compare_arms.py --trial-file ~/.claude/hook-trial.json --project=-path-of-one-project
```

Options: `--projects` (default `~/.claude/projects`), `--project NAME` to read only some
project folders (repeatable; folder names start with `-`, so write `--project=NAME`),
`--gate` (default: the claim gate in this repository), `--resamples` (default 2000),
`--seed`, `--json`. The output holds counts and rates only: no message text, no session ids.
Run it with `python3 -I`; transcripts are data, and nothing in them is followed.

## What it reports

Per arm, for the main sessions (`<project>/<session-id>.jsonl`) that started on or after the
start date:

| Figure | How it is computed |
|---|---|
| sessions, turns | A turn starts at a user record carrying `turnPosition`; in transcripts without that field, at a user record that is not meta and carries text rather than a tool result. Compaction summaries do not start a turn. |
| output tokens per turn | `message.usage.output_tokens` of the main transcript, once per `message.id` (one API message is written as several records, each repeating its usage), divided by turns. Subagent transcripts (`<session>/subagents/*.jsonl`) are reported on a separate line. |
| unsupported completion claims per judged turn | The final message of each turn is the last assistant message (by message id) with text and no tool call after it. It is judged by the claim gate's own `judge()` function, imported from the file given with `--gate`, with the transcript up to that message. In the on arm, a turn the gate paused is counted by the message the model sent after the pause. |
| claim-gate blocks | Gate firings, recognised as below. |
| firings per hook | See the next section. Should be 0 in the off arm; if not, the report prints a warning. |
| user follow-up messages per session | User prompts after the first whose `origin.kind` (or `turnOrigin`) is `human`; without those fields, a prompt that is not meta and does not start with a harness tag. **Rough**: a follow-up may be a correction, a new request or a thank-you. |

Each figure is a ratio over sessions (for example, all unsupported final messages of the arm
divided by all its judged turns). Its interval is a 95% percentile bootstrap: sessions are
drawn with replacement within the arm, 2000 times by default, with a fixed seed. The
difference "on - off" gets an interval the same way. No interval is given for an arm with
fewer than two sessions.

Records that cannot be read are counted by reason and listed at the end: lines that are not
JSON, records without a type, assistant records without a message id, files whose name is not
a session id (set-aside `.orphaned-` copies), sessions whose records carry another session
id, sessions with no timestamp or no turns, turns with no final text (ended on a tool call or
an API error), and prompts judged human by the fallback rule.

## What the transcripts show, and what they do not

The transcript format is internal to Claude Code and changes between versions; the
documentation names the kinds of entries and not their fields. What is below was checked
against transcripts written by Claude Code 2.1.322 to 2.1.325 (record shapes only); other
versions were not checked.

**Identifiable.** A hook firing is recognised by the opening words of that hook's own output
(`Send-time verification check.`, `Plan check: the session plan`, `Placeholder check: this
turn wrote placeholder code`, `Task routing (sent once per session per category`), found in a
record the harness writes for hook output, never in the user's or the model's own text:

- the claim gate's `decision: "block"` appears as an `attachment` record of type
  `hook_blocking_error` (with the reason and the hook's command) and as a meta user message
  beginning `Stop hook feedback:`. Both shapes occur in transcripts of the versions checked.
  One block shows in both, so per turn and hook the count is the largest count in any one
  kind of record, not their sum;
- task-grounding's `additionalContext` appears as an `attachment` of type
  `hook_additional_context` with `hookEvent: "UserPromptSubmit"`. This shape also occurs in
  transcripts of the versions checked.

**Identifiable in principle, not yet seen.** Plan-reconciliation and placeholder-disclosure
return `additionalContext` on Stop. The hooks reference says this continues the conversation
and is "labelled `Stop hook feedback` in the transcript"; the `stop_hook_summary` system
record also has a `hookAdditionalContext` list. The script searches both, and any
`attachment` whose type starts with `hook`. No transcript with a firing of either hook was
available to check against, so their counts are tested only on synthetic records until one
is.

**Not identifiable.**

- Which hook names fired from the record's own fields: `hookName` holds the event name
  (`Stop`), not the script, so the opening words are the only handle. If a hook's message is
  reworded, `SIGNATURES` in `compare_arms.py` must be updated; a test checks that each hook's
  source still contains its signature.
- A hook that ran and stayed silent leaves no trace beyond the list of commands in
  `stop_hook_summary`; so the analysis cannot tell an on-arm session where nothing triggered a
  hook from an off-arm session.
- Whether the model followed a task-grounding directive, or what it would have done without
  one.
- Whether a claim is true. The claim judgement is the gate's own pattern match, with the
  misses and false positives listed in its README.

**A bias to keep in mind.** In the on arm, the gate tells the model which wording it objected
to, and the model often restates the claim. The analysis then judges the restated message
with the same patterns. A lower rate in the on arm therefore partly measures rewording that
the gate's patterns no longer match, not only checks that were run. The off arm has no such
feedback. Read the claim rate together with the other figures, and read a sample of the
on-arm corrections before drawing a conclusion.

## What this design can show, and what it cannot

It can show **differences between the two arms on one user's own work**, during the trial,
with the hook versions installed at the time.

It cannot give benchmark scores, compare models, or compare one user's results with
another's. It cannot say why a difference arose, or whether the work itself was better, only
what the measured figures did.

- **The session is the unit.** Turns in one session depend on each other, so intervals are
  computed over sessions, not turns.
- **Intervals will be wide.** One user over a few weeks produces tens of sessions per arm,
  and sessions differ greatly in length and kind. An interval that includes zero is not
  evidence that the hooks do nothing; it means this trial could not tell.
- **Not blind.** Once a hook fires in a session, the user (and the model) can tell that the
  session is in the on arm, and may act differently for the rest of it; this affects the
  follow-up count most. Before the first firing nothing shows which arm a session is in.
- **All four hooks switch together**, so the trial measures their combined effect and cannot
  separate one hook from another.
- **Several figures are reported.** With ten figures, one interval may exclude zero by chance.
- **Sessions that span the start date are excluded** (judged by the first timestamp in the
  transcript). Whether a resumed session keeps its session id is not stated in the
  documentation; a transcript whose records carry a session id other than its file name is
  excluded and counted.
- **Hook coverage is uneven.** Stop hooks do not run on a user interrupt; turns that end that
  way are still judged, in both arms.

## Test

```bash
python3 test_compare_arms.py
```

Standalone, no pytest, synthetic transcripts only. 40 cases: the shared session-id vectors;
that all four hooks and `compare_arms.arm` give the same arm for 1,000 random session ids and
that about half land in each arm; that `trial_arm` is word for word the same in the four
hooks and each hook still emits its signature; and the analysis on a synthetic projects
directory: sessions, turns, tokens counted once per message id, subagent tokens, a paused turn
counted by its corrected final message, firings from each kind of record without double
counting, a hook message pasted by the user or quoted by the model not counted as a firing,
follow-ups that leave out task notifications, every unreadable record counted by its reason,
an older transcript shape, the seeded bootstrap, `--project`, `--trial-file`, `--gate` (a
stand-in gate is used when given), refusal of a gate without `judge()` and of a malformed
date, and a text report that holds no session ids or message text.
`COMPARE_ARMS=/path/to/other/compare_arms.py python3 test_compare_arms.py` runs the same
cases against another copy.

Each of the four hooks has its own `test_hook_trial.py` for the switch: the same vectors,
silence in the off arm, every fail-safe case, the lookup order, and `HOOK_TRIAL_IGNORE`.

## Status

The switch and the analysis are tested on synthetic transcripts. No trial has been run yet,
and the script has not been run on transcripts of a session in which the switch was active.
