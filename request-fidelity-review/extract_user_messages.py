#!/usr/bin/env python3
"""Print every message the user actually typed in a Claude Code session.

Reads a session transcript (JSONL) and prints the user's own messages,
verbatim and in order, plus the user's answers to AskUserQuestion prompts.
Everything the harness put in the user's turn is left out: other tool results,
system reminders, hook output, subagent reports, task
notifications, messages from other sessions, local-command output, compaction
summaries, skill expansions, image captions, IDE context and interruption
markers.

It works by positive identification, not by a list of things to drop. A record
is kept only if it is one of:

1. a `type: "user"` record whose `origin.kind` is `"human"`, not a sidechain,
   not `isMeta`, not a compaction summary. Inside it, text blocks that consist
   entirely of an `<ide_opened_file>`, `<ide_selection>`, `<ide_diagnostics>`
   or `<system-reminder>` element are dropped (the IDE and harness add those),
   and image blocks are counted but not printed;
2. a slash command the user typed (`<command-name>/x</command-name>` with
   optional `<command-args>`), printed as `/x args`;
3. a shell command the user typed with `!` (`<bash-input>...</bash-input>`),
   printed as `! ...`;
4. a `queued_command` attachment whose origin is human (a message typed while
   Claude was working). When the same text is also recorded as a human message
   next to it, only one copy is printed;
5. the user's answer to an AskUserQuestion prompt. Claude Code records it as a
   tool result, so it is kept only when the record holds exactly one
   `tool_result` block, that block answers a `tool_use` named AskUserQuestion
   earlier in the same file (not in a sidechain), and `toolUseResult` holds the
   `questions` list and `answers` mapping. Printed per question: the question
   (labelled as the agent's words), the options the user chose, any text the
   user typed instead ("Other"), the user's note on that question, and any
   reply the user typed to the prompt as a whole. Option descriptions and
   previews are the agent's words and are not printed. A prompt with no answer,
   note or reply is excluded.

Anything else is excluded, including kinds this script has never seen. A
transcript with no `origin` fields at all predates that field, and a subagent
transcript holds no user messages; both are refused (exit 3) rather than
guessed at.

Usage:
    python3 extract_user_messages.py TRANSCRIPT.jsonl [--json] [--stats]
    python3 extract_user_messages.py --session SESSION_ID [--json] [--stats]

--session looks for ~/.claude/projects/*/SESSION_ID.jsonl. In a Claude Code
shell the current session's id is in $CLAUDE_CODE_SESSION_ID.

Exit codes: 0 ok, 2 cannot read, 3 transcript format not supported.
Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HARNESS_BLOCK = re.compile(
    r"\A\s*<(ide_opened_file|ide_selection|ide_diagnostics|system-reminder)>.*</\1>\s*\Z",
    re.DOTALL,
)
COMMAND = re.compile(
    r"\A\s*<command-name>(?P<name>[^<]*)</command-name>\s*"
    r"(?:<command-message>[^<]*</command-message>\s*)?"
    r"(?:<command-args>(?P<args>.*?)</command-args>\s*)?\Z",
    re.DOTALL,
)
BASH_INPUT = re.compile(r"\A<bash-input>(?P<cmd>.*)</bash-input>\Z", re.DOTALL)

ASK_TOOL = "AskUserQuestion"
# Claude Code's value for "no option chosen, but the user wrote a note".
NOTES_ONLY = "(notes only)"


def _origin_kind(rec: dict) -> str | None:
    o = rec.get("origin")
    if isinstance(o, dict):
        k = o.get("kind")
        return k if isinstance(k, str) else None
    return None


def _blocks(content) -> list:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return []


def _human_text(content) -> tuple[str, int, int]:
    """(typed text, images, dropped harness blocks) from a human record."""
    parts: list[str] = []
    images = dropped = 0
    for b in _blocks(content):
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "image":
            images += 1
        elif t == "text":
            text = b.get("text", "")
            if not isinstance(text, str):
                continue
            if HARNESS_BLOCK.match(text):
                dropped += 1
                continue
            parts.append(text)
    return "\n\n".join(parts), images, dropped


def _single_text(content) -> str | None:
    bl = [b for b in _blocks(content) if isinstance(b, dict)]
    if len(bl) == 1 and bl[0].get("type") == "text" and isinstance(bl[0].get("text"), str):
        return bl[0]["text"]
    return None


def ask_tool_ids(records: list[dict]) -> set[str]:
    """Ids of AskUserQuestion calls made by the main session's assistant."""
    ids: set[str] = set()
    for rec in records:
        if rec.get("type") != "assistant" or rec.get("isSidechain"):
            continue
        for b in _blocks((rec.get("message") or {}).get("content")):
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == ASK_TOOL:
                if isinstance(b.get("id"), str):
                    ids.add(b["id"])
    return ids


