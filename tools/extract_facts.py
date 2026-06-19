#!/usr/bin/env python3
"""Extraction des faits musicaux depuis les sources brutes (PC, ollama local).

Lit  : data/song_raw_sources.json  (produit par le NAS via docker/facts-worker)
Écrit: data/song_facts.json        (consommé par tools/rig_batch.py)

Usage :
    pixi run python tools/extract_facts.py
    pixi run python tools/extract_facts.py --raw data/song_raw_sources.json
    pixi run python tools/extract_facts.py --limit 50          # traiter 50 morceaux
    pixi run python tools/extract_facts.py --model gemma4      # changer de modèle

Reprend là où c'était arrêté : les morceaux déjà dans song_facts.json sont sautés.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = ROOT / "data" / "song_raw_sources.json"
DEFAULT_FACTS = ROOT / "data" / "song_facts.json"
DEFAULT_MODEL = "gemma4"
DEFAULT_OLLAMA = "http://localhost:11434"

_AMP = ["Off", "Tweedy", "Bassman", "Foxy30", "UK 45", "UK 50", "UK 900", "Solo100",
        "Mesa Dual Recto", "Tremoverb", "ENGL Savage", "ENGL Gigmaster"]
_DST = ["Off", "Dist+ (MXR)", "DS1", "Rat", "Big Muff", "Fuzz Face"]
_PRE = ["Off", "Comp", "OD9 TS808", "OD9 TS9", "Klon Centaur"]
_MOD = ["Off", "CE2 Chorus", "CE3 Chorus", "Tremolo", "MicroPitch", "Shimmer"]
_DLY = ["Off", "DD3", "Ping Pong", "Carbon Copy", "Sweep Echo"]
_RVB = ["Off", "Room", "Plate", "Spring", "Hall", "Shimmer"]
_NR = ["Off", "Gate 1"]
_GUITAR = ["Gibson Les Paul", "Gibson SG", "Fender Telecaster", "Fender Stratocaster", "Superstrat"]

_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["tuning", "capo", "guitar", "amp", "pre", "dst", "nr", "mod", "dly", "rvb"],
    "properties": {
        "tuning": {"type": "string"}, "capo": {"type": "string"},
        "guitar": {"type": "string", "enum": _GUITAR},
        "amp": {"type": "string", "enum": _AMP},
        "pre": {"type": "string", "enum": _PRE},
        "dst": {"type": "string", "enum": _DST},
        "nr": {"type": "string", "enum": _NR},
        "mod": {"type": "string", "enum": _MOD},
        "dly": {"type": "string", "enum": _DLY},
        "rvb": {"type": "string", "enum": _RVB},
        "notes": {"type": "string"},
    },
}
_SYS = (
    "Tu extrais des faits d'équipement guitare à partir d'extraits de sources web. "
    "Règles : (1) n'utilise QUE des faits présents dans les sources ; "
    "(2) accordage = version STUDIO (pas live) ; "
    "(3) si la disto vient de l'ampli, dst=Off (un boost TS n'est pas une disto) ; "
    "(4) mappe l'ampli/effets réels vers le preset GP-180 le plus proche (enums) ; "
    "(5) info absente → Off (et 'inconnu' pour l'accordage). JSON strict."
)


def _normalize(name: str) -> str:
    name = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")
    name = name.encode("ascii", "ignore").decode("ascii").lower()
    name = name.replace("&", "and").replace("/", "")
    name = re.sub(r"[''',\.!\(\)\?:;\"…_]", "", name)
    name = re.sub(r"[-\s]+", "_", name)
    return re.sub(r"_+", "_", name).strip("_")


def fkey(artist: str, title: str) -> str:
    return f"{_normalize(artist)}::{_normalize(title)}"


def grade(d: dict, n_sources: int) -> str:
    tuning = bool(d.get("tuning")) and "inconnu" not in str(d.get("tuning")).lower()
    amp = str(d.get("amp", "Off")).lower() != "off"
    guitar = bool(d.get("guitar"))
    found = sum((tuning, amp, guitar))
    return "B" if found == 3 and n_sources >= 2 else "C" if found >= 2 else "D"


def ollama_extract(artist: str, title: str, sources: str, model: str, url: str) -> dict:
    prompt = f"Morceau: {artist} - {title}\n\n=== SOURCES ===\n{sources}\n\nJSON strict."
    payload = {
        "model": model, "stream": False, "think": False, "format": _SCHEMA,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": prompt},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        body = json.loads(r.read().decode("utf-8"))
    return json.loads(body.get("message", {}).get("content", "{}"))


def load_raw(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("raw_sources", data) if isinstance(data, dict) else data
    return {fkey(e["artist"], e["title"]): e for e in entries
            if isinstance(e, dict) and e.get("artist")}


def load_facts(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    facts = data.get("facts", data) if isinstance(data, dict) else data
    return {fkey(f["artist"], f["title"]): f for f in facts
            if isinstance(f, dict) and f.get("artist")}


def save_facts(db: dict[str, dict], path: Path) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"facts": list(db.values())}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", default=str(DEFAULT_RAW), help="Chemin vers song_raw_sources.json")
    p.add_argument("--facts", default=str(DEFAULT_FACTS), help="Chemin vers song_facts.json (sortie)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Modèle ollama local (défaut: gemma4)")
    p.add_argument("--ollama", default=DEFAULT_OLLAMA, help="URL ollama (défaut: http://localhost:11434)")
    p.add_argument("--limit", type=int, default=0, help="Limiter à N morceaux (0 = tous)")
    p.add_argument("--dry-run", action="store_true", help="Ne pas écrire, juste afficher")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    raw_path = Path(args.raw)
    facts_path = Path(args.facts)

    raw_db = load_raw(raw_path)
    facts_db = load_facts(facts_path)

    pending = {k: v for k, v in raw_db.items() if k not in facts_db}
    total = len(pending)
    print(f"Sources brutes : {len(raw_db)} | Déjà extraits : {len(facts_db)} | À traiter : {total}")

    if not pending:
        print("Rien à faire.")
        return 0

    done = 0
    for k, entry in pending.items():
        if args.limit and done >= args.limit:
            break
        artist = entry["artist"]
        title = entry["title"]
        sources = "\n\n".join(entry.get("pages", []))
        urls = entry.get("urls", [])
        n_sources = len(urls)

        print(f"[{done+1}/{total}] {artist} - {title} ({n_sources} src) … ", end="", flush=True)
        t0 = time.monotonic()
        try:
            d = ollama_extract(artist, title, sources, args.model, args.ollama)
        except Exception as exc:
            print(f"KO ({exc})")
            continue

        reliability = grade(d, n_sources)
        rec = {
            "artist": artist, "title": title,
            "tuning": str(d.get("tuning") or "inconnu"),
            "capo": str(d.get("capo") or "non"),
            "guitar": str(d.get("guitar") or ""),
            "amp": str(d.get("amp") or "Off"),
            "pre": str(d.get("pre") or "Off"),
            "dst": str(d.get("dst") or "Off"),
            "nr": str(d.get("nr") or "Off"),
            "mod": str(d.get("mod") or "Off"),
            "dly": str(d.get("dly") or "Off"),
            "rvb": str(d.get("rvb") or "Off"),
            "reliability": reliability,
            "notes": str(d.get("notes") or ""),
            "sources": urls,
        }
        dur = time.monotonic() - t0
        print(f"{reliability} ({dur:.1f}s)")

        if not args.dry_run:
            facts_db[k] = rec
            save_facts(facts_db, facts_path)
        done += 1

    print(f"\nTerminé : {done} extraits → {facts_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
