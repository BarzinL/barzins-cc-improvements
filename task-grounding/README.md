# Task grounding (Claude Code UserPromptSubmit hook)

A UserPromptSubmit hook that recognises a few categories of work from the words of
the prompt and adds one short directive for each, once per session: measure before
and after for performance work, render and look for visual work, read sources before
coding for scientific work, write a plan file for multi-step work, and, for a large
piece of work meant for a reader (a course, tutorial, guide, documentation, long
report), state the reading and the reader and show one piece before building the rest.

Targeted at: Opus 5.5

## The failure it targets

Anthropic's system card for Claude Fable 5.2 and Claude Mythos 5.2 (2026-11-09)
compares the two models on long engineering tasks. Section 8.7, FrontierSWE v2
(page 212):

> It was ahead of GPT-6 Astra (65.5%), Claude Opus 5.5 (62.3%), [...]
> Its gains over Opus 5.5 were greatest for performance
> optimization, scientific computing, and visual reasoning.

Section 8.13.2, BenchCAD 2.1, rebuilding parts from engineering drawings and rendered
images (page 233):

> Claude Fable 5.2 scored 75.4% without tools and 83.5% with tools. Claude Opus 5.5 scored
> 49.0% without tools and 65.3% with tools

And the Opus 5.5 system card, section 2.3.3, on flagged behaviour in internal use:

> The second most common subcategory was dismissing its
> own doubts or abandoning its own stated plan

Part of the gap in these categories is a step that a careful engineer takes and the
model often skips: measuring before claiming a speed-up, looking at the rendered
output instead of reasoning about it from the code, checking a domain fact at its
source instead of recalling it, writing the plan down so it can be checked off.
Asking the model to notice when it is out of its depth relies on the judgement that
is weak in these categories. This hook decides the category mechanically, from the
prompt's words, and adds the step as an instruction at the start of the work. It
costs one short paragraph per category per session.

The reader category comes from a different source: a trial of this repository's
`request-fidelity-review/` reviewer on 2026-11-15, on five past cases where an agent
misread what the user wanted. The misreadings were about the reader's level, the
register and the teaching order, and about one ambiguous key phrase in the request, not
about scope. A review after the work was built caught 1 of the 5 and, where it did
catch, saved little, because the whole deliverable had already been produced. The
check is cheaper before the work: say which reading and which reader you are assuming,
then show one piece.

## What it does

On each `UserPromptSubmit`, the hook:

1. skips the prompt if it is shorter than 40 characters, starts with `<` or `!` (harness
   traffic, shell commands) or with a slash command (`/name` followed by a space or the
   end; a prompt starting with an absolute path such as `/home/...` is not skipped), or
   contains `<task-notification` or `[Subagent hand-back]`;
2. removes fenced code blocks and `<pasted_content>` blocks, so words inside pasted
   code do not set a category;
3. matches what is left against each category's regular expression in
   `categories.json`;
4. drops categories whose directive was already sent in this session, recorded in
   `task-grounding-seen.json` in the session's scratchpad directory (or, without a
   scratchpad, `task-grounding-<session_id>.json` in the system temp directory). A state
   file that is not valid JSON is treated as empty and rewritten;
5. if any category is left, prints one `additionalContext` message listing their
   directives, and records them as sent.

