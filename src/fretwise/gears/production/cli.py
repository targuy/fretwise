import argparse
import csv
import json
import os
import sys

from .env import load_project_env
from .llm import build_prompt, build_stage_prompt, generate_rig
from .notion import NotionClient
from .render import notion_payload
from .schema import load_json
from .skills import (
    gp180_stage_brief,
    load_gp180_allowed_catalog,
    load_skill_prompt,
    load_skill_stage,
    resolve_data_path,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate guitar rig Notion pages from songs.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run a batch")
    run.add_argument("--config", required=True)
    run.add_argument("--input", required=True)
    run.add_argument("--provider", choices=["mock", "ollama", "openai", "claude"])
    run.add_argument("--model")
    run.add_argument("--limit", type=int)
    run.add_argument(
        "--render-only", action="store_true", help="Skip LLM and read rigs JSONL from --input"
    )
    recommend = sub.add_parser("recommend", help="Generate one rig recommendation")
    recommend.add_argument("--config", required=True)
    recommend.add_argument("--song", required=True)
    recommend.add_argument("--artist", required=True)
    recommend.add_argument("--album", default="")
    recommend.add_argument("--year")
    recommend.add_argument("--equipment", default="Valeton GP-180")
    recommend.add_argument("--guitar", default="Default electric guitar")
    recommend.add_argument("--output", default="FRFR / headphones")
    recommend.add_argument("--provider", choices=["mock", "ollama", "openai", "claude"])
    recommend.add_argument("--model")
    recommend.add_argument("--write-notion", action="store_true")
    prompt = sub.add_parser("prompt", help="Print or save the exact LLM prompt for one rig request")
    prompt.add_argument("--config", required=True)
    prompt.add_argument("--song", required=True)
    prompt.add_argument("--artist", required=True)
    prompt.add_argument("--album", default="")
    prompt.add_argument("--year")
    prompt.add_argument("--equipment", default="Valeton GP-180")
    prompt.add_argument("--guitar", default="Default electric guitar")
    prompt.add_argument("--output-system", default="FRFR / headphones")
    prompt.add_argument("--output")
    prompt_stage = sub.add_parser("prompt-stage", help="Print or save one staged LLM prompt")
    prompt_stage.add_argument("--config", required=True)
    prompt_stage.add_argument(
        "--stage", required=True, choices=["general", "gp180", "improvements"]
    )
    prompt_stage.add_argument("--song", required=True)
    prompt_stage.add_argument("--artist", required=True)
    prompt_stage.add_argument("--album", default="")
    prompt_stage.add_argument("--year")
    prompt_stage.add_argument("--equipment", default="Valeton GP-180")
    prompt_stage.add_argument("--guitar", default="Default electric guitar")
    prompt_stage.add_argument("--output-system", default="FRFR / headphones")
    prompt_stage.add_argument("--general-json", help="JSON output from the general stage")
    prompt_stage.add_argument("--gp180-json", help="JSON output from the GP-180 stage")
    prompt_stage.add_argument("--output")
    assemble = sub.add_parser(
        "assemble-stages", help="Assemble staged JSON outputs into one rig JSON"
    )
    assemble.add_argument("--config", required=True)
    assemble.add_argument("--song", required=True)
    assemble.add_argument("--artist", required=True)
    assemble.add_argument("--album", default="")
    assemble.add_argument("--year")
    assemble.add_argument("--equipment", default="Valeton GP-180")
    assemble.add_argument("--guitar", default="Default electric guitar")
    assemble.add_argument("--output-system", default="FRFR / headphones")
    assemble.add_argument("--general-json", required=True)
    assemble.add_argument("--gp180-json", required=True)
    assemble.add_argument("--improvements-json", required=True)
    assemble.add_argument("--output")
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_batch(args)
    if args.command == "recommend":
        return recommend_rig(args)
    if args.command == "prompt":
        return print_prompt(args)
    if args.command == "prompt-stage":
        return print_stage_prompt(args)
    if args.command == "assemble-stages":
        return assemble_stages(args)
    return 2


def run_batch(args):
    base_dir = os.path.dirname(os.path.abspath(args.config))
    load_project_env(os.getcwd(), base_dir)
    config = load_json(args.config)
    provider = args.provider or config["llm"].get("provider", "mock")
    model = args.model or config["llm"].get("model", "mock-song-v1")
    limit = args.limit if args.limit is not None else config.get("batch", {}).get("limit")
    run_dir = _abs(base_dir, config["paths"].get("run_dir", "sample_run"))
    os.makedirs(run_dir, exist_ok=True)
    _reset_file(os.path.join(run_dir, "notion_payloads.jsonl"))
    _reset_file(os.path.join(run_dir, "rigs.jsonl"))
    skill_prompt = load_skill_prompt(base_dir, config)
    allowed_catalog = load_gp180_allowed_catalog(base_dir, config)
    schema = load_json(resolve_data_path(base_dir, config["paths"]["schema"]))
    notion = NotionClient(config, run_dir)
    rows = _load_rigs(args.input) if args.render_only else _load_songs(args.input)
    count = 0
    for row in rows:
        if limit is not None and count >= limit:
            break
        rig = (
            row
            if args.render_only
            else generate_rig(provider, model, row, skill_prompt, schema, config, allowed_catalog)
        )
        payload = notion_payload(rig, config)
        result = notion.create_song_page(rig, payload)
        _append_jsonl(os.path.join(run_dir, "rigs.jsonl"), rig)
        song = rig.get("song", {})
        print(
            f"{song.get('artist')} - {song.get('title')} -> "
            f"{result.get('id')} {result.get('url', '')}"
        )
        count += 1
    print(f"Done. Processed {count} item(s). Run dir: {run_dir}")
    return 0


def recommend_rig(args):
    base_dir = os.path.dirname(os.path.abspath(args.config))
    load_project_env(os.getcwd(), base_dir)
    config = load_json(args.config)
    provider = args.provider or config["llm"].get("provider", "mock")
    model = args.model or config["llm"].get("model", "mock-song-v1")
    run_dir = _abs(base_dir, config["paths"].get("run_dir", "sample_run"))
    os.makedirs(run_dir, exist_ok=True)
    skill_prompt = load_skill_prompt(base_dir, config)
    allowed_catalog = load_gp180_allowed_catalog(base_dir, config)
    schema = load_json(resolve_data_path(base_dir, config["paths"]["schema"]))
    request = {
        "artist": args.artist,
        "title": args.song,
        "album": args.album,
        "year": args.year,
        "equipment": args.equipment,
        "guitar": args.guitar,
        "output": args.output,
        "mode": "best_match",
    }
    rig = generate_rig(provider, model, request, skill_prompt, schema, config, allowed_catalog)
    _append_jsonl(os.path.join(run_dir, "rigs.jsonl"), rig)
    if args.write_notion:
        notion = NotionClient(config, run_dir)
        payload = notion_payload(rig, config)
        result = notion.create_song_page(rig, payload)
        print(f"Notion result: {result.get('id')} {result.get('url', '')}")
    print(json.dumps(rig, ensure_ascii=False, indent=2))
    return 0


def print_prompt(args):
    base_dir = os.path.dirname(os.path.abspath(args.config))
    load_project_env(os.getcwd(), base_dir)
    config = load_json(args.config)
    skill_prompt = load_skill_prompt(base_dir, config)
    allowed_catalog = load_gp180_allowed_catalog(base_dir, config)
    schema = load_json(resolve_data_path(base_dir, config["paths"]["schema"]))
    request = {
        "artist": args.artist,
        "title": args.song,
        "album": args.album,
        "year": args.year,
        "equipment": args.equipment,
        "guitar": args.guitar,
        "output": args.output_system,
        "mode": "best_match",
    }
    prompt_text = build_prompt(request, skill_prompt, schema, allowed_catalog)
    if args.output:
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(prompt_text)
            f.write("\n")
        print(args.output)
    else:
        print(prompt_text)
    return 0


def print_stage_prompt(args):
    base_dir = os.path.dirname(os.path.abspath(args.config))
    load_project_env(os.getcwd(), base_dir)
    config = load_json(args.config)
    request = _request_from_args(args)
    stage_id = {
        "general": "general_rig",
        "gp180": "gp180_translation",
        "improvements": "nam_ir_replacement",
    }[args.stage]
    reference = (
        gp180_stage_brief()
        if args.stage == "gp180"
        else load_skill_stage(base_dir, config, stage_id)
    )
    previous = {}
    if args.stage in ("gp180", "improvements"):
        if not args.general_json:
            raise SystemExit("--general-json is required for gp180 and improvements stages")
        previous["general_result"] = load_json(args.general_json)
    if args.stage == "improvements":
        if not args.gp180_json:
            raise SystemExit("--gp180-json is required for improvements stage")
        previous["gp180_result"] = load_json(args.gp180_json)
    allowed_catalog = load_gp180_allowed_catalog(base_dir, config) if args.stage == "gp180" else ""
    prompt_text = build_stage_prompt(args.stage, request, reference, previous, allowed_catalog)
    _write_or_print(prompt_text, args.output)
    return 0


def assemble_stages(args):
    base_dir = os.path.dirname(os.path.abspath(args.config))
    load_project_env(os.getcwd(), base_dir)
    request = _request_from_args(args)
    general_result = load_json(args.general_json)
    gp180_result = load_json(args.gp180_json)
    improvements_result = load_json(args.improvements_json)
    general = general_result.get("general", general_result)
    gp180 = gp180_result.get("gp180", gp180_result)
    improvements = improvements_result.get("improvements", improvements_result)
    confidence = _lowest_confidence(
        [
            general_result.get("confidence", "unknown"),
            gp180_result.get("confidence", "unknown"),
            improvements_result.get("confidence", "unknown"),
        ]
    )
    rig = {
        "rigName": f"{request['artist']} - {request['title']} - "
        f"{gp180.get('equipment', {}).get('model', request['equipment'])}",
        "song": {
            "artist": request["artist"],
            "title": request["title"],
            "album": request.get("album", ""),
            "year": _safe_int(request.get("year")),
        },
        "equipment": gp180.get("equipment", {"model": request["equipment"]}),
        "guitar": gp180.get("guitar", request["guitar"]),
        "output": gp180.get("output", request["output"]),
        "toneProfile": general.get("toneProfile", general.get("targetSound", "")),
        "status": "draft",
        "confidence": confidence,
        "signalChainSummary": gp180.get("bestMatchSummary", general.get("idealSignalChain", "")),
        "blocks": gp180.get("blocks", []),
        "general": general,
        "gp180": gp180,
        "improvements": improvements,
        "assumptions": general_result.get("assumptions", []),
        "warnings": gp180_result.get("warnings", []) + improvements_result.get("warnings", []),
        "sources": general_result.get("sources", []),
        "createdFrom": "generated",
        "needsReview": any(
            [
                general_result.get("needsReview", True),
                gp180_result.get("needsReview", True),
                improvements_result.get("needsReview", True),
            ]
        ),
    }
    _write_or_print(json.dumps(rig, ensure_ascii=False, indent=2), args.output)
    return 0


def _request_from_args(args):
    return {
        "artist": args.artist,
        "title": args.song,
        "album": args.album,
        "year": args.year,
        "equipment": args.equipment,
        "guitar": args.guitar,
        "output": args.output_system,
        "mode": "best_match",
    }


def _write_or_print(text, output):
    if output:
        output_dir = os.path.dirname(output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")
        print(output)
    else:
        print(text)


def _load_songs(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = _detect_delimiter(path, sample)
        for row in csv.DictReader(f, delimiter=delimiter):
            if row.get("status", "").lower() in ("done", "generated", "published") and row.get(
                "skip_existing"
            ):
                continue
            yield {key: _clean(value) for key, value in row.items()}


def _load_rigs(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _append_jsonl(path, item):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _reset_file(path):
    if os.path.exists(path):
        os.remove(path)


def _abs(base_dir, path):
    return path if os.path.isabs(path) else os.path.join(base_dir, path)


def _clean(value):
    if value is None:
        return ""
    return value.strip()


def _detect_delimiter(path, sample):
    if path.lower().endswith(".tsv"):
        return "\t"
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except csv.Error:
        return ","


def _lowest_confidence(values):
    order = {"unknown": 0, "low": 1, "medium": 2, "medium/high": 3, "high": 4}
    normalized = [str(value).lower() for value in values if value]
    if not normalized:
        return "unknown"
    return min(normalized, key=lambda value: order.get(value, 0))


def _safe_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
