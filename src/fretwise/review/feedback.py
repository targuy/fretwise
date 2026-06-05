"""Persistence for fingering-review feedback.

User choices are stored two ways:

* a per-song sidecar ``{stem}.feedback.json`` (the authoritative list of choices
  for that song, also consumed to re-bias / hard-lock future solves), and
* a global append-only ``feedback_corpus.jsonl`` (one record per choice, in a
  retrain-ready shape aligned with :func:`fretwise.ml.extract_transition_features`).

Both live under a ``.fretwise_feedback`` directory inside the score root so they
travel with the library. The :class:`fretwise.storage.StorageBackend` interface
only accepts score-file names, so persistence here works on a plain filesystem
directory resolved from the backend's ``local_root``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fretwise.config import ConfigNode, config
from fretwise.models import Finger, FingeringState

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"


def _as_int(v: object) -> int:
    """Coerce a JSON scalar to int (mypy-friendly)."""
    if isinstance(v, (bool, int, float, str)):
        return int(v)
    raise TypeError(f"expected int-like, got {type(v).__name__}")


def _as_float(v: object) -> float:
    """Coerce a JSON scalar to float (mypy-friendly)."""
    if isinstance(v, (bool, int, float, str)):
        return float(v)
    raise TypeError(f"expected float-like, got {type(v).__name__}")


@dataclass(frozen=True)
class FeedbackRecord:
    """One user feedback event — retrain-ready and replayable for re-bias."""

    song_stem: str
    measure_index: int
    onset: float
    severity: str
    chosen: list[dict[str, object]]
    rejected: list[dict[str, object]]
    created_at: str = ""
    user_id: str = "local"
    song_hash: str = ""
    track_id: int | None = None
    reasons: list[str] = field(default_factory=list)
    context: dict[str, object] = field(default_factory=dict)
    alternatives_offered: list[dict[str, object]] = field(default_factory=list)
    features_chosen: dict[str, float] = field(default_factory=dict)
    features_rejected: dict[str, float] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable mapping of the record."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> FeedbackRecord:
        """Build a record from a parsed JSON mapping (unknown keys ignored)."""
        fields = {
            "song_stem", "measure_index", "onset", "severity", "chosen",
            "rejected", "created_at", "user_id", "song_hash", "track_id",
            "reasons", "context", "alternatives_offered", "features_chosen",
            "features_rejected", "schema_version",
        }
        return cls(**{k: v for k, v in data.items() if k in fields})  # type: ignore[arg-type]


@dataclass(frozen=True)
class SongFeedback:
    """All recorded feedback for a single song."""

    stem: str
    records: list[FeedbackRecord]

    def __bool__(self) -> bool:
        return bool(self.records)

    def locks(self) -> dict[tuple[float, int, int | None], FingeringState]:
        """Return per-note hard locks keyed by ``(onset, pitch, voice_hint)``.

        Later records win, so a re-corrected note reflects the newest choice.
        Only chosen entries carrying ``onset`` and ``pitch`` produce a lock.
        """
        out: dict[tuple[float, int, int | None], FingeringState] = {}
        for rec in self.records:
            for f in rec.chosen:
                onset = f.get("onset")
                pitch = f.get("pitch")
                if onset is None or pitch is None:
                    continue
                voice = f.get("voice_hint")
                key = (
                    round(_as_float(onset), 6),
                    _as_int(pitch),
                    _as_int(voice) if voice is not None else None,
                )
                out[key] = FingeringState(
                    string_num=_as_int(f["string"]),
                    fret=_as_int(f["fret"]),
                    finger=Finger(str(f["finger"])),
                    hand_position=_as_int(f["hand_position"]),
                )
        return out

    def preferred_signatures(self) -> set[tuple[int, int, str]]:
        """Return ``(string, fret, finger)`` triples the user preferred."""
        return _signatures(rec.chosen for rec in self.records)

    def rejected_signatures(self) -> set[tuple[int, int, str]]:
        """Return ``(string, fret, finger)`` triples the user rejected."""
        return _signatures(rec.rejected for rec in self.records)


def _signatures(
    groups: Iterable[list[dict[str, object]]],
) -> set[tuple[int, int, str]]:
    out: set[tuple[int, int, str]] = set()
    for group in groups:
        for f in group:
            try:
                out.add((_as_int(f["string"]), _as_int(f["fret"]), str(f["finger"])))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def feedback_dir(root: Path | None, *, cfg: ConfigNode | None = None) -> Path:
    """Resolve (and create) the feedback directory under the score ``root``.

    Args:
        root: Score-library root (e.g. ``storage.local_root``). When ``None``
            the configured partitions directory is used as a fallback.
        cfg: ``config().review`` node; loaded from defaults when ``None``.

    Returns:
        The ``.fretwise_feedback`` directory path (created if missing).
    """
    review_cfg = cfg if cfg is not None else config().review
    base = Path(root) if root is not None else Path.cwd() / "partitions"
    out = base / str(review_cfg.bias.dir_name)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _sidecar_path(base_dir: Path, stem: str) -> Path:
    safe = stem.replace("/", "_").replace("\\", "_")
    return base_dir / f"{safe}.feedback.json"


def load_song_feedback(base_dir: Path, stem: str) -> SongFeedback:
    """Load all feedback recorded for ``stem`` (empty when none exists)."""
    path = _sidecar_path(base_dir, stem)
    if not path.exists():
        return SongFeedback(stem=stem, records=[])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read feedback sidecar %s: %s", path, exc)
        return SongFeedback(stem=stem, records=[])
    records = [FeedbackRecord.from_dict(d) for d in raw.get("records", [])]
    return SongFeedback(stem=stem, records=records)


def save_choice(base_dir: Path, record: FeedbackRecord) -> None:
    """Append ``record`` to the per-song sidecar (creating it if needed)."""
    existing = load_song_feedback(base_dir, record.song_stem)
    records = [*existing.records, record]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "song_stem": record.song_stem,
        "records": [r.to_dict() for r in records],
    }
    path = _sidecar_path(base_dir, record.song_stem)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_corpus(
    base_dir: Path, record: FeedbackRecord, *, cfg: ConfigNode | None = None
) -> None:
    """Append ``record`` as one JSON line to the global retrain corpus."""
    review_cfg = cfg if cfg is not None else config().review
    path = base_dir / str(review_cfg.bias.corpus_name)
    line = json.dumps(record.to_dict(), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
