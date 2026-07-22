#!/usr/bin/env python3
"""Discipline compliance scanner (Increment 1: bright-line rules).

Reads Claude Code session transcripts and reports where standing bright-line
disciplines were violated. Deterministic, no LLM, no cost. The rule table is
data - add a rule by appending to RULES, not by changing the engine.

Usage:
    python3 scan.py                      # scan the default project transcripts
    python3 scan.py --project <dirname>  # a specific ~/.claude/projects/<dirname>
    python3 scan.py --all                # every project under ~/.claude/projects
    python3 scan.py --samples 5          # show up to N sample citations per rule
    python3 scan.py --max-mb 5           # skip transcripts larger than N MB

Exit status is 0 always (audit tool); use --strict to exit 1 when any rule fires
(for a pre-commit hook wrapper later).
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
DEFAULT_PROJECT = "-mnt-ultrakrill--gateway-src"


# --------------------------------------------------------------------------- #
# Rule model. A rule is data: a kind + patterns. The engine interprets it.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Rule:
    rule_id: str
    kind: str                 # 'bash_regex' | 'tool_name' | 'write_regex'
    why: str                  # one-line: which discipline this enforces
    pattern: str = ""         # regex for bash_regex / write_regex
    exclude: str = ""         # regex; if it also matches, the hit is suppressed
    tool: str = ""            # tool name for tool_name rules
    path_suffix: str = ""     # write_regex only: require the edited file end with this
    _rx: re.Pattern[str] | None = field(default=None, compare=False, repr=False)
    _ex: re.Pattern[str] | None = field(default=None, compare=False, repr=False)


def _compile(r: Rule) -> Rule:
    rx = re.compile(r.pattern) if r.pattern else None
    ex = re.compile(r.exclude) if r.exclude else None
    return Rule(r.rule_id, r.kind, r.why, r.pattern, r.exclude, r.tool,
                r.path_suffix, rx, ex)


# Initial rule set - CLAUDE.md "never do" list + memory feedback_* bright-lines.
RULES: list[Rule] = [_compile(r) for r in [
    Rule("em-dash-in-file", "write_regex",
         "CLAUDE.md: never write the em-dash; use '-'.",
         pattern="\u2014"),  # matches em-dash; keeps this file em-dash-free
    Rule("sqlite-not-readonly", "bash_regex",
         "CLAUDE.md: session DBs must use sqlite3 -readonly / immutable=1.",
         pattern=r"sqlite3\b(?=.*@sessions/)",
         exclude=r"-readonly|immutable=1"),
    Rule("ask-user-question", "tool_name",
         "CLAUDE.md: never use AskUserQuestion; list options inline.",
         tool="AskUserQuestion"),
    Rule("git-push", "bash_regex",
         "memory: repos are local-only, never push.",
         pattern=r"\bgit\s+push\b",
         exclude=r"print\(|echo\s|['\"].*git\s+push"),
    Rule("sudo-in-bash", "bash_regex",
         "CLAUDE.md: never run sudo via the Bash tool.",
         pattern=r"(?:^|[;&|]|\s)sudo\s",
         exclude=r"echo\s|#|print\(|boundary|the\ssudo"),
    Rule("shell-true", "write_regex",
         "CLAUDE.md: no subprocess shell=True, ever.",
         pattern=r"shell\s*=\s*True",
         exclude=r"`shell",
         path_suffix=".py"),
    Rule("pip-install", "bash_regex",
         "CLAUDE.md: use `uv add`, not pip install.",
         pattern=r"\bpip\s+install\b",
         exclude=r"uv\s+pip|--help"),
]]


# --------------------------------------------------------------------------- #
# Transcript walk. Yields (kind, name, text) for each tool call, where text is
# the Bash command (bash) or authored content (write) or "" (other).
# --------------------------------------------------------------------------- #
def iter_tool_calls(path: Path):
    """Yield (kind, name, text, file) per tool call. file is "" unless a write."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                name = b.get("name") or ""
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if name == "Bash":
                    yield "bash", name, str(inp.get("command", "")), ""
                elif name in ("Edit", "Write"):
                    text = str(inp.get("new_string", "")) + str(inp.get("content", ""))
                    yield "write", name, text, str(inp.get("file_path", ""))
                else:
                    yield "other", name, "", ""


