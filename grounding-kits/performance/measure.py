#!/usr/bin/env python3
"""Time a command repeatedly and keep a record; compare two records.

  measure.py run --out-dir DIR [--name NAME] [--warmup 1] [--runs 10] [--memory]
                 [--input ID ...] [--input-file PATH ...] [--timeout SECONDS] -- COMMAND ARGS...
  measure.py compare BEFORE.json AFTER.json [--allow-mismatch] [--seed 0]
                 [--resamples 2000] [--out-dir DIR]

`run` executes COMMAND (no shell; use `sh -c '...'` for a pipeline) in the current
directory, first --warmup times untimed, then --runs times timed, and writes one JSON
record to DIR. If any run exits non-zero the command is reported as failed and no record
is written. `compare` reports after/before as a ratio of medians, a seeded bootstrap
interval for it, and a verdict: faster, slower, or not distinguishable at this sample
size. It refuses records whose command or declared inputs differ, unless
--allow-mismatch is given.

Exit codes: 0 done; 1 the command failed; 2 usage error or refusal.
Python standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

MIN_RUNS_FOR_VERDICT = 5
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")


class Refusal(Exception):
    pass


def summarize(samples: list[float]) -> dict:
    s = sorted(samples)
    out = {"n": len(s), "median": statistics.median(s), "min": s[0], "max": s[-1]}
    if len(s) >= 2:
        q1, _, q3 = statistics.quantiles(s, n=4, method="inclusive")
        out["iqr"] = q3 - q1
    else:
        out["iqr"] = 0.0
    return out


def fmt(t: float) -> str:
    return f"{t * 1000:.1f} ms" if t < 1 else f"{t:.3f} s"


def peak_bytes(ru_maxrss: int) -> int:
    # getrusage reports ru_maxrss in kilobytes on Linux and the BSDs, in bytes on macOS.
    return ru_maxrss if sys.platform == "darwin" else ru_maxrss * 1024


def run_once(cmd: list[str], scratch: Path, timeout: float | None) -> tuple[int, float, int, bytes, bytes]:
    """Run cmd once. Returns (exit status, seconds, peak RSS bytes, stdout, stderr tail)."""
    with tempfile.TemporaryFile(dir=scratch) as out, tempfile.TemporaryFile(dir=scratch) as err:
        start = time.perf_counter()
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        timer = threading.Timer(timeout, p.kill) if timeout else None
        if timer:
            timer.start()
        try:
            _, status, ru = os.wait4(p.pid, 0)
        finally:
            if timer:
                timer.cancel()
        elapsed = time.perf_counter() - start
        p.returncode = os.waitstatus_to_exitcode(status)  # keep Popen from waiting again
        out.seek(0)
        err.seek(0)
        return p.returncode, elapsed, peak_bytes(ru.ru_maxrss), out.read(), err.read()[-2000:]


def file_id(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"{path} sha256:{h.hexdigest()}"


def target(out_dir: Path, stem: str) -> Path:
    if not _NAME.fullmatch(stem):
        raise Refusal(f"name {stem!r}: use letters, digits, '.', '_' or '-' only")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = out_dir / f"{stem}-{stamp}.json"
    if path.resolve().parent != out_dir.resolve():
        raise Refusal(f"{path} is outside {out_dir}")
    return path


def cmd_run(a) -> int:
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        raise Refusal("no command given; put it after --")
    if a.runs < 1 or a.warmup < 0:
        raise Refusal("--runs must be at least 1 and --warmup at least 0")
    out_dir = Path(a.out_dir)
    path = target(out_dir, a.name)  # checks the name before anything runs
    inputs = list(a.input or [])
    try:
        inputs += [file_id(f) for f in a.input_file or []]
    except OSError as e:
        raise Refusal(f"--input-file: {e}")

    samples, peaks, digests = [], [], set()
    total = a.warmup + a.runs
    for i in range(total):
        try:
            code, secs, peak, out, err = run_once(cmd, out_dir, a.timeout)
        except OSError as e:
            print(f"failed: could not start {cmd[0]!r}: {e}", file=sys.stderr)
            return 1
        if code != 0:
            what = f"killed by signal {-code}" if code < 0 else f"exit code {code}"
            phase = "warm-up" if i < a.warmup else "timed"
            print(f"failed: {phase} run {i + 1} of {total} ended with {what}; nothing timed or recorded.",
                  file=sys.stderr)
            if err.strip():
                print("stderr (last lines):\n" + err.decode("utf-8", "replace").rstrip(), file=sys.stderr)
            return 1
        if i >= a.warmup:
            samples.append(secs)
            peaks.append(peak)
            digests.add(hashlib.sha256(out).hexdigest())

    st = summarize(samples)
    record = {
        "tool": "measure.py", "version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": cmd,
        "cwd": os.path.relpath(Path.cwd(), out_dir.resolve()),
        "cwd_note": "working directory, relative to the directory holding this record",
        "inputs": inputs,
        "warmup": a.warmup, "runs": a.runs,
        "samples": samples,
        "stats": st,
        "stdout_sha256": next(iter(digests)) if len(digests) == 1 else None,
        "stdout_stable": len(digests) == 1,
        "platform": sys.platform,
    }
    if a.memory:
        record["peak_rss_bytes"] = peaks
    with open(path, "x", encoding="utf-8") as f:
        json.dump(record, f, indent=1)
        f.write("\n")
    print(f"{' '.join(cmd)}\n  runs {st['n']} (after {a.warmup} warm-up)  median {fmt(st['median'])}  "
          f"min {fmt(st['min'])}  max {fmt(st['max'])}  spread (IQR) {fmt(st['iqr'])}")
    if a.memory:
        print(f"  peak RSS median {statistics.median(peaks) / 2**20:.1f} MiB")
    if len(digests) > 1:
        print("  note: stdout differed between runs (output is not deterministic)")
    if a.runs < MIN_RUNS_FOR_VERDICT:
        print(f"  note: fewer than {MIN_RUNS_FOR_VERDICT} runs; compare will not give a verdict on this record")
    print(f"record: {path}")
    return 0


def load(path: str) -> dict:
    try:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Refusal(f"{path}: {e}")
    if not isinstance(rec, dict) or not isinstance(rec.get("samples"), list) or not rec["samples"]:
        raise Refusal(f"{path}: not a measure.py record with samples")
    return rec


def bootstrap(before: list[float], after: list[float], seed: int, n: int) -> tuple[float, float]:
    rng = random.Random(seed)
    ratios = sorted(statistics.median(rng.choices(after, k=len(after))) /
                    statistics.median(rng.choices(before, k=len(before))) for _ in range(n))
    return ratios[int(0.025 * (n - 1))], ratios[int(round(0.975 * (n - 1)))]


def cmd_compare(a) -> int:
    b, f = load(a.before), load(a.after)
    problems = [k for k in ("command", "inputs") if b.get(k) != f.get(k)]
    if problems and not a.allow_mismatch:
        for k in problems:
            print(f"refused: the {k} differs between the records:\n  before: {b.get(k)}\n  after:  {f.get(k)}",
                  file=sys.stderr)
        print("Measure both with the same command and input, or pass --allow-mismatch.", file=sys.stderr)
        return 2
    ratio = statistics.median(f["samples"]) / statistics.median(b["samples"])
    lo, hi = bootstrap(b["samples"], f["samples"], a.seed, a.resamples)
    nb, nf = len(b["samples"]), len(f["samples"])
    if min(nb, nf) < MIN_RUNS_FOR_VERDICT:
        verdict = f"not distinguishable at this sample size (fewer than {MIN_RUNS_FOR_VERDICT} runs in a record)"
    elif hi < 1:
        verdict = "faster"
    elif lo > 1:
        verdict = "slower"
    else:
        verdict = "not distinguishable at this sample size"
    lines = [
        f"before: median {fmt(statistics.median(b['samples']))} over {nb} runs ({a.before})",
        f"after:  median {fmt(statistics.median(f['samples']))} over {nf} runs ({a.after})",
        f"ratio after/before {ratio:.3f}, 95% bootstrap interval {lo:.3f} to {hi:.3f} "
        f"(seed {a.seed}, {a.resamples} resamples)",
    ]
    for k in problems:
        lines.append(f"warning: the {k} differs between the records (--allow-mismatch)")
    if b.get("cwd") != f.get("cwd"):
        lines.append("warning: the records were made from different working directories")
    sb, sf = b.get("stdout_sha256"), f.get("stdout_sha256")
    if sb and sf:
        lines.append("stdout identical" if sb == sf else
                     "stdout differs between before and after: check the result is still correct")
    else:
        lines.append("stdout not compared (not deterministic in one of the records)")
    if "peak_rss_bytes" in b and "peak_rss_bytes" in f:
        mb, mf = statistics.median(b["peak_rss_bytes"]), statistics.median(f["peak_rss_bytes"])
        lines.append(f"peak RSS median {mb / 2**20:.1f} MiB -> {mf / 2**20:.1f} MiB")
    lines.append(f"verdict: {verdict}")
    print("\n".join(lines))
    if a.out_dir:
        path = target(Path(a.out_dir), "compare")
        result = {"tool": "measure.py", "version": 1,
                  "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "before": a.before, "after": a.after, "ratio": ratio, "interval": [lo, hi],
                  "seed": a.seed, "resamples": a.resamples, "verdict": verdict, "mismatched": problems}
        with open(path, "x", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
            fh.write("\n")
        print(f"record: {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="time a command and write a record")
    r.add_argument("--out-dir", required=True, help="directory for records; nothing is written outside it")
    r.add_argument("--name", default="run", help="record file name prefix (default: run)")
    r.add_argument("--warmup", type=int, default=1)
    r.add_argument("--runs", type=int, default=10)
    r.add_argument("--memory", action="store_true", help="record peak resident memory of each timed run")
    r.add_argument("--input", action="append", help="an identifier for the input (repeatable)")
    r.add_argument("--input-file", action="append", help="an input file; its path and sha256 are recorded")
    r.add_argument("--timeout", type=float, help="kill a run after this many seconds (it then counts as failed)")
    r.add_argument("command", nargs=argparse.REMAINDER)
    c = sub.add_parser("compare", help="compare two records")
    c.add_argument("before")
    c.add_argument("after")
    c.add_argument("--allow-mismatch", action="store_true")
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--resamples", type=int, default=2000)
    c.add_argument("--out-dir", help="also write the comparison as a JSON record here")
    a = ap.parse_args(argv)
    try:
        return cmd_run(a) if a.cmd == "run" else cmd_compare(a)
    except Refusal as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
