# ruff: noqa: E501 — long lines are verbatim LLM prompt/skill strings ported from SongsGears.
import argparse
import copy
import json
import queue
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from fretwise.gears.production.env import load_project_env
from fretwise.gears.production.fretwise_export import attach_fretwise_export
from fretwise.gears.production.llm import request_claude_cached_json, request_json_with_usage
from fretwise.gears.production.models import normalize_rig
from fretwise.gears.production.paths import default_config_path, default_production_root
from fretwise.gears.production.schema import load_json, validate_rig
from fretwise.gears.production.tools.run_hybrid_music_arbitration import (
    CLAUDE_PROVIDER,
    CLAUDE_SONNET_RATES_PER_MTOK,
    COMPACT_GP180_CATALOG,
    GP180_SCHEMA,
    IMPROVEMENTS_SCHEMA,
    MUSIC_SCHEMA,
    OLLAMA_PROVIDER,
    confidence_to_schema,
    estimate_claude_sonnet_cost,
    estimate_openai_cost,
    general_from_claude_verdict,
    music_prompt,
    safe_int,
)
from fretwise.gears.production.tools.run_ollama_staged_preview import (
    assemble_rig,
    load_songs,
    request_from_row,
    song_output_filename,
    write_json,
)

OPENAI_PROVIDER = "openai"


VERDICT_SCHEMA = {
    "type": "object",
    "required": [
        "targetTone",
        "mustHave",
        "avoid",
        "gearClues",
        "corrections",
        "confidence",
        "needsManualReview",
    ],
    "properties": {
        "targetTone": {"type": "string"},
        "mustHave": {"type": "array", "items": {"type": "string"}},
        "avoid": {"type": "array", "items": {"type": "string"}},
        "gearClues": {"type": "array", "items": {"type": "string"}},
        "corrections": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "needsManualReview": {"type": "boolean"},
    },
}


OPENAI_JUDGE_SCHEMA = {
    "type": "object",
    "required": ["action", "finalVerdict", "escalationReasons"],
    "properties": {
        "action": {"type": "string", "enum": ["accept", "repair", "escalate"]},
        "finalVerdict": VERDICT_SCHEMA,
        "escalationReasons": {"type": "array", "items": {"type": "string"}},
    },
}


GENRE_SCHEMA = {
    "type": "object",
    "required": ["genre", "subgenres", "confidence", "rationale"],
    "properties": {
        "genre": {"type": "string"},
        "subgenres": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "rationale": {"type": "string"},
    },
}


OPENAI_JUDGE_SYSTEM = """# ROLE
You are an economical musical quality gate for guitar-rig generation.
Your task is to review one compact Ollama musical draft before a GP-180 preset is generated.

# DECISION
Return action:
- accept: Ollama captured the decisive recorded guitar signature.
- repair: Ollama is broadly usable but needs concise musical corrections.
- escalate: a stronger paid arbiter is worth the cost.

# ESCALATE WHEN
- famous or iconic recording and the draft is generic;
- fuzz/wah/chorus/delay/reverb/sitar-like/studio texture is likely decisive and omitted;
- the draft confuses acoustic/electric/bass/keyboard/sitar context;
- confidence is low, disputed, or title metadata is ambiguous;
- the GP-180 generator would likely build the wrong amp/effect family.

# DO NOT ESCALATE WHEN
- only minor wording differs;
- the draft is missing non-essential gear trivia;
- a concise repair can safely fix the target.

# MUSICAL RUBRIC
- The recorded guitar texture outranks live rig myths.
- Signature effect outranks broad artist style.
- "Classic rock crunch" is not enough for fuzz, slapback, chorus, wah, octave, or sitar-like parts.
- Fuzz is not overdrive: nasal/gated/buzzy/woolly/sustaining clues matter.
- Amp family matters: Vox chime, Fender clean/scoop, Marshall/Plexi upper mids, Hiwatt authority, Mesa saturation, JC clean.
- Cabinet scale matters: 1x12, 2x12, 4x12, and speaker family change the result.
- Production era matters: 50s slapback, 60s garage/psychedelic, 70s dry rock, 80s rack sheen, 90s grunge/alt.
- Choose the iconic recorded guitar part when the song is known for one part.
- Keep arrays to at most 5 short items.
- Keep every string short. No prose paragraphs.

# OUTPUT
Return JSON only.
finalVerdict is the corrected musical target used by the later GP-180 generator.

# CACHEABLE QUALITY CALIBRATION
The next rules are intentionally stable across the whole batch.
- A useful targetTone is an audible guitar texture, not a key, mood, artist name, or genre label.
- "E minor", "rock tone", "lead tone", "clean guitar", "distorted guitar", and similar thin labels are invalid targets.
- A valid targetTone should normally name gain family plus texture or production clue.
- Examples of valid targets: dry Marshall crunch with bright upper mids; nasal gated fuzz into small combo; compressed chorus clean with 80s rack sheen; jangly edge-of-breakup Vox rhythm; warm soul clean with short room.
- The mustHave list must contain the decisive audible elements, not generic equipment trivia.
- The gearClues list should include likely guitar/pickup/amp/cab/effect families when they matter.
- If the song entry says bass-only, piano-only, acoustic-only, karaoke, stems, isolated bass, or non-guitar, escalate.
- If the draft describes the wrong instrument, escalate.
- If the title is iconic and the draft misses the iconic texture, escalate.
- If the draft would lead GP-180 toward the wrong gain family, escalate.
- If you can fix a mediocre draft with a precise short verdict, repair.
- If you are uncertain whether guitar is present or what part should be imitated, escalate.
- If a track has a signature effect, the verdict must name it.
- If the original sound is intentionally dry, do not invent ambient effects.
- If the original sound is polished 80s/rack/stereo, do not reduce it to generic crunch.
- If the original sound is 60s/70s raw mono/close mic, do not over-modernize it.
- If the song is a ballad with piano-dominant arrangement, escalate unless there is a clear guitar part.
- Keep the output short because every token is paid and downstream generators only need control signals.
- The economical policy is not "avoid Claude"; it is "pay Claude only when it protects quality".
"""


CLAUDE_FALLBACK_SYSTEM = """You are a high-precision musical fallback arbiter for guitar-rig generation.

Your only job is to correct the musical target before any device-specific preset is generated.
Do not write a GP-180 preset. Do not write amp settings. Do not propose NAM or IR assets.
You receive one compact Ollama draft plus the OpenAI quality-gate result.

Decision policy:
- Prefer the most song-specific sonic signature, not the most generic artist style.
- For famous recordings, prioritize the recorded guitar texture over live versions or later gear myths.
- Identify non-negotiable tone elements: gain family, pickup/guitar clues, amp family, cabinet size, fuzz/drive/wah/modulation/delay/reverb, EQ shape, production era.
- Penalize generic answers such as "classic rock crunch" when the track has a distinctive fuzz, chorus, slapback, octave, sitar-like, clean-compressed, or studio-specific character.
- Correct hallucinated gear only if it materially changes the target sound.
- Mark needsManualReview true for uncertain studio instrumentation, disputed guitar player, or non-guitar signature tones.

Output discipline:
- Return JSON only.
- Keep every string short.
- Use at most 5 items per array.
- Each array item should be under 12 words.
- confidence is one of: high, medium, low.

Required JSON shape:
{
  "targetTone": "short phrase",
  "mustHave": ["short"],
  "avoid": ["short"],
  "gearClues": ["short"],
  "corrections": ["short"],
  "confidence": "high|medium|low",
  "needsManualReview": false
}

Compact sonic checklist:
- Era matters: 1950s rockabilly, 1960s garage, 1960s psychedelic, 1970s classic rock, 1980s chorus clean, 1990s high gain, modern metal, funk, reggae, disco, punk, shoegaze, grunge, indie, country, blues, soul, pop.
- Gain family matters: pristine clean, compressed clean, edge-of-breakup, low-gain overdrive, crunchy rhythm, fuzz, distortion, saturated lead, modern high gain.
- Fuzz is not generic overdrive. Fuzz Face is round and woolly; Tone Bender and Maestro-style fuzz can be nasal, buzzy, gated, and sitar-like; Big Muff is smoother and sustaining.
- Amp family matters: Vox/AC chime and upper-mid jangle, Fender clean headroom and scoop, Marshall/Plexi upper-mid crunch, Hiwatt clean authority, Mesa/Rectifier modern saturation, JC-style transistor clean, small combo boxiness.
- Cabinet size matters: 1x12 and 2x12 are focused and vintage; 4x12 is larger, punchier, and more rock-stack oriented; speaker family shifts the midrange.
- Effects matter only when audible: wah, phaser, flanger, chorus, tremolo, octave, slapback, tape delay, dotted-eighth delay, spring, plate, room.
- Production matters: close-mic dry studio, room ambience, double tracking, mono vintage, stereo chorus, bright 80s rack, dark lo-fi, compressed radio mix.
- If the song has a signature riff texture, that texture outranks broad band identity.
- Prefer audible evidence over forum-style gear trivia when the two conflict.
- Be terse: this fallback feeds another generator, so short constraints are more valuable than explanation.
"""