def _split_joined(s: str) -> list[str] | None:
    """Split a multi-select answer Claude Code joined with ", ". Parts that
    contain ", " or '"' are written as JSON strings. None if it does not parse."""
    parts: list[str] = []
    rest = s
    while True:
        if rest.startswith('"'):
            end, esc = -1, False
            for i in range(1, len(rest)):
                if esc:
                    esc = False
                elif rest[i] == "\\":
                    esc = True
                elif rest[i] == '"':
                    end = i
                    break
            if end == -1:
                return None
            try:
                parts.append(json.loads(rest[: end + 1]))
            except ValueError:
                return None
            rest = rest[end + 1 :]
        else:
            i = rest.find(", ")
            parts.append(rest if i == -1 else rest[:i])
            rest = "" if i == -1 else rest[i:]
        if not rest:
            return parts
        if not rest.startswith(", "):
            return None
        rest = rest[2:]


def _split_answer(answer, labels: set[str], multi: bool) -> tuple[list[str], list[str]]:
    """(options chosen, text typed instead) for one question's answer."""
    if answer is None or answer == "" or answer == NOTES_ONLY:
        return [], []
    if isinstance(answer, list):
        parts = [p for p in answer if isinstance(p, str)]
    elif not isinstance(answer, str):
        return [], []
    elif answer in labels:
        return [answer], []
    elif multi:
        parts = _split_joined(answer) or [answer]
        if not any(p in labels for p in parts):
            parts = [answer]
    else:
        return [], [answer]
    chosen: list[str] = []
    typed: list[str] = []
    run: list[str] = []
    for p in parts:
        if p in labels:
            if run:
                typed.append(", ".join(run))
                run = []
            chosen.append(p)
        else:
            run.append(p)
    if run:
        typed.append(", ".join(run))
    return chosen, typed


def _ask_answer(rec: dict, ts: str) -> tuple[str, dict | None]:
    """Classify a tool result that answers an AskUserQuestion call."""
    data = rec.get("toolUseResult")
    if not isinstance(data, dict):
        return "excluded: AskUserQuestion not answered (rejected or failed)", None
    questions = data.get("questions")
    answers = data.get("answers")
    if not isinstance(questions, list) or not isinstance(answers, dict):
        return "excluded: AskUserQuestion result of unknown shape", None
    notes_by_q = data.get("annotations") if isinstance(data.get("annotations"), dict) else {}

    seen: set[str] = set()
    out_qs: list[dict] = []
    asked = [qq for qq in questions if isinstance(qq, dict) and isinstance(qq.get("question"), str)]
    asked += [{"question": k} for k in answers if isinstance(k, str) and k not in {qq["question"] for qq in asked}]
    for qq in asked:
        text = qq["question"]
        if text in seen:
            continue
        seen.add(text)
        labels = {
            o["label"] for o in qq.get("options") or [] if isinstance(o, dict) and isinstance(o.get("label"), str)
        }
        chosen, typed = _split_answer(answers.get(text), labels, qq.get("multiSelect") is True)
        ann = notes_by_q.get(text)
        notes = ann.get("notes") if isinstance(ann, dict) else None
        notes = notes if isinstance(notes, str) and notes.strip() else None
        if chosen or typed or notes:
            out_qs.append({"question": text, "chosen": chosen, "typed": typed, "notes": notes})

    response = data.get("response")
    response = response if isinstance(response, str) and response.strip() else None
    if not out_qs and response is None:
        return "excluded: AskUserQuestion not answered", None

    lines: list[str] = []
    for qa in out_qs:
        lines.append(f"[agent asked] {qa['question']}")
        lines += [f"[user chose] {c}" for c in qa["chosen"]]
        lines += [f"[user typed] {t}" for t in qa["typed"]]
        if not qa["chosen"] and not qa["typed"]:
            lines.append("[no option chosen]")
        if qa["notes"]:
            lines.append(f"[user's note] {qa['notes']}")
    if response is not None:
        lines.append(f"[user's reply to the prompt] {response}")
    msg = {
        "kind": "answer",
        "timestamp": ts,
        "text": "\n".join(lines),
        "images": 0,
        "dropped_blocks": 0,
        "questions": out_qs,
        "response": response,
    }
    if data.get("afkTimeoutMs"):
        msg["timed_out"] = True
    if data.get("followUp") is True:
        msg["follow_up"] = True
    return "kept: answer to AskUserQuestion", msg


