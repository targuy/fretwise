# ruff: noqa: E501 — long lines are verbatim LLM prompt/skill strings ported from SongsGears.
import argparse
import json
import random
import sys
import time
from pathlib import Path

from fretwise.gears.production.env import load_project_env
from fretwise.gears.production.llm import request_claude_cached_json, request_json_with_usage
from fretwise.gears.production.paths import default_config_path, default_production_root
from fretwise.gears.production.schema import load_json
from fretwise.gears.production.tools.run_ollama_staged_preview import (
    assemble_rig,
    load_songs,
    request_from_row,
    song_output_filename,
    write_json,
)

CHATGPT_PROVIDER = "openai"
OLLAMA_PROVIDER = "ollama"
CLAUDE_PROVIDER = "claude"


CLAUDE_MUSIC_ARBITER_SYSTEM = """You are a strict musical tone arbiter for guitar-rig generation.

Your only job is to correct the musical target before any device-specific preset is generated.
Do not write a GP-180 preset. Do not write amp settings. Do not propose NAM or IR assets.
You compare two compact analyses from other models and output one short corrected verdict.

Decision policy:
- Prefer the answer that identifies the most song-specific sonic signature, not the most generic artist style.
- For famous recordings, prioritize the recorded guitar texture over live versions or later gear myths.
- Identify non-negotiable tone elements: gain family, pickup/guitar clues, amp family, cabinet size, fuzz/drive/wah/modulation/delay/reverb, EQ shape, production era.
- Penalize generic answers such as "classic rock crunch" when the track has a distinctive fuzz, chorus, slapback, octave, sitar-like, clean-compressed, or studio-specific character.
- Correct hallucinated gear only if it materially changes the target sound.
- If both drafts are plausible but incomplete, set winner to "mixed".
- If both miss the signature, set winner to "neither" and provide the corrected target.

Output discipline:
- Return JSON only.
- Keep every string short. No prose paragraphs.
- Use at most 5 items per array.
- Each array item should be under 12 words.
- confidence is one of: high, medium, low.
- winner is one of: chatgpt, ollama, mixed, neither.
- agreesWithChatGPT and agreesWithOllama mean the draft captured the main sonic signature, not just a few details.

Required JSON shape:
{
  "targetTone": "short phrase",
  "mustHave": ["short"],
  "avoid": ["short"],
  "gearClues": ["short"],
  "corrections": ["short"],
  "winner": "chatgpt|ollama|mixed|neither",
  "agreesWithChatGPT": true,
  "agreesWithOllama": false,
  "confidence": "high|medium|low",
  "needsManualReview": false
}

Consistency rules:
- If winner is "chatgpt", agreesWithChatGPT should normally be true.
- If winner is "ollama", agreesWithOllama should normally be true.
- If winner is "mixed", both booleans may be true when both caught the core signature, or one may be true if only one core idea survives.
- If winner is "neither", both booleans should normally be false.

This cached instruction is intentionally stable across all songs in a batch. The changing song request and model drafts arrive in the user message only.

Compact sonic checklist for arbitration:
- Era matters: 1950s rockabilly, 1960s garage, 1960s psychedelic, 1970s classic rock, 1980s chorus clean, 1990s high gain, modern metal, funk, reggae, disco, punk, shoegaze, grunge, indie, country, blues, soul, pop.
- Gain family matters: pristine clean, compressed clean, edge-of-breakup, low-gain overdrive, crunchy rhythm, fuzz, distortion, saturated lead, modern high gain.
- Fuzz is not generic overdrive. Fuzz Face is round and woolly; Tone Bender and Maestro-style fuzz can be nasal, buzzy, gated, and sitar-like; Big Muff is smoother and sustaining.
- Amp family matters: Vox/AC chime and upper-mid jangle, Fender clean headroom and scoop, Marshall/Plexi upper-mid crunch, Hiwatt clean authority, Mesa/Rectifier modern saturation, JC-style transistor clean, small combo boxiness.
- Cabinet size matters: 1x12 and 2x12 are focused and vintage; 4x12 is larger, punchier, and more rock-stack oriented; speaker family shifts the midrange.
- Effects matter only when audible: wah, phaser, flanger, chorus, tremolo, octave, slapback, tape delay, dotted-eighth delay, spring, plate, room.
- Production matters: close-mic dry studio, room ambience, double tracking, mono vintage, stereo chorus, bright 80s rack, dark lo-fi, compressed radio mix.
- If the song has a signature riff texture, that texture outranks broad band identity.
- If one draft names plausible gear but misses the audible texture, it is not agreement.
- If both drafts agree on a generic amp family but miss a distinctive fuzz/modulation/delay, mark both as not fully agreeing.
- If both drafts disagree but each contributes one essential clue, use winner "mixed".
- If a draft is usable as a live preset but not faithful to the record, mark partial through the boolean only if it captures the main sonic signature.
- Be terse: this arbitration feeds another generator, so short constraints are more valuable than explanation.
- Distinguish rhythm tone from lead tone if the title is known for one iconic part; choose the iconic recorded guitar part.
- Prefer audible evidence over forum-style gear trivia when the two conflict.
- Treat bass, strings, keyboards, or sitar parts as context only unless the requested guitar rig must imitate them.
- Mark needsManualReview true for uncertain studio instrumentation, disputed guitar player, or non-guitar signature tones.
- Do not reward a draft for naming many effects. Reward it for naming the decisive effect.
- Your verdict should be useful as a compact control signal for a later preset generator.
"""


