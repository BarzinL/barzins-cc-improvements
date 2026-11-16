# Performance playbook

For work whose goal is to make code faster or use less memory. `measure.py` is in the
same directory as this file.

## Procedure

1. **Fix the workload before touching code.** Write down the command, the input, and how
   you will tell that the output is still correct. Use the same three after the change.
2. **Keep the current output.** Save what the unchanged program produces on that input,
   or name the test command that checks it. You need it at step 6.
3. **Measure before changing anything.**
   `python3 measure.py run --out-dir <scratchpad>/perf --name before --input <input id> -- <command>`.
   The default is 1 warm-up run and 10 timed runs. If the spread it prints is not small
   next to the change you hope for, use more runs.
4. **Profile before guessing where the time goes.** Optimise what the profile shows,
   not what looks slow when reading the code. Standard profilers, as their documentation
   gives them:
   - Python: `python -m cProfile -s cumulative script.py` (Python 3.15 names the module
     `profiling.tracing` and keeps `cProfile` as an alias).
     [src: https://docs.python.org/3/library/profiling.tracing.html | read: 2026-11-15 | status: source | loc: Command-line interface]
   - Go: `go test -cpuprofile cpu.prof -memprofile mem.prof -bench .`, then `go tool pprof cpu.prof`.
     [src: https://pkg.go.dev/runtime/pprof | read: 2026-11-15 | status: source | loc: package overview]
   - Node.js: `node --prof app.js`, then `node --prof-process isolate-0x...-v8.log > processed.txt`.
     [src: https://nodejs.org/en/learn/getting-started/profiling | read: 2026-11-15 | status: source]
   - Java: `java -XX:StartFlightRecording=duration=60s,filename=recording.jfr ...` (JDK Flight Recorder).
     [src: https://docs.oracle.com/en/java/javase/21/docs/specs/man/java.html | read: 2026-11-15 | status: source | loc: -XX:StartFlightRecording]
   - Native code on Linux (C, C++, Rust and others): `perf record ./program`, then `perf report`.
     [src: https://perfwiki.github.io/main/tutorial/ | read: 2026-11-15 | status: source | loc: Sampling with perf record; Sample analysis with perf report]
5. **Change one thing at a time,** so each measured difference has one cause.
6. **Check the output is still correct.** Compare with what you kept at step 2, or run
   the tests. `measure.py compare` says whether stdout is identical between the records;
   if the program's output varies from run to run, check correctness some other way. A
   speed-up that changes the result is a bug, not a speed-up.
7. **Measure after, with the identical command and input** (`--name after`), then
   `python3 measure.py compare <before record> <after record>`.
8. **Report** the command, the input, both medians, the ratio and its interval, the
   number of runs and the verdict, in those words. If the verdict is "not
   distinguishable", say so; do not round it into a speed-up.

## Mistakes to avoid

- Claiming a speed-up from one run each, or from a difference smaller than the spread.
  `compare` gives no verdict below 5 runs per record.
- Comparing across different inputs, flags, build modes (debug and release), or a cold
  cache against a warm one. `compare` refuses a different command or declared input; it
  cannot see the rest.
- Measuring before and after under different load on the machine, or far apart in time.
- Timing a run that failed. An early exit is fast. `measure.py` stops at the first failed
  run and writes no record.
- Optimising code the profile shows is not where the time goes.
- Timing a whole process when the work is a few milliseconds: start-up then dominates.
  Time the work inside the program, or give it a larger input.
- Reporting a micro-benchmark's ratio as the speed-up of the whole program.
- Loosening a test or a tolerance so the faster version passes.
