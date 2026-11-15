#!/usr/bin/env python3
"""Compare the two arms of a hook trial from recorded Claude Code transcripts.

During a trial, each of the four hooks that take part (verification-claim gate,
plan-reconciliation, placeholder-disclosure, task-grounding) stays silent in sessions
whose arm is "off" and works normally in sessions whose arm is "on". The arm is the
lowest bit of sha256(salt + ":" + session_id): 0 is on, 1 is off. The hooks record
nothing about the trial; this script recomputes each session's arm from its id and the
salt, and compares the arms:

1. sessions, turns, and output tokens per turn (main agent; subagents separately);
2. final messages with a completion claim the claim gate finds unsupported, judged by
   the gate given with --gate (imported, not copied), and how often the gate blocked;
3. hook firings visible in the transcript, per hook;
4. user follow-up messages per session (a rough proxy for corrections).

The unit is the session. Each figure has a 95% percentile bootstrap interval over
sessions (seeded), and so does the difference between the arms.

    python3 -I compare_arms.py --projects ~/.claude/projects --salt SALT --start 2026-11-16
    python3 -I compare_arms.py --trial-file ~/.claude/hook-trial.json --json

The transcript format is internal to Claude Code and changes between versions. Records
that cannot be read are counted by reason and reported, never guessed at. The output
holds only counts and rates, no message text and no session ids. Transcripts are data:
nothing in them is followed as an instruction. Run with `python3 -I`. Python standard
library only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the gate's directory

HERE = Path(__file__).resolve().parent
DEFAULT_GATE = HERE.parent / "theory-formation-discipline" / "verification-claim-gate" / "verification_claim_gate.py"
HOOKS = ("claim-gate", "plan-reconciliation", "placeholder-disclosure", "task-grounding")

# The opening words of each hook's own output. A hook's firing is recognised by these
# words in a record the harness wrote (an attachment, a stop-hook summary or a meta
# message), never in the user's or the model's own text.
SIGNATURES = {
    "claim-gate": "Send-time verification check.",
    "plan-reconciliation": "Plan check: the session plan",
    "placeholder-disclosure": "Placeholder check: this turn wrote placeholder code",
    "task-grounding": "Task routing (sent once per session per category",
}

_SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def arm(salt: str, session_id: str) -> str:
    """The trial arm of a session: the same rule as trial_arm in each hook."""
    digest = hashlib.sha256(f"{salt}:{session_id}".encode("utf-8")).digest()
    return "off" if digest[-1] & 1 else "on"


# ------------------------------------------------------------------ reading --

def _timestamp(rec: dict) -> datetime | None:
    t = rec.get("timestamp")
    if not isinstance(t, str):
        return None
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_records(path: Path, skipped: Counter) -> list[dict] | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        skipped["file unreadable"] += 1
        return None
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            skipped["line is not JSON"] += 1
            continue
        if not isinstance(rec, dict):
            skipped["line is not a JSON object"] += 1
            continue
        if not isinstance(rec.get("type"), str):
            skipped["record has no type"] += 1
            continue
        out.append(rec)
    return out


def _message(rec: dict) -> dict:
    m = rec.get("message")
    return m if isinstance(m, dict) else {}


def _blocks(rec: dict) -> list:
    c = _message(rec).get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _text(rec: dict) -> str:
    return "\n".join(b["text"] for b in _blocks(rec) if b.get("type") == "text" and isinstance(b.get("text"), str))


def _has(rec: dict, kind: str) -> bool:
    return any(b.get("type") == kind for b in _blocks(rec))


def output_tokens(records: list[dict], skipped: Counter, where: str) -> int:
    """Output tokens of the assistant messages, each message id counted once.

    One API message is written as several records (one per content block), each with
    the message's usage; the largest output_tokens among them is taken.
    """
    by_id: dict[str, int] = {}
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        m = _message(rec)
        mid = m.get("id")
        if not isinstance(mid, str) or not mid:
            skipped[f"{where}: assistant record without message.id (usage not counted)"] += 1
            continue
        usage = m.get("usage")
        n = usage.get("output_tokens") if isinstance(usage, dict) else None
        if not isinstance(n, int) or isinstance(n, bool):
            if mid not in by_id:
                skipped[f"{where}: assistant record without a numeric usage.output_tokens"] += 1
            continue
        by_id[mid] = max(by_id.get(mid, 0), n)
    return sum(by_id.values())


# -------------------------------------------------------------------- turns --

def _is_turn_start(rec: dict, markers: bool) -> bool:
    """A record that opens a turn. Current transcripts mark it with `turnPosition`; in
    older ones it is a user record that is not meta and carries text, not a tool result."""
    if rec.get("type") != "user" or rec.get("isCompactSummary"):
        return False
    if markers:
        return "turnPosition" in rec
    if rec.get("isMeta") or _has(rec, "tool_result"):
        return False
    return bool(_text(rec).strip())


def is_human_prompt(rec: dict, skipped: Counter) -> bool:
    """A message the user typed. Decided by the record's `origin.kind` or `turnOrigin`
    when present; otherwise by a rule (not meta, text, not a harness tag), counted."""
    if rec.get("type") != "user" or rec.get("isCompactSummary"):
        return False
    origin = rec.get("origin")
    if isinstance(origin, dict) and isinstance(origin.get("kind"), str):
        return origin["kind"] == "human"
    if isinstance(rec.get("turnOrigin"), str):
        return rec["turnOrigin"] == "human"
    if rec.get("isMeta") or _has(rec, "tool_result"):
        return False
    text = _text(rec).lstrip()
    if not text or text.startswith("<") or text.startswith("[Request interrupted"):
        return False
    skipped["user prompt judged human by rule (no origin field)"] += 1
    return True


def final_message(segment: list[dict]) -> tuple[str, int, str]:
    """(text, index of its last record, problem) for the final assistant message of a turn.

    The final message is the last assistant message (by message id) that has text, with
    no tool call after it. A turn the hook paused has an earlier message too; only the
    last one counts. `problem` is empty when a final message was found.
    """
    last_text = -1
    last_tool = -1
    for i, rec in enumerate(segment):
        if rec.get("type") != "assistant":
            continue
        if _has(rec, "tool_use"):
            last_tool = i
        if _text(rec).strip():
            last_text = i
    if last_tool > last_text:
        return "", -1, "turn ended on a tool call (interrupted, or the transcript is cut short)"
    if last_text < 0:
        return "", -1, "turn has no assistant text"
    rec = segment[last_text]
    if rec.get("isApiErrorMessage") or _message(rec).get("model") == "<synthetic>":
        return "", -1, "final message is an API error or synthetic"
    mid = _message(rec).get("id")
    if isinstance(mid, str) and mid:
        parts = [_text(r) for r in segment if r.get("type") == "assistant" and _message(r).get("id") == mid]
    else:
        parts = [_text(rec)]
    end = last_text
    for j in range(last_text + 1, len(segment)):
        if segment[j].get("type") == "assistant" and isinstance(mid, str) and _message(segment[j]).get("id") == mid:
            end = j
    return "\n".join(p for p in parts if p.strip()), end, ""


# ------------------------------------------------------------------ firings --

def _strings(v, depth: int = 0) -> list[str]:
    if isinstance(v, str):
        return [v]
    if depth > 4:
        return []
    if isinstance(v, list):
        return [s for x in v for s in _strings(x, depth + 1)]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x, depth + 1)]
    return []


def hook_output(rec: dict) -> tuple[str, list[str]] | None:
    """(source, texts) when the record is one the harness writes for a hook's output."""
    t = rec.get("type")
    if t == "attachment":
        a = rec.get("attachment")
        if isinstance(a, dict) and str(a.get("type", "")).startswith("hook"):
            return "attachment", _strings(a)
        return None
    if t == "system" and rec.get("subtype") == "stop_hook_summary":
        return "stop_hook_summary", _strings(rec.get("hookAdditionalContext"))
    if t == "user" and rec.get("isMeta"):
        text = _text(rec)
        if text.lstrip().startswith(("Stop hook feedback", "UserPromptSubmit hook")):
            return "meta message", [text]
    return None