MUSIC_SCHEMA = {
    "type": "object",
    "required": ["targetTone", "signatureElements", "gearHypotheses", "avoid", "confidence"],
    "properties": {
        "targetTone": {"type": "string"},
        "signatureElements": {"type": "array", "items": {"type": "string"}},
        "gearHypotheses": {"type": "array", "items": {"type": "string"}},
        "avoid": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}


GP180_SCHEMA = {
    "type": "object",
    "required": ["gp180", "warnings", "confidence", "needsReview"],
    "properties": {
        "gp180": {
            "type": "object",
            "required": [
                "equipment",
                "guitar",
                "output",
                "choicePolicy",
                "bestMatchSummary",
                "blocks",
            ],
            "properties": {
                "equipment": {"type": "object", "properties": {"model": {"type": "string"}}},
                "guitar": {"type": "string"},
                "output": {"type": "string"},
                "choicePolicy": {"type": "string"},
                "bestMatchSummary": {"type": "string"},
                "blocks": {"type": "array", "items": {"type": "object"}},
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium/high", "medium", "low", "unknown"],
        },
        "needsReview": {"type": "boolean"},
    },
}


IMPROVEMENTS_SCHEMA = {
    "type": "object",
    "required": ["improvements", "warnings", "confidence", "needsReview"],
    "properties": {
        "improvements": {
            "type": "object",
            "required": ["summary", "proposals"],
            "properties": {
                "summary": {"type": "string"},
                "proposals": {"type": "array", "items": {"type": "object"}},
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium/high", "medium", "low", "unknown"],
        },
        "needsReview": {"type": "boolean"},
    },
}


COMPACT_GP180_CATALOG = """GP-180 compact allowed names.
NR: None, Gate 1, Gate 2, Gate 3.
PRE: None, Comp, Boost, OD 9, Green OD, Blues OD.
WAH: None, V-Wah, C-Wah, B-Wah, T-Wah.
DST: None, Red Haze, Distortion, Fuzz, Chief, RAT-style, Muff-style.
AMP: UK 45, UK 50, UK SLP, UK 800, US Deluxe, Silver Twin, Foxy 30TB, AC30 TB, Bellman 59N, Recti, EV 51.
CAB/IR: UK Vintage 4x12, UK Basket 4x12, UK 30 4x12, Foxy 2x12, US 2x12, Bellman 4x10, Mess 4x12, User IR 1.
EQ/MOD/DLY/RVB/VOL: Guitar EQ 1, Guitar EQ 2, Chorus, O-Phase, Tremolo, Slapback, Digital Delay, Tape, Room, Spring, Plate, Volume.
Use exact names only. If absent, choose the closest and explain the gap."""


CLAUDE_SONNET_RATES_PER_MTOK = {
    "input_tokens": 3.0,
    "output_tokens": 15.0,
    "cache_creation_input_tokens": 3.75,
    "cache_read_input_tokens": 0.30,
}


OPENAI_RATES_PER_MTOK = {
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
    "gpt-5.4": {"input": 2.50, "cached_input": 0.25, "output": 15.00},
    "gpt-5.5": {"input": 5.00, "cached_input": 0.50, "output": 30.00},
}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Hybrid workflow: ChatGPT+Ollama draft music, Claude cached arbitration, ChatGPT+Ollama GP-180/improvements."
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Pipeline config JSON (default: packaged config.example.json).",
    )
    parser.add_argument("--input", default="songs.tsv")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260621)
    parser.add_argument(
        "--output-root",
        default=str(default_production_root() / "Hybrid"),
        help="Output root (default: <repo>/exports/gears_production/Hybrid).",
    )
    parser.add_argument("--chatgpt-model", default="gpt-4.1-mini")
    parser.add_argument("--ollama-model", default="gemma4:latest")
    parser.add_argument("--claude-model", default="claude-sonnet-4-5")
    parser.add_argument("--num-ctx", type=int, default=65536)
    parser.add_argument("--claude-max-tokens", type=int, default=700)
    parser.add_argument("--openai-prompt-cache-key", default="")
    parser.add_argument("--openai-prompt-cache-retention", default="")
    parser.add_argument("--openai-text-verbosity", default="")
    parser.add_argument("--openai-reasoning-effort", default="")
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args(argv)

    base_dir = Path.cwd()
    load_project_env(base_dir, (base_dir / args.config).parent)
    config = load_json(str(base_dir / args.config))
    config.setdefault("llm", {})["temperature"] = 0.0
    output_dir = base_dir / args.output_root / f"seed_{args.seed}_n{args.limit}"
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        row
        for row in load_songs(base_dir / args.input)
        if (row.get("artist") and (row.get("title") or row.get("song")))
    ]
    selected = random.Random(args.seed).sample(rows, min(args.limit, len(rows)))
    summary = new_summary(args)

    for index, row in enumerate(selected, start=1):
        request = request_from_row(row)
        label = f"{request['artist']} - {request['title']}"
        print(f"\n=== {index}/{len(selected)} {label} ===", flush=True)
        summary["counts"]["songsAttempted"] += 1
        try:
            record = run_song(request, config, args)
            update_summary(summary, record)
            output_path = output_dir / song_output_filename(record["song"])
            write_json(output_path, record)
            print(format_song_result(record, output_path), flush=True)
        except Exception as exc:
            error = {"song": request, "error": str(exc)}
            summary["errors"].append(error)
            print(f"ERROR: {exc}", flush=True)
            if args.stop_on_error:
                raise

    finalize_summary(summary)
    write_json(output_dir / "summary.json", summary)
    print(f"\nDone. Output dir: {output_dir}", flush=True)
    print(format_summary(summary), flush=True)
    return 0


