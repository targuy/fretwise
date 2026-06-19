"""Tests for the local AI rig generation service (fretwise.rig_generation)."""
from __future__ import annotations

import json
import subprocess

import pytest

from fretwise.rig_generation import (
    GeneratedRig,
    ProcessResult,
    RigGenerationError,
    SongRigGenerationService,
    parse_rig_output,
)

VALID_PAYLOAD = {
    "schema_version": "codex_output_schema_v1",
    "artist": "AC/DC",
    "song": "Highway To Hell",
    "genre": "hard rock",
    "accordage": "Mi standard (E standard)",
    "capo": "non",
    "recommended_guitar": "Gibson SG bridge humbucker",
    "signal_chain": "NR -> AMP -> CAB -> EQ -> RVB",
    "rig": {
        "nr": "Gate 1",
        "pre": "Off",
        "dst": "Off",
        "amp": "UK 50",
        "cab": "UK Vintage 4x12",
        "eq": "Guitar EQ 1",
        "mod": "Off",
        "dly": "Off",
        "rvb": "Room",
    },
    "reliability": "B",
    "comments": "Validate on a bridge humbucker.",
}


def _stub_runner(returncode=0, stdout="", stderr=""):
    """Return a fake runner that records the command it was called with."""
    calls: list[tuple[list[str], str, int]] = []

    def runner(cmd, cwd, timeout):
        calls.append((cmd, cwd, timeout))
        return ProcessResult(returncode, stdout, stderr)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


# --------------------------------------------------------------------------- #
# parse_rig_output
# --------------------------------------------------------------------------- #

def test_parse_rig_output_valid_json_returns_dict():
    out = json.dumps(VALID_PAYLOAD)
    assert parse_rig_output(out) == VALID_PAYLOAD


def test_parse_rig_output_trailing_newline_and_whitespace_ok():
    out = "  " + json.dumps(VALID_PAYLOAD) + "\n\n"
    assert parse_rig_output(out)["artist"] == "AC/DC"


def test_parse_rig_output_falls_back_to_last_line():
    out = "some banner line\n" + json.dumps(VALID_PAYLOAD)
    assert parse_rig_output(out)["song"] == "Highway To Hell"


def test_parse_rig_output_empty_raises():
    with pytest.raises(RigGenerationError):
        parse_rig_output("   \n  ")


def test_parse_rig_output_invalid_json_raises():
    with pytest.raises(RigGenerationError):
        parse_rig_output("not json at all")


def test_parse_rig_output_missing_top_key_raises():
    bad = {k: v for k, v in VALID_PAYLOAD.items() if k != "reliability"}
    with pytest.raises(RigGenerationError, match="missing required keys"):
        parse_rig_output(json.dumps(bad))


def test_parse_rig_output_missing_rig_slot_raises():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    del bad["rig"]["amp"]
    with pytest.raises(RigGenerationError, match="missing slots"):
        parse_rig_output(json.dumps(bad))


def test_parse_rig_output_rig_not_object_raises():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["rig"] = "nope"
    with pytest.raises(RigGenerationError):
        parse_rig_output(json.dumps(bad))


# --------------------------------------------------------------------------- #
# SongRigGenerationService — with a fake runner
# --------------------------------------------------------------------------- #

def test_generate_with_fake_runner_returns_generated_rig(tmp_path):
    runner = _stub_runner(stdout=json.dumps(VALID_PAYLOAD))
    svc = SongRigGenerationService(tools_dir=tmp_path, runner=runner)
    (tmp_path / "codex_song_rig.py").write_text("# stub", encoding="utf-8")

    result = svc.generate("AC/DC", "Highway To Hell")

    assert isinstance(result, GeneratedRig)
    assert result.artist == "AC/DC"
    assert result.genre == "hard rock"
    assert result.rig["amp"] == "UK 50"
    assert result.reliability == "B"
    assert result.raw == VALID_PAYLOAD


def test_generate_builds_direct_argv_no_shell(tmp_path):
    runner = _stub_runner(stdout=json.dumps(VALID_PAYLOAD))
    svc = SongRigGenerationService(
        tools_dir=tmp_path, python_exe="py-exe", provider="codex", timeout=42, runner=runner
    )
    (tmp_path / "codex_song_rig.py").write_text("# stub", encoding="utf-8")

    svc.generate("AC/DC", "Highway To Hell", genre="hard rock", target_guitar="SG", refresh=True)

    cmd, cwd, timeout = runner.calls[0]
    # argv is a list (never a single shell string) and carries each value as its
    # own token, so shell metacharacters in artist/title cannot be reinterpreted.
    assert isinstance(cmd, list)
    assert cmd[0] == "py-exe"
    assert cmd[1].endswith("codex_song_rig.py")
    assert cmd[2] == "AC/DC"
    assert cmd[3] == "Highway To Hell"
    assert "--genre" in cmd and cmd[cmd.index("--genre") + 1] == "hard rock"
    assert "--target-guitar" in cmd and cmd[cmd.index("--target-guitar") + 1] == "SG"
    assert "--provider" in cmd and cmd[cmd.index("--provider") + 1] == "codex"
    assert "--refresh" in cmd
    assert "--timeout" in cmd and cmd[cmd.index("--timeout") + 1] == "42"
    assert timeout == 42