def firings(records: list[dict]) -> Counter:
    """Firings per hook in these records. The same firing can appear in several kinds of
    record (a blocking-error attachment and a "Stop hook feedback" message), so per hook
    the count is the largest count found in any one kind of record."""
    per_source: dict[str, Counter] = {}
    for rec in records:
        out = hook_output(rec)
        if out is None:
            continue
        source, texts = out
        for hook, sig in SIGNATURES.items():
            if any(sig in s for s in texts):
                per_source.setdefault(source, Counter())[hook] += 1
    total = Counter()
    for hook in HOOKS:
        n = max((c[hook] for c in per_source.values()), default=0)
        if n:
            total[hook] = n
    return total


# ------------------------------------------------------------------ session --

def analyse_session(records: list[dict], judge, skipped: Counter) -> dict:
    markers = any(r.get("type") == "user" and "turnPosition" in r for r in records)
    starts = [i for i, r in enumerate(records) if _is_turn_start(r, markers)]
    conv_index = []  # for each record, how many user/assistant records up to and including it
    n = 0
    for r in records:
        if r.get("type") in ("user", "assistant"):
            n += 1
        conv_index.append(n)
    conv = [r for r in records if r.get("type") in ("user", "assistant")]
    s = {"turns": len(starts), "judged": 0, "unsupported": 0, "blocks": 0, "firings": Counter(),
         "human": sum(1 for r in records if is_human_prompt(r, skipped))}
    if starts:
        s["firings"] += firings(records[: starts[0]])
    for k, a in enumerate(starts):
        b = starts[k + 1] if k + 1 < len(starts) else len(records)
        seg = records[a:b]
        fired = firings(seg)
        s["firings"] += fired
        s["blocks"] += fired["claim-gate"]
        text, end, problem = final_message(seg)
        if problem:
            skipped[f"turn not judged: {problem}"] += 1
            continue
        try:
            problems = judge(conv[: conv_index[a + end]], text)
        except Exception as e:  # the gate fails open in a hook; here the failure is counted
            skipped[f"turn not judged: the gate raised {type(e).__name__}"] += 1
            continue
        s["judged"] += 1
        s["unsupported"] += 1 if problems else 0
    return s


