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
- a speed or memory claim ("3x faster", "now runs in 1.2 s") needs a timing or
  benchmark program, in command position, that did not fail;
- a whole-file claim ("read the whole file", "read X in full") is compared with
  the reads of the whole session (Read calls, and cat / head / tail / sed -n at the
  end of a pipeline): the file must have been read with no line limit, or with reads
  that together cover every line; a named file that was never read fails;
- a whole-repository claim is always flagged; "read through <dir>" fails if a file
  read under that directory was read only in part; "read all four <noun>s" fails if
  fewer files named like the noun were read in full than the claim counts.

A claim inside a code block or a quotation, a negated or conditional claim, a
claim followed by "means" or the like (a rule, not a report), a question, and a
sentence that hedges the claim or attributes it to someone else are not counted.

It is advisory. It pauses at most once per stop cycle (`stop_hook_active`), and
on any unexpected input it does nothing (fails open). An optional trial file can
switch it off in a random half of sessions, so its effect can be measured
(`trial_arm`; hook-trial/ in the repository). Python standard library only. See
README.md in this directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
from datetime import date, datetime, timezone
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

# A measured speed or size change. Support is a timing or benchmark command. A
# plain "runs in 40 minutes" is usually background, not a measurement, so a time
# counts only with "now" or as a change ("from 900 ms to 300 ms").
_UNIT = r"(?:ms|µs|us|ns|s|secs?|seconds?|mins?|minutes?|h|hours?|[KMG]i?B|%)"
_PERF_CLAIM = re.compile(
    r"\b\d+(?:\.\d+)? ?(?:x|×|%|percent|times) (?:faster|slower|quicker|speed-?up|less memory|smaller)\b"
    r"|\b(?:speed-?up|sped up|speeds up) (?:of|by) (?:about |roughly |~)?\d"
    r"|\b(?:reduc|cut|lower|dropp|improv)\w* (?:the )?(?:latency|runtime|run time|wall time|memory(?: use| usage)?|"
    r"build time|startup time|throughput) (?:by|from) (?:about |roughly |~)?\d"
    r"|\bnow (?:runs?|takes?|completes?|finishes) (?:in )?(?:about |roughly |~)?\d+(?:\.\d+)? ?" + _UNIT + r"(?!\w)"
    r"|\b(?:dropped|fell|went|came|is|are|was) (?:down )?from (?:about |roughly |~)?\d+(?:\.\d+)? ?" + _UNIT
    + r"? to (?:about |roughly |~)?\d",
    re.IGNORECASE,
)

# A claim to have read a whole repository or codebase. Reads cannot be shown
# to cover one, so this is always asked to be restated as what was read. The noun
# must end the phrase ("the entire project brief" is about a document).
_REPO_CLAIM = re.compile(
    r"\b(?:read(?: through)?|reviewed|went through|gone through|looked through|audited) "
    r"(?:the |this |that |your )?(?:whole|entire|full|complete) (?:repo(?:sitory)?|codebase|code base|project|source tree)"
    r"(?=\s*(?:[.,;:!?)]|$)|\s+(?:and|but|or|to|for|in|of|at|on|with|before|after|from|so|then|which|that|is|was|"
    r"looks?|seems?|again|once|now|first|today|carefully|end)\b)"
    r"|\bread (?:through )?every file\b",
    re.IGNORECASE,
)

# "I've read through widget-core", "went through src/": a read of a directory. Judged
# only when the name is a directory of files read in the session.
_DIR_CLAIM = re.compile(
    r"\b(?:read|gone|went|looked) through (?:the |all of |all |your |this )?"
    r"(?P<d>[\w.-]*[\w-](?:/[\w.-]*[\w-])*)/?(?: (?:repo(?:sitory)?|directory|folder|codebase|project|tree))?"
    r"(?=[\s.,;:!?)]|$)",
    re.IGNORECASE,
)

