#!/usr/bin/env python3
"""Claude Code Stop hook: pause a turn once when its final message claims a check
that the turn's own tool calls do not support.

The failure it targets: the model states an unverified inference as established
fact - "all tests pass", "the build passes", "verified end-to-end", "I read the
whole file" - when the check behind it did not run, ran and failed, or covered
less than the claim says. The model corrects such claims readily once a person
points at them; this hook does the pointing before the turn ends.

What counts as support depends on the claim:

- a test claim needs a test command in the turn, and the last such command must
  not have failed (non-zero exit, or a failure summary in its output);
- a build claim needs a build, check or test command, under the same rule;
- a claim that a named command passes ("`make check` passes") needs that
  command in the turn, and its last run must not have failed;
- a "works" / "end-to-end" claim needs a command that ran something (not only
  ls, cat, grep and the like) and did not fail, or an HTTP fetch;
- a "no errors" / "healthy" / "I've confirmed" claim needs any observing tool
  call (a command, a Read, a search, a fetch);
- a whole-file claim ("read the whole file", "read X in full") is compared with
  the Read calls: the file must have been read with no line limit, or with reads
  that together cover every line.

A claim inside a code block or a quotation, a negated or conditional claim, a
question, and a sentence that hedges the claim or attributes it to someone else
are not counted.

It is advisory. It pauses at most once per stop cycle (`stop_hook_active`), and
on any unexpected input it does nothing (fails open). Python standard library
only. See README.md in this directory.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Claims. Each pattern is matched case-insensitively against one sentence of
# the final message, after code and quotations are replaced by placeholders.
# --------------------------------------------------------------------------

_TEST_CLAIM = re.compile(
    r"\ball (?:\d+ )?(?:of the )?(?:\w+ )?tests? (?:now |still )?"
    r"(?:pass(?:es|ed|ing)?|succeed(?:s|ed)?|(?:are|is) (?:green|passing))\b"
    r"|\ball (?:\d+ )?(?:cases? |suites? )?(?:now |still )?pass(?:es|ed|ing)?\b"
    r"|\b(?:the |my |its |both |these )?(?:unit |integration |e2e |regression )?"
    r"tests? (?:now |still |all )?(?:pass(?:es|ed)?|(?:are|is) (?:green|passing))\b"
    r"|\btest suite (?:now |still )?(?:pass(?:es|ed)?|(?:is|was) (?:green|passing|clean))\b"
    r"|\b\d+ (?:tests? |cases? )?passed\b"
    r"|\b\d+ ?/ ?\d+ (?:tests? |cases? )?pass(?:ed|ing|es)?\b"
    r"|\btests? (?:are |all )?green\b",
    re.IGNORECASE,
)

_BUILD_CLAIM = re.compile(
    r"\b(?:the )?build (?:now |still )?(?:pass(?:es|ed)?|succeed(?:s|ed)?|works|"
    r"(?:is|was) (?:green|clean|passing|fine))\b"
    r"|\b(?:buil(?:ds?|t)|compile[sd]?) (?:cleanly|clean|fine|successfully|"
    r"(?:without|with no|with zero) (?:any )?(?:errors?|warnings?))\b"
    r"|\b(?:type-?checks?|typecheck(?:ing)?|lint(?:ing|er)?|clippy) "
    r"(?:now |still )?(?:pass(?:es|ed)?|(?:is|was|comes back) clean|clean)\b"
    r"|\bno (?:compile|compiler|compilation|build|type) errors\b"
    r"|\b(?:all|every|each) (?:of the )?(?:\w+ )?checks? (?:now |still )?(?:pass(?:es|ed)?|succeed(?:s|ed)?)\b",
    re.IGNORECASE,
)

# "Works" claims: something was run and seen to work.
_RUN_CLAIM = re.compile(
    r"\b(?:verified|tested|confirmed|works?) end[- ]to[- ]end\b"
    r"|\bverified (?:that |it |this )?works?\b"
    r"|\bconfirmed (?:that |it |this )?works?\b"
    r"|\bverified (?:live|in prod|in production)\b"
    r"|\bi(?:'ve| have)? tested\b|\b(?:was|were|been) tested (?:on|against|with|live|end)\b"
    r"|\bsmoke tests? (?:pass(?:es|ed)?|(?:is|was) clean)\b",
    re.IGNORECASE,
)

# "Healthy" counts only next to a word for a running system; about a person, a
# habit or a design it is ordinary speech.
_SYSTEM_NOUN = (
    r"(?:service|server|cluster|pod|node|deploy\w*|release|pipeline|endpoint|"
    r"container|database|db|instance|job|daemon|health[- ]?check|replica|worker|"
    r"queue|ci|build|training run|training|api|site|backend|frontend)s?"
)
_OBSERVE_CLAIM = re.compile(
    r"\bno errors\b|\b(?:zero|0) errors\b|\bno error(?: signal| movement| at all)\b"
    r"|\bno error(?=\s*[.,;!)]|\s*$)"
    r"|\bi(?:'ve| have)? (?:checked|verified|confirmed)\b"
    r"|\bnone (?:of them |of the \w+ )?failed\b"
    r"|\b" + _SYSTEM_NOUN + r"\b[^.;:!?]{0,40}?\bhealthy\b"
    r"|\bhealthy\b[^.;:!?]{0,10}?\b" + _SYSTEM_NOUN + r"\b",
    re.IGNORECASE,
)

_SCOPE_CLAIM = re.compile(
    r"\b(?:read(?: through)?|reviewed|went through|gone through|looked through|looked at|checked) "
    r"(?:the |this |that )?(?:whole|entire|full|complete) "
    r"(?:file|thing|document|script|module|source|log|transcript|readme|\S+\.\w{1,5})\b"
    r"|\bread all (?:of )?(?:it|the file|this file|that file|the document|\S+\.\w{1,5})\b"
    r"|\b(?:read|reviewed) (?:it|the file|this file|that file|\S+\.\w{1,5}) "
    r"(?:in full|in its entirety|fully|end[- ]to[- ]end|cover to cover|from top to bottom|start to finish)\b"
    r"|\b(?:read|reviewed|went through) every line\b"
    r"|\bfully read\b",
    re.IGNORECASE,
)

# A command quoted in the message (replaced by CMDn) said to pass.
_CITED_CLAIM = re.compile(
    r"\bCMD(\d+) (?:now |still |also )?(?:pass(?:es|ed)?|succeed(?:s|ed)?|"
    r"(?:is|was|comes back|came back) (?:green|clean)|runs? clean(?:ly)?|"
    r"exit(?:s|ed)? (?:0|zero|cleanly)|returns? 0)\b",
    re.IGNORECASE,
)

# Claim kinds whose support is a property of the whole turn: checked once.
_TURN_CLAIMS = (
    ("test", _TEST_CLAIM),
    ("build", _BUILD_CLAIM),
    ("run", _RUN_CLAIM),
    ("observe", _OBSERVE_CLAIM),
)

# A sentence containing one of these is already flagging the gap, attributing
# the claim to someone else, or pointing at earlier work. Not nagged.
_HEDGE = re.compile(
    r"\b(?:not (?:yet |independently )?(?:sure|verified|tested|run|checked|confirmed)|"
    r"unverified|untested|"
    r"(?:haven't|have not|hasn't|has not|didn't|did not|couldn't|could not|wasn't able to|was not able to) "
    r"(?:yet )?(?:verify|verified|test|tested|run|ran|check|checked|confirm|confirmed|build|built|read)|"
    r"can't confirm|cannot confirm|"
    r"should (?:verify|test|check|run)|"
    r"needs? (?:verification|testing|to be (?:run|tested|verified))|"
    r"without (?:running|checking|verifying|testing)|"
    r"according to|"
    r"(?:subagent|agent|reviewer|user|you|he|she|they) (?:reported|reports|says|said|claims?)|"
    r"earlier in (?:this|the) session|in (?:an? |the )?(?:earlier|previous|last) (?:turn|run|session|message)|"
    r"previously|last time)\b",
    re.IGNORECASE,
)

# Words just before a claim that make it negated, conditional or prospective.
_NEGATED_BEFORE = re.compile(
    r"(?:\b(?:not|never|no longer|cannot|if|unless|until|once|whether|before|"
    r"might|may|should|would|could|will|to see|expect(?:ed)? to|make sure|ensure|"
    r"check (?:that|whether|if)|confirm (?:that|whether|if)|so that|in case)|n't)"
    r"\W+(?:\w+\W+){0,3}$",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------
# Evidence. Commands are split into segments on shell separators; a segment
# whose program only inspects or moves files (ls, cat, grep, cp, git...) is not
# a run of anything.
# --------------------------------------------------------------------------

_INSPECT_PROGRAMS = frozenset(
    "ls cat head tail less more grep egrep fgrep rg ag find fd wc echo printf pwd cd "
    "pushd popd stat file which whereis type command tree du df sort uniq cut tr awk "
    "sed jq yq diff cmp readlink realpath basename dirname date sleep true false test [ "
    "mkdir touch cp mv rm ln chmod chown tee xxd hexdump od strings nl column "
    "printenv export set unset source . id whoami hostname uname lscpu free ps pgrep git".split()
)
_WRAPPERS = frozenset("sudo time timeout nice nohup exec env command builtin stdbuf ionice".split())

_TEST_CMD = re.compile(
    r"\b(?:pytest|py\.test|unittest|tox|nox|jest|vitest|mocha|ava|karma|jasmine|"
    r"rspec|phpunit|ctest|bats|nextest|tests?|specs?)\b"
    r"|\btest_\w*|\w+_tests?\b|\.(?:test|spec)\.\w+|tests?/"
    r"|\b(?:go|cargo|npm|yarn|pnpm|bun|deno|mix|dotnet|gradle|mvn|zig build|meson|just|make)"
    r"(?: run)? (?:test|check)\b",
    re.IGNORECASE,
)
_BUILD_CMD = re.compile(
    r"\b(?:cargo (?:build|b|check|c|clippy|test|t|run|r|doc)|make|cmake|ninja|meson|bazel|"
    r"gcc|g\+\+|clang(?:\+\+)?|cc|rustc|go (?:build|vet|test|run)|tsc|npm run|yarn|pnpm|bun|"
    r"npx|mypy|pyright|ruff|flake8|pylint|eslint|gradle|mvn|dotnet|zig|javac|py_compile|"
    r"compileall|swift build|xcodebuild|nix build|build|compile|lint|typecheck|check)\b",
    re.IGNORECASE,
)
# Failure in the output of a command that exited 0 (for example `cargo test | tail`).
_FAIL_OUTPUT = re.compile(
    r"test result: FAILED|^FAILED\b|^FAIL\b|^ERROR:|BUILD FAILED|Compilation failed|"
    r"npm ERR!|make(?:\[\d+\])?: \*\*\*|error: could not compile|^error(?:\[E\d+\])?:|"
    r":\d+:\d+: (?:fatal )?error:|\berror TS\d+:|"
    r"\b[1-9]\d* (?:failed|failing|failures?)\b|Tests?:\s+[1-9]\d* failed",
    re.MULTILINE,
)
_HTTP_TOOLS = re.compile(r"^(?:WebFetch|mcp__.*(?:playwright|puppeteer|browser|fetch|http).*)$", re.IGNORECASE)
_NON_OBSERVING_TOOLS = frozenset(
    "Write Edit MultiEdit NotebookEdit TodoWrite TaskCreate TaskUpdate TaskList AskUserQuestion "
    "Agent Task Skill ToolSearch SubagentHandback ExitPlanMode EnterPlanMode SendMessage".split()
)

_HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?(?:\n\s*\1\s*(?=\n|$)|\Z)", re.DOTALL)
_MULTILINE_QUOTE = re.compile(r"'[^']*\n[^']*'|\"(?:[^\"\\]|\\.)*\n(?:[^\"\\]|\\.)*\"")


def _segments(command: str) -> list[str]:
    """Split a shell command on ; | || && & and newlines, outside quotes.

    Heredoc bodies and multi-line quoted strings are dropped first, so a script
    passed to python3 or cat is not read as shell commands.
    """
    command = _HEREDOC.sub(" HEREDOC", command)
    command = _MULTILINE_QUOTE.sub(" QUOTED ", command)
    out: list[str] = []
    cur: list[str] = []
    quote, i, n = "", 0, len(command)
    while i < n:
        ch = command[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                cur.append(command[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = ""
            cur.append(ch)
        elif ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch in ";|\n" or (ch == "&" and command[i - 1 : i] not in ("<", ">", "&") and command[i + 1 : i + 2] != ">"):
            out.append("".join(cur))
            cur = []
            if command[i : i + 2] in ("||", "&&", "|&"):
                i += 1
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def _program(segment: str) -> str:
    """First program word of a shell segment, past env assignments and wrappers."""
    words = segment.replace("(", " ").replace("{", " ").split()
    i = 0
    while i < len(words):
        w = words[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w) or w in _WRAPPERS or w.startswith("-"):
            i += 1
            if w == "timeout" and i < len(words) and not words[i].startswith("-"):
                i += 1  # timeout's duration
            continue
        break
    return os.path.basename(words[i]) if i < len(words) else ""


def _run_segments(command: str) -> list[str]:
    """Segments of a command that run something rather than only inspect."""
    out = []
    for s in _segments(command):
        prog = _program(s)
        if prog and prog not in _INSPECT_PROGRAMS:
            out.append(s)
    return out


class Call:
    """One tool call in the turn and, when the transcript has it, its result."""

    def __init__(self, name: str, inp: dict):
        self.name = name
        self.input = inp if isinstance(inp, dict) else {}
        self.result_text: str | None = None
        self.is_error = False
        self.result_meta = None  # the transcript's toolUseResult for this call

    @property
    def command(self) -> str:
        c = self.input.get("command") if self.name == "Bash" else None
        return c if isinstance(c, str) else ""

    def failed(self) -> bool:
        if self.is_error:
            return True
        return bool(self.result_text and _FAIL_OUTPUT.search(self.result_text))

    def describe(self) -> str:
        first = self.command.strip().splitlines()[0] if self.command.strip() else ""
        if not first:
            return self.name
        return "`" + first[:80] + ("..." if len(first) > 80 else "") + "`"


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _turn_calls(events: list[dict]) -> list[Call]:
    calls: list[Call] = []
    by_id: dict[str, Call] = {}
    pending: list[Call] = []  # calls without ids, matched to results in order
    for e in events:
        content = e.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if e.get("type") == "assistant" and b.get("type") == "tool_use":
                call = Call(str(b.get("name", "")), b.get("input", {}))
                calls.append(call)
                if b.get("id"):
                    by_id[b["id"]] = call
                else:
                    pending.append(call)
            elif e.get("type") == "user" and b.get("type") == "tool_result":
                call = by_id.get(b.get("tool_use_id") or "")
                if call is None and pending:
                    call = pending.pop(0)
                if call is None:
                    continue
                call.result_text = _result_text(b)
                call.is_error = bool(b.get("is_error"))
                call.result_meta = e.get("toolUseResult")
    return calls


def _last_run(calls: list[Call], *patterns: re.Pattern) -> Call | None:
    last = None
    for c in calls:
        if c.name == "Bash" and any(p.search(s) for s in _run_segments(c.command) for p in patterns):
            last = c
    return last


def _ran_note(calls: list[Call]) -> str:
    ran = [c.describe() for c in calls if c.name == "Bash"]
    if not ran:
        return ""
    return "; commands run: " + ", ".join(ran[:4]) + (" ..." if len(ran) > 4 else "")


def _cited_ok(span: str, calls: list[Call]) -> bool:
    """`span` is a command that ran in this turn, and its last run did not fail."""
    span = span.strip()
    last = None
    for c in calls:
        if c.name == "Bash" and span and span in c.command:
            last = c
    return last is not None and not last.failed()


def _support(kind: str, calls: list[Call], spans: list[str]) -> str | None:
    """None if the turn supports a claim of this kind, else what is missing."""
    if kind in ("test", "build", "run"):
        # a run command quoted in the message that ran and did not fail
        if any(_run_segments(s) and _cited_ok(s, calls) for s in spans if len(s.strip()) >= 4):
            return None
    if kind == "test":
        last = _last_run(calls, _TEST_CMD)
        if last is None:
            return "no test command ran in this turn" + _ran_note(calls)
        if last.failed():
            return f"the last test command in this turn, {last.describe()}, failed"
        return None
    if kind == "build":
        last = _last_run(calls, _BUILD_CMD, _TEST_CMD)
        if last is None:
            return "no build, check or test command ran in this turn" + _ran_note(calls)
        if last.failed():
            return f"the last build or test command in this turn, {last.describe()}, failed"
        return None
    if kind == "run":
        runs = [c for c in calls if (c.name == "Bash" and _run_segments(c.command)) or _HTTP_TOOLS.match(c.name)]
        if not runs:
            return "nothing was run in this turn, only reads, searches or edits" + _ran_note(calls)
        if all(c.failed() for c in runs):
            return "every command run in this turn failed"
        return None
    if kind == "observe":
        if any(c.name not in _NON_OBSERVING_TOOLS for c in calls):
            return None
        return "no command, read or fetch ran in this turn"
    return None


# --------------------------------------------------------------------------
# Whole-file claims against Read calls.
# --------------------------------------------------------------------------

_WHOLE = 10**9  # end of a read with no line limit


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _read_coverage(calls: list[Call]) -> dict[str, tuple[bool, str]]:
    """file path -> (read in full?, what was read)."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    totals: dict[str, int] = {}
    for c in calls:
        if c.name != "Read" or c.is_error:
            continue
        path = c.input.get("file_path")
        if not isinstance(path, str):
            continue
        meta = c.result_meta.get("file") if isinstance(c.result_meta, dict) else None
        total = _int(meta.get("totalLines")) if isinstance(meta, dict) else None
        if total is not None:
            start = _int(meta.get("startLine")) or 1
            num = _int(meta.get("numLines")) or 0
            totals[path] = total
            ranges.setdefault(path, []).append((start, start + num - 1))
            continue
        # No result metadata: judge from the call's own offset and limit.
        offset = _int(c.input.get("offset"))
        limit = _int(c.input.get("limit"))
        from_top = offset in (None, 0, 1)
        returned = len(re.findall(r"^\s*\d+\t", c.result_text or "", re.MULTILINE))
        if from_top and (limit is None or (c.result_text is not None and returned < limit)):
            ranges.setdefault(path, []).append((1, _WHOLE))  # no limit, or the file ended first
            continue
        start = offset if offset and offset > 0 else 1
        ranges.setdefault(path, []).append((start, start + (limit or returned or 1) - 1))
    out: dict[str, tuple[bool, str]] = {}
    for path, rs in ranges.items():
        rs.sort()
        covered_to, gaps = 0, False
        for a, b in rs:
            gaps = gaps or a > covered_to + 1
            covered_to = max(covered_to, b)
        total = totals.get(path)
        if total is not None:
            full = not gaps and covered_to >= total
            desc = "lines " + ", ".join(f"{a}-{min(b, total)}" for a, b in rs) + f" of {total}"
        else:
            full = not gaps and covered_to >= _WHOLE
            desc = "the whole file" if full else "lines " + ", ".join(f"{a}-{b}" for a, b in rs)
        out[path] = (full, desc)
    return out