def run_song(request, config, args):
    timings = []
    chatgpt_music, timing = timed_json(
        "music",
        CHATGPT_PROVIDER,
        args.chatgpt_model,
        music_prompt(request),
        config,
        MUSIC_SCHEMA,
        openai_options=openai_options(args, "music"),
    )
    timings.append(timing)
    print(f"Phase 1A ChatGPT music ({timing['seconds']:.1f}s)", flush=True)

    ollama_music, timing = timed_json(
        "music",
        OLLAMA_PROVIDER,
        args.ollama_model,
        music_prompt(request),
        config,
        MUSIC_SCHEMA,
        ollama_options={"num_ctx": args.num_ctx},
    )
    timings.append(timing)
    print(f"Phase 1B Ollama music ({timing['seconds']:.1f}s)", flush=True)

    claude_started = time.perf_counter()
    claude_verdict, claude_raw, claude_usage = request_claude_cached_json(
        CLAUDE_MUSIC_ARBITER_SYSTEM,
        claude_user_prompt(request, chatgpt_music, ollama_music),
        args.claude_model,
        config,
        max_tokens=args.claude_max_tokens,
    )
    claude_timing = {
        "stage": "claude_music_arbitration",
        "provider": CLAUDE_PROVIDER,
        "model": args.claude_model,
        "seconds": round(time.perf_counter() - claude_started, 3),
        "prompt_chars": len(CLAUDE_MUSIC_ARBITER_SYSTEM)
        + len(claude_user_prompt(request, chatgpt_music, ollama_music)),
        "response_chars": len(claude_raw),
        "usage": claude_usage,
    }
    timings.append(claude_timing)
    print(f"Phase 1C Claude arbitration ({claude_timing['seconds']:.1f}s)", flush=True)

    provider_outputs = {}
    for provider, model in (
        (CHATGPT_PROVIDER, args.chatgpt_model),
        (OLLAMA_PROVIDER, args.ollama_model),
    ):
        ollama_options = {"num_ctx": args.num_ctx} if provider == OLLAMA_PROVIDER else None
        gp180, timing = timed_json(
            "gp180",
            provider,
            model,
            gp180_prompt(request, claude_verdict),
            config,
            GP180_SCHEMA,
            ollama_options=ollama_options,
            openai_options=openai_options(args, "gp180") if provider == CHATGPT_PROVIDER else None,
        )
        timings.append(timing)
        print(f"Phase 2 {provider_label(provider)} GP-180 ({timing['seconds']:.1f}s)", flush=True)

        improvements, timing = timed_json(
            "improvements",
            provider,
            model,
            improvements_prompt(request, claude_verdict, gp180),
            config,
            IMPROVEMENTS_SCHEMA,
            ollama_options=ollama_options,
            openai_options=openai_options(args, "improvements")
            if provider == CHATGPT_PROVIDER
            else None,
        )
        timings.append(timing)
        print(
            f"Phase 3 {provider_label(provider)} improvements ({timing['seconds']:.1f}s)",
            flush=True,
        )

        general = general_from_claude_verdict(claude_verdict)
        rig = assemble_rig(request, general, gp180, improvements)
        provider_outputs[provider_label(provider)] = {
            "gp180": gp180,
            "improvements": improvements,
            "rig": rig,
        }

    return {
        "metadata": {
            "workflow": "hybrid_music_arbitration_v1",
            "models": {
                "chatgpt": args.chatgpt_model,
                "ollama": args.ollama_model,
                "claude": args.claude_model,
            },
        },
        "song": {
            "artist": request["artist"],
            "title": request["title"],
            "album": request.get("album", ""),
            "year": safe_int(request.get("year")),
        },
        "musicDrafts": {
            "ChatGPT": chatgpt_music,
            "Ollama": ollama_music,
        },
        "claudeArbitration": claude_verdict,
        "generated": provider_outputs,
        "comparison": compare_generated(provider_outputs, claude_verdict),
        "timings": timings,
    }


