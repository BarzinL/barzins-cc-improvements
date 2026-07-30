#!/usr/bin/env python3
"""UserPromptSubmit hook: inject model-specific instructions, read from payload files.

Project instructions (`CLAUDE.md`) are written once, for whichever model normally
drives the session. Switching mid-session with `/model` changes nothing about them, so
a rule that raises a frontier model's ceiling keeps costing a smaller one, and a rule
that only one family needs has nowhere to live. This hook closes that gap: one short
payload per model family, injected into the user turn.

Payloads are files, not code. `model-discipline-payloads/<family>.md` is injected when
that family is live. Two optional directives on the leading lines of a payload:

    <!-- cadence: every-turn -->   inject on every user prompt (default: on-change)
    <!-- same-as: sonnet -->       use another family's payload and cadence

Cadence matters more than it looks. An injection lands once, early, and is summarized
away by the first compaction, after which the family has not changed so nothing
re-fires (measured: a state file still read `opus` across a compaction). So
`on-change` suits a rule about a stint - you switched models, here is what differs.
A rule needed on every substantive turn, such as an output-format rule, must be
`every-turn`, or it decays out of context while still looking installed.

Model identity is read from the transcript, not from a hook field: only SessionStart
receives a `model`, and it does not re-fire on `/model`. Every assistant record in the
transcript carries `message.model`, which is the live value.

**The normalizer is deliberately local and must stay that way.** The model field is not
a closed set of exact strings. Measured across every transcript on one machine
(2026-07-26): versioned IDs (`claude-opus-5`), dated IDs
(`claude-haiku-4-5-20251001`), bare aliases from settings.json (`opus`, `sonnet`,
`haiku` - 341 occurrences), and 552 records literally labelled `<synthetic>`. Bracket
suffixes such as `claude-opus-5[1m]` did not appear there but are a documented form. So
this matches on family after normalizing, and never against a list of full IDs.

**Subagents.** This fires on `UserPromptSubmit`, which is a real user prompt. A
subagent's prompt arrives as an Agent/Task tool call instead, and its transcript is a
separate file under `<session>/subagents/`. In a sampled subagent transcript the first
message was the parent's prompt verbatim, with no injected content and no
system-reminder, so nothing here reaches a subagent's context. That is evidence rather
than proof: transcripts do not record system prompts.

Fails OPEN on anything unexpected: a hook that cannot identify the model prints
nothing and exits 0. Injecting the wrong discipline is worse than injecting none.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

_SYNTHETIC = "<synthetic>"
_DATE_SUFFIX = re.compile(r"-\d{8}$|-\d{2}-\d{2}$")
_DIRECTIVE = re.compile(r"^<!--\s*(cadence|same-as)\s*:\s*([A-Za-z0-9_-]+)\s*-->\s*$")

# Families recognized even with no payload file, so switching to one still records the
# change and does not leave another family's payload standing as the last thing said.
_BASE_FAMILIES = ("fable", "mythos", "opus", "sonnet", "haiku")

_CADENCES = ("on-change", "every-turn")


def payload_dir() -> Path:
    override = os.environ.get("MODEL_DISCIPLINE_PAYLOAD_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "model-discipline-payloads"


def state_path(session_id: str) -> Path:
    # Overridable so a test run gets a fresh state dir; without it, state from an
    # earlier run persists and a "no change" result is indistinguishable from a
    # broken matcher.
    override = os.environ.get("MODEL_DISCIPLINE_STATE_DIR")
    d = Path(override) if override else Path(tempfile.gettempdir()) / f"model-discipline-{os.getuid()}"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session_id}.model"


def known_families() -> tuple[str, ...]:
    """Base families plus any added by dropping in a payload file.

    Longest-first so a longer name cannot be shadowed by a shorter prefix of it.
    """
    extra: set[str] = set()
    try:
        for f in payload_dir().glob("*.md"):
            name = f.stem.strip().lower()
            if name and re.fullmatch(r"[a-z0-9_-]+", name):
                extra.add(name)
    except OSError:
        pass
    return tuple(sorted(set(_BASE_FAMILIES) | extra, key=lambda s: (-len(s), s)))


def family_of(model: str) -> str | None:
    """Map any observed model string onto a family, or None if unrecognized."""
    s = model.strip().lower()
    if not s or s == _SYNTHETIC:
        return None
    s = s.removeprefix("claude-")
    for cut in ("[", "@"):  # variant suffixes, e.g. claude-opus-5[1m]
        s = s.split(cut, 1)[0]
    s = _DATE_SUFFIX.sub("", s)
    return next((f for f in known_families() if s.startswith(f)), None)


def _read_payload(family: str) -> tuple[str, str, str | None] | None:
    """Return (text, cadence, same_as) for a family, or None if it has no payload."""
    p = payload_dir() / f"{family}.md"
    try:
        raw = p.read_text(errors="ignore")
    except OSError:
        return None
    cadence = "on-change"
    same_as: str | None = None
    body: list[str] = []
    for line in raw.splitlines():
        m = _DIRECTIVE.match(line) if not body else None
        if m:
            key, value = m.group(1), m.group(2).lower()
            if key == "cadence" and value in _CADENCES:
                cadence = value
            elif key == "same-as":
                same_as = value
            continue
        if line.strip() or body:
            body.append(line)
    return "\n".join(body).strip(), cadence, same_as


def payload_for(family: str) -> tuple[str, str] | None:
    """Resolve a family to (text, cadence), following `same-as` at most twice."""
    seen: set[str] = set()
    current = family
    for _ in range(3):
        if current in seen:
            return None  # a cycle: say nothing rather than guess
        seen.add(current)
        found = _read_payload(current)
        if found is None:
            return None
        text, cadence, same_as = found
        if same_as:
            current = same_as
            continue
        return (text, cadence) if text else None
    return None


def current_family(transcript: Path) -> str | None:
    """Family of the most recent real assistant turn, skipping synthetic records."""
    try:
        lines = transcript.read_text(errors="ignore").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"model"' not in line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "assistant":
            continue
        fam = family_of((obj.get("message") or {}).get("model") or "")
        if fam:
            return fam
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
        session_id = data.get("session_id")
        tp = data.get("transcript_path")
        if not isinstance(session_id, str) or not isinstance(tp, str):
            return 0
        transcript = Path(tp)
        if not transcript.is_file():
            return 0

        fam = current_family(transcript)
        if fam is None:
            return 0  # first turn, or an unrecognized string: say nothing

        state = state_path(session_id)
        try:
            last = state.read_text().strip()
        except OSError:
            last = ""
        # State advances even for a family with no payload, so returning to a family
        # that does have one speaks again.
        if fam != last:
            state.write_text(fam)

        resolved = payload_for(fam)
        if resolved is None:
            return 0
        text, cadence = resolved
        if cadence == "on-change" and fam == last:
            return 0
        print(text)
    except Exception:
        return 0  # never block or noise up a prompt
    return 0


if __name__ == "__main__":
    sys.exit(main())
