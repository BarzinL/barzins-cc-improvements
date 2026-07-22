# discipline-compliance-scanner

Every other tool in this repo is a discipline the agent runs *before* it speaks or acts.
None of them checks whether the discipline was actually followed. This one does: it mines
the agent's own session transcripts and reports where standing bright-line rules were
broken, with clickable citations. It is the retrospective auditor - the piece that closes
the loop by *measuring* compliance instead of asserting it.

The rules it enforces are written down (a `CLAUDE.md` "never do" list, the `feedback_*`
rules in project memory). Writing a rule does nothing to guarantee it was obeyed. Run this
against a few hundred transcripts of real work and the gap is stark: in the session set it
was built on it found the agent had written the forbidden em-dash into files hundreds of
times and run `sqlite3` on session DBs without the mandatory `-readonly` flag dozens of
times - both rules it had "known" the whole time.

## The finding that shaped it: two classes of rule

A throwaway probe (kept in the commit history) tested whether a violation can be detected
mechanically. It split the rules cleanly, and the split is the architecture:

- **Bright-line rules** - a specific token or tool is forbidden (em-dash, `sqlite3`
  without `-readonly`, `AskUserQuestion`, `git push`, `sudo`, `shell=True`). Deterministic
  scan, near-zero false positives. **This tool covers these.**
- **Judgment rules** - the violation is defined by content and reasoning, not any token
  (reactive-patching, skipped grounding, false-scoping). The probe tried to detect
  reactive-patching structurally and *failed*: the signal lives in the edit contents and
  the reasoning text, not in tool names. These need an LLM-judge over transcript spans, and
  are deliberately out of scope here (see `SPEC.md`, Increment 2).

Building this as one "grep the transcripts" tool would have silently failed on exactly the
judgment rules that matter most. Knowing that up front is the whole point of proving the
keystone before formalizing (`seam-proof-build`, move 1).

## Usage

```bash
python3 scan.py                      # default project's transcripts
python3 scan.py --all                # every project under ~/.claude/projects
python3 scan.py --project <dirname>  # one project
python3 scan.py --samples 5          # up to N sample citations per rule
python3 scan.py --max-mb 5           # skip giant transcripts
python3 scan.py --strict             # exit 1 if any rule fires (hook wrapper)
```

Output is a ranked table of raw hit counts plus sample citations for eyeballing. Counts
are labelled **raw** on purpose: a small, documented false-positive residue survives (a
`.py` file that contains a forbidden token as *data* - this scanner's own rule table is
one; an em-dash inside content the agent pasted rather than authored). The samples exist so
those are discountable by hand, not hidden.

## Adding a rule

A rule is data, not code. Append to `RULES` in `scan.py`:

- `bash_regex` - Bash command matches `pattern`, optionally not `exclude`.
- `tool_name` - any use of a named tool.
- `write_regex` - authored content (`Edit.new_string` / `Write.content`) matches
  `pattern`; optional `path_suffix` restricts it to real code files so prose *discussing*
  a token does not trip it.

## What it is not

It never edits a discipline artifact and never runs unattended. It reports; the operator
decides what to fix. Making it an autonomous grader the agent optimizes against would
invite the exact reward-hacking these tools exist to prevent.

## Next

`SPEC.md` carries the full two-increment plan. Increment 2 (the LLM-judge for judgment
rules) is not built. A natural near-term step is wrapping `--strict` as a pre-write hook so
a bright-line violation is caught *before* it lands, not counted hundreds of times after.
