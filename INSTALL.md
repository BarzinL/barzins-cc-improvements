# Install

Written to be executed by an agent. Point your Claude Code at this file and it has
everything it needs:

```
Read https://raw.githubusercontent.com/BarzinL/barzins-cc-improvements/main/INSTALL.md
and install the parts that fit this project.
```

Or clone first and say `read INSTALL.md and install the parts that fit this project`.
Cloning is only required for `per-model-discipline`, which ships a script; everything
else is text an agent can fetch and write.

Nothing here needs a package manager, a build step, or any dependency beyond Python 3
from the standard library.

---

## Scope: pick one before copying anything

| Destination | Applies to | Use for |
|---|---|---|
| `~/.claude/` | every project on this machine | how you want the agent to talk and behave |
| `<project>/.claude/` | one repository, shared via git | rules about this codebase, checked in |

A hook command in **global** settings needs an **absolute path**.
`$CLAUDE_PROJECT_DIR` resolves only for project-scoped settings; used globally it stays a
literal and the command exits 2 with `can't open file`. That failure is easy to miss, so
run the acceptance check below after installing anything mechanical.

---

## 1. The prose pieces - copy into `CLAUDE.md`

Paste the quoted rule blocks from each of these into your `CLAUDE.md` (global at
`~/.claude/CLAUDE.md`, or project-level). Nothing else to do.

- [`stopping-rules/`](stopping-rules/) - four rules for the moments the model stops too
  early: stale world facts, patching without a diagnosis, shallow answers, made-up
  estimates.
- [`response-length-calibration/`](response-length-calibration/) - the moment it stops too
  late: correct answers wrapped in unreadable document prose.
- [`theory-formation-discipline/theory-formation-method.md`](theory-formation-discipline/theory-formation-method.md)
  - nine moves for reasoning like a researcher without fooling yourself.

Trim to taste. These are ambient cost on every request, so a rule you do not need is not
free.

## 2. The skills - copy a directory

Each goes in `.claude/skills/<name>/SKILL.md`, project-local or global. Agent definitions
(where an entry has one) go in `.claude/agents/`.

- [`ground-skill-verifier/`](ground-skill-verifier/) - `/ground`, plus the cold verifier
  subagent it spawns. Start here if you only want one thing.
- [`seam-proof-build/`](seam-proof-build/) - keeps that discipline running during the build.
- [`experiment-freeze-gate/`](experiment-freeze-gate/) - eight checks before spending
  compute on an experiment design.
- [`delegated-build-stint/`](delegated-build-stint/) - contract for handing build work to a
  subagent.

Skills are discovered from the filesystem, so a new session picks them up with no
registration step. Confirm with `/help` or by invoking one.

## 3. The mechanical pieces - these edit `settings.json`

Two hooks and a script. **Hooks bind at session start**, so anything installed here
activates in the *next* session, not the current one. Confirm with `/hooks`.

### per-model-discipline (has an installer)

```bash
python3 per-model-discipline/install.py --scope global            # dry run: diff, writes nothing
python3 per-model-discipline/install.py --scope global --apply    # install, then self-check
```

The installer backs up `settings.json`, appends to the existing `UserPromptSubmit` array
rather than rewriting it, refuses a `settings.json` that is not valid JSON, and is
idempotent. Then it proves the registered command actually fires. Re-run the check any
time:

```bash
python3 per-model-discipline/install.py --scope global --verify-only
```

### verification-claim-gate (register by hand)

Copy `theory-formation-discipline/verification-claim-gate/verification_claim_gate.py` into
your hooks directory and add it under `Stop`; the JSON block is in
[that directory's README](theory-formation-discipline/verification-claim-gate/README.md).
Tune `_ACTION_HINT` to name your project's test and build commands, or it will
false-positive on real verifications it does not recognize.

### discipline-compliance-scanner (nothing to install)

```bash
python3 discipline-compliance-scanner/scan.py --all
```

Reads your own session transcripts and reports where standing rules were actually broken,
with citations. Run it after a week of use; the results are the argument for which of the
above you actually need.

---

## If you are the agent doing this

Do not hand-edit `settings.json` when an installer exists for that entry - the installer
handles the backup, the append-not-rewrite merge, and the post-install check. Where you do
edit it by hand:

1. Read the current file first. Never write a `hooks` block over one that already has
   entries; other hooks in the same array are somebody's working setup.
2. Copy it to `settings.json.bak-<date>` before writing.
3. Show the diff and get a yes before applying, unless you were told to proceed.
4. Afterwards, run the hook command exactly as you wrote it into settings, with a
   synthetic stdin payload, and confirm it exits 0. A hook that is registered but
   unrunnable looks identical to one that works until the day you need it.

Step 4 is the point of the whole repository. Do not skip it and report the install as
verified.