def timed_json(
    stage, provider, model, prompt, config, schema, ollama_options=None, openai_options=None
):
    started = time.perf_counter()
    result, raw, usage = request_json_with_usage(
        provider,
        prompt,
        model,
        config,
        output_schema=schema,
        schema_name=f"hybrid_{stage}",
        ollama_options=ollama_options,
        openai_options=openai_options,
    )
    return result, {
        "stage": stage,
        "provider": provider,
        "model": model,
        "seconds": round(time.perf_counter() - started, 3),
        "prompt_chars": len(prompt),
        "response_chars": len(raw),
        "usage": usage,
    }


def music_prompt(request):
    return f"""# TASK
Give only the musical target for this song. Do not generate a GP-180 preset.

Return JSON only:
{json.dumps(MUSIC_SCHEMA, ensure_ascii=False)}

Rules:
- Be song-specific, not just artist-generic.
- Keep arrays to max 5 short items.
- Mention decisive texture clues: fuzz, crunch, clean, wah, modulation, delay, reverb, amp/cab family.
- Keep the whole answer compact.

# SONG INPUT
{json.dumps(request, ensure_ascii=False, indent=2)}
"""


def claude_user_prompt(request, chatgpt_music, ollama_music):
    payload = {
        "song": request,
        "chatgptDraft": chatgpt_music,
        "ollamaDraft": ollama_music,
    }
    return "Arbitrate these two drafts and return the required short JSON.\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )


