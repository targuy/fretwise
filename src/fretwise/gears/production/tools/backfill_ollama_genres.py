import argparse
import json
import time
from pathlib import Path

from fretwise.gears.production.env import load_project_env
from fretwise.gears.production.fretwise_export import attach_fretwise_export
from fretwise.gears.production.llm import request_json_with_usage
from fretwise.gears.production.paths import default_config_path, default_production_root
from fretwise.gears.production.schema import load_json
from fretwise.gears.production.tools.run_economic_production_batch import (
    GENRE_SCHEMA,
    OLLAMA_PROVIDER,
    genre_classification_prompt,
    genre_semantic_errors,
    normalize_genre_result,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Backfill Fretwise genres using a final Ollama classification pass."
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Pipeline config JSON (default: packaged config.example.json).",
    )
    parser.add_argument(
        "--input-dir",
        default=str(default_production_root() / "Songs"),
        help="Verbose batch output dir (default: <repo>/exports/gears_production/Songs).",
    )
    parser.add_argument("--pattern", default="*.json")
    parser.add_argument("--ollama-model", default="gemma4:latest")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--progress-every", type=int, default=10)
    args = parser.parse_args(argv)

    base_dir = Path.cwd()
    load_project_env(base_dir, (base_dir / args.config).parent)
    config = load_json(str(base_dir / args.config))
    config.setdefault("llm", {})["temperature"] = 0.0

    paths = sorted(Path(args.input_dir).glob(args.pattern))
    counts = {"seen": 0, "classified": 0, "skipped": 0, "failed": 0}
    failures = []
    started = time.perf_counter()

    for index, path in enumerate(paths, start=1):
        counts["seen"] += 1
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            existing_genre = (record.get("song") or {}).get("genre") or ""
            if existing_genre and not args.overwrite:
                counts["skipped"] += 1
                continue

            classification, timing = classify_record(record, config, args)
            errors = genre_semantic_errors(classification)
            if errors:
                raise ValueError("; ".join(errors))

            update_record(record, classification, timing, args.ollama_model)
            counts["classified"] += 1
            if not args.dry_run:
                path.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )

            if args.progress_every and (index % args.progress_every == 0 or index == len(paths)):
                elapsed = time.perf_counter() - started
                rate = counts["classified"] / elapsed * 3600 if elapsed else 0
                print(
                    f"Progress {index}/{len(paths)} | classified={counts['classified']} "
                    f"skipped={counts['skipped']} failed={counts['failed']} | rate={rate:.1f}/h",
                    flush=True,
                )
        except Exception as exc:
            counts["failed"] += 1
            failures.append({"path": str(path), "error": str(exc)})
            print(f"FAILED {path.name}: {exc}", flush=True)

    print(json.dumps({"counts": counts, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def classify_record(record, config, args):
    request = dict(record.get("song") or {})
    final_verdict = (
        record.get("finalVerdict") or record.get("fretwiseExport", {}).get("musicalVerdict") or {}
    )
    rig = (
        record.get("generated", {}).get("Ollama", {}).get("rig")
        or record.get("fretwiseExport", {}).get("rig")
        or {}
    )
    prompt = genre_classification_prompt(request, final_verdict, rig)
    failures = []
    for attempt in range(1, args.max_retries + 2):
        started = time.perf_counter()
        try:
            result, raw, usage = request_json_with_usage(
                OLLAMA_PROVIDER,
                retry_prompt(prompt, attempt, failures[-1]["error"] if failures else ""),
                args.ollama_model,
                config,
                output_schema=GENRE_SCHEMA,
                schema_name="backfill_ollama_genre",
                ollama_options={"num_ctx": args.num_ctx},
            )
            result = normalize_genre_result(result)
            errors = genre_semantic_errors(result)
            if errors:
                raise ValueError("; ".join(errors))
            timing = {
                "stage": "ollama_genre_classification",
                "provider": OLLAMA_PROVIDER,
                "model": args.ollama_model,
                "seconds": round(time.perf_counter() - started, 3),
                "prompt_chars": len(prompt),
                "response_chars": len(raw),
                "usage": usage,
                "attempts": attempt,
                "retryFailures": failures,
            }
            return result, timing
        except Exception as exc:
            failures.append({"attempt": attempt, "error": str(exc)})
            if attempt > args.max_retries:
                raise
            time.sleep(min(2 * attempt, 6))


def update_record(record, classification, timing, model):
    record["genreClassification"] = classification
    record.setdefault("song", {})["genre"] = classification["genre"]
    rig = record.get("generated", {}).get("Ollama", {}).get("rig")
    if isinstance(rig, dict):
        rig.setdefault("song", {})["genre"] = classification["genre"]
    record.setdefault("metadata", {}).setdefault("models", {})["genreClassifier"] = model
    timings = record.setdefault("timings", [])
    timings[:] = [item for item in timings if item.get("stage") != "ollama_genre_classification"]
    timings.append(timing)
    updated = attach_fretwise_export(record)
    record.clear()
    record.update(updated)


def retry_prompt(prompt, attempt, last_error=""):
    if attempt == 1:
        return prompt
    return (
        prompt
        + "\n\n# RETRY INSTRUCTION\n"
        + f"Previous failure: {last_error}\n"
        + "Return one valid JSON object only."
    )


if __name__ == "__main__":
    raise SystemExit(main())