def load_gate(path: Path):
    spec = importlib.util.spec_from_file_location("hook_trial_claim_gate", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load the claim gate from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    judge = getattr(module, "judge", None)
    if not callable(judge):
        raise SystemExit(f"{path} has no judge(events, text) function; use the gate from this repository "
                         "dated 2026-11-15 or later")
    return judge


def collect(projects: Path, salt: str, start: date, end: date | None, names: list[str] | None,
            judge) -> tuple[list[dict], Counter]:
    skipped: Counter = Counter()
    sessions = []
    dirs = sorted(p for p in projects.iterdir() if p.is_dir()) if projects.is_dir() else []
    if names:
        dirs = [d for d in dirs if d.name in names]
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) if end else None
    for d in dirs:
        try:
            files = sorted(d.glob("*.jsonl"))
        except OSError:
            skipped["project folder unreadable"] += 1
            continue
        for f in files:
            sid = f.stem
            if not _SESSION_ID.match(sid):
                skipped["file skipped: name is not a session id"] += 1
                continue
            records = read_records(f, skipped)
            if records is None:
                continue
            ids = {r.get("sessionId") for r in records if isinstance(r.get("sessionId"), str)}
            if ids - {sid}:
                skipped["session excluded: records carry another session id"] += 1
                continue
            times = [t for t in (_timestamp(r) for r in records) if t is not None]
            if not times:
                skipped["session excluded: no readable timestamp"] += 1
                continue
            first = min(times)
            if first < start_dt:
                skipped["session excluded: started before --start"] += 1
                continue
            if end_dt is not None and first >= end_dt:
                skipped["session excluded: started on or after --end"] += 1
                continue
            s = analyse_session(records, judge, skipped)
            if not s["turns"]:
                skipped["session excluded: no turns found"] += 1
                continue
            s["arm"] = arm(salt, sid)
            s["tokens"] = output_tokens(records, skipped, "main")
            sub = 0
            for sf in sorted((d / sid / "subagents").glob("*.jsonl")):
                srecs = read_records(sf, skipped)
                if srecs is not None:
                    sub += output_tokens(srecs, skipped, "subagent")
            s["sub_tokens"] = sub
            sessions.append(s)
    return sessions, skipped


