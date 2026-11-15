#!/usr/bin/env python3
"""Standalone tests for compare_arms.py and for the trial switch shared by the four hooks.
Run: python3 test_compare_arms.py

All transcripts here are synthetic, written in the record shapes of Claude Code 2.1.322
to 2.1.325 (field names only), plus one session in an older shape without `turnPosition`
or `origin`. Exit 0 when every case passes, 1 otherwise.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
# COMPARE_ARMS lets the same cases run against another copy of the script.
SCRIPT = Path(os.environ.get("COMPARE_ARMS") or HERE / "compare_arms.py")
REPO = HERE.parent
HOOK_FILES = {
    "claim-gate": REPO / "theory-formation-discipline" / "verification-claim-gate" / "verification_claim_gate.py",
    "plan-reconciliation": REPO / "plan-reconciliation" / "plan_reconciliation.py",
    "placeholder-disclosure": REPO / "placeholder-disclosure" / "placeholder_disclosure.py",
    "task-grounding": REPO / "task-grounding" / "task_grounding.py",
}

SALT = "trial-salt-1"
# (salt, session id, arm): the same vectors as in each hook's test_hook_trial.py.
VECTORS = [
    ("trial-salt-1", "00000000-0000-4000-8000-000000000001", "off"),
    ("trial-salt-1", "00000000-0000-4000-8000-000000000002", "off"),
    ("trial-salt-1", "00000000-0000-4000-8000-000000000003", "off"),
    ("trial-salt-1", "00000000-0000-4000-8000-000000000006", "off"),
    ("trial-salt-1", "00000000-0000-4000-8000-000000000007", "on"),
    ("trial-salt-1", "00000000-0000-4000-8000-000000000008", "on"),
    ("another salt", "00000000-0000-4000-8000-000000000003", "on"),
    ("another salt", "00000000-0000-4000-8000-000000000004", "off"),
    ("another salt", "00000000-0000-4000-8000-000000000008", "on"),
]


def sid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


# Arms under SALT: 1-6, 10, 11 off; 7, 8, 9, 12 on.
ON_A, ON_B, ON_C, ON_D = sid(7), sid(8), sid(9), sid(12)
OFF_A, OFF_B, OFF_C = sid(1), sid(2), sid(3)
MIXED, NO_TS, BEFORE = sid(4), sid(5), sid(6)

GATE_REASON = ("Send-time verification check. The final message makes a claim that this turn's tool calls "
               "do not support:\n- 'All tests pass': no test command ran in this turn.")
PLAN_REASON = "Plan check: the session plan (/tmp/x/plan.md) has open items that your final message does not mention:"
PLACEHOLDER_REASON = "Placeholder check: this turn wrote placeholder code that your final message does not mention:"
ROUTING = "Task routing (sent once per session per category; pattern-matched, so ignore any that do not apply):"


class Session:
    """Writes one synthetic transcript in the current record shapes."""

    def __init__(self, session_id: str, start: str = "2026-11-20T10:00:00", markers: bool = True):
        self.sid = session_id
        self.start = start
        self.markers = markers
        self.records: list = []
        self.n = 0
        self.prompts = 0
        self.tools = 0

    def _ts(self) -> str:
        self.n += 1
        return f"{self.start}.{self.n:03d}Z"

    def rec(self, rtype: str, **fields) -> dict:
        r = {"type": rtype, "sessionId": self.sid, "timestamp": self._ts(), "uuid": str(uuid.uuid4()), **fields}
        self.records.append(r)
        return r

    def prompt(self, text: str, kind: str = "human") -> None:
        extra = {}
        if self.markers:
            extra = {"turnPosition": {"promptIndex": self.prompts, "turnIndex": self.prompts},
                     "origin": {"kind": kind}, "turnOrigin": kind.replace("-", "_")}
        self.prompts += 1
        self.rec("user", message={"role": "user", "content": text}, **extra)

    def say(self, text: str, mid: str, out: int, **extra) -> None:
        self.rec("assistant", message={"id": mid, "role": "assistant", "model": extra.pop("model", "claude-opus-5-5"),
                                        "type": "message", "stop_reason": "end_turn",
                                        "content": [{"type": "text", "text": text}],
                                        "usage": {"input_tokens": 3, "output_tokens": out}}, **extra)

    def think_then_say(self, text: str, mid: str, out: int) -> None:
        """One API message written as two records, each with the message's usage."""
        usage = {"input_tokens": 3, "output_tokens": out}
        self.rec("assistant", message={"id": mid, "role": "assistant", "model": "claude-opus-5-5", "type": "message",
                                        "content": [{"type": "thinking", "thinking": "..."}], "usage": usage})
        self.rec("assistant", message={"id": mid, "role": "assistant", "model": "claude-opus-5-5", "type": "message",
                                        "stop_reason": "end_turn", "content": [{"type": "text", "text": text}],
                                        "usage": usage})

    def tool(self, name: str, inp: dict, mid: str, out: int, result: str | None = "ok", is_error: bool = False) -> None:
        self.tools += 1
        tid = f"toolu_{self.tools:03d}"
        self.rec("assistant", message={"id": mid, "role": "assistant", "model": "claude-opus-5-5", "type": "message",
                                        "stop_reason": "tool_use",
                                        "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}],
                                        "usage": {"input_tokens": 3, "output_tokens": out}})
        if result is not None:
            block = {"type": "tool_result", "tool_use_id": tid, "content": result}
            if is_error:
                block["is_error"] = True
            self.rec("user", message={"role": "user", "content": [block]}, toolUseResult={"stdout": result})

    def gate_block(self) -> None:
        self.rec("attachment", attachment={"type": "hook_blocking_error", "hookName": "Stop", "hookEvent": "Stop",
                                           "toolUseID": "x", "blockingError": {"blockingError": GATE_REASON,
                                                                               "command": "python3 gate.py"}})
        self.rec("user", isMeta=True, message={"role": "user", "content": "Stop hook feedback:\n" + GATE_REASON})

    def write(self, project: Path, name: str | None = None) -> Path:
        project.mkdir(parents=True, exist_ok=True)
        p = project / (name or f"{self.sid}.jsonl")
        p.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in self.records))
        return p