def gp180_prompt(request, claude_verdict):
    payload = {
        "song": request,
        "claudeMusicalVerdict": claude_verdict,
    }
    return f"""# TASK
Generate the GP-180 phase only from Claude's musical verdict.

Allowed catalog:
{COMPACT_GP180_CATALOG}

Return JSON only:
{json.dumps(GP180_SCHEMA, ensure_ascii=False)}

Rules:
- 8 to 12 blocks, ordered as NR/PRE/WAH/DST/N->S/AMP/CAB/EQ/MOD/DLY/RVB/VOL when useful.
- Use exact model names from the compact catalog.
- Keep settings compact.
- Document gaps honestly.

# INPUT
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


def improvements_prompt(request, claude_verdict, gp180):
    payload = {
        "song": request,
        "claudeMusicalVerdict": claude_verdict,
        "gp180Result": gp180,
    }
    return f"""# TASK
Generate NAM/SnapTone/IR improvement proposals only.

Return JSON only:
{json.dumps(IMPROVEMENTS_SCHEMA, ensure_ascii=False)}

Rules:
- Max 3 proposals.
- Use P1 only for a critical missing fuzz/amp/cab signature.
- Use priority "none" if GP-180 is already sufficient.
- Keep every reason short.

# INPUT
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


def general_from_claude_verdict(verdict):
    return {
        "general": {
            "targetSound": verdict.get("targetTone", ""),
            "toneProfile": verdict.get("targetTone", ""),
            "idealSignalChain": " | ".join(verdict.get("gearClues", [])),
            "bestPossibleEquipment": [
                {"role": "signature", "model": item, "reason": "Claude musical arbitration"}
                for item in verdict.get("gearClues", [])
            ],
            "productionNotes": verdict.get("mustHave", []),
        },
        "assumptions": verdict.get("corrections", []),
        "sources": ["ChatGPT music draft", "Ollama music draft", "Claude arbitration"],
        "confidence": confidence_to_schema(verdict.get("confidence", "medium")),
        "needsReview": bool(verdict.get("needsManualReview", False)),
    }


def compare_generated(provider_outputs, claude_verdict):
    chatgpt_models = block_models(provider_outputs["ChatGPT"]["rig"].get("blocks", []))
    ollama_models = block_models(provider_outputs["Ollama"]["rig"].get("blocks", []))
    overlap = sorted(set(chatgpt_models) & set(ollama_models))
    return {
        "claudeAgreement": {
            "agreesWithChatGPT": bool(claude_verdict.get("agreesWithChatGPT")),
            "agreesWithOllama": bool(claude_verdict.get("agreesWithOllama")),
            "winner": claude_verdict.get("winner", "unknown"),
        },
        "gp180ModelOverlap": overlap,
        "chatgptModels": chatgpt_models,
        "ollamaModels": ollama_models,
    }


def block_models(blocks):
    return [
        str(block.get("model", ""))
        for block in blocks
        if block.get("active") and block.get("model")
    ]


def new_summary(args):
    return {
        "metadata": {
            "workflow": "hybrid_music_arbitration_v1",
            "limit": args.limit,
            "seed": args.seed,
            "models": {
                "chatgpt": args.chatgpt_model,
                "ollama": args.ollama_model,
                "claude": args.claude_model,
            },
        },
        "counts": {
            "songsAttempted": 0,
            "songsCompleted": 0,
            "claudeAgreedWithBoth": 0,
            "claudeAgreedWithChatGPTOnly": 0,
            "claudeAgreedWithOllamaOnly": 0,
            "claudeAgreedWithNeither": 0,
        },
        "winners": {},
        "cache": {
            "creationInputTokens": 0,
            "readInputTokens": 0,
        },
        "timings": [],
        "songs": [],
        "errors": [],
    }