def snippet(text: str, rx: re.Pattern[str] | None, width: int = 70) -> str:
    """A one-line context window around the first match, for eyeballing."""
    text = text.replace("\n", " ")
    if rx is not None:
        m = rx.search(text)
        if m:
            s = max(0, m.start() - width // 2)
            return text[s:s + width].strip()
    return text[:width].strip()


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
@dataclass
class Hit:
    file: str
    sample: str


def scan_file(path: Path) -> dict[str, list[Hit]]:
    hits: dict[str, list[Hit]] = {r.rule_id: [] for r in RULES}
    for kind, name, text, file in iter_tool_calls(path):
        for r in RULES:
            if not _fires(r, kind, name, text, file):
                continue
            rx = r._rx if r.kind in ("bash_regex", "write_regex") else None
            hits[r.rule_id].append(Hit(path.name, snippet(text, rx)))
    return hits


def _fires(r: Rule, kind: str, name: str, text: str, file: str) -> bool:
    if r.kind == "tool_name":
        return name == r.tool
    if r.kind == "bash_regex" and kind == "bash":
        return bool(r._rx and r._rx.search(text)
                    and not (r._ex and r._ex.search(text)))
    if r.kind == "write_regex" and kind == "write":
        if r.path_suffix and not file.endswith(r.path_suffix):
            return False
        return bool(r._rx and r._rx.search(text)
                    and not (r._ex and r._ex.search(text)))
    return False


def transcripts(args) -> list[Path]:
    roots = (sorted(PROJECTS.iterdir()) if args.all
             else [PROJECTS / (args.project or DEFAULT_PROJECT)])
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files += sorted(root.glob("*.jsonl"))
    if args.max_mb:
        cap = args.max_mb * 1_000_000
        files = [f for f in files if f.stat().st_size <= cap]
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="Bright-line discipline scanner")
    ap.add_argument("--project", help="project dir under ~/.claude/projects")
    ap.add_argument("--all", action="store_true", help="scan every project")
    ap.add_argument("--samples", type=int, default=3, help="sample citations per rule")
    ap.add_argument("--max-mb", type=float, default=0, help="skip files larger than N MB")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any rule fires")
    args = ap.parse_args()

    files = transcripts(args)
    if not files:
        print("no transcripts found")
        return 0

    totals: dict[str, int] = {r.rule_id: 0 for r in RULES}
    files_with: dict[str, set[str]] = {r.rule_id: set() for r in RULES}
    samples: dict[str, list[Hit]] = {r.rule_id: [] for r in RULES}
    for f in files:
        for rid, hs in scan_file(f).items():
            if hs:
                totals[rid] += len(hs)
                files_with[rid].add(f.name)
                for h in hs:
                    if len(samples[rid]) < args.samples:
                        samples[rid].append(h)

    by_id = {r.rule_id: r for r in RULES}
    ranked = sorted(RULES, key=lambda r: totals[r.rule_id], reverse=True)
    print(f"scanned {len(files)} transcripts\n")
    print(f"{'rule':<22}{'hits':>7}{'files':>7}")
    print("-" * 36)
    for r in ranked:
        print(f"{r.rule_id:<22}{totals[r.rule_id]:>7}{len(files_with[r.rule_id]):>7}")
    print()
    for r in ranked:
        if not totals[r.rule_id]:
            continue
        print(f"### {r.rule_id}  ({totals[r.rule_id]} raw hits) - {by_id[r.rule_id].why}")
        for h in samples[r.rule_id]:
            print(f"    {h.file[:12]}...  {h.sample!r}")
        print()

    any_hit = any(totals.values())
    return 1 if (args.strict and any_hit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