ALLOWED_GP180_MODELS = {
    "None",
    "Gate 1",
    "Gate 2",
    "Gate 3",
    "Comp",
    "Boost",
    "OD 9",
    "Green OD",
    "Blues OD",
    "V-Wah",
    "C-Wah",
    "B-Wah",
    "T-Wah",
    "Red Haze",
    "Distortion",
    "Fuzz",
    "Chief",
    "RAT-style",
    "Muff-style",
    "UK 45",
    "UK 50",
    "UK SLP",
    "UK 800",
    "US Deluxe",
    "Silver Twin",
    "Foxy 30TB",
    "AC30 TB",
    "Bellman 59N",
    "Recti",
    "EV 51",
    "UK Vintage 4x12",
    "UK Basket 4x12",
    "UK 30 4x12",
    "Foxy 2x12",
    "US 2x12",
    "Bellman 4x10",
    "Mess 4x12",
    "User IR 1",
    "Guitar EQ 1",
    "Guitar EQ 2",
    "Chorus",
    "O-Phase",
    "Tremolo",
    "Slapback",
    "Digital Delay",
    "Tape",
    "Room",
    "Spring",
    "Plate",
    "Volume",
}


GP180_MODEL_ALIASES = {
    "Wah": "V-Wah",
    "Auto Wah": "T-Wah",
    "Auto-wah": "T-Wah",
    "Touch Wah": "T-Wah",
    "Flanger": "Chorus",
    "Phaser": "O-Phase",
    "Analog Delay": "Tape",
    "Delay": "Digital Delay",
    "Reverb": "Room",
}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Economical production workflow: Ollama draft, OpenAI cached judge, Claude fallback only if needed, Ollama final."
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Pipeline config JSON (default: packaged config.example.json).",
    )
    parser.add_argument("--input", default="songs.tsv")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from output-root/checkpoint.json nextOffset when available.",
    )
    parser.add_argument(
        "--limit", default="100", help="Number of Songs JSON files to produce, or Remaining/All."
    )
    parser.add_argument(
        "--output-root",
        default=str(default_production_root()),
        help="Batch output root holding Songs/, Logs/, summary.json and checkpoint.json "
        "(default: <repo>/exports/gears_production, env FRETWISE_GEARS_PRODUCTION_ROOT).",
    )
    parser.add_argument("--ollama-model", default="gemma4:latest")
    parser.add_argument("--openai-model", default="gpt-5.4-mini")
    parser.add_argument("--claude-model", default="claude-sonnet-4-5")
    parser.add_argument("--num-ctx", type=int, default=65536)
    parser.add_argument("--openai-prompt-cache-key", default="songsgear-production-judge-v1")
    parser.add_argument("--openai-prompt-cache-retention", default="24h")
    parser.add_argument("--openai-text-verbosity", default="low")
    parser.add_argument("--openai-reasoning-effort", default="")
    parser.add_argument("--claude-max-tokens", type=int, default=700)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--progress-every", type=int, default=5)
    parser.add_argument(
        "--jobs", type=int, default=1, help="Number of Songs JSON files to process concurrently."
    )
    parser.add_argument(
        "--ollama-urls",
        default="",
        help=(
            "Comma-separated Ollama URL pool. Entries may use =slots and @ctx, "
            "e.g. http://127.0.0.1:11434=6@65536,http://127.0.0.1:11435=2@32768."
        ),
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Show a live console monitor with worker progress and ETA.",
    )
    parser.add_argument(
        "--monitor-every", type=float, default=2.0, help="Seconds between live monitor refreshes."
    )
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args(argv)

    base_dir = Path.cwd()
    load_project_env(base_dir, (base_dir / args.config).parent)
    config = load_json(str(base_dir / args.config))
    config.setdefault("llm", {})["temperature"] = 0.0

    output_root = base_dir / args.output_root
    if args.resume:
        args.offset = resume_offset(output_root, args.offset)
        print(f"Resume offset: {args.offset}", flush=True)
    rows = [
        row
        for row in load_songs(base_dir / args.input)
        if row.get("artist") and (row.get("title") or row.get("song"))
    ]
    args.limit_spec = str(args.limit).strip()
    args.limit = resolve_quantity_limit(args.limit_spec, args.offset, len(rows))
    if args.limit_spec.lower() in {"remaining", "all"}:
        print(f"Quantity {args.limit_spec} resolved to limit: {args.limit}", flush=True)
    ollama_workers = parse_ollama_worker_pool(
        args.ollama_urls,
        config["llm"].get("ollama_url", "http://localhost:11434/api/generate"),
        args.jobs,
        args.num_ctx,
    )
    args.jobs = len(ollama_workers)
    args.ollama_worker_urls = [worker.url for worker in ollama_workers]
    args.ollama_worker_specs = [worker.label for worker in ollama_workers]
    if args.jobs > 1:
        print(f"Parallel jobs: {args.jobs}", flush=True)
        print(
            "Ollama worker pool: " + ", ".join(summarize_worker_specs(ollama_workers)), flush=True
        )

    songs_dir = output_root / "Songs"
    logs_dir = output_root / "Logs"
    songs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    progress_path = logs_dir / f"progress_offset_{args.offset}_limit_{args.limit}.jsonl"
    run_log_path = logs_dir / f"run_offset_{args.offset}_limit_{args.limit}.log"

    selected = rows[args.offset : args.offset + args.limit]
    summary = new_summary(args, len(rows), output_root)
    started = time.perf_counter()

    log(
        run_log_path,
        f"START offset={args.offset} limit={args.limit} selected={len(selected)} output={output_root}",
    )
    handled_source_indices = set()
    checkpoint_source_index = args.offset
    completed_results = 0
    for result in run_song_tasks(
        selected, args, config, songs_dir, ollama_workers, len(rows), started
    ):
        completed_results += 1
        source_index = result["sourceIndex"]
        batch_index = result["batchIndex"]
        request = result["request"]
        output_path = result["outputPath"]
        summary["counts"]["songsAttempted"] += 1
        if result["status"] != "error":
            handled_source_indices.add(source_index)
            while checkpoint_source_index + 1 in handled_source_indices:
                checkpoint_source_index += 1

        if result["status"] == "error":
            summary["errors"].append(
                {"sourceIndex": source_index, "song": request, "error": result["error"]}
            )
            log_json(
                progress_path,
                {
                    "status": "error",
                    "sourceIndex": source_index,
                    "song": request,
                    "error": result["error"],
                    "ts": time.time(),
                },
            )
            log(
                run_log_path,
                f"ERROR source={source_index} label={result['label']}: {result['error']}",
            )
            print(f"ERROR source {source_index}: {result['error']}", flush=True)
            if args.stop_on_error:
                raise RuntimeError(result["error"])
        else:
            record = result["record"]
            skipped = result["status"] == "skipped"
            update_summary(summary, record, skipped=skipped)
            log_json(
                progress_path,
                progress_entry(
                    result["status"],
                    source_index,
                    batch_index,
                    len(selected),
                    request,
                    record,
                    output_path,
                ),
            )
            print(result["message"], flush=True)

        if args.progress_every and (
            completed_results % args.progress_every == 0 or completed_results == len(selected)
        ):
            finalize_summary(summary, started)
            write_json(output_root / "summary.json", summary)
            write_json(
                output_root / "checkpoint.json",
                checkpoint(args, checkpoint_source_index, len(rows), summary),
            )
            print(format_progress(summary), flush=True)
            log(run_log_path, format_progress(summary))

    finalize_summary(summary, started)
    write_json(output_root / "summary.json", summary)
    write_json(
        output_root / "checkpoint.json",
        checkpoint(args, checkpoint_source_index, len(rows), summary),
    )
    log(run_log_path, "DONE " + format_progress(summary))
    print(f"\nDone. Output dir: {output_root}", flush=True)
    print(format_progress(summary), flush=True)
    return 0


