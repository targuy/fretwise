"""Local open-source web-research agent that produces verified :class:`SongFacts`.

100% local / no cloud API, no API key:

  * SEARCH  -> DuckDuckGo HTML endpoint (keyless).
  * FETCH   -> reliable-domain pages, stripped to text.
  * EXTRACT -> a local Ollama model (gemma4) reads the fetched source text and
               emits palette-constrained facts (Ollama ``format`` = JSON schema).

The model READS the sources instead of recalling from memory, which is what makes
a small local model usable for facts. Its judgment is still weaker than a frontier
model, so the extracted reliability is graded honestly (A..D) by completeness.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from collections.abc import Sequence

from fretwise.rig_pipeline import SongFacts

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FretWise-FactsAgent/1.0"
_RELIABLE = (
    "guitarworld.com", "groundguitar.com", "equipboard.com", "premierguitar.com",
    "guitar.com", "musicradar.com", "soundonsound.com", "ultimate-guitar.com",
    "songsterr.com", "wikipedia.org", "guitarchalk.com", "killerrig.com",
    "musicstrive.com", "riffhard.com", "tdpri.com", "gearnews.com", "rigtone.com",
    "tunedstrings.com", "studentofguitar.com", "andertons.co.uk", "mixdownmag.com.au",
)

# Ollama extraction schema: palette-constrained enums so the model can only emit
# valid GP-180 tokens. Tuning/capo/notes stay free text; reliability is graded.
_AMP = ["Off", "Tweedy", "Bassman", "Foxy30", "UK 45", "UK 50", "UK 900", "Solo100",
        "Mesa Dual Recto", "Tremoverb", "ENGL Savage", "ENGL Gigmaster"]
_DST = ["Off", "Dist+ (MXR)", "DS1", "Rat", "Big Muff", "Fuzz Face"]
_PRE = ["Off", "Comp", "OD9 TS808", "OD9 TS9", "Klon Centaur"]
_MOD = ["Off", "CE2 Chorus", "CE3 Chorus", "Tremolo", "MicroPitch", "Shimmer"]
_DLY = ["Off", "DD3", "Ping Pong", "Carbon Copy", "Sweep Echo"]
_RVB = ["Off", "Room", "Plate", "Spring", "Hall", "Shimmer"]
_NR = ["Off", "Gate 1"]
_GUITAR = ["Gibson Les Paul", "Gibson SG", "Fender Telecaster",
           "Fender Stratocaster", "Superstrat"]

_FACTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tuning", "capo", "guitar", "amp", "pre", "dst", "nr", "mod",
                 "dly", "rvb", "reliability"],
    "properties": {
        "tuning": {"type": "string"},
        "capo": {"type": "string"},
        "guitar": {"type": "string", "enum": _GUITAR},
        "amp": {"type": "string", "enum": _AMP},
        "pre": {"type": "string", "enum": _PRE},
        "dst": {"type": "string", "enum": _DST},
        "nr": {"type": "string", "enum": _NR},
        "mod": {"type": "string", "enum": _MOD},
        "dly": {"type": "string", "enum": _DLY},
        "rvb": {"type": "string", "enum": _RVB},
        "reliability": {"type": "string", "enum": ["A", "B", "C", "D"]},
        "notes": {"type": "string"},
    },
}

_EXTRACT_SYS = (
    "Tu extrais des faits d'equipement guitare a partir d'extraits de sources web. "
    "Regles STRICTES: (1) n'utilise QUE des faits presents dans les sources; "
    "(2) accordage = version STUDIO; (3) si la distorsion vient de l'AMPLI, mets dst=Off "
    "(une pedale TS/boost n'est PAS une disto); (4) mappe l'ampli/effets reels vers le "
    "preset GP-180 le plus proche de la palette imposee (enums); (5) si une info est "
    "absente des sources, mets Off (et 'inconnu' pour l'accordage). Reponds en JSON strict."
)


class WebAgentError(Exception):
    """Raised when search/fetch fails irrecoverably."""


def _http_get(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def searxng_search(query: str, base_url: str, *, limit: int = 6, timeout: int = 12) -> list[str]:
    """Return result URLs from a self-hosted SearXNG instance (JSON API).

    SearXNG is the standard open-source, keyless search backend (same one used by
    Perplexica / gpt-researcher). Run one locally, e.g.::

        docker run -d -p 8888:8080 -e "SEARXNG_BASE_URL=http://localhost:8888/" \\
            searxng/searxng

    then point the provider at ``http://localhost:8888``. Enable the JSON format in
    the instance ``settings.yml`` (``search.formats: [html, json]``).
    """
    url = base_url.rstrip("/") + "/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "safesearch": "0"}
    )
    try:
        body = _http_get(url, timeout=timeout)
        data = json.loads(body)
    except Exception as exc:  # noqa: BLE001 - search is best-effort
        raise WebAgentError(f"searxng search failed: {exc}") from exc
    urls: list[str] = []
    for item in data.get("results", []):
        u = item.get("url")
        if isinstance(u, str) and u not in urls:
            urls.append(u)
        if len(urls) >= limit * 2:
            break
    return urls


def wikipedia_extract(title: str, *, timeout: int = 12) -> str:
    """Return the plain-text lead/extract of the best-matching Wikipedia article.

    Keyless and not bot-blocked (official API), used as a last-resort source when
    no other reliable page is reachable. Coverage of gear/tuning is thin, so this
    only ever yields a partial (low-reliability) fact sheet.
    """
    api = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "prop": "extracts", "explaintext": "1", "redirects": "1",
        "format": "json", "titles": title,
    })
    try:
        data = json.loads(_http_get(api, timeout=timeout))
        pages = data["query"]["pages"]
        return next(iter(pages.values())).get("extract", "")[:2600]
    except Exception:  # noqa: BLE001
        return ""


def ddg_search(query: str, *, limit: int = 6, timeout: int = 12) -> list[str]:
    """Return result URLs from the keyless DuckDuckGo HTML endpoint.

    Note: many automated environments are served an anti-bot shell by DuckDuckGo
    (no results). Prefer a self-hosted SearXNG via :func:`searxng_search` for a
    reliable keyless backend.
    """
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        body = _http_get(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - search is best-effort
        raise WebAgentError(f"search failed: {exc}") from exc
    urls: list[str] = []
    for m in re.finditer(r'href="(//duckduckgo\.com/l/\?uddg=[^"]+)"', body):
        href = "https:" + html.unescape(m.group(1))
        q = urllib.parse.urlparse(href).query
        target = urllib.parse.parse_qs(q).get("uddg", [""])[0]
        if target and target not in urls:
            urls.append(target)
        if len(urls) >= limit * 2:
            break
    # Direct (non-redirect) result links as a fallback.
    if not urls:
        for m in re.finditer(r'class="result__a"[^>]*href="(https?://[^"]+)"', body):
            if m.group(1) not in urls:
                urls.append(m.group(1))
    return urls[: limit * 2]


def _reliable(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(dom in host for dom in _RELIABLE)


def _html_to_text(page: str, *, max_chars: int = 2600) -> str:
    page = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html.unescape(page)
    page = re.sub(r"\s+", " ", page).strip()
    return page[:max_chars]


def _ollama_extract(model: str, base_url: str, artist: str, title: str,
                    sources_text: str, timeout: int) -> dict:
    payload = {
        "model": model, "stream": False, "think": False, "format": _FACTS_SCHEMA,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": _EXTRACT_SYS},
            {"role": "user", "content": (
                f"Morceau: {artist} - {title}\n\n=== SOURCES WEB ===\n{sources_text}\n\n"
                "Extrais les faits d'equipement (accordage studio, capo, guitare, ampli, "
                "pre/boost, distorsion, noise gate, modulation, delay, reverb) mappes a la "
                "palette GP-180. JSON strict uniquement."
            )},
        ],
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return json.loads(body.get("message", {}).get("content", "{}"))


def _grade(data: dict, n_sources: int) -> str:
    """Honest reliability grade from completeness + source coverage."""
    tuning_ok = bool(data.get("tuning")) and "inconnu" not in str(data.get("tuning")).lower()
    amp_ok = str(data.get("amp", "Off")).lower() != "off"
    guitar_ok = bool(data.get("guitar"))
    found = sum((tuning_ok, amp_ok, guitar_ok))
    if found == 3 and n_sources >= 2:
        return "B"  # grounded but model judgment < frontier -> never auto-"A"
    if found >= 2:
        return "C"
    return "D"


class LocalWebFactsProvider:
    """A keyless, fully-local web-research :class:`FactsProvider`."""

    def __init__(self, *, model: str = "gemma4",
                 base_url: str = "http://127.0.0.1:11434",
                 searxng_url: str | None = None,
                 max_pages: int = 3, timeout: int = 60) -> None:
        self.model = model
        self.base_url = base_url
        self.searxng_url = searxng_url
        self.max_pages = max_pages
        self.timeout = timeout

    def _search(self, query: str) -> list[str]:
        if self.searxng_url:
            try:
                return searxng_search(query, self.searxng_url, limit=5)
            except WebAgentError:
                return []
        try:
            return ddg_search(query, limit=5)
        except WebAgentError:
            return []

    def _gather_sources(self, artist: str, title: str) -> tuple[str, list[str]]:
        queries = [
            f'{artist} "{title}" guitar tuning',
            f'{artist} "{title}" guitar amp gear rig pedals',
        ]
        seen: list[str] = []
        for q in queries:
            for u in self._search(q):
                if _reliable(u) and u not in seen:
                    seen.append(u)
        texts: list[str] = []
        used: list[str] = []
        for u in seen:
            if len(used) >= self.max_pages:
                break
            try:
                txt = _html_to_text(_http_get(u))
            except Exception:  # noqa: BLE001 - skip unreachable pages
                continue
            if len(txt) > 200:
                texts.append(f"[{urllib.parse.urlparse(u).netloc}] {txt}")
                used.append(u)
        # Last-resort keyless source when search returned nothing reachable.
        if not texts:
            wiki = wikipedia_extract(f"{title}")
            if len(wiki) > 200:
                texts.append(f"[en.wikipedia.org] {wiki}")
                used.append(f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}")
        return "\n\n".join(texts), used

    def get_facts(self, artist: str, title: str) -> SongFacts | None:
        sources_text, used = self._gather_sources(artist, title)
        if not sources_text:
            return None
        try:
            data = _ollama_extract(self.model, self.base_url, artist, title,
                                   sources_text, self.timeout)
        except Exception as exc:  # noqa: BLE001
            raise WebAgentError(f"extraction failed: {exc}") from exc
        reliability = _grade(data, len(used))
        return SongFacts(
            artist=artist, title=title,
            tuning=str(data.get("tuning") or "inconnu"),
            capo=str(data.get("capo") or "non"),
            guitar=str(data.get("guitar") or ""),
            amp=str(data.get("amp") or "Off"),
            pre=str(data.get("pre") or "Off"),
            dst=str(data.get("dst") or "Off"),
            nr=str(data.get("nr") or "Off"),
            mod=str(data.get("mod") or "Off"),
            dly=str(data.get("dly") or "Off"),
            rvb=str(data.get("rvb") or "Off"),
            reliability=reliability,
            notes=str(data.get("notes") or ""),
            sources=tuple(used),
        )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Local web facts agent (DDG + Ollama).")
    p.add_argument("artist")
    p.add_argument("title")
    p.add_argument("--model", default="gemma4")
    args = p.parse_args(argv)
    facts = LocalWebFactsProvider(model=args.model).get_facts(args.artist, args.title)
    print(json.dumps(facts.to_json() if facts else {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
