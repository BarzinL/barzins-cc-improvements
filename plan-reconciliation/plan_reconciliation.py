#!/usr/bin/env python3
"""Claude Code Stop hook: a final report must account for every open plan item.

When the session has a plan checklist and the turn is ending on a report (not on a
question to the user), every item not marked done must be mentioned in the final
message. Items that are not mentioned are listed once, with a request to report each
as done, deferred with a reason, or dropped with a reason. The hook does not judge
whether dropping an item was right; it only makes the drop visible.

Where the plan lives: `<scratchpad_dir>/plan.md`, a Markdown checklist. The Stop
payload carries `scratchpad_dir`, the agent is told the same path in its system
prompt, and the path contains the session id, so the file belongs to one session.
On Opus 5.5 the harness's own task tools are off by default and never appear in the
transcript; README.md has the evidence.

Checklist format, one item per line:

    - [ ] B3: write the plan hook        open
    - [x] B2: revise the claim gate      done (x or X)

Any other mark inside the brackets counts as open. Text before a first colon that is
one short token ("B3") is the item's key; mentioning the key counts as mentioning
the item. Otherwise most of the item's significant words must appear.

Advisory, loop-safe (`stop_hook_active`), silent when it passes, fails open on any
error. An optional trial file can switch it off in a random half of sessions, so its
effect can be measured (`trial_arm`; hook-trial/ in the repository). Python standard
library only. Install: see README.md.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PLAN_FILENAME = "plan.md"
MAX_LISTED = 15

_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\[(?P<mark>[^\]]?)\]\s+(?P<text>\S.*?)\s*$")
_KEY = re.compile(r"^(?P<key>[A-Za-z0-9][\w.\-]{0,11}):\s+(?P<rest>.+)$")
_WORD = re.compile(r"[a-z0-9][a-z0-9_\-]*")

_STOPWORDS = frozenset(
    "the and for with from into onto that this those these then than them they their "
    "there here what when where which while who whom whose why how all any each every "
    "some such not but are was were been being have has had having can could should "
    "would will shall may might must its it's our ours your yours his her him she you "
    "one two via per also just only very more most less least out off over under about "
    "above below after before again once both other own same too step item task todo "
    "make sure use using".split()
)

# Words that say the turn is reporting work as finished. Used only when the turn made
# no tool calls, so a purely conversational reply does not trigger a plan check.
_COMPLETION = re.compile(
    r"\b(done|complete[ds]?|completed|finished|implemented|fixed|all set|shipped|"
    r"wrapped up|in place|ready|summary|that's everything|nothing (?:left|remaining))\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- transcript --
def _load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def _is_real_user_turn(e: dict) -> bool:
    """A prompt from the user, not a tool result or an injected meta message.

    Tool results arrive as type "user" events whose content is tool_result blocks.
    Meta messages (isMeta) are inserted by the harness, including mid-turn, so they
    do not start a turn either.
    """
    if e.get("type") != "user" or e.get("isMeta"):
        return False
    msg = e.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in content)
    return False


def _turn_events(events: list[dict]) -> list[dict]:
    start = 0
    for i, e in enumerate(events):
        if _is_real_user_turn(e):
            start = i
    return events[start:]


def _blocks(e: dict) -> list:
    msg = e.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def _turn_has_tool_calls(turn: list[dict]) -> bool:
    for e in turn:
        if e.get("type") == "assistant":
            for b in _blocks(e):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    return True
    return False


def _final_text_from_transcript(turn: list[dict]) -> str:
    """Assistant text after the last tool call of the turn."""
    parts: list[str] = []
    for e in turn:
        if e.get("type") != "assistant":
            continue
        for b in _blocks(e):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                parts = []
            elif b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
    return "\n".join(parts)


# ---------------------------------------------------------------------- plan --
def parse_plan(text: str) -> list[tuple[bool, str]]:
    """Return (is_done, item_text) for each checklist line."""
    items: list[tuple[bool, str]] = []
    for line in text.splitlines():
        m = _ITEM.match(line)
        if m:
            items.append((m.group("mark") in ("x", "X"), m.group("text")))
    return items


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if len(w) >= 3 and w not in _STOPWORDS}


def is_mentioned(item: str, message: str) -> bool:
    rest = item
    m = _KEY.match(item)
    if m and not m.group("key").isdigit():
        key = re.escape(m.group("key"))
        if re.search(rf"(?<![\w.\-]){key}(?![\w\-])", message, re.IGNORECASE):
            return True
        rest = m.group("rest")
    wanted = _words(rest)
    if not wanted:
        return item.strip().lower() in message.lower()
    have = _words(message)
    need = min(4, math.ceil(2 * len(wanted) / 3))
    return len(wanted & have) >= need


def ends_with_question(message: str) -> bool:
    lines = [ln.strip() for ln in message.strip().splitlines() if ln.strip()]
    if not lines:
        return False
    return lines[-1].rstrip("*_`\"')]} \t").endswith("?")


# ---------------------------------------------------------------------- main --
def evaluate(payload: dict) -> str | None:
    """Return the reason text if the hook should fire, else None."""
    if payload.get("stop_hook_active"):
        return None
    scratch = payload.get("scratchpad_dir")
    if not isinstance(scratch, str) or not scratch:
        return None
    plan_path = Path(scratch) / PLAN_FILENAME
    if not plan_path.is_file():
        return None
    items = parse_plan(plan_path.read_text(encoding="utf-8", errors="replace"))
    open_items = [text for done, text in items if not done]
    if not open_items:
        return None

    turn: list[dict] = []
    tp = payload.get("transcript_path")
    if isinstance(tp, str) and tp and Path(tp).is_file():
        turn = _turn_events(_load_events(Path(tp)))

    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        message = _final_text_from_transcript(turn)
    if not message.strip():
        return None
    if ends_with_question(message):
        return None  # handing back to the user, not reporting the work as finished
    if not _turn_has_tool_calls(turn) and not _COMPLETION.search(message):
        return None  # a conversational reply, not a report on the plan

    missing = [it for it in open_items if not is_mentioned(it, message)]
    if not missing:
        return None
    listed = "\n".join(f"- {it}" for it in missing[:MAX_LISTED])
    more = len(missing) - MAX_LISTED
    if more > 0:
        listed += f"\n- ... and {more} more"
    return (
        f"Plan check: the session plan ({plan_path}) has open items that your final "
        f"message does not mention:\n{listed}\n\n"
        "For each one, say in your reply whether it is done, deferred (and why), or "
        "dropped (and why), then end the turn. Mark finished items [x] in the plan "
        "file. This check does not judge whether deferring or dropping is right; it "
        "asks only that the user can see it."
    )


# --------------------------------------------------------------------- trial --
# The same function, word for word, is in each hook that takes part.
TRIAL_FILE = os.path.join(".claude", "hook-trial.json")


def trial_arm(payload: dict) -> str:
    """"off" when a hook trial is enabled and this session is in its off arm, else "on".

    The trial file is <project>/.claude/hook-trial.json, where <project> is
    $CLAUDE_PROJECT_DIR, or the payload's cwd when that variable is unset; if that file
    does not exist, ~/.claude/hook-trial.json. The first file that exists decides. It
    holds {"enabled": true, "salt": "...", "start": "YYYY-MM-DD"} (start optional; before
    that UTC date the trial is not running). The arm is the lowest bit of
    sha256(salt + ":" + session_id): 0 is on, 1 is off. Anything unexpected (no session
    id, an unreadable or malformed file, HOOK_TRIAL_IGNORE set) gives "on", so the trial
    never silences a hook by accident. See hook-trial/README.md in the repository.
    """
    try:
        if os.environ.get("HOOK_TRIAL_IGNORE"):
            return "on"
        sid = payload.get("session_id")
        if not isinstance(sid, str) or not sid:
            return "on"
        root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
        paths = [os.path.join(root, TRIAL_FILE)] if isinstance(root, str) and root else []
        paths.append(os.path.join(os.path.expanduser("~"), TRIAL_FILE))
        path = next((p for p in paths if os.path.lexists(p)), None)
        if path is None:
            return "on"
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict) or cfg.get("enabled") is not True:
            return "on"
        salt = cfg.get("salt")
        if not isinstance(salt, str) or not salt:
            return "on"
        start = cfg.get("start")
        if start is not None:
            if not isinstance(start, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
                return "on"
            if datetime.now(timezone.utc).date() < date.fromisoformat(start):
                return "on"
        digest = hashlib.sha256(f"{salt}:{sid}".encode("utf-8")).digest()
        return "off" if digest[-1] & 1 else "on"
    except Exception:
        return "on"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict) or trial_arm(payload) == "off":
            return 0
        reason = evaluate(payload)
    except Exception:  # fail open on anything unexpected
        return 0
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