def update_summary(summary, record):
    summary["counts"]["songsCompleted"] += 1
    agreement = record["comparison"]["claudeAgreement"]
    agrees_chatgpt = agreement["agreesWithChatGPT"]
    agrees_ollama = agreement["agreesWithOllama"]
    if agrees_chatgpt and agrees_ollama:
        summary["counts"]["claudeAgreedWithBoth"] += 1
    elif agrees_chatgpt:
        summary["counts"]["claudeAgreedWithChatGPTOnly"] += 1
    elif agrees_ollama:
        summary["counts"]["claudeAgreedWithOllamaOnly"] += 1
    else:
        summary["counts"]["claudeAgreedWithNeither"] += 1
    winner = agreement["winner"]
    summary["winners"][winner] = summary["winners"].get(winner, 0) + 1
    for timing in record["timings"]:
        summary["timings"].append(timing)
        usage = timing.get("usage", {})
        summary["cache"]["creationInputTokens"] += int(
            usage.get("cache_creation_input_tokens", 0) or 0
        )
        summary["cache"]["readInputTokens"] += int(usage.get("cache_read_input_tokens", 0) or 0)
    summary["songs"].append(
        {
            "song": record["song"],
            "winner": winner,
            "agreesWithChatGPT": agrees_chatgpt,
            "agreesWithOllama": agrees_ollama,
            "targetTone": record["claudeArbitration"].get("targetTone", ""),
        }
    )


def finalize_summary(summary):
    completed = summary["counts"]["songsCompleted"]
    if completed:
        summary["rates"] = {
            "claudeAgreedWithBoth": round(summary["counts"]["claudeAgreedWithBoth"] / completed, 3),
            "claudeAgreedWithChatGPT": round(
                (
                    summary["counts"]["claudeAgreedWithBoth"]
                    + summary["counts"]["claudeAgreedWithChatGPTOnly"]
                )
                / completed,
                3,
            ),
            "claudeAgreedWithOllama": round(
                (
                    summary["counts"]["claudeAgreedWithBoth"]
                    + summary["counts"]["claudeAgreedWithOllamaOnly"]
                )
                / completed,
                3,
            ),
        }
    else:
        summary["rates"] = {}
    summary["costEstimate"] = estimate_claude_sonnet_cost(summary)
    summary["openaiCostEstimate"] = estimate_openai_cost(summary)


def format_song_result(record, output_path):
    agreement = record["comparison"]["claudeAgreement"]
    return "\n".join(
        [
            f"Output JSON -> {output_path}",
            f"Claude target: {record['claudeArbitration'].get('targetTone', '')}",
            f"Winner: {agreement['winner']} | agree ChatGPT={agreement['agreesWithChatGPT']} | agree Ollama={agreement['agreesWithOllama']}",
        ]
    )


def format_summary(summary):
    counts = summary["counts"]
    return (
        "Stats Claude agreement: "
        f"both={counts['claudeAgreedWithBoth']}, "
        f"ChatGPT only={counts['claudeAgreedWithChatGPTOnly']}, "
        f"Ollama only={counts['claudeAgreedWithOllamaOnly']}, "
        f"neither={counts['claudeAgreedWithNeither']} | "
        f"cache creation={summary['cache']['creationInputTokens']} tokens, "
        f"cache read={summary['cache']['readInputTokens']} tokens, "
        f"Claude cost/song=${summary.get('costEstimate', {}).get('claudeCostPerCompletedSongUsd', 0):.4f}, "
        f"OpenAI cost/song=${summary.get('openaiCostEstimate', {}).get('costPerCompletedSongUsd', 0):.4f}"
    )


def estimate_claude_sonnet_cost(summary):
    usage_totals = {}
    for timing in summary["timings"]:
        if timing.get("provider") != CLAUDE_PROVIDER:
            continue
        for key, value in timing.get("usage", {}).items():
            if isinstance(value, (int, float)):
                usage_totals[key] = usage_totals.get(key, 0) + value
    cost_by_field = {
        key: round(usage_totals.get(key, 0) / 1_000_000 * rate, 6)
        for key, rate in CLAUDE_SONNET_RATES_PER_MTOK.items()
    }
    total = round(sum(cost_by_field.values()), 6)
    completed = summary["counts"]["songsCompleted"]
    return {
        "modelClass": "Claude Sonnet",
        "ratesPerMTokUsd": CLAUDE_SONNET_RATES_PER_MTOK,
        "usageTokens": usage_totals,
        "costByFieldUsd": cost_by_field,
        "totalClaudeCostUsd": total,
        "claudeCostPerCompletedSongUsd": round(total / completed, 6) if completed else 0,
    }


