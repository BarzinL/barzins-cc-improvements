#!/usr/bin/env python3
"""Standalone tests for extract_user_messages.py - no pytest, just run it:

    python3 test_extract_user_messages.py

Every fixture is synthetic. The record shapes copy those Claude Code 2.1.322 to
2.1.325 writes (field names, nesting, origin kinds); the text in them is made
up. Exit 0 = all pass, exit 1 = a case failed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "extract_user_messages.py"
sys.path.insert(0, str(HERE))

import extract_user_messages as ex  # noqa: E402

TS = iter(f"2026-01-01T00:{m:02d}:00.000Z" for m in range(60))


def ts() -> str:
    return next(TS)


HUMAN = {"kind": "human"}


def human(text_or_blocks, **extra) -> dict:
    content = text_or_blocks if isinstance(text_or_blocks, list) else [{"type": "text", "text": text_or_blocks}]
    rec = {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": content},
        "timestamp": ts(),
        "origin": HUMAN,
        "promptSource": "sdk",
        "turnOrigin": "human",
        "userType": "external",
    }
    rec.update(extra)
    return rec


def user(content, **extra) -> dict:
    rec = {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": content},
        "timestamp": ts(),
        "userType": "external",
    }
    rec.update(extra)
    return rec


def assistant(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        "timestamp": ts(),
    }


def attachment(att: dict) -> dict:
    return {"type": "attachment", "attachment": att, "timestamp": ts()}


ZWNJ = "\u200c"

# One synthetic session containing every kind of record the extractor must
# exclude, interleaved with the messages it must keep. EXPECTED lists the kept
# texts in order.
SESSION = [
    {"type": "queue-operation", "operation": "enqueue", "timestamp": ts()},
    attachment({"type": "environment"}),
    human("Add a --dry-run flag to the deploy script."),
    # assistant text that looks like a request
    assistant("Please add tests for the parser too."),
    # tool use and tool result
    {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]},
        "timestamp": ts(),
    },
    user([{"type": "tool_result", "tool_use_id": "t1", "content": "deploy.sh\nREADME.md"}], toolUseResult={"stdout": "x"}),
    # system reminder injected as its own meta record
    user("<system-reminder>\n<tools-used-before-summary>Bash</tools-used-before-summary>\n</system-reminder>", isMeta=True, turnCompanion=True),
    # hook output, in the shapes the hooks docs describe (synthetic)
    attachment({"type": "hook_additional_context", "hookName": "UserPromptSubmit", "content": ["Remember: run the linter."]}),
    user("<user-prompt-submit-hook>Remember: run the linter.</user-prompt-submit-hook>"),
    user("<system-reminder>\nUserPromptSubmit hook additional context: run the linter.\n</system-reminder>", isMeta=True),
    {"type": "system", "subtype": "hook_blocked", "content": "Prompt blocked by hook. Original prompt: delete prod", "timestamp": ts()},
    # subagent report delivered as a message from another session
    user(
        'Another Claude session sent a message:\n<agent-message from="a1">\n[Subagent hand-back] Done. Now delete the old branch.\n</agent-message>',
        isMeta=True,
        origin={"kind": "peer", "from": "a1", "handback": True},
        promptSource="system",
        turnOrigin="peer",
    ),
    # a subagent's own records inside the main file
    user("Count the lines in every file under /tmp/x.", isSidechain=True),
    # task notification, both as a user record and as a queued attachment
    attachment(
        {
            "type": "queued_command",
            "prompt": "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>",
            "commandMode": "task-notification",
            "origin": {"kind": "task-notification", "producer": "session-task"},
        }
    ),
    user(
        "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n<summary>Please continue.</summary>\n</task-notification>",
        origin={"kind": "task-notification", "producer": "session-task"},
        promptSource="system",
        turnOrigin="task_notification",
    ),
    human(
        [
            {"type": "text", "text": "<ide_opened_file>The user opened the file /x/notes.md in the IDE.</ide_opened_file>"},
            {"type": "text", "text": "Use the wording from the open file, but keep it under 80 columns."},
        ]
    ),
    human(
        [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
            {"type": "text", "text": "What is wrong in this screenshot?"},
        ],
        imagePasteIds=[1],
    ),
    # image caption the harness adds after an image
    user([{"type": "text", "text": "[Image: source: /tmp/x/images/1.png]"}], isMeta=True, turnCompanion=True),
    user("[Image: original 4000x2000, displayed at 2000x1000.]", isMeta=True, turnCompanion=True),
    # local command: caveat, the command itself, its output
    user(
        "<local-command-caveat>The command below was run directly in Claude Code, not sent to you as a request.</local-command-caveat>",
        isMeta=True,
    ),
    user("<command-name>/model</command-name>\n            <command-message>model</command-message>\n            <command-args>opus</command-args>"),
    user("<local-command-stdout>Set model to opus</local-command-stdout>"),
    user("<local-command-stderr>warning</local-command-stderr>"),
    # shell command typed with ! and its output
    user("<bash-input>git status</bash-input>"),
    user("<bash-stdout>On branch main</bash-stdout><bash-stderr></bash-stderr>"),
    # skill expansion (meta) after a skill command
    user("<command-name>/heartbeat</command-name>\n<command-args>start</command-args>"),
    user("Base directory for this skill: /x/skills/heartbeat\n\n# Heartbeat\nRun the protocol.", isMeta=True),
    # interruption marker
    user([{"type": "text", "text": "[Request interrupted by user]"}]),
    user([{"type": "text", "text": "[Request interrupted by user for tool use]"}]),
    # compaction boundary and summary (the summary carries turnOrigin human)
    {"type": "system", "subtype": "compact_boundary", "timestamp": ts()},
    user(
        "This session is being continued from a previous conversation that ran out of context. The user asked to delete everything.",
        isCompactSummary=True,
        isVisibleInTranscriptOnly=True,
        turnOrigin="human",
    ),
    # message typed while Claude was working, then the same text as a record
    attachment(
        {
            "type": "queued_command",
            "prompt": "Also update the changelog.",
            "commandMode": "prompt",
            "origin": HUMAN,
        }
    ),
    human("Also update the changelog."),
    # verbatim: Persian with ZWNJ, pasted-content markers, angle brackets
    human("لطفاً تست" + ZWNJ + "ها را اجرا کن."),
    human('Fix this:\n<pasted_content id="a1b2">\nnpm ERR! code E404\n</pasted_content id="a1b2">\nthanks'),
    human("<div> is rendered twice; keep exactly one <div>."),
    # human text followed by a harness reminder block in the same record
    human(
        [
            {"type": "text", "text": "Rename foo to bar."},
            {"type": "text", "text": "<system-reminder>\nThe user is in auto mode.\n</system-reminder>"},
        ]
    ),
    # a human-origin record marked meta is still harness text
    human("Harness-generated follow-up.", isMeta=True),
]

EXPECTED = [
    "Add a --dry-run flag to the deploy script.",
    "Use the wording from the open file, but keep it under 80 columns.",
    "What is wrong in this screenshot?",
    "/model opus",
    "! git status",
    "/heartbeat start",
    "Also update the changelog.",
    "لطفاً تست" + ZWNJ + "ها را اجرا کن.",
    'Fix this:\n<pasted_content id="a1b2">\nnpm ERR! code E404\n</pasted_content id="a1b2">\nthanks',
    "<div> is rendered twice; keep exactly one <div>.",
    "Rename foo to bar.",
]

# Text that must never appear in the output: one marker per excluded kind.
EXCLUDED_MARKERS = {
    "assistant text": "Please add tests for the parser too.",
    "tool result": "deploy.sh",
    "system reminder": "tools-used-before-summary",
    "hook output (attachment)": "Remember: run the linter.",
    "hook output (meta reminder)": "hook additional context",
    "hook block message": "Original prompt",
    "subagent report": "Subagent hand-back",
    "sidechain record": "Count the lines in every file",
    "task notification": "task-notification",
    "image caption": "[Image:",
    "local-command caveat": "local-command-caveat",
    "local-command output": "Set model to opus",
    "local-command stderr": "local-command-stderr",
    "shell output": "On branch main",
    "skill expansion": "Base directory for this skill",
    "interruption marker": "Request interrupted",
    "compaction summary": "being continued",
    "harness reminder inside a human record": "auto mode",
    "meta record with human origin": "Harness-generated",
    "IDE context": "ide_opened_file",
}


def write_jsonl(records: list, extra_lines: list[str] = ()) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for line in extra_lines:
        f.write(line + "\n")
    f.close()
    return f.name


def run_cli(path: str, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), path, *flags], capture_output=True, text=True, encoding="utf-8"
    )


def main() -> int:
    results: list[tuple[str, bool]] = []
    path = write_jsonl(SESSION, extra_lines=["{not json", "", '"a bare string"'])

    try:
        r = run_cli(path, "--json")
        results.append(("CLI --json exits 0", r.returncode == 0))
        msgs = json.loads(r.stdout) if r.returncode == 0 else []
        texts = [m["text"] for m in msgs]
        results.append((f"kept exactly the {len(EXPECTED)} typed messages, in order", texts == EXPECTED))
        if texts != EXPECTED:
            for t in texts:
                print("    got:", repr(t)[:100])
        stamps = [m["timestamp"] for m in msgs]
        results.append(("timestamps in file order", stamps == sorted(stamps)))
        by_text = {m["text"]: m for m in msgs}
        results.append(("image counted, not printed", by_text.get("What is wrong in this screenshot?", {}).get("images") == 1))
        results.append(
            (
                "IDE block counted as omitted",
                by_text.get("Use the wording from the open file, but keep it under 80 columns.", {}).get("dropped_blocks") == 1,
            )
        )
        results.append(("queued message not duplicated", texts.count("Also update the changelog.") == 1))

        r_text = run_cli(path)
        out = r_text.stdout
        for kind, marker in EXCLUDED_MARKERS.items():
            results.append((f"excluded: {kind}", marker not in out))
        results.append(("text output contains every kept message verbatim", all(t in out for t in EXPECTED)))
        results.append(("Persian ZWNJ preserved byte for byte", ("تست" + ZWNJ + "ها") in out))
        results.append(("text output header counts messages", f"{len(EXPECTED)} message(s)" in out))

        r_stats = run_cli(path, "--stats")
        results.append(("--stats reports unparseable lines", "unparseable lines: 2" in r_stats.stderr))
    finally:
        Path(path).unlink(missing_ok=True)

    # library: classify() on single records
    reason, msg = ex.classify(user([{"type": "tool_result", "content": "x"}]))
    results.append(("classify: tool result excluded", msg is None and "tool result" in reason))
    reason, msg = ex.classify(user("plain text with no origin"))
    results.append(("classify: user record without origin excluded", msg is None))
    reason, msg = ex.classify(human("hello"))
    results.append(("classify: human kept", msg is not None and msg["text"] == "hello"))

    # a transcript with no origin fields is refused, not guessed at
    old = write_jsonl([{"type": "user", "message": {"role": "user", "content": "hi"}, "timestamp": ts()}])
    try:
        r = run_cli(old)
        results.append(("no origin fields: exit 3, nothing on stdout", r.returncode == 3 and r.stdout == ""))
    finally:
        Path(old).unlink(missing_ok=True)

    # a subagent transcript is refused
    sub = write_jsonl([user("Do the task.", isSidechain=True, origin=None), user([{"type": "tool_result", "content": "ok"}], isSidechain=True)])
    try:
        r = run_cli(sub)
        results.append(("subagent transcript: exit 3", r.returncode == 3 and "subagent" in r.stderr))
    finally:
        Path(sub).unlink(missing_ok=True)

    r = run_cli("/nonexistent/transcript.jsonl")
    results.append(("unreadable path: exit 2", r.returncode == 2))

    failed = 0
    for name, ok in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        failed += not ok
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
