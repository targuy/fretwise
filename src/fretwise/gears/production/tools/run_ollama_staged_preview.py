# ruff: noqa: E501 — long lines are verbatim LLM prompt/skill strings ported from SongsGears.
import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from fretwise.gears.production.env import load_project_env
from fretwise.gears.production.llm import build_stage_prompt, request_json, stage_schema
from fretwise.gears.production.models import normalize_rig
from fretwise.gears.production.paths import default_config_path, default_production_root
from fretwise.gears.production.schema import load_json, validate_rig
from fretwise.gears.production.skills import load_gp180_allowed_catalog, load_skill_stage

STAGE_REFERENCES = {
    "general": """Compact tone research stage for a local Gemma smoke run.

Find the likely guitar tone for the song. Keep it practical and concise.
Prefer well-known amp, cab, guitar, and effects references. If uncertain, state the assumption.
Return only the requested stage JSON.""",
    "gp180": """Compact Valeton GP-180 translation stage for a local Gemma smoke run.

Create 3 to 5 GP-180 blocks. Use practical GP-180-style names such as:
Noise Gate, Comp, Tube Drive, UK 45, UK 50, UK SLP, US Deluxe, US Twin, AC30 TB,
Recti, UK Vintage 4x12, US 2x12, Graphic EQ, Chorus, Phaser, Digital Delay,
Analog Delay, Plate Reverb, Spring Reverb, Room Reverb.
Every block must include order, role, module, model, active, settings, purpose,
matchQuality, gap, and alternatives.
Return only the requested stage JSON.""",
    "improvements": """Compact NAM / SnapTone / IR improvement stage for a local Gemma smoke run.

Recommend only upgrades that would materially improve the generated GP-180 match.
Use an empty proposals array if no clear upgrade is needed.
Return only the requested stage JSON.""",
}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run the staged LLM workflow over songs.tsv.")
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Pipeline config JSON (default: packaged config.example.json).",
    )
    parser.add_argument("--input", default="songs.tsv")
    parser.add_argument("--provider", choices=["ollama", "openai", "claude"])
    parser.add_argument("--model")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--output-root",
        default=str(default_production_root() / "Preview"),
        help="Root output directory (default: <repo>/exports/gears_production/Preview). "
        "Results are written under <root>/Ollama, <root>/ChatGPT, or <root>/Claude.",
    )
    parser.add_argument("--output-dir", help=argparse.SUPPRESS)
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=65536,
        help="Ollama-only num_ctx option. 65536 fits the full current prompts with less RAM than 131072.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="Provider max output tokens when supported, mainly useful for Claude.",
    )
    parser.add_argument(
        "--general-reference-chars", type=int, default=0, help="0 means use the full reference."
    )
    parser.add_argument(
        "--gp180-reference-chars", type=int, default=0, help="0 means use the full reference."
    )
    parser.add_argument(
        "--improvements-reference-chars",
        type=int,
        default=0,
        help="0 means use the full reference.",
    )
    parser.add_argument("--no-md", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--print-md", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args(argv)

    base_dir = Path.cwd()
    load_project_env(base_dir, (base_dir / args.config).parent)
    config = load_json(str(base_dir / args.config))
    if args.max_tokens:
        config.setdefault("llm", {})["max_tokens"] = args.max_tokens
    provider = args.provider or default_provider(config)
    model = args.model or default_model(config, provider)
    output_dir = provider_output_dir(base_dir, args.output_root, provider)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = list(load_songs(base_dir / args.input))
    selected = rows[args.offset : args.offset + args.limit]
    if not selected:
        raise SystemExit("No songs selected.")

    timing_stats = TimingStats()

    for index, row in enumerate(selected, start=1):
        request = request_from_row(row)
        label = f"{request['artist']} - {request['title']}"
        print(f"\n=== {index}/{len(selected)} {label} ===", flush=True)
        try:
            rig, timings = run_stages(
                request=request,
                config=config,
                provider=provider,
                model=model,
                reference_limits={
                    "general": args.general_reference_chars,
                    "gp180": args.gp180_reference_chars,
                    "improvements": args.improvements_reference_chars,
                },
                num_ctx=args.num_ctx if provider == "ollama" else None,
            )
            timing_stats.add_many(timings)
            output_record = build_output_record(
                rig=rig,
                timings=timings,
                timing_summary=timing_stats.summary(),
                provider=provider,
                model=model,
                input_path=args.input,
                source_index=args.offset + index,
                num_ctx=args.num_ctx if provider == "ollama" else None,
            )
            output_path = output_dir / song_output_filename(rig["song"])
            write_json(output_path, output_record)
            print(run_preview(rig, output_path), flush=True)
            print(timing_stats.format_summary(), flush=True)
        except Exception as exc:
            print(f"ERROR: {exc}", flush=True)
            if args.stop_on_error:
                raise

    print(f"\nDone. Output dir: {output_dir}", flush=True)
    return 0


def default_provider(config):
    provider = str(config.get("llm", {}).get("provider", "")).lower()
    return provider if provider in ("ollama", "openai", "claude") else "ollama"


def default_model(config, provider):
    configured = config.get("llm", {}).get("model", "")
    if configured and default_provider(config) == provider:
        return configured
    defaults = {
        "ollama": "gemma4:latest",
        "openai": "gpt-4.1-mini",
        "claude": "claude-sonnet-4-5",
    }
    return defaults[provider]


def provider_display_name(provider):
    return {
        "ollama": "Ollama",
        "openai": "ChatGPT",
        "claude": "Claude",
    }[provider]


def provider_output_dir(base_dir, output_root, provider):
    return base_dir / output_root / provider_display_name(provider)


def run_stages(request, config, provider, model, reference_limits, num_ctx):
    timings = []
    general_prompt = build_stage_prompt(
        "general",
        request,
        stage_reference(config, "general", reference_limits["general"]),
    )
    general, timing = ask_llm("general", general_prompt, provider, model, config, num_ctx)
    timings.append(timing)
    print(f"Step 1/3 general ({timing['seconds']:.1f}s)", flush=True)

    gp180_prompt = build_stage_prompt(
        "gp180",
        request,
        stage_reference(config, "gp180", reference_limits["gp180"]),
        {"general_result": general},
        allowed_catalog=gp180_allowed_catalog(config),
    )
    gp180, timing = ask_llm("gp180", gp180_prompt, provider, model, config, num_ctx)
    timings.append(timing)
    print(f"Step 2/3 gp180 ({timing['seconds']:.1f}s)", flush=True)

    improvements_prompt = build_stage_prompt(
        "improvements",
        request,
        stage_reference(config, "improvements", reference_limits["improvements"]),
        {"general_result": general, "gp180_result": gp180},
    )
    improvements, timing = ask_llm(
        "improvements", improvements_prompt, provider, model, config, num_ctx
    )
    timings.append(timing)
    print(f"Step 3/3 improvements ({timing['seconds']:.1f}s)", flush=True)

    rig = assemble_rig(request, general, gp180, improvements)
    return rig, timings


def ask_llm(stage, prompt, provider, model, config, num_ctx=None):
    ollama_options = None
    if num_ctx:
        ollama_options = {"num_ctx": num_ctx}
    started = time.perf_counter()
    result, response = request_json(
        provider,
        prompt,
        model,
        config,
        output_schema=stage_schema(stage),
        schema_name=f"{stage}_stage",
        ollama_options=ollama_options,
    )
    elapsed = time.perf_counter() - started
    timing = {
        "provider": provider,
        "stage": stage,
        "seconds": round(elapsed, 3),
        "prompt_chars": len(prompt),
        "response_chars": len(response),
        "num_ctx": num_ctx,
    }
    return result, timing


class TimingStats:
    def __init__(self):
        self.by_stage = {}
        self.all_seconds = []

    def add_many(self, timings):
        for timing in timings:
            seconds = float(timing["seconds"])
            self.all_seconds.append(seconds)
            self.by_stage.setdefault(timing["stage"], []).append(seconds)

    def summary(self):
        stages = {}
        for stage, values in self.by_stage.items():
            stages[stage] = {
                "count": len(values),
                "avg_seconds": round(sum(values) / len(values), 3),
                "last_seconds": round(values[-1], 3),
            }
        return {
            "all": {
                "count": len(self.all_seconds),
                "avg_seconds": round(sum(self.all_seconds) / len(self.all_seconds), 3)
                if self.all_seconds
                else 0,
                "last_seconds": round(self.all_seconds[-1], 3) if self.all_seconds else 0,
            },
            "stages": stages,
        }

    def format_summary(self):
        summary = self.summary()
        parts = [
            f"Timing avg all: {summary['all']['avg_seconds']:.1f}s over {summary['all']['count']} request(s)"
        ]
        for stage in ("general", "gp180", "improvements"):
            stage_summary = summary["stages"].get(stage)
            if stage_summary:
                parts.append(f"{stage}: {stage_summary['avg_seconds']:.1f}s avg")
        return " | ".join(parts)


def assemble_rig(request, general_result, gp180_result, improvements_result):
    general = general_result.get("general", general_result)
    gp180 = gp180_result.get("gp180", gp180_result)
    improvements = improvements_result.get("improvements", improvements_result)
    blocks = normalize_blocks(gp180.get("blocks", []))
    gp180["blocks"] = blocks
    rig = {
        "rigName": f"{request['artist']} - {request['title']} - {gp180.get('equipment', {}).get('model', request['equipment'])}",
        "song": {
            "artist": request["artist"],
            "title": request["title"],
            "album": request.get("album", ""),
            "year": safe_int(request.get("year")),
            "genre": request.get("genre", ""),
        },
        "equipment": gp180.get("equipment", {"model": request["equipment"]}),
        "guitar": gp180.get("guitar", request["guitar"]),
        "output": gp180.get("output", request["output"]),
        "toneProfile": general.get("toneProfile") or general.get("targetSound", ""),
        "status": "draft",
        "confidence": lowest_confidence(
            [
                general_result.get("confidence", "unknown"),
                gp180_result.get("confidence", "unknown"),
                improvements_result.get("confidence", "unknown"),
            ]
        ),
        "signalChainSummary": gp180.get("bestMatchSummary") or general.get("idealSignalChain", ""),
        "blocks": blocks,
        "general": general,
        "gp180": gp180,
        "improvements": improvements,
        "assumptions": general_result.get("assumptions", []),
        "warnings": gp180_result.get("warnings", []) + improvements_result.get("warnings", []),
        "sources": general_result.get("sources", []),
        "createdFrom": "generated",
        "needsReview": True,
    }
    return validate_rig(normalize_rig(rig))


def build_output_record(
    rig, timings, timing_summary, provider, model, input_path, source_index, num_ctx=None
):
    return {
        "metadata": {
            "provider": provider_display_name(provider),
            "providerId": provider,
            "model": model,
            "input": input_path,
            "sourceIndex": source_index,
            "numCtx": num_ctx,
        },
        "song": rig["song"],
        "synthesis": {
            "rigName": rig.get("rigName", ""),
            "toneProfile": rig.get("toneProfile", ""),
            "signalChainSummary": rig.get("signalChainSummary", ""),
            "confidence": rig.get("confidence", "unknown"),
            "needsReview": rig.get("needsReview", True),
            "equipment": rig.get("equipment", {}),
            "guitar": rig.get("guitar", ""),
            "output": rig.get("output", ""),
            "blocks": rig.get("blocks", []),
            "assumptions": rig.get("assumptions", []),
            "warnings": rig.get("warnings", []),
            "sources": rig.get("sources", []),
        },
        "phases": {
            "general": rig.get("general", {}),
            "gp180": rig.get("gp180", {}),
            "improvements": rig.get("improvements", {}),
        },
        "timings": {
            "requests": timings,
            "runningAverages": timing_summary,
        },
        "rig": rig,
    }


def run_preview(rig, output_path=None):
    blocks = rig.get("blocks", [])
    lines = []
    if output_path is not None:
        lines.append(f"Output JSON -> {output_path}")
    lines.extend(
        [
            f"Tone: {rig.get('toneProfile', '')}",
            f"Signal chain: {rig.get('signalChainSummary', '')}",
            f"Blocks: {len(blocks)} | Confidence: {rig.get('confidence', 'unknown')}",
        ]
    )
    return "\n".join(lines)


def load_songs(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        delimiter = (
            "\t"
            if path.suffix.lower() == ".tsv"
            else csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
        )
        for row in csv.DictReader(handle, delimiter=delimiter):
            cleaned = {key: clean(value) for key, value in row.items()}
            if cleaned.get("status", "").lower() in (
                "done",
                "generated",
                "published",
            ) and cleaned.get("skip_existing"):
                continue
            yield cleaned


def request_from_row(row):
    return {
        "artist": row.get("artist", ""),
        "title": row.get("title", "") or row.get("song", ""),
        "album": row.get("album", ""),
        "year": row.get("year", ""),
        "genre": row.get("genre", ""),
        "equipment": row.get("rig", "") or row.get("equipment", "") or "Valeton GP-180",
        "guitar": row.get("guitar", "") or "Default electric guitar",
        "output": row.get("output", "") or "FRFR / headphones",
        "mode": "best_match",
    }


def stage_reference(config, stage, max_chars):
    stage_ids = {
        "general": "general_rig",
        "gp180": "gp180_translation",
        "improvements": "nam_ir_replacement",
    }
    try:
        configured = load_skill_stage(str(Path.cwd()), config, stage_ids[stage])
    except Exception:
        configured = ""
    reference = configured.strip() if configured.strip() else STAGE_REFERENCES[stage]
    return bounded_reference(stage, reference, max_chars)


def bounded_reference(stage, reference, max_chars):
    if not max_chars or max_chars <= 0:
        return reference
    if len(reference) <= max_chars:
        return reference
    head_chars = int(max_chars * 0.72)
    tail_chars = max_chars - head_chars
    head = reference[:head_chars].rstrip()
    tail = reference[-tail_chars:].lstrip()
    return "\n\n".join(
        [
            head,
            f"[... {stage} skill excerpt truncated to fit local Gemma context; omitted middle sections, kept beginning rules and ending checklists/examples ...]",
            tail,
        ]
    )


def normalize_blocks(blocks):
    normalized = []
    for index, raw_block in enumerate(blocks or [], start=1):
        block = dict(raw_block) if isinstance(raw_block, dict) else {}
        block.setdefault("order", index)
        block.setdefault("role", block.get("module", "unknown"))
        block.setdefault("module", block.get("role", "unknown"))
        block.setdefault("model", "None")
        block.setdefault("active", block.get("model") not in ("", "None", None))
        block.setdefault("settings", {})
        block.setdefault("purpose", "")
        block.setdefault("alternatives", [])
        block.setdefault("matchQuality", "fallback")
        block.setdefault(
            "gap", "Gemma omitted one or more GP-180 block details; this block needs manual review."
        )
        normalized.append(block)
    return normalized


def gp180_allowed_catalog(config):
    catalog = load_gp180_allowed_catalog(str(Path.cwd()), config).strip()
    if catalog:
        return catalog
    return """# GP-180 ALLOWED MODEL CATALOG (FALLBACK)

Use exact names when possible. If the ideal gear is absent, choose the closest GP-180-style model, set `matchQuality`, and document `gap`.

## NR
None; Gate 1; Gate 2; Gate 3

## PRE / DST
None; Comp; Boost; Green OD; Blues OD; Chief; Red Haze; Distortion; Fuzz

## AMP
None; UK 45; UK 50; UK SLP; UK 800; US Deluxe; Silver Twin; AC30 TB; Recti; EV 51

## CAB / IR
None; UK Vintage 4x12; UK Basket 4x12; UK 30 4x12; US 2x12; Mess 4x12; User IR 1

## EQ / MOD / DLY / RVB
None; Guitar EQ 1; Guitar EQ 2; Chorus; O-Phase; Digital Delay; Tape; Plate; Room; Spring
"""


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def clean(value):
    return "" if value is None else value.strip()


def safe_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except ValueError:
        return None


def lowest_confidence(values):
    order = {"unknown": 0, "low": 1, "medium": 2, "medium/high": 3, "high": 4}
    normalized = [str(value).lower() for value in values if value]
    return min(normalized, key=lambda value: order.get(value, 0)) if normalized else "unknown"


def song_output_filename(song):
    artist = filename_token(song.get("artist"), "unknown_artist")
    title = filename_token(song.get("title"), "unknown_title")
    return f"{artist}__{title}.json"


def filename_token(value, fallback):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return text[:80] or fallback


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
