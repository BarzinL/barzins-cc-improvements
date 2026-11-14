#!/usr/bin/env python3
"""Standalone tests for placeholder_disclosure.py - no pytest, just run it:

    python3 test_placeholder_disclosure.py

Each case builds a synthetic project directory, applies a turn's Write/Edit calls to
it the way the harness would, records a synthetic transcript of that turn (tool
calls and tool results, in the shape Claude Code writes them), and runs the hook as
a subprocess with a Stop payload. Cases marked [plan] are the acceptance cases from
the plan; the others were added. Exit 0 when every case passes, 1 otherwise.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "placeholder_disclosure.py"

LIB_RS = """pub struct Header {
    pub name: String,
}

pub fn parse_header(input: &str) -> Header {
    todo!()
}
"""
LIB_RS_TODO_LINE = 6


class Turn:
    """Applies Write/Edit calls to a project dir and records them as transcript events."""

    def __init__(self, project: Path, prompt: str = "please build the parser"):
        self.project = project
        self.events: list[dict] = [{"type": "user", "promptSource": "sdk",
                                    "message": {"role": "user",
                                                "content": [{"type": "text", "text": prompt}]}}]
        self.n = 0

    def _ids(self) -> str:
        self.n += 1
        return f"toolu_{self.n:03d}"

    def _emit(self, name: str, inp: dict, result: dict | None, is_error: bool = False) -> None:
        tid = self._ids()
        self.events.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        block = {"type": "tool_result", "tool_use_id": tid, "content": "ok"}
        if is_error:
            block["is_error"] = True
            block["content"] = "Error: synthetic failure"
        ev = {"type": "user", "message": {"role": "user", "content": [block]}}
        if result is not None:
            ev["toolUseResult"] = result
        self.events.append(ev)

    def write(self, rel: str, content: str, record_result: bool = True) -> None:
        p = self.project / rel
        before = p.read_text() if p.exists() else None
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        result = {"type": "create" if before is None else "update", "filePath": str(p),
                  "content": content, "structuredPatch": [], "originalFile": before,
                  "userModified": False}
        self._emit("Write", {"file_path": str(p), "content": content},
                   result if record_result else None)

    def edit(self, rel: str, old: str, new: str, record_result: bool = True) -> None:
        p = self.project / rel
        before = p.read_text()
        assert before.count(old) == 1, f"fixture error: {old!r} not unique in {rel}"
        p.write_text(before.replace(old, new))
        result = {"filePath": str(p), "oldString": old, "newString": new, "originalFile": before,
                  "structuredPatch": [], "userModified": False, "replaceAll": False}
        self._emit("Edit", {"file_path": str(p), "old_string": old, "new_string": new,
                            "replace_all": False}, result if record_result else None)

    def failed_write(self, rel: str, content: str) -> None:
        p = self.project / rel
        self._emit("Write", {"file_path": str(p), "content": content}, None, is_error=True)

    def bash(self, cmd: str) -> None:
        self._emit("Bash", {"command": cmd}, {"stdout": "", "stderr": "", "interrupted": False})

    def meta(self, text: str) -> None:
        self.events.append({"type": "user", "isMeta": True, "message": {"role": "user", "content": text}})

    def say(self, text: str) -> None:
        self.events.append({"type": "assistant", "message": {"role": "assistant",
                                                             "content": [{"type": "text", "text": text}]}})

    def new_prompt(self, text: str) -> None:
        self.events.append({"type": "user", "message": {"role": "user",
                                                        "content": [{"type": "text", "text": text}]}})

    def run(self, message: str | None, stop_hook_active: bool = False) -> tuple[bool, str, int]:
        tp = self.project.parent / "session.jsonl"
        tp.write_text("".join(json.dumps(e) + "\n" for e in self.events))
        payload = {"session_id": "test-session", "transcript_path": str(tp), "cwd": str(self.project),
                   "hook_event_name": "Stop", "stop_hook_active": stop_hook_active}
        if message is not None:
            payload["last_assistant_message"] = message
        return _parse(run_hook(json.dumps(payload)))


def run_hook(stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(HOOK)], input=stdin,
                          capture_output=True, text=True, timeout=30)


def _parse(r: subprocess.CompletedProcess) -> tuple[bool, str, int]:
    out = r.stdout.strip()
    if not out:
        return False, "", r.returncode
    try:
        obj = json.loads(out)
    except ValueError:
        return False, out, r.returncode
    ctx = (obj.get("hookSpecificOutput") or {}).get("additionalContext") or obj.get("reason") or ""
    return bool(ctx) or obj.get("decision") == "block", ctx, r.returncode


FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def project() -> tuple[tempfile.TemporaryDirectory, Path]:
    td = tempfile.TemporaryDirectory()
    proj = Path(td.name) / "proj"
    proj.mkdir()
    return td, proj


def main() -> int:
    # ---------------------------------------------------------- plan's cases --
    td, proj = project()
    t = Turn(proj)
    t.write("src/lib.rs", LIB_RS)
    fired, ctx, _ = t.run("Implemented the header parser in src/lib.rs. Done.")
    check("[plan] todo!() written into src/lib.rs; message says implemented -> fires with file and line",
          fired and f"src/lib.rs:{LIB_RS_TODO_LINE}" in ctx, ctx)
    fired2, ctx2, _ = t.run("Implemented the header parser in src/lib.rs. Done.", stop_hook_active=True)
    check("... and only once: the follow-up stop (stop_hook_active) is silent", not fired2, ctx2)

    fired, ctx, _ = t.run("Added the Header type. `parse_header` is still a stub.")
    check("[plan] same write; message says `parse_header` is still a stub -> silent", not fired, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("tests/test_parser.py",
            'from parser import status\n\n\ndef test_todo_status():\n'
            '    assert status("TODO") == "open"\n    # TODO-like data below\n'
            '    assert status("FIXME") == "open"\n')
    fired, ctx, _ = t.run("Added a test for the status parser. All done.")
    check("[plan] turn writes a test containing the string TODO as data -> silent", not fired, ctx)
    td.cleanup()

    original = ("def load(path):\n    # TODO: support gzip\n    with open(path) as f:\n"
                "        return f.read()\n\n\ndef size(path):\n    return 0\n")
    for record in (True, False):
        td, proj = project()
        (proj / "io_utils.py").write_text(original)
        t = Turn(proj)
        t.edit("io_utils.py", "def size(path):\n    return 0\n",
               "def size(path):\n    import os\n    return os.path.getsize(path)\n", record_result=record)
        fired, ctx, _ = t.run("Implemented size(). Done.")
        label = "with recorded originalFile" if record else "no tool result recorded"
        check(f"[plan] TODO already in the file before the turn, untouched -> silent ({label})",
              not fired, ctx)
        td.cleanup()

    td, proj = project()
    (proj / "store.py").write_text("import json\n")
    t = Turn(proj)
    t.write("store.py", "import json\n# TODO: support yaml\n", record_result=True)
    fired, ctx, _ = t.run("Store module updated. Done.")
    check("Write overwrite that adds a TODO comment -> fires with line", fired and "store.py:2" in ctx, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("shapes.py",
            "from abc import ABC, abstractmethod\n\n\nclass Shape(ABC):\n    @abstractmethod\n"
            "    def area(self) -> float:\n        raise NotImplementedError\n")
    fired, ctx, _ = t.run("Added the Shape base class. Done.")
    check("[plan] abstract method body `raise NotImplementedError` under @abstractmethod -> silent",
          not fired, ctx)
    td.cleanup()

    # -------------------------------------------------------- added cases --
    td, proj = project()
    t = Turn(proj)
    t.write("convert.py", "def to_celsius(f):\n    raise NotImplementedError\n")
    fired, ctx, _ = t.run("Added the converter. Done.")
    check("plain function `raise NotImplementedError` -> fires", fired and "convert.py:2" in ctx, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("api.py", 'def fetch(url):\n    """Fetch a URL."""\n    pass\n\n\ndef post(url, body):\n    ...\n')
    fired, ctx, _ = t.run("The client is complete.")
    check("function bodies that are only pass (after a docstring) and only ... -> fires, both listed",
          fired and "api.py:3" in ctx and "api.py:7" in ctx, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("types_.py",
            "from typing import Protocol, overload\n\n\nclass Reader(Protocol):\n"
            "    def read(self) -> bytes: ...\n\n\n@overload\ndef f(x: int) -> int: ...\n"
            "@overload\ndef f(x: str) -> str: ...\ndef f(x):\n    return x\n\n\n"
            "class Empty(Exception):\n    pass\n\n\ntry:\n    import yaml\nexcept ImportError:\n    pass\n")
    fired, ctx, _ = t.run("Added the types. Done.")
    check("Protocol method, @overload stubs, empty exception class, except: pass -> silent",
          not fired, ctx)
    td.cleanup()

    td, proj = project()
    (proj / "app.py").write_text("def main():\n    return 1\n")
    t = Turn(proj)
    t.edit("app.py", "def main():\n    return 1\n",
           "def main():\n    # FIXME: read the port from config\n    return 1\n")
    fired, ctx, _ = t.run("Updated main. Done.")
    check("FIXME comment added by an Edit -> fires with line", fired and "app.py:2" in ctx, ctx)
    fired, ctx, _ = t.run("Updated main; there is a FIXME left in main for the port.")
    check("... disclosed by naming the function and the FIXME -> silent", not fired, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("status.py", 'STATES = ["TODO", "DOING", "DONE"]\nLABEL = "FIXME later"\n')
    fired, ctx, _ = t.run("Added the states. Done.")
    check("TODO/FIXME inside string data in a non-test code file -> silent", not fired, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("README.md", "# Parser\n\nTODO: write usage notes\n")
    t.write("notes.txt", "todo!() FIXME\n")
    fired, ctx, _ = t.run("Wrote the README. Done.")
    check("TODO in non-code files (README.md, notes.txt) -> silent", not fired, ctx)
    td.cleanup()

    td, proj = project()
    (proj / "src").mkdir()
    (proj / "src" / "lib.rs").write_text(LIB_RS)
    t = Turn(proj)
    t.bash("cargo build")
    fired, ctx, _ = t.run("Build is done.")
    check("placeholder in a file the turn did not write -> silent", not fired, ctx)
    t.failed_write("src/lib.rs", LIB_RS)
    fired, ctx, _ = t.run("Build is done.")
    check("Write call that returned an error is ignored -> silent", not fired, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("src/lib.rs", LIB_RS)
    t.say("Wrote a skeleton; `parse_header` is a stub.")
    t.new_prompt("now add a README")
    t.write("README.md", "# lib\n")
    fired, ctx, _ = t.run("Added the README. Done.")
    check("placeholder written in an earlier turn, not this one -> silent", not fired, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("src/lib.rs", LIB_RS)
    fired, ctx, _ = t.run("Done. lib.rs still has a todo!() where the parsing goes.")
    check("disclosed by file name and the word todo -> silent", not fired, ctx)
    fired, ctx, _ = t.run("Implemented parse_header in lib.rs.")
    check("names the function and file but no disclosure word -> fires", fired, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("src/lib.rs", "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n#[cfg(test)]\n"
                          "mod tests {\n    #[test]\n    fn later() {\n        todo!()\n    }\n}\n")
    fired, ctx, _ = t.run("Added add(). Done.")
    check("todo!() inside the inline #[cfg(test)] module -> silent", not fired, ctx)
    td.cleanup()

    td, proj = project()
    (proj / "lib").mkdir()
    (proj / "lib" / "a.js").write_text("export function one() {\n  return 1;\n}\n")
    t = Turn(proj)
    t.edit("lib/a.js", "export function one() {\n  return 1;\n}\n",
           "export function zero() {\n  return 0;\n}\n\nexport function one() {\n  return 1;\n}\n")
    t.edit("lib/a.js", "export function one() {\n  return 1;\n}\n",
           "export function one() {\n  return 1;\n}\n\nexport function two() {\n"
           "  throw new Error('Not implemented');\n}\n")
    fired, ctx, _ = t.run("Added zero() and two(). Done.")
    check("JS not-implemented throw after two Edits -> fires with the final line number and function",
          fired and "lib/a.js:10" in ctx and "`two`" in ctx, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("src/lib.rs", LIB_RS)
    t.say("Done: Header added; `parse_header` is still a stub.")
    fired, ctx, _ = t.run(None)
    check("no last_assistant_message; disclosure read from the transcript -> silent", not fired, ctx)
    td.cleanup()

    td, proj = project()
    t = Turn(proj)
    t.write("src/lib.rs", LIB_RS)
    t.meta("synthetic harness note")
    t.say("Done.")
    fired, ctx, _ = t.run("Done.")
    check("meta message mid-turn does not hide the turn's writes -> fires", fired, ctx)
    td.cleanup()

    td, proj = project()
    (proj / "jobs.py").write_text("def run():\n    # TODO: retry on failure\n    return 1\n")
    t = Turn(proj)
    t.write("jobs.py", "def run():\n    # TODO: retry on failure\n    return 2\n")
    fired, ctx, _ = t.run("Changed the return value. Done.")
    check("Write overwrites a file whose TODO line is unchanged -> silent", not fired, ctx)
    td.cleanup()

    # ---------------------------------------------------------- fail-open --
    for label, stdin in [
        ("non-JSON stdin", "not json at all"),
        ("JSON that is not an object", '"a string"'),
        ("empty stdin", ""),
        ("transcript_path missing on disk", json.dumps({"transcript_path": "/nonexistent/t.jsonl"})),
        ("transcript_path is a number", json.dumps({"transcript_path": 5})),
    ]:
        r = run_hook(stdin)
        check(f"fail-open: {label} -> exit 0, no output",
              r.returncode == 0 and not r.stdout.strip() and not r.stderr.strip(),
              f"rc={r.returncode} out={r.stdout!r} err={r.stderr[-200:]!r}")

    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        tp.write_text('{"type": "assistant", "message": {"content": [{"type": "tool_use", '
                      '"name": "Write", "input": {"file_path": ["not", "a", "string"]}}]}}\n'
                      "garbage line\n[1,2]\n")
        r = run_hook(json.dumps({"transcript_path": str(tp), "cwd": tmp}))
        check("fail-open: malformed transcript lines and inputs -> exit 0, no output",
              r.returncode == 0 and not r.stdout.strip())

    print()
    if FAILURES:
        print(f"{len(FAILURES)} case(s) FAILED")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
