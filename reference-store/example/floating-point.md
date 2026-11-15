# Floating point in Python

Scope: how Python floats store decimal values, how large the rounding error is, and
which standard-library tools compare or sum floats. Compiled 2026-11-14 from the
Python 3.15 tutorial chapter on floating point.

## Claims

- On almost all platforms Python floats are IEEE 754 binary64 ("double precision")
  values, which carry 53 bits of precision.
  [src: https://docs.python.org/3/tutorial/floatingpoint.html | read: 2026-11-14 | status: source | loc: §15.1 Representation Error]
- The decimal 0.1 has no exact binary representation; the float stored for it is
  3602879701896397 / 2**55.
  [src: https://docs.python.org/3/tutorial/floatingpoint.html | read: 2026-11-14 | status: source | loc: §15]
- `0.1 + 0.1 + 0.1 == 0.3` is `False`, and `math.isclose(0.1 + 0.1 + 0.1, 0.3)` is `True`.
  [src: https://docs.python.org/3/tutorial/floatingpoint.html | read: 2026-11-14 | status: source | loc: §15]
- On most machines the error of one float operation is no more than about 1 part in
  2**53, and every operation can add a new rounding error.
  [src: https://docs.python.org/3/tutorial/floatingpoint.html | read: 2026-11-14 | status: source | loc: §15]
- In the Python 3.15 documentation, `sum()` uses extended precision for intermediate
  steps, so `sum([0.1] * 10) == 1.0` is `True` while ten chained `+ 0.1` additions are
  not equal to `1.0`.
  [src: https://docs.python.org/3/tutorial/floatingpoint.html | read: 2026-11-14 | status: source | loc: §15]
- `math.fsum()` tracks the digits lost during addition so the total is rounded once;
  it is slower than `sum()` and more accurate when large inputs mostly cancel.
  [src: https://docs.python.org/3/tutorial/floatingpoint.html | read: 2026-11-14 | status: source | loc: §15]
- Because each addition rounds, adding the same floats in a different order can give a
  different total, so a reordered or parallel sum should be compared with a serial
  one by tolerance, not by `==`.
  [src: https://docs.python.org/3/tutorial/floatingpoint.html | read: 2026-11-14 | status: inferred | loc: drawn from §15, not stated there]