def build(projects: Path) -> None:
    proj = projects / "-work-proj"

    a = Session(ON_A)
    a.prompt("Please fix the off-by-one bug in the parser.")
    a.think_then_say("All tests pass.", "m1", 100)
    a.gate_block()
    a.say("Edited parser.py; the tests have not been run yet.", "m2", 20)
    a.prompt("Now optimise the tokenizer hot path please, it is the bottleneck.")
    a.rec("attachment", attachment={"type": "hook_additional_context", "hookName": "UserPromptSubmit",
                                    "hookEvent": "UserPromptSubmit", "toolUseID": "y",
                                    "content": [ROUTING + "\n- Performance work. Measure first."]})
    a.tool("Bash", {"command": "pytest tests/"}, "m3", 30, result="5 passed in 0.2s")
    a.say("All tests pass.", "m4", 10)
    a.prompt("thanks, that is all for now")
    a.say("Glad it helped.", "m5", 5)
    a.write(proj)
    sub = Session(ON_A)
    sub.think_then_say("Found three call sites.", "s1", 50)
    sub.say("Done.", "s2", 7)
    sub.write(proj / ON_A / "subagents", "agent-a1.jsonl")

    b = Session(ON_B)
    b.prompt("Carry on with the plan.")
    b.tool("Bash", {"command": "python3 -m unittest"}, "m6", 12, result="OK")
    b.say("Done. The config loader is in.", "m7", 8)
    b.rec("system", subtype="stop_hook_summary", hookCount=4, hookInfos=[{"command": "python3 plan.py"}],
          hookErrors=[], hookAdditionalContext=[PLAN_REASON + "\n- Write the migration script"],
          preventedContinuation=False, stopReason="", hasOutput=True, level="suggestion")
    b.rec("user", isMeta=True, message={"role": "user",
                                        "content": "Stop hook feedback:\n" + PLAN_REASON + "\n- Write the migration script"})
    b.say("The migration script is deferred until the schema is frozen.", "m8", 6)
    b.prompt("<task-notification>\n<task-id>t1</task-id> finished\n</task-notification>", kind="task-notification")
    b.tool("Write", {"file_path": "/w/src/lib.rs", "content": "fn f() { todo!() }"}, "m9", 9)
    b.say("Wrote the stub.", "m10", 4)
    b.rec("system", subtype="stop_hook_summary", hookCount=4, hookInfos=[], hookErrors=[],
          hookAdditionalContext=[PLACEHOLDER_REASON + "\n- src/lib.rs:1  todo!() in `f`"],
          preventedContinuation=False, stopReason="", hasOutput=True, level="suggestion")
    b.say("f in lib.rs is a stub: todo!() remains.", "m11", 3)
    b.prompt("and run the build")
    b.tool("Bash", {"command": "cargo build"}, "m12", 2, result=None)
    b.write(proj)

    c = Session(ON_C)
    c.rec("last-prompt")
    c.write(proj)

    oa = Session(OFF_A)
    oa.prompt("Fix the failing test in parser.py.")
    oa.say("All tests pass.", "m13", 40)
    # The user pastes a hook message into a prompt: still the user's text, not a firing.
    oa.prompt("Stop hook feedback:\nSend-time verification check. I saw this in another window; nothing ran here.")
    oa.say("You are right, no test ran. Plan check: the session plan is not used here.", "m14", 10)
    oa.write(proj)

    ob = Session(OFF_B)
    ob.prompt("Summarise the log for me.")
    ob.rec("assistant", message={"role": "assistant", "content": [{"type": "text", "text": "Partial."}]})
    ob.say("API Error: overloaded", "m15", 0, model="<synthetic>", isApiErrorMessage=True)
    ob.records[1:1] = ["not json", "[1]", json.dumps({"no": "type"})]
    ob.write(proj)

    oc = Session(OFF_C, markers=False)
    oc.prompt("Build the crate and tell me if it compiles.")
    oc.tool("Bash", {"command": "cargo build"}, "m16", 11, result="Finished dev profile")
    oc.say("The build passes.", "m17", 4)
    oc.prompt("<command-name>/model</command-name>")
    oc.write(proj)

    m = Session(MIXED)
    m.prompt("Hello there, please look at the parser.")
    m.say("Looked.", "m18", 1)
    m.records[-1]["sessionId"] = sid(99)
    m.write(proj)

    nt = Session(NO_TS)
    nt.prompt("Hello there, please look at the parser.")
    nt.say("Looked.", "m19", 1)
    for r in nt.records:
        del r["timestamp"]
    nt.write(proj)

    bf = Session(BEFORE, start="2026-11-10T10:00:00")
    bf.prompt("Hello there, please look at the parser.")
    bf.say("Looked.", "m20", 1)
    bf.write(proj)

    orphan = Session(ON_A)
    orphan.prompt("Hello there, please look at the parser.")
    orphan.say("Looked.", "m21", 1)
    orphan.write(proj, f"{ON_A}.orphaned-20261120-x.jsonl")

    d = Session(ON_D)
    d.prompt("Hello there, please look at the parser.")
    d.say("Looked.", "m22", 1)
    d.write(projects / "-other-proj")
    (projects / "stray-file.txt").write_text("not a project\n")


