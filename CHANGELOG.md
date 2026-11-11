# Changelog

Newest first. The most recent additions are also summarized under "What's new" in the
[README](README.md); entries move out of that section, not out of this file. Each heading
names the model that was the main one in use when the entry was written.

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