| Category | Matched by (examples) | Directive, in short |
|---|---|---|
| performance | optimise / optimization, speed up, run faster, faster than, too slow, slower, latency, throughput, profiling, profiler, flame graph, microbenchmark, performance or speed benchmark, benchmark it / the parser / the change (a verb with a piece of code as its object), bottleneck, memory usage, hot path | Measure with a rerunnable command before changing anything, rerun it after, report both numbers and the command. |
| visual | screenshot, mockup, wireframe, page or CSS layout, renderer, render the page / image / chart, diagram, bar or line chart, plot, matplotlib, CSS, SVG, canvas, shader, Figma, CAD, UI, pixel, font | Render the output to an image and look at it before reporting; compare with any reference image. |
| scientific | simulation, numerical, ODE / PDE solver, finite element, Monte Carlo, Bayesian, linear or logistic regression, statistical test, statistically significant, t-test, p-value, genome, protein or DNA sequences, sequencing, molecule, spectroscopy, FFT, Fourier, eigenvalue, SI units, unit conversion, dimensional analysis, methylation | Say first that this is domain work; look in the project reference; if nothing is there, read primary sources and add an entry; validate against a known answer; state units. |
| multi-step | end to end, phases, milestones, migration, refactor, roadmap, step by step, or a list of three or more items | Write the steps as a checklist in `plan.md` in the scratchpad, tick them off, account for every item at the end. |
| reader | write / draft / create / put together / build / want ... a course, lessons, tutorial, explainer, walkthrough, primer, handbook, guide, write-up; write / draft / create ... documentation or docs; a long or detailed report, a report on / about; teach me; so (that) I can understand; explain / teach / learn ... from the (very) beginning, from first principles, from zero, assuming I know nothing, complete beginner | Before building all of it: state the reading of the key phrase and who the reader is and what they know, in the user's words; build one lesson or section and show it first; check its order, pitch and wording against any level or goal the user stated. |