def run(projects: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), "--projects", str(projects), "--salt", SALT,
                           "--start", "2026-11-16", "--resamples", "300", *args],
                          capture_output=True, text=True, timeout=300)


FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_arm_agreement() -> None:
    try:
        ca = _load(SCRIPT, "compare_arms_under_test")
    except Exception as e:
        check("compare_arms.py loads", False, repr(e))
        return
    for salt, s, want in VECTORS:
        check(f"vector {salt!r} {s[-4:]} -> {want} (compare_arms.arm)", ca.arm(salt, s) == want)

    hooks = {}
    for name, path in HOOK_FILES.items():
        try:
            hooks[name] = _load(path, "trial_" + name.replace("-", "_"))
        except Exception as e:
            check(f"{name} loads", False, repr(e))
    have = {n: m for n, m in hooks.items() if callable(getattr(m, "trial_arm", None))}
    check("all four hooks define trial_arm", len(have) == 4, f"have {sorted(have)}")

    sources = {}
    for name, path in HOOK_FILES.items():
        tree = ast.parse(path.read_text())
        text = path.read_text()
        fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "trial_arm"), None)
        const = next((n for n in tree.body if isinstance(n, ast.Assign)
                      and any(getattr(t, "id", "") == "TRIAL_FILE" for t in n.targets)), None)
        sources[name] = (ast.get_source_segment(text, fn) if fn else None,
                         ast.get_source_segment(text, const) if const else None)
    check("trial_arm and TRIAL_FILE are word for word the same in all four hooks",
          len(set(sources.values())) == 1 and None not in next(iter(sources.values())))

    for name, path in HOOK_FILES.items():
        check(f"{name}: its own output starts with the signature compare_arms looks for",
              ca.SIGNATURES[name] in path.read_text())

    saved = {k: os.environ.get(k) for k in ("HOME", "CLAUDE_PROJECT_DIR", "HOOK_TRIAL_IGNORE")}
    with tempfile.TemporaryDirectory() as home:
        try:
            os.environ["HOME"] = home
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            os.environ.pop("HOOK_TRIAL_IGNORE", None)
            (Path(home) / ".claude").mkdir()
            (Path(home) / ".claude" / "hook-trial.json").write_text(json.dumps({"enabled": True, "salt": SALT}))
            rng = random.Random(1115)
            ids = [str(uuid.UUID(int=rng.getrandbits(128), version=4)) for _ in range(1000)]
            disagree = 0
            for s in ids:
                want = ca.arm(SALT, s)
                if any(m.trial_arm({"session_id": s}) != want for m in have.values()):
                    disagree += 1
            check("1,000 random session ids: all four hooks and compare_arms give the same arm",
                  disagree == 0 and len(have) == 4, f"{disagree} disagree")
            on = sum(1 for s in ids if ca.arm(SALT, s) == "on")
            check(f"1,000 random session ids split about evenly ({on} on, {1000 - on} off; 450-550 expected)",
                  450 <= on <= 550)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def test_analysis() -> None:
    with tempfile.TemporaryDirectory() as d:
        projects = Path(d) / "projects"
        build(projects)
        r = run(projects, "--project=-work-proj", "--json")
        try:
            out = json.loads(r.stdout)
        except ValueError:
            check("compare_arms runs and prints JSON", False, r.stderr[-500:])
            return
        check("compare_arms runs and prints JSON", r.returncode == 0)
        on, off = out["counts"]["on"], out["counts"]["off"]
        nr = out["not_read"]

        check("sessions per arm: 2 on, 3 off", on["sessions"] == 2 and off["sessions"] == 3, f"{on['sessions']} {off['sessions']}")
        check("turns per arm: 6 on, 5 off", on["turns"] == 6 and off["turns"] == 5, f"{on['turns']} {off['turns']}")
        check("output tokens counted once per message id: 209 on, 65 off",
              on["output_tokens_main"] == 209 and off["output_tokens_main"] == 65,
              f"{on['output_tokens_main']} {off['output_tokens_main']}")
        check("subagent output tokens, by message id: 57 on, 0 off",
              on["output_tokens_subagents"] == 57 and off["output_tokens_subagents"] == 0)
        check("judged turns: 5 on, 3 off", on["judged_turns"] == 5 and off["judged_turns"] == 3,
              f"{on['judged_turns']} {off['judged_turns']}")
        check("a blocked turn counts by its corrected final message: 0 unsupported on, 1 off",
              on["unsupported_final_messages"] == 0 and off["unsupported_final_messages"] == 1,
              f"{on['unsupported_final_messages']} {off['unsupported_final_messages']}")
        check("claim-gate blocks: 1 on (attachment and feedback message are one block), 0 off",
              on["claim_gate_blocks"] == 1 and off["claim_gate_blocks"] == 0)
        check("firings on: one per hook (attachment, stop-hook summary + meta message counted once)",
              on["firings"] == {h: 1 for h in HOOK_FILES}, str(on["firings"]))
        check("a signature in the user's or the model's own text is not a firing",
              off["firings"] == {h: 0 for h in HOOK_FILES} and off["sessions_with_any_firing"] == 0, str(off["firings"]))
        check("follow-up messages: 3 on (task notification not counted), 1 off",
              on["follow_up_messages"] == 3 and off["follow_up_messages"] == 1,
              f"{on['follow_up_messages']} {off['follow_up_messages']}")

        want_reasons = {
            "file skipped: name is not a session id": 1,
            "session excluded: records carry another session id": 1,
            "session excluded: no readable timestamp": 1,
            "session excluded: started before --start": 1,
            "session excluded: no turns found": 1,
            "line is not JSON": 1,
            "line is not a JSON object": 1,
            "record has no type": 1,
            "main: assistant record without message.id (usage not counted)": 1,
            "turn not judged: final message is an API error or synthetic": 1,
            "turn not judged: turn ended on a tool call (interrupted, or the transcript is cut short)": 1,
            "turn not judged: turn has no assistant text": 1,
            "user prompt judged human by rule (no origin field)": 1,
        }
        wrong = {k: (nr.get(k), v) for k, v in want_reasons.items() if nr.get(k) != v}
        check("everything not read is counted by reason", not wrong, str(wrong) + " got " + str(nr))

        m = out["metrics"]
        check("unsupported claims per judged turn: 0 on, 1/3 off, difference -1/3",
              m["unsupported_rate"]["on"] == 0 and abs(m["unsupported_rate"]["off"] - 1 / 3) < 1e-9
              and abs(m["unsupported_rate"]["difference"] + 1 / 3) < 1e-9)
        check("output tokens per turn is a ratio over sessions: 209/6 on",
              abs(m["tokens_per_turn"]["on"] - 209 / 6) < 1e-9)
        iv = m["tokens_per_turn"]["on_interval"]
        check("intervals are given with two or more sessions per arm, low <= high",
              iv is not None and iv[0] <= iv[1] and m["tokens_per_turn"]["difference_interval"] is not None)
        r2 = run(projects, "--project=-work-proj", "--json")
        check("the bootstrap is seeded: the same run gives the same output", r2.stdout == r.stdout)

        r3 = run(projects, "--json")
        try:
            all_on = json.loads(r3.stdout)["counts"]["on"]["sessions"]
        except (ValueError, KeyError):
            all_on = None
        check("without --project, sessions of every project are read (3 on)", all_on == 3, r3.stderr[-300:])

        text = run(projects, "--project=-work-proj")
        leaked = [s for s in (ON_A, ON_B, OFF_A, OFF_B, OFF_C, "All tests pass", "parser") if s in text.stdout]
        check("the text report holds no session ids and no message text", text.returncode == 0 and not leaked,
              str(leaked) + text.stderr[-300:])
        check("the text report labels follow-ups as rough and states the unit",
              "(rough)" in text.stdout and "Unit: the session" in text.stdout)

        trial = Path(d) / "hook-trial.json"
        trial.write_text(json.dumps({"enabled": True, "salt": SALT, "start": "2026-11-16"}))
        r4 = subprocess.run([sys.executable, "-I", str(SCRIPT), "--projects", str(projects), "--project=-work-proj",
                             "--trial-file", str(trial), "--resamples", "300", "--json"],
                            capture_output=True, text=True, timeout=300)
        check("--trial-file gives the same result as --salt and --start", r4.stdout == r.stdout, r4.stderr[-300:])

        # The gate given with --gate is the one used: a stand-in that flags only "Glad".
        stub = Path(d) / "stub_gate.py"
        stub.write_text("def judge(events, text=None):\n    return [('x', 'y')] if 'Glad' in (text or '') else []\n")
        r5 = run(projects, "--project=-work-proj", "--json", "--gate", str(stub))
        try:
            c5 = json.loads(r5.stdout)["counts"]
        except ValueError:
            c5 = None
        check("--gate: the given gate judges the final messages",
              c5 is not None and c5["on"]["unsupported_final_messages"] == 1
              and c5["off"]["unsupported_final_messages"] == 0, r5.stderr[-300:])

        old = Path(d) / "old_gate.py"
        old.write_text("def main():\n    return 0\n")
        r6 = run(projects, "--json", "--gate", str(old))
        check("--gate without judge() -> refused with a message, exit non-zero",
              r6.returncode != 0 and "judge" in r6.stderr and not r6.stdout.strip())

        r7 = run(projects, "--json", "--start", "16/11/2026")
        check("a malformed --start is refused", r7.returncode != 0 and "YYYY-MM-DD" in r7.stderr)


def main() -> int:
    test_arm_agreement()
    test_analysis()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} case(s) FAILED")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