# -------------------------------------------------------------- statistics --

def _ratio(rows: list[tuple[float, float]]) -> float | None:
    den = sum(b for _, b in rows)
    return sum(a for a, _ in rows) / den if den else None


def _interval(values: list[float]) -> tuple[float, float] | None:
    if len(values) < 20:
        return None
    values = sorted(values)
    lo = values[int(0.025 * (len(values) - 1))]
    hi = values[int(round(0.975 * (len(values) - 1)))]
    return lo, hi


def bootstrap(on: list[tuple[float, float]], off: list[tuple[float, float]], resamples: int,
              rng: random.Random) -> dict:
    """A ratio sum(a)/sum(b) per arm, its interval, and the interval of on - off.
    Sessions are resampled with replacement within each arm."""
    out = {"on": _ratio(on), "off": _ratio(off), "on_interval": None, "off_interval": None,
           "difference": None, "difference_interval": None}
    if out["on"] is not None and out["off"] is not None:
        out["difference"] = out["on"] - out["off"]
    if len(on) < 2 and len(off) < 2:
        return out
    draws = {"on": [], "off": [], "diff": []}
    for _ in range(resamples):
        r_on = _ratio([on[rng.randrange(len(on))] for _ in on]) if len(on) >= 2 else None
        r_off = _ratio([off[rng.randrange(len(off))] for _ in off]) if len(off) >= 2 else None
        if r_on is not None:
            draws["on"].append(r_on)
        if r_off is not None:
            draws["off"].append(r_off)
        if r_on is not None and r_off is not None:
            draws["diff"].append(r_on - r_off)
    out["on_interval"] = _interval(draws["on"])
    out["off_interval"] = _interval(draws["off"])
    out["difference_interval"] = _interval(draws["diff"])
    return out


METRICS = [
    # (key, label, numerator, denominator) per session
    ("turns_per_session", "turns per session", lambda s: s["turns"], lambda s: 1),
    ("tokens_per_turn", "output tokens per turn, main agent", lambda s: s["tokens"], lambda s: s["turns"]),
    ("sub_tokens_per_turn", "output tokens per turn, subagents", lambda s: s["sub_tokens"], lambda s: s["turns"]),
    ("unsupported_rate", "unsupported completion claims per judged turn", lambda s: s["unsupported"],
     lambda s: s["judged"]),
    ("blocks_per_turn", "claim-gate blocks per turn", lambda s: s["blocks"], lambda s: s["turns"]),
] + [
    (f"firings_{h}", f"{h} firings per turn", (lambda h: lambda s: s["firings"][h])(h), lambda s: s["turns"])
    for h in HOOKS
] + [
    ("followups_per_session", "user follow-up messages per session (rough)",
     lambda s: max(0, s["human"] - 1), lambda s: 1),
]


def summarise(sessions: list[dict], skipped: Counter, resamples: int, seed: int) -> dict:
    rng = random.Random(seed)
    by_arm = {a: [s for s in sessions if s["arm"] == a] for a in ("on", "off")}
    counts = {a: {"sessions": len(ss), "turns": sum(s["turns"] for s in ss),
                  "judged_turns": sum(s["judged"] for s in ss),
                  "unsupported_final_messages": sum(s["unsupported"] for s in ss),
                  "claim_gate_blocks": sum(s["blocks"] for s in ss),
                  "firings": {h: sum(s["firings"][h] for s in ss) for h in HOOKS},
                  "sessions_with_any_firing": sum(1 for s in ss if sum(s["firings"].values())),
                  "follow_up_messages": sum(max(0, s["human"] - 1) for s in ss),
                  "output_tokens_main": sum(s["tokens"] for s in ss),
                  "output_tokens_subagents": sum(s["sub_tokens"] for s in ss)}
              for a, ss in by_arm.items()}
    metrics = {}
    for key, label, num, den in METRICS:
        rows = {a: [(num(s), den(s)) for s in ss] for a, ss in by_arm.items()}
        metrics[key] = {"label": label, **bootstrap(rows["on"], rows["off"], resamples, rng)}
    return {"counts": counts, "metrics": metrics, "not_read": dict(sorted(skipped.items())),
            "resamples": resamples, "seed": seed}


