#!/usr/bin/env python3
"""Keep a validation record for numerical results: one JSON line per check of one
result against an independent expectation. The tool decides pass or fail from the
numbers; it does no domain science.

  validate.py add --record FILE --name NAME --kind KIND --expected X --observed Y
                  (--abs-tol T | --rel-tol T | both) --units U [--note TEXT]
  validate.py convergence --pair H VALUE --pair H VALUE --pair H VALUE [...]
                  [--expected-order P] [--order-tol 0.2] [--record FILE --name NAME --units U]
  validate.py summary --record FILE

add: passes when |observed - expected| <= abs_tol, or <= rel_tol * |expected|; with
both, when within either. A relative tolerance alone is refused for expected 0. A NaN
or infinite observed value is recorded as a failure.

convergence: H is the grid spacing or step size (smaller is finer), with a constant
refinement ratio. Reports the observed order from each three successive values,
p = ln(|v1 - v2| / |v2 - v3|) / ln(r), and whether the successive differences shrink.

summary: prints the record; exits 1 if any check failed or the record is empty.

Exit codes: 0 pass; 1 a check failed (or convergence not shown); 2 refused or unreadable.
Python standard library only.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

KINDS = {
    "analytic": "a closed-form or exact value for this case",
    "limit": "a limiting or special case the general result must reduce to",
    "conservation": "a quantity that must be conserved or a constraint that must hold",
    "second-method": "the same quantity computed by an independent method or code",
    "refinement": "a finer grid, smaller step or more samples",
    "reference-data": "a published or measured value for this case",
    "other": "anything else; say what in --note",
}


class Refusal(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path: str, entry: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def judge(expected: float, observed: float, abs_tol: float | None, rel_tol: float | None) -> tuple[float, bool]:
    if abs_tol is None and rel_tol is None:
        raise Refusal("no tolerance: give --abs-tol, --rel-tol or both")
    for name, v in (("--abs-tol", abs_tol), ("--rel-tol", rel_tol)):
        if v is not None and not (math.isfinite(v) and v >= 0):
            raise Refusal(f"{name} must be a finite number >= 0")
    if not math.isfinite(expected):
        raise Refusal("the expected value must be finite")
    if abs_tol is None and expected == 0:
        raise Refusal("a relative tolerance is undefined when the expected value is zero; give --abs-tol")
    if not math.isfinite(observed):
        return math.nan, False
    diff = abs(observed - expected)
    allowed = max(abs_tol or 0.0, (rel_tol or 0.0) * abs(expected))
    return diff, diff <= allowed


def tol_text(e: dict) -> str:
    parts = []
    if e.get("abs_tol") is not None:
        parts.append(f"abs {e['abs_tol']:g}")
    if e.get("rel_tol") is not None:
        parts.append(f"rel {e['rel_tol']:g}")
    return " or ".join(parts) or "-"


def num(v, spec: str) -> str:
    return f"{v:{spec}}" if isinstance(v, (int, float)) and not isinstance(v, bool) else ("-" if v is None else str(v))


def line(e: dict) -> str:
    exp, obs, diff = num(e.get("expected"), ".10g"), num(e.get("observed"), ".10g"), num(e.get("diff"), ".3g")
    note = f"  ({e['note']})" if e.get("note") else ""
    return (f"{'PASS' if e.get('pass') else 'FAIL'}  {e.get('name')} [{e.get('kind')}]  expected {exp}  "
            f"observed {obs}  diff {diff}  tol {tol_text(e)}  units {e.get('units')}{note}")


def cmd_add(a) -> int:
    diff, ok = judge(a.expected, a.observed, a.abs_tol, a.rel_tol)
    entry = {"time": now(), "name": a.name, "kind": a.kind, "expected": a.expected,
             "observed": a.observed if math.isfinite(a.observed) else str(a.observed),
             "abs_tol": a.abs_tol, "rel_tol": a.rel_tol, "units": a.units,
             "diff": diff if math.isfinite(diff) else None, "pass": ok, "note": a.note}
    append(a.record, entry)
    print(line(entry))
    return 0 if ok else 1


def cmd_convergence(a) -> int:
    if a.record and not (a.name and a.units):
        raise Refusal("--record needs --name and --units")
    pts = sorted(((h, v) for h, v in a.pair), key=lambda p: -p[0])
    if len(pts) < 3:
        raise Refusal("need at least three (spacing, value) pairs")
    if any(h <= 0 or not math.isfinite(h) for h, _ in pts):
        raise Refusal("spacings must be positive and finite")
    if len({h for h, _ in pts}) != len(pts):
        raise Refusal("two pairs have the same spacing")
    ratios = [pts[i][0] / pts[i + 1][0] for i in range(len(pts) - 1)]
    r = ratios[0]
    if any(abs(x - r) > 1e-6 * r for x in ratios):
        raise Refusal(f"the refinement ratio is not constant ({', '.join(f'{x:.4g}' for x in ratios)}); "
                      "this formula needs a constant ratio")
    diffs = [pts[i][1] - pts[i + 1][1] for i in range(len(pts) - 1)]
    if any(not math.isfinite(v) for _, v in pts):
        shrinking, orders = False, []
    else:
        shrinking = all(abs(diffs[i + 1]) < abs(diffs[i]) for i in range(len(diffs) - 1))
        orders = [math.log(abs(diffs[i]) / abs(diffs[i + 1])) / math.log(r)
                  if diffs[i] != 0 and diffs[i + 1] != 0 else math.nan for i in range(len(diffs) - 1)]

    print(f"refinement ratio {r:.4g}")
    for h, v in pts:
        print(f"  h {h:<12.6g} value {v:.12g}")
    for i, d in enumerate(diffs):
        print(f"  difference {i + 1}: {d:.6g}")
    for i, p in enumerate(orders):
        print(f"  observed order from values {i + 1}-{i + 3}: {p:.2f}")
    sign_flips = sum(1 for i in range(len(diffs) - 1) if diffs[i] * diffs[i + 1] < 0)
    if sign_flips:
        print(f"  note: the differences change sign {sign_flips} time(s) (oscillating)")
    last = orders[-1] if orders else math.nan
    ok = shrinking and math.isfinite(last)
    if ok:
        err = abs(diffs[-1]) / (r ** last - 1) if last > 0 else math.nan
        print(f"converging: successive differences shrink; observed order {last:.2f}"
              + (f"; estimated error of the finest value {err:.3g}" if math.isfinite(err) else ""))
    else:
        print("not converging: successive differences do not shrink" if not shrinking else
              "not converging: no order can be computed (a difference is zero)")
    if a.expected_order is not None:
        agrees = ok and abs(last - a.expected_order) <= a.order_tol
        print(f"expected order {a.expected_order:g} (tolerance {a.order_tol:g}): "
              + ("agrees" if agrees else "does not agree"))
        ok = agrees
    if a.record:
        append(a.record, {"time": now(), "name": a.name, "kind": "refinement",
                          "expected": a.expected_order, "observed": last if math.isfinite(last) else None,
                          "abs_tol": a.order_tol if a.expected_order is not None else None, "rel_tol": None,
                          "units": a.units, "diff": abs(last - a.expected_order)
                          if a.expected_order is not None and math.isfinite(last) else None,
                          "pass": ok, "note": f"observed order of convergence; pairs {pts}"})
    return 0 if ok else 1


def cmd_summary(a) -> int:
    p = Path(a.record)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        print(f"cannot read {p}: {e}", file=sys.stderr)
        return 2
    entries = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            print(f"{p}:{n}: not a JSON line", file=sys.stderr)
            return 2
        if not isinstance(e, dict) or not isinstance(e.get("pass"), bool):
            print(f"{p}:{n}: not a validation entry", file=sys.stderr)
            return 2
        entries.append(e)
    if not entries:
        print(f"{p}: empty record: no result has been checked")
        return 1
    for e in entries:
        print(line(e))
    failed = [e for e in entries if not e["pass"]]
    print(f"{len(entries)} checks: {len(entries) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ad = sub.add_parser("add", help="record one check")
    ad.add_argument("--record", required=True)
    ad.add_argument("--name", required=True)
    ad.add_argument("--kind", required=True, choices=sorted(KINDS),
                    help="; ".join(f"{k}: {v}" for k, v in KINDS.items()))
    ad.add_argument("--expected", required=True, type=float)
    ad.add_argument("--observed", required=True, type=float)
    ad.add_argument("--abs-tol", type=float)
    ad.add_argument("--rel-tol", type=float)
    ad.add_argument("--units", required=True, help='units of expected and observed; "1" if dimensionless')
    ad.add_argument("--note", default="")
    cv = sub.add_parser("convergence", help="observed order of convergence from (spacing, value) pairs")
    cv.add_argument("--pair", nargs=2, type=float, action="append", required=True, metavar=("H", "VALUE"))
    cv.add_argument("--expected-order", type=float)
    cv.add_argument("--order-tol", type=float, default=0.2)
    cv.add_argument("--record")
    cv.add_argument("--name")
    cv.add_argument("--units")
    sm = sub.add_parser("summary", help="print the record; non-zero if any check failed or it is empty")
    sm.add_argument("--record", required=True)
    a = ap.parse_args(argv)
    try:
        return {"add": cmd_add, "convergence": cmd_convergence, "summary": cmd_summary}[a.cmd](a)
    except Refusal as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
