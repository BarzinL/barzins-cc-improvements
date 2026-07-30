#!/usr/bin/env python3
"""Install the per-model discipline hook, then prove it fires.

Dry run by default: prints the file copies and a unified diff of the settings change,
writes nothing. Re-run with --apply to perform it.

    python3 install.py --scope global            # show what would change
    python3 install.py --scope global --apply    # do it, then run the acceptance check
    python3 install.py --scope project --project /path/to/repo --apply
    python3 install.py --scope global --verify-only

Merging into a live `settings.json` is the only destructive thing in this repository, so
it is done narrowly: the file is backed up first, the existing `hooks.UserPromptSubmit`
array is appended to and never rewritten, and an entry with the same command is
recognized as already installed rather than duplicated.

Stdlib only. Every path is absolute for a global install, because `$CLAUDE_PROJECT_DIR`
resolves only for project-scoped settings; used globally it stays a literal and the hook
command exits 2 with `can't open file` (measured), which the acceptance check catches.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK_SRC = HERE / "model_discipline.py"
PAYLOAD_SRC = HERE / "model-discipline-payloads"
STATUS = "Per-model discipline"


class Fail(Exception):
    """An install or verification step that must stop the run."""


# --------------------------------------------------------------------- locations


def locations(scope: str, project: Path | None) -> tuple[Path, Path, str]:
    """Return (settings_path, hooks_dir, command_string) for the chosen scope."""
    if scope == "global":
        root = Path.home() / ".claude"
        hooks_dir = root / "hooks"
        cmd = f'python3 "{hooks_dir / HOOK_SRC.name}"'
    else:
        root = (project or Path.cwd()).resolve() / ".claude"
        hooks_dir = root / "hooks"
        cmd = f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{HOOK_SRC.name}"'
    return root / "settings.json", hooks_dir, cmd


def resolve_command(cmd: str, scope: str, project: Path | None) -> list[str]:
    """The command as the harness would run it, so the check tests the real string."""
    expanded = cmd
    if scope == "project":
        base = str((project or Path.cwd()).resolve())
        expanded = expanded.replace("$CLAUDE_PROJECT_DIR", base)
    return shlex.split(expanded)


# ------------------------------------------------------------------ settings merge


def read_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError as exc:
        raise Fail(f"{path} is not valid JSON ({exc}); fix it by hand first") from exc
    if not isinstance(data, dict):
        raise Fail(f"{path} does not contain a JSON object")
    return data


# Both legs run the same command; the script branches on `hook_event_name`.
# UserPromptSubmit injects; PostCompact only marks that a compaction happened, so an
# on-change payload is re-injected on the next prompt instead of being lost to the
# summary. See the module docstring in model_discipline.py.
EVENTS = ("UserPromptSubmit", "PostCompact")


def _event_installed(settings: dict, event: str, cmd: str) -> bool:
    groups = (settings.get("hooks") or {}).get(event) or []
    for group in groups:
        for hook in (group or {}).get("hooks") or []:
            if (hook or {}).get("command") == cmd:
                return True
    return False


def already_installed(settings: dict, cmd: str) -> bool:
    """True only when EVERY leg is present, so a pre-PostCompact install still
    upgrades rather than reporting itself as done."""
    return all(_event_installed(settings, e, cmd) for e in EVENTS)


def merged(settings: dict, cmd: str) -> dict:
    """A copy of settings with our hook appended to each event in EVENTS.

    Idempotent per event: an install that already has UserPromptSubmit but not
    PostCompact adds only the missing leg.
    """
    out = json.loads(json.dumps(settings))  # deep copy without importing copy
    hooks = out.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise Fail("settings.json has a 'hooks' key that is not an object")
    for event in EVENTS:
        if _event_installed(out, event, cmd):
            continue
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise Fail(f"settings.json has a 'hooks.{event}' key that is not an array")
        entry = {"type": "command", "command": cmd, "statusMessage": STATUS}
        # Neither event's groups carry a matcher; join a matcher-less group if one
        # exists rather than adding a second group beside it.
        for group in groups:
            if isinstance(group, dict) and "matcher" not in group and isinstance(group.get("hooks"), list):
                group["hooks"].append(entry)
                break
        else:
            groups.append({"hooks": [entry]})
    return out


def render(settings: dict) -> str:
    return json.dumps(settings, indent=2) + "\n"


def diff(before: str, after: str, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{path} (current)",
            tofile=f"{path} (after install)",
        )
    )


# ------------------------------------------------------------------- verification


def _transcript(dir_: Path, model: str) -> Path:
    p = dir_ / f"t-{abs(hash(model))}.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {"model": model, "content": []}}) + "\n")
    return p


def _run(
    argv: list[str],
    transcript: Path,
    session: str,
    state: Path,
    event: str = "UserPromptSubmit",
) -> str:
    payload = json.dumps(
        {
            "session_id": session,
            "transcript_path": str(transcript),
            "hook_event_name": event,
            "user_prompt": "x",
        }
    )
    env = {**os.environ, "MODEL_DISCIPLINE_STATE_DIR": str(state)}
    proc = subprocess.run(argv, input=payload, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise Fail(
            f"hook command exited {proc.returncode}, expected 0.\n"
            f"  command: {' '.join(argv)}\n  stderr: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def verify(argv: list[str]) -> None:
    """Prove the registered command fires, and that it stays silent when it should.

    A check that has never been seen to fail is indistinguishable from one that cannot
    fail, so the negative controls run every time alongside the positive case.
    """
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = d / "state"
        state.mkdir()

        opus = _transcript(d, "claude-opus-5")
        first = _run(argv, opus, "verify-opus", state)
        if not first:
            raise Fail(
                "no output for claude-opus-5. Either the payload file is missing from "
                f"{PAYLOAD_SRC.name}/ next to the installed hook, or it is empty."
            )
        second = _run(argv, opus, "verify-opus", state)
        if not second:
            raise Fail(
                "output on the first turn but not the second. The opus payload needs "
                "`<!-- cadence: every-turn -->`; on-change fires once and then decays "
                "out of context at the first compaction."
            )

        # Negative controls. Each of these printing anything is a real defect.
        unknown = _run(argv, _transcript(d, "gpt-4"), "verify-unknown", state)
        if unknown:
            raise Fail(f"an unrecognized model produced output: {unknown[:120]!r}")
        synthetic = _run(argv, _transcript(d, "<synthetic>"), "verify-synthetic", state)
        if synthetic:
            raise Fail(f"a <synthetic> record produced output: {synthetic[:120]!r}")
        missing = _run(argv, d / "does-not-exist.jsonl", "verify-missing", state)
        if missing:
            raise Fail(f"a missing transcript produced output: {missing[:120]!r}")

        sonnet = _transcript(d, "claude-sonnet-5")
        if not _run(argv, sonnet, "verify-sonnet", state):
            raise Fail("no output on a switch to claude-sonnet-5")
        if _run(argv, sonnet, "verify-sonnet", state):
            raise Fail("the sonnet payload repeated on an unchanged family; cadence is broken")

        # The PostCompact leg. Marking must be silent, and must make the very next
        # prompt re-inject the on-change payload it would otherwise have skipped.
        if _run(argv, sonnet, "verify-sonnet", state, event="PostCompact"):
            raise Fail("the PostCompact leg printed something; it must only mark state")
        if not _run(argv, sonnet, "verify-sonnet", state):
            raise Fail(
                "an on-change payload did not re-fire after PostCompact. Without this, a "
                "stint's discipline is summarized away at the first compaction and never "
                "returns. Check that hooks.PostCompact is registered in settings.json."
            )
        if _run(argv, sonnet, "verify-sonnet", state):
            raise Fail("the compaction marker fired twice; it must be single-shot")

    print("acceptance check passed: fires every turn for opus, on change for sonnet, "
          "re-fires once after PostCompact, silent for unknown / synthetic / missing "
          "transcript.")


# --------------------------------------------------------------------------- main


def install(scope: str, project: Path | None, apply: bool) -> int:
    settings_path, hooks_dir, cmd = locations(scope, project)
    if not HOOK_SRC.is_file() or not PAYLOAD_SRC.is_dir():
        raise Fail(f"run this from its own directory; {HOOK_SRC.name} not found beside it")

    settings = read_settings(settings_path)
    installed = already_installed(settings, cmd)
    before = render(settings) if settings_path.is_file() else ""
    after = before if installed else render(merged(settings, cmd))

    print(f"scope:    {scope}")
    print(f"settings: {settings_path}")
    print(f"hook:     {hooks_dir / HOOK_SRC.name}")
    print(f"payloads: {hooks_dir / PAYLOAD_SRC.name}/  ({len(list(PAYLOAD_SRC.glob('*.md')))} files)")
    print(f"command:  {cmd}")
    print()
    if installed:
        print("settings.json already registers this command; only the files will be refreshed.")
    else:
        print(diff(before, after, settings_path) or "(no settings change)")

    if not apply:
        print("\ndry run. Nothing written. Re-run with --apply.")
        return 0

    hooks_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOK_SRC, hooks_dir / HOOK_SRC.name)
    dest_payloads = hooks_dir / PAYLOAD_SRC.name
    dest_payloads.mkdir(exist_ok=True)
    for f in PAYLOAD_SRC.glob("*.md"):
        shutil.copy2(f, dest_payloads / f.name)
    print(f"\ncopied hook and payloads into {hooks_dir}")

    if not installed:
        if settings_path.is_file():
            backup = settings_path.with_suffix(f".json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(settings_path, backup)
            print(f"backed up settings to {backup}")
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(after)
        print(f"registered the hook in {settings_path}")

    print()
    verify(resolve_command(cmd, scope, project))
    print("\nDone. Start a new session, or run /hooks to confirm it is listed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", choices=("global", "project"), default="global",
                    help="global: ~/.claude (every project). project: <project>/.claude.")
    ap.add_argument("--project", type=Path, default=None, help="project root for --scope project")
    ap.add_argument("--apply", action="store_true", help="write the changes")
    ap.add_argument("--verify-only", action="store_true", help="run the acceptance check and exit")
    args = ap.parse_args(argv)

    try:
        if args.verify_only:
            _, _, cmd = locations(args.scope, args.project)
            verify(resolve_command(cmd, args.scope, args.project))
            return 0
        return install(args.scope, args.project, args.apply)
    except Fail as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
