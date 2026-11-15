#!/usr/bin/env python3
"""Standalone tests for the trial switch in verification_claim_gate.py. Run:

    python3 test_hook_trial.py

The switch is described in hook-trial/README.md at the top of the repository. With an
enabled trial file, the gate stays silent in sessions whose arm is "off"; with no trial
file, or any problem with it, the gate behaves as it always did.

Every case runs the gate as a subprocess with HOME set to a temporary directory and
CLAUDE_PROJECT_DIR and HOOK_TRIAL_IGNORE removed from its environment, so a trial file in
the real home directory cannot change the result. The scenario is one that blocks when
the gate is on: a claim of an end-to-end check in a turn that ran nothing.
Exit 0 when every case passes, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOK = Path(os.environ.get("CLAIM_GATE") or Path(__file__).resolve().parent / "verification_claim_gate.py")

SALT = "trial-salt-1"
OFF_SID = "00000000-0000-4000-8000-000000000001"  # arm "off" under SALT
ON_SID = "00000000-0000-4000-8000-000000000007"   # arm "on" under SALT

# (salt, session id, arm). The same vectors are pinned in the trial tests of all four
# hooks and of hook-trial/, so the hooks and the analysis agree on every session.
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

MISSING = object()


def _scenario(tmp: Path, sid) -> dict:
    """A Stop payload on which the gate blocks when it is on."""
    tp = tmp / "session.jsonl"
    events = [
        {"type": "user", "message": {"role": "user", "content": "rebuild the report"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Verified end-to-end: topology validates and auth works."}]}},
    ]
    tp.write_text("".join(json.dumps(e) + "\n" for e in events))
    work = tmp / "work"
    work.mkdir(exist_ok=True)
    payload = {"transcript_path": str(tp), "cwd": str(work), "hook_event_name": "Stop",
               "stop_hook_active": False}
    if sid is not MISSING:
        payload["session_id"] = sid
    return payload


def _fired(r: subprocess.CompletedProcess) -> bool:
    if not r.stdout.strip():
        return False
    try:
        return json.loads(r.stdout).get("decision") == "block"
    except (ValueError, AttributeError):
        return False


def _trial(directory: Path, content) -> None:
    """Write <directory>/.claude/hook-trial.json; a str is written as is, anything else as JSON."""
    d = directory / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    (d / "hook-trial.json").write_text(content if isinstance(content, str) else json.dumps(content))


def _run(tmp: Path, sid=OFF_SID, project: Path | None = None, cwd: Path | None = None,
         ignore: bool = False) -> subprocess.CompletedProcess:
    payload = _scenario(tmp, sid)
    if cwd is not None:
        payload["cwd"] = str(cwd)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "HOOK_TRIAL_IGNORE")}
    env["HOME"] = str(tmp / "home")
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    if ignore:
        env["HOOK_TRIAL_IGNORE"] = "1"
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), env=env,
                          capture_output=True, text=True, timeout=60)


def _case(setup, sid=OFF_SID, **kw) -> subprocess.CompletedProcess:
    """Run once in a fresh temporary tree; `setup(tmp)` writes trial files and returns kwargs."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "home").mkdir()
        extra = setup(tmp) or {}
        return _run(tmp, sid, **{**kw, **extra})


def _home(cfg):
    return lambda tmp: _trial(tmp / "home", cfg)


FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def main() -> int:
    on = {"enabled": True, "salt": SALT}
    today = datetime.now(timezone.utc).date()

    r = _case(lambda tmp: None)
    check("no trial file -> gate on (blocks)", _fired(r) and r.returncode == 0, r.stderr[-300:])

    r = _case(_home(on), sid=OFF_SID)
    check("enabled, session in the off arm -> silent, exit 0, nothing on stderr",
          not _fired(r) and r.returncode == 0 and not r.stdout.strip() and not r.stderr.strip(), r.stderr[-300:])
    r = _case(_home(on), sid=ON_SID)
    check("enabled, session in the on arm -> blocks", _fired(r))

    for salt, sid, arm in VECTORS:
        r = _case(_home({"enabled": True, "salt": salt}), sid=sid)
        check(f"vector {salt!r} {sid[-4:]} -> {arm}", _fired(r) == (arm == "on"))

    # Fail safe: anything wrong with the trial file means the gate behaves normally.
    for label, cfg in [
        ("enabled false", {"enabled": False, "salt": SALT}),
        ("enabled is the string 'true'", {"enabled": "true", "salt": SALT}),
        ("enabled missing", {"salt": SALT}),
        ("salt missing", {"enabled": True}),
        ("salt empty", {"enabled": True, "salt": ""}),
        ("salt a number", {"enabled": True, "salt": 7}),
        ("not JSON", "{enabled: true"),
        ("JSON array", "[true]"),
        ("empty file", ""),
        ("start in the future", {"enabled": True, "salt": SALT, "start": (today + timedelta(days=2)).isoformat()}),
        ("start not a date", {"enabled": True, "salt": SALT, "start": "15/11/2026"}),
        ("start a number", {"enabled": True, "salt": SALT, "start": 20261115}),
    ]:
        r = _case(_home(cfg), sid=OFF_SID)
        check(f"fail safe: {label} -> gate on", _fired(r) and r.returncode == 0, r.stderr[-300:])

    for label, start in [("in the past", today - timedelta(days=3)), ("today (UTC)", today)]:
        r = _case(_home({**on, "start": start.isoformat()}), sid=OFF_SID)
        check(f"start {label}, off arm -> silent", not _fired(r))

    def trial_is_directory(tmp: Path) -> None:
        (tmp / "home" / ".claude" / "hook-trial.json").mkdir(parents=True)
    r = _case(trial_is_directory)
    check("fail safe: trial path is a directory -> gate on", _fired(r) and r.returncode == 0)

    if os.geteuid() != 0:
        def unreadable(tmp: Path) -> None:
            _trial(tmp / "home", on)
            (tmp / "home" / ".claude" / "hook-trial.json").chmod(0)
        r = _case(unreadable)
        check("fail safe: trial file unreadable -> gate on", _fired(r) and r.returncode == 0)

    for label, sid in [("missing", MISSING), ("empty", ""), ("a number", 12345), ("null", None)]:
        r = _case(_home(on), sid=sid)
        check(f"fail safe: session id {label} -> gate on", _fired(r) and r.returncode == 0)

    # Where the trial file is looked for.
    def project_file(tmp: Path) -> dict:
        _trial(tmp / "proj", on)
        return {"project": tmp / "proj"}
    r = _case(project_file)
    check("trial file in $CLAUDE_PROJECT_DIR/.claude, off arm -> silent", not _fired(r))

    def cwd_file(tmp: Path) -> dict:
        _trial(tmp / "proj", on)
        return {"cwd": tmp / "proj"}
    r = _case(cwd_file)
    check("no CLAUDE_PROJECT_DIR: trial file in <cwd>/.claude, off arm -> silent", not _fired(r))

    def project_wins_over_cwd(tmp: Path) -> dict:
        (tmp / "proj").mkdir()
        _trial(tmp / "proj" / "sub", on)
        return {"project": tmp / "proj", "cwd": tmp / "proj" / "sub"}
    r = _case(project_wins_over_cwd)
    check("CLAUDE_PROJECT_DIR set: a trial file in a cd'd-into cwd is not read -> gate on", _fired(r))

    def project_disables(tmp: Path) -> dict:
        _trial(tmp / "home", on)
        _trial(tmp / "proj", {"enabled": False, "salt": SALT})
        return {"project": tmp / "proj"}
    r = _case(project_disables)
    check("project file (enabled false) decides over an enabled home file -> gate on", _fired(r))

    def home_fallback(tmp: Path) -> dict:
        (tmp / "proj").mkdir()
        _trial(tmp / "home", on)
        return {"project": tmp / "proj"}
    r = _case(home_fallback)
    check("no project file: ~/.claude/hook-trial.json is used, off arm -> silent", not _fired(r))

    r = _case(_home(on), ignore=True)
    check("HOOK_TRIAL_IGNORE=1 in the environment, off arm -> gate on", _fired(r))

    # replay.py asks what the gate would have done, so a running trial must not silence it.
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "home").mkdir()
        _trial(tmp / "home", on)
        proj = tmp / "projects" / "-work"
        proj.mkdir(parents=True)
        events = [
            {"type": "user", "cwd": str(tmp), "message": {"role": "user", "content": "rebuild the report"}},
            {"type": "assistant", "cwd": str(tmp), "message": {
                "id": "msg_1", "role": "assistant", "model": "claude-opus-5-5", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Verified end-to-end: topology validates and auth works."}]}},
        ]
        (proj / f"{OFF_SID}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "HOOK_TRIAL_IGNORE")}
        env["HOME"] = str(tmp / "home")
        r = subprocess.run([sys.executable, "-I", str(HOOK.with_name("replay.py")), "run", "--out", str(tmp / "out"),
                            "--label", "t", "--gate", str(HOOK), "--projects", str(tmp / "projects")],
                           env=env, capture_output=True, text=True, timeout=120)
        try:
            summary = json.loads((tmp / "out" / "summary-t.json").read_text())
        except (OSError, ValueError):
            summary = {}
        check("replay.py with an enabled trial file, off-arm session -> the gate still fires in the replay",
              summary.get("fired") == 1, r.stderr[-300:] or str(summary))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} case(s) FAILED")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