def classify(rec: dict, ask_ids: set[str] | frozenset = frozenset()) -> tuple[str, dict | None]:
    """(reason, message) for one record. message is None when excluded.

    ask_ids: ids of the session's AskUserQuestion calls (see ask_tool_ids);
    without them no tool result is kept."""
    t = rec.get("type")
    ts = rec.get("timestamp", "")

    if t == "attachment":
        a = rec.get("attachment")
        if isinstance(a, dict) and a.get("type") == "queued_command":
            if _origin_kind(a) == "human" and isinstance(a.get("prompt"), str):
                return "kept: queued human message", {
                    "kind": "queued",
                    "timestamp": a.get("timestamp", ts),
                    "text": a["prompt"],
                    "images": 0,
                    "dropped_blocks": 0,
                }
            return f"excluded: queued {a.get('commandMode') or _origin_kind(a) or 'command'}", None
        kind = a.get("type") if isinstance(a, dict) else None
        return f"excluded: attachment {kind or '?'}", None

    if t != "user":
        return f"excluded: record type {t}", None
    if rec.get("isSidechain"):
        return "excluded: sidechain (subagent)", None
    if rec.get("isCompactSummary") or rec.get("isVisibleInTranscriptOnly"):
        return "excluded: compaction summary", None
    if rec.get("isMeta"):
        kind = _origin_kind(rec)
        return f"excluded: meta{' (' + kind + ')' if kind else ''}", None

    content = (rec.get("message") or {}).get("content")
    bl = [b for b in _blocks(content) if isinstance(b, dict)]
    if bl and all(b.get("type") == "tool_result" for b in bl):
        if len(bl) == 1 and bl[0].get("tool_use_id") in ask_ids:
            return _ask_answer(rec, ts)
        return "excluded: tool result", None

    kind = _origin_kind(rec)
    if kind == "human":
        text, images, dropped = _human_text(content)
        if not text and not images:
            return "excluded: human record with no typed text", None
        return "kept: human message", {
            "kind": "message",
            "timestamp": ts,
            "text": text,
            "images": images,
            "dropped_blocks": dropped,
        }
    if kind is not None:
        return f"excluded: origin {kind}", None

    single = _single_text(content)
    if single is not None:
        m = COMMAND.match(single)
        if m:
            name = m.group("name").strip()
            args = (m.group("args") or "").strip()
            typed = name if name.startswith("/") else "/" + name
            return "kept: slash command", {
                "kind": "command",
                "timestamp": ts,
                "text": typed + (" " + args if args else ""),
                "images": 0,
                "dropped_blocks": 0,
            }
        m = BASH_INPUT.match(single.strip())
        if m:
            return "kept: shell command", {
                "kind": "shell",
                "timestamp": ts,
                "text": "! " + m.group("cmd"),
                "images": 0,
                "dropped_blocks": 0,
            }
        tag = re.match(r"\s*<([A-Za-z_-]+)", single)
        if tag:
            return f"excluded: <{tag.group(1)}>", None
        if single.startswith("[Request interrupted"):
            return "excluded: interruption marker", None
    return "excluded: user record without human origin", None


def read_records(path: Path) -> tuple[list[dict], int]:
    records: list[dict] = []
    bad = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                bad += 1
                continue
            if isinstance(rec, dict):
                records.append(rec)
            else:
                bad += 1
    return records, bad


def has_origin_fields(records: list[dict]) -> bool:
    return any(r.get("type") == "user" and "origin" in r for r in records)