# "I read all four handoffs": a count of documents, judged against the files read
# in full in the session whose names contain the noun.
_NUMBERS = {"both": 2, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_COUNT_CLAIM = re.compile(
    r"\bread (?:all |each of |every one of )?(?:the |my |your )?(?P<n>\d+|" + "|".join(_NUMBERS) + r") "
    r"(?:of the )?(?P<noun>[a-z][a-z-]{2,}?)s\b",
    re.IGNORECASE,
)

# Words right after a claim that make it a definition or a rule, not a report:
# "all pass means the task counts as solved".
_GENERIC_AFTER = re.compile(
    r"^\s*(?:(?:means?|meaning|implies|indicates|counts? as|is (?:what|how|required|needed|enough|the (?:goal|bar|"
    r"criterion|condition))|are (?:required|needed))\b|=)",
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
    ("perf", _PERF_CLAIM),
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
        self.cwd = ""  # the working directory the transcript records for the call, if any

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
                cwd = e.get("cwd")
                call.cwd = cwd if isinstance(cwd, str) and cwd.startswith("/") else ""
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


_TIMERS = frozenset("time hyperfine valgrind heaptrack wrk k6 pyperf".split())
_INTERPRETERS = frozenset("python python3 node bash sh zsh ruby perl deno bun uv".split())
_TIMED_RUN = re.compile(
    r"^(?:cargo (?:bench|criterion)\b|go test\b.*\s-bench|(?:python3? -m )?pytest\b.*--benchmark|"
    r"python3? -m (?:timeit|pyperf)\b|perf (?:stat|record)\b|strace\b.*\s-c\b|ab\b.*\s-n\b)"
)


def _is_timing(command: str) -> bool:
    """A segment of the command whose program, in command position, times or benchmarks."""
    if re.search(r"\bEXPLAIN ANALYZE\b", command, re.IGNORECASE):
        return True
    for seg in _segments(command):
        words = seg.replace("(", " ").replace("{", " ").split()
        i = 0
        while i < len(words) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[i]) or words[i] in
                                  ("sudo", "nice", "nohup", "exec", "env", "command", "stdbuf", "ionice", "timeout")):
            i += 2 if words[i] == "timeout" and i + 1 < len(words) and not words[i + 1].startswith("-") else 1
        if i >= len(words):
            continue
        prog = os.path.basename(words[i])
        if prog in _TIMERS or "bench" in prog.lower() or _TIMED_RUN.match(" ".join([prog] + words[i + 1:])):
            return True
        if prog in _INTERPRETERS:
            args = [w for w in words[i + 1:] if not w.startswith("-") and w not in ("run", "exec")]
            if args and "bench" in os.path.basename(args[0]).lower():
                return True
    return False


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
    if kind == "perf":
        timed = [c for c in calls if c.name == "Bash" and _is_timing(c.command)]
        if not timed:
            return "no timing or benchmark command ran in this turn" + _ran_note(calls)
        if all(c.failed() for c in timed):
            return "every timing or benchmark command in this turn failed"
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


# Reads done with shell commands. What the agent sees is the output of the last
# stage of a pipeline, so a file counts as read in full only through a `cat` (or
# `nl`) at the end of its pipeline, or a `head` / `sed -n` range of at least
# _LARGE_RANGE lines that printed fewer lines than it asked for (the file ended
# first). A read piped into anything but `head`, written to a file, or whose
# output Claude Code cut short counts as a read of an unknown part.

_PART = 0  # end of a read whose extent is unknown: recorded as (1, _PART), never full
_LARGE_RANGE = 500
_PERSISTED = re.compile(r"<persisted-output>|Output too large \(|\[\d+ (?:characters|lines) truncated\]")
_SED_SCRIPT = re.compile(r"^(\d+)(?:,(\d+|\$))?p$")
_REDIR = re.compile(r"^(\d*|&)(>>|>|<)(.*)$")
_PASS_THROUGH = frozenset("cat tee less more".split())
_UNKNOWN_FILE = re.compile(r"[*?\[$`{]")  # a glob or a variable: which file it names is not known
_READ_WRAPPERS = frozenset("sudo command env nice nohup stdbuf ionice exec builtin".split())


