# Heartbeat protocol (read on every fire)

A heartbeat fire is a prompt from a cron job, not from the operator. It names the heartbeat and its file. The file
says what the work is; this protocol says how each fire runs. Where the file and this protocol disagree, the file's
Constraints win. A message from the operator during a fire takes priority over the fire.

`HB` below is `python3 ~/.claude/skills/heartbeat/heartbeat.py`.

## 1. Count the fire

Run `HB tick NAME`. It returns the fire number, whether a zoom-out is due, whether the cron job needs renewal, and
whether the heartbeat is paused.

- Paused: reply with one line saying so and stop.
- Renewal due: CronCreate a replacement with the cron from `HB status` and the prompt from `HB prompt NAME`
  (recurring, not durable), CronDelete the old job, run `HB renewed NAME --job NEW_ID`.

## 2. Orient

Read the heartbeat file: Goal, Done when, Constraints, the queue, and the last few STATE lines. If the file names a
knowledge log, read what it says to read. Do not rely on the conversation's memory of the work; the file is the
state, and the conversation may have been compacted since the last fire.

## 3. Run the checks

Run every item under Checks (jobs started earlier, external reviews, anything waiting). Use the real result: read
exit codes, not a piped tail; confirm a job is running by its own log, not by having started it.

## 4. Zoom out, when due

When `tick` says `zoom_out`, before taking a step answer in writing, as a STATE line:

1. Does the top of the queue still serve the Goal, or has the work drifted into fixing the last measured gap?
2. What would each possible result of the next step say about the Goal?
3. Does the next step only add (parts, flags, special cases) without removing anything? If so, what is it standing
   in for?
4. Is anything in the queue now pointless given what was learned?

Reorder or rewrite the queue from the answers. A step that cannot answer 2 is not taken.

## 5. Take one step

Take the first queue item that can proceed now. Do one focused piece of it, roughly the time between fires. Ground
in the actual code or data before designing; verify by running, not by reading; treat a check as passing only after
it has been seen to fail on a wrong input. If the item is blocked, say why in the queue and take the next one.

When no queue item can proceed, the queue is not the only source of work. Run `HB idle NAME --blocked q1=REASON ...`
with a reason for every queue item. It runs each command under the file's Fallback work section (the structural
review, stale plan status lines, unindexed papers and the like) and refuses while any of them prints an item you have
not named blocked with a reason. When it refuses, the first open item it lists is this fire's step: take it as in the
paragraph above, and add it to the queue if it will take more than one fire. Do not name a fallback item blocked to
get past the check. Name it only when it truly cannot proceed without the operator (a review whose scope they must
pick, work that would collide with their deploy), and give that reason.

When `HB idle` pauses the heartbeat, nothing in the queue or the fallback sources can move without the operator.
CronDelete the job (the id is in its output), append the `state_line` it printed to STATE, and tell the operator
through the Escalation section that the heartbeat paused itself and what each blocked item is waiting for. They resume
it with `HB resume NAME` and a new job, as after any pause.

When work is waiting on something that will change without the operator (a run, a CI result, a reply), do not
pause. Make the fire a quiet fire instead: one line, no step. After three quiet fires in a row with a long wait ahead, slow the job down: `HB cadence NAME --cron SPARSER`,
CronCreate the job with that cron and the prompt it prints, CronDelete the old job, `HB renewed NAME --job NEW_ID`,
and note it in STATE; restore the cadence the same way when work resumes. Never `HB start` again for this: it resets
the fire count, the log and the zoom-out interval.

## 6. Record

- Append one STATE line to the file: the time from `date`, what was done with its evidence (commit hash, file, run
  name, measured number), what is running (names, ids, expected end), and the next step.
- Update the queue: remove what is done, add what follows, keep it ordered. No emphasis marks; order is priority.
- If the file names a knowledge log, write into it every result, refutation or change of direction this fire
  produced, with its evidence. What is running goes in STATE; what was learned goes in the log.

## 7. Reply

A short note: what changed and what is next. Report outcomes as they are: a failure with its output, a skipped step
as skipped, a claim only once it has been checked. Contact the operator outside the session only as the file's
Escalation section allows.

## Pausing

`HB idle` is the only way the agent pauses a heartbeat on its own (step 5). When the operator asks to pause, finish and record the current step first, then CronDelete the job (its id is in
`HB status`) and run `HB pause NAME`. The hook will not re-create a paused heartbeat.

## Wind-down before compaction

The context-winddown mod (`~/.claude/skills/context-winddown`) checks context size at the end of every turn. Past its
threshold (`CONTEXT_WINDDOWN_TOKENS`, default 450000) it sends one prompt starting `[context-winddown]`. That prompt
is not a fire: do not run `HB tick`. Finish and verify the step in progress, or record it as unfinished, and take no
new queue item. Then run step 6 in full: the STATE line, the queue, and every finding not yet in the knowledge log,
since after the compaction only the file is the state. Commit finished work where the file's Constraints allow. Last,
call `mcp__context-winddown__ready_to_compact` and end the turn; the mod compacts when the turn ends, and the next fire
orients from the file as in step 2.
