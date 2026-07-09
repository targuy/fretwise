#!/usr/bin/env python3
"""Convert verbose SongsGear/Fretwise sheets to a compact render format.

The current production JSON keeps the full generation history plus a stable
``fretwiseExport`` object. Fretwise only needs the final renderable sheet, the
Claude-enriched guitar research, and a small audit trail. This tool writes those
compact v2 sheets to a separate directory by default so the original files stay
untouched.

Usage:
    python -m fretwise.gears.production.tools.compact_fretwise_gears
    python -m fretwise.gears.production.tools.compact_fretwise_gears \
        --input-dir ... --output-dir ... --pretty

Defaults to ``<repo>/data/gears`` (override with ``--input-dir`` or the
``FRETWISE_GEARS_DIR`` environment variable).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from fretwise.gears.production.paths import default_gears_dir

COMPACT_SCHEMA_VERSION = "songsgear.fretwise.gear.v2"
REMOVED_HISTORY_KEYS = {
    "musicDraft",
    "openaiJudge",
    "claudeFallback",
    "generated",
    "timings",
    "fretwiseExport",
}
GENERIC_GUITAR_VALUES = {
    "default electric guitar",
    "electric guitar",
    "guitare electrique generique",
    "guitare électrique générique",
}


def _clean(value: Any) -> Any:
    """Recursively remove empty containers/strings while keeping False and 0."""
    if isinstance(value, dict):
        out = {key: _clean(item) for key, item in value.items()}
        return {
            key: item
            for key, item in out.items()
            if item is not None and item != "" and item != [] and item != {}
        }
    if isinstance(value, list):
        return [item for item in (_clean(item) for item in value) if item not in (None, "", [], {})]
    return value


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    if not text:
        return []
    parts = re.split(r"\s*/\s*|\s+;\s+", text)
    return [part.strip() for part in parts if part.strip()]


def _meaningful_guitar(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in GENERIC_GUITAR_VALUES:
        return None
    return text


def _source_from(doc: dict[str, Any], export: dict[str, Any]) -> dict[str, Any]:
    source = export.get("source") if isinstance(export.get("source"), dict) else {}
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return {
        "workflow": source.get("workflow") or metadata.get("workflow"),
        "sourceIndex": source.get("sourceIndex")
        if source.get("sourceIndex") is not None
        else metadata.get("sourceIndex"),
        "models": source.get("models") or metadata.get("models"),
        "finalVerdictSource": source.get("finalVerdictSource")
        or metadata.get("finalVerdictSource"),
        "openaiAction": source.get("openaiAction") or metadata.get("openaiAction"),
        "fallbacks": {
            "gp180": bool(
                source.get("usedLocalGp180Fallback") or metadata.get("usedLocalGp180Fallback")
            ),
            "improvements": bool(
                source.get("usedLocalImprovementsFallback")
                or metadata.get("usedLocalImprovementsFallback")
            ),
        },
    }


def _guitar_credits(doc: dict[str, Any], export: dict[str, Any]) -> dict[str, Any]:
    research = export.get("originalGearResearch")
    if not isinstance(research, dict):
        research = (
            doc.get("originalGearResearch")
            if isinstance(doc.get("originalGearResearch"), dict)
            else {}
        )
    guitarist_text = research.get("guitarist")
    model_text = research.get("guitar_model")
    return {
        "guitaristsText": guitarist_text,
        "guitarists": _as_list(guitarist_text),
        "type": research.get("guitar_type"),
        "modelsText": model_text,
        "models": _as_list(model_text),
        "confidence": research.get("confidence"),
        "evidence": research.get("evidence_basis"),
        "notes": research.get("notes"),
        "source": research.get("source"),
    }


def compact_sheet(doc: dict[str, Any], *, source_file: str | None = None) -> dict[str, Any]:
    """Return a compact v2 sheet preserving render-relevant information."""
    export = doc.get("fretwiseExport") if isinstance(doc.get("fretwiseExport"), dict) else doc
    song = export.get("song") if isinstance(export.get("song"), dict) else doc.get("song", {})
    rig = export.get("rig") if isinstance(export.get("rig"), dict) else {}
    verdict = export.get("musicalVerdict") if isinstance(export.get("musicalVerdict"), dict) else {}
    context = export.get("musicalContext") if isinstance(export.get("musicalContext"), dict) else {}
    improvements = (
        export.get("improvements") if isinstance(export.get("improvements"), dict) else {}
    )
    validation = (
        export.get("validation")
        if isinstance(export.get("validation"), dict)
        else doc.get("validation", {})
    )
    genre = (
        doc.get("genreClassification") if isinstance(doc.get("genreClassification"), dict) else {}
    )

    primary_genre = genre.get("genre") or context.get("primaryGenre") or song.get("genre")
    subgenres = genre.get("subgenres") or context.get("styleTags") or []
    source = _source_from(doc, export)
    if source_file:
        source["sourceFile"] = source_file

    compact = {
        "schemaVersion": COMPACT_SCHEMA_VERSION,
        "id": Path(source_file).stem if source_file else None,
        "song": {
            "artist": song.get("artist"),
            "title": song.get("title"),
            "album": song.get("album"),
            "year": song.get("year"),
            "genre": primary_genre,
            "subgenres": subgenres,
            "genreConfidence": genre.get("confidence") or context.get("confidence"),
        },
        "credits": {
            "guitar": _guitar_credits(doc, export),
        },
        "tone": {
            "target": verdict.get("targetTone") or context.get("targetTone"),
            "profile": rig.get("toneProfile"),
            "summary": rig.get("signalChainSummary"),
            "mustHave": verdict.get("mustHave") or [],
            "avoid": verdict.get("avoid") or [],
            "gearClues": verdict.get("gearClues") or [],
            "corrections": verdict.get("corrections") or [],
            "confidence": verdict.get("confidence")
            or rig.get("confidence")
            or context.get("confidence"),
            "needsReview": bool(rig.get("needsReview") or verdict.get("needsManualReview")),
        },
        "rig": {
            "name": rig.get("rigName"),
            "confidence": rig.get("confidence"),
            "equipment": rig.get("equipment"),
            "recommendedGuitar": _meaningful_guitar(rig.get("guitar")),
            "output": rig.get("output"),
            "blocks": rig.get("blocks") or [],
        },
        "improvements": improvements,
        "audit": {
            **source,
            "validation": validation,
        },
    }
    return _clean(compact)


def convert_dir(
    input_dir: Path, output_dir: Path, *, pattern: str, pretty: bool, dry_run: bool
) -> dict[str, Any]:
    paths = sorted(input_dir.glob(pattern))
    counts = {"seen": 0, "written": 0, "failed": 0}
    failures: list[dict[str, str]] = []
    before_bytes = after_bytes = 0
    indent = 2 if pretty else None
    separators = None if pretty else (",", ":")

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    for path in paths:
        counts["seen"] += 1
        before_bytes += path.stat().st_size
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            compact = compact_sheet(doc, source_file=path.name)
            payload = json.dumps(compact, ensure_ascii=False, indent=indent, separators=separators)
            if pretty:
                payload += "\n"
            after_bytes += len(payload.encode("utf-8"))
            if not dry_run:
                (output_dir / path.name).write_text(payload, encoding="utf-8")
            counts["written"] += 1
        except Exception as exc:  # pragma: no cover - exercised by CLI failures.
            counts["failed"] += 1
            failures.append({"path": str(path), "error": str(exc)})

    reduction = 0.0 if before_bytes == 0 else 1.0 - (after_bytes / before_bytes)
    return {
        "inputDir": str(input_dir),
        "outputDir": str(output_dir),
        "pattern": pattern,
        "pretty": pretty,
        "dryRun": dry_run,
        "counts": counts,
        "bytesBefore": before_bytes,
        "bytesAfter": after_bytes,
        "reductionPercent": round(reduction * 100, 2),
        "removedHistoryKeys": sorted(REMOVED_HISTORY_KEYS),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        default=str(default_gears_dir()),
        help="Verbose sheet directory (default: <repo>/data/gears, env FRETWISE_GEARS_DIR).",
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--pattern", default="*.json")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Write indented JSON instead of compact minified JSON.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else input_dir.with_name(input_dir.name + "_compact_v2")
    )
    summary = convert_dir(
        input_dir, output_dir, pattern=args.pattern, pretty=args.pretty, dry_run=args.dry_run
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["counts"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
