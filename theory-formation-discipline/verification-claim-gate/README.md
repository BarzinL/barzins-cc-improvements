# Verification-claim gate (Claude Code Stop hook)

A Claude Code **Stop hook** that pauses a turn once when the agent says it *verified*
something it didn't actually run.

It catches the single most frequent, most detectable slice of the honesty failure that
published frontier-model system cards document as a top failure surface: **stating an
unverified guess as fact** - "verified end-to-end", "all tests pass", "no errors",
"healthy" - when no test, command, or check was actually executed. The cards note the
model self-corrects flawlessly, but only *after* a human pushes back. This hook moves
the push-back to send-time.

## What it does

When a turn is about to end, the hook:

1. reads the final assistant message plus the tool calls made since the last user message;
2. checks whether the message makes a **verification claim** (a narrow, specific set of
   phrasings - not every use of the word "check");
3. checks whether a **verification action** actually ran this exchange (a test runner,
   a command, a build, an HTTP check);
4. if there's a claim, no action, and no hedge - it **pauses the turn once** with a
   reminder to either run the check or soften the claim to what was actually done.

It is **advisory, not authoritative.** A regex can't police truth. Key safety properties:

- **Loop-safe** - it pauses at most once per stop cycle (via `stop_hook_active`), then
  lets the turn end no matter what.
- **Fails open** - any surprise (bad payload, unreadable transcript) degrades to a no-op.
  It will never wedge a turn.
- **Respects honest hedges** - a claim that's already flagged ("haven't run it
  end-to-end", "unverified") passes untouched. That's the behaviour you *want*; don't
  nag it.
- **Cost of a false positive** is one extra self-check pass, not a blocked turn.

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

3. **Hooks bind at session start**, so it activates in your *next* session, not the one
   where you added it. Confirm with `/hooks` (it should appear under `Stop`).

Pure Python stdlib - no dependencies.

## Tune it to your stack

Two regexes are meant to be edited for your project:

- **`_ACTION_HINT`** - what counts as "a verification actually ran". Add the test
  runners, build commands, and check tools your project uses (`cargo test`, `go test`,
  `make check`, your own CLI, etc.). If this list is too narrow, the hook will
  false-positive on real verifications it didn't recognize.
- **`_CLAIM`** - the phrasings that count as a verification claim. Add ones specific to
  your domain if you find the agent using them ("deploy is green", "smoke test clean").

## Test

```bash
python3 test_verification_claim_gate.py
```

Standalone (no pytest). Covers: claim+no-action (blocks), claim+action (passes),
claim+hedge (passes), no-claim (passes), loop-safety, a `healthy` monitoring claim, an
`npm test`-backed claim, and fail-open on a bad transcript path.

## Why a hook and not a memory instruction

Because system cards document a "correction fails" category: the corrective instruction
was present in a memory file, and the behavior recurred anyway. A memory note is
*recalled context* the model can drift from. A Stop hook is executed by the harness - it
fires whether or not the model remembered to care. That's the difference between a poster
on the wall and a wall.

The tradeoff: a hook can only enforce what's mechanically detectable. This one covers the
*frequent, detectable* slice. The rest of the discipline (see the parent directory) stays
self-enforced.
