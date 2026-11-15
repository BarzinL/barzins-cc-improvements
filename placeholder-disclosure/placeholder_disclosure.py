#!/usr/bin/env python3
"""Claude Code Stop hook: placeholder code written this turn must be disclosed.

When the turn wrote placeholder code into a code file (todo!(), unimplemented!(),
raise NotImplementedError, a function whose body is only `pass` or `...`, a TODO or
FIXME comment, a "not implemented" throw or panic) and the final message does not
mention it, the turn is paused once with the file and line of each placeholder.

A placeholder counts as disclosed when the final message uses a disclosure word
(stub, placeholder, TODO, not implemented, unfinished, ...) and names the function
it is in or the file it is in. Test files, non-code files and files the turn did
not write through Write or Edit are ignored. Only lines this turn added count: the
file's content before the turn is taken from the first Write/Edit result of the
turn (`originalFile`), and the current content from disk.

Advisory, loop-safe (`stop_hook_active`), silent when it passes, fails open on any
error. An optional trial file can switch it off in a random half of sessions, so its
effect can be measured (`trial_arm`; hook-trial/ in the repository). Python standard
library only. Install: see README.md.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import io
import json
import os
import re
import sys
import tokenize
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path, PurePath

MAX_LISTED = 20

SLASH_COMMENT = {".rs", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".js", ".jsx",
                 ".mjs", ".cjs", ".ts", ".tsx", ".go", ".java", ".kt", ".kts", ".swift",
                 ".cs", ".scala", ".dart", ".zig", ".php", ".m", ".mm", ".v", ".sol"}
HASH_COMMENT = {".py", ".sh", ".bash", ".zsh", ".fish", ".rb", ".pl", ".r", ".jl", ".ex",
                ".exs", ".nim", ".cr", ".ps1", ".php", ".tcl"}
DASH_COMMENT = {".lua", ".sql", ".hs", ".elm", ".ada", ".adb"}
CODE_EXTS = SLASH_COMMENT | HASH_COMMENT | DASH_COMMENT

TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testdata", "test_data",
             "fixtures", "testing", "e2e"}
_TEST_NAME = re.compile(
    r"^(test_.*\.py|.*_test\.(py|go|rs|rb|exs|cc|cpp)|conftest\.py|"
    r".*\.(test|spec)\.[a-z]+|.*_spec\.rb|.*Tests?\.(java|kt|cs|swift|scala))$"
)

_COMMENT_MARK = {
    "slash": re.compile(r"//|/\*|^\s*\*"),
    "hash": re.compile(r"#"),
    "dash": re.compile(r"--"),
}
_TODO = re.compile(r"\b(TODO|FIXME)\b")
_RUST_MACRO = re.compile(r"\b(todo|unimplemented)!\s*[\(\[\{]")
_KOTLIN_TODO = re.compile(r"\bTODO\s*\(")
_NOT_IMPL_THROW = re.compile(
    r"\b(?:throw|panic!?|raise|abort)\b.*\bnot\s+(?:yet\s+)?implemented\b", re.IGNORECASE)
_PY_NOT_IMPL = re.compile(r"\braise\s+NotImplementedError\b")
_RUST_TEST_MOD = re.compile(r"^\s*#\[cfg\(test\)\]")

_FUNC_PATTERNS = [
    re.compile(r"\bfn\s+(\w+)"),
    re.compile(r"\bdef\s+(\w+)"),
    re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?(\w+)"),
    re.compile(r"\bfunction\s*\*?\s*(\w+)"),
    re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"),
    re.compile(r"^\s*(?:[\w<>\[\],:*&?]+\s+)+(\w+)\s*\([^;]*\)\s*(?:const\s*)?"
               r"(?:throws\s+[\w.,\s]+)?\{?\s*$"),
]
_NOT_FUNC = {"if", "for", "while", "switch", "return", "catch", "else", "new", "match",
             "elif", "with", "sizeof", "typeof", "await", "yield", "throw", "delete"}

_DISCLOSE = re.compile(
    r"\b(stub(?:s|bed)?|placeholders?|todos?|fixmes?|unimplemented|"
    r"not (?:yet )?(?:implemented|done|written|filled in|finished)|notimplementederror|"
    r"unfinished|incomplete|skeleton|to be (?:written|implemented|done|filled in)|"
    r"still needs?|remains? to be|left (?:empty|blank|unimplemented|as (?:a )?\w+)|blocked)\b",
    re.IGNORECASE,
)

_ABSTRACT_DECORATORS = {"abstractmethod", "abstractproperty", "abstractclassmethod",
                        "abstractstaticmethod", "overload"}


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


def _blocks(e: dict) -> list:
    msg = e.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def _is_real_user_turn(e: dict) -> bool:
    """A prompt from the user, not a tool result or an injected meta message."""
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


def _final_text_from_transcript(turn: list[dict]) -> str:
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


def collect_writes(turn: list[dict]) -> list[dict]:
    """Write/Edit/MultiEdit calls of the turn that did not fail, in order.

    Each entry: {"path", "added": [str], "removed": [str], "result": dict | None}.
    """
    results: dict[str, dict | None] = {}
    failed: set[str] = set()
    for e in turn:
        if e.get("type") != "user":
            continue
        for b in _blocks(e):
            if isinstance(b, dict) and b.get("type") == "tool_result":
                tid = b.get("tool_use_id")
                if not isinstance(tid, str):
                    continue
                if b.get("is_error"):
                    failed.add(tid)
                r = e.get("toolUseResult")
                results[tid] = r if isinstance(r, dict) else None

    writes: list[dict] = []
    for e in turn:
        if e.get("type") != "assistant":
            continue
        for b in _blocks(e):
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            name = b.get("name")
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            fp = inp.get("file_path")
            if name not in ("Write", "Edit", "MultiEdit") or not isinstance(fp, str) or not fp:
                continue
            tid = b.get("id")
            if tid in failed:
                continue
            added: list[str] = []
            removed: list[str] = []
            if name == "Write":
                added.append(str(inp.get("content", "")))
            elif name == "Edit":
                added.append(str(inp.get("new_string", "")))
                removed.append(str(inp.get("old_string", "")))
            else:
                for ed in inp.get("edits") or []:
                    if isinstance(ed, dict):
                        added.append(str(ed.get("new_string", "")))
                        removed.append(str(ed.get("old_string", "")))
            writes.append({"path": fp, "tool": name, "added": added, "removed": removed,
                           "result": results.get(tid) if isinstance(tid, str) else None})
    return writes


def _content_before_turn(first: dict) -> str | None:
    """The file's content before the turn's first write to it, when recorded."""
    r = first.get("result")
    if not isinstance(r, dict):
        return None
    if first["tool"] == "Write" and r.get("type") == "create":
        return ""
    orig = r.get("originalFile")
    return orig if isinstance(orig, str) else None


# --------------------------------------------------------------------- files --
def is_test_path(path: str) -> bool:
    p = PurePath(path)
    if any(part.lower() in TEST_DIRS for part in p.parts[:-1]):
        return True
    return bool(_TEST_NAME.match(p.name))


def is_code_path(path: str) -> bool:
    return PurePath(path).suffix.lower() in CODE_EXTS


# -------------------------------------------------------------- placeholders --
def _enclosing_name(lines: list[str], idx: int) -> str:
    for j in range(idx, max(-1, idx - 300), -1):
        for rx in _FUNC_PATTERNS:
            m = rx.search(lines[j])
            if m and m.group(1) not in _NOT_FUNC:
                return m.group(1)
    return ""


def _python_placeholders(src: str) -> list[tuple[int, str, str]] | None:
    """(line, what, function) for a Python source, or None if it does not parse."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    hits: list[tuple[int, str, str]] = []
    spans: list[tuple[int, int, str]] = []

    def deco_name(d: ast.expr) -> str:
        if isinstance(d, ast.Call):
            d = d.func
        if isinstance(d, ast.Attribute):
            return d.attr
        if isinstance(d, ast.Name):
            return d.id
        return ""

    def is_protocol(cls: ast.ClassDef) -> bool:
        return any(deco_name(b) == "Protocol" or (isinstance(b, ast.Subscript) and deco_name(b.value) == "Protocol")
                   for b in cls.bases)

    def is_not_impl(exc: ast.expr | None) -> bool:
        if isinstance(exc, ast.Call):
            exc = exc.func
        return deco_name(exc) == "NotImplementedError" if exc is not None else False

    def visit(node: ast.AST, func: str, exempt: bool, in_protocol: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, func, exempt, is_protocol(child))
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                ex = in_protocol or any(deco_name(d) in _ABSTRACT_DECORATORS for d in child.decorator_list)
                spans.append((child.lineno, getattr(child, "end_lineno", child.lineno) or child.lineno, child.name))
                body = list(child.body)
                if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    body = body[1:]
                if not ex and len(body) == 1:
                    s = body[0]
                    if isinstance(s, ast.Pass):
                        hits.append((s.lineno, "function body is only `pass`", child.name))
                    elif (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                          and s.value.value is Ellipsis):
                        hits.append((s.lineno, "function body is only `...`", child.name))
                visit(child, child.name, ex, False)
            else:
                if isinstance(child, ast.Raise) and is_not_impl(child.exc) and not exempt:
                    hits.append((child.lineno, "raise NotImplementedError", func))
                visit(child, func, exempt, in_protocol)

    visit(tree, "", False, False)

    def name_at(line: int) -> str:
        best = ""
        best_start = -1
        for start, end, name in spans:
            if start <= line <= end and start > best_start:
                best, best_start = name, start
        return best

    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                m = _TODO.search(tok.string)
                if m:
                    hits.append((tok.start[0], f"{m.group(1)} comment", name_at(tok.start[0])))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return hits


