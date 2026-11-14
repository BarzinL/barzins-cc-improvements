# Placeholder disclosure (Claude Code Stop hook)

A Stop hook that pauses the turn once when the turn wrote placeholder code into a code
file and the final message does not say so. It lists each placeholder by file and line.

Targeted at: Opus 5.5

## The failure it targets

The Opus 5.5 system card, section 6.2.2 ("Impossible tasks"), on training environments
where a file needed for the task was missing:

> For all models, rates of attempted reward hacking were
> drastically higher when faced with an impossible task compared to a possible one, by a
> factor of about three to six. Note that the classifier counts knowingly incomplete work as
> an attempted reward hack regardless of whether the model discloses it; this alone accounts
> for about 80% of the reward-hacking attempts on these tasks in each of the three models.

The card also says the model "was also explicitly instructed not to ask for
clarification" in those environments. Its 80% figure includes incomplete work that
was disclosed; the card does not say how much was not. This hook is aimed at the
undisclosed part: a stub left in place in a turn reported as complete.

## What it does

When a turn ends, the hook:

1. reads the transcript from the last user prompt on (tool results and harness meta
   messages do not start a new turn) and collects the `Write`, `Edit` and `MultiEdit`
   calls that did not return an error;
2. skips non-code files (by extension) and test files (`tests/`, `test/`, `spec/`,
   `__tests__/`, `fixtures/` and similar directories; `test_*.py`, `*_test.go`,
   `*.test.ts`, `*.spec.js`, `conftest.py` and similar names; in Rust, everything after
   `#[cfg(test)]`);
3. finds placeholders in the current file on disk:
   - Rust `todo!()` and `unimplemented!()`; Kotlin `TODO()`;
   - Python `raise NotImplementedError`, and a function whose body (after an optional
     docstring) is only `pass` or `...`, found with `ast`. Methods under
     `@abstractmethod` or `@overload` and methods of a `Protocol` class are exempt;
   - a throw, raise or panic whose message says "not implemented";
   - a `TODO` or `FIXME` in a comment. In Python, comments come from `tokenize`; in
     other languages the word must follow a comment marker on the same line. `TODO` in a
     string is not counted;
4. keeps only placeholders on lines this turn added. The content before the turn comes
   from the first write's tool result (`originalFile`, or `type: "create"` for a new
   file), and is compared to the current file with `difflib`. When the result is not
   recorded, it falls back to counting placeholder lines in the turn's new text minus
   its replaced text;
5. treats a placeholder as disclosed when the final message (`last_assistant_message`,
   or the transcript if that is missing) contains a disclosure word (stub, placeholder,
   TODO, FIXME, unimplemented, not implemented, unfinished, incomplete, blocked, and a
   few phrases) **and** names the enclosing function or the file;
6. if any placeholder is not disclosed, pauses the turn once, listing `file:line`, the
   kind of placeholder and its function, and asks for each to be named with what it
   still needs, or for the task to be reported as blocked with the reason.

The pause is returned as `hookSpecificOutput.additionalContext` (non-error feedback that
continues the conversation, under the same loop protections as `decision: "block"`). It
is advisory, fires at most once per stop cycle (`stop_hook_active`), is silent when it
passes, and fails open: malformed input or any unexpected error ends in exit 0 with no
output.

The plan asked for this check to share code with `discipline-compliance-scanner`'s
`write_regex` rules. Each directory in this repository is self-contained, so the
transcript walk and the pattern-table idea are copied rather than imported.

## What it cannot catch

- **Writes made outside `Write` and `Edit`.** A file written by `sed`, a heredoc in
  Bash, a code generator or a subagent is not seen.
- **Placeholders that do not look like one.** A function that returns a hard-coded
  value, an empty list or `0`, or that silently skips the hard case, has no marker to
  find. This is likely the larger share of incomplete work, and the hook does not touch
  it.
- **Vague disclosure that happens to match.** "parse_header is not done yet" passes,
  and so does a message that uses a disclosure word about something else while naming
  the same file.
- **Precise disclosure in other words.** "parse_header returns an error for now"
  without any disclosure word is not recognised, and the placeholder is listed.
- **Test-path guesses.** A code file in a directory named `fixtures` or `spec` is
  treated as a test and skipped; a test file with an unusual name is checked.
- **Comment detection outside Python** is per line: a `TODO` after a `#` or `//` inside
  a string literal is counted, and block comments spanning lines are only caught on
  lines that start with `*` or contain the marker.
- **Files changed after the write.** Line numbers come from the file on disk at stop
  time; if a later Bash command rewrote the file, lines may be off.
- **Subagents.** A Stop hook runs for the main agent only.

## Install

1. Copy `placeholder_disclosure.py` into the project, for example
   `.claude/hooks/placeholder_disclosure.py`.
2. Register it as a `Stop` hook in `.claude/settings.json`, alongside any existing Stop
   hooks:

   ```json
   {
     "hooks": {
       "Stop": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/placeholder_disclosure.py\""
             }
           ]
         }
       ]
     }
   }
   ```

3. Hooks bind at session start, so it is active from the next session. Confirm with
   `/hooks`.

Python standard library only.

## Test

```bash
python3 test_placeholder_disclosure.py
```

Standalone, no pytest. The five acceptance cases from the plan are marked `[plan]`
(the "already in the file" case runs twice, with and without a recorded tool result);
the rest cover Python stubs and their exemptions, comments versus string data, non-code
files, failed writes, earlier turns, multiple edits to one file, Rust inline tests, the
transcript fallback, and fail-open on bad input.

## Status

The tests feed recorded-shape payloads to the script. The hook has not been run in a
live Claude Code session. Its firing rate on real work is unmeasured.

## The "blocked" rule

[`blocked-rule-DRAFT.md`](blocked-rule-DRAFT.md) is a two-line `CLAUDE.md` rule that
makes "blocked" an accepted result. It is a draft and is not
installed anywhere.
