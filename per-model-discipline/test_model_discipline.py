"""The hook must recognise every model string a real machine emits, and the installer
must refuse to report success when the thing it registered does not work.

The bug the first block guards against is an exact-match matcher: the transcript `model`
field is not a closed set. The strings below are the real distinct values swept from
every transcript on one machine (2026-07-26), plus the documented bracket-suffix form. A
matcher that compares against a list silently mis-identifies the bare aliases and
`<synthetic>`, which is how the first draft of this hook would have failed on its first
turn.

    python3 -m pytest per-model-discipline/ -q
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_HOOK = HERE / "model_discipline.py"
_PAYLOADS = HERE / "model-discipline-payloads"
_STATE_DIR = Path(tempfile.mkdtemp(prefix="model-discipline-test-"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_md = _load("model_discipline", _HOOK)
_install = _load("install_hook", HERE / "install.py")


# ------------------------------------------------------------ normalizer: family_of


@pytest.mark.parametrize(
    ("raw", "family"),
    [
        ("claude-opus-4-8", "opus"),
        ("claude-opus-5", "opus"),
        ("claude-sonnet-4-6", "sonnet"),
        ("claude-sonnet-5", "sonnet"),
        ("claude-fable-5", "fable"),
        ("claude-mythos-5", "mythos"),
        ("claude-haiku-4-5-20251001", "haiku"),  # dated ID
        ("sonnet", "sonnet"),  # bare alias from settings.json
        ("opus", "opus"),
        ("haiku", "haiku"),
        ("claude-opus-5[1m]", "opus"),  # documented variant form
        ("claude-opus-4-5@20251101", "opus"),  # Vertex-style version separator
        ("CLAUDE-OPUS-5", "opus"),
        ("  claude-opus-5  ", "opus"),
    ],
)
def test_family_recognised(raw: str, family: str) -> None:
    assert _md.family_of(raw) == family


@pytest.mark.parametrize("raw", ["<synthetic>", "", "   ", "gpt-4", "llama-3", "unknown-model"])
def test_unrecognised_returns_none(raw: str) -> None:
    """Unknown strings must yield None so the hook stays silent rather than guessing."""
    assert _md.family_of(raw) is None


def test_a_new_payload_file_adds_a_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dropping in `<name>.md` is the whole of adding support for a family."""
    (tmp_path / "someothermodel.md").write_text("hello")
    monkeypatch.setenv("MODEL_DISCIPLINE_PAYLOAD_DIR", str(tmp_path))
    assert _md.family_of("someothermodel-9") == "someothermodel"
    assert _md.family_of("gpt-4") is None


# ------------------------------------------------------------------ payload parsing


def _payload_dir(tmp_path: Path, files: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "payloads"
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text)
    monkeypatch.setenv("MODEL_DISCIPLINE_PAYLOAD_DIR", str(d))
    return d


def test_cadence_defaults_to_on_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _payload_dir(tmp_path, {"opus.md": "plain text"}, monkeypatch)
    assert _md.payload_for("opus") == ("plain text", "on-change")


def test_directives_are_stripped_from_the_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _payload_dir(tmp_path, {"opus.md": "<!-- cadence: every-turn -->\nbody line\n"}, monkeypatch)
    assert _md.payload_for("opus") == ("body line", "every-turn")


def test_same_as_resolves_to_another_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _payload_dir(
        tmp_path,
        {"sonnet.md": "<!-- cadence: on-change -->\nshared\n", "haiku.md": "<!-- same-as: sonnet -->\n"},
        monkeypatch,
    )
    assert _md.payload_for("haiku") == ("shared", "on-change")


def test_same_as_cycle_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _payload_dir(
        tmp_path,
        {"opus.md": "<!-- same-as: sonnet -->\n", "sonnet.md": "<!-- same-as: opus -->\n"},
        monkeypatch,
    )
    assert _md.payload_for("opus") is None


def test_missing_and_empty_payloads_are_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _payload_dir(tmp_path, {"opus.md": "   \n"}, monkeypatch)
    assert _md.payload_for("opus") is None
    assert _md.payload_for("sonnet") is None