def test_generate_nonzero_returncode_raises_with_stderr(tmp_path):
    runner = _stub_runner(returncode=1, stderr="codex blew up")
    svc = SongRigGenerationService(tools_dir=tmp_path, runner=runner)
    (tmp_path / "codex_song_rig.py").write_text("# stub", encoding="utf-8")

    with pytest.raises(RigGenerationError) as exc:
        svc.generate("AC/DC", "Highway To Hell")
    assert exc.value.returncode == 1
    assert exc.value.stderr == "codex blew up"


def test_generate_timeout_raises(tmp_path):
    def runner(cmd, cwd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    svc = SongRigGenerationService(tools_dir=tmp_path, runner=runner)
    (tmp_path / "codex_song_rig.py").write_text("# stub", encoding="utf-8")

    with pytest.raises(RigGenerationError, match="timed out"):
        svc.generate("AC/DC", "Highway To Hell")


def test_generate_missing_script_raises(tmp_path):
    runner = _stub_runner(stdout=json.dumps(VALID_PAYLOAD))
    svc = SongRigGenerationService(tools_dir=tmp_path, runner=runner)
    # No codex_song_rig.py written into tmp_path.
    with pytest.raises(RigGenerationError, match="not found"):
        svc.generate("AC/DC", "Highway To Hell")


def test_default_runner_preserves_utf8_via_real_subprocess(tmp_path):
    """End-to-end through the real (non-faked) runner: a stub wrapper that emits
    a non-ASCII em-dash must survive the round-trip uncorrupted. Guards the
    Windows cp1252-vs-UTF-8 stdout mismatch. No Codex involved.
    """
    payload = json.loads(json.dumps(VALID_PAYLOAD))
    payload["rig"]["amp"] = "UK 50 — Gain 55"  # real em-dash (U+2014)
    payload["comments"] = "Gain modéré, à valider."  # accented French
    stub = tmp_path / "codex_song_rig.py"
    stub.write_text(
        "import sys, json\n"
        f"sys.stdout.write(json.dumps({payload!r}, ensure_ascii=False))\n",
        encoding="utf-8",
    )

    svc = SongRigGenerationService(tools_dir=tmp_path)  # real _default_runner
    result = svc.generate("AC/DC", "Highway To Hell")

    assert result.rig["amp"] == "UK 50 — Gain 55"
    assert result.comments == "Gain modéré, à valider."


def test_generated_rig_roundtrips_through_markdown():
    """generated_rig_to_view -> rig_view_to_markdown -> parse_rig preserves the
    fields the saved .md must carry, and the saved file re-acquires pedal art."""
    from fretwise.rig import generated_rig_to_view, parse_rig, rig_view_to_markdown

    view = generated_rig_to_view(VALID_PAYLOAD)
    md = rig_view_to_markdown(view, date="01-02-2026")
    reparsed = parse_rig(md)

    assert reparsed["artist"] == "AC/DC"
    assert reparsed["song"] == "Highway To Hell"
    assert reparsed["genre"] == "hard rock"
    assert reparsed["accordage"] == "Mi standard (E standard)"
    assert reparsed["capo"] == "non"
    assert reparsed["fiabilite"] == "B"
    # Recommended guitar written as "Guitare originale" so its photo shows on reload.
    assert reparsed["guitare_originale"] == "Gibson SG bridge humbucker"
    amp = reparsed["reglages"]["AMP"]
    assert amp["active"] is True
    assert amp["preset"] == "UK 50"
    assert amp["image"]  # a pedal/amp artwork was matched
    assert reparsed["reglages"]["PRE"]["active"] is False  # "Off" stays inactive


def test_default_rig_path_is_findable():
    """default_rig_path lands where find_rig will later resolve it."""
    import tempfile
    from pathlib import Path

    from fretwise.rig import default_rig_path, find_rig

    with tempfile.TemporaryDirectory() as d:
        rigs = Path(d)
        target = default_rig_path("AC_DC - Highway To Hell.gp", rigs)
        target.write_text("# stub", encoding="utf-8")
        assert find_rig("AC_DC - Highway To Hell.gp", rigs) == target


def test_generate_blank_artist_or_title_raises(tmp_path):
    runner = _stub_runner(stdout=json.dumps(VALID_PAYLOAD))
    svc = SongRigGenerationService(tools_dir=tmp_path, runner=runner)
    (tmp_path / "codex_song_rig.py").write_text("# stub", encoding="utf-8")

    with pytest.raises(RigGenerationError):
        svc.generate("  ", "Highway To Hell")
    with pytest.raises(RigGenerationError):
        svc.generate("AC/DC", "")