def estimate_openai_cost(summary):
    completed = summary["counts"]["songsCompleted"]
    totals = {
        "inputTokens": 0,
        "cachedInputTokens": 0,
        "outputTokens": 0,
        "totalCostUsd": 0.0,
        "batchDiscountedCostUsd": 0.0,
    }
    by_model = {}
    by_stage = {}
    unknown_models = set()
    for timing in summary["timings"]:
        if timing.get("provider") != CHATGPT_PROVIDER:
            continue
        usage = timing.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        cached_tokens = cached_input_tokens(usage)
        model = timing.get("model", "")
        rates = openai_rates_for_model(model)
        if not rates:
            unknown_models.add(model)
            cost = 0.0
        else:
            billable_input = max(input_tokens - cached_tokens, 0)
            cost = (
                billable_input / 1_000_000 * rates["input"]
                + cached_tokens / 1_000_000 * rates["cached_input"]
                + output_tokens / 1_000_000 * rates["output"]
            )
        totals["inputTokens"] += input_tokens
        totals["cachedInputTokens"] += cached_tokens
        totals["outputTokens"] += output_tokens
        totals["totalCostUsd"] += cost
        stage = timing.get("stage", "unknown")
        add_openai_bucket(by_model, model, input_tokens, cached_tokens, output_tokens, cost)
        add_openai_bucket(by_stage, stage, input_tokens, cached_tokens, output_tokens, cost)
    totals["totalCostUsd"] = round(totals["totalCostUsd"], 6)
    totals["batchDiscountedCostUsd"] = round(totals["totalCostUsd"] * 0.5, 6)
    return {
        "ratesPerMTokUsd": OPENAI_RATES_PER_MTOK,
        "usageTokens": totals,
        "byModel": finalize_openai_buckets(by_model),
        "byStage": finalize_openai_buckets(by_stage),
        "unknownModels": sorted(unknown_models),
        "costPerCompletedSongUsd": round(totals["totalCostUsd"] / completed, 6) if completed else 0,
        "batchDiscountedCostPerCompletedSongUsd": round(
            totals["batchDiscountedCostUsd"] / completed, 6
        )
        if completed
        else 0,
    }


def cached_input_tokens(usage):
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    if isinstance(details, dict):
        return int(details.get("cached_tokens") or 0)
    return 0


def openai_rates_for_model(model):
    if model in OPENAI_RATES_PER_MTOK:
        return OPENAI_RATES_PER_MTOK[model]
    for prefix, rates in OPENAI_RATES_PER_MTOK.items():
        if model.startswith(prefix):
            return rates
    return None


def add_openai_bucket(bucket, key, input_tokens, cached_tokens, output_tokens, cost):
    data = bucket.setdefault(
        key,
        {"inputTokens": 0, "cachedInputTokens": 0, "outputTokens": 0, "totalCostUsd": 0.0},
    )
    data["inputTokens"] += input_tokens
    data["cachedInputTokens"] += cached_tokens
    data["outputTokens"] += output_tokens
    data["totalCostUsd"] += cost


def finalize_openai_buckets(bucket):
    return {
        key: {**value, "totalCostUsd": round(value["totalCostUsd"], 6)}
        for key, value in sorted(bucket.items())
    }


def openai_options(args, stage):
    options = {}
    if args.openai_prompt_cache_key:
        options["prompt_cache_key"] = f"{args.openai_prompt_cache_key}:{stage}"
    if args.openai_prompt_cache_retention:
        options["prompt_cache_retention"] = args.openai_prompt_cache_retention
    if args.openai_text_verbosity:
        options["text_verbosity"] = args.openai_text_verbosity
    if args.openai_reasoning_effort:
        options["reasoning_effort"] = args.openai_reasoning_effort
    return options or None


def provider_label(provider):
    return {"openai": "ChatGPT", "ollama": "Ollama", "claude": "Claude"}[provider]


def confidence_to_schema(value):
    if value == "high":
        return "high"
    if value == "low":
        return "low"
    return "medium"


def safe_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