def resume_offset(output_root, fallback_offset):
    checkpoint_path = Path(output_root) / "checkpoint.json"
    if not checkpoint_path.exists():
        return fallback_offset
    try:
        checkpoint_data = load_json(str(checkpoint_path))
    except Exception:
        return fallback_offset
    next_offset = checkpoint_data.get("nextOffset")
    if isinstance(next_offset, int) and next_offset >= 0:
        return next_offset
    return fallback_offset


@dataclass
class OllamaWorkerSpec:
    url: str
    num_ctx: int
    endpoint_key: str
    label: str


@dataclass
class WorkerState:
    worker_id: int
    endpoint_key: str
    url: str
    num_ctx: int
    status: str = "idle"
    current: str = ""
    source_index: int | None = None
    started_at: float | None = None
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    total_seconds: float = 0.0
    last_seconds: float = 0.0
    last_status: str = ""
    last_message: str = ""

    def average_seconds(self):
        done = self.completed + self.failed + self.skipped
        return self.total_seconds / done if done else 0.0


@dataclass
class MonitorState:
    total: int
    offset: int
    total_rows: int
    started_at: float
    lock: threading.Lock = field(default_factory=threading.Lock)
    workers: dict[int, WorkerState] = field(default_factory=dict)
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    checkpoint_source_index: int = 0
    stop_requested: bool = False

    def snapshot(self):
        with self.lock:
            workers = [
                copy.copy(worker)
                for worker in sorted(self.workers.values(), key=lambda item: item.worker_id)
            ]
            return {
                "total": self.total,
                "offset": self.offset,
                "totalRows": self.total_rows,
                "startedAt": self.started_at,
                "completed": self.completed,
                "failed": self.failed,
                "skipped": self.skipped,
                "checkpointSourceIndex": self.checkpoint_source_index,
                "workers": workers,
            }


def parse_ollama_worker_pool(value, default_url, jobs, default_num_ctx):
    if jobs < 1:
        raise ValueError("--jobs must be 1 or greater.")
    spec = str(value or "").strip()
    default_url = normalize_ollama_generate_url(default_url)
    if not spec:
        return [
            OllamaWorkerSpec(
                url=default_url,
                num_ctx=default_num_ctx,
                endpoint_key=endpoint_key(default_url),
                label=f"{endpoint_key(default_url)}@{default_num_ctx}",
            )
            for _ in range(jobs)
        ]

    weighted = []
    unweighted = []
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            continue
        url_part, slots, num_ctx = parse_worker_pool_part(part, default_num_ctx)
        worker_url = normalize_ollama_generate_url(url_part)
        worker = OllamaWorkerSpec(
            url=worker_url,
            num_ctx=num_ctx,
            endpoint_key=endpoint_key(worker_url),
            label=f"{endpoint_key(worker_url)}@{num_ctx}",
        )
        if slots is not None:
            if slots < 1:
                raise ValueError("Ollama URL slots must be 1 or greater.")
            weighted.extend(copy.copy(worker) for _ in range(slots))
        else:
            unweighted.append(worker)

    if weighted and unweighted:
        weighted.extend(unweighted)
        return weighted
    if weighted:
        return weighted
    if not unweighted:
        return [default_url] * jobs

    return [copy.copy(unweighted[index % len(unweighted)]) for index in range(jobs)]


def parse_ollama_worker_urls(value, default_url, jobs):
    return [worker.url for worker in parse_ollama_worker_pool(value, default_url, jobs, 65536)]


def parse_worker_pool_part(part, default_num_ctx):
    slots = None
    num_ctx = default_num_ctx
    base = part

    if "@" in base:
        before_ctx, after_ctx = base.rsplit("@", 1)
        if after_ctx.strip().isdigit():
            base = before_ctx
            num_ctx = int(after_ctx.strip())

    url, separator, slots_text = base.rpartition("=")
    if separator and slots_text.strip().isdigit():
        slots = int(slots_text.strip())
        base = url.strip()

    if not base:
        raise ValueError(f"Invalid Ollama worker pool entry: {part}")
    return base, slots, num_ctx


def normalize_ollama_generate_url(value):
    url = str(value or "").strip()
    if not url:
        return "http://localhost:11434/api/generate"
    url = url.rstrip("/")
    if url.endswith("/api/generate"):
        return url
    if url.endswith("/api"):
        return url + "/generate"
    return url + "/api/generate"


def summarize_worker_urls(urls):
    counts = {}
    for url in urls:
        counts[url] = counts.get(url, 0) + 1
    return [f"{url} x{count}" for url, count in counts.items()]


def summarize_worker_specs(workers):
    counts = {}
    for worker in workers:
        counts[worker.label] = counts.get(worker.label, 0) + 1
    return [f"{label} x{count}" for label, count in counts.items()]


def endpoint_key(url):
    match = re.match(r"^https?://([^/]+)/?", str(url))
    return match.group(1) if match else str(url)


def resolve_quantity_limit(value, offset, total_rows):
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("--limit must be a number, Remaining, or All.")

    keyword = normalized.lower()
    if keyword in {"remaining", "all"}:
        return max(total_rows - offset, 0)

    try:
        limit = int(normalized)
    except ValueError as exc:
        raise ValueError("--limit must be a number, Remaining, or All.") from exc
    if limit < 0:
        raise ValueError("--limit must be zero or greater.")
    return limit