def _fmt(v: float | None, iv) -> str:
    if v is None:
        return "-"
    s = f"{v:.3g}" if abs(v) < 1000 else f"{v:,.0f}"
    if iv:
        lo, hi = iv
        s += f" [{lo:.3g}, {hi:.3g}]" if max(abs(lo), abs(hi)) < 1000 else f" [{lo:,.0f}, {hi:,.0f}]"
    return s


def render(summary: dict, start: date, end: date | None) -> str:
    c = summary["counts"]
    lines = [
        f"Hook trial: sessions that started on or after {start.isoformat()} (UTC)"
        + (f" and before {end.isoformat()}" if end else "") + ".",
        f"Unit: the session. Intervals: 95% percentile bootstrap over sessions, {summary['resamples']} resamples, "
        f"seed {summary['seed']}; none with fewer than two sessions in an arm.",
        "",
        f"{'':52} {'on':>26} {'off':>26} {'on - off':>26}",
    ]
    for key in ("sessions", "turns", "judged_turns", "unsupported_final_messages", "claim_gate_blocks",
                "follow_up_messages", "output_tokens_main", "output_tokens_subagents"):
        lines.append(f"{key.replace('_', ' '):52} {c['on'][key]:>26} {c['off'][key]:>26}")
    for h in HOOKS:
        lines.append(f"{h + ' firings':52} {c['on']['firings'][h]:>26} {c['off']['firings'][h]:>26}")
    lines.append("")
    for m in summary["metrics"].values():
        lines.append(f"{m['label']:52} {_fmt(m['on'], m['on_interval']):>26} {_fmt(m['off'], m['off_interval']):>26} "
                     f"{_fmt(m['difference'], m['difference_interval']):>26}")
    if c["off"]["sessions_with_any_firing"]:
        lines += ["", f"WARNING: {c['off']['sessions_with_any_firing']} off-arm session(s) show a hook firing. "
                  "The switch did not hold there (a hook without the switch, a different salt or trial file, "
                  "or a session id the hooks saw differently); read the results with that in mind."]
    lines += ["", "Not read or not counted, by reason:"]
    lines += [f"  {k}: {v}" for k, v in summary["not_read"].items()] or ["  (nothing)"]
    return "\n".join(lines)


def _date(s: str) -> date:
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError(f"not a YYYY-MM-DD date: {s!r}")
    return date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--projects", default="~/.claude/projects", help="directory of per-project transcript folders")
    ap.add_argument("--project", action="append", help="only this project folder name (repeatable)")
    ap.add_argument("--salt", help="the trial's salt")
    ap.add_argument("--start", help="first day of the trial, YYYY-MM-DD (UTC)")
    ap.add_argument("--end", help="first day after the trial, YYYY-MM-DD (UTC); optional")
    ap.add_argument("--trial-file", help="read salt and start from this hook-trial.json")
    ap.add_argument("--gate", default=str(DEFAULT_GATE), help="path of verification_claim_gate.py")
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261115)
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = ap.parse_args(argv)

    salt, start = args.salt, args.start
    if args.trial_file:
        try:
            cfg = json.loads(Path(args.trial_file).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            ap.error(f"cannot read --trial-file: {e}")
        if not isinstance(cfg, dict):
            ap.error("--trial-file does not hold a JSON object")
        salt = salt or cfg.get("salt")
        start = start or cfg.get("start")
    if not isinstance(salt, str) or not salt:
        ap.error("a salt is needed (--salt, or --trial-file with a salt)")
    if not start:
        ap.error("a start date is needed (--start, or --trial-file with a start)")
    try:
        start_d = _date(start)
        end_d = _date(args.end) if args.end else None
    except ValueError as e:
        ap.error(str(e))
    if args.resamples < 0:
        ap.error("--resamples must be 0 or more")
    gate = Path(args.gate).expanduser()
    if not gate.is_file():
        ap.error(f"no claim gate at {gate}; give its path with --gate")
    judge = load_gate(gate)
    sessions, skipped = collect(Path(args.projects).expanduser(), salt, start_d, end_d, args.project, judge)
    summary = summarise(sessions, skipped, args.resamples, args.seed)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(render(summary, start_d, end_d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