def _pipelines(command: str) -> list[list[str]]:
    """The pipelines of a command, each a list of its stages, split outside quotes."""
    command = _HEREDOC.sub(" HEREDOC", command)
    command = _MULTILINE_QUOTE.sub(" QUOTED ", command)
    out: list[list[str]] = []
    stages: list[str] = []
    cur: list[str] = []
    quote, i, n = "", 0, len(command)

    def end_stage() -> None:
        stages.append("".join(cur).strip())
        cur.clear()

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
        elif ch == "|" and command[i + 1 : i + 2] != "|":
            end_stage()
            if command[i + 1 : i + 2] == "&":
                i += 1
        elif ch in ";\n" or command[i : i + 2] in ("&&", "||") or (
            ch == "&" and command[i - 1 : i] not in ("<", ">") and command[i + 1 : i + 2] != ">"
        ):
            end_stage()
            out.append([s for s in stages if s])
            stages = []
            if command[i : i + 2] in ("&&", "||"):
                i += 1
        else:
            cur.append(ch)
        i += 1
    end_stage()
    out.append([s for s in stages if s])
    return [p for p in out if p]


def _words(stage: str) -> list[str]:
    try:
        return shlex.split(stage)
    except ValueError:
        return stage.split()


def _args(words: list[str]) -> tuple[list[str], bool]:
    """Words without redirections and the program's wrappers; and whether stdout goes to a file."""
    out: list[str] = []
    to_file = False
    i = 0
    while i < len(words):
        m = _REDIR.match(words[i])
        if m:
            fd, op, target = m.groups()
            if not target and i + 1 < len(words):
                target = words[i + 1]
                i += 1
            if op != "<" and fd in ("", "1", "&") and not target.startswith("&"):
                to_file = True
            i += 1
            continue
        out.append(words[i])
        i += 1
    while out and (out[0] in _READ_WRAPPERS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", out[0])):
        out.pop(0)
    return out, to_file


def _count_arg(w: str) -> int | None:
    v = _int(w)
    return v if v is not None and v > 0 else None


def _stage_reads(args: list[str]) -> list[tuple[str, int, int]]:
    """(file, first line, last line) for a stage that prints files: cat, nl, head, tail, sed -n."""
    if not args:
        return []
    prog, rest = os.path.basename(args[0]), args[1:]
    if prog in ("cat", "nl"):
        return [(f, 1, _WHOLE) for f in rest if f and not f.startswith("-") and f not in ("HEREDOC", "QUOTED")
                and not _UNKNOWN_FILE.search(f)]
    if prog in ("head", "tail"):
        count: int | None = 10
        start_at: int | None = None
        partial = False
        files: list[str] = []
        j = 0
        while j < len(rest):
            w = rest[j]
            if w in ("-n", "--lines") and j + 1 < len(rest):
                v = rest[j + 1]
                j += 2
            elif w.startswith("--lines="):
                v, j = w[8:], j + 1
            elif re.fullmatch(r"-n[+-]?\d+", w):
                v, j = w[2:], j + 1
            elif re.fullmatch(r"-\d+", w):
                v, j = w[1:], j + 1
            elif re.fullmatch(r"\+\d+", w) and prog == "tail":
                v, j = w, j + 1
            else:
                if w in ("-c", "--bytes"):
                    partial, j = True, j + 2
                    continue
                if w.startswith("-c") or w.startswith("--bytes"):
                    partial = True
                elif not w.startswith("-"):
                    files.append(w)
                j += 1
                continue
            if prog == "tail" and v.startswith("+"):
                start_at = _count_arg(v[1:])
            else:
                count = _count_arg(v)
        if prog == "tail":
            if start_at is None or partial:
                return [(f, 1, _PART) for f in files]
            return [(f, start_at, _WHOLE) for f in files]
        if partial or count is None:
            return [(f, 1, _PART) for f in files]
        return [(f, 1, count) for f in files]
    if prog == "sed" and "-n" in rest:
        plain = [w for w in rest if not w.startswith("-")]
        if len(plain) < 2:
            return []
        ranges = []
        for part in plain[0].split(";"):
            m = _SED_SCRIPT.match(part.strip())
            if not m:
                return []  # a script that does more than print line ranges
            a = int(m.group(1))
            b = _WHOLE if m.group(2) == "$" else int(m.group(2)) if m.group(2) else a
            ranges.append((a, b))
        return [(f, a, b) for f in plain[1:] for a, b in ranges]
    return []


def _head_limit(args: list[str]) -> int | None:
    """The line count of a `head` stage reading its input, or None if it is not one."""
    if not args or os.path.basename(args[0]) != "head":
        return None
    reads = _stage_reads(args + ["STDIN"])
    return reads[-1][2] if reads else None


def _norm(path: str, cwd: str) -> str:
    if path.startswith("/"):
        return os.path.normpath(path)
    if cwd:
        return os.path.normpath(os.path.join(cwd, path))
    return os.path.normpath(path)


def _comps(path: str) -> list[str]:
    return [c for c in path.split("/") if c not in ("", ".")]


def _bash_reads(call: Call) -> list[tuple[str, int, int]]:
    """(resolved file, first line, last line) for the files a Bash call printed."""
    out: list[tuple[str, int, int]] = []
    cwd = call.cwd
    last_stage_reads = 0
    for stages in _pipelines(call.command):
        parsed = [_args(_words(s)) for s in stages]
        first = parsed[0][0]
        if len(stages) == 1 and first and first[0] == "cd":
            target = first[1] if len(first) > 1 else ""
            if target and not target.startswith(("~", "$", "-")):
                cwd = _norm(target, cwd)
            continue
        for idx, (args, to_file) in enumerate(parsed):
            reads = _stage_reads(args)
            if not reads or to_file:
                continue
            for nxt, nxt_to_file in parsed[idx + 1 :]:
                if nxt_to_file:
                    reads = []
                    break
                limit = _head_limit(nxt)
                if limit is not None:
                    reads = [(f, a, b if b == _PART else min(b, a + limit - 1)) for f, a, b in reads]
                    continue
                if nxt and os.path.basename(nxt[0]) in _PASS_THROUGH:
                    continue
                reads = [(f, 1, _PART) for f, _, _ in reads]
                break
            out.extend((_norm(f, cwd), a, b) for f, a, b in reads if not _UNKNOWN_FILE.search(f))
            last_stage_reads += len(reads)
    text = call.result_text or ""
    if _PERSISTED.search(text):
        return [(f, 1, _PART) for f, _, _ in out]
    if len(out) == 1:
        f, a, b = out[0]
        printed = len(text.rstrip("\n").splitlines()) if text.strip() else 0
        if b not in (_WHOLE, _PART) and b - a + 1 >= _LARGE_RANGE and printed < b - a + 1:
            out = [(f, a, _WHOLE)]  # the file ended before the range did
    return out


def _coverage(session: list[Call], turn: list[Call]) -> tuple[dict[str, tuple[bool, str]], set[str]]:
    """file -> (read in full in the session?, what was read), and the files read in this turn.

    Files are keyed by resolved path. A relative path (no working directory recorded)
    is merged into the one absolute path it is a suffix of; files that only share a
    base name are kept apart.
    """
    turn_ids = {id(c) for c in turn}
    ranges: dict[str, list[tuple[int, int]]] = {}
    totals: dict[str, int] = {}
    touched: set[str] = set()

    def add(key: str, a: int, b: int, c: Call) -> None:
        ranges.setdefault(key, []).append((a, b))
        if id(c) in turn_ids:
            touched.add(key)

    for c in session:
        if c.is_error:
            continue
        if c.name == "Bash":
            for f, a, b in _bash_reads(c):
                add(f, a, b, c)
            continue
        if c.name != "Read":
            continue
        path = c.input.get("file_path")
        if not isinstance(path, str):
            continue
        key = _norm(path, c.cwd)
        meta = c.result_meta.get("file") if isinstance(c.result_meta, dict) else None
        total = _int(meta.get("totalLines")) if isinstance(meta, dict) else None
        if total is not None:
            start = _int(meta.get("startLine")) or 1
            num = _int(meta.get("numLines")) or 0
            totals[key] = total
            add(key, start, start + num - 1, c)
            continue
        # No result metadata: judge from the call's own offset and limit.
        offset = _int(c.input.get("offset"))
        limit = _int(c.input.get("limit"))
        from_top = offset in (None, 0, 1)
        returned = len(re.findall(r"^\s*\d+\t", c.result_text or "", re.MULTILINE))
        if from_top and (limit is None or (c.result_text is not None and returned < limit)):
            add(key, 1, _WHOLE, c)  # no limit, or the file ended first
            continue
        start = offset if offset and offset > 0 else 1
        add(key, start, start + (limit or returned or 1) - 1, c)
    absolute = [k for k in ranges if k.startswith("/")]
    for k in [k for k in ranges if not k.startswith("/")]:
        comps = _comps(k)
        cands = [p for p in absolute if comps and _comps(p)[-len(comps):] == comps]
        if len(cands) == 1:
            ranges[cands[0]].extend(ranges.pop(k))
            if k in touched:
                touched.discard(k)
                touched.add(cands[0])
    out: dict[str, tuple[bool, str]] = {}
    for path, rs in ranges.items():
        rs.sort()
        covered_to, gaps = 0, False
        for a, b in rs:
            if b == _PART:
                continue
            gaps = gaps or a > covered_to + 1
            covered_to = max(covered_to, b)
        total = totals.get(path)
        parts = []
        for a, b in rs:
            if b == _PART:
                parts.append("an unknown part (filtered or cut-off output)")
            else:
                parts.append(f"lines {a}-{min(b, total) if total else b}")
        if total is not None:
            full = covered_to > 0 and not gaps and covered_to >= total
            desc = ", ".join(parts) + f" of {total}"
        else:
            full = covered_to > 0 and not gaps and covered_to >= _WHOLE
            desc = "the whole file" if full else ", ".join(parts)
        out[path] = (full, desc.replace(f"-{_WHOLE}", "-end"))
    return out, touched


def _read_coverage(calls: list[Call]) -> dict[str, tuple[bool, str]]:
    return _coverage(calls, calls)[0]


def _matching(token: str, cov: dict[str, tuple[bool, str]]) -> list[str]:
    """Files read in the session whose path ends with the named path, component by component."""
    comps = _comps(token)
    return [k for k in cov if comps and _comps(k)[-len(comps):] == comps]


def _scope_problem(sentence: str, m: re.Match, cov: dict[str, tuple[bool, str]], touched: set[str]) -> str | None:
    """Reads anywhere in the session count: a file read in two turns is read."""
    named, unread = [], []
    for t in _FILE_NAME.finditer(sentence):
        keys = _matching(t.group(0), cov)
        if keys:
            named.append((t.group(0), keys))
        elif t.start() < m.end() + 15 and t.end() > m.start():
            unread.append(t.group(0))  # the claim's own object, never read
    for name, keys in named:
        if not any(cov[k][0] for k in keys):
            return f"the reads of {name} in this session covered {cov[keys[0]][1]}"
    if unread:
        return f"{unread[0]} was not read in this session (by a Read, or by cat, head, tail or sed -n)"
    if named or not cov:
        return None
    if touched:
        if any(cov[k][0] for k in touched):
            return None  # a file read this turn was read in full; the claim may be about that one
        k = sorted(touched)[0]
        return f"no file read in this turn was read in full in this session ({os.path.basename(k)}: {cov[k][1]})"
    if any(full for full, _ in cov.values()):
        return None
    k = next(iter(cov))
    return f"no file read in this session was read in full ({os.path.basename(k)}: {cov[k][1]})"


def _contains(seq: list[str], sub: list[str]) -> bool:
    return any(seq[i : i + len(sub)] == sub for i in range(len(seq) - len(sub) + 1))


_NOT_DIRS = frozenset("it this that them those these the all everything whole entire full complete".split())


def _dir_problem(m: re.Match, cov: dict[str, tuple[bool, str]], spans: list[str]) -> str | None:
    d = m.group("d")
    cited = re.fullmatch(r"CMD(\d+)", d)
    if cited and int(cited.group(1)) < len(spans):
        d = spans[int(cited.group(1))].strip()
    comps = _comps(d.strip("/"))
    if not comps or d.lower() in _NOT_DIRS:
        return None
    under = [k for k in cov if _contains(_comps(k)[:-1], comps)]
    part = [k for k in under if not cov[k][0]]
    if not part:
        return None  # not a directory read in this session, or every file read under it was read in full
    k = part[0]
    return (f"{len(part)} of the {len(under)} files read under {d} in this session were read only in part "
            f"({os.path.basename(k)}: {cov[k][1]})")


_GENERIC_DOCS = frozenset("file document doc page line section chapter part item paper note slide".split())


def _count_problem(m: re.Match, cov: dict[str, tuple[bool, str]]) -> str | None:
    word = m.group("n").lower()
    n = int(word) if word.isdigit() else _NUMBERS[word]
    noun = m.group("noun").lower()
    if noun.endswith("ie"):
        noun = noun[:-2] + "y"
    if noun in _GENERIC_DOCS:
        return None
    variants = {noun, noun.replace("-", "_"), noun.replace("-", "")}
    matching = [k for k in cov if any(v in os.path.basename(k).lower() for v in variants)]
    if len(matching) < n:
        return None  # fewer files are named like these documents than the claim counts: names do not identify them
    full = [k for k in matching if cov[k][0]]
    if len(full) >= n:
        return None
    names = ", ".join(os.path.basename(k) for k in full) or "none"
    return (f"{len(full)} file(s) named like '{noun}' were read in full in this session ({names}), "
            f"of {len(matching)} read at all; the claim is {n}")


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


def find_problems(text: str, calls: list[Call], session: list[Call] | None = None) -> list[tuple[str, str]]:
    """(claim as written, what the turn lacks) for each unsupported claim."""
    prose, spans = _prepare(text)
    problems: list[tuple[str, str]] = []
    checked: set[str] = set()
    cov, touched = _coverage(session if session is not None else calls, calls)
    for sentence in _sentences(prose):
        if sentence.rstrip().endswith("?") or _HEDGE.search(sentence):
            continue
        for kind, pattern in _TURN_CLAIMS:
            if kind in checked:
                continue
            for m in pattern.finditer(sentence):
                if _NEGATED_BEFORE.search(sentence[: m.start()]) or _GENERIC_AFTER.match(sentence[m.end():]):
                    continue
                checked.add(kind)
                gap = _support(kind, calls, spans)
                if gap:
                    problems.append((m.group(0).strip(), gap))
                break
        for m in _SCOPE_CLAIM.finditer(sentence):
            if _NEGATED_BEFORE.search(sentence[: m.start()]):
                continue
            gap = _scope_problem(sentence, m, cov, touched)
            if gap:
                problems.append((m.group(0).strip(), gap))
            break
        for pattern, judge in ((_DIR_CLAIM, lambda m: _dir_problem(m, cov, spans)),
                               (_COUNT_CLAIM, lambda m: _count_problem(m, cov))):
            for m in pattern.finditer(sentence):
                if _NEGATED_BEFORE.search(sentence[: m.start()]):
                    continue
                gap = judge(m)
                if gap:
                    problems.append((m.group(0).strip(), gap))
                    break
        for m in _REPO_CLAIM.finditer(sentence):
            if _NEGATED_BEFORE.search(sentence[: m.start()]):
                continue
            problems.append((m.group(0).strip(), "reads cannot be shown to cover a whole repository; name the files or directories that were read"))
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


def judge(events: list, text: str | None = None) -> list[tuple[str, str]]:
    """(claim, what the turn lacks) for each unsupported claim in the final message of
    the last turn in `events`, the transcript records up to the end of that turn.

    `text` is the final message; when it is missing or empty it is read from the
    transcript. Used by main() and by analyses that judge recorded turns.
    """
    events = [e for e in events if isinstance(e, dict) and e.get("type") in ("user", "assistant")]
    turn = _turn_events(events)
    if not isinstance(text, str) or not text.strip():
        text = _final_text_from_transcript(turn)
    if not text.strip():
        return []
    session = _turn_calls(events)
    # The turn is a suffix of the session, so its calls are the session's last ones
    # (the same objects, which _coverage relies on to tell this turn's reads apart).
    n_turn = len(_turn_calls(turn))
    return find_problems(text, session[len(session) - n_turn:] if n_turn else [], session)


# --------------------------------------------------------------------------
# Trial switch: the same function, word for word, is in each hook that takes part.
# --------------------------------------------------------------------------

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
        data = json.load(sys.stdin)
        if not isinstance(data, dict) or trial_arm(data) == "off" or data.get("stop_hook_active"):
            return 0  # not a payload we understand, the trial's off arm, or already paused once
        transcript = _resolve_transcript(data)
        if transcript is None:
            return 0  # can't see the turn -> fail open
        problems = judge(_load_events(transcript), data.get("last_assistant_message"))
        if problems:
            print(json.dumps({"decision": "block", "reason": _reason(problems)}))
    except Exception:  # fail open on anything unexpected
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
