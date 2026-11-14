#!/usr/bin/env python3
"""Standalone tests for plan_reconciliation.py - no pytest, just run it:

    python3 test_plan_reconciliation.py

Each case builds a synthetic scratchpad (with or without plan.md) and a synthetic
transcript, runs the hook as a subprocess with a Stop payload, and checks whether it
fired. Cases marked [plan] are the acceptance cases from the plan; the others were
added. Exit 0 when every case passes, 1 otherwise.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "plan_reconciliation.py"

TWO_OPEN = """# Plan
- [x] Add the config loader
- [ ] Write the migration script
- [ ] Update the API docs
"""


def _user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def _meta(text: str) -> dict:
    return {"type": "user", "isMeta": True, "message": {"role": "user", "content": text}}


def _asst_text(text: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _asst_tool(cmd: str, tid: str = "toolu_1") -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]},
    }


def _tool_result(tid: str = "toolu_1", text: str = "ok") -> dict:
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text}]}}


WORK_TURN = [_user("carry on with the plan"), _asst_tool("python3 -m unittest"), _tool_result()]


def run_hook(stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(HOOK)], input=stdin,
                          capture_output=True, text=True, timeout=30)


def run_case(plan: str | None, events: list[dict], message: str | None,
             stop_hook_active: bool = False, with_scratch: bool = True) -> tuple[bool, str, int]:
    """Returns (fired, context_text, exit_code)."""
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "scratchpad"
        scratch.mkdir()
        if plan is not None:
            (scratch / "plan.md").write_text(plan)
        tp = Path(tmp) / "session.jsonl"
        tp.write_text("".join(json.dumps(e) + "\n" for e in events))
        payload = {
            "session_id": "test-session",
            "transcript_path": str(tp),
            "cwd": tmp,
            "hook_event_name": "Stop",
            "stop_hook_active": stop_hook_active,
        }
        if with_scratch:
            payload["scratchpad_dir"] = str(scratch)
        if message is not None:
            payload["last_assistant_message"] = message
        r = run_hook(json.dumps(payload))
    return _parse(r)


def _parse(r: subprocess.CompletedProcess) -> tuple[bool, str, int]:
    out = r.stdout.strip()
    if not out:
        return False, "", r.returncode
    try:
        obj = json.loads(out)
    except ValueError:
        return False, out, r.returncode
    ctx = (obj.get("hookSpecificOutput") or {}).get("additionalContext") or obj.get("reason") or ""
    fired = bool(ctx) or obj.get("decision") == "block"
    return fired, ctx, r.returncode


FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def main() -> int:
    completion = "Done. The config loader is in and all unit tests pass."

    # ---------------------------------------------------------- plan's cases --
    fired, ctx, code = run_case(None, WORK_TURN, completion)
    check("[plan] no plan for the session -> silent", not fired and code == 0, ctx)

    fired, ctx, code = run_case(None, WORK_TURN, completion, with_scratch=False)
    check("no scratchpad_dir in the payload -> silent", not fired and code == 0, ctx)

    all_done = "- [x] Add the config loader\n- [X] Write the migration script\n"
    fired, ctx, _ = run_case(all_done, WORK_TURN, completion)
    check("[plan] all items marked done -> silent", not fired, ctx)

    deferred = ("The config loader is done. Two items are deferred: the migration script "
                "waits on the schema freeze next week, and the API docs wait until the "
                "endpoint names are reviewed.")
    fired, ctx, _ = run_case(TWO_OPEN, WORK_TURN, deferred)
    check("[plan] two open; message says both deferred and why -> silent", not fired, ctx)

    fired, ctx, _ = run_case(TWO_OPEN, WORK_TURN, completion)
    names_both = "Write the migration script" in ctx and "Update the API docs" in ctx
    check("[plan] two open; completion message mentions neither -> fires naming both",
          fired and names_both, ctx)
    fired2, ctx2, _ = run_case(TWO_OPEN, WORK_TURN, completion, stop_hook_active=True)
    check("[plan] ... and only once: the follow-up stop (stop_hook_active) is silent",
          not fired2, ctx2)

    question = ("The config loader is in and tests pass. Should I do the migration "
                "script next, or the docs first?")
    fired, ctx, _ = run_case(TWO_OPEN, WORK_TURN, question)
    check("[plan] turn ends with a question, items open -> silent", not fired, ctx)

    fired, ctx, _ = run_case(TWO_OPEN, WORK_TURN, completion, stop_hook_active=True)
    check("[plan] second stop in the same cycle -> silent", not fired, ctx)

    # -------------------------------------------------------- added cases --
    fired, ctx, _ = run_case(TWO_OPEN, WORK_TURN,
                             "Done. The migration script is written and runs clean.")
    check("one of two mentioned -> fires naming only the other",
          fired and "Update the API docs" in ctx and "Write the migration script" not in ctx, ctx)

    keyed = "- [x] B2: revise the claim gate\n- [ ] B3: plan reconciliation hook\n- [ ] B4: placeholder hook\n"
    fired, ctx, _ = run_case(keyed, WORK_TURN, "B3 is finished. B4 is deferred until B3 has run live.")
    check("items mentioned by key (B3, B4) -> silent", not fired, ctx)

    fired, ctx, _ = run_case(keyed, WORK_TURN, "B3 is finished; tests pass.")
    check("keyed item not mentioned -> fires naming it", fired and "B4: placeholder hook" in ctx, ctx)

    fired, ctx, _ = run_case(keyed, WORK_TURN, "B3 is finished. b33 and B4x are separate.")
    check("key must match as a whole token (b33, B4x do not count)", fired and "B4" in ctx, ctx)

    chat = [_user("what does the loader read first?")]
    fired, ctx, _ = run_case(TWO_OPEN, chat, "It reads the environment first, then the file.")
    check("conversational reply, no tool calls, no completion words -> silent", not fired, ctx)

    fired, ctx, _ = run_case(TWO_OPEN, chat, "Finished: the loader now reads the environment first.")
    check("no tool calls but completion words -> fires", fired, ctx)

    events = WORK_TURN + [_asst_text(completion)]
    fired, ctx, _ = run_case(TWO_OPEN, events, None)
    check("no last_assistant_message; final text read from transcript -> fires", fired, ctx)

    events = WORK_TURN + [_meta("synthetic harness note"), _asst_text("Here is where things stand.")]
    fired, ctx, _ = run_case(TWO_OPEN, events, "Here is where things stand.")
    check("meta message mid-turn does not hide the turn's tool calls -> fires", fired, ctx)

    mid_q = ("Was the old loader meant to be kept? I assumed not and removed it.\n\n"
             "Done: the config loader is in.")
    fired, ctx, _ = run_case(TWO_OPEN, WORK_TURN, mid_q)
    check("question earlier in the message, report at the end -> fires", fired, ctx)

    numbered = "1. [ ] Write the migration script\n2. [x] Add the config loader\n"
    fired, ctx, _ = run_case(numbered, WORK_TURN, completion)
    check("numbered checklist items are read -> fires", fired and "migration" in ctx, ctx)

    # ---------------------------------------------------------- fail-open --
    for label, stdin in [
        ("non-JSON stdin", "this is not json"),
        ("JSON that is not an object", "[1, 2, 3]"),
        ("empty stdin", ""),
        ("scratchpad_dir is a number", json.dumps({"scratchpad_dir": 7, "last_assistant_message": "done"})),
        ("transcript_path missing on disk",
         json.dumps({"scratchpad_dir": "/nonexistent/x", "transcript_path": "/nonexistent/t.jsonl"})),
    ]:
        r = run_hook(stdin)
        check(f"fail-open: {label} -> exit 0, no output",
              r.returncode == 0 and not r.stdout.strip() and not r.stderr.strip(),
              f"rc={r.returncode} out={r.stdout!r} err={r.stderr[-200:]!r}")

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "plan.md").mkdir()  # a directory where the file should be
        r = run_hook(json.dumps({"scratchpad_dir": tmp, "last_assistant_message": "done"}))
        check("fail-open: plan.md is a directory -> exit 0, no output",
              r.returncode == 0 and not r.stdout.strip())

    print()
    if FAILURES:
        print(f"{len(FAILURES)} case(s) FAILED")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