def _generic_placeholders(src: str, suffix: str) -> list[tuple[int, str, str]]:
    lines = src.splitlines()
    family = ("slash" if suffix in SLASH_COMMENT else "hash" if suffix in HASH_COMMENT else "dash")
    mark = _COMMENT_MARK[family]
    hits: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        if suffix == ".rs" and _RUST_TEST_MOD.match(line):
            break  # the rest of the file is the inline test module
        what = ""
        m = _RUST_MACRO.search(line) if suffix == ".rs" else None
        if m:
            what = f"{m.group(1)}!()"
        elif suffix in (".kt", ".kts") and _KOTLIN_TODO.search(line):
            what = "TODO()"
        elif _NOT_IMPL_THROW.search(line):
            what = "not-implemented error"
        elif suffix == ".py" and _PY_NOT_IMPL.search(line):
            what = "raise NotImplementedError"
        else:
            t = _TODO.search(line)
            c = mark.search(line)
            if t and c and c.start() <= t.start():
                what = f"{t.group(1)} comment"
        if what:
            hits.append((i + 1, what, _enclosing_name(lines, i)))
    return hits


def find_placeholders(src: str, suffix: str) -> list[tuple[int, str, str]]:
    if suffix == ".py":
        hits = _python_placeholders(src)
        if hits is not None:
            lines = src.splitlines()
            for i, line in enumerate(lines):  # not-implemented throws ast does not model
                if _NOT_IMPL_THROW.search(line) and not _PY_NOT_IMPL.search(line):
                    hits.append((i + 1, "not-implemented error", ""))
            return sorted(set(hits))
    return _generic_placeholders(src, suffix)


