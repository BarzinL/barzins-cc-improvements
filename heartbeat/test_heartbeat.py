"""Checks for heartbeat.py (the registry and the hook). Run: python3 ~/.claude/skills/heartbeat/test_heartbeat.py
Each check uses its own temporary registry (HEARTBEAT_HOME), never the real one."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
SCRIPT = HERE / "heartbeat.py"


def run(home, *args, stdin=None):
    env = dict(os.environ, HEARTBEAT_HOME=str(home))
    p = subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


def hook(home, event, sid, source="compact"):
    return run(home, "hook", stdin=json.dumps({"hook_event_name": event, "session_id": sid, "source": source}))


def check_start_registers_and_the_hook_recreates_only_for_its_session():
    with tempfile.TemporaryDirectory() as h:
        f = Path(h) / "work.md"
        f.write_text("# goal\n")
        rc, out, err = run(h, "start", "work", "--session", "S1", "--file", str(f), "--cron", "7,27,47 * * * *")
        assert rc == 0, err
        reg = json.loads((Path(h) / "registry.json").read_text())
        assert reg["work"]["session"] == "S1" and reg["work"]["file"] == str(f) and not reg["work"]["paused"]
        _, out, _ = hook(h, "SessionStart", "S1")
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        assert "CronCreate" in ctx and "Heartbeat (work" in ctx and "7,27,47 * * * *" in ctx
        _, out, _ = hook(h, "SessionStart", "OTHER")
        assert out.strip() == "", "another session gets nothing"


def check_a_paused_heartbeat_is_not_recreated_and_resume_brings_it_back():
    with tempfile.TemporaryDirectory() as h:
        f = Path(h) / "work.md"
        f.write_text("x")
        run(h, "start", "work", "--session", "S1", "--file", str(f))
        assert run(h, "pause", "work")[0] == 0
        _, out, _ = hook(h, "SessionStart", "S1")
        assert out.strip() == "", "paused: nothing to recreate"
        run(h, "resume", "work")
        _, out, _ = hook(h, "SessionStart", "S1")
        assert "Heartbeat (work" in out


def check_precompact_asks_the_summary_for_state_and_for_the_log_when_one_is_set():
    with tempfile.TemporaryDirectory() as h:
        f, log = Path(h) / "work.md", Path(h) / "findings.md"
        f.write_text("x")
        log.write_text("y")
        run(h, "start", "work", "--session", "S1", "--file", str(f), "--log", str(log))
        _, out, _ = hook(h, "PreCompact", "S1")
        assert "HEARTBEAT STATE (work)" in out and "UNRECORDED (work)" in out and str(log) in out
        run(h, "start", "plain", "--session", "S2", "--file", str(f))
        _, out, _ = hook(h, "PreCompact", "S2")
        assert "HEARTBEAT STATE (plain)" in out and "UNRECORDED (plain)" not in out


def check_tick_counts_fires_and_calls_a_zoom_out_every_n():
    with tempfile.TemporaryDirectory() as h:
        f = Path(h) / "work.md"
        f.write_text("x")
        run(h, "start", "work", "--session", "S1", "--file", str(f), "--zoom-every", "3")
        got = [json.loads(run(h, "tick", "work")[1]) for _ in range(6)]
        assert [g["fire"] for g in got] == [1, 2, 3, 4, 5, 6]
        assert [g["zoom_out"] for g in got] == [False, False, True, False, False, True]


def check_a_paused_heartbeat_does_not_count_fires():
    with tempfile.TemporaryDirectory() as h:
        f = Path(h) / "work.md"
        f.write_text("x")
        run(h, "start", "work", "--session", "S1", "--file", str(f), "--zoom-every", "2")
        run(h, "tick", "work")
        run(h, "pause", "work")
        got = json.loads(run(h, "tick", "work")[1])
        assert got["paused"] is True and got["fire"] == 1 and got["zoom_out"] is False
        run(h, "resume", "work")
        assert json.loads(run(h, "tick", "work")[1])["fire"] == 2


def check_cadence_changes_only_the_cron():
    with tempfile.TemporaryDirectory() as h:
        f, log = Path(h) / "work.md", Path(h) / "findings.md"
        f.write_text("x")
        log.write_text("y")
        run(h, "start", "work", "--session", "S1", "--file", str(f), "--log", str(log), "--zoom-every", "4")
        run(h, "tick", "work")
        run(h, "renewed", "work", "--job", "J1")
        rc, out, err = run(h, "cadence", "work", "--cron", "17 * * * *")
        assert rc == 0, err
        assert json.loads(out)["was"] == "7,27,47 * * * *" and "Heartbeat (work" in json.loads(out)["prompt"]
        e = json.loads((Path(h) / "registry.json").read_text())["work"]
        assert (e["cron"], e["fires"], e["log"], e["zoom_every"], e["job"]) == ("17 * * * *", 1, str(log), 4, "J1")
        assert run(h, "cadence", "nothing", "--cron", "17 * * * *")[0] != 0


def check_a_job_six_days_old_is_due_for_renewal():
    with tempfile.TemporaryDirectory() as h:
        f = Path(h) / "work.md"
        f.write_text("x")
        run(h, "start", "work", "--session", "S1", "--file", str(f))
        reg_path = Path(h) / "registry.json"
        reg = json.loads(reg_path.read_text())
        reg["work"]["created"] = "2026-01-01"
        reg_path.write_text(json.dumps(reg))
        _, out, _ = run(h, "tick", "work", "--today", "2026-01-07")
        assert json.loads(out)["renew"] is True
        _, out, _ = run(h, "tick", "work", "--today", "2026-01-06")
        assert json.loads(out)["renew"] is False


def check_start_refuses_a_missing_file_and_an_unknown_name_fails():
    with tempfile.TemporaryDirectory() as h:
        rc, _, err = run(h, "start", "work", "--session", "S1", "--file", str(Path(h) / "absent.md"))
        assert rc != 0 and "absent.md" in err
        assert run(h, "pause", "nothing")[0] != 0


def check_the_hook_never_fails_a_session_on_bad_input():
    with tempfile.TemporaryDirectory() as h:
        rc, out, _ = run(h, "hook", stdin="not json")
        assert rc == 0 and out.strip() == ""


def _idle_file(h, sources, queue=("Wait for the operator's answer on X.",)):
    f = Path(h) / "work.md"
    f.write_text("## Queue\n\n" + "".join(f"{i}. {q}\n   detail line, not an item\n" for i, q in enumerate(queue, 1))
                 + "\n## Fallback work\n\n" + "".join(f"- {n}: `{c}`\n" for n, c in sources) + "\n## STATE\n")
    run(h, "start", "work", "--session", "S1", "--file", str(f))
    return f


def _paused(h):
    return json.loads((Path(h) / "registry.json").read_text())["work"]["paused"]


def check_idle_refuses_without_fallback_sources():
    with tempfile.TemporaryDirectory() as h:
        f = Path(h) / "work.md"
        f.write_text("## Queue\n\n1. x\n")
        run(h, "start", "work", "--session", "S1", "--file", str(f))
        rc, _, err = run(h, "idle", "work", "--blocked", "q1=waiting")
        assert rc != 0 and "Fallback work" in err and not _paused(h)


def check_idle_refuses_while_a_source_has_an_item_or_a_queue_item_is_unexplained():
    with tempfile.TemporaryDirectory() as h:
        _idle_file(h, [("review", "echo 27 commits since the last review"), ("index", "true")])
        rc, out, _ = run(h, "idle", "work", "--blocked", "q1=waiting on the operator")
        assert rc == 1 and "review: 27 commits" in out and not _paused(h)
        rc, out, _ = run(h, "idle", "work", "--blocked", "review=the operator is mid-deploy")
        assert rc == 1 and "q1: 1. Wait" in out and not _paused(h), "an unexplained queue item stays open"


def check_idle_refuses_when_a_source_fails_or_a_key_is_unknown():
    with tempfile.TemporaryDirectory() as h:
        _idle_file(h, [("broken", "exit 3")])
        rc, out, _ = run(h, "idle", "work", "--blocked", "q1=waiting")
        assert rc == 1 and "exit 3" in out and not _paused(h), "a source that cannot be read is not empty"
    with tempfile.TemporaryDirectory() as h:
        _idle_file(h, [("index", "true")])
        rc, _, err = run(h, "idle", "work", "--blocked", "q1=waiting", "--blocked", "q2=typo")
        assert rc != 0 and "q2" in err and not _paused(h)
        rc, _, err = run(h, "idle", "work", "--blocked", "q1=")
        assert rc != 0 and not _paused(h), "a block needs a reason"


def check_idle_pauses_with_its_evidence_when_nothing_is_left():
    with tempfile.TemporaryDirectory() as h:
        _idle_file(h, [("index", "true"), ("review", "echo one item")])
        rc, out, err = run(h, "idle", "work", "--blocked", "q1=waiting on the operator's answer",
                           "--blocked", "review=needs the operator's pick of scope")
        assert rc == 0, err + out
        res = json.loads(out)
        assert res["paused"] and _paused(h)
        assert "index 0" in res["state_line"] and "review 1" in res["state_line"] and "q1 (waiting" in res["state_line"]
        _, hk, _ = hook(h, "SessionStart", "S1")
        assert hk.strip() == "", "a self-paused heartbeat is not re-created"


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("check_"):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # report every check, then fail
                failed += 1
                print("FAIL", name, "-", type(e).__name__, e)
    sys.exit(1 if failed else 0)
