# Changelog

Newest first. The most recent additions are also summarized under "What's new" in the
[README](README.md); entries move out of that section, not out of this file. Each heading
names the model that was the main one in use when the entry was written.

## 2026-11-15 (Opus 5.5)

- Added [`hook-trial/`](hook-trial/): an optional on/off trial for the claim gate,
  `plan-reconciliation`, `placeholder-disclosure` and `task-grounding`. With a trial file
  (`<project>/.claude/hook-trial.json` or `~/.claude/hook-trial.json`) enabled, all four stay
  silent in sessions where the lowest bit of sha256(salt + ":" + session id) is 1. Off by
  default; any problem with the file leaves the hooks on. `compare_arms.py` recomputes each
  session's arm and compares the arms from the transcripts, judging final messages with the
  claim gate's own `judge()`; the README states what this design can and cannot show. Each
  hook has a new `test_hook_trial.py`; the existing tests are unchanged and pass.
- Claim gate: `main()` now calls a new `judge(events, text)`, which the trial's analysis
  imports. `replay.py` sets `HOOK_TRIAL_IGNORE=1` so a running trial does not silence the gate
  in a replay.
- [`task-grounding/`](task-grounding/): "benchmark" alone no longer sets the performance
  category. It set it for prompts about installing and running a benchmark suite and the disk
  space its images need. It now counts in "microbenchmark", after "performance", "speed",
  "timing", "latency", "throughput" or "memory", and as a verb with a piece of code as its
  object. Eleven new tests: seven such prompts that must stay silent for performance, four
  that must still set it.
- [`request-fidelity-review/`](request-fidelity-review/): trialled on five past cases where
  an agent misread the user's intent, plus three controls. It caught 1 of 5. Of its other
  flags, 19 of 30 on the cases and 11 of 17 on the controls were judged noise, by a single
  scorer who knew the answers. Not recommended for installation as it is: its prompt
  forbids judging level, register and order, where the misreadings were, and run after the
  work is built it saves little. It must run as an agent type that does not load the user's
  memory index. The reviewer prompt is unchanged.
- `extract_user_messages.py` now keeps the user's answers to AskUserQuestion prompts
  (chosen options, typed "Other" text, notes, and a reply to the prompt), labelled as
  answers to questions the agent asked. Claude Code records these as tool results, so the
  extractor dropped them before. Other tool results are still excluded. Tests use
  synthetic records.
