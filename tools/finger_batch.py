#!/usr/bin/env python3
"""Resumable, auto-tuned, multi-core batch regeneration of stale fingerings.

The library UI flags every song whose fingerings were computed by an older
version of the engine with an amber "⚠" hand icon (see
``src/fretwise/web/static/js/main.js`` around line 518, driven by
``_fingering_meta_is_current`` / ``FINGERING_ALGO_VERSION`` in
``src/fretwise/web/app.py``). This script recomputes every such song.

Why a standalone script instead of the existing ``/api/library/refresh-fingerings``
endpoint: that endpoint deliberately uses a ``ThreadPoolExecutor`` (GIL-bound)
because a ``ProcessPoolExecutor`` tried from *inside* the live FastAPI/uvicorn
server hung on Windows when spawning workers (see the docstring of
``_process_single_gp`` in app.py, and git commits 756f0200 / ccfb7753). A cold
``if __name__ == "__main__"`` script has no live event loop or open sockets at
spawn time, so a real ``ProcessPoolExecutor`` across all CPU cores works fine
here — the same shape that already works for ``tools/rig_batch.py``.

GPUs are *not* used for compute: a fingering takes ~100ms, dominated by a
pure-Python Viterbi step (GIL-bound) plus tiny ONNX models (24-26 features)
that already run on CPU faster than a CUDA kernel launch would. The dashboard
shows GPU stats for transparency only.

Stop & resume: progress is checkpointed to a state file after every file and
on Ctrl-C/dashboard-Stop, so a re-run skips everything already done.

Worker count is capped at MAX_WORKERS_CEILING (8) regardless of core count, and
each file gets at most FILE_TIMEOUT_S (240s); a stuck file's worker is killed and
the file retried once, then marked "error" on a second timeout.

    pixi run python tools/finger_batch.py                  # resume / run all
    pixi run python tools/finger_batch.py --dry-run         # plan only
    pixi run python tools/finger_batch.py --limit 20         # first 20 pending
    pixi run python tools/finger_batch.py --refresh           # ignore checkpoint, redo all
    pixi run python tools/finger_batch.py --no-dashboard      # headless, console only
    pixi run python tools/finger_batch.py --max-workers 8      # skip auto-tune, fixed pool size
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, wait
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        # line_buffering=True so progress lines flush immediately even when stdout
        # is a pipe (otherwise parent prints sit in a block buffer behind worker
        # noise and the run *looks* frozen — it isn't).
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from pebble import ProcessExpired, ProcessPool  # noqa: E402

from fretwise.web import settings as _settings  # noqa: E402
from fretwise.web.app import (  # noqa: E402
    FINGERING_ALGO_VERSION,
    _fingering_meta_is_current,
    _process_single_gp,
    _read_fingering_meta,
)

try:
    import psutil
except ImportError:  # pragma: no cover — degrades gracefully
    psutil = None

try:
    import pynvml

    pynvml.nvmlInit()
    _GPU_COUNT = pynvml.nvmlDeviceGetCount()
except Exception:  # noqa: BLE001 — optional, informational only
    pynvml = None
    _GPU_COUNT = 0

STATE_FILE = REPO / "exports" / "finger_batch_state.json"
HISTORY_LEN = 180  # ~6 minutes at 2s sampling
MEM_CEILING = 75.0  # target RAM ceiling used to cap the worker count
MEM_SAFETY_CEILING = 85.0  # backpressure during the main run
MEM_SAFETY_RESUME = 70.0
MAX_WORKERS_CEILING = 8  # hard cap on parallel workers, regardless of core count
FILE_TIMEOUT_S = 240.0  # kill a single file's worker past this; retry once, then error

_stop = threading.Event()


def _worker(path_str: str) -> dict[str, Any]:
    """Subprocess entry point: mute the pipeline's per-note WARNING spam, then run.

    The fingering pipeline logs a WARNING for every unresolvable chord span and
    every guitar-less track. Across 1800 files that's tens of thousands of lines
    that drown the progress output, so we raise the ``fretwise`` logger to ERROR
    inside each worker (genuine errors still come back in the result dict —
    ``_process_single_gp`` never raises).
    """
    import logging

    logging.getLogger("fretwise").setLevel(logging.ERROR)
    return _process_single_gp(path_str)


def _handle_sigint(signum: int, frame: object) -> None:  # noqa: ARG001
    _stop.set()
    print("\n[stop] arrêt demandé — flush du checkpoint après les fichiers en vol…", flush=True)


# ── Resumable state file (same atomic pattern as tools/rig_batch.py) ─────────

def load_state(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"version": 1, "algo_version": FINGERING_ALGO_VERSION, "done": {}}


def save_state(path: Path, state: dict[str, Any]) -> bool:
    """Atomically checkpoint *state*. Never raises — a failed write must not kill
    a long run (e.g. a transient Windows FS hiccup under heavy concurrent disk
    load). Retries briefly, then gives up and lets the next file re-checkpoint.
    """
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".tmp")
    for attempt in range(4):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)  # atomic on the same volume
            return True
        except OSError as exc:
            if attempt == 3:
                print(f"  [warn] checkpoint non écrit ({exc}); reprise au prochain fichier.")
                return False
            time.sleep(0.25 * (attempt + 1))
    return False


# ── Library root + worklist (mirrors app.py's /api/library/refresh-fingerings) ─

def resolve_library_root(override: Path | None = None) -> Path:
    if override is not None:
        return override
    cfg = _settings.load()
    backend = str(cfg.get("storage_backend") or "local")
    if backend != "local":
        print(
            f"[error] storage_backend={backend!r} — ce script ne supporte que le "
            "stockage local (même limite que /api/library/refresh-fingerings).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return Path(cfg.get("partitions_dir") or _settings.DEFAULT_PARTITIONS_DIR)


def build_worklist(root: Path, *, force: bool) -> tuple[list[Path], list[Path]]:
    """Return (to_process, pre_skipped) — same criterion as the amber UI badge."""
    all_files = sorted(root.glob("*.gp"))
    sources = [f for f in all_files if not f.stem.endswith("_fingered")]
    to_process: list[Path] = []
    pre_skipped: list[Path] = []
    for f in sources:
        if not force:
            meta = _read_fingering_meta(f)
            if meta is not None and _fingering_meta_is_current(meta, f):
                pre_skipped.append(f)
                continue
        to_process.append(f)
    return to_process, pre_skipped


# ── Shared live state for the dashboard (read by the HTTP thread, written by main) ─

@dataclass
class BatchState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    total: int = 0
    pre_skipped: int = 0
    done: int = 0
    ok: int = 0
    err: int = 0
    workers: int = 0
    calibrating: bool = True
    calibration_log: list[dict[str, Any]] = field(default_factory=list)
    in_flight: dict[str, float] = field(default_factory=dict)  # filename -> start ts
    throughput_history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))
    cpu_history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))
    mem_history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))
    gpu_history: list[deque] = field(default_factory=list)
    started_at: float = 0.0
    last_results: deque = field(default_factory=lambda: deque(maxlen=12))
    user_paused: bool = False
    auto_paused: bool = False
    finished: bool = False

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            elapsed = time.monotonic() - self.started_at if self.started_at else 0.0
            rate = self.done / elapsed * 60 if elapsed > 1 else 0.0
            remaining = self.total - self.done
            eta_s = remaining / (rate / 60) if rate > 0 and remaining > 0 else None
            return {
                "total": self.total,
                "pre_skipped": self.pre_skipped,
                "done": self.done,
                "ok": self.ok,
                "err": self.err,
                "workers": self.workers,
                "calibrating": self.calibrating,
                "calibration_log": list(self.calibration_log),
                "in_flight": [
                    {"file": f, "elapsed_s": round(time.monotonic() - t0, 1)}
                    for f, t0 in self.in_flight.items()
                ],
                "throughput_history": list(self.throughput_history),
                "cpu_history": list(self.cpu_history),
                "mem_history": list(self.mem_history),
                "gpu_history": [list(h) for h in self.gpu_history],
                "elapsed_s": round(elapsed, 1),
                "rate_per_min": round(rate, 1),
                "eta_s": round(eta_s) if eta_s else None,
                "last_results": list(self.last_results),
                "user_paused": self.user_paused,
                "auto_paused": self.auto_paused,
                "finished": self.finished,
                "algo_version": FINGERING_ALGO_VERSION,
                "gpu_count": _GPU_COUNT,
                "psutil_available": psutil is not None,
            }


# ── Resource monitor thread (feeds the dashboard charts + RAM backpressure) ──

def _gpu_samples() -> list[float]:
    if not pynvml or not _GPU_COUNT:
        return []
    samples = []
    for i in range(_GPU_COUNT):
        try:
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            samples.append(float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu))
        except Exception:  # noqa: BLE001
            samples.append(0.0)
    return samples


def monitor_loop(state: BatchState, stop: threading.Event) -> None:
    if psutil is not None:
        psutil.cpu_percent(interval=None)  # prime the non-blocking counter
    if state.gpu_history == [] and _GPU_COUNT:
        state.gpu_history = [deque(maxlen=HISTORY_LEN) for _ in range(_GPU_COUNT)]
    last_done = 0
    last_t = time.monotonic()
    while not stop.is_set():
        time.sleep(2.0)
        now = time.monotonic()
        cpu = psutil.cpu_percent(interval=None) if psutil else None
        mem = psutil.virtual_memory().percent if psutil else None
        with state.lock:
            ts = round(now - state.started_at, 1) if state.started_at else 0.0
            if cpu is not None:
                state.cpu_history.append((ts, cpu))
            if mem is not None:
                state.mem_history.append((ts, mem))
            for hist, val in zip(state.gpu_history, _gpu_samples(), strict=False):
                hist.append((ts, val))
            rate = (state.done - last_done) / (now - last_t) * 60 if now > last_t else 0.0
            state.throughput_history.append((ts, round(rate, 1)))
            last_done, last_t = state.done, now

            # RAM safety backpressure — independent of the dashboard pause toggle.
            if mem is not None:
                if mem > MEM_SAFETY_CEILING and not state.auto_paused:
                    state.auto_paused = True
                elif mem < MEM_SAFETY_RESUME and state.auto_paused:
                    state.auto_paused = False


# ── Worker count: cores + RAM headroom (no multi-pool A/B — see note below) ──
#
# An earlier version "calibrated" by running the first files through fresh pools
# of 8/16/24 workers and keeping the fastest. On Windows that measured the wrong
# thing: each trial pool re-spawns N processes that re-import the whole fretwise
# stack (~30-50s), a one-time cost that does NOT recur in the real run's single
# persistent pool — so the bigger pools always looked "slower" and the heuristic
# wrongly picked the smallest. The work here is CPU-bound pure-Python-per-process
# (one GIL per worker), so throughput rises with workers up to the core count,
# bounded only by RAM. The right N is therefore min(cores, RAM headroom) — no A/B
# needed. Live RAM backpressure (monitor_loop) handles any runtime spike.

PER_WORKER_GB = 0.6  # rough RSS per worker (fretwise + ONNX), for the RAM cap


def choose_workers(state: BatchState, cpu_count: int) -> int:
    """Pick the pool size from core count, capped by MAX_WORKERS_CEILING and by
    available RAM headroom."""
    n = min(cpu_count, MAX_WORKERS_CEILING)
    reason = (
        f"{cpu_count} cœurs (plafonné à {MAX_WORKERS_CEILING})"
        if cpu_count > MAX_WORKERS_CEILING
        else f"{cpu_count} cœurs"
    )
    if psutil is not None:
        total_gb = psutil.virtual_memory().total / (1024**3)
        ram_cap = max(2, int(total_gb * (MEM_CEILING / 100.0) / PER_WORKER_GB))
        if ram_cap < n:
            n = ram_cap
            reason = f"plafond RAM ({total_gb:.0f} Go → {ram_cap} workers)"
    n = max(1, n)
    with state.lock:
        state.calibrating = False
        state.workers = n
        state.calibration_log.append({"workers": n, "reason": reason})
    print(f"[workers] {n} workers retenus ({reason}).")
    return n


# ── Main processing loop ─────────────────────────────────────────────────────

def run_batch(
    to_process: list[Path],
    n_workers: int,
    state: BatchState,
    state_path: Path,
    persisted: dict[str, Any],
) -> None:
    root_done = persisted.setdefault("done", {})
    # Pebble's ProcessPool (unlike stdlib ProcessPoolExecutor) lets a per-task
    # timeout kill *just* the offending worker and silently respawn a fresh one —
    # the rest of the pool keeps running. A bare ProcessPoolExecutor can't do this:
    # killing one of its workers trips BrokenProcessPool for the *whole* pool, and
    # pool.shutdown(wait=True) blocks forever on a genuinely stuck worker — which is
    # exactly why the dashboard Stop button used to hang instead of stopping.
    timeout_retries: dict[Path, int] = {}
    with ProcessPool(max_workers=n_workers) as pool:
        pending = list(to_process)
        in_flight: dict[Future, Path] = {}

        def _effective_pause() -> bool:
            with state.lock:
                return state.user_paused or state.auto_paused

        while pending or in_flight:
            if _stop.is_set():
                break
            while pending and len(in_flight) < n_workers and not _effective_pause():
                f = pending.pop(0)
                fut = pool.schedule(_worker, args=(str(f),), timeout=FILE_TIMEOUT_S)
                in_flight[fut] = f
                with state.lock:
                    state.in_flight[f.name] = time.monotonic()

            if not in_flight:
                time.sleep(0.2)
                continue

            done_set, _ = wait(in_flight.keys(), timeout=1.0, return_when=FIRST_COMPLETED)
            for fut in done_set:
                f = in_flight.pop(fut)
                with state.lock:
                    state.in_flight.pop(f.name, None)
                try:
                    result = fut.result()
                except FutureTimeoutError:
                    if timeout_retries.get(f, 0) == 0:
                        timeout_retries[f] = 1
                        pending.insert(0, f)  # retry now, ahead of the rest of the queue
                        print(f"  [timeout] {f.name} — dépassement {FILE_TIMEOUT_S:.0f}s, "
                              "worker tué, nouvelle tentative.")
                        continue  # not counted as done — it's back in the queue
                    result = {
                        "file": f.name, "status": "error",
                        "error": f"timeout (>{FILE_TIMEOUT_S:.0f}s) deux fois de suite",
                    }
                except ProcessExpired as exc:
                    result = {"file": f.name, "status": "error",
                              "error": f"worker process crashed: {exc}"}
                except Exception as exc:  # noqa: BLE001 — never crash the pool
                    result = {"file": f.name, "status": "error", "error": str(exc)}

                with state.lock:
                    state.done += 1
                    if result.get("status") == "ok":
                        state.ok += 1
                    else:
                        state.err += 1
                    state.last_results.append(result)
                root_done[str(f.relative_to(f.anchor) if f.is_absolute() else f)] = {
                    "status": result.get("status"),
                    "ts": int(time.time()),
                    "elapsed_s": result.get("elapsed_s"),
                }
                save_state(state_path, persisted)
                with state.lock:
                    done, total = state.done, state.total
                status = result.get("status")
                tag = "ok" if status == "ok" else status
                print(f"  [{tag}] {done}/{total} {f.name}"
                      + (f" — {result['error']}" if status == "error" else ""))

        if _stop.is_set() and (pending or in_flight):
            n_left = len(pending) + len(in_flight)
            pool.stop()  # kill in-flight workers immediately, don't wait on them
            pool.join(timeout=10)
            print(f"[stop] {n_left} fichier(s) non traités — relancer pour reprendre.")

    with state.lock:
        state.finished = True


# ── Dashboard (throwaway FastAPI/uvicorn app, separate port, same process) ──

def start_dashboard(state: BatchState, port: int) -> None:
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse

    dash = FastAPI()
    index_path = Path(__file__).resolve().parent / "finger_batch_static" / "index.html"

    @dash.get("/")
    def _index() -> FileResponse:
        return FileResponse(str(index_path))

    @dash.get("/state")
    def _state() -> JSONResponse:
        return JSONResponse(state.snapshot())

    @dash.post("/control/pause")
    def _pause() -> dict[str, bool]:
        with state.lock:
            state.user_paused = True
        return {"user_paused": True}

    @dash.post("/control/resume")
    def _resume() -> dict[str, bool]:
        with state.lock:
            state.user_paused = False
        return {"user_paused": False}

    @dash.post("/control/stop")
    def _stop_route() -> dict[str, bool]:
        _stop.set()
        return {"stopping": True}

    config = uvicorn.Config(dash, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    print(f"[dashboard] http://127.0.0.1:{port}")


# ── CLI ───────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Batch regeneration des doigtés obsolètes.")
    p.add_argument("--root", type=Path, default=None,
                   help="Force la racine bibliothèque (défaut: partitions_dir de ~/.fretwise/config.json).")
    p.add_argument("--state", type=Path, default=STATE_FILE)
    p.add_argument("--limit", type=int, default=0, help="Traiter au plus N fichiers en attente.")
    p.add_argument("--refresh", action="store_true", help="Ignorer le checkpoint, tout retraiter.")
    p.add_argument("--force", action="store_true",
                   help="Retraiter aussi les fichiers déjà à jour (algo_version courant).")
    p.add_argument("--dry-run", action="store_true", help="Planifier seulement; n'écrit rien.")
    p.add_argument("--max-workers", type=int, default=0,
                   help="Fixe le nombre de workers (saute la calibration auto).")
    p.add_argument("--no-dashboard", action="store_true", help="Pas de serveur web, console seule.")
    p.add_argument("--port", type=int, default=8765, help="Port du dashboard web.")
    args = p.parse_args(argv)

    root = resolve_library_root(args.root)
    if not root.is_dir():
        print(f"[error] bibliothèque introuvable: {root}", file=sys.stderr)
        return 2

    to_process, pre_skipped = build_worklist(root, force=args.force)

    persisted = {"version": 1, "algo_version": FINGERING_ALGO_VERSION, "done": {}} \
        if args.refresh else load_state(args.state)
    done_keys = persisted.get("done", {})

    def _is_done_ok(f: Path) -> bool:
        # Resume skips only files that completed OK — errored files (e.g. a
        # transient FS hiccup mid-run) are retried on the next pass.
        key = str(f.relative_to(f.anchor) if f.is_absolute() else f)
        return done_keys.get(key, {}).get("status") == "ok"

    if not args.refresh:
        to_process = [f for f in to_process if not _is_done_ok(f)]
    done_ok = sum(1 for v in done_keys.values() if v.get("status") == "ok")

    if args.limit:
        to_process = to_process[: args.limit]

    print(f"[plan] racine={root}  à traiter={len(to_process)}  "
          f"déjà à jour={len(pre_skipped)}  déjà fait OK (checkpoint)={done_ok}")

    if args.dry_run:
        for f in to_process:
            print(f"  [dry] {f.name}")
        return 0

    if not to_process:
        print("[done] rien à faire.")
        return 0

    state = BatchState()
    state.total = len(to_process)
    state.pre_skipped = len(pre_skipped)
    state.started_at = time.monotonic()

    signal.signal(signal.SIGINT, _handle_sigint)
    monitor_stop = threading.Event()
    threading.Thread(target=monitor_loop, args=(state, monitor_stop), daemon=True).start()

    if not args.no_dashboard:
        start_dashboard(state, args.port)

    cpu_count = os.cpu_count() or 4
    if args.max_workers:
        n_workers = min(args.max_workers, cpu_count, MAX_WORKERS_CEILING)
        with state.lock:
            state.calibrating = False
            state.workers = n_workers
        print(f"[workers] {n_workers} workers (forcé via --max-workers, "
              f"plafond {MAX_WORKERS_CEILING}).")
    else:
        n_workers = choose_workers(state, cpu_count)

    if not _stop.is_set():
        run_batch(to_process, n_workers, state, args.state, persisted)

    save_state(args.state, persisted)
    monitor_stop.set()
    with state.lock:
        state.finished = True
        ok, err, done = state.ok, state.err, state.done
    print(f"\n[done] traités={done} ok={ok} erreurs={err}")
    print(f"[state] {args.state} — relancer la commande reprendra les fichiers restants.")
    if not args.no_dashboard:
        print("[dashboard] toujours actif — Ctrl-C pour fermer.")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
