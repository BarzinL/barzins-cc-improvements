#!/usr/bin/env python3
"""Standalone tests for verification_claim_gate.py - no pytest, just run it:

    python3 test_verification_claim_gate.py

Feeds the hook synthetic Claude Code transcripts (JSONL) covering every branch and
checks whether it blocks or passes. Exit 0 = all green, exit 1 = a case regressed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "verification_claim_gate.py"


def _run(events: list[dict], stop_hook_active: bool = False) -> bool:
    """Run the hook against a synthetic transcript. Returns True if it BLOCKED."""
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
        tp = f.name
    payload = {"session_id": "test", "transcript_path": tp, "stop_hook_active": stop_hook_active}
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    Path(tp).unlink(missing_ok=True)
    out = r.stdout.strip()
    if not out:
        return False
    try:
        return json.loads(out).get("decision") == "block"
    except (json.JSONDecodeError, ValueError):
        return False


def _user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _asst_text(text: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _asst_tool(cmd: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]},
    }


def _tool_result(text: str = "ok") -> dict:
    # Claude Code returns tool results as type:"user" events - these must NOT reset
    # the exchange window (regression guard for the tool-result false positive).
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": text}]}}


CASES = [
    # (name, events, stop_hook_active, want_block)
    (
        "claim + no action -> BLOCK",
        [_user("rebuild the report"), _asst_text("Verified end-to-end: topology validates and auth works.")],
        False,
        True,
    ),
    (
        "claim + verification action -> pass",
        [_user("rebuild it"), _asst_tool("pytest tests/"), _asst_text("Verified it works - all tests passed.")],
        False,
        False,
    ),
    (
        "claim but hedged -> pass",
        [_user("rebuild it"), _asst_text("Static checks pass, but I haven't verified it end-to-end - should run it first.")],
        False,
        False,
    ),
    (
        "no claim at all -> pass",
        [_user("what's next?"), _asst_text("Next is the scaffold spec; here's the fork.")],
        False,
        False,
    ),
    (
        "loop-safety: stop_hook_active=true suppresses block",
        [_user("rebuild it"), _asst_text("Verified end-to-end and healthy.")],
        True,
        False,
    ),
    (
        "'healthy' claim + no action -> BLOCK",
        [_user("monitor the release"), _asst_text("The release looks healthy, no error signal at all.")],
        False,
        True,
    ),
    (
        "'all tests pass' + npm test action -> pass",
        [_user("check the suite"), _asst_tool("npm test"), _asst_text("All tests passing.")],
        False,
        False,
    ),
    (
        "action -> tool_result -> summary claim in a LATER assistant msg -> pass "
        "(regression: tool_result must not reset the window)",
        [
            _user("build and verify it"),
            _asst_tool("pytest tests/"),
            _tool_result("8 passed"),
            _asst_text("All tests passed - the change is verified."),
        ],
        False,
        False,
    ),
]


def main() -> int:
    failures = 0
    for name, events, active, want in CASES:
        got = _run(events, stop_hook_active=active)
        ok = got == want
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  (want block={want}, got block={got})")
        if not ok:
            failures += 1

    # fail-open: a bad transcript path must not crash and must not block
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"session_id": "x", "transcript_path": "/nonexistent", "stop_hook_active": False}),
        capture_output=True,
        text=True,
    )
    fail_open_ok = r.returncode == 0 and not r.stdout.strip()
    print(f"[{'PASS' if fail_open_ok else 'FAIL'}] fail-open on bad path (exit 0, no output)")
    if not fail_open_ok:
        failures += 1

    print()
    if failures:
        print(f"{failures} case(s) FAILED")
        return 1
    print("all cases green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
