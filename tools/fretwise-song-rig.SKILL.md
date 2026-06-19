---
name: fretwise-song-rig
description: Generate structured local guitar rig data for FretWise from an artist and song title. Use when Codex or another local provider must create or enrich a GP-180 song rig JSON, integrate the local wrapper in FretWise, call Codex non-interactively, or consume rig JSON from tools/codex_song_rig.py.
---

# FretWise Song Rig

Use this skill to add or use local AI rig generation inside FretWise.

## Contract

FretWise calls `tools/codex_song_rig.py` as a child process and reads one JSON object from stdout.

Required input:
- `artist`
- `title`

Optional input:
- `target_guitar`
- `provider`
- `refresh`
- `out`

Required output:
- JSON matching `tools/codex_song_rig.schema.json`.

## Integration Rules

1. Keep all files local to the FretWise repository.
2. Do not hard-code the Codex binary path in FretWise code. Let the wrapper resolve it, or pass `CODEX_BIN`.
3. Launch the wrapper directly, not through PowerShell, because shell startup text can pollute stdout.
4. Treat generation as slow I/O. Run asynchronously, show progress, and allow cancellation.
5. Cache generated results. Use `--refresh` only when the user explicitly asks to regenerate.
6. Parse stdout as JSON only after process exit code `0`.
7. If exit code is non-zero, show stderr/log details to the user and keep the previous rig data.
8. Store accepted JSON in FretWise's normal song/catalog data store.

## Provider Selection

Default provider is read from `tools/fretwise_ai_rig.config.json`.

Supported wrapper targets:
- `codex`: production path today; calls local `codex exec`.
- `lmstudio`: planned local OpenAI-compatible HTTP endpoint.
- `openai`: planned direct OpenAI-compatible HTTP endpoint.
- `mcp`: planned external command/MCP bridge.

When modifying FretWise, add provider as a setting rather than branching UI logic everywhere.

## C# Process Pattern

Use `ProcessStartInfo` with:
- `UseShellExecute = false`
- `RedirectStandardOutput = true`
- `RedirectStandardError = true`
- `CreateNoWindow = true`
- `ArgumentList` instead of one quoted command string

Never use shell redirection or profile-loaded shells for this call.

## Prompt Resource

The generation prompt is `tools/fretwise_song_rig.prompt.md`.
The wrapper substitutes:
- `{{artist}}`
- `{{title}}`
- `{{target_guitar}}`
- `{{skill_file}}`
- `{{schema_file}}`

Edit the prompt file to change generation behavior without recompiling FretWise.
