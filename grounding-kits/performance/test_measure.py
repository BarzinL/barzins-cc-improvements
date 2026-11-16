#!/usr/bin/env python3
"""Standalone tests for measure.py. Run: python3 -I test_measure.py

MEASURE=/path/to/other/measure.py runs the same cases against another copy.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(os.environ.get("MEASURE") or Path(__file__).with_name("measure.py"))
PY = sys.executable
# A stand-in program whose speed is set by a file: changing the file is "changing the
# code", while the command line and the declared input stay the same.
PROG = "import sys,time; time.sleep(float(open(sys.argv[1]).read())); print('result 42')"


def tool(*args, cwd=None):
    r = subprocess.run([PY, "-I", str(TOOL), *map(str, args)], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def records(d):
    return sorted(p for p in Path(d).glob("*.json"))


def timed(d, delay, name, runs=5, extra=()):
    (Path(d) / "delay.txt").write_text(str(delay))
    code, out = tool("run", "--out-dir", Path(d) / "rec", "--name", name, "--runs", runs, "--warmup", 1,
                     "--input", "fixture-1", *extra, "--", PY, "-c", PROG, "delay.txt", cwd=d)
    return code, out


def newest(d, name):
    found = [p for p in records(Path(d) / "rec") if p.name.startswith(name + "-")]
    return found[-1] if found else None


def main() -> int:
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n       {detail[-400:]}" if not ok and detail else ""))
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as d:
        code, out = timed(d, 0.20, "before")
        rec = newest(d, "before")
        check("run writes one record under --out-dir", code == 0 and rec is not None, out)
        data = json.loads(rec.read_text()) if rec else {}
        check("record keeps the command, inputs, cwd (relative), timestamp and every sample",
              data.get("command", [])[-2:] == [PROG, "delay.txt"]
              and data.get("inputs") == ["fixture-1"] and "timestamp" in data
              and len(data.get("samples", [])) == 5 and not os.path.isabs(data.get("cwd", "/")), json.dumps(data)[:300])
        check("record's samples are about 0.2 s each",
              all(0.18 < s < 1.0 for s in data.get("samples", [0])), str(data.get("samples")))
        check("run prints median, spread and min", all(w in out for w in ("median", "min", "spread")), out)

        code, out = timed(d, 0.02, "after")
        after = newest(d, "after")
        code, out = tool("compare", rec, after)
        check("clear speed-up -> verdict faster", code == 0 and "verdict: faster" in out, out)
        check("compare reports ratio and an interval", "ratio" in out and "interval" in out, out)
        code, out = tool("compare", after, rec)
        check("clear slow-down -> verdict slower", code == 0 and "verdict: slower" in out, out)

        # Indistinguishable: two records of the same command whose samples overlap.
        base = json.loads(rec.read_text())
        a, b = dict(base), dict(base)
        a["samples"] = [1.00, 1.03, 0.97, 1.01, 0.99, 1.04, 0.96, 1.02]
        b["samples"] = [1.01, 0.98, 1.03, 0.99, 1.00, 0.97, 1.04, 1.02]
        pa, pb = Path(d) / "a.json", Path(d) / "b.json"
        pa.write_text(json.dumps(a))
        pb.write_text(json.dumps(b))
        code, out = tool("compare", pa, pb)
        check("overlapping samples -> not distinguishable", code == 0 and "not distinguishable" in out, out)

        # One run each is never enough, however large the difference looks.
        a["samples"], b["samples"] = [2.0], [1.0]
        pa.write_text(json.dumps(a))
        pb.write_text(json.dumps(b))
        code, out = tool("compare", pa, pb)
        check("one sample each -> not distinguishable, says too few runs",
              "not distinguishable" in out and "verdict: faster" not in out and "runs" in out, out)

        # Seeded bootstrap: the same comparison gives the same interval twice.
        _, o1 = tool("compare", rec, after)
        _, o2 = tool("compare", rec, after)
        check("bootstrap is seeded: same output twice", o1 == o2, o1 + "\n" + o2)

        # Mismatched command or inputs are refused unless told otherwise.
        c = dict(base)
        c["command"] = base["command"] + ["--fast"]
        pc = Path(d) / "c.json"
        pc.write_text(json.dumps(c))
        code, out = tool("compare", rec, pc)
        check("different commands -> refused (exit 2)", code == 2 and "command" in out and "verdict" not in out, out)
        code, out = tool("compare", rec, pc, "--allow-mismatch")
        check("different commands with --allow-mismatch -> compared, with a warning",
              code == 0 and "verdict" in out and "differ" in out, out)
        c = dict(base)
        c["inputs"] = ["fixture-2"]
        pc.write_text(json.dumps(c))
        code, out = tool("compare", rec, pc)
        check("different declared inputs -> refused (exit 2)", code == 2 and "input" in out, out)

        # Output changed by the change: reported.
        c = dict(base)
        c["stdout_sha256"] = "0" * 64
        pc.write_text(json.dumps(c))
        code, out = tool("compare", rec, pc)
        check("stdout differs between records -> compare says so", "stdout differs" in out, out)
        code, out = tool("compare", rec, after)
        check("same stdout -> compare says it is the same", "stdout identical" in out, out)

        # compare with --out-dir writes its result there.
        code, out = tool("compare", rec, after, "--out-dir", Path(d) / "rec")
        check("compare --out-dir writes a comparison record",
              code == 0 and any(p.name.startswith("compare-") for p in records(Path(d) / "rec")), out)

    with tempfile.TemporaryDirectory() as d:
        code, out = tool("run", "--out-dir", Path(d) / "rec", "--", PY, "-c", "import sys; print('boom', file=sys.stderr); sys.exit(3)")
        check("failing command -> reported as failed, non-zero exit, no record",
              code != 0 and "failed" in out and "exit code 3" in out and "boom" in out
              and not records(Path(d) / "rec"), out)
        code, out = tool("run", "--out-dir", Path(d) / "rec", "--", "no-such-program-xyz")
        check("missing program -> reported as failed, no record", code != 0 and "failed" in out
              and not records(Path(d) / "rec"), out)

    with tempfile.TemporaryDirectory() as d:
        code, out = tool("run", "--out-dir", Path(d) / "rec", "--name", "../escape", "--", PY, "-c", "pass")
        check("a --name that would leave the directory -> refused, nothing written",
              code == 2 and not list(Path(d).glob("*.json")) and not records(Path(d) / "rec"), out)
        code, out = tool("run", "--out-dir", Path(d) / "rec", "--runs", 0, "--", PY, "-c", "pass")
        check("--runs 0 -> refused", code == 2, out)

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "in.dat").write_text("abc")
        code, out = tool("run", "--out-dir", Path(d) / "rec", "--runs", 2, "--input-file", "in.dat",
                         "--", PY, "-c", "pass", cwd=d)
        data = json.loads(records(Path(d) / "rec")[0].read_text()) if code == 0 else {}
        check("--input-file records the file's path and sha256",
              any("in.dat" in i and "sha256:" in i for i in data.get("inputs", [])), out + json.dumps(data))

    if sys.platform.startswith("linux"):
        with tempfile.TemporaryDirectory() as d:
            code, out = tool("run", "--out-dir", Path(d) / "rec", "--runs", 2, "--memory",
                             "--", PY, "-c", "b = bytearray(100 * 1024 * 1024); b[::4096] = b'x' * len(b[::4096])")
            data = json.loads(records(Path(d) / "rec")[0].read_text()) if code == 0 else {}
            peaks = data.get("peak_rss_bytes", [])
            check("--memory records a peak RSS per run, above the 100 MiB allocated",
                  len(peaks) == 2 and all(p > 100 * 1024 * 1024 for p in peaks), out + str(peaks))

    print("\nall cases passed" if not fails else f"\n{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
