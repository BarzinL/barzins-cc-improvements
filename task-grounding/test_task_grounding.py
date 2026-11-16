#!/usr/bin/env python3
"""Standalone tests for task_grounding.py. Run: python3 test_task_grounding.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# TASK_GROUNDING lets the same cases run against another copy of the hook (an older version).
HOOK = Path(os.environ.get("TASK_GROUNDING") or Path(__file__).with_name("task_grounding.py"))
REPO_CHECKER = Path(__file__).resolve().parent.parent / "reference-store" / "check_reference.py"


def run(prompt, scratch=None, raw=None, extra=None, hook=None):
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": prompt}
    if scratch:
        payload["scratchpad_dir"] = scratch
    payload.update(extra or {})
    r = subprocess.run([sys.executable, str(hook or HOOK)], input=raw if raw is not None else json.dumps(payload),
                       capture_output=True, text=True)
    ctx = ""
    if r.stdout.strip():
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    return r.returncode, ctx


def main() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    cases = [
        ("performance prompt -> measure-before-and-after directive",
         "The importer is too slow on large files, can you optimise the parsing loop?", "Performance work"),
        ("visual prompt -> render-and-look directive",
         "Please match the settings page to the mockup I attached, the layout is off.", "Visual work"),
        ("scientific prompt -> grounding directive with bold caveat",
         "Write a simulation of methylation drift across cell divisions and fit it.", "Scientific or numerical work"),
        ("numbered multi-step prompt -> plan file directive",
         "Do these in order:\n1. add the config loader\n2. wire it into main\n3. write the tests", "Multi-step work"),
    ]
    for name, prompt, want in cases:
        with tempfile.TemporaryDirectory() as d:
            code, ctx = run(prompt, d)
            check(name, code == 0 and want in ctx)

    with tempfile.TemporaryDirectory() as d:
        code, ctx = run("Rename the variable foo to bar in the config module please.", d)
        check("plain coding prompt -> silent", code == 0 and ctx == "")
        code, ctx = run("thanks, that works", d)
        check("short prompt -> silent", ctx == "")
        code, ctx = run("<task-notification>the benchmark agent finished optimising the layout</task-notification>", d)
        check("harness-tagged input -> silent", ctx == "")
        code, ctx = run("/loop 5m check whether the benchmark run has finished and optimise", d)
        check("slash command -> silent", ctx == "")
        code, ctx = run("Why does this fail?\n```\nerror: benchmark render simulation optimise layout\n```\nIt is in the config loader.", d)
        check("category words only inside pasted code -> silent", ctx == "")

    with tempfile.TemporaryDirectory() as d:
        p = "Can you optimise the hot path in the tokenizer? It is the bottleneck."
        _, first = run(p, d)
        _, second = run(p, d)
        check("same category twice in a session -> sent once", "Performance work" in first and second == "")
        _, third = run("Now also make the chart render match the screenshot I sent earlier.", d)
        check("a new category later in the session -> sent, without repeating the old one",
              "Visual work" in third and "Performance work" not in third)

    with tempfile.TemporaryDirectory() as d:
        _, ctx = run("Optimise the renderer so the chart layout draws faster than it does now.", d)
        check("two categories in one prompt -> both, in one message",
              "Performance work" in ctx and "Visual work" in ctx)

    code, ctx = run("Can you optimise the hot path in the tokenizer? It is the bottleneck.")
    check("no scratchpad and no session id -> silent (cannot dedupe)", code == 0 and ctx == "")
    sid = "test-session-" + next(tempfile._get_candidate_names())
    _, a = run("Can you optimise the hot path in the tokenizer? It is the bottleneck.", extra={"session_id": sid})
    _, b = run("Can you optimise the hot path in the tokenizer? It is the bottleneck.", extra={"session_id": sid})
    check("session id fallback -> sent once", "Performance work" in a and b == "")
    (Path(tempfile.gettempdir()) / f"task-grounding-{sid}.json").unlink(missing_ok=True)

    for name, raw in [("empty stdin", ""), ("not JSON", "{{"), ("JSON array", "[1]"),
                      ("prompt not a string", json.dumps({"prompt": 3})), ("no prompt", "{}")]:
        code, ctx = run("", raw=raw)
        check(f"fail-open: {name} -> exit 0, no output", code == 0 and ctx == "")
    # Changed on 2026-11-14 at the coordinator's request: a corrupt state file used to
    # silence the hook for the rest of the session; it is now treated as empty.
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "task-grounding-seen.json").write_text("not json")
        code, ctx = run("Can you optimise the hot path in the tokenizer? It is the bottleneck.", d)
        _, again = run("Can you optimise the hot path in the tokenizer? It is the bottleneck.", d)
        check("corrupt state file -> treated as empty: directive sent, then deduplicated",
              code == 0 and "Performance work" in ctx and again == "")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "task-grounding-seen.json").mkdir()
        code, ctx = run("Can you optimise the hot path in the tokenizer? It is the bottleneck.", d)
        check("fail-open: state path is a directory -> exit 0, no output", code == 0 and ctx == "")

    # Misfires found in review: ordinary coding prompts that must stay silent.
    for prompt in [
        "Add unit tests for the config loader and make sure they cover the error path.",
        "There is a regression in the login flow since yesterday's deploy, please fix it.",
        "Change the sequence of the startup hooks so the logger initialises before the database.",
        "Make the CLI output a summary table of statistics for each run of the job.",
        "Update the Helm charts so the staging deployment uses the new image tag.",
        "The React component re-renders on every keystroke, can you stop that from happening?",
        "Please answer faster and with less detail from now on, thank you very much.",
        "I'm optimistic about this approach, can you wire the config loader into main?",
        "Show the user profile page link in the account settings menu, next to logout.",
        "Simulate a click on the submit button in the integration test for the form.",
    ]:
        with tempfile.TemporaryDirectory() as d:
            _, ctx = run(prompt, d)
            check(f"misfire -> silent: {prompt[:60]}", ctx == "")

    # Recall kept for the narrowed patterns.
    for prompt, want in [
        ("Fit a linear regression to the dose-response data and report the coefficients.", "Scientific"),
        ("Align these protein sequences and compute the identity between each pair.", "Scientific"),
        ("Is the difference between the two groups statistically significant? Use a t-test.", "Scientific"),
        ("Convert the solver output to SI units and check the dimensional analysis.", "Scientific"),
        ("The bar chart labels overlap on small screens, fix the axis layout.", "Visual work"),
        ("Render the page to a PNG and compare it with the screenshot in docs/.", "Visual work"),
        ("This endpoint is too slow under load, profile it and find the bottleneck.", "Performance work"),
        ("Make the import step run faster than it does now; it takes minutes.", "Performance work"),
    ]:
        with tempfile.TemporaryDirectory() as d:
            _, ctx = run(prompt, d)
            check(f"narrowed pattern still matches -> {want}: {prompt[:50]}", want in ctx)

    # Setting up and running a benchmark suite, and disk space for it, is not work on
    # making code faster: the performance category must not be set (it was, on "benchmark").
    for prompt in [
        "Install the benchmark runner and check that it can pull the task images from the registry.",
        "Which container runtime should I use for running the benchmark suite, docker or podman?",
        "How much disk space do the benchmark's container images need? The disk is nearly full.",
        "Set up the benchmark harness from its README and run the first ten tasks.",
        "Run the benchmark suite overnight and send me the scores per task in a table.",
        "Free up disk space so the benchmark images fit, then start the evaluation run.",
        "Clone the benchmarks repository and list the tasks it contains, with their categories.",
    ]:
        with tempfile.TemporaryDirectory() as d:
            _, ctx = run(prompt, d)
            check(f"benchmark setup -> performance not set: {prompt[:55]}", "Performance work" not in ctx)

    # "benchmark" still sets performance when it is about timing code.
    for prompt in [
        "Benchmark the parser before and after the change and report the timings.",
        "Write a microbenchmark for the hash function and run it on both branches.",
        "Add a performance benchmark for the JSON encoder so we can track regressions.",
        "Can you benchmark it against the old implementation with the large input file?",
    ]:
        with tempfile.TemporaryDirectory() as d:
            _, ctx = run(prompt, d)
            check(f"benchmark about timing code -> performance: {prompt[:50]}", "Performance work" in ctx)

    # Work for a reader: a large deliverable (course, tutorial, guide, documentation,
    # long report, explainer) or a request to be taught from a stated level.
    reader = "Work for a reader"
    for prompt in [
        "Write a short course on SQL joins with exercises, one lesson per join type.",
        "Can you put together a tutorial on setting up the dev environment for new hires?",
        "Write documentation for the plugin API so other teams can build on it.",
        "Write a detailed report on why the nightly jobs failed last week.",
        "I'd like an explainer about how the cache invalidation works, for the wiki.",
        "Teach me how TCP congestion control works, I want to really get it this time.",
        "Explain how git stores objects from the very beginning, assuming I know nothing.",
        "Go through the scheduler design and lay it out so that I can understand it properly.",
        "Explain Rust lifetimes from first principles please, with small examples.",
        "Draft a migration guide for users moving from version 2 to version 3.",
        "I want a series of lessons on linear algebra for programmers, starting at vectors.",
    ]:
        with tempfile.TemporaryDirectory() as d:
            _, ctx = run(prompt, d)
            check(f"reader deliverable -> directive: {prompt[:55]}", reader in ctx)

    with tempfile.TemporaryDirectory() as d:
        _, ctx = run("Write a short course on SQL joins with exercises, one lesson per join type.", d)
        check("reader directive asks for the reading, the reader, one piece first, and a check against the stated level",
              all(w in ctx for w in ("key phrase", "who the reader is", "one representative piece", "before producing the rest",
                                     "order, pitch and wording")))

    # Ordinary coding prompts that mention docs, reports, guides or explaining: must not
    # set the reader category.
    for prompt in [
        "Fix the docs build, sphinx fails on the new module with an import error.",
        "Update the README badge so it points at the new CI workflow instead.",
        "Add a docstring to the parse_config function describing its arguments.",
        "Write a test report parser that reads the JUnit XML and prints failures.",
        "Explain this error please: TypeError: undefined is not a function",
        "Generate a coverage report for the tests and fail the build under 80 percent.",
        "Make the docs build run in CI on every pull request to main.",
        "Create a bug report template in .github with fields for version and steps.",
        "Add a link to the tutorial page in the footer of the landing site.",
        "Write the handler first, and make it of course return a 404 for unknown ids.",
        "Help me understand why this test fails only on the CI runner and not locally.",
        "Build the course table migration and add an index on the slug column.",
        "Update the documentation for the --verbose flag, it now takes a level.",
        "I don't understand why the cache is rebuilt from scratch on every run.",
        "Rename the guide_id column to guide_slug in the lessons model and its tests.",
        "Can you explain what this regex does? It is in the config loader.",
    ]:
        with tempfile.TemporaryDirectory() as d:
            _, ctx = run(prompt, d)
            check(f"reader misfire -> not set: {prompt[:55]}", reader not in ctx)

    with tempfile.TemporaryDirectory() as d:
        _, ctx = run("/home/me/proj/solver.py has a bug in the ODE step size, can you look at it?", d)
        check("prompt starting with an absolute path is not a slash command -> scientific directive",
              "Scientific" in ctx)
        _, ctx = run("/review the numerical solver and its ODE step size handling in detail", d)
        check("a real slash command is still skipped", ctx == "")

    sci = "Write a simulation of methylation drift across cell divisions and fit it."
    with tempfile.TemporaryDirectory() as d:
        _, ctx = run(sci, d)
        check("scientific directive names the checker by absolute path, and that file exists",
              f'"{REPO_CHECKER}"' in ctx and REPO_CHECKER.is_file())
    with tempfile.TemporaryDirectory() as inst, tempfile.TemporaryDirectory() as d:
        shutil.copy(HOOK, inst)
        shutil.copy(HOOK.with_name("categories.json"), inst)
        (Path(inst) / "check_reference.py").write_text("# stand-in\n")
        _, ctx = run(sci, d, hook=Path(inst) / HOOK.name)
        check("hook installed with check_reference.py beside it -> directive names that copy",
              str(Path(inst) / "check_reference.py") in ctx)
    with tempfile.TemporaryDirectory() as inst, tempfile.TemporaryDirectory() as d:
        shutil.copy(HOOK, inst)
        shutil.copy(HOOK.with_name("categories.json"), inst)
        _, ctx = run(sci, d, hook=Path(inst) / HOOK.name)
        check("hook installed with no checker nearby -> directive points at INDEX.md, names no checker",
              "Scientific" in ctx and "--find" not in ctx and "docs/reference/INDEX.md" in ctx)

    # Grounding kits: the performance and scientific directives name the kit's tool and
    # playbook by absolute path when the kit is found from the hook's location, and fall
    # back to the plain directive in categories.json when it is not.
    perf = "Can you optimise the hot path in the tokenizer? It is the bottleneck."
    rules = {c["id"]: c for c in json.loads(HOOK.with_name("categories.json").read_text())["categories"]}
    for cid, prompt, tool in (("performance", perf, "measure.py"), ("scientific", sci, "validate.py")):
        kit = Path(__file__).resolve().parent.parent / "grounding-kits" / cid
        with tempfile.TemporaryDirectory() as d:
            _, ctx = run(prompt, d)
            check(f"{cid} directive in the repository layout names the kit's tool and playbook, and both exist",
                  f'"{kit / tool}"' in ctx and str(kit / "PLAYBOOK.md") in ctx
                  and (kit / tool).is_file() and (kit / "PLAYBOOK.md").is_file())
        with tempfile.TemporaryDirectory() as inst, tempfile.TemporaryDirectory() as d:
            shutil.copy(HOOK, inst)
            shutil.copy(HOOK.with_name("categories.json"), inst)
            copy = Path(inst) / "grounding-kits" / cid
            copy.mkdir(parents=True)
            (copy / tool).write_text("# stand-in\n")
            (copy / "PLAYBOOK.md").write_text("stand-in\n")
            _, ctx = run(prompt, d, hook=Path(inst) / HOOK.name)
            check(f"hook installed with grounding-kits/{cid}/ beside it -> {cid} directive names that copy",
                  str(copy / tool) in ctx and str(copy / "PLAYBOOK.md") in ctx)
        with tempfile.TemporaryDirectory() as inst, tempfile.TemporaryDirectory() as d:
            shutil.copy(HOOK, inst)
            shutil.copy(HOOK.with_name("categories.json"), inst)
            copy = Path(inst) / "grounding-kits" / cid
            copy.mkdir(parents=True)
            (copy / tool).write_text("# stand-in\n")  # playbook missing: kit incomplete
            _, ctx = run(prompt, d, hook=Path(inst) / HOOK.name)
            plain = rules[cid]["directive"].replace("{reference}", "read docs/reference/INDEX.md")
            check(f"hook installed with no complete {cid} kit -> the plain directive, word for word",
                  plain in ctx and tool not in ctx and "PLAYBOOK" not in ctx)

    with tempfile.TemporaryDirectory() as d:
        paste = '<pasted_content id="1">\nINFO request served in 12 ms\n</pasted_content id="1">\n'
        _, ctx = run("Here is the log:\n" + paste + "The importer is too slow on large files, can you optimise the parsing loop?", d)
        check("text after a pasted block whose closing tag carries an id still sets the category",
              "Performance work" in ctx)
    with tempfile.TemporaryDirectory() as d:
        paste = '<pasted_content id="2">\nthe render is too slow, optimise the layout\n</pasted_content id="2">\n'
        _, ctx = run("Please file this note under the docs folder for me.\n" + paste + "Put it in notes.md, thanks a lot.", d)
        check("words only inside an id-closed pasted block -> silent", ctx == "")

    print("\nall cases passed" if not fails else f"\n{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
