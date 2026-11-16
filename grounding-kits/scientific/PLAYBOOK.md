# Scientific and numerical playbook

For any computed scientific or numerical result, before reporting it. `validate.py` is
in the same directory as this file; record every check below with it
(`python3 validate.py add --record <scratchpad>/validation.jsonl ...`) and run
`python3 validate.py summary --record ...` before you report.

## Before reporting a result

1. **At least one independent check.** Compare the result with an expectation that does
   not come from the same code path. Kinds (`--kind` in `validate.py`):
   - `analytic`: a case with a closed-form answer; use it when one exists near your case.
   - `limit`: a limiting or special case the general result must reduce to (a parameter
     at zero, a symmetric case, a single particle).
   - `conservation`: a quantity that must be conserved or a constraint that must hold
     (total mass, energy, probability summing to one); use it for anything that evolves in
     time.
   - `second-method`: the same quantity by an independent method or code; use it when no
     exact answer exists.
   - `refinement`: a finer grid, smaller step or more samples; use it for anything
     discretised (step 3).
   - `reference-data`: a published or measured value for this case; cite where it came
     from in `--note`.
   Choose the tolerance before you look at the observed value, and say why it is that size.
2. **Units and dimensions.** State the unit of every input and output. Check that each
   formula is dimensionally consistent, and that values read from files or libraries are
   in the units you assume.
3. **Refinement for anything discretised.** Run at three or more resolutions with a
   constant ratio and pass them to `python3 validate.py convergence --pair H VALUE ...`.
   The differences must shrink, and the observed order should match the method's
   expected order (`--expected-order`). If they do not shrink, the result is not
   converged; say so.
4. **Stochastic results.** Fix and report the seed. Run with several seeds and report the
   spread, not one run's value.
5. **Fitted parameters.** Report each with an uncertainty (a standard error or an
   interval) and say how it was obtained. Check that the fit is identifiable: refit from
   different starting values, and fit data simulated with known parameters to see whether
   they are recovered. Strongly correlated or unrecovered parameters cannot be reported
   as measured.
6. **Data from files.** Before use, print the shape, column names, units, ranges and the
   count of missing values, and check them against what the analysis assumes.
7. **A failed check is reported as failed.** Do not adjust the tolerance, the expected
   value or the method until it passes. Report the failure, what you think causes it, and
   what would test that.

## When the method or domain is unfamiliar

1. **Stop before coding.** Look the method up in a primary source: the paper that
   defines it, the standard, or the library's own documentation. A summary, a search
   answer or your recollection is not enough for the formula, its constants or the
   conditions under which it holds.
2. **Record what you read** in the project's reference (`docs/reference/`), in the format
   of this repository's `reference-store/`: one entry with a `## Claims` section, each
   claim ending in a tag such as
   `[src: https://... | read: YYYY-MM-DD | status: source | loc: section 2]`, a row in
   `INDEX.md`, and a run of `check_reference.py` that reports no violations.
3. **Say in the answer which parts rest on that reading,** which on your own inference,
   and which were checked with `validate.py`.
