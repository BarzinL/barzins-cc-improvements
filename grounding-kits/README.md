# Grounding kits

Each kit pairs a directive from `task-grounding/` with a small command-line tool that does
the careful step in one call and leaves a record file, and a one-page playbook the agent
reads when the category applies. When `task_grounding.py` finds a kit in a
`grounding-kits/` directory beside it or one level up, its directive for that category
names the kit's tool and playbook by absolute path; otherwise it sends its plain
directive.

| Kit | Tool | What the tool records |
|---|---|---|
| [`performance/`](performance/) | `measure.py` | Repeated timings of one command on declared inputs; a comparison of two such records with a bootstrap interval and a verdict. |
| [`scientific/`](scientific/) | `validate.py` | Checks of numerical results against independent expectations, with tolerance and units; observed order of convergence. |

Each kit directory is self-contained: Python standard library only, its own README and
tests (`python3 -I test_*.py`). Neither kit has been evaluated for effect on outcomes.