def test_an_invalid_cadence_falls_back_to_on_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo must not silently promote a payload to every turn, or demote it."""
    _payload_dir(tmp_path, {"opus.md": "<!-- cadence: eveyr-turn -->\nbody\n"}, monkeypatch)
    assert _md.payload_for("opus") == ("body", "on-change")


# -------------------------------------------------------- transcript reading


def _transcript(tmp_path: Path, models: list[str]) -> Path:
    p = tmp_path / "t.jsonl"
    with p.open("w") as fh:
        for m in models:
            fh.write(json.dumps({"type": "assistant", "message": {"model": m, "content": []}}) + "\n")
            fh.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
    return p


def test_reads_most_recent_model(tmp_path: Path) -> None:
    assert _md.current_family(_transcript(tmp_path, ["claude-opus-5", "claude-sonnet-5"])) == "sonnet"


def test_skips_synthetic_records(tmp_path: Path) -> None:
    """Hundreds of synthetic records exist in real transcripts; the last real turn counts."""
    t = _transcript(tmp_path, ["claude-sonnet-5", "<synthetic>", "<synthetic>"])
    assert _md.current_family(t) == "sonnet"


def test_empty_transcript_is_silent(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    assert _md.current_family(p) is None


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    p.write_text(
        '{"model": broken\n' + json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5"}}) + "\n"
    )
    assert _md.current_family(p) == "sonnet"


# ------------------------------------------------- end to end, against real payloads


def run(transcript: Path, session_id: str, raw: str | None = None) -> str:
    payload = (
        raw
        if raw is not None
        else json.dumps(
            {
                "session_id": session_id,
                "transcript_path": str(transcript),
                "hook_event_name": "UserPromptSubmit",
                "user_prompt": "x",
            }
        )
    )
    env = {k: v for k, v in os.environ.items() if k != "MODEL_DISCIPLINE_PAYLOAD_DIR"}
    env["MODEL_DISCIPLINE_STATE_DIR"] = str(_STATE_DIR)
    p = subprocess.run([sys.executable, str(_HOOK)], input=payload, capture_output=True, text=True, env=env)
    assert p.returncode == 0, f"hook must always exit 0: {p.returncode} {p.stderr}"
    return p.stdout.strip()


def test_opus_injects_every_turn(tmp_path: Path) -> None:
    """The shipped opus payload is a format rule, so it must not be change-gated."""
    t = _transcript(tmp_path, ["claude-opus-5"])
    assert run(t, "sess-opus")
    assert run(t, "sess-opus"), "an every-turn payload must repeat on an unchanged family"


def test_sonnet_injects_then_goes_quiet(tmp_path: Path) -> None:
    t = _transcript(tmp_path, ["claude-sonnet-5"])
    assert "Sonnet" in run(t, "sess-quiet")
    assert run(t, "sess-quiet") == "", "an on-change payload must not repeat"


def test_haiku_shares_the_sonnet_payload(tmp_path: Path) -> None:
    t = _transcript(tmp_path, ["claude-haiku-4-5-20251001"])
    assert "procedural" in run(t, "sess-haiku")


def test_switch_injects_again(tmp_path: Path) -> None:
    """Silence is per-family, not permanent: leaving and returning speaks again."""
    sid = "sess-switch"
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    assert "Sonnet" in run(_transcript(a, ["claude-sonnet-5"]), sid)
    assert run(_transcript(b, ["claude-opus-5"]), sid)
    assert "Sonnet" in run(_transcript(c, ["claude-sonnet-5"]), sid)


def test_a_family_with_no_payload_still_records_the_switch(tmp_path: Path) -> None:
    """Having no payload must not mean having no effect: state still advances."""
    sid = "sess-clears"
    a, b, c = tmp_path / "fa", tmp_path / "fb", tmp_path / "fc"
    for d in (a, b, c):
        d.mkdir()
    assert "Sonnet" in run(_transcript(a, ["claude-sonnet-5"]), sid)
    assert run(_transcript(b, ["claude-fable-5"]), sid) == ""  # no fable payload ships
    assert "Sonnet" in run(_transcript(c, ["claude-sonnet-5"]), sid), (
        "returning to Sonnet must re-inject, so the payload-less family recorded the switch"
    )


def test_unparseable_stdin_is_silent(tmp_path: Path) -> None:
    assert run(_transcript(tmp_path, ["claude-sonnet-5"]), "sess-bad", raw="{not json") == ""


def test_missing_transcript_is_silent(tmp_path: Path) -> None:
    assert run(tmp_path / "does-not-exist.jsonl", "sess-missing") == ""


# ----------------------------------------------------------------- the installer


def test_verify_passes_against_the_real_hook() -> None:
    _install.verify([sys.executable, str(_HOOK)])


def test_verify_fails_on_a_wrong_hook_path(tmp_path: Path) -> None:
    """The negative control for the installer's own check: a bad path must not pass."""
    with pytest.raises(_install.Fail) as exc:
        _install.verify([sys.executable, str(tmp_path / "not-here.py")])
    assert "exited" in str(exc.value)


