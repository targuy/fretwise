#!/usr/bin/env python3
"""Resumable batch regeneration of GP-180 rig sheets through the grounded pipeline.

For every existing rig sheet it looks up verified facts (``data/song_facts.json``),
regenerates the rig with the local model, deterministically writes the hard facts,
validates against the GP-180 palette, and saves the ``.md`` (backing up the original
once). Songs without verified facts are still regenerated but marked ``D`` /
``non ancré`` — never an inflated grade.

Stop & resume: progress is checkpointed to a state file after every song and on
Ctrl-C, so a re-run skips everything already done and continues where it stopped.

    pixi run python tools/rig_batch.py                 # resume / run all
    pixi run python tools/rig_batch.py --only-grounded # only songs with facts
    pixi run python tools/rig_batch.py --limit 20      # first 20 pending
    pixi run python tools/rig_batch.py --refresh       # ignore checkpoint, redo all
    pixi run python tools/rig_batch.py --acquire       # fetch missing facts via web agent
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fretwise.rig import find_rigs_dir, parse_rig, rig_view_to_markdown  # noqa: E402
from fretwise.rig_generation import RigGenerationError, SongRigGenerationService  # noqa: E402
from fretwise.rig_pipeline import (  # noqa: E402
    JsonFactsProvider,
    facts_key,
    generate_grounded_rig,
)

FACTS_DB = REPO / "data" / "song_facts.json"
STATE_FILE = REPO / "exports" / "rig_batch_state.json"

_stop = False


def _handle_sigint(signum: int, frame: object) -> None:  # noqa: ARG001
    global _stop
    _stop = True
    print("\n[stop] arrêt demandé — flush du checkpoint après le morceau courant…", flush=True)


def load_state(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"version": 1, "done": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic on the same volume


def song_list(rigs_dir: Path) -> list[tuple[Path, str, str]]:
    """Return (rig_path, artist, title) for every rig sheet, sorted by name."""
    songs: list[tuple[Path, str, str]] = []
    for rig in sorted(rigs_dir.glob("*.md")):
        try:
            data = parse_rig(rig.read_text(encoding="utf-8"))
        except OSError:
            continue
        artist = (data.get("artist") or "").strip()
        title = (data.get("song") or "").strip()
        if artist and title:
            songs.append((rig, artist, title))
    return songs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Resumable grounded rig batch.")
    p.add_argument("--rigs-dir", type=Path, default=None)
    p.add_argument("--facts-db", type=Path, default=FACTS_DB)
    p.add_argument("--state", type=Path, default=STATE_FILE)
    p.add_argument("--provider", default=None, help="Override AI provider (e.g. ollama, codex).")
    p.add_argument("--limit", type=int, default=0, help="Process at most N pending songs.")
    p.add_argument("--only-grounded", action="store_true", help="Skip songs without verified facts.")
    p.add_argument("--acquire", action="store_true", help="Fetch missing facts via the local web agent.")
    p.add_argument("--searxng", default=None, help="SearXNG base URL for --acquire (e.g. http://localhost:8888).")
    p.add_argument("--refresh", action="store_true", help="Ignore checkpoint and redo everything.")
    p.add_argument("--dry-run", action="store_true", help="Plan only; write nothing.")
    p.add_argument("--timeout", type=int, default=None)
    args = p.parse_args(argv)

    rigs_dir = args.rigs_dir or find_rigs_dir(REPO / "partitions")
    if not rigs_dir or not rigs_dir.is_dir():
        print(f"[error] rigs directory not found: {rigs_dir}", file=sys.stderr)
        return 2

    facts_provider = JsonFactsProvider(args.facts_db)
    web_provider = None
    if args.acquire:
        from fretwise.facts_web_agent import LocalWebFactsProvider
        web_provider = LocalWebFactsProvider(searxng_url=args.searxng)

    service = SongRigGenerationService(provider=args.provider, timeout=args.timeout)
    state = {"version": 1, "done": {}} if args.refresh else load_state(args.state)
    done: dict = state.setdefault("done", {})

    songs = song_list(rigs_dir)
    pending = [s for s in songs if facts_key(s[1], s[2]) not in done]
    print(f"[plan] {len(songs)} fiches, {len(songs) - len(pending)} déjà faites, "
          f"{len(pending)} à traiter. rigs_dir={rigs_dir}")

    signal.signal(signal.SIGINT, _handle_sigint)
    processed = 0
    counts = {"grounded": 0, "ungrounded": 0, "skipped": 0, "failed": 0}

    for rig_path, artist, title in pending:
        if _stop or (args.limit and processed >= args.limit):
            break
        key = facts_key(artist, title)
        facts = facts_provider.get_facts(artist, title)
        if facts is None and web_provider is not None:
            try:
                facts = web_provider.get_facts(artist, title)
                if facts is not None:
                    facts_provider.upsert(facts)  # cache for next time
            except Exception as exc:  # noqa: BLE001
                print(f"  [warn] acquisition échouée {artist} - {title}: {exc}")
        if facts is None and args.only_grounded:
            counts["skipped"] += 1
            continue

        t0 = time.time()
        try:
            if args.dry_run:
                tag = "GROUNDED" if facts else "ungrounded"
                print(f"  [dry] {tag:<9} {artist} - {title}")
                processed += 1
                continue
            res = generate_grounded_rig(service, artist, title, facts=facts)
        except RigGenerationError as exc:
            counts["failed"] += 1
            done[key] = {"status": "failed", "error": str(exc)[:200], "ts": int(time.time())}
            print(f"  [fail] {artist} - {title}: {exc}")
            save_state(args.state, state)
            continue

        # Write the .md (back up the original once).
        backup = rig_path.with_name(rig_path.name + ".bak")
        if rig_path.is_file() and not backup.exists():
            backup.write_text(rig_path.read_text(encoding="utf-8"), encoding="utf-8")
        md = rig_view_to_markdown(res.view, generator="pipeline ancré (FretWise)",
                                  date=date.today().strftime("%d-%m-%Y"))
        rig_path.write_text(md, encoding="utf-8")

        counts["grounded" if res.grounded else "ungrounded"] += 1
        done[key] = {"status": "done", "grounded": res.grounded,
                     "reliability": res.reliability, "flags": list(res.flags),
                     "dur_s": round(time.time() - t0, 1), "ts": int(time.time())}
        processed += 1
        flag_s = f" ⚠ {len(res.flags)} flag(s)" if res.flags else ""
        print(f"  [ok] {'G' if res.grounded else '·'} {res.reliability} "
              f"{artist} - {title} ({done[key]['dur_s']}s){flag_s}")
        save_state(args.state, state)

    save_state(args.state, state)
    print(f"\n[done] traités={processed} | ancrés={counts['grounded']} "
          f"non-ancrés={counts['ungrounded']} sautés={counts['skipped']} échecs={counts['failed']}")
    print(f"[state] {args.state} — relancer la commande reprendra les morceaux restants.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
