#!/usr/bin/env python3
"""The heartbeat registry and its hook: the deterministic half of the heartbeat skill (SKILL.md is the other half).

A heartbeat is a session-only cron job that fires a fixed prompt into one Claude Code session, plus a plain-text file
holding that work's goal, checks, constraints and queue. Session-only jobs die with the session and recurring jobs
expire after 7 days, so this registry remembers each heartbeat and the hook tells its session to re-create the job
after a resume or a compaction. Nothing here creates cron jobs itself: only the session can (CronCreate).

  heartbeat.py start NAME --session ID --file PATH [--cron EXPR] [--log PATH] [--zoom-every N]
  heartbeat.py pause NAME | resume NAME | stop NAME | status
  heartbeat.py cadence NAME --cron EXPR   change only the cron (the session re-creates the job with it)
  heartbeat.py renewed NAME [--job ID]   the session re-created the job today (records its id for CronDelete)
  heartbeat.py tick NAME [--today DATE]  one fire: its number, whether a zoom-out is due, whether the job needs renewal
                                         (a paused heartbeat's fire is not counted)
  heartbeat.py idle NAME [--blocked KEY=REASON ...]
                                         pause by the agent's own decision, refused unless nothing is left: every
                                         queue item (q1, q2, ...) is named blocked with a reason, and every command
                                         under the file's "Fallback work" section ran cleanly and printed no item
                                         that is not named blocked. Prints the open items when it refuses (exit 1)
  heartbeat.py prompt NAME               the cron prompt to create
  heartbeat.py hook                      SessionStart / PreCompact hook (reads the hook's JSON on stdin)

The registry lives in $HEARTBEAT_HOME (default ~/.claude/heartbeats)/registry.json.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent
PROTOCOL = SKILL / "protocol.md"
HOME = Path(os.environ.get("HEARTBEAT_HOME", Path.home() / ".claude" / "heartbeats"))
REGISTRY = HOME / "registry.json"
RENEW_AFTER_DAYS = 6  # recurring cron jobs expire after 7 days; renew a day early


def load() -> dict:
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}


def save(reg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1, sort_keys=True))
    tmp.replace(REGISTRY)


def today(given: str | None = None) -> dt.date:
    return dt.date.fromisoformat(given) if given else dt.date.today()


def prompt(name: str, entry: dict, on: dt.date) -> str:
    return (f"Heartbeat ({name}, created {on.isoformat()}). Read {PROTOCOL} and then {entry['file']}, "
            f"and follow them.")


def entry_of(reg: dict, name: str) -> dict:
    if name not in reg:
        sys.exit(f"no heartbeat named {name!r}; registered: {', '.join(sorted(reg)) or 'none'}")
    return reg[name]


def cmd_start(a) -> None:
    f = Path(a.file).expanduser().resolve()
    if not f.exists():
        sys.exit(f"the heartbeat file {f} does not exist; write it from {SKILL / 'template.md'} first")
    if a.log and not Path(a.log).expanduser().exists():
        sys.exit(f"the knowledge log {a.log} does not exist")
    reg = load()
    reg[a.name] = {"session": a.session, "file": str(f), "cron": a.cron, "log": str(Path(a.log).expanduser().resolve()) if a.log else None,
                   "zoom_every": a.zoom_every, "paused": False, "fires": 0, "created": today().isoformat(), "job": None}
    save(reg)
    print(json.dumps({"name": a.name, "cron": a.cron, "prompt": prompt(a.name, reg[a.name], today())}))


def cmd_flag(a, paused: bool) -> None:
    reg = load()
    entry_of(reg, a.name)["paused"] = paused
    save(reg)
    print(json.dumps({"name": a.name, "paused": paused, "job": reg[a.name]["job"]}))


def cmd_stop(a) -> None:
    reg = load()
    gone = reg.pop(a.name, None) or entry_of(reg, a.name)
    save(reg)
    print(json.dumps({"stopped": a.name, "job": gone["job"]}))


def cmd_status(a) -> None:
    print(json.dumps(load(), indent=1, sort_keys=True))


def cmd_cadence(a) -> None:
    """A new cron for a running heartbeat, keeping its fires, log and zoom-out interval
    (starting it again would reset them). The session then replaces the job and runs
    `renewed` with the new job's id."""
    reg = load()
    e = entry_of(reg, a.name)
    old, e["cron"] = e["cron"], a.cron
    save(reg)
    print(json.dumps({"name": a.name, "cron": a.cron, "was": old, "job": e["job"], "prompt": prompt(a.name, e, today())}))