The patterns are narrow on purpose. A bare "regression", "sequence", "statistics",
"unit", "chart", "render", "faster", "slow", "profile" or "simulate" appears in ordinary
coding prompts ("unit tests", "a regression in the login flow", "Helm charts", "the
component re-renders", "answer faster", "the user profile page"), so each now needs a word
beside it that places it in the category. This loses some recall: "the simulated annealing
step diverges" is missed, and "make the plot render faster" sets visual but not
performance. A directive that fires on ordinary coding prompts costs more than one that
sometimes misses.

"Benchmark" is narrowed the same way (2026-11-15). On its own it set the performance category
for prompts about installing and running a benchmark suite, or the disk space its images
need, which is evaluation work, not making code faster. It now counts in "microbenchmark",
after "performance", "speed", "timing", "latency", "throughput" or "memory", and as a verb
whose object is a piece of code ("benchmark it", "benchmark the parser", "benchmark the change
against the old implementation"). "Run the benchmark suite", "the benchmark runner" and "the
benchmark's images" no longer set it. Missed as a result: "run the benchmarks again after the
fix" and "the benchmark shows a regression" without a speed word.

The reader pattern draws its boundary the same way. A deliverable noun counts only
after a verb of producing or asking for it ("write", "draft", "put together", "I want"),
within four words, and only when the noun ends the phrase: it must be followed by
punctuation, the end of the prompt, or a word that starts a description ("on", "about",
"for", "that", "so", ...). A noun followed by another noun is a modifier and does not
count: "a test report parser", "the tutorial page", "the course table", "the docs
build", "a bug report template". "Documentation" and "docs" need an authoring verb
("write", "draft", "create", "put together"), so "build the docs" and "update the
documentation for the flag" stay silent. A plain "report" needs "on", "about",
"explaining" or "covering" after it, or an adjective before it ("long", "detailed",
"full", ...), so "generate a coverage report" stays silent. "Explain" alone does not
count; it needs a stated starting level within the same sentence ("from the beginning",
"from first principles", "assuming I know nothing"). "Help me understand" does not
count, because it is how debugging questions are often asked; "so that I can
understand" does. "From scratch" is not used, because "rebuilt from scratch" is common
in coding prompts.

The scientific directive tells the agent how to search the project reference. The hook
looks for `check_reference.py` (from `reference-store/`) beside itself, in a
`reference-store/` directory beside itself, or in `../reference-store/` (the layout of this
repository), and names the first one found by absolute path:
`run python3 "/abs/path/check_reference.py" --find <term>, or read docs/reference/INDEX.md`.
If none is found, the directive says only `read docs/reference/INDEX.md`.

The performance and scientific directives name a grounding kit when one is found
(`grounding-kits/` in this repository, added 2026-11-15). The hook looks for
`grounding-kits/performance/` and `grounding-kits/scientific/` beside itself or one level
up, and uses a kit only if both its tool and its `PLAYBOOK.md` are there. With the kit,
the directive tells the agent to read the playbook and to use the tool, both named by
absolute path:

- performance: `Read "/abs/.../PLAYBOOK.md" first`, then time the command before the
  change with `measure.py run --name before`, after it with `--name after`, run
  `measure.py compare` on the two records, and report its verdict, both medians and the
  command;
- scientific: the same bold line and reference lookup as before, then `Read
  "/abs/.../PLAYBOOK.md"`, record each check against an independent expectation with
  `validate.py add`, and run its `summary` before reporting.

Without the kit, each category sends the plain directive in the table above, unchanged.
Each category's `kit` object in `categories.json` holds the kit's directory, tool,
playbook and directive text.

The multi-step directive feeds `plan-reconciliation/`, which reads that `plan.md` at
the end of each turn. The scientific directive points at `reference-store/`, and, when
found, both it and the performance directive point at `grounding-kits/`.

The rules are data. To add a category, change a pattern or reword a directive, edit
`categories.json`; the hook reads it on every prompt.

### The hook interface it relies on

Checked against the Claude Code hooks reference (code.claude.com/docs/en/hooks) on
2026-11-14:

- Input: the common fields (`session_id`, `transcript_path`, `cwd`, and
  `scratchpad_dir`, which is "Absent when the session has no scratchpad or the temp
  directory is unavailable. Requires Claude Code v2.1.257 or later") plus `prompt`,
  "the submitted text". "Pasted content that collapsed to a `[Pasted text #N]`
  placeholder arrives expanded in place."
- Output: `hookSpecificOutput` with `hookEventName: "UserPromptSubmit"` and
  `additionalContext`, a "String added to Claude's context alongside the submitted
  prompt", injected "as a system reminder that starts with the hook's name". The
  event "can't replace the prompt; it only injects `additionalContext` alongside it."
  Strings over 10,000 characters are saved to a file instead; the directives are far
  below that.
- When it fires: not only on typed prompts. The reference lists "A session-scoped
  scheduled task firing, including a `/loop` iteration", "A background subagent
  reporting back to the session that started it", "A message another session sends to
  your main conversation", and Code Mode output. A typed slash command arrives "as you
  typed it rather than the expanded skill content".

The hook's output has that shape. It never blocks a prompt and never changes it.

Properties:

- **Advisory.** It adds text and nothing else.
- **Once per category per session.** A session that stays on performance work hears
  the performance directive once.
- **Fails open.** Malformed input, a missing rules file, an unreadable state file (a
  directory, no permission), or any exception ends in exit 0 with no output. A state file
  with invalid JSON is not an error: it is treated as empty. With neither a scratchpad nor a
  usable session id it stays silent, rather than repeat the directive on every prompt.
- Python standard library only.

## What it cannot do

- **Categories are keyword matches, and they will still misfire.** The misfires found in
  review are fixed and tested ("unit tests", "a regression in", "sequence of", "summary
  table of statistics", "Helm charts", "re-renders", "answer faster", "optimistic", "user
  profile page", "simulate a click"), but any pattern can match a prompt outside its
  category ("the UI shows a stale count" sets visual; "a quantum of work" sets scientific),
  and a prompt in a category phrased without a listed word is missed. The directive text
  tells the model to ignore one that does not apply.
- **Known reader misfires and misses.** Found while choosing the boundary, left as they
  are: "add comments to this function so I can understand it later" and "explain why the
  loop restarts from the beginning when the file is empty" set the reader category, and
  so does a small request such as "write docs for the new endpoint" when it is long
  enough to pass the 40-character minimum. Missed: "I want to learn this from scratch",
  a README or cheat sheet, and any request for a course or guide phrased without a
  producing verb before the noun.
- **Pasted text that is not fenced sets categories.** Claude Code expands pasted text
  into the prompt; only fenced blocks and `<pasted_content>` blocks are removed before
  matching. A pasted log that mentions "render" or "latency" counts as the user's
  words.
- **Once per session is once, including across compactions.** The record of what was
  sent lives in the scratchpad and outlasts a compaction, but the directive itself was in
  the conversation and survives only as far as the compaction summary keeps it. It is not
  sent again, so a category that comes back after a compaction, or late in a long session,
  gets no reminder. This is left as it is: repeating directives is the interruption
  pattern the hooks are meant to avoid.
- **Prompts that are not typed** (a `/loop` iteration, a message from another session)
  are matched like typed ones, except the two harness markers listed above.
- **It delivers an instruction; it does not check one.** Nothing verifies that the
  model measured, rendered, read the reference, or wrote `plan.md`. The grounding kits
  leave record files when they are used, but nothing checks that they were. The claim gate's
  speed check and `plan-reconciliation` check two of these afterwards, partly.

## Status

- The tests feed recorded-shape payloads to the script. **The hook has not run in a
  live Claude Code session.**
- **There is no measurement of whether the directives change outcomes.** The plan is
  to run the same tasks with and without it, including tasks from the three categories
  the Fable 5.2 card names; until then this is a hypothesis that costs little.
- Its firing rate on real prompts is unmeasured.

## Measuring it on your own work

The hook takes part in the trial described in [`hook-trial/`](../hook-trial/). With a trial
file enabled (`<project>/.claude/hook-trial.json` or `~/.claude/hook-trial.json`), it stays
silent in a random half of sessions, chosen from the session id, together with the other
three hooks of the trial; `hook-trial/compare_arms.py` compares the two halves afterwards. In
the off arm it exits before reading its rules and writes no state file. Without a trial file,
or with one it cannot read, it behaves as described above.

## Install

1. Copy `task_grounding.py` and `categories.json` into the same directory in the
   project, for example `.claude/hooks/`.
2. Register it as a `UserPromptSubmit` hook in `.claude/settings.json`, alongside any
   existing UserPromptSubmit hooks:

   ```json
   {
     "hooks": {
       "UserPromptSubmit": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/task_grounding.py\""
             }
           ]
         }
       ]
     }
   }
   ```

3. For the scientific directive to name the checker, copy
   `reference-store/check_reference.py` beside `task_grounding.py`. Without it the
   directive points only at `docs/reference/INDEX.md`.
4. For the performance and scientific directives to name the grounding kits, copy
   `grounding-kits/` (or only the kits you want) beside `task_grounding.py`, so that
   for example `.claude/hooks/grounding-kits/performance/measure.py` exists. Without
   them the two directives are the plain ones.
5. Claude Code watches settings files and normally applies hook edits to the running session without a restart; if `/hooks` does not list it, restart the session. In an interactive session, hooks do not run until the workspace trust dialog has been accepted.

## Test

```bash
python3 test_task_grounding.py
```

Standalone, no pytest. 91 cases: one prompt per category, a plain coding prompt, a short
prompt, harness-tagged input, a slash command, category words only inside pasted code, the
once-per-session rule within and across categories, two categories in one prompt, the
session-id fallback, fail-open on malformed input and on an unreadable state file, a
corrupt state file treated as empty, ten ordinary coding prompts that must stay silent, eight
prompts that the narrowed patterns must still match, seven prompts about setting up and
running a benchmark suite that must not set performance and four about timing code with a
benchmark that must, a prompt starting with an absolute path, the checker path as found
from where the hook is installed, the performance and scientific directives naming their
grounding kit in the repository layout and in an installed copy and falling back to the
plain directive word for word when the kit is absent or incomplete, eleven reader prompts that must set the reader category,
the reader directive's three steps, and sixteen ordinary coding prompts about docs,
reports, guides and errors that must not set it.
`TASK_GROUNDING=/path/to/other/task_grounding.py python3 test_task_grounding.py` runs the
same cases against another copy of the hook.

`python3 test_hook_trial.py` tests the trial switch: silence in the off arm with no state
file written, the session-id vectors shared with the other hooks, every fail-safe case, where
the trial file is looked for, and `HOOK_TRIAL_IGNORE`. With a trial file enabled in your home
directory, run `test_task_grounding.py` with `HOOK_TRIAL_IGNORE=1`, since its cases use your
real home directory.