def test_verify_fails_when_the_payload_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An installed hook with no payloads beside it is the silent-failure case."""
    empty = tmp_path / "empty-payloads"
    empty.mkdir()
    monkeypatch.setenv("MODEL_DISCIPLINE_PAYLOAD_DIR", str(empty))
    with pytest.raises(_install.Fail) as exc:
        _install.verify([sys.executable, str(_HOOK)])
    assert "no output for claude-opus-5" in str(exc.value)


def test_verify_fails_when_opus_is_only_on_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression that would otherwise be invisible: the rule decays after one turn."""
    d = tmp_path / "on-change-payloads"
    d.mkdir()
    (d / "opus.md").write_text("<!-- cadence: on-change -->\nbe brief\n")
    (d / "sonnet.md").write_text("shared\n")
    monkeypatch.setenv("MODEL_DISCIPLINE_PAYLOAD_DIR", str(d))
    with pytest.raises(_install.Fail) as exc:
        _install.verify([sys.executable, str(_HOOK)])
    assert "every-turn" in str(exc.value)


def _settings(home: Path) -> Path:
    return home / ".claude" / "settings.json"


def test_install_is_idempotent_and_preserves_existing_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    existing = {
        "model": "opus",
        "hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 /somebody/else.py"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "python3 /their/stop.py"}]}],
        },
    }
    _settings(home).write_text(json.dumps(existing, indent=2))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MODEL_DISCIPLINE_PAYLOAD_DIR", raising=False)

    assert _install.main(["--scope", "global", "--apply"]) == 0
    after = json.loads(_settings(home).read_text())
    ups = after["hooks"]["UserPromptSubmit"][0]["hooks"]
    assert [h["command"] for h in ups][0] == "python3 /somebody/else.py", "appended, not rewritten"
    assert any("model_discipline.py" in h["command"] for h in ups)
    assert after["hooks"]["Stop"] == existing["hooks"]["Stop"]
    assert after["model"] == "opus", "unrelated settings preserved"
    assert list((home / ".claude" / "hooks" / "model-discipline-payloads").glob("*.md"))
    assert list((home / ".claude").glob("settings.json.bak-*")), "settings backed up before writing"

    # Second run must not duplicate the entry.
    assert _install.main(["--scope", "global", "--apply"]) == 0
    again = json.loads(_settings(home).read_text())
    cmds = [h["command"] for h in again["hooks"]["UserPromptSubmit"][0]["hooks"]]
    assert sum("model_discipline.py" in c for c in cmds) == 1


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home2"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert _install.main(["--scope", "global"]) == 0
    assert not (home / ".claude").exists()


def test_broken_settings_json_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home3"
    (home / ".claude").mkdir(parents=True)
    _settings(home).write_text("{ not json")
    monkeypatch.setenv("HOME", str(home))
    assert _install.main(["--scope", "global", "--apply"]) == 1
    assert _settings(home).read_text() == "{ not json", "a refused install changes nothing"


def test_project_scope_uses_the_project_dir_variable(tmp_path: Path) -> None:
    settings, hooks_dir, cmd = _install.locations("project", tmp_path)
    assert settings == tmp_path / ".claude" / "settings.json"
    assert hooks_dir == tmp_path / ".claude" / "hooks"
    assert "$CLAUDE_PROJECT_DIR" in cmd
    assert _install.resolve_command(cmd, "project", tmp_path)[1] == str(
        tmp_path / ".claude" / "hooks" / "model_discipline.py"
    )