def extract(records: list[dict]) -> tuple[list[dict], Counter]:
    """User messages in order, and a count of every classification."""
    out: list[dict] = []
    stats: Counter = Counter()
    ask_ids = ask_tool_ids(records)
    for rec in records:
        reason, msg = classify(rec, ask_ids)
        # A queued message and the record of the same message can both be
        # written; keep one, preferring the record.
        if msg is not None and out and out[-1]["text"] == msg["text"]:
            if msg["kind"] == "queued":
                reason, msg = "excluded: queued duplicate", None
            elif out[-1]["kind"] == "queued":
                out.pop()
                stats["kept: queued human message"] -= 1
                stats["excluded: queued duplicate"] += 1
        stats[reason] += 1
        if msg is not None:
            out.append(msg)
    return out, stats


def render_text(messages: list[dict], source: str) -> str:
    lines = [
        f"# Messages the user typed, from {source}: {len(messages)} message(s).",
        "# Extracted verbatim, in order. Lines starting with '-----' are added by the",
        "# extractor; everything between them is the user's text exactly as sent.",
        "# Exception: in an answer to questions the agent asked, each line starts with",
        "# a bracketed label added by the extractor; '[agent asked]' lines are the",
        "# agent's question, '[user chose]' lines are option labels the agent wrote",
        "# and the user picked, and the other labelled lines are the user's own text.",
        "",
    ]
    for i, m in enumerate(messages, 1):
        notes = []
        if m["kind"] == "answer":
            notes.append("answer to questions the agent asked (AskUserQuestion)")
            if m.get("timed_out"):
                notes.append("prompt timed out: selected, not submitted")
            if m.get("follow_up"):
                notes.append("user asked for more questions")
        elif m["kind"] == "command":
            notes.append("slash command")
        elif m["kind"] == "shell":
            notes.append("shell command typed with !")
        elif m["kind"] == "queued":
            notes.append("typed while Claude was working")
        if m["images"]:
            notes.append(f"{m['images']} image(s) attached, not shown")
        if m["dropped_blocks"]:
            notes.append(f"{m['dropped_blocks']} IDE/harness block(s) omitted")
        note = (" · " + " · ".join(notes)) if notes else ""
        lines.append(f"----- user message {i} of {len(messages)} · {m['timestamp']}{note} -----")
        lines.append(m["text"])
        lines.append("")
    return "\n".join(lines)


def _find_session(session_id: str) -> Path | None:
    base = Path.home() / ".claude" / "projects"
    hits = sorted(base.glob(f"*/{session_id}.jsonl"))
    return hits[0] if hits else None


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    show_stats = "--stats" in argv
    args = [a for a in argv if a not in ("--json", "--stats")]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2
    if args[0] == "--session":
        if len(args) < 2:
            print("--session needs a session id", file=sys.stderr)
            return 2
        path = _find_session(args[1])
        if path is None:
            print(f"no transcript found for session {args[1]}", file=sys.stderr)
            return 2
    else:
        path = Path(args[0])
    try:
        records, bad = read_records(path)
    except OSError as e:
        print(f"{path}: cannot read: {e}", file=sys.stderr)
        return 2
    users = [r for r in records if r.get("type") == "user"]
    if users and all(r.get("isSidechain") for r in users):
        print(
            f"{path}: every user record is a sidechain, so this is a subagent "
            "transcript. Its prompts were written by the agent that started it, "
            "not by the user. Pass the main session transcript instead.",
            file=sys.stderr,
        )
        return 3
    if not has_origin_fields(records):
        print(
            f"{path}: no user record carries an 'origin' field. Either this is a "
            "subagent transcript, an empty one, or it was written by a Claude Code "
            "version older than the one this extractor was checked against "
            "(2.1.322-2.1.325). Refusing to guess.",
            file=sys.stderr,
        )
        return 3
    messages, stats = extract(records)
    if as_json:
        print(json.dumps(messages, ensure_ascii=False, indent=1))
    else:
        print(render_text(messages, path.name))
    if show_stats:
        print(f"records read: {len(records)}, unparseable lines: {bad}", file=sys.stderr)
        for reason, n in sorted(stats.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {n:6d}  {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