- [`task-grounding/`](task-grounding/): added a `reader` category for requests to produce a
  large piece of work for a reader (a course, lessons, tutorial, guide, documentation, long
  report, explainer, or "teach me" / "so that I can understand" / "explain ... from the
  beginning"). Before building all of it, the agent states which reading of the key phrase
  it takes and who the reader is, shows one representative piece first, and checks it
  against any level or goal the user stated. Twenty-eight new tests, sixteen of them ordinary
  coding prompts about docs, reports, guides and errors that must not set it.

## 2026-11-14 (Opus 5.5)

Written by Opus 5.5 subagents against the shortcomings Anthropic's Opus 5.5 system card
reports, to a plan and acceptance cases set by a separate session. None of the hooks has
run in a live session yet.

- Revised the verification-claim gate: claims are matched by kind to supporting commands;
  tool results are read (`is_error`, failure summaries in output); whole-file claims are
  checked against Read ranges; the final message comes from `last_assistant_message`; a
  turn starts at a record with `turnPosition`, so injected `isMeta` records no longer reset
  it; "healthy" counts only about running systems; fails open on any exception. Added
  `replay.py` (offline replay, blind labelling sample, scoring).
- Added [`plan-reconciliation/`](plan-reconciliation/): a Stop hook that makes dropped plan
  items visible in the final report (system card §2.3.3).
- Added [`placeholder-disclosure/`](placeholder-disclosure/): a Stop hook that lists
  undisclosed placeholder code written in the turn (system card §6.2.2), and a draft
  "blocked is an accepted result" rule.
- Added [`pasted-text-guard/`](pasted-text-guard/): an invisible-character detector for
  system card §6.5.1, with the evidence on what Claude Code already strips and marks.
- Added [`request-fidelity-review/`](request-fidelity-review/): a user-message extractor
  and a reviewer subagent for system card §2.3.3. The trial on past sessions is not yet run.
- Claim gate, second revision: whole-file coverage counts reads from every turn of the
  session; `sed -n`, `head` and `cat` count as reads; claims to have read a whole
  repository or codebase are always flagged; speed and memory claims ("3x faster",
  "reduced memory usage by 40%") need a timing or benchmark command in the turn. Eleven
  tests added (`S-1` to `S-7`, `P-1` to `P-4`).
- Claim gate, fixes from review of the second revision, each with a test that failed
  first (`G-1` to `G-13`): shell reads are parsed per pipeline, so `cat FILE | head -30`
  is a partial read, a `cat` in a heredoc or written to a file is no read, `cat -n` and
  several files count, and output Claude Code cut short is a partial read; paths are
  resolved against the recorded working directory and matched by path suffix, not base
  name; a named file never read fails the claim; "the entire project brief" is no longer a
  repository claim; timing commands must be in command position; "runs in 40 minutes"
  without "now" or a before-and-after is not a speed claim; "all pass means ..." is a rule,
  not a report; "I've read through <directory>" and "I read all four <documents>" are
  checked against the session's reads. `S-5` now uses the `cat | head` command alone, and
  the two-command form is `S-5b`.
- Added [`task-grounding/`](task-grounding/): a UserPromptSubmit hook that adds one
  directive per category of work (performance, visual, scientific, multi-step), chosen by
  keywords, once per session. Targets the categories where the Fable 5.2 system card
  reports Opus 5.5 furthest behind (§8.7). Not run live; effect unmeasured. After review:
  narrower patterns (ten ordinary coding prompts that misfired are now silent tests), a
  prompt starting with an absolute path is no longer taken for a slash command, a corrupt
  state file is treated as empty, and the scientific directive names the reference checker
  by an absolute path found from the hook's own location.
- Added [`reference-store/`](reference-store/): the format of a project's compiled domain
  reference, where every claim is tagged with its source, read date and status (`source`,
  `secondary`, `inferred`), and `check_reference.py`, which validates a reference and
  finds the entry for a search term. Includes a small example reference.

## 2026-11-11 (Opus 5.5)

- Added [`heartbeat/`](heartbeat/): `/heartbeat` keeps a session working between operator
  messages through a session-only cron job that runs a fixed protocol against a per-work
  file, with a hook that re-creates the job after restarts and carries unrecorded state
  through compactions.
- Added [`context-winddown/`](context-winddown/): a mod that asks the agent to wind down at a
  context threshold and compacts when the agent signals it is ready.
- README: added "What's new", this changelog, and a column naming the model each entry was
  written against.

## 2026-10-23 (Opus 5.5)

- Added [`deneuralyzer/`](deneuralyzer/): treats each failure on a real input as a training
  example and the code as the model, so fixes generalize instead of encoding the example.

## 2026-08-19 to 2026-08-20 (Opus 5)

- Added [`standing-corrections/`](standing-corrections/): three defaults that are wrong in one
  place (trusting inherited code over a failing test, citing the PDF instead of the paper,
  varying wording inside a fixed vocabulary).
- `standing-corrections`: scoped the terminology rule to writing, not searching, and ordered
  it against `seam-proof-build`.

## 2026-08-09 (Opus 5)

- Added [`literature-scope-discipline/`](literature-scope-discipline/): reading papers without
  being fooled by them, with a novelty-sweep protocol.

## 2026-07-29 (Opus 5)

- Added [`response-length-calibration/`](response-length-calibration/) and
  [`per-model-discipline/`](per-model-discipline/): the verbosity rule, and the hook that
  delivers a rule to one model family, with an installer an agent can run.
- `per-model-discipline`: re-injects `on-change` payloads after a compaction.

## 2026-07-21 to 2026-07-24 (Opus 5)

- Added [`seam-proof-build/`](seam-proof-build/), the through-build companion to `/ground`.
- Added [`discipline-compliance-scanner/`](discipline-compliance-scanner/), the retrospective
  auditor of session transcripts.
- Added [`stopping-rules/`](stopping-rules/): four standing rules for stopping too early.
- Added the MIT licence; replaced em dashes in Markdown with plain dashes.

## 2026-07-07 to 2026-07-11 (Opus 4.8)

- Added [`theory-formation-discipline/`](theory-formation-discipline/) with the
  verification-claim Stop hook, then move 9 (deflate the seductive frame, keep the result).
- Added [`ground-skill-verifier/`](ground-skill-verifier/), fixing a tool-result window bug on
  the way in.
- Added [`experiment-freeze-gate/`](experiment-freeze-gate/) and
  [`delegated-build-stint/`](delegated-build-stint/), generalized from research-delegation
  rules.
