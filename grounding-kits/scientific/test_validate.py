#!/usr/bin/env python3
"""Standalone tests for validate.py. Run: python3 -I test_validate.py

VALIDATE=/path/to/other/validate.py runs the same cases against another copy.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(os.environ.get("VALIDATE") or Path(__file__).with_name("validate.py"))


def tool(*args):
    r = subprocess.run([sys.executable, "-I", str(TOOL), *map(str, args)], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def entries(path):
    p = Path(path)
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


def main() -> int:
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n       {detail[-400:]}" if not ok and detail else ""))
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as d:
        rec = Path(d) / "validation.jsonl"

        def add(name, expected, observed, *tol, kind="analytic", units="m"):
            return tool("add", "--record", rec, "--name", name, "--kind", kind, "--expected", expected,
                        "--observed", observed, "--units", units, *tol)

        code, out = add("abs inside", 1.0, 1.0004, "--abs-tol", 1e-3)
        check("absolute tolerance, inside -> pass recorded", code == 0 and entries(rec)[-1]["pass"] is True, out)
        code, out = add("abs outside", 1.0, 1.002, "--abs-tol", 1e-3)
        check("absolute tolerance, outside -> fail recorded, non-zero exit",
              code == 1 and entries(rec)[-1]["pass"] is False and "FAIL" in out, out)
        code, out = add("abs boundary", 2.0, 2.5, "--abs-tol", 0.5)
        check("absolute tolerance, difference equal to tolerance -> pass", code == 0 and entries(rec)[-1]["pass"] is True, out)
        code, out = add("rel inside", 1000.0, 1009.0, "--rel-tol", 0.01)
        check("relative tolerance, inside -> pass", code == 0 and entries(rec)[-1]["pass"] is True, out)
        code, out = add("rel outside", 1000.0, 1011.0, "--rel-tol", 0.01)
        check("relative tolerance, outside -> fail", code == 1 and entries(rec)[-1]["pass"] is False, out)
        code, out = add("rel negative expected", -50.0, -50.4, "--rel-tol", 0.01)
        check("relative tolerance uses |expected| -> pass for a negative expected value",
              code == 0 and entries(rec)[-1]["pass"] is True, out)
        code, out = add("both", 0.0, 1e-9, "--rel-tol", 0.01, "--abs-tol", 1e-8)
        check("expected zero with both tolerances -> decided by the absolute one",
              code == 0 and entries(rec)[-1]["pass"] is True, out)
        code, out = add("nan observed", 1.0, "nan", "--abs-tol", 1.0)
        check("observed NaN -> recorded as a failure, not refused", code == 1 and entries(rec)[-1]["pass"] is False, out)

        n = len(entries(rec))
        code, out = add("zero rel", 0.0, 1e-12, "--rel-tol", 0.01)
        check("expected zero with only a relative tolerance -> refused (exit 2), nothing written",
              code == 2 and "zero" in out and len(entries(rec)) == n, out)
        code, out = add("no tol", 1.0, 1.0)
        check("no tolerance -> refused (exit 2), nothing written", code == 2 and len(entries(rec)) == n, out)
        code, out = add("neg tol", 1.0, 1.0, "--abs-tol", -1)
        check("negative tolerance -> refused", code == 2 and len(entries(rec)) == n, out)
        code, out = add("nan expected", "nan", 1.0, "--abs-tol", 1)
        check("NaN expected value -> refused", code == 2 and len(entries(rec)) == n, out)
        code, out = tool("add", "--record", rec, "--name", "x", "--kind", "analytic", "--expected", 1,
                         "--observed", 1, "--abs-tol", 0.1)
        check("no --units -> refused", code != 0 and len(entries(rec)) == n, out)
        code, out = add("bad kind", 1.0, 1.0, "--abs-tol", 1, kind="vibes")
        check("unknown kind of check -> refused", code != 0 and len(entries(rec)) == n, out)

        e = entries(rec)[0]
        check("entry keeps name, kind, expected, observed, tolerance, units, difference",
              all(k in e for k in ("name", "kind", "expected", "observed", "abs_tol", "rel_tol", "units", "diff", "pass", "time")),
              json.dumps(e))

        code, out = tool("summary", "--record", rec)
        check("summary with a failed check -> exit 1, names the failures",
              code == 1 and "abs outside" in out and "rel outside" in out and "FAIL" in out
              and "nan observed" in out and "Traceback" not in out and "8 checks: 5 passed, 3 failed" in out, out)

    with tempfile.TemporaryDirectory() as d:
        rec = Path(d) / "v.jsonl"
        tool("add", "--record", rec, "--name", "ok", "--kind", "conservation", "--expected", 1.0,
             "--observed", 1.0, "--abs-tol", 1e-12, "--units", "J")
        code, out = tool("summary", "--record", rec)
        check("summary with all checks passing -> exit 0", code == 0 and "1 passed" in out, out)
        empty = Path(d) / "empty.jsonl"
        empty.write_text("")
        code, out = tool("summary", "--record", empty)
        check("summary of an empty record -> non-zero", code != 0 and "empty" in out.lower(), out)
        code, out = tool("summary", "--record", Path(d) / "missing.jsonl")
        check("summary of a missing record -> non-zero", code != 0, out)
        (Path(d) / "bad.jsonl").write_text("{not json\n")
        code, out = tool("summary", "--record", Path(d) / "bad.jsonl")
        check("summary of a malformed record -> non-zero", code != 0, out)

    # Convergence: v(h) = 3 + 0.5 h^2 is second order; v(h) = 3 + (-1)^k is not converging.
    pairs = []
    for h in (0.4, 0.2, 0.1, 0.05):
        pairs += ["--pair", h, 3 + 0.5 * h * h]
    code, out = tool("convergence", *pairs)
    check("second-order sequence -> observed order 2.00, differences shrink, exit 0",
          code == 0 and "2.00" in out and "converging" in out and "not converging" not in out, out)
    code, out = tool("convergence", *pairs, "--expected-order", 2)
    check("second-order sequence with --expected-order 2 -> agrees", code == 0 and "agrees" in out, out)
    code, out = tool("convergence", *pairs, "--expected-order", 4)
    check("second-order sequence with --expected-order 4 -> flagged, exit 1", code == 1 and "does not agree" in out, out)

    shuffled = ["--pair", 0.1, 3 + 0.5 * 0.01, "--pair", 0.4, 3 + 0.5 * 0.16, "--pair", 0.2, 3 + 0.5 * 0.04]
    code, out = tool("convergence", *shuffled)
    check("pairs given out of order -> sorted by resolution, order 2.00", code == 0 and "2.00" in out, out)

    bad = []
    for k, h in enumerate((0.4, 0.2, 0.1, 0.05)):
        bad += ["--pair", h, 3 + (-1) ** k]
    code, out = tool("convergence", *bad)
    check("oscillating sequence -> not converging, exit 1", code == 1 and "not converging" in out, out)
    grow = []
    for h in (0.4, 0.2, 0.1, 0.05):
        grow += ["--pair", h, 1 / h]
    code, out = tool("convergence", *grow)
    check("growing differences -> not converging, exit 1", code == 1 and "not converging" in out, out)

    code, out = tool("convergence", "--pair", 0.2, 1.0, "--pair", 0.1, 1.1)
    check("fewer than three pairs -> refused (exit 2)", code == 2, out)
    code, out = tool("convergence", "--pair", 0.4, 1.0, "--pair", 0.2, 1.1, "--pair", 0.15, 1.12)
    check("non-constant refinement ratio -> refused (exit 2)", code == 2 and "ratio" in out, out)

    with tempfile.TemporaryDirectory() as d:
        rec = Path(d) / "v.jsonl"
        code, out = tool("convergence", *pairs, "--expected-order", 2, "--record", rec, "--name", "grid", "--units", "m")
        e = entries(rec)
        check("convergence --record appends a refinement entry", code == 0 and len(e) == 1
              and e[0]["kind"] == "refinement" and e[0]["pass"] is True, out + json.dumps(e))
        code, out = tool("convergence", *bad, "--record", rec, "--name", "osc", "--units", "m")
        e = entries(rec)
        check("non-converging --record entry is a failure", len(e) == 2 and e[1]["pass"] is False, json.dumps(e))
        code, out = tool("summary", "--record", rec)
        check("summary after a failed convergence entry -> exit 1", code == 1, out)

    print("\nall cases passed" if not fails else f"\n{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
