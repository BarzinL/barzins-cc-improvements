#!/usr/bin/env python3
"""Standalone tests for verification_claim_gate.py - no pytest, just run it:

    python3 test_verification_claim_gate.py

Feeds the hook synthetic Claude Code transcripts (JSONL) covering every branch and
checks whether it blocks or passes. Exit 0 = all green, exit 1 = a case regressed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# CLAIM_GATE lets the same cases run against another copy of the gate (an older version).
HOOK = Path(os.environ.get("CLAIM_GATE") or Path(__file__).resolve().parent / "verification_claim_gate.py")


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


EXTRA += [
    (
        "S-1 whole-file claim; file read in two turns of the session -> silent",
        [_prompt("start on parser.rs"), *_read("/w/src/parser.rs", total=300, limit=200), _asst_text("Read the first part."),
         _prompt("go on"), *_read("/w/src/parser.rs", total=300, offset=201, limit=200),
         _asst_text("I read parser.rs in full and found nothing wrong.")],
        False, None, False,
    ),
    (
        "S-2 whole-file claim; earlier turn and this turn together still leave a gap -> fires",
        [_prompt("start on parser.rs"), *_read("/w/src/parser.rs", total=900, limit=200), _asst_text("Read the first part."),
         _prompt("go on"), *_read("/w/src/parser.rs", total=900, offset=201, limit=200),
         _asst_text("I read parser.rs in full and found nothing wrong.")],
        False, None, True,
    ),
    (
        "S-3 whole-file claim after `sed -n 1,80p` on the file -> fires",
        [_prompt("review notes.md"), *_bash("sed -n 1,80p docs/notes.md", "line"),
         _asst_text("I read notes.md in full. It is consistent.")],
        False, None, True,
    ),
    (
        "S-4 whole-file claim after `cat` on the file -> silent",
        [_prompt("review notes.md"), *_bash("cat docs/notes.md", "line"),
         _asst_text("I read notes.md in full. It is consistent.")],
        False, None, False,
    ),
    (
        "S-5 whole-file claim after only `cat file | head -30` -> fires",
        [_prompt("review notes.md"), *_bash("cat docs/notes.md | head -30", "line"),
         _asst_text("I read notes.md in full. It is consistent.")],
        False, None, True,
    ),
    (
        "S-5b whole-file claim after `cat file | head -30` and `head -30 file` -> fires",
        [_prompt("review notes.md"), *_bash("cat docs/notes.md | head -30", "line"), *_bash("head -30 docs/notes.md", "line"),
         _asst_text("I read notes.md in full. It is consistent.")],
        False, None, True,
    ),
    (
        "S-6 'read through the whole repository' -> fires",
        [_prompt("look at the repo"), *_bash("ls src && sed -n 1,40p src/lib.rs", "x"),
         _asst_text("I read through the whole repository. The design is sound.")],
        False, None, True,
    ),
    (
        "S-7 'I read the README and src/lib.rs' (names what was read) -> silent",
        [_prompt("look at the repo"), *_bash("cat README.md", "x"),
         _asst_text("I read the README and the top of src/lib.rs. The design looks sound so far.")],
        False, None, False,
    ),
    (
        "P-1 '3x faster' with no timing command in the turn -> fires",
        [_prompt("speed up the parser"), *_edit("/w/src/parser.rs"), *_bash("cargo build --release", "Finished"),
         _asst_text("The parser is now 3x faster on large inputs.")],
        False, None, True,
    ),
    (
        "P-2 '3x faster' after hyperfine ran -> silent",
        [_prompt("speed up the parser"), *_bash("hyperfine './target/release/p big.txt'", "Time (mean): 1.2 s"),
         *_edit("/w/src/parser.rs"), *_bash("hyperfine './target/release/p big.txt'", "Time (mean): 0.4 s"),
         _asst_text("The parser is now 3x faster on big.txt: 1.2 s before, 0.4 s after.")],
        False, None, False,
    ),
    (
        "P-3 'should be faster' (no number) -> silent",
        [_prompt("speed up the parser"), *_edit("/w/src/parser.rs"),
         _asst_text("This should be faster, but I have not measured it.")],
        False, None, False,
    ),
    (
        "P-4 'reduced memory usage by 40%' after `time` on an unrelated failing command only -> fires",
        [_prompt("cut memory"), *_edit("/w/src/a.rs"), *_bash("time ./run", "boom", exit_code=1),
         _asst_text("I reduced memory usage by 40%.")],
        False, None, True,
    ),
]

def _bash_at(cmd: str, output: str, cwd: str, exit_code: int = 0) -> list[dict]:
    """A Bash call whose transcript records carry the session's working directory."""
    events = _bash(cmd, output, exit_code)
    for e in events:
        e["cwd"] = cwd
    return events