def cmd_renewed(a) -> None:
    reg = load()
    e = entry_of(reg, a.name)
    e["created"], e["job"] = today().isoformat(), a.job or e["job"]
    save(reg)
    print(json.dumps({"name": a.name, "created": e["created"], "job": e["job"]}))


def cmd_tick(a) -> None:
    reg = load()
    e = entry_of(reg, a.name)
    if not e["paused"]:  # a fire of a job left running during a pause is not one of the work's
        e["fires"] += 1
        save(reg)
    age = (today(a.today) - dt.date.fromisoformat(e["created"])).days
    print(json.dumps({"fire": e["fires"], "zoom_out": e["fires"] % e["zoom_every"] == 0, "renew": age >= RENEW_AFTER_DAYS,
                      "paused": e["paused"], "file": e["file"], "log": e["log"]}))


FALLBACK = re.compile(r"-\s+([\w.-]+):\s+`?(.+?)`?\s*$")
SHOWN = 5  # open items printed per source; the rest are counted


def sections(text: str) -> dict:
    """The file's "## Title" sections as lists of their lines."""
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = out.setdefault(line[3:].strip(), [])
        elif cur is not None:
            cur.append(line)
    return out


def cmd_idle(a) -> None:
    """The agent's self-pause. Whether work is left is decided by running the file's fallback sources and naming
    each queue item's blocker, not by the agent's impression, and the STATE line it prints records the evidence."""
    reg = load()
    e = entry_of(reg, a.name)
    secs = sections(Path(e["file"]).read_text())
    sources = [m.groups() for line in secs.get("Fallback work", []) if (m := FALLBACK.match(line.strip()))]
    if not sources:
        sys.exit(f"{e['file']} has no command under '## Fallback work' ('- NAME: COMMAND', one item per output line); "
                 "a heartbeat cannot pause itself without them, only the operator can pause it")
    blocked = {}
    for b in a.blocked:
        key, sep, reason = b.partition("=")
        if not sep or not reason.strip():
            sys.exit(f"--blocked takes KEY=REASON with a reason, got {b!r}")
        blocked[key] = reason.strip()
    queue = [line.strip() for line in secs.get("Queue", []) if re.match(r"\d+\.\s", line)]
    keys = {f"q{i}" for i in range(1, len(queue) + 1)} | {n for n, _ in sources}
    if unknown := sorted(set(blocked) - keys):
        sys.exit(f"--blocked names {unknown}, which are neither queue items ({len(queue)}) nor sources")
    open_ = [f"q{i}: {item}" for i, item in enumerate(queue, 1) if f"q{i}" not in blocked]
    counts = {}
    for name, cmd in sources:
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=a.timeout)
        except subprocess.TimeoutExpired:
            open_.append(f"{name}: the command did not finish in {a.timeout} s")
            continue
        if p.returncode:  # a source that cannot be read is not an empty one
            open_.append(f"{name}: the command failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-200:]}")
            continue
        items = [line.strip() for line in p.stdout.splitlines() if line.strip()]
        counts[name] = len(items)
        if items and name not in blocked:
            open_ += [f"{name}: {i}" for i in items[:SHOWN]] + ([f"{name}: and {len(items) - SHOWN} more"] if len(items) > SHOWN else [])
    if open_:
        print(json.dumps({"paused": False, "open": open_}, indent=1))
        sys.exit(1)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    e["paused"], e["idle_pause"] = True, {"at": now, "sources": counts, "blocked": blocked}
    save(reg)
    state = (f"{now} paused itself, no independent work left. Sources: "
             + ", ".join(f"{n} {c}" for n, c in counts.items())
             + (". Blocked: " + "; ".join(f"{k} ({v})" for k, v in blocked.items()) if blocked else "") + ".")
    print(json.dumps({"paused": True, "job": e["job"], "state_line": state}))