def run_song_tasks(selected, args, config, songs_dir, ollama_workers, total_rows, started):
    if not selected:
        return

    task_queue = queue.Queue()
    result_queue = queue.Queue()
    monitor_state = MonitorState(
        total=len(selected),
        offset=args.offset,
        total_rows=total_rows,
        started_at=started,
        checkpoint_source_index=args.offset,
    )
    for batch_index, row in enumerate(selected, start=1):
        request = request_from_row(row)
        source_index = args.offset + batch_index
        output_path = songs_dir / song_output_filename(
            {"artist": request["artist"], "title": request["title"]}
        )
        task_queue.put(
            {
                "batchIndex": batch_index,
                "sourceIndex": source_index,
                "request": request,
                "outputPath": output_path,
                "selectedTotal": len(selected),
                "totalRows": total_rows,
            }
        )

    worker_count = min(len(ollama_workers), len(selected))
    threads = []
    for index, worker_spec in enumerate(ollama_workers[:worker_count], start=1):
        worker_config = copy.deepcopy(config)
        worker_config.setdefault("llm", {})["ollama_url"] = worker_spec.url
        worker_args = copy.copy(args)
        worker_args.num_ctx = worker_spec.num_ctx
        with monitor_state.lock:
            monitor_state.workers[index] = WorkerState(
                worker_id=index,
                endpoint_key=worker_spec.endpoint_key,
                url=worker_spec.url,
                num_ctx=worker_spec.num_ctx,
            )
        thread = threading.Thread(
            target=song_worker,
            args=(
                index,
                worker_spec,
                task_queue,
                result_queue,
                worker_config,
                worker_args,
                monitor_state,
            ),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    monitor_thread = None
    if args.monitor:
        monitor_thread = threading.Thread(
            target=render_monitor_loop, args=(monitor_state, args.monitor_every), daemon=True
        )
        monitor_thread.start()

    handled_source_indices = set()
    checkpoint_source_index = args.offset
    for _ in range(len(selected)):
        result = result_queue.get()
        source_index = result["sourceIndex"]
        if result["status"] != "error":
            handled_source_indices.add(source_index)
            while checkpoint_source_index + 1 in handled_source_indices:
                checkpoint_source_index += 1
        with monitor_state.lock:
            if result["status"] == "completed":
                monitor_state.completed += 1
            elif result["status"] == "skipped":
                monitor_state.skipped += 1
            elif result["status"] == "error":
                monitor_state.failed += 1
            monitor_state.checkpoint_source_index = checkpoint_source_index
        yield result

    for thread in threads:
        thread.join()
    with monitor_state.lock:
        monitor_state.stop_requested = True
    if monitor_thread:
        monitor_thread.join(timeout=3)
        render_monitor(monitor_state.snapshot(), final=True)


def song_worker(worker_id, worker_spec, task_queue, result_queue, config, args, monitor_state):
    while True:
        try:
            task = task_queue.get_nowait()
        except queue.Empty:
            return
        mark_worker_started(monitor_state, worker_id, task)
        started = time.perf_counter()
        try:
            result = process_song_task(task, worker_id, worker_spec, config, args)
            elapsed = time.perf_counter() - started
            mark_worker_finished(monitor_state, worker_id, result, elapsed)
            result_queue.put(result)
        except Exception as exc:
            request = task["request"]
            elapsed = time.perf_counter() - started
            result = {
                "status": "error",
                "workerId": worker_id,
                "workerUrl": worker_spec.url,
                "workerEndpoint": worker_spec.endpoint_key,
                "workerNumCtx": worker_spec.num_ctx,
                "batchIndex": task["batchIndex"],
                "sourceIndex": task["sourceIndex"],
                "request": request,
                "outputPath": task["outputPath"],
                "label": f"{request['artist']} - {request['title']}",
                "error": str(exc),
            }
            mark_worker_finished(monitor_state, worker_id, result, elapsed)
            result_queue.put(result)
        finally:
            task_queue.task_done()


def mark_worker_started(monitor_state, worker_id, task):
    request = task["request"]
    with monitor_state.lock:
        worker = monitor_state.workers[worker_id]
        worker.status = "running"
        worker.current = f"{request['artist']} - {request['title']}"
        worker.source_index = task["sourceIndex"]
        worker.started_at = time.perf_counter()
        worker.last_message = ""


def mark_worker_finished(monitor_state, worker_id, result, elapsed):
    with monitor_state.lock:
        worker = monitor_state.workers[worker_id]
        worker.status = "idle"
        worker.current = ""
        worker.source_index = None
        worker.started_at = None
        worker.last_seconds = elapsed
        worker.total_seconds += elapsed
        worker.last_status = result["status"]
        worker.last_message = result.get("label", "")
        if result["status"] == "completed":
            worker.completed += 1
        elif result["status"] == "skipped":
            worker.skipped += 1
        elif result["status"] == "error":
            worker.failed += 1


def process_song_task(task, worker_id, worker_spec, config, args):
    source_index = task["sourceIndex"]
    batch_index = task["batchIndex"]
    request = task["request"]
    output_path = task["outputPath"]
    label = f"{request['artist']} - {request['title']}"
    print(
        f"\n=== worker {worker_id} | {batch_index}/{task['selectedTotal']} | source {source_index}/{task['totalRows']} | {label} ===",
        flush=True,
    )
    if args.skip_existing and output_path.exists():
        record = load_json(str(output_path))
        metadata = record.setdefault("metadata", {})
        metadata["skippedExisting"] = True
        metadata["workerId"] = worker_id
        metadata["ollamaUrl"] = worker_spec.url
        metadata["workerEndpoint"] = worker_spec.endpoint_key
        metadata["workerNumCtx"] = worker_spec.num_ctx
        return {
            "status": "skipped",
            "workerId": worker_id,
            "workerUrl": worker_spec.url,
            "workerEndpoint": worker_spec.endpoint_key,
            "workerNumCtx": worker_spec.num_ctx,
            "batchIndex": batch_index,
            "sourceIndex": source_index,
            "request": request,
            "outputPath": output_path,
            "record": record,
            "label": label,
            "message": f"Skip existing -> {output_path}",
        }

    record = run_song(request, config, args, source_index, output_path)
    metadata = record.setdefault("metadata", {})
    metadata["workerId"] = worker_id
    metadata["ollamaUrl"] = worker_spec.url
    metadata["workerEndpoint"] = worker_spec.endpoint_key
    metadata["workerNumCtx"] = worker_spec.num_ctx
    write_json(output_path, record)
    return {
        "status": "completed",
        "workerId": worker_id,
        "workerUrl": worker_spec.url,
        "workerEndpoint": worker_spec.endpoint_key,
        "workerNumCtx": worker_spec.num_ctx,
        "batchIndex": batch_index,
        "sourceIndex": source_index,
        "request": request,
        "outputPath": output_path,
        "record": record,
        "label": label,
        "message": format_song_result(record, output_path),
    }


def render_monitor_loop(monitor_state, interval):
    while True:
        render_monitor(monitor_state.snapshot())
        with monitor_state.lock:
            if monitor_state.stop_requested:
                return
        time.sleep(max(interval, 0.5))


def render_monitor(snapshot, final=False):
    elapsed = max(time.perf_counter() - snapshot["startedAt"], 0.001)
    done = snapshot["completed"] + snapshot["failed"] + snapshot["skipped"]
    total = snapshot["total"]
    active = sum(1 for worker in snapshot["workers"] if worker.status == "running")
    rate = done / elapsed * 3600 if done else 0
    remaining = max(total - done, 0)
    eta_seconds = remaining / (done / elapsed) if done else 0
    width = shutil.get_terminal_size((120, 30)).columns

    lines = []
    lines.append("SongsGears production monitor" + (" (final)" if final else ""))
    lines.append(
        f"Batch {done}/{total} | completed={snapshot['completed']} skipped={snapshot['skipped']} "
        f"failed={snapshot['failed']} active={active} | rate={rate:.1f}/h | ETA={format_duration(eta_seconds)}"
    )
    lines.append(
        f"Elapsed={format_duration(elapsed)} | checkpoint source={snapshot['checkpointSourceIndex']} | corpus {snapshot['offset'] + done}/{snapshot['totalRows']}"
    )
    lines.append("-" * min(width, 140))
    lines.append(
        f"{'W':>2} {'endpoint':<21} {'ctx':>6} {'state':<8} {'done':>5} {'avg':>8} {'last':>8} current"
    )
    for worker in snapshot["workers"]:
        current = worker.current or worker.last_message
        if len(current) > max(width - 68, 20):
            current = current[: max(width - 71, 17)] + "..."
        done_worker = worker.completed + worker.failed + worker.skipped
        state = worker.status
        if worker.status == "running" and worker.started_at:
            state = f"run {format_duration(time.perf_counter() - worker.started_at)}"
        lines.append(
            f"{worker.worker_id:>2} {worker.endpoint_key:<21.21} {worker.num_ctx:>6} {state:<8.8} "
            f"{done_worker:>5} {format_duration(worker.average_seconds()):>8} {format_duration(worker.last_seconds):>8} {current}"
        )
    text = "\n".join(lines)
    if sys.stdout.isatty() and not final:
        print("\x1b[2J\x1b[H" + text, flush=True)
    else:
        print(text, flush=True)


def format_duration(seconds):
    if not seconds:
        return "--"
    seconds = max(int(seconds), 0)
    return str(timedelta(seconds=seconds))


def run_song(request, config, args, source_index, output_path):
    timings = []
    validations = []

    ollama_music, timing = timed_json(
        "ollama_music_draft",
        OLLAMA_PROVIDER,
        args.ollama_model,
        music_prompt(request),
        config,
        MUSIC_SCHEMA,
        ollama_options={"num_ctx": args.num_ctx},
        max_retries=args.max_retries,
    )
    timings.append(timing)
    print(f"Ollama draft ({timing['seconds']:.1f}s)", flush=True)

    openai_judge, timing = timed_json(
        "openai_music_judge",
        OPENAI_PROVIDER,
        args.openai_model,
        openai_judge_prompt(request, ollama_music),
        config,
        OPENAI_JUDGE_SCHEMA,
        openai_options=openai_options(args),
        max_retries=args.max_retries,
    )
    timings.append(timing)
    print(
        f"OpenAI judge action={openai_judge.get('action')} ({timing['seconds']:.1f}s)", flush=True
    )

    action = openai_judge.get("action", "escalate")
    final_source = "openai"
    final_verdict = openai_judge.get("finalVerdict", {})
    claude_verdict = None
    forced_quality_issues = verdict_quality_issues(final_verdict, request)
    if forced_quality_issues:
        openai_judge["forcedEscalationReasons"] = forced_quality_issues
    if should_escalate(openai_judge, request):
        claude_started = time.perf_counter()
        user_prompt = claude_fallback_prompt(request, ollama_music, openai_judge)
        claude_verdict, claude_raw, claude_usage = request_claude_cached_json(
            CLAUDE_FALLBACK_SYSTEM,
            user_prompt,
            args.claude_model,
            config,
            max_tokens=args.claude_max_tokens,
        )
        timings.append(
            {
                "stage": "claude_music_fallback",
                "provider": CLAUDE_PROVIDER,
                "model": args.claude_model,
                "seconds": round(time.perf_counter() - claude_started, 3),
                "prompt_chars": len(CLAUDE_FALLBACK_SYSTEM) + len(user_prompt),
                "response_chars": len(claude_raw),
                "usage": claude_usage,
            }
        )
        final_source = "claude"
        final_verdict = claude_verdict
        print(f"Claude fallback ({timings[-1]['seconds']:.1f}s)", flush=True)

    try:
        gp180, timing = timed_json(
            "ollama_gp180",
            OLLAMA_PROVIDER,
            args.ollama_model,
            production_gp180_prompt(request, final_verdict),
            config,
            GP180_SCHEMA,
            ollama_options={"num_ctx": args.num_ctx},
            max_retries=args.max_retries,
            normalizer=lambda result: normalize_gp180_result(result, request),
            validator=gp180_semantic_errors,
        )
    except Exception as exc:
        gp180 = local_gp180_fallback(request, final_verdict, str(exc))
        timing = local_timing("local_gp180_fallback", str(exc))
    timings.append(timing)
    print(f"{timing['stage']} ({timing['seconds']:.1f}s)", flush=True)

    try:
        improvements, timing = timed_json(
            "ollama_improvements",
            OLLAMA_PROVIDER,
            args.ollama_model,
            production_improvements_prompt(request, final_verdict, gp180),
            config,
            IMPROVEMENTS_SCHEMA,
            ollama_options={"num_ctx": args.num_ctx},
            max_retries=args.max_retries,
            normalizer=normalize_improvements_result,
            validator=improvements_semantic_errors,
        )
    except Exception as exc:
        improvements = local_improvements_fallback(str(exc))
        timing = local_timing("local_improvements_fallback", str(exc))
    timings.append(timing)
    print(f"{timing['stage']} ({timing['seconds']:.1f}s)", flush=True)

    general = general_from_verdict(final_verdict, final_source)
    rig = assemble_rig(request, general, gp180, improvements)
    validation = validate_output(rig)
    if not validation.get("ok"):
        reason = "; ".join(validation.get("errors") or ["final validation failed"])
        gp180 = local_gp180_fallback(request, final_verdict, reason)
        fallback_timing = local_timing("local_gp180_fallback", reason)
        timings.append(fallback_timing)
        rig = assemble_rig(request, general, gp180, improvements)
        validation = validate_output(rig)
    validations.append(validation)

    genre_classification, timing = timed_json(
        "ollama_genre_classification",
        OLLAMA_PROVIDER,
        args.ollama_model,
        genre_classification_prompt(request, final_verdict, rig),
        config,
        GENRE_SCHEMA,
        ollama_options={"num_ctx": min(args.num_ctx, 8192)},
        max_retries=args.max_retries,
        normalizer=normalize_genre_result,
        validator=genre_semantic_errors,
    )
    timings.append(timing)
    print(
        f"Ollama genre={genre_classification.get('genre')} ({timing['seconds']:.1f}s)", flush=True
    )

    song = {
        "artist": request["artist"],
        "title": request["title"],
        "album": request.get("album", ""),
        "year": safe_int(request.get("year")),
        "genre": genre_classification.get("genre") or request.get("genre", ""),
    }
    rig.setdefault("song", {}).update(song)

    record = {
        "metadata": {
            "workflow": "economic_production_v1",
            "sourceIndex": source_index,
            "outputPath": str(output_path),
            "models": {
                "ollama": args.ollama_model,
                "openaiJudge": args.openai_model,
                "claudeFallback": args.claude_model,
            },
            "finalVerdictSource": final_source,
            "openaiAction": action,
            "forcedEscalationReasons": forced_quality_issues,
            "usedLocalGp180Fallback": timing_used(
                record_stage="local_gp180_fallback", timings=timings
            ),
            "usedLocalImprovementsFallback": timing_used(
                record_stage="local_improvements_fallback", timings=timings
            ),
        },
        "song": song,
        "genreClassification": genre_classification,
        "musicDraft": {"Ollama": ollama_music},
        "openaiJudge": openai_judge,
        "claudeFallback": claude_verdict,
        "finalVerdict": final_verdict,
        "generated": {"Ollama": {"gp180": gp180, "improvements": improvements, "rig": rig}},
        "validation": validation,
        "timings": timings,
    }
    return attach_fretwise_export(record)


def timed_json(
    stage,
    provider,
    model,
    prompt,
    config,
    schema,
    ollama_options=None,
    openai_options=None,
    max_retries=2,
    normalizer=None,
    validator=None,
):
    started = time.perf_counter()
    failures = []
    for attempt in range(1, max_retries + 2):
        try:
            result, raw, usage = request_json_with_usage(
                provider,
                retry_prompt(prompt, attempt, failures[-1]["error"] if failures else ""),
                model,
                config,
                output_schema=schema,
                schema_name=f"economic_{stage}",
                ollama_options=ollama_options,
                openai_options=openai_options,
            )
            if normalizer:
                result = normalizer(result)
            if validator:
                semantic_errors = validator(result)
                if semantic_errors:
                    raise ValueError("Semantic validation failed: " + "; ".join(semantic_errors))
            return result, {
                "stage": stage,
                "provider": provider,
                "model": model,
                "ollamaUrl": config.get("llm", {}).get("ollama_url")
                if provider == OLLAMA_PROVIDER
                else None,
                "seconds": round(time.perf_counter() - started, 3),
                "prompt_chars": len(prompt),
                "response_chars": len(raw),
                "usage": usage,
                "attempts": attempt,
                "retryFailures": failures,
            }
        except Exception as exc:
            failures.append({"attempt": attempt, "error": str(exc)})
            if attempt > max_retries:
                raise
            time.sleep(min(2 * attempt, 6))


def retry_prompt(prompt, attempt, last_error=""):
    if attempt == 1:
        return prompt
    error_line = f" Previous failure: {last_error}" if last_error else ""
    return (
        prompt
        + "\n\n# RETRY INSTRUCTION\n"
        + "The previous answer was not valid for the required JSON parser/schema or semantic checks."
        + error_line
        + " "
        + "Return one valid JSON object only, with no markdown and no trailing commentary."
    )


def gp180_semantic_errors(result):
    gp180 = result.get("gp180", result) if isinstance(result, dict) else {}
    blocks = gp180.get("blocks")
    errors = []
    if not isinstance(blocks, list) or len(blocks) < 3:
        errors.append("GP-180 result must contain at least 3 blocks")
    if not isinstance(gp180.get("equipment"), dict) or not gp180.get("equipment", {}).get("model"):
        errors.append("GP-180 equipment.model is required")
    invalid_models = []
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            model = str(block.get("model", ""))
            if model and model not in ALLOWED_GP180_MODELS:
                invalid_models.append(model)
    if invalid_models:
        errors.append("Non-catalog GP-180 models: " + ", ".join(sorted(set(invalid_models))))
    return errors


def improvements_semantic_errors(result):
    improvements = result.get("improvements", result) if isinstance(result, dict) else {}
    proposals = improvements.get("proposals")
    if not isinstance(proposals, list):
        return ["improvements.proposals must be a list"]
    return []


def genre_semantic_errors(result):
    errors = []
    genre = str(result.get("genre", "")).strip() if isinstance(result, dict) else ""
    if not genre:
        errors.append("genre is required")
    if genre.lower() in {"unknown", "n/a", "none"}:
        errors.append("genre must be a musical genre, not unknown/none")
    subgenres = result.get("subgenres") if isinstance(result, dict) else None
    if not isinstance(subgenres, list):
        errors.append("subgenres must be a list")
    return errors


def normalize_gp180_result(result, request):
    if not isinstance(result, dict):
        return result
    normalized = dict(result)
    if "gp180" not in normalized:
        gp180_schema_echo = normalized.get("properties", {}).get("gp180", {})
        if isinstance(gp180_schema_echo, dict) and isinstance(
            gp180_schema_echo.get("properties"), dict
        ):
            normalized["gp180"] = gp180_schema_echo["properties"]
    gp180 = normalized.get("gp180")
    if isinstance(gp180, dict):
        equipment = gp180.get("equipment")
        if not isinstance(equipment, dict) or not equipment.get("model") or "type" in equipment:
            gp180["equipment"] = {"model": "Valeton GP-180"}
        if not isinstance(gp180.get("guitar"), str) or not gp180.get("guitar"):
            gp180["guitar"] = request.get("guitar", "Default electric guitar")
        if not isinstance(gp180.get("output"), str) or not gp180.get("output"):
            gp180["output"] = request.get("output", "FRFR / headphones")
        normalize_gp180_block_models(gp180)
        gp180.setdefault(
            "choicePolicy", "Build the closest GP-180 guitar imitation from the musical verdict."
        )
        gp180.setdefault("bestMatchSummary", "GP-180 best match generated from musical verdict.")
    normalized.setdefault("warnings", [])
    normalized.setdefault("confidence", "medium")
    normalized.setdefault("needsReview", True)
    return normalized


def normalize_gp180_block_models(gp180):
    blocks = gp180.get("blocks")
    if not isinstance(blocks, list):
        return
    for block in blocks:
        if not isinstance(block, dict):
            continue
        model = block.get("model")
        if isinstance(model, str):
            block["model"] = GP180_MODEL_ALIASES.get(model, model)


def normalize_genre_result(result):
    if not isinstance(result, dict):
        return result
    normalized = dict(result)
    normalized["genre"] = str(normalized.get("genre") or "").strip().lower()
    subgenres = normalized.get("subgenres")
    if not isinstance(subgenres, list):
        subgenres = []
    normalized["subgenres"] = [
        str(item).strip().lower() for item in subgenres if str(item).strip()
    ][:5]
    confidence = str(normalized.get("confidence") or "medium").strip().lower()
    normalized["confidence"] = confidence if confidence in {"high", "medium", "low"} else "medium"
    normalized["rationale"] = str(normalized.get("rationale") or "").strip()[:240]
    return normalized


def normalize_improvements_result(result):
    if not isinstance(result, dict):
        return result
    normalized = dict(result)
    if "improvements" not in normalized:
        improvements_schema_echo = normalized.get("properties", {}).get("improvements", {})
        if isinstance(improvements_schema_echo, dict) and isinstance(
            improvements_schema_echo.get("properties"), dict
        ):
            normalized["improvements"] = improvements_schema_echo["properties"]
    improvements = normalized.get("improvements")
    if isinstance(improvements, dict):
        if not isinstance(improvements.get("proposals"), list):
            improvements["proposals"] = []
        improvements.setdefault("summary", "No structured improvement proposed.")
    normalized.setdefault("warnings", [])
    normalized.setdefault("confidence", "medium")
    normalized.setdefault("needsReview", True)
    return normalized


def local_gp180_fallback(request, verdict, reason):
    text = verdict_text(verdict)
    if any(word in text for word in ("fuzz", "buzzy", "gated", "nasal")):
        amp, cab, drive, mod, delay, reverb = (
            "Foxy 30TB",
            "Foxy 2x12",
            "Red Haze",
            "None",
            "Tape",
            "Room",
        )
        summary = "Local fallback fuzz/psychedelic GP-180 approximation."
    elif any(word in text for word in ("metal", "saturated", "recti", "high gain", "heavy")):
        amp, cab, drive, mod, delay, reverb = (
            "Recti",
            "Mess 4x12",
            "Green OD",
            "None",
            "Digital Delay",
            "Plate",
        )
        summary = "Local fallback high-gain GP-180 approximation."
    elif any(word in text for word in ("marshall", "plexi", "crunch", "rock", "ac/dc", "hard")):
        amp, cab, drive, mod, delay, reverb = (
            "UK SLP",
            "UK Vintage 4x12",
            "None",
            "None",
            "Tape",
            "Room",
        )
        summary = "Local fallback classic-rock GP-180 approximation."
    elif any(word in text for word in ("chorus", "shimmer", "80s", "rack", "wide")):
        amp, cab, drive, mod, delay, reverb = (
            "Silver Twin",
            "US 2x12",
            "None",
            "Chorus",
            "Digital Delay",
            "Plate",
        )
        summary = "Local fallback clean/chorus GP-180 approximation."
    else:
        amp, cab, drive, mod, delay, reverb = (
            "US Deluxe",
            "US 2x12",
            "None",
            "None",
            "Digital Delay",
            "Room",
        )
        summary = "Local fallback clean GP-180 approximation."

    blocks = [
        block(
            1, "noise reduction", "NR", "Gate 1", {"Threshold": "-60 dB"}, "Keep noise controlled."
        ),
        block(
            2,
            "dynamics",
            "PRE",
            "Comp",
            {"Sustain": 35, "Level": "unity"},
            "Smooth dynamics before amp.",
        ),
        block(
            3,
            "drive",
            "DST",
            drive,
            {"Gain": 35, "Tone": 50, "Level": "unity"},
            "Match required gain texture.",
            active=drive != "None",
        ),
        block(4, "preamp", "PRE", "None", {}, "No extra preamp coloration.", active=False),
        block(
            5,
            "amp",
            "AMP",
            amp,
            {"Gain": 35, "Bass": 45, "Mid": 55, "Treble": 58, "Level": 85},
            "Core amp family.",
        ),
        block(
            6, "cabinet", "CAB/IR", cab, {"Mic": "center/off-axis blend"}, "Closest cabinet family."
        ),
        block(
            7,
            "eq",
            "EQ",
            "Guitar EQ 1",
            {"Low": "flat", "Mid": "+1 dB", "High": "flat"},
            "Final tone shaping.",
        ),
        block(
            8,
            "modulation",
            "MOD",
            mod,
            {"Rate": 25, "Depth": 35, "Mix": 25},
            "Add required movement.",
            active=mod != "None",
        ),
        block(
            9,
            "delay",
            "DLY",
            delay,
            {"Time": "280 ms", "Feedback": 18, "Mix": 12},
            "Subtle space/depth.",
            active=delay != "None",
        ),
        block(10, "reverb", "RVB", reverb, {"Decay": "2.2 s", "Mix": 18}, "Record-like ambience."),
        block(11, "volume", "VOL", "Volume", {"Level": "unity"}, "Output trim."),
    ]
    target = verdict.get("targetTone", "musical target")
    return {
        "gp180": {
            "equipment": {"model": "Valeton GP-180"},
            "guitar": request.get("guitar", "Default electric guitar"),
            "output": request.get("output", "FRFR / headphones"),
            "choicePolicy": f"Local fallback after Ollama GP-180 failure. Preserve target: {target}",
            "bestMatchSummary": summary,
            "blocks": blocks,
        },
        "warnings": [
            "Local deterministic GP-180 fallback used after Ollama failed semantic validation.",
            f"Original error: {reason[:240]}",
        ],
        "confidence": "medium",
        "needsReview": True,
    }


def local_improvements_fallback(reason):
    return {
        "improvements": {
            "summary": "Local fallback: review by ear before buying external captures.",
            "proposals": [
                {
                    "priority": "P3",
                    "type": "IR",
                    "target": "Cabinet realism",
                    "recommendedAsset": "Song-appropriate speaker IR",
                    "reason": "Use only if factory cab feels generic.",
                    "replacesBlockOrder": None,
                    "whenToUse": "After testing the GP-180 preset.",
                    "expectedGain": "Better speaker/mic realism.",
                    "requiredIfGp180Gap": False,
                }
            ],
        },
        "warnings": [
            "Local deterministic improvements fallback used after Ollama failed semantic validation.",
            f"Original error: {reason[:240]}",
        ],
        "confidence": "medium",
        "needsReview": True,
    }


def block(order, role, module, model, settings, purpose, active=True):
    return {
        "order": order,
        "role": role,
        "module": module,
        "model": model,
        "active": active,
        "settings": settings,
        "purpose": purpose,
        "matchQuality": "fallback",
        "gap": "Local deterministic fallback, validate by ear.",
        "alternatives": [],
    }


def verdict_text(verdict):
    parts = [str(verdict.get("targetTone", ""))]
    for key in ("mustHave", "avoid", "gearClues", "corrections"):
        parts.extend(str(item) for item in verdict.get(key, []))
    return " ".join(parts).lower()


def local_timing(stage, reason):
    return {
        "stage": stage,
        "provider": "local",
        "model": "deterministic-fallback",
        "seconds": 0.0,
        "prompt_chars": 0,
        "response_chars": 0,
        "usage": {},
        "attempts": 0,
        "retryFailures": [{"attempt": "fallback", "error": reason}],
    }


def timing_used(record_stage, timings):
    return any(timing.get("stage") == record_stage for timing in timings)


def openai_judge_prompt(request, ollama_music):
    payload = {"song": request, "ollamaDraft": ollama_music}
    return (
        OPENAI_JUDGE_SYSTEM
        + "\n\n# OUTPUT JSON SCHEMA\n"
        + json.dumps(OPENAI_JUDGE_SCHEMA, ensure_ascii=False)
        + "\n\n# VARIABLE INPUT\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def claude_fallback_prompt(request, ollama_music, openai_judge):
    payload = {"song": request, "ollamaDraft": ollama_music, "openaiJudge": openai_judge}
    return "Correct this musical target and return the required short JSON.\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )


def production_gp180_prompt(request, final_verdict):
    payload = {"song": request, "musicalVerdict": final_verdict}
    example = {
        "gp180": {
            "equipment": {"model": "Valeton GP-180"},
            "guitar": "Default electric guitar",
            "output": "FRFR / headphones",
            "choicePolicy": "short policy",
            "bestMatchSummary": "short signal-chain summary",
            "blocks": [
                {
                    "order": 1,
                    "role": "noise reduction",
                    "module": "NR",
                    "model": "Gate 1",
                    "active": True,
                    "settings": {"Threshold": "-60 dB"},
                    "purpose": "short purpose",
                    "matchQuality": "close",
                    "gap": "short gap or none",
                    "alternatives": [],
                }
            ],
        },
        "warnings": [],
        "confidence": "medium",
        "needsReview": True,
    }
    return f"""# TASK
Generate a usable Valeton GP-180 guitar rig from the musical verdict.

This is always a guitar-rig task:
- If the original recording is piano, voice, bass-only, synth, strings, or sparse/non-guitar, create a guitar imitation rig for the most playable musical role.
- Never return empty blocks.
- Always return 8 to 12 blocks.
- Use exact model names from the compact catalog.
- If the source is non-guitar, state the limitation in warnings and choicePolicy, but still build the closest GP-180 guitar rig.

Allowed catalog:
{COMPACT_GP180_CATALOG}

Return one JSON object only, exactly shaped like this:
{json.dumps(example, ensure_ascii=False, indent=2)}

Required minimum chain:
- NR or None
- PRE or None
- DST or None
- AMP
- CAB/IR
- EQ
- WAH or None
- MOD or None
- DLY or None
- RVB
- VOL

Rules:
- blocks must be a non-empty array with at least 8 entries.
- Every block needs order, role, module, model, active, settings, purpose, matchQuality, gap, alternatives.
- equipment.model must be "Valeton GP-180".
- For clean/piano-like/voice-like targets, use Comp, US Deluxe or Silver Twin, US 2x12, Chorus if useful, Room/Plate.
- For AC/DC/classic rock, use UK SLP/UK 45/UK 50 and UK Vintage 4x12 with dry room.
- For 80s hard rock/metal, use UK 800 or Recti and 4x12 with modest ambience.
- For fuzz/psychedelic targets, use Red Haze or Fuzz before a suitable amp.
- Document gaps honestly but do not refuse.

# INPUT
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


def production_improvements_prompt(request, final_verdict, gp180):
    payload = {"song": request, "musicalVerdict": final_verdict, "gp180Result": gp180}
    example = {
        "improvements": {
            "summary": "short summary",
            "proposals": [
                {
                    "priority": "P3",
                    "type": "IR",
                    "target": "Cabinet realism",
                    "recommendedAsset": "song-appropriate IR",
                    "reason": "short reason",
                    "replacesBlockOrder": None,
                    "whenToUse": "after testing GP-180 preset",
                    "expectedGain": "short expected gain",
                    "requiredIfGp180Gap": False,
                }
            ],
        },
        "warnings": [],
        "confidence": "medium",
        "needsReview": True,
    }
    return f"""# TASK
Generate NAM/SnapTone/IR improvement proposals only.

Return one JSON object only, exactly shaped like this:
{json.dumps(example, ensure_ascii=False, indent=2)}

Rules:
- Max 3 proposals.
- Use priority "none" and empty proposals if the GP-180 preset is sufficient.
- Use P1 only for a critical missing fuzz/amp/cab signature.
- Keep every reason short.
- Do not include markdown.

# INPUT
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


def genre_classification_prompt(request, final_verdict, rig):
    payload = {
        "song": {
            "artist": request.get("artist", ""),
            "title": request.get("title", ""),
            "sourceGenre": request.get("genre", ""),
            "year": request.get("year", ""),
        },
        "musicalVerdict": final_verdict,
        "rigSummary": {
            "toneProfile": rig.get("toneProfile", ""),
            "signalChainSummary": rig.get("signalChainSummary", ""),
            "blocks": [
                {
                    "module": block.get("module"),
                    "model": block.get("model"),
                    "role": block.get("role"),
                }
                for block in (rig.get("blocks") or [])[:12]
            ],
        },
    }
    return f"""# TASK
Classify the musical genre for Fretwise import.

Use the song identity first, then the musical verdict and rig summary.
If sourceGenre is non-empty and plausible, preserve it.
Return a useful musical genre, not a guitar tone and not an instrument name.

Rules:
- genre: one short primary genre, e.g. "classic rock", "blues", "soul", "punk rock", "grunge", "funk", "bossa nova", "pop rock".
- subgenres: 1 to 5 short tags, more specific if useful.
- confidence: high, medium, or low.
- rationale: under 18 words.
- Return JSON only.

# OUTPUT SHAPE
{{
  "genre": "short primary genre",
  "subgenres": ["short tag"],
  "confidence": "high",
  "rationale": "short reason"
}}

# INPUT
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


def should_escalate(openai_judge, request=None):
    verdict = openai_judge.get("finalVerdict") or {}
    if openai_judge.get("action") == "escalate":
        return True
    if verdict.get("confidence") == "low":
        return True
    if verdict.get("needsManualReview"):
        return True
    if verdict_quality_issues(verdict, request):
        return True
    return False


def verdict_quality_issues(verdict, request=None):
    issues = []
    target = str(verdict.get("targetTone", "")).strip()
    target_tokens = [token for token in target.replace("-", " ").split() if token]
    if len(target_tokens) < 4:
        issues.append("targetTone is too short")
    lower_target = target.lower()
    thin_targets = {
        "rock tone",
        "lead tone",
        "clean guitar",
        "distorted guitar",
        "electric guitar",
        "e minor",
        "a minor",
        "d minor",
        "g minor",
        "c minor",
        "e major",
        "a major",
        "d major",
        "g major",
        "c major",
    }
    if lower_target in thin_targets:
        issues.append("targetTone is generic or harmonic-only")
    if not verdict.get("mustHave") or len(verdict.get("mustHave", [])) < 2:
        issues.append("mustHave lacks decisive audible clues")
    if not verdict.get("gearClues"):
        issues.append("gearClues missing")
    full_text = " ".join(
        [
            str(request.get("title", "") if request else ""),
            target,
            " ".join(str(item) for item in verdict.get("mustHave", [])),
            " ".join(str(item) for item in verdict.get("gearClues", [])),
            " ".join(str(item) for item in verdict.get("corrections", [])),
        ]
    ).lower()
    if any(
        marker in full_text
        for marker in ("bass only", "piano only", "karaoke", "isolated bass", "stem only")
    ):
        issues.append("non-guitar or stem-specific song entry")
    return issues


def general_from_verdict(verdict, source):
    result = general_from_claude_verdict(verdict)
    general = result.setdefault("general", {})
    target = str(
        general.get("toneProfile") or general.get("targetSound") or verdict.get("targetTone") or ""
    ).strip()
    if not target:
        target = "song-specific guitar interpretation"
    general["targetSound"] = str(general.get("targetSound") or target)
    general["toneProfile"] = str(general.get("toneProfile") or target)

    chain_items = [
        str(item).strip()
        for item in (verdict.get("gearClues") or verdict.get("mustHave") or [])
        if str(item).strip()
    ]
    if not chain_items:
        chain_items = [target]
    general["idealSignalChain"] = str(general.get("idealSignalChain") or " | ".join(chain_items))
    if not general.get("bestPossibleEquipment"):
        general["bestPossibleEquipment"] = [
            {"role": "signature", "model": item, "reason": f"{source} musical verdict"}
            for item in chain_items[:5]
        ]
    general.setdefault("productionNotes", verdict.get("mustHave", []))
    result["sources"] = [f"{source} music verdict", "Ollama music draft"]
    result["confidence"] = confidence_to_schema(verdict.get("confidence", "medium"))
    return result


def validate_output(rig):
    warnings = []
    errors = []
    try:
        validate_rig(normalize_rig(rig))
    except Exception as exc:
        errors.append(str(exc))
    blocks = rig.get("blocks") or []
    if len(blocks) < 3:
        errors.append("GP-180 block count is below 3.")
    invalid_models = []
    for block in blocks:
        model = str(block.get("model", ""))
        if model and model not in ALLOWED_GP180_MODELS:
            invalid_models.append(model)
    if invalid_models:
        errors.append("Non-catalog GP-180 models: " + ", ".join(sorted(set(invalid_models))))
    if not rig.get("toneProfile"):
        errors.append("Missing toneProfile.")
    if not rig.get("signalChainSummary"):
        warnings.append("Missing signalChainSummary.")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def new_summary(args, total_rows, output_root):
    return {
        "metadata": {
            "workflow": "economic_production_v1",
            "totalInputSongs": total_rows,
            "offset": args.offset,
            "limit": args.limit,
            "limitSpec": getattr(args, "limit_spec", str(args.limit)),
            "jobs": args.jobs,
            "ollamaUrls": summarize_worker_urls(getattr(args, "ollama_worker_urls", [])),
            "outputRoot": str(output_root),
            "models": {
                "ollama": args.ollama_model,
                "openaiJudge": args.openai_model,
                "claudeFallback": args.claude_model,
            },
            "openaiOptions": openai_options(args),
        },
        "counts": {
            "songsAttempted": 0,
            "songsCompleted": 0,
            "songsSkippedExisting": 0,
            "openaiAccepted": 0,
            "openaiRepaired": 0,
            "openaiEscalated": 0,
            "claudeFallbacks": 0,
            "localGp180Fallbacks": 0,
            "localImprovementsFallbacks": 0,
            "validationOk": 0,
            "validationFailed": 0,
        },
        "timings": [],
        "songs": [],
        "errors": [],
    }


def update_summary(summary, record, skipped=False):
    if skipped:
        summary["counts"]["songsSkippedExisting"] += 1
    else:
        summary["counts"]["songsCompleted"] += 1
    action = record.get("metadata", {}).get("openaiAction", "")
    if action == "accept":
        summary["counts"]["openaiAccepted"] += 1
    elif action == "repair":
        summary["counts"]["openaiRepaired"] += 1
    elif action == "escalate":
        summary["counts"]["openaiEscalated"] += 1
    if record.get("metadata", {}).get("finalVerdictSource") == "claude":
        summary["counts"]["claudeFallbacks"] += 1
    if record.get("metadata", {}).get("usedLocalGp180Fallback"):
        summary["counts"]["localGp180Fallbacks"] += 1
    if record.get("metadata", {}).get("usedLocalImprovementsFallback"):
        summary["counts"]["localImprovementsFallbacks"] += 1
    validation_ok = bool(record.get("validation", {}).get("ok"))
    summary["counts"]["validationOk" if validation_ok else "validationFailed"] += 1
    summary["timings"].extend(record.get("timings", []))
    verdict = record.get("finalVerdict") or {}
    summary["songs"].append(
        {
            "sourceIndex": record.get("metadata", {}).get("sourceIndex"),
            "song": record.get("song"),
            "openaiAction": action,
            "finalVerdictSource": record.get("metadata", {}).get("finalVerdictSource"),
            "targetTone": verdict.get("targetTone", ""),
            "validationOk": validation_ok,
        }
    )


def finalize_summary(summary, started):
    completed = summary["counts"]["songsCompleted"] + summary["counts"]["songsSkippedExisting"]
    elapsed = time.perf_counter() - started
    summary["runtime"] = {
        "elapsedSeconds": round(elapsed, 3),
        "songsPerHour": round(completed / elapsed * 3600, 2) if elapsed and completed else 0,
        "estimatedSecondsFor1783AtCurrentRate": round(1783 / completed * elapsed, 1)
        if completed
        else 0,
    }
    summary["rates"] = {
        "claudeFallbackRate": round(summary["counts"]["claudeFallbacks"] / completed, 3)
        if completed
        else 0,
        "localGp180FallbackRate": round(summary["counts"]["localGp180Fallbacks"] / completed, 3)
        if completed
        else 0,
        "localImprovementsFallbackRate": round(
            summary["counts"]["localImprovementsFallbacks"] / completed, 3
        )
        if completed
        else 0,
        "validationOkRate": round(summary["counts"]["validationOk"] / completed, 3)
        if completed
        else 0,
    }
    summary["openaiCostEstimate"] = estimate_openai_cost_for_summary(summary)
    summary["claudeCostEstimate"] = estimate_claude_sonnet_cost_for_summary(summary)
    summary["projectedFullCorpusCostUsd"] = {
        "openaiAtCurrentRate": round(
            summary["openaiCostEstimate"]["costPerCompletedSongUsd"] * 1783, 4
        ),
        "claudeAtCurrentRate": round(
            summary["claudeCostEstimate"]["claudeCostPerCompletedSongUsd"] * 1783, 4
        ),
        "totalAtCurrentRate": round(
            (
                summary["openaiCostEstimate"]["costPerCompletedSongUsd"]
                + summary["claudeCostEstimate"]["claudeCostPerCompletedSongUsd"]
            )
            * 1783,
            4,
        ),
    }


def estimate_claude_sonnet_cost_for_summary(summary):
    compat = {
        "counts": {
            "songsCompleted": summary["counts"]["songsCompleted"]
            + summary["counts"]["songsSkippedExisting"]
        },
        "timings": summary["timings"],
    }
    estimate = estimate_claude_sonnet_cost(compat)
    estimate["ratesPerMTokUsd"] = CLAUDE_SONNET_RATES_PER_MTOK
    return estimate


def estimate_openai_cost_for_summary(summary):
    completed = summary["counts"]["songsCompleted"] + summary["counts"]["songsSkippedExisting"]
    compat = {
        "counts": {"songsCompleted": completed},
        "timings": summary["timings"],
    }
    return estimate_openai_cost(compat)


def openai_options(args):
    options = {}
    if args.openai_prompt_cache_key:
        options["prompt_cache_key"] = args.openai_prompt_cache_key
    if args.openai_prompt_cache_retention:
        options["prompt_cache_retention"] = args.openai_prompt_cache_retention
    if args.openai_text_verbosity:
        options["text_verbosity"] = args.openai_text_verbosity
    if args.openai_reasoning_effort:
        options["reasoning_effort"] = args.openai_reasoning_effort
    return options


def checkpoint(args, last_source_index, total_rows, summary):
    return {
        "workflow": "economic_production_v1",
        "lastCompletedSourceIndex": last_source_index,
        "nextOffset": last_source_index,
        "remainingSongs": max(total_rows - last_source_index, 0),
        "lastRunOffset": args.offset,
        "lastRunLimit": args.limit,
        "counts": summary["counts"],
    }


def progress_entry(status, source_index, batch_index, total_selected, request, record, output_path):
    return {
        "ts": time.time(),
        "status": status,
        "sourceIndex": source_index,
        "batchIndex": batch_index,
        "batchTotal": total_selected,
        "song": {"artist": request["artist"], "title": request["title"]},
        "outputPath": str(output_path),
        "openaiAction": record.get("metadata", {}).get("openaiAction"),
        "finalVerdictSource": record.get("metadata", {}).get("finalVerdictSource"),
        "workerId": record.get("metadata", {}).get("workerId"),
        "workerEndpoint": record.get("metadata", {}).get("workerEndpoint"),
        "workerNumCtx": record.get("metadata", {}).get("workerNumCtx"),
        "validationOk": record.get("validation", {}).get("ok"),
        "seconds": round(sum(t.get("seconds", 0) for t in record.get("timings", [])), 3),
    }


def format_song_result(record, output_path):
    validation = record.get("validation", {})
    return (
        f"Output JSON -> {output_path}\n"
        f"Final source: {record['metadata']['finalVerdictSource']} | OpenAI action: {record['metadata']['openaiAction']} | "
        f"validation={validation.get('ok')}\n"
        f"Target: {record.get('finalVerdict', {}).get('targetTone', '')}"
    )


def format_progress(summary):
    counts = summary["counts"]
    completed = counts["songsCompleted"] + counts["songsSkippedExisting"]
    openai_cost = summary.get("openaiCostEstimate", {}).get("costPerCompletedSongUsd", 0)
    claude_cost = summary.get("claudeCostEstimate", {}).get("claudeCostPerCompletedSongUsd", 0)
    return (
        f"Progress {completed}/{summary['metadata']['limit']} | "
        f"fallback Claude={counts['claudeFallbacks']} ({summary.get('rates', {}).get('claudeFallbackRate', 0):.0%}) | "
        f"local GP180={counts.get('localGp180Fallbacks', 0)} | "
        f"validation OK={counts['validationOk']} failed={counts['validationFailed']} | "
        f"cost/song OpenAI=${openai_cost:.4f} Claude=${claude_cost:.4f} | "
        f"rate={summary.get('runtime', {}).get('songsPerHour', 0):.1f} songs/h"
    )


def log_json(path, data):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


def log(path, message):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