def _scope_problem(sentence: str, calls: list[Call]) -> str | None:
    cov = _read_coverage(calls)
    if not cov:
        return None  # no Read calls this turn: nothing to compare against
    low = sentence.lower()
    named = [p for p in cov if os.path.basename(p).lower() in low]
    if named:
        for p in named:
            if not cov[p][0]:
                return f"the Read calls on {os.path.basename(p)} in this turn covered {cov[p][1]}"
        return None
    if any(full for full, _ in cov.values()):
        return None  # some file was read in full; the claim may be about that one
    p, (_, desc) = next(iter(cov.items()))
    return f"no file was read in full in this turn ({os.path.basename(p)}: {desc})"


# --------------------------------------------------------------------------
# Transcript.
# --------------------------------------------------------------------------

def _resolve_transcript(payload: dict) -> Path | None:
    """The Stop hook payload carries transcript_path; reconstruct it if absent."""
    tp = payload.get("transcript_path")
    if isinstance(tp, str) and tp and Path(tp).is_file():
        return Path(tp)
    sid = payload.get("session_id") or payload.get("sessionId")
    cwd = payload.get("cwd") or os.getcwd()
    if isinstance(sid, str) and sid and isinstance(cwd, str):
        sanitized = re.sub(r"[^A-Za-z0-9-]", "-", str(Path(cwd).resolve()))
        cand = Path.home() / ".claude" / "projects" / sanitized / f"{sid}.jsonl"
        if cand.is_file():
            return cand
    return None