def cmd_prompt(a) -> None:
    reg = load()
    print(prompt(a.name, entry_of(reg, a.name), today()))


def cmd_hook(a) -> None:
    """Never fails the session: bad input or no match prints nothing."""
    try:
        data = json.loads(sys.stdin.read())
        sid, event = data.get("session_id", ""), data.get("hook_event_name", "")
        mine = {n: e for n, e in load().items() if e["session"] == sid and not e["paused"]}
    except Exception:
        return
    if not mine:
        return
    if event == "SessionStart":
        lines = ["Heartbeats registered for this session. Before anything else, silently: run CronList, and for each "
                 "heartbeat below with no job whose prompt starts with 'Heartbeat (NAME,', CronCreate it (recurring, "
                 f"durable false, the cron and prompt given), then run `python3 {SKILL / 'heartbeat.py'} renewed NAME "
                 "--job JOB_ID`. Then read each heartbeat's file before other work on it."]
        for n, e in mine.items():
            lines.append(f"- {n}: cron '{e['cron']}', prompt: {prompt(n, e, today())}" + (f" Knowledge log: {e['log']}." if e["log"] else ""))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(lines)}}))
    elif event == "PreCompact":
        for n, e in mine.items():
            print(f'Heartbeat {n} (required section of the summary). Add a section titled "HEARTBEAT STATE ({n})": what was '
                  f"done since the last STATE line in {e['file']} that the file does not record, what is running or "
                  "waiting (names, ids, expected end), and the next step, in plain language.")
            if e["log"]:
                print(f'Also add a section titled "UNRECORDED ({n})": every result, refutation, insight or change of '
                      f"direction from this conversation that {e['log']} does not already state, one line each, with "
                      "its evidence (run, commit or file), and the reason the work is being done.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("name")
    s.add_argument("--session", default=os.environ.get("CLAUDE_CODE_SESSION_ID"))
    s.add_argument("--file", required=True)
    s.add_argument("--cron", default="7,27,47 * * * *")
    s.add_argument("--log")
    s.add_argument("--zoom-every", type=int, default=6)
    for c in ("pause", "resume", "stop", "prompt"):
        sub.add_parser(c).add_argument("name")
    sub.add_parser("status")
    c = sub.add_parser("cadence")
    c.add_argument("name")
    c.add_argument("--cron", required=True)
    r = sub.add_parser("renewed")
    r.add_argument("name")
    r.add_argument("--job")
    i = sub.add_parser("idle")
    i.add_argument("name")
    i.add_argument("--blocked", action="append", default=[], metavar="KEY=REASON")
    i.add_argument("--timeout", type=int, default=120)
    t = sub.add_parser("tick")
    t.add_argument("name")
    t.add_argument("--today")
    sub.add_parser("hook")
    a = p.parse_args()
    if a.cmd == "start" and not a.session:
        sys.exit("no session id: pass --session or run inside Claude Code (CLAUDE_CODE_SESSION_ID)")
    {"start": cmd_start, "pause": lambda a: cmd_flag(a, True), "resume": lambda a: cmd_flag(a, False), "stop": cmd_stop,
     "status": cmd_status, "cadence": cmd_cadence, "renewed": cmd_renewed, "tick": cmd_tick, "idle": cmd_idle, "prompt": cmd_prompt, "hook": cmd_hook}[a.cmd](a)


if __name__ == "__main__":
    main()
