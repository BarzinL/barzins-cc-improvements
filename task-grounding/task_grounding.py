#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: add one short directive when a prompt falls
into a category of work where the Fable 5.2 system card reports Opus 5.5 furthest
behind (performance, visual, scientific), where a plan file is needed, or where a
large piece of work for a reader should be checked with the user one piece first.

The category is decided by pattern match on the prompt, not by the model judging
its own familiarity. Each category's directive is added at most once per session.
The hook only adds context. It never blocks or changes a prompt, and on any error
or unexpected input it exits 0 with no output.

Rules are data: categories.json beside this file. In a directive, {reference} is
replaced by how to search the project reference, naming the check_reference.py the
hook finds from its own location.

An optional trial file can switch it off in a random half of sessions, so its effect
can be measured (`trial_arm`; hook-trial/ in the repository).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

RULES = Path(__file__).with_name("categories.json")
STATE_NAME = "task-grounding-seen.json"
_SLASH_COMMAND = re.compile(r"/[A-Za-z][\w:.-]*(?:\s|$)")


def checker_path(here: Path = Path(__file__).resolve().parent) -> Path | None:
    """The reference checker, found from this hook's own location: beside it, or in a
    reference-store/ directory beside it or one level up (the repository layout)."""
    for p in (here / "check_reference.py", here / "reference-store" / "check_reference.py",
              here.parent / "reference-store" / "check_reference.py"):
        if p.is_file():
            return p
    return None


def reference_hint() -> str:
    p = checker_path()
    index = "read docs/reference/INDEX.md"
    return f'run python3 "{p}" --find <term>, or {index}' if p else index


def load_rules(path: Path = RULES) -> tuple[int, list[tuple[str, re.Pattern, str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cats = [(c["id"], re.compile(c["pattern"], re.IGNORECASE), c["directive"]) for c in data["categories"]]
    return int(data.get("min_prompt_chars", 40)), cats


def is_typed_prompt(prompt: str, min_chars: int) -> bool:
    """Skip harness traffic (it arrives wrapped in tags), slash and shell
    commands, and prompts too short to be a task."""
    p = prompt.strip()
    if len(p) < min_chars or p[0] in "<!" or _SLASH_COMMAND.match(p):
        return False  # an absolute path ("/home/...") is not a slash command
    return "<task-notification" not in p and "[Subagent hand-back]" not in p


def strip_quoted(prompt: str) -> str:
    """Drop fenced code and pasted blocks so pasted logs do not set the category."""
    p = re.sub(r"```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)", " ", prompt, flags=re.DOTALL)
    return re.sub(r"<pasted_content\b.*?(?:</pasted_content\b[^>]*>|\Z)", " ", p, flags=re.DOTALL)


def matches(prompt: str, cats) -> list[tuple[str, str]]:
    text = strip_quoted(prompt)
    return [(cid, directive) for cid, pat, directive in cats if pat.search(text)]


def state_path(payload: dict) -> Path | None:
    d = payload.get("scratchpad_dir")
    if isinstance(d, str) and d and os.path.isdir(d):
        return Path(d) / STATE_NAME
    sid = payload.get("session_id")
    if isinstance(sid, str) and re.fullmatch(r"[\w-]{6,80}", sid):
        return Path(tempfile.gettempdir()) / f"task-grounding-{sid}.json"
    return None


# The same function, word for word, is in each hook that takes part in a trial.
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
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or trial_arm(payload) == "off":
            return 0
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return 0
        min_chars, cats = load_rules()
        if not is_typed_prompt(prompt, min_chars):
            return 0
        found = matches(prompt, cats)
        if not found:
            return 0
        sp = state_path(payload)
        seen: list[str] = []
        if sp is not None and sp.exists():
            try:
                loaded = json.loads(sp.read_text(encoding="utf-8"))
            except ValueError:
                loaded = []  # corrupt state: treat as empty rather than go silent for the session
            seen = [x for x in loaded if isinstance(x, str)] if isinstance(loaded, list) else []
        if sp is None:
            return 0  # cannot remember what was sent: stay silent rather than repeat every turn
        new = [(cid, d) for cid, d in found if cid not in seen]
        if not new:
            return 0
        sp.write_text(json.dumps(seen + [cid for cid, _ in new]), encoding="utf-8")
        text = "Task routing (sent once per session per category; pattern-matched, so ignore any that do not apply):\n" + "\n".join(
            f"- {d.replace('{reference}', reference_hint())}" for _, d in new
        )
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