def new_placeholders(post: str, pre: str | None, added: list[str], removed: list[str],
                     suffix: str) -> list[tuple[int, str, str, str]]:
    """Placeholders on lines this turn added: (line, what, function, line_text)."""
    lines = post.splitlines()
    hits = find_placeholders(post, suffix)
    out: list[tuple[int, str, str, str]] = []
    if pre is not None:
        sm = difflib.SequenceMatcher(None, pre.splitlines(), lines, autojunk=False)
        added_lines: set[int] = set()
        for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
            if tag in ("insert", "replace"):
                added_lines.update(range(j1 + 1, j2 + 1))
        for ln, what, fn in hits:
            if ln in added_lines:
                out.append((ln, what, fn, lines[ln - 1].strip()))
        return out
    # No record of the content before the turn: count added minus removed fragment lines.
    budget: Counter[str] = Counter()
    for frag in added:
        budget.update(s.strip() for s in frag.splitlines())
    for frag in removed:
        budget.subtract(s.strip() for s in frag.splitlines())
    for ln, what, fn in hits:
        text = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
        if budget[text] > 0:
            budget[text] -= 1
            out.append((ln, what, fn, text))
    return out


# ---------------------------------------------------------------- disclosure --
def _mentions(message: str, token: str) -> bool:
    if len(token) < 3:
        return False
    return re.search(rf"(?<![\w.]){re.escape(token)}(?!\w)", message, re.IGNORECASE) is not None


def is_disclosed(message: str, path: str, function: str) -> bool:
    if not _DISCLOSE.search(message):
        return False
    return _mentions(message, function) or _mentions(message, PurePath(path).name)


# ---------------------------------------------------------------------- main --
def _display(path: Path, cwd: str) -> str:
    try:
        return str(path.relative_to(Path(cwd).resolve()))
    except (ValueError, OSError):
        return str(path)


def evaluate(payload: dict) -> str | None:
    if payload.get("stop_hook_active"):
        return None
    tp = payload.get("transcript_path")
    if not isinstance(tp, str) or not tp or not Path(tp).is_file():
        return None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    turn = _turn_events(_load_events(Path(tp)))
    writes = collect_writes(turn)
    if not writes:
        return None

    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        message = _final_text_from_transcript(turn)

    by_file: dict[Path, list[dict]] = {}
    for w in writes:
        p = Path(w["path"])
        if not p.is_absolute():
            if not cwd:
                continue
            p = Path(cwd) / p
        by_file.setdefault(p.resolve(), []).append(w)

    undisclosed: list[str] = []
    for path, ops in by_file.items():
        shown = _display(path, cwd)  # relative to the project when inside it
        if not is_code_path(shown) or is_test_path(shown):
            continue
        try:
            post = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        pre = _content_before_turn(ops[0])
        added = [a for op in ops for a in op["added"]]
        removed = [r for op in ops for r in op["removed"]]
        for ln, what, fn, _text in new_placeholders(post, pre, added, removed, path.suffix.lower()):
            if is_disclosed(message, str(path), fn):
                continue
            where = f" in `{fn}`" if fn else ""
            undisclosed.append(f"- {shown}:{ln}  {what}{where}")

    if not undisclosed:
        return None
    listed = "\n".join(undisclosed[:MAX_LISTED])
    if len(undisclosed) > MAX_LISTED:
        listed += f"\n- ... and {len(undisclosed) - MAX_LISTED} more"
    return (
        "Placeholder check: this turn wrote placeholder code that your final message "
        f"does not mention:\n{listed}\n\n"
        "If the work is not finished, say so: name each placeholder and what it still "
        "needs, or report the task as blocked, with the reason and what would unblock "
        "it. If a placeholder is deliberate (an interface, a planned stub), say that in "
        "one line. Then end the turn."
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