PERSISTED = ("<persisted-output>\nOutput too large (45.2KB). Full output saved to: /tmp/x/tool-results/b1.txt\n\n"
             "Preview (first 2KB):\nline 1\nline 2\n</persisted-output>")

# Cases written from the defects found in review of the second revision. Each defect
# case failed against the gate before its fix; the cases marked "guard" in the README
# already passed and are there so the fix does not overshoot.
FIXES = [
    ("G-1b `cat data.json | head -5` only, claim data.json in full -> fires",
     [_prompt("review"), *_bash("cat data.json | head -5", "{"), _asst_text("I read data.json in full.")], True),
    ("G-1c `cat -n FILE` is a whole read -> silent",
     [_prompt("review"), *_bash("cat -n docs/notes.md", "     1\tline"), _asst_text("I read notes.md in full.")], False),
    ("G-1d `cat a.md b.md` reads both files -> silent",
     [_prompt("review"), *_bash("cat docs/a.md docs/b.md", "x\ny"), _asst_text("I read b.md in full.")], False),
    ("G-1e `cat` inside a heredoc script body is not a read -> fires",
     [_prompt("review"), *_bash("python3 - <<'EOF'\nimport os\nos.system('cat notes.md')\nEOF", "x"),
      _asst_text("I read notes.md in full.")], True),
    ("G-1f `cat FILE > copy` shows nothing, so it is not a read -> fires",
     [_prompt("review"), *_bash("cat docs/notes.md > /tmp/copy.md", ""), _asst_text("I read notes.md in full.")], True),
    ("G-2a a/config.py read in full does not cover a claim about b/config.py -> fires",
     [_prompt("review"), *_read("/w/a/config.py", total=50), *_bash_at("sed -n 1,50p b/config.py", "x", "/w"),
      _asst_text("I read b/config.py in full.")], True),
    ("G-2b relative sed range resolved against cwd adds to an absolute Read -> silent",
     [_prompt("review"), *_read("/w/docs/notes.md", total=200, limit=100),
      *_bash_at("sed -n 101,200p docs/notes.md", "x", "/w"), _asst_text("I read docs/notes.md in full.")], False),
    ("G-2c same without a recorded cwd: matched on the shared path suffix -> silent",
     [_prompt("review"), *_read("/w/docs/notes.md", total=200, limit=100),
      *_bash("sed -n 101,200p docs/notes.md", "x"), _asst_text("I read docs/notes.md in full.")], False),
    ("G-2d bare name, two same-named files, one read in full -> silent (ambiguous, lenient)",
     [_prompt("review"), *_read("/w/a/config.py", total=50), *_read("/w/b/config.py", total=100, limit=10),
      _asst_text("I read config.py in full.")], False),
    ("G-2e claim names b/config.py, only a/config.py was read -> fires",
     [_prompt("review"), *_read("/w/a/config.py", total=50), _asst_text("I read b/config.py in full.")], True),
    ("G-3 a.py read in part, data.py in full; claim about data.py -> silent",
     [_prompt("review"), *_read("/w/a.py", total=100, limit=10), *_read("/w/data.py", total=40),
      _asst_text("I read data.py in full.")], False),
    ("G-4a 'the entire project brief' is not a repository claim -> silent",
     [_prompt("plan"), *_read("/w/brief.md", total=40), _asst_text("I read the entire project brief before starting.")],
     False),
    ("G-4b 'the entire repository before starting' -> fires",
     [_prompt("plan"), *_read("/w/brief.md", total=40), _asst_text("I read the entire repository before starting.")],
     True),
    ("G-5a '3x faster' with only `ls benchmarks/` -> fires",
     [_prompt("speed"), *_edit("/w/a.rs"), *_bash("ls benchmarks/", "a.rs"), _asst_text("The parser is now 3x faster.")],
     True),
    ("G-5b '3x faster' with only `grep -n time src/a.rs` -> fires",
     [_prompt("speed"), *_edit("/w/a.rs"), *_bash("grep -n time src/a.rs", "1:x"),
      _asst_text("The parser is now 3x faster.")], True),
    ("G-5c '3x faster' after `./bench.sh` -> silent",
     [_prompt("speed"), *_bash("./bench.sh", "1.2 s"), *_edit("/w/a.rs"), *_bash("./bench.sh", "0.4 s"),
      _asst_text("The parser is now 3x faster.")], False),
    ("G-5d '3x faster' after `/usr/bin/time -v` -> silent",
     [_prompt("speed"), *_bash("/usr/bin/time -v ./target/release/p big.txt", "Elapsed: 0.4"),
      _asst_text("The parser is now 3x faster.")], False),
    ("G-5e '3x faster' after `python3 benchmarks/run_bench.py` -> silent",
     [_prompt("speed"), *_bash("python3 benchmarks/run_bench.py", "0.4 s"), _asst_text("The parser is now 3x faster.")],
     False),
    ("G-5f '3x faster' after `cd build && time make` -> silent",
     [_prompt("speed"), *_bash("cd build && time make", "real 0m4.1s"), _asst_text("The build is now 3x faster.")],
     False),
    ("G-6 `cat` whose output Claude Code persisted as too large -> fires",
     [_prompt("review"), *_bash("cat big.log", PERSISTED), _asst_text("I read big.log in full.")], True),
    ("G-7 `head -n 5000` that printed fewer lines than asked showed the whole file -> silent",
     [_prompt("review"), *_bash("head -n 5000 small.py", "a\nb\nc"), _asst_text("I read small.py in full.")], False),
    ("G-7b `head -n 3` that printed exactly 3 lines may have stopped early -> fires",
     [_prompt("review"), *_bash("head -n 3 small.py", "a\nb\nc"), _asst_text("I read small.py in full.")], True),
    ("G-7c `sed -n 1,500p` that printed fewer lines than asked -> silent",
     [_prompt("review"), *_bash("sed -n 1,500p small.py", "a\nb\nc"), _asst_text("I read small.py in full.")], False),
    ("G-8a a run time stated as background, no tool calls -> silent",
     [_prompt("how long?"), _asst_text("On the workstation the full training run completes in 40 minutes.")], False),
    ("G-8b 'now runs in 1.2 s' with no timing command -> fires",
     [_prompt("speed"), *_edit("/w/a.rs"), _asst_text("The parser now runs in 1.2 s.")], True),
    ("G-8c 'dropped from 900 ms to 300 ms' with no timing command -> fires",
     [_prompt("speed"), *_edit("/w/a.rs"), _asst_text("Startup dropped from 900 ms to 300 ms.")], True),
    ("G-9 claim names a file never read; another file was read in full -> fires",
     [_prompt("review"), *_read("/w/other.py", total=40), _asst_text("I read the whole config.toml.")], True),
    ("G-9b a second file mentioned after the claim is not its object -> silent",
     [_prompt("review"), *_read("/w/parser.rs", total=40), _asst_text("I read parser.rs in full, and it imports lexer.rs.")],
     False),
    ("G-11 a general statement about tests ('all pass means ...') -> silent",
     [_prompt("how does the benchmark score?"),
      _asst_text("Each task comes with a set of tests the model never sees ... all pass means the task counts as "
                 "solved, otherwise it doesn't.")], False),
    ("G-12a 'I've read through <dir>' after partial reads under it -> fires",
     [_prompt("look at it"), *_read("/w/widget-core/README.md", total=40),
      *_read("/w/widget-core/docs/plan.md", total=900, limit=200),
      _asst_text("I've read through widget-core. Here's what I took from it.")], True),
    ("G-12b 'I've read through <dir>' when every read under it was whole -> silent",
     [_prompt("look at it"), *_read("/w/widget-core/README.md", total=40), *_read("/w/widget-core/docs/plan.md", total=90),
      _asst_text("I've read through widget-core. Here's what I took from it.")], False),
    ("G-12c 'read through the paper' (not a directory read in the session) -> silent",
     [_prompt("look at it"), *_read("/w/docs/plan.md", total=900, limit=200),
      _asst_text("I read through the paper and the notes.")], False),
    ("G-13a 'I read all four handoffs'; three read in full, one in part -> fires",
     [_prompt("synthesise"), *_read("/w/h/a_handoff.md", total=40), *_read("/w/h/b_handoff.md", total=40),
      *_read("/w/h/c_handoff.md", total=40), *_read("/w/h/d_handoff.md", total=229, limit=60),
      _asst_text("I read all four handoffs and wrote the synthesis.")], True),
    ("G-13b four handoffs read in full across two turns, one by sed -> silent",
     [_prompt("start"), *_read("/w/h/a_handoff.md", total=40), *_bash_at("sed -n 1,1000p h/b_handoff.md", "x", "/w"),
      _asst_text("Read two."), _prompt("go on"), *_read("/w/h/c_handoff.md", total=40),
      *_read("/w/h/d_handoff.md", total=229), _asst_text("I read all four handoffs and wrote the synthesis.")], False),
    ("G-13d 'all four handoffs', only two files have 'handoff' in their names, all four read in full -> silent "
     "(from the replay: names do not identify the documents, so the count is not judged)",
     [_prompt("synthesise"), *_read("/w/h/a_handoff.md", total=40), *_read("/w/h/b_handoff.md", total=40),
      *_read("/w/h/context.md", total=40), *_read("/w/h/sequence.md", total=40),
      _asst_text("I read all four handoffs and wrote the synthesis.")], False),
    ("G-13c 'I read all four papers' when no file matches 'paper' -> silent",
     [_prompt("synthesise"), *_read("/w/h/a_handoff.md", total=40), _asst_text("I read all four papers.")], False),
]

# (name, events, text the pause reason must contain, text it must not contain)
REASON_CASES = [
    ("G-10 scope gap computed over the session says 'in this session'",
     [_prompt("review"), *_read("/w/src/parser.rs", total=850, limit=200), _asst_text("I read the whole file.")],
     "in this session", "read in this turn has been read in full"),
]


def _reason_of(events: list[dict]) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
        tp = f.name
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"transcript_path": tp}),
                       capture_output=True, text=True)
    Path(tp).unlink(missing_ok=True)
    try:
        return json.loads(r.stdout).get("reason", "") if r.stdout.strip() else ""
    except (json.JSONDecodeError, ValueError):
        return ""


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

    for name, events, active, extra, want in ACCEPTANCE + EXTRA + [(n, e, False, None, w) for n, e, w in FIXES]:
        got = _run(events, stop_hook_active=active, extra=extra)
        ok = got == want
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  (want block={want}, got block={got})")
        if not ok:
            failures += 1

    for name, events, want_in, want_out in REASON_CASES:
        reason = _reason_of(events)
        ok = want_in in reason and want_out not in reason
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  (reason: {(reason.splitlines() or [''])[min(1, len(reason.splitlines()) - 1)] if reason else ''!r})")
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
