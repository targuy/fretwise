#!/usr/bin/env python3
"""Local FretWise AI rig wrapper.

Current production provider: Codex CLI (`codex exec`).
Prepared provider hooks: LM Studio, OpenAI-compatible HTTP, MCP/command bridge.

The script prints exactly one JSON object to stdout on success.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = TOOLS_DIR / "fretwise_ai_rig.config.json"


def slug(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("&", "and").replace("/", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "unknown"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_tool_path(config: dict[str, Any], key: str) -> Path:
    value = config["paths"][key]
    path = Path(value)
    if not path.is_absolute():
        path = TOOLS_DIR / path
    return path.resolve()


def render_prompt(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def load_prompt(args: argparse.Namespace, config: dict[str, Any]) -> tuple[str, Path]:
    prompt_file = args.prompt_file or resolve_tool_path(config, "prompt_file")
    skill_file = args.skill_file or resolve_tool_path(config, "skill_file")
    schema_file = args.schema or resolve_tool_path(config, "schema_file")
    target = args.target_guitar or "Non specifiee"
    genre = args.genre or "A deduire du morceau"
    template = prompt_file.read_text(encoding="utf-8")
    prompt = render_prompt(
        template,
        {
            "artist": args.artist,
            "title": args.title,
            "genre": genre,
            "target_guitar": target,
            "skill_file": str(skill_file),
            "schema_file": str(schema_file),
        },
    )
    # Grounding: prepend a verified-facts block (supplied by a FactsProvider) so
    # the model anchors on real sources instead of its parametric memory. The
    # hard facts are still re-asserted deterministically downstream (override).
    facts_file = getattr(args, "facts_file", None)
    if facts_file and Path(facts_file).is_file():
        facts = Path(facts_file).read_text(encoding="utf-8").strip()
        if facts:
            prompt = (
                "## FAITS VERIFIES (sources fiables) — VERITE A RESPECTER\n"
                "Ces faits sont verifies et sources. Accordage, capo, ampli, distorsion,\n"
                "effets et guitare DOIVENT en decouler. Mappe vers le preset GP-180 le plus\n"
                "proche de la palette.\n\n" + facts + "\n\n---\n\n" + prompt
            )
    return prompt, schema_file


def find_codex_bin(config: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("CODEX_BIN"):
        return os.environ["CODEX_BIN"]
    configured = config.get("codex", {}).get("bin")
    if configured:
        return configured

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates = sorted(
            Path(local_app_data).glob("OpenAI/Codex/bin/*/codex.exe"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return str(candidates[0])
    return "codex"


def run_codex(args: argparse.Namespace, config: dict[str, Any], out_path: Path) -> None:
    prompt, schema_file = load_prompt(args, config)
    codex_cfg = config.get("codex", {})
    command = [
        find_codex_bin(config, args.codex_bin),
        "exec",
        *codex_cfg.get("extra_args", []),
        "-C",
        str(TOOLS_DIR.parent),
        "--sandbox",
        args.sandbox or codex_cfg.get("sandbox", "read-only"),
        "--output-schema",
        str(schema_file),
        "-o",
        str(out_path),
        prompt,
    ]
    completed = subprocess.run(
        command,
        cwd=str(TOOLS_DIR.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=args.timeout or codex_cfg.get("timeout_seconds", 300),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "codex provider failed\n"
            f"returncode: {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def post_openai_compatible(base_url: str, api_key: str | None, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"HTTP provider failed: {exc}") from exc


def run_http_provider(args: argparse.Namespace, config: dict[str, Any], provider: str, out_path: Path) -> None:
    prompt, schema_file = load_prompt(args, config)
    schema = read_json(schema_file)
    cfg = config[provider]
    api_key = None
    if provider == "openai":
        api_key = os.environ.get(cfg.get("api_key_env", "OPENAI_API_KEY"))
        if not api_key:
            raise RuntimeError(f"Missing API key env var: {cfg.get('api_key_env', 'OPENAI_API_KEY')}")

    payload = {
        "model": args.model or cfg["model"],
        "messages": [
            {"role": "system", "content": "Return only valid JSON matching the requested schema."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "fretwise_song_rig",
                "strict": True,
                "schema": schema,
            },
        },
    }
    response = post_openai_compatible(cfg["base_url"], api_key, payload, args.timeout or cfg.get("timeout_seconds", 180))
    content = response["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    out_path.write_text(json.dumps(parsed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def run_ollama(args: argparse.Namespace, config: dict[str, Any], out_path: Path) -> None:
    """Generate via a local Ollama server using native /api/chat structured output.

    Uses Ollama's ``format`` field (a JSON schema) so the model is constrained to
    emit schema-conforming JSON — more reliable than OpenAI-compat ``strict`` mode
    for local models. Thinking is disabled by default for speed/cleanliness on
    thinking-capable models (e.g. gemma4).
    """
    prompt, schema_file = load_prompt(args, config)
    schema = read_json(schema_file)
    cfg = config.get("ollama", {})
    base_url = cfg.get("base_url", "http://127.0.0.1:11434")
    model = args.model or cfg.get("model", "gemma4")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only valid JSON matching the requested schema. No markdown, no commentary."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": schema,
        "options": {"temperature": cfg.get("temperature", 0)},
    }
    if cfg.get("disable_thinking", True):
        payload["think"] = False
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout or cfg.get("timeout_seconds", 300)) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama provider failed: {exc}") from exc
    content = body.get("message", {}).get("content", "")
    parsed = json.loads(content)
    out_path.write_text(json.dumps(parsed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def run_mcp(args: argparse.Namespace, config: dict[str, Any], out_path: Path) -> None:
    cfg = config.get("mcp", {})
    command = cfg.get("command")
    if not command:
        raise RuntimeError("MCP provider is configured but mcp.command is null.")
    prompt, _schema_file = load_prompt(args, config)
    completed = subprocess.run(
        [command, *cfg.get("args", [])],
        input=prompt,
        cwd=str(TOOLS_DIR.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=args.timeout or cfg.get("timeout_seconds", 180),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"MCP command failed:\n{completed.stderr}")
    parsed = json.loads(completed.stdout)
    out_path.write_text(json.dumps(parsed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate FretWise GP-180 rig JSON.")
    parser.add_argument("artist")
    parser.add_argument("title")
    parser.add_argument("--genre")
    parser.add_argument("--target-guitar")
    parser.add_argument("--provider", choices=["codex", "ollama", "lmstudio", "openai", "mcp"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--skill-file", type=Path)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--facts-file", type=Path, help="Verified-facts block to ground the prompt.")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--codex-bin")
    parser.add_argument("--sandbox")
    parser.add_argument("--model")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = read_json(args.config.resolve())
    provider = args.provider or config.get("provider", "codex")
    cache_dir = resolve_tool_path(config, "cache_dir")
    cache_dir.mkdir(parents=True, exist_ok=True)

    target_suffix = f"__{slug(args.target_guitar)}" if args.target_guitar else ""
    genre_suffix = f"__{slug(args.genre)}" if args.genre else ""
    schema_suffix = "__schema_genre_v1"
    default_out = (
        cache_dir
        / (
            f"{provider}__{slug(args.artist)}__{slug(args.title)}"
            f"{genre_suffix}{target_suffix}{schema_suffix}.json"
        )
    )
    out_path = (args.out or default_out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.refresh or not out_path.exists():
        if provider == "codex":
            run_codex(args, config, out_path)
        elif provider == "ollama":
            run_ollama(args, config, out_path)
        elif provider in {"lmstudio", "openai"}:
            run_http_provider(args, config, provider, out_path)
        elif provider == "mcp":
            run_mcp(args, config, out_path)
        else:
            raise RuntimeError(f"Unknown provider: {provider}")

    data = json.loads(out_path.read_text(encoding="utf-8"))
    sys.stdout.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