def _load_events(transcript: Path) -> list[dict]:
    events: list[dict] = []
    for line in transcript.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(e, dict) and e.get("type") in ("user", "assistant"):
            events.append(e)
    return events


def _is_turn_start(e: dict, has_turn_markers: bool) -> bool:
    """A prompt that starts a turn, not a tool result or an injected meta message.

    Current transcripts mark each turn's opening prompt with `turnPosition`; system
    reminders, skill text and pasted-image notes arrive as user events with
    `isMeta` and no `turnPosition`, and must not cut the turn short. Older or
    synthetic transcripts have no markers: there a prompt is a non-meta user
    event whose content is a string or contains a text block.
    """
    if e.get("type") != "user":
        return False
    if has_turn_markers:
        return bool(e.get("turnPosition"))
    if e.get("isMeta"):
        return False
    content = e.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in content)
    return False


def _turn_events(events: list[dict]) -> list[dict]:
    markers = any(e.get("turnPosition") for e in events)
    start = 0
    for i, e in enumerate(events):
        if _is_turn_start(e, markers):
            start = i
    return events[start:]


def _final_text_from_transcript(turn: list[dict]) -> str:
    """Text of the assistant events after the turn's last tool call or result."""
    last_tool = -1
    for i, e in enumerate(turn):
        content = e.get("message", {}).get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result") for b in content
        ):
            last_tool = i
    parts: list[str] = []
    for e in turn[last_tool + 1:]:
        if e.get("type") != "assistant":
            continue
        content = e.get("message", {}).get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# The message.
