"""Local AI rig generation service.

Wraps the local CLI wrapper ``tools/codex_song_rig.py`` as a child process and
returns the structured GP-180 rig it prints as JSON to stdout.

Design notes
------------
* The wrapper is launched **directly** (argv list, never a shell). Going through
  PowerShell/cmd would let profile banners and shell startup text pollute stdout,
  which the wrapper contract relies on being a single clean JSON object.
* The Codex binary path is *not* hard-coded here — the wrapper resolves it (or
  honours ``CODEX_BIN`` / its config). FretWise only needs to know which Python
  interpreter to run the wrapper with (defaults to the running interpreter, which
  is correct inside the project's pixi environment).
* The blocking subprocess call lives in :meth:`SongRigGenerationService.generate`
  (sync). The web layer offloads it with ``asyncio.to_thread`` so the event loop
  is never blocked. The process runner is injectable for testing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "RigGenerationError",
    "GeneratedRig",
    "ProcessResult",
    "SongRigGenerationService",
    "parse_rig_output",
]

# Keys the wrapper schema (``tools/codex_song_rig.schema.json``) guarantees.
_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "artist",
        "song",
        "genre",
        "accordage",
        "capo",
        "recommended_guitar",
        "signal_chain",
        "rig",
        "reliability",
        "comments",
    }
)
_REQUIRED_RIG_SLOTS = frozenset({"nr", "pre", "dst", "amp", "cab", "eq", "mod", "dly", "rvb"})

DEFAULT_TIMEOUT_SECONDS = 300


class RigGenerationError(Exception):
    """Raised when the wrapper fails, times out, or returns unusable output.

    ``stderr`` carries the child process diagnostics when available so the caller
    can surface them to the user without losing the previously stored rig.
    """

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


@dataclass(frozen=True)
class ProcessResult:
    """Minimal result of a child-process run (the injectable runner's return)."""

    returncode: int
    stdout: str
    stderr: str


@dataclass
class GeneratedRig:
    """Typed view over one wrapper output object.

    ``raw`` keeps the full parsed payload so the API/UI can render fields this
    dataclass does not promote to attributes without a second parse.
    """

    schema_version: str
    artist: str
    song: str
    genre: str
    accordage: str
    capo: str
    recommended_guitar: str
    signal_chain: str
    rig: dict[str, str]
    reliability: str
    comments: str
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> GeneratedRig:
        """Build from a validated wrapper payload (see :func:`parse_rig_output`)."""
        return cls(
            schema_version=str(data["schema_version"]),
            artist=str(data["artist"]),
            song=str(data["song"]),
            genre=str(data.get("genre") or ""),
            accordage=str(data["accordage"]),
            capo=str(data["capo"]),
            recommended_guitar=str(data["recommended_guitar"]),
            signal_chain=str(data["signal_chain"]),
            rig={k: str(v) for k, v in data["rig"].items()},
            reliability=str(data["reliability"]),
            comments=str(data["comments"]),
            raw=data,
        )


def parse_rig_output(stdout: str) -> dict[str, Any]:
    """Parse the wrapper's stdout into a validated rig dict.

    The wrapper prints exactly one JSON object. To stay robust against a stray
    trailing newline (or an environment that leaks one banner line), we try the
    whole payload first and fall back to the last non-empty line.

    Raises:
        RigGenerationError: if the output is empty, not JSON, or missing the
            keys the schema guarantees.
    """
    text = stdout.strip()
    if not text:
        raise RigGenerationError("wrapper produced no output on stdout")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        last_line = text.splitlines()[-1].strip()
        try:
            data = json.loads(last_line)
        except json.JSONDecodeError as exc:
            raise RigGenerationError(
                f"wrapper stdout was not valid JSON: {exc}"
            ) from exc

    if not isinstance(data, dict):
        raise RigGenerationError("wrapper JSON was not an object")

    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        raise RigGenerationError(
            f"wrapper JSON missing required keys: {', '.join(sorted(missing))}"
        )
    rig = data.get("rig")
    if not isinstance(rig, dict):
        raise RigGenerationError("wrapper JSON 'rig' was not an object")
    missing_slots = _REQUIRED_RIG_SLOTS - rig.keys()
    if missing_slots:
        raise RigGenerationError(
            f"wrapper JSON 'rig' missing slots: {', '.join(sorted(missing_slots))}"
        )
    return data


def _child_env() -> dict[str, str]:
    """Environment for the child: force UTF-8 stdout so non-ASCII (accents,
    em-dashes) survive the round-trip. Without this the wrapper's stdout uses
    the Windows locale (cp1252), which we then mis-decode as UTF-8 and corrupt.
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    """Kill the child *and its descendants*.

    The wrapper spawns the provider (e.g. ``codex.exe``) as a grandchild. A plain
    ``proc.kill()`` leaves that grandchild alive holding the write end of our
    stdout pipe, so the subsequent drain never sees EOF and blocks forever. On
    Windows ``taskkill /T`` walks the tree; elsewhere we fall back to killing the
    process group / the child.
    """
    try:
        if sys.platform == "win32":
            subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        else:
            proc.kill()
    except Exception:  # noqa: BLE001 - best-effort cleanup; never mask the timeout
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _default_runner(cmd: list[str], cwd: str, timeout: int) -> ProcessResult:
    """Run ``cmd`` directly (no shell) and capture stdout/stderr as UTF-8 text.

    Uses an explicit argv list — never a command string — so artist/title cannot
    be reinterpreted by a shell. On timeout the whole process tree is killed so a
    surviving provider grandchild cannot wedge the pipe drain.
    """
    creationflags = 0
    if sys.platform == "win32":
        # Own process group so the tree can be signalled/killed independently.
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(  # noqa: S603 - argv list, no shell, trusted script
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_child_env(),
        creationflags=creationflags,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        raise
    return ProcessResult(proc.returncode, stdout or "", stderr or "")


# A runner takes (argv, cwd, timeout) and returns a ProcessResult. Injectable so
# tests can supply a fake without spawning a real process.
Runner = Callable[[list[str], str, int], ProcessResult]


class SongRigGenerationService:
    """Generate a structured GP-180 rig for a song via the local AI wrapper."""

    def __init__(
        self,
        *,
        python_exe: str | None = None,
        tools_dir: Path | str | None = None,
        provider: str | None = None,
        timeout: int | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._python_exe = python_exe or sys.executable
        self._tools_dir = Path(tools_dir) if tools_dir else _project_root() / "tools"
        self._provider = provider or None
        self._timeout = int(timeout) if timeout else DEFAULT_TIMEOUT_SECONDS
        self._runner: Runner = runner or _default_runner

    @property
    def script_path(self) -> Path:
        return self._tools_dir / "codex_song_rig.py"

    def build_command(
        self,
        artist: str,
        title: str,
        *,
        genre: str | None = None,
        target_guitar: str | None = None,
        refresh: bool = False,
        facts_file: Path | str | None = None,
    ) -> list[str]:
        """Build the argv list for the wrapper. Exposed for inspection/tests."""
        cmd: list[str] = [self._python_exe, str(self.script_path), artist, title]
        if genre:
            cmd += ["--genre", genre]
        if target_guitar:
            cmd += ["--target-guitar", target_guitar]
        if facts_file:
            cmd += ["--facts-file", str(facts_file)]
        if self._provider:
            cmd += ["--provider", self._provider]
        if refresh:
            cmd.append("--refresh")
        cmd += ["--timeout", str(self._timeout)]
        return cmd

    def generate(
        self,
        artist: str,
        title: str,
        *,
        genre: str | None = None,
        target_guitar: str | None = None,
        refresh: bool = False,
        facts_file: Path | str | None = None,
    ) -> GeneratedRig:
        """Run the wrapper and return the parsed rig.

        Blocking — call from a worker thread (``asyncio.to_thread``) in async
        contexts. Raises :class:`RigGenerationError` on any failure; the caller
        is expected to keep the previously stored rig in that case.

        ``facts_file`` points at a verified-facts block (see
        :mod:`fretwise.rig_pipeline`); when given, the wrapper grounds the prompt
        on it.
        """
        artist = (artist or "").strip()
        title = (title or "").strip()
        if not artist or not title:
            raise RigGenerationError("artist and title are both required")
        if not self.script_path.is_file():
            raise RigGenerationError(f"wrapper script not found: {self.script_path}")

        cmd = self.build_command(
            artist,
            title,
            genre=genre,
            target_guitar=target_guitar,
            refresh=refresh,
            facts_file=facts_file,
        )
        cwd = str(self._tools_dir.parent)
        try:
            result = self._runner(cmd, cwd, self._timeout)
        except subprocess.TimeoutExpired as exc:
            raise RigGenerationError(
                f"rig generation timed out after {self._timeout}s"
            ) from exc
        except OSError as exc:
            raise RigGenerationError(f"failed to launch wrapper: {exc}") from exc

        if result.returncode != 0:
            raise RigGenerationError(
                "rig generation wrapper exited with a non-zero status",
                returncode=result.returncode,
                stderr=result.stderr,
            )

        data = parse_rig_output(result.stdout)
        return GeneratedRig.from_json(data)


def _project_root() -> Path:
    # src/fretwise/rig_generation.py -> parents[2] == repository root
    return Path(__file__).resolve().parents[2]
