#!/usr/bin/env python3
"""FretWise — worker d'acquisition de sources brutes (NAS, stdlib-only, sans ollama).

Boucle sur songs.tsv et, pour chaque morceau absent de song_raw_sources.json :
  SearXNG → filtre sources fiables → fetch pages → sauvegarde texte brut (atomique).

Le PC lit ensuite song_raw_sources.json et appelle ollama localement via
tools/extract_facts.py pour produire song_facts.json.

Idempotent : un redémarrage saute les morceaux déjà dans la base.
"""
from __future__ import annotations

import html
import json
import os
import re
import signal
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
SONGS_TSV = os.environ.get("SONGS_TSV", "/data/songs.tsv")
RAW_DB = os.environ.get("RAW_DB", "/data/song_raw_sources.json")
SLEEP_BETWEEN = float(os.environ.get("SLEEP_BETWEEN", "2"))
RESCAN_SECONDS = float(os.environ.get("RESCAN_SECONDS", "3600"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "4"))
_UA = "Mozilla/5.0 FretWise-FactsWorker/1.0"

_RELIABLE = (
    # gear / rig
    "guitarworld.com", "groundguitar.com", "equipboard.com", "premierguitar.com",
    "guitar.com", "musicradar.com", "soundonsound.com", "ultimate-guitar.com",
    "guitarchalk.com", "killerrig.com", "musicstrive.com", "riffhard.com",
    "tdpri.com", "gearnews.com", "rigtone.com", "tunedstrings.com",
    "studentofguitar.com", "andertons.co.uk", "mixdownmag.com.au",
    "whoplayswhat.com", "gearaficionado.com", "loudwire.com", "loudersound.com",
    "vintageguitar.com", "guitarplayer.com", "thetonekingdom.com",
    # tuning / tabs
    "songsterr.com", "e-chords.com", "chordie.com", "guitartabs.cc",
    "azchords.com", "chordify.net", "justinguitar.com",
    # encyclopédique
    "wikipedia.org", "en.wikipedia.org", "fr.wikipedia.org",
    # presse musicale
    "rollingstone.com", "nme.com", "allmusic.com", "discogs.com",
    # sources FR (artistes francophones)
    "guitariste.com", "accord-guitare.com", "lacoursdeguitare.com",
)

_stop = False


def _on_term(*_a: object) -> None:
    global _stop
    _stop = True
    log("arrêt demandé, fin du morceau courant…")


def log(msg: str) -> None:
    print(f"[facts-worker] {msg}", flush=True)


def _normalize(name: str) -> str:
    name = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")
    name = name.encode("ascii", "ignore").decode("ascii").lower()
    name = name.replace("&", "and").replace("/", "")
    name = re.sub(r"[''',\.!\(\)\?:;\"…_]", "", name)
    name = re.sub(r"[-\s]+", "_", name)
    return re.sub(r"_+", "_", name).strip("_")


def fkey(artist: str, title: str) -> str:
    return f"{_normalize(artist)}::{_normalize(title)}"


def _get(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def search(query: str) -> list[str]:
    url = SEARXNG_URL.rstrip("/") + "/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "safesearch": "0"})
    try:
        data = json.loads(_get(url))
    except Exception as exc:  # noqa: BLE001
        log(f"search KO ({exc})")
        return []
    return [it["url"] for it in data.get("results", []) if isinstance(it.get("url"), str)]


def _text(page: str, n: int = 2600) -> str:
    page = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(page)).strip()[:n]


def gather(artist: str, title: str) -> tuple[list[str], list[str]]:
    """Retourne (texts, urls) — texte brut des pages fiables trouvées."""
    seen: list[str] = []
    queries = [
        f'{artist} "{title}" guitar tuning',
        f'{artist} "{title}" guitar amp gear rig pedals',
        f'{artist} guitar rig amp setup what guitar does use',
        f'{artist} "{title}" tuning drop standard',
    ]
    for q in queries:
        for u in search(q):
            host = urllib.parse.urlparse(u).netloc.lower()
            if any(d in host for d in _RELIABLE) and u not in seen:
                seen.append(u)
    texts, used = [], []
    for u in seen:
        if len(used) >= MAX_PAGES:
            break
        try:
            t = _text(_get(u))
        except Exception:  # noqa: BLE001
            continue
        if len(t) > 200:
            texts.append(f"[{urllib.parse.urlparse(u).netloc}] {t}")
            used.append(u)
    return texts, used


def load_songs() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not os.path.isfile(SONGS_TSV):
        return out
    with open(SONGS_TSV, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            a, t = parts[0].strip(), parts[1].strip()
            if i == 0 and a.lower() in ("artist", "rig_file", "file"):
                continue
            if len(parts) >= 3 and parts[0].startswith("rig_"):
                a, t = parts[1].strip(), parts[2].strip()
            if a and t:
                out.append((a, t))
    return out


def load_db() -> dict[str, dict]:
    if not os.path.isfile(RAW_DB):
        return {}
    try:
        data = json.load(open(RAW_DB, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = data.get("raw_sources", data) if isinstance(data, dict) else data
    return {fkey(e["artist"], e["title"]): e for e in entries
            if isinstance(e, dict) and e.get("artist")}


def save_db(db: dict[str, dict]) -> None:
    tmp = RAW_DB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"raw_sources": list(db.values())}, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, RAW_DB)


def main() -> int:
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    log(f"start | searxng={SEARXNG_URL} raw_db={RAW_DB}")
    while not _stop:
        songs = load_songs()
        db = load_db()
        pending = [(a, t) for a, t in songs if fkey(a, t) not in db]
        log(f"cycle: {len(songs)} morceaux, {len(db)} déjà acquis, {len(pending)} à faire")
        for a, t in pending:
            if _stop:
                break
            texts, urls = gather(a, t)
            if texts:
                db[fkey(a, t)] = {
                    "artist": a, "title": t,
                    "pages": texts,
                    "urls": urls,
                }
                save_db(db)
                log(f"[ok] {a} - {t} ({len(urls)} src)")
            else:
                log(f"[skip] aucune source  {a} - {t}")
            time.sleep(SLEEP_BETWEEN)
        if _stop:
            break
        log(f"passage terminé, re-scan dans {int(RESCAN_SECONDS)}s")
        slept = 0.0
        while slept < RESCAN_SECONDS and not _stop:
            time.sleep(min(5.0, RESCAN_SECONDS - slept))
            slept += 5.0
    log("stop propre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
