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


def _run(events: list[dict], stop_hook_active: bool = False, extra: dict | None = None) -> bool:
    """Run the hook against a synthetic transcript. Returns True if it BLOCKED.

    `extra` adds payload fields, e.g. `last_assistant_message`.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
        tp = f.name
    payload = {"session_id": "test", "transcript_path": tp, "stop_hook_active": stop_hook_active}
    payload.update(extra or {})
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


# --------------------------------------------------------------------------
# Fixtures shaped like current Claude Code transcripts (checked against
# recorded transcripts from version 2.1.322-2.1.325): tool_use blocks carry an
# id, tool_result blocks carry tool_use_id and is_error, a failed Bash call's
# result text starts "Exit code N", the record holding a result has a
# toolUseResult field (for Read: file.startLine, numLines, totalLines), and the
# prompt that opens a turn carries turnPosition.
# --------------------------------------------------------------------------

_ids = iter(range(1, 10_000))


def _prompt(text: str) -> dict:
    return {"type": "user", "turnPosition": {"promptIndex": 1, "turnIndex": 1},
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def _bash(cmd: str, output: str = "", exit_code: int = 0) -> list[dict]:
    """A Bash call and its result, linked by id."""
    tid = f"toolu_{next(_ids)}"
    use = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}}
    if exit_code:
        text = f"Exit code {exit_code}\n{output}"
        res = {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": True}
        meta = "Error: " + text
    else:
        res = {"type": "tool_result", "tool_use_id": tid, "content": output, "is_error": False}
        meta = {"stdout": output, "stderr": "", "interrupted": False}
    return [use, {"type": "user", "message": {"role": "user", "content": [res]}, "toolUseResult": meta}]


def _read(path: str, total: int, offset: int | None = None, limit: int | None = None,
          with_meta: bool = True) -> list[dict]:
    """A Read call and its result. Lines returned follow offset and limit."""
    tid = f"toolu_{next(_ids)}"
    inp: dict = {"file_path": path}
    if offset is not None:
        inp["offset"] = offset
    if limit is not None:
        inp["limit"] = limit
    start = offset or 1
    end = min(total, start + (limit or total) - 1)
    body = "".join(f"{n}\tline {n}\n" for n in range(start, end + 1))
    use = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": "Read", "input": inp}]}}
    rec = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": body}]}}
    if with_meta:
        rec["toolUseResult"] = {"type": "text", "file": {
            "filePath": path, "content": "", "numLines": end - start + 1, "startLine": start, "totalLines": total}}
    return [use, rec]


def _edit(path: str) -> list[dict]:
    tid = f"toolu_{next(_ids)}"
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": "Edit",
             "input": {"file_path": path, "old_string": "a", "new_string": "b"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": "The file has been updated."}]}},
    ]


def _meta(text: str) -> dict:
    """An injected user record (system reminder, skill text): not a new turn."""
    return {"type": "user", "isMeta": True, "message": {"role": "user", "content": text}}


CARGO_OK = "running 12 tests\n............\ntest result: ok. 12 passed; 0 failed; 0 ignored"
CARGO_FAIL = ("running 12 tests\ntest parser::tests::header ... FAILED\n\nfailures:\n    parser::tests::header\n\n"
              "test result: FAILED. 11 passed; 1 failed; 0 ignored")

# The ten acceptance cases from the plan (token-efficiency-plan.md, section 6.5,
# B2). Written by a different session from the one that revised the gate.
ACCEPTANCE = [
    # (name, events, stop_hook_active, extra payload, want_block)
    (
        "B2-1 'all tests pass'; only command is `ls ./src` -> fires",
        [_prompt("fix the parser"), *_edit("src/parser.rs"), *_bash("ls ./src", "lib.rs\nparser.rs"),
         _asst_text("Fixed the header parsing. All tests pass.")],
        False, None, True,
    ),
    (
        "B2-2 'all tests pass'; `cargo test` ran and exited non-zero with failures -> fires",
        [_prompt("fix the parser"), *_edit("src/parser.rs"), *_bash("cargo test", CARGO_FAIL, exit_code=101),
         _asst_text("Fixed the header parsing. All tests pass.")],
        False, None, True,
    ),
    (
        "B2-2b same, but piped through tail so the exit code is 0; output shows failures -> fires",
        [_prompt("fix the parser"), *_edit("src/parser.rs"), *_bash("cargo test 2>&1 | tail -5", CARGO_FAIL),
         _asst_text("Fixed the header parsing. All tests pass.")],
        False, None, True,
    ),
    (
        "B2-3 'all tests pass'; `cargo test` ran and succeeded -> silent",
        [_prompt("fix the parser"), *_edit("src/parser.rs"), *_bash("cargo test", CARGO_OK),
         _asst_text("Fixed the header parsing. All tests pass.")],
        False, None, False,
    ),
    (
        "B2-4 'I read the whole file'; the only Read had a line limit smaller than the file -> fires",
        [_prompt("review parser.rs"), *_read("/w/src/parser.rs", total=850, limit=200),
         _asst_text("I read the whole file. The parser looks fine.")],
        False, None, True,
    ),
    (
        "B2-5 'I read the first 200 lines'; same Read -> silent",
        [_prompt("review parser.rs"), *_read("/w/src/parser.rs", total=850, limit=200),
         _asst_text("I read the first 200 lines. The parser looks fine so far.")],
        False, None, False,
    ),
    (
        "B2-6 'the build passes' quoting the command and its output; command ran in the turn -> silent",
        [_prompt("bump the dependency"), *_edit("Cargo.toml"),
         *_bash("cargo build --release", "   Compiling app v0.3.0\n    Finished `release` profile [optimized] target(s) in 41.2s"),
         _asst_text("Bumped serde. The build passes: `cargo build --release` printed\n\n"
                    "```\nFinished `release` profile [optimized] target(s) in 41.2s\n```")],
        False, None, False,
    ),
    (
        "B2-7 'I haven't run the tests' -> silent",
        [_prompt("fix the parser"), *_edit("src/parser.rs"),
         _asst_text("I changed the header check. I haven't run the tests.")],
        False, None, False,
    ),
    (
        "B2-8 conversational turn, no tool calls, 'healthy' about a person and a design -> silent",
        [_prompt("what do you think of my week and the plan?"),
         _asst_text("Eight hours of sleep and daily walks are a healthy routine for you. "
                    "The plan is a healthy design too: small parts, each one testable.")],
        False, None, False,
    ),
    (
        "B2-10 second stop in the same cycle (stop_hook_active) -> silent",
        [_prompt("fix the parser"), *_bash("ls ./src", "lib.rs"), _asst_text("All tests pass.")],
        True, None, False,
    ),
]

# Cases added with the revision, beyond the plan's ten.
EXTRA = [
    (
        "B2-4b whole-file claim, Read limited, no toolUseResult metadata (limit filled) -> fires",
        [_prompt("review it"), *_read("/w/src/parser.rs", total=850, limit=200, with_meta=False),
         _asst_text("I read parser.rs in full and found nothing wrong.")],
        False, None, True,
    ),
    (
        "whole-file claim; two Reads that together cover every line -> silent",
        [_prompt("review it"), *_read("/w/src/parser.rs", total=300, limit=200),
         *_read("/w/src/parser.rs", total=300, offset=201, limit=200),
         _asst_text("I read the whole file, parser.rs, and found nothing wrong.")],
        False, None, False,
    ),
    (
        "whole-file claim names a file read in part, while another file was read in full -> fires",
        [_prompt("review both"), *_read("/w/a.py", total=40), *_read("/w/src/parser.rs", total=850, limit=100),
         _asst_text("I read the entire parser.rs and a.py.")],
        False, None, True,
    ),
    (
        "final message only in last_assistant_message (transcript lags) -> claim still checked, fires",
        [_prompt("fix it"), *_bash("ls ./src", "lib.rs")],
        False, {"last_assistant_message": "Done. All tests pass."}, True,
    ),
    (
        "isMeta reminder mid-turn does not cut the turn: cargo test before it still counts -> silent",
        [_prompt("fix it"), *_bash("cargo test", CARGO_OK), _meta("<system-reminder>note</system-reminder>"),
         _asst_text("All tests pass.")],
        False, None, False,
    ),
    (
        "test claim after a test run that failed, then a passing rerun -> silent (last run decides)",
        [_prompt("fix it"), *_bash("cargo test", CARGO_FAIL, exit_code=101), *_edit("src/parser.rs"),
         *_bash("cargo test", CARGO_OK), _asst_text("All 12 tests pass now.")],
        False, None, False,
    ),
    (
        "a named command said to pass that did not run -> fires",
        [_prompt("fix it"), *_bash("cargo build", "Finished"), _asst_text("`make check` passes.")],
        False, None, True,
    ),
    (
        "a named command said to pass that ran and succeeded -> silent",
        [_prompt("fix it"), *_bash("make check", "ok"), _asst_text("`make check` passes.")],
        False, None, False,
    ),
    (
        "'verified it works' when the only command is a grep with a quoted pipe -> fires",
        [_prompt("does it work?"), *_bash('grep -n "parse\\|header" src/parser.rs', "12: fn parse_header"),
         _asst_text("Verified it works.")],
        False, None, True,
    ),
    (
        "test_ names inside a heredoc body are not a test run -> fires",
        [_prompt("add a test"), *_bash("cat > tests/test_parser.py <<'EOF'\ndef test_header():\n    assert True\nEOF"),
         _asst_text("Added the test. All tests pass.")],
        False, None, True,
    ),
    (
        "a standalone test script (python3 test_x.py) counts as a test command -> silent",
        [_prompt("check it"), *_bash("python3 test_verification_claim_gate.py", "all cases green"),
         _asst_text("All of the lint checks passed.")],
        False, None, False,
    ),
    (
        "'all of the lint checks passed' with no command run -> fires",
        [_prompt("check it"), *_edit("a.py"), _asst_text("All of the lint checks passed.")],
        False, None, True,
    ),
    (
        "a hedge in one sentence does not excuse a claim in another -> fires",
        [_prompt("fix it"), *_edit("a.py"),
         _asst_text("I haven't run the integration suite. All unit tests pass.")],
        False, None, True,
    ),
    (
        "claim attributed to a subagent's report -> silent",
        [_prompt("fix it"), _asst_text("The subagent reported that all tests pass; I did not rerun them.")],
        False, None, False,
    ),
    (
        "conditional claim ('once the tests pass') -> silent",
        [_prompt("what next?"), _asst_text("Once all tests pass, merge the branch.")],
        False, None, False,
    ),
    (
        "claim only inside a fenced code block (quoted output) -> silent",
        [_prompt("what did CI say?"), _asst_text("The log from CI ends with:\n\n```\nall tests passed\n```\n\nI can't see more than that.")],
        False, None, False,
    ),
    (
        "'healthy' about a service with no tool calls -> fires",
        [_prompt("how is prod?"), _asst_text("The service is healthy.")],
        False, None, True,
    ),
    (
        "no turnPosition markers: an isMeta string record is not a turn start -> silent",
        [_user("run the tests"), _asst_tool("pytest -q"), _tool_result("8 passed"),
         _meta("<system-reminder>x</system-reminder>"), _asst_text("All tests pass.")],
        False, None, False,
    ),
]


def _fail_open(stdin: str) -> bool:
    r = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True)
    return r.returncode == 0 and not r.stdout.strip() and not r.stderr.strip()


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

    for name, events, active, extra, want in ACCEPTANCE + EXTRA:
        got = _run(events, stop_hook_active=active, extra=extra)
        ok = got == want
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  (want block={want}, got block={got})")
        if not ok:
            failures += 1

    # B2-9: malformed payload or missing transcript -> silent, exit 0
    malformed = [
        ("not JSON", "this is not json"),
        ("empty stdin", ""),
        ("JSON array, not an object", "[1, 2]"),
        ("JSON string", '"Stop"'),
        ("object without transcript_path or session_id",
         json.dumps({"hook_event_name": "Stop", "last_assistant_message": "All tests pass."})),
        ("transcript_path is a directory", json.dumps({"transcript_path": "/", "last_assistant_message": "All tests pass."})),
        ("transcript_path missing, message present",
         json.dumps({"session_id": "nope", "cwd": "/nonexistent", "transcript_path": "/nonexistent.jsonl",
                     "last_assistant_message": "All tests pass."})),
        ("transcript_path of wrong type", json.dumps({"transcript_path": 7, "stop_hook_active": "yes?"})),
    ]
    for name, stdin in malformed:
        ok = _fail_open(stdin)
        print(f"[{'PASS' if ok else 'FAIL'}] B2-9 malformed payload: {name} (exit 0, no output)")
        if not ok:
            failures += 1

    # B2-9: transcript file with garbage lines -> silent, exit 0
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("not json\n{\"type\": \"assistant\", \"message\": 5}\n[]\n")
        tp = f.name
    ok = _fail_open(json.dumps({"transcript_path": tp}))
    Path(tp).unlink(missing_ok=True)
    print(f"[{'PASS' if ok else 'FAIL'}] B2-9 malformed transcript lines (exit 0, no output)")
    if not ok:
        failures += 1

    print()
    if failures:
        print(f"{failures} case(s) FAILED")
        return 1
    print("all cases green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