# --------------------------------------------------------------------------

_FENCE = re.compile(r"```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)", re.DOTALL)
_INLINE = re.compile(r"`([^`\n]+)`")
_QUOTED = re.compile(r"\"[^\"\n]{1,120}\"|“[^”\n]{1,120}”|^\s*>.*$", re.MULTILINE)
_FILE_NAME = re.compile(r"[\w./~-]+\.\w{1,6}")


def _prepare(text: str) -> tuple[str, list[str]]:
    """Prose with code and quotations replaced, and the inline code spans.

    An inline span that is a file name is kept, so a whole-file claim can name
    its file. Any other span becomes CMDn, n its index in the returned list.
    """
    prose = _FENCE.sub(" CODE ", text)
    spans: list[str] = []

    def inline(m: re.Match) -> str:
        s = m.group(1)
        if _FILE_NAME.fullmatch(s):
            return s
        spans.append(s)
        return f"CMD{len(spans) - 1}"

    prose = _INLINE.sub(inline, prose)
    prose = _QUOTED.sub(" QUOTE ", prose)
    return prose, spans


def _sentences(prose: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?;])\s+|\n+", prose) if s.strip()]


def find_problems(text: str, calls: list[Call]) -> list[tuple[str, str]]:
    """(claim as written, what the turn lacks) for each unsupported claim."""
    prose, spans = _prepare(text)
    problems: list[tuple[str, str]] = []
    checked: set[str] = set()
    for sentence in _sentences(prose):
        if sentence.rstrip().endswith("?") or _HEDGE.search(sentence):
            continue
        for kind, pattern in _TURN_CLAIMS:
            if kind in checked:
                continue
            for m in pattern.finditer(sentence):
                if _NEGATED_BEFORE.search(sentence[: m.start()]):
                    continue
                checked.add(kind)
                gap = _support(kind, calls, spans)
                if gap:
                    problems.append((m.group(0).strip(), gap))
                break
        for m in _SCOPE_CLAIM.finditer(sentence):
            if _NEGATED_BEFORE.search(sentence[: m.start()]):
                continue
            gap = _scope_problem(sentence, calls)
            if gap:
                problems.append((m.group(0).strip(), gap))
            break
        for m in _CITED_CLAIM.finditer(sentence):
            if _NEGATED_BEFORE.search(sentence[: m.start()]):
                continue
            span = spans[int(m.group(1))]
            if _run_segments(span) and not _cited_ok(span, calls):
                ran = any(c.name == "Bash" and span.strip() in c.command for c in calls)
                gap = "its last run in this turn failed" if ran else "it did not run in this turn"
                problems.append((f"`{span}`" + m.group(0)[len(m.group(0).split()[0]):], gap))
    return problems


def _reason(problems: list[tuple[str, str]]) -> str:
    lines = [f"- {claim!r}: {gap}." for claim, gap in problems[:3]]
    return (
        "Send-time verification check. The final message makes a claim that this "
        "turn's tool calls do not support:\n"
        + "\n".join(lines)
        + "\n\nBefore ending, either run the check that supports the claim, or restate "
        "it as what was actually done (for example \"edited, not yet run\", or \"read "
        "lines 1-200\"). If the claim rests on earlier work in this session or on "
        "someone else's report, say so and end the turn. This check is a pattern "
        "match and can be wrong; if it is, say so in one line and end the turn."
    )


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict) or data.get("stop_hook_active"):
            return 0  # not a payload we understand, or already paused once this cycle
        transcript = _resolve_transcript(data)
        if transcript is None:
            return 0  # can't see the turn -> fail open
        turn = _turn_events(_load_events(transcript))
        text = data.get("last_assistant_message")
        if not isinstance(text, str) or not text.strip():
            text = _final_text_from_transcript(turn)
        if not text.strip():
            return 0
        problems = find_problems(text, _turn_calls(turn))
        if problems:
            print(json.dumps({"decision": "block", "reason": _reason(problems)}))
    except Exception:  # fail open on anything unexpected
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
