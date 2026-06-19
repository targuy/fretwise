#!/usr/bin/env python3
"""Seed data/song_facts.json from the MVP-verified ground truth (13 songs).

Uses the real JsonFactsProvider.upsert path, so this also smoke-tests the engine.
The 10 from factsheets.json carry their GP-180 mapping; the 3 from the first MVP
are added explicitly. All are graded B (frontier-grounded, validated to the ear
not yet done -> never auto-A).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fretwise.rig_pipeline import JsonFactsProvider, SongFacts  # noqa: E402

FACTS_DB = REPO / "data" / "song_facts.json"
FACTSHEETS = REPO / "exports" / "mvp_grounding" / "factsheets.json"

# The 3 songs verified in the first MVP (web-researched, mapped to palette).
MVP1 = [
    SongFacts(artist="Metallica", title="Master of Puppets", tuning="Mi standard (E standard, studio)",
              capo="non", guitar="Gibson SG", amp="Mesa Dual Recto", dst="Off", nr="Gate 1",
              mod="Off", dly="Off", rvb="Off", reliability="B",
              notes="Disto = ampli (Mesa Mark IIC+/Marshall JCM800), mediums scoopes, downpicking serre.",
              sources=("https://mixdownmag.com.au/features/how-to-get-the-metallica-master-of-puppets-tone/",
                       "https://www.tunedstrings.com/tutorials/metallica-tuning-guide")),
    SongFacts(artist="Nirvana", title="Smells Like Teen Spirit", tuning="Demi-ton plus bas (Eb)",
              capo="non", guitar="Superstrat", amp="Mesa Dual Recto", dst="DS1", nr="Off",
              mod="CE2 Chorus", dly="Off", rvb="Off", reliability="B",
              notes="Clean+chorus (Small Clone) sur couplets, DS-1 sur refrains; preampli Mesa Studio + cab Marshall.",
              sources=("https://www.guitarworld.com/features/the-secrets-behind-kurt-cobains-guitar-tone-on-nirvanas-smells-like-teen-spirit",)),
    SongFacts(artist="Bob Marley", title="Three Little Birds", tuning="Mi standard (E standard)",
              capo="non", guitar="Fender Stratocaster", amp="Tweedy", dst="Off", nr="Off",
              mod="Off", dly="Off", rvb="Spring", reliability="B",
              notes="Clean reggae skank, aucune disto, reverb a ressort; Fender Twin clean.",
              sources=("https://www.guitarworld.com/lessons/bob-marley-reggae-rhythm-guitar",)),
]


def main() -> int:
    provider = JsonFactsProvider(FACTS_DB)
    sheets = json.loads(FACTSHEETS.read_text(encoding="utf-8"))
    for fs in sheets:
        gt = fs["gt"]
        provider.upsert(SongFacts(
            artist=fs["artist"], title=fs["title"], tuning=gt["tuning"], capo=gt["capo"],
            guitar=gt["guitar"].split("+")[0].strip(), amp=gt["amp"], dst=gt["dst"], nr=gt["nr"],
            mod=gt["mod"], dly=gt["dly"], rvb=gt["rvb"], reliability="B",
            notes="MVP-verified (frontier web research).",
        ))
    for f in MVP1:
        provider.upsert(f)
    print(f"Seeded {len(sheets) + len(MVP1)} song facts -> {FACTS_DB}")
    # Round-trip check
    reloaded = JsonFactsProvider(FACTS_DB)
    sample = reloaded.get_facts("Foo Fighters", "Everlong")
    print("Round-trip Everlong:", sample.tuning if sample else "MISSING", "|", sample.amp if sample else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
