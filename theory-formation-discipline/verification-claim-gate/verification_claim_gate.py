#!/usr/bin/env python3
"""Claude Code Stop hook: don't let a turn end on an UNSUBSTANTIATED verification claim.

Targets the single highest-frequency documented failure mode of current frontier
models: stating an unverified guess as fact - "verified end-to-end", "all tests
pass", "no errors", "healthy" - when no verification actually ran. Published system
cards document this as a top failure surface, and note that the model self-corrects
flawlessly, but only AFTER a human pushes back. This hook moves the push-back to
send-time: if the final assistant turn makes a verification claim and the exchange
shows no verification ACTION to back it, the turn is paused once with a reminder to
substantiate the claim or soften it to what was actually done.

It is deliberately ADVISORY, not authoritative. A regex can't police truth. It
injects one reminder (loop-safe via `stop_hook_active`), then lets the turn end. A
false positive costs one extra self-check pass, never a wedged turn. It fails OPEN
on any surprise - a wrong assumption about the hook contract or the transcript shape
degrades to a no-op.

Install: see README.md in this directory. Pure stdlib, no dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Verification CLAIMS - assertions that work was checked / is healthy. Word-boundary,
# case-insensitive. Deliberately narrow: these are the specific phrasings that make
# up the documented failure surface, not every use of the word "check".
_CLAIM = re.compile(
    r"\b("
    r"verified end-to-end|verified end to end|"
    r"tested end-to-end|tested end to end|"
    r"verified (?:that |it |this )?works?|"
    r"confirmed (?:it |that |this )?works?|"
    r"no error(?:s| signal| movement)?(?: at all)?|"
    r"all (?:tests? )?pass(?:ed|ing)?|"
    r"healthy|"
    r"i(?:'ve| have) (?:verified|tested|confirmed)|"
    r"verified (?:live|in prod|in production)"
    r")\b",
    re.IGNORECASE,
)

# Evidence that a verification ACTION actually ran this turn: a tool_use whose input
# invoked a command / test runner / build / HTTP check. Extend this list to match the
# tools your project actually uses to verify things.
_ACTION_HINT = re.compile(
    r"\b(pytest|unittest|jest|vitest|mocha|go test|cargo test|"
    r"npm test|npm run|yarn|pnpm|make|"
    r"python -m|node |uv run|poetry run|"
    r"curl|http|wget|playwright|puppeteer|selenium|"
    r"docker|kubectl|systemctl|journalctl|"
    r"\./|bash |sh )\b",
    re.IGNORECASE,
)

# Phrasings that make a claim SAFE even without a fresh action: the model is already
# hedging or explicitly flagging the gap - which is exactly the wanted behaviour.
# Don't nag an honest hedge.
_ALREADY_HEDGED = re.compile(
    r"\b(not (?:independently )?(?:sure|verified|tested)|"
    r"unverified|haven't (?:verified|tested|run|checked)|"
    r"have not (?:verified|tested|run)|"
    r"i did not (?:verify|test|run)|"
    r"can't confirm|cannot confirm|"
    r"should (?:verify|test|check)|"
    r"needs? (?:verification|testing)|"
    r"without (?:running|checking|verifying))\b",
    re.IGNORECASE,
)


def _resolve_transcript(payload: dict) -> Path | None:
    """The Stop hook payload carries transcript_path; reconstruct it if absent."""
    tp = payload.get("transcript_path")
    if tp and Path(tp).exists():
        return Path(tp)
    sid = payload.get("session_id") or payload.get("sessionId")
    cwd = payload.get("cwd") or os.getcwd()
    if sid:
        sanitized = str(Path(cwd).resolve()).replace("/", "-")
        cand = Path.home() / ".claude" / "projects" / sanitized / f"{sid}.jsonl"
        if cand.exists():
            return cand
    return None


def _is_real_user_turn(e: dict) -> bool:
    """A user PROMPT, not a tool-result plumbing event.

    In Claude Code transcripts, tool results come back as type:"user" events whose
    content is a list of tool_result blocks. Those must NOT reset the exchange window,
    or every assistant summary emitted after the last tool call looks action-less.
    A real prompt is a bare string, or a content list containing a text block.
    """
    if e.get("type") != "user":
        return False
    content = e.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in content)
    return False


def _tail_events(transcript: Path) -> list[dict]:
    """Events since (and including) the last real user prompt - the final exchange.

    Tool-result events (type:"user" with only tool_result blocks) do NOT reset the
    window; otherwise a claim made in a summary after the last tool call would look
    unbacked even though the verifying action ran earlier in the same turn.
    """
    events: list[dict] = []
    for line in transcript.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    last_user = 0
    for i, e in enumerate(events):
        if _is_real_user_turn(e):
            last_user = i
    return events[last_user:]


def _final_assistant_text(events: list[dict]) -> str:
    parts: list[str] = []
    for e in events:
        if e.get("type") != "assistant":
            continue
        content = e.get("message", {}).get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(
                c.get("text", "")
                for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
    return "\n".join(parts)


def _ran_verification_action(events: list[dict]) -> bool:
    for e in events:
        if e.get("type") != "assistant":
            continue
        content = e.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                blob = json.dumps(c.get("input", {}))
                if _ACTION_HINT.search(blob):
                    return True
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if data.get("stop_hook_active"):
        return 0  # already paused once this cycle - never loop

    transcript = _resolve_transcript(data)
    if transcript is None:
        return 0  # can't see the turn -> fail open

    try:
        tail = _tail_events(transcript)
        text = _final_assistant_text(tail)
    except OSError:
        return 0

    if not text.strip():
        return 0
    claim = _CLAIM.search(text)
    if not claim:
        return 0  # no verification language -> nothing to gate
    if _ALREADY_HEDGED.search(text):
        return 0  # already flagging the gap -> that's the good behaviour
    if _ran_verification_action(tail):
        return 0  # claim is backed by an action this turn

    print(
        json.dumps(
            {
                "decision": "block",
                "reason": (
                    "Send-time verification check: your turn asserts "
                    f"\"{claim.group(0)}\" but this exchange shows no verification "
                    "action (no test / command / build / HTTP check since the last "
                    "user message).\n\n"
                    "Before ending: either (a) run the check that substantiates the "
                    "claim, or (b) soften it to what you actually did (e.g. 'static "
                    "checks pass, haven't run it end-to-end'). Do not report work as "
                    "verified on the strength of reasoning alone - that is the exact "
                    "pre-pushback failure this gate exists to catch. If the claim IS "
                    "already backed by earlier work in this session, say so explicitly "
                    "and end the turn."
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
