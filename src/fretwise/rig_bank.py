"""Structured Valeton rig bank storage, lookup, and MIDI activation.

This module is deliberately separate from :mod:`fretwise.profile`: the project
spec reserves M6 for the player's biomechanical profile consumed by scoring,
whereas a GP-180 rig bank is performance/library metadata plus device control.
It also leaves the existing Markdown rig sheets untouched; those remain a rich
human-readable view, while this JSON bank is the actionable index.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal, Protocol

from fretwise.rig import _normalize

RIG_BANK_SCHEMA_VERSION = "fretwise_rig_bank_v1"
DEFAULT_RIG_BANK_NAME = "rig_bank.json"

RigBindingScope = Literal["song", "artist", "genre"]
RigSelectionSource = Literal[
    "explicit",
    "song_binding",
    "artist_binding",
    "genre_binding",
    "profile_artist",
    "profile_genre",
    "artist_match",
    "genre_match",
    "tag_match",
    "fallback",
]

_TOKEN_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "de",
        "des",
        "du",
        "en",
        "for",
        "in",
        "la",
        "le",
        "les",
        "of",
        "on",
        "the",
        "to",
        "un",
        "une",
    }
)

_GENRE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("progressive metal", ("progressive metal", "dream theater", "petrucci")),
    ("thrash metal", ("thrash metal", "metallica", "lica")),
    ("industrial metal", ("industrial metal", "rammstein")),
    ("melodic death metal", ("melodic death", "children of bodom", "alexi")),
    ("doom metal", ("doom metal", "sabbath", "iommi")),
    ("metalcore", ("metalcore", "metal core")),
    ("heavy metal", ("heavy metal", "maiden")),
    ("hard rock", ("hard rock", "ac/dc", "gnr", "guns", "van halen", "eddie", "zeppelin")),
    ("classic rock", ("classic rock", "dire straits", "eagles", "queen", "brian may")),
    ("blues rock", ("blues rock", "clapton", "cream", "tweed")),
    ("blues pop", ("blues pop", "john mayer", "mayer")),
    ("progressive rock", ("progressive rock", "pink floyd", "gilmour", "numb")),
    ("psychedelic rock", ("psychedelic rock", "hendrix")),
    ("post-rock", ("post rock", "post-rock")),
    ("pop punk", ("pop punk", "green day")),
    ("ska punk", ("ska punk", "no doubt")),
    ("punk", ("punk",)),
    ("grunge", ("grunge", "nirvana", "cobain")),
    ("new wave", ("new wave",)),
    ("j-rock", ("j rock", "j-rock", "japanese rock")),
    ("art rock", ("art rock", "david bowie", "bowie")),
    ("instrumental rock", ("instrumental rock", "satriani", "vai")),
    ("neoclassical metal", ("neoclassical", "yngwie", "malmsteen")),
    ("fusion", ("fusion", "guthrie govan")),
    ("jazz", ("jazz",)),
    ("funk", ("funk", "funky")),
    ("bluegrass", ("bluegrass",)),
    ("acoustic", ("acoustic", "12-string", "12 strings", "blackbird")),
    ("ambient", ("ambient", "ethereal", "luminous", "shimmer")),
    ("synth", ("synth", "organ")),
    ("bass", ("bass", "slap")),
    ("pop", ("pop",)),
    ("clean", ("clean",)),
    ("effect", ("wah", "filter", "freeze", "vibrato", "trem", "whammy", "harmony")),
)

_GENRE_FAMILIES: dict[str, str] = {
    "rock": "rock",
    "hard": "rock",
    "classic": "rock",
    "progressive": "rock",
    "psychedelic": "rock",
    "instrumental": "rock",
    "art": "rock",
    "j": "rock",
    "grunge": "rock",
    "wave": "rock",
    "punk": "punk",
    "ska": "punk",
    "pop": "pop",
    "metal": "metal",
    "metalcore": "metal",
    "thrash": "metal",
    "industrial": "metal",
    "doom": "metal",
    "death": "metal",
    "neoclassical": "metal",
    "blues": "blues",
    "jazz": "jazz",
    "fusion": "jazz",
    "funk": "funk",
    "bluegrass": "acoustic",
    "acoustic": "acoustic",
    "ambient": "ambient",
    "ethereal": "ambient",
    "synth": "synth",
    "bass": "bass",
    "clean": "clean",
    "effect": "effect",
}


class RigBankError(Exception):
    """Raised when rig-bank data is invalid or cannot be applied."""


@dataclass(frozen=True)
class RigProfile:
    """A Valeton preset slot that FretWise can select.

    Args:
        id: Stable FretWise identifier, independent of the visible preset name.
        name: Human-readable preset name.
        program: GP-180 preset/program number, 0-based (0..199).
        midi_channel: MIDI channel, 1-based (1..16).
        device: Device family identifier. Defaults to ``valeton_gp180``.
        bank_msb: Optional MIDI Bank Select MSB (CC 0), 0..127.
        bank_lsb: Optional MIDI Bank Select LSB (CC 32), 0..127.
        artist: Optional artist this preset is naturally associated with.
        genre: Optional genre this preset is naturally associated with.
        tags: Free tags for search/filtering.
        source: Where the preset came from (manual, device, Valeton Suite, etc.).
        notes: Free-form operator notes.
    """

    id: str
    name: str
    program: int
    midi_channel: int = 1
    device: str = "valeton_gp180"
    bank_msb: int | None = None
    bank_lsb: int | None = None
    artist: str | None = None
    genre: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    source: str = "manual"
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise RigBankError("rig profile id is required")
        if not self.name.strip():
            raise RigBankError("rig profile name is required")
        _validate_midi_range("program", self.program, high=199)
        _validate_midi_range("midi_channel", self.midi_channel, low=1, high=16)
        if self.bank_msb is not None:
            _validate_midi_range("bank_msb", self.bank_msb)
        if self.bank_lsb is not None:
            _validate_midi_range("bank_lsb", self.bank_lsb)

    @property
    def display_program(self) -> int:
        """Return the user-facing 1-based program number."""

        return self.program + 1

    def midi_bytes(self) -> tuple[tuple[int, ...], ...]:
        """Return raw MIDI bytes for selecting this profile.

        The GP-180 public/manual control path is expected to follow the normal
        MIDI convention: optional Bank Select CC messages followed by Program
        Change. The Notion GP-180 reference documents presets 0..199; raw MIDI
        Program Change is 7-bit. The GP-180 manual's MIDI Control Information
        List maps patches 001~128 to ``CC0=0, PC=0~127`` and patches 129~200 to
        ``CC0=1, PC=0~71``. Values above 127 therefore emit Bank Select MSB
        (CC 0) plus ``program % 128`` unless an explicit bank is provided.
        Proprietary SysEx can be added later without changing the bank lookup
        API.
        """

        status_cc = 0xB0 + (self.midi_channel - 1)
        status_pc = 0xC0 + (self.midi_channel - 1)
        messages: list[tuple[int, ...]] = []
        bank_msb = self.bank_msb
        if bank_msb is None and self.bank_lsb is None:
            bank_msb = self.program // 128
        if bank_msb is not None:
            messages.append((status_cc, 0, bank_msb))
        bank_lsb = self.bank_lsb
        if bank_lsb is not None:
            messages.append((status_cc, 32, bank_lsb))
        messages.append((status_pc, self.program % 128))
        return tuple(messages)

    def to_json(self) -> dict[str, object]:
        """Serialize to the rig-bank JSON shape."""

        data: dict[str, object] = {
            "id": self.id,
            "name": self.name,
            "device": self.device,
            "program": self.program,
            "midi_channel": self.midi_channel,
            "tags": list(self.tags),
            "source": self.source,
            "notes": self.notes,
        }
        if self.bank_msb is not None:
            data["bank_msb"] = self.bank_msb
        if self.bank_lsb is not None:
            data["bank_lsb"] = self.bank_lsb
        if self.artist:
            data["artist"] = self.artist
        if self.genre:
            data["genre"] = self.genre
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> RigProfile:
        """Build from one profile object in ``rig_bank.json``."""

        name = _str_field(data, "name")
        artist = _optional_str_field(data, "artist")
        tags = tuple(_str_list_field(data, "tags"))
        notes = _str_field(data, "notes", default="")
        genre = _optional_str_field(data, "genre") or infer_rig_profile_genre(
            name=name,
            artist=artist,
            tags=tags,
            notes=notes,
        )
        return cls(
            id=_str_field(data, "id"),
            name=name,
            device=_str_field(data, "device", default="valeton_gp180"),
            program=_int_field(data, "program"),
            midi_channel=_int_field(data, "midi_channel", default=1),
            bank_msb=_optional_int_field(data, "bank_msb"),
            bank_lsb=_optional_int_field(data, "bank_lsb"),
            artist=artist,
            genre=genre,
            tags=tags,
            source=_str_field(data, "source", default="manual"),
            notes=notes,
        )


@dataclass(frozen=True)
class RigBinding:
    """Association from a song, artist, or genre key to a rig profile."""

    scope: RigBindingScope
    key: str
    profile_id: str

    def __post_init__(self) -> None:
        if self.scope not in ("song", "artist", "genre"):
            raise RigBankError(f"unsupported rig binding scope: {self.scope}")
        if not self.key.strip():
            raise RigBankError("rig binding key is required")
        if not self.profile_id.strip():
            raise RigBankError("rig binding profile_id is required")

    @property
    def normalized_key(self) -> str:
        """Return the canonical lookup key for this binding."""

        return _normalize(self.key)

    def to_json(self) -> dict[str, object]:
        """Serialize to the rig-bank JSON shape."""

        return {"scope": self.scope, "key": self.key, "profile_id": self.profile_id}

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> RigBinding:
        """Build from one binding object in ``rig_bank.json``."""

        scope = _str_field(data, "scope")
        if scope not in ("song", "artist", "genre"):
            raise RigBankError(f"unsupported rig binding scope: {scope}")
        return cls(
            scope=scope,
            key=_str_field(data, "key"),
            profile_id=_str_field(data, "profile_id"),
        )


@dataclass(frozen=True)
class RigResolution:
    """Resolved rig profile and why it won."""

    profile: RigProfile
    source: RigSelectionSource
    matched_key: str

    def to_json(self) -> dict[str, object]:
        """Serialize for CLI/API output."""

        return {
            "source": self.source,
            "matched_key": self.matched_key,
            "profile": self.profile.to_json(),
            "midi": [list(message) for message in self.profile.midi_bytes()],
        }


@dataclass(frozen=True)
class RigRecommendation:
    """Best-effort profile suggestion with human-readable evidence."""

    profile: RigProfile
    source: RigSelectionSource
    score: int
    reasons: tuple[str, ...]
    matched_key: str = ""

    def to_json(self) -> dict[str, object]:
        """Serialize for API/UI output."""

        return {
            "source": self.source,
            "score": self.score,
            "matched_key": self.matched_key,
            "reasons": list(self.reasons),
            "profile": self.profile.to_json(),
            "midi": [list(message) for message in self.profile.midi_bytes()],
        }


@dataclass(frozen=True)
class RigBank:
    """Collection of selectable Valeton profiles and their lookup bindings."""

    profiles: tuple[RigProfile, ...] = field(default_factory=tuple)
    bindings: tuple[RigBinding, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for profile in self.profiles:
            if profile.id in seen:
                raise RigBankError(f"duplicate rig profile id: {profile.id}")
            seen.add(profile.id)
        missing = sorted({binding.profile_id for binding in self.bindings} - seen)
        if missing:
            raise RigBankError(f"rig binding references unknown profile(s): {', '.join(missing)}")

    def to_json(self) -> dict[str, object]:
        """Serialize to ``rig_bank.json``."""

        return {
            "schema_version": RIG_BANK_SCHEMA_VERSION,
            "profiles": [profile.to_json() for profile in self.profiles],
            "bindings": [binding.to_json() for binding in self.bindings],
        }

    def get_profile(self, profile_id: str) -> RigProfile | None:
        """Return a profile by id, or None."""

        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        return None

    def with_profile(self, profile: RigProfile) -> RigBank:
        """Return a bank where ``profile`` is added or replaces an existing id."""

        profiles = tuple(p for p in self.profiles if p.id != profile.id) + (profile,)
        return RigBank(profiles=profiles, bindings=self.bindings)

    def with_binding(self, binding: RigBinding) -> RigBank:
        """Return a bank where a scope/key binding points to ``profile_id``."""

        if self.get_profile(binding.profile_id) is None:
            raise RigBankError(f"unknown rig profile id: {binding.profile_id}")
        key = binding.normalized_key
        bindings = tuple(
            existing
            for existing in self.bindings
            if not (existing.scope == binding.scope and existing.normalized_key == key)
        ) + (binding,)
        return RigBank(profiles=self.profiles, bindings=bindings)

    def resolve(
        self,
        *,
        song: str | None = None,
        artist: str | None = None,
        genre: str | None = None,
        profile_id: str | None = None,
    ) -> RigResolution | None:
        """Resolve the rig to activate.

        Priority is explicit profile, song binding, artist binding, genre
        binding, then profile metadata by artist/genre. That mirrors stage use:
        a song-specific sound overrides an artist sound, which overrides a broad
        style fallback.
        """

        if profile_id:
            profile = self.get_profile(profile_id)
            if profile is None:
                raise RigBankError(f"unknown rig profile id: {profile_id}")
            return RigResolution(profile, "explicit", profile_id)

        for scope, key, source in (
            ("song", song, "song_binding"),
            ("artist", artist, "artist_binding"),
            ("genre", genre, "genre_binding"),
        ):
            if not key:
                continue
            resolution = self._resolve_binding(scope, key, source)
            if resolution is not None:
                return resolution

        if artist:
            artist_key = _normalize(artist)
            for profile in self.profiles:
                if profile.artist and _normalize(profile.artist) == artist_key:
                    return RigResolution(profile, "profile_artist", profile.artist)
        if genre:
            genre_key = _normalize(genre)
            for profile in self.profiles:
                if profile.genre and _normalize(profile.genre) == genre_key:
                    return RigResolution(profile, "profile_genre", profile.genre)
        return None

    def recommend(
        self,
        *,
        song: str | None = None,
        artist: str | None = None,
        genre: str | None = None,
        profile_id: str | None = None,
    ) -> RigRecommendation | None:
        """Recommend the closest GP-180 profile for song metadata.

        Exact bindings still win, but unlike :meth:`resolve`, this also returns
        an approximate match based on artist/genre/profile tags so every song can
        get a playable starting point.
        """

        resolution = self.resolve(
            song=song,
            artist=artist,
            genre=genre,
            profile_id=profile_id,
        )
        if resolution is not None:
            reason = _resolution_reason(resolution.source, resolution.matched_key)
            return RigRecommendation(
                profile=resolution.profile,
                source=resolution.source,
                score=100,
                reasons=(reason,),
                matched_key=resolution.matched_key,
            )

        best: RigRecommendation | None = None
        for profile in self.profiles:
            score, reasons, source, matched_key = _score_profile(profile, song, artist, genre)
            if score <= 0:
                continue
            recommendation = RigRecommendation(
                profile=profile,
                source=source,
                score=score,
                reasons=tuple(reasons),
                matched_key=matched_key,
            )
            if best is None or recommendation.score > best.score:
                best = recommendation

        if best is not None:
            return best
        if self.profiles:
            profile = self.profiles[0]
            return RigRecommendation(
                profile=profile,
                source="fallback",
                score=1,
                reasons=("Aucun artiste ou genre exploitable : profil neutre de départ.",),
            )
        return None

    def _resolve_binding(
        self,
        scope: RigBindingScope,
        key: str,
        source: RigSelectionSource,
    ) -> RigResolution | None:
        wanted = _normalize(key)
        for binding in self.bindings:
            if binding.scope == scope and binding.normalized_key == wanted:
                profile = self.get_profile(binding.profile_id)
                if profile is None:
                    raise RigBankError(f"unknown rig profile id: {binding.profile_id}")
                return RigResolution(profile, source, binding.key)
        return None

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> RigBank:
        """Build a bank from parsed JSON."""

        version = _str_field(data, "schema_version", default=RIG_BANK_SCHEMA_VERSION)
        if version != RIG_BANK_SCHEMA_VERSION:
            raise RigBankError(f"unsupported rig bank schema: {version}")
        profiles_obj = data.get("profiles", [])
        bindings_obj = data.get("bindings", [])
        if not isinstance(profiles_obj, list):
            raise RigBankError("rig bank 'profiles' must be a list")
        if not isinstance(bindings_obj, list):
            raise RigBankError("rig bank 'bindings' must be a list")
        profiles = tuple(
            RigProfile.from_json(_object_item(item, "profile")) for item in profiles_obj
        )
        bindings = tuple(
            RigBinding.from_json(_object_item(item, "binding")) for item in bindings_obj
        )
        return cls(profiles=profiles, bindings=bindings)


class MidiOutput(Protocol):
    """Small protocol for testable MIDI outputs."""

    def send(self, message: object) -> None:
        """Send one MIDI message."""

    def close(self) -> None:
        """Close the output port."""


def rig_bank_path(rigs_dir: Path) -> Path:
    """Return the standard structured rig-bank path under a rigs directory."""

    return rigs_dir / DEFAULT_RIG_BANK_NAME


def load_rig_bank(path: Path) -> RigBank:
    """Load a rig bank, returning an empty bank when the file is absent."""

    if not path.is_file():
        return RigBank()
    data_obj: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data_obj, dict):
        raise RigBankError("rig bank JSON must be an object")
    return RigBank.from_json(data_obj)


def save_rig_bank(path: Path, bank: RigBank) -> None:
    """Write a rig bank as pretty UTF-8 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bank.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def list_midi_output_names() -> list[str]:
    """Return available MIDI output port names via mido."""

    try:
        import mido
    except ImportError as exc:
        raise RigBankError("mido is required to list MIDI outputs") from exc
    try:
        return list(mido.get_output_names())
    except Exception as exc:
        raise RigBankError(f"MIDI output listing failed: {exc}") from exc


def send_profile_program_change(
    profile: RigProfile,
    port_name: str | None = None,
) -> tuple[tuple[int, ...], ...]:
    """Send the MIDI messages that activate ``profile``.

    Args:
        profile: Profile to activate.
        port_name: Optional mido output name. ``None`` lets mido open its default
            output, when available.

    Returns:
        Raw bytes that were sent, useful for logs and API responses.
    """

    messages = profile.midi_bytes()
    try:
        import mido
    except ImportError as exc:
        raise RigBankError("mido is required to activate a MIDI rig profile") from exc

    try:
        output = mido.open_output(port_name) if port_name else mido.open_output()
    except Exception as exc:
        label = f" {port_name!r}" if port_name else ""
        raise RigBankError(f"MIDI output{label} could not be opened: {exc}") from exc
    try:
        for raw in messages:
            output.send(mido.Message.from_bytes(list(raw)))
    finally:
        output.close()
    return messages


def read_valeton_suite_effect_catalog(paths: Iterable[Path]) -> dict[str, list[str]]:
    """Extract effect model names from Valeton Suite ``module*_data.json`` files.

    This does not read user bank names. The installed Suite assets describe
    effect algorithms/modules; actual preset names appear to live on the device
    or in exported project data, not in ``Program Files``.
    """

    catalog: dict[str, set[str]] = {}
    for path in paths:
        if not path.is_file():
            continue
        data_obj: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data_obj, dict):
            continue
        modules_obj = data_obj.get("modules")
        if not isinstance(modules_obj, list):
            continue
        for module_obj in modules_obj:
            if not isinstance(module_obj, dict):
                continue
            module_name = str(module_obj.get("name") or "").strip()
            effects_obj = module_obj.get("module")
            if not module_name or not isinstance(effects_obj, list):
                continue
            bucket = catalog.setdefault(module_name, set())
            for effect_obj in effects_obj:
                if not isinstance(effect_obj, dict):
                    continue
                title = str(effect_obj.get("fxtitle") or effect_obj.get("name") or "").strip()
                if title:
                    bucket.add(title)
    return {module: sorted(names) for module, names in sorted(catalog.items())}


def _resolution_reason(source: RigSelectionSource, matched_key: str) -> str:
    if source == "explicit":
        return "Profil choisi explicitement."
    if source == "song_binding":
        return f"Liaison exacte avec la chanson « {matched_key} »."
    if source == "artist_binding":
        return f"Liaison exacte avec l'artiste « {matched_key} »."
    if source == "genre_binding":
        return f"Liaison exacte avec le genre « {matched_key} »."
    if source == "profile_artist":
        return f"Artiste du profil : « {matched_key} »."
    if source == "profile_genre":
        return f"Genre du profil : « {matched_key} »."
    return "Correspondance approchante."


def _score_profile(
    profile: RigProfile,
    song: str | None,
    artist: str | None,
    genre: str | None,
) -> tuple[int, list[str], RigSelectionSource, str]:
    score = 0
    reasons: list[str] = []
    source: RigSelectionSource = "tag_match"
    matched_key = ""

    if artist:
        artist_norm = _normalize(artist)
        if profile.artist and _normalize(profile.artist) == artist_norm:
            score += 90
            source = "artist_match"
            matched_key = profile.artist
            reasons.append(f"Artiste reconnu : {artist} -> {profile.artist}.")
        else:
            artist_tokens = _tokens(artist)
            profile_artist_tokens = _tokens(profile.artist or "")
            artist_overlap = artist_tokens & profile_artist_tokens
            if artist_overlap:
                score += 35 + 8 * len(artist_overlap)
                source = "artist_match"
                matched_key = " ".join(sorted(artist_overlap))
                reasons.append(
                    "Artiste proche du profil : "
                    + ", ".join(sorted(artist_overlap))
                    + "."
                )

    if genre:
        profile_genre = profile.genre or infer_rig_profile_genre(
            name=profile.name,
            artist=profile.artist,
            tags=profile.tags,
            notes=profile.notes,
        )
        genre_norm = _normalize(genre)
        if profile_genre and _normalize(profile_genre) == genre_norm:
            score += 75
            if source != "artist_match":
                source = "genre_match"
                matched_key = profile_genre
            reasons.append(f"Genre/sous-genre compatible : {genre} -> {profile_genre}.")
        else:
            genre_score, genre_reason, matched_genre = _genre_similarity(
                genre,
                profile_genre,
                profile,
            )
            if genre_score:
                score += genre_score
                if source not in ("artist_match", "genre_match"):
                    source = "genre_match"
                    matched_key = matched_genre
                reasons.append(genre_reason)

    song_tokens = _tokens(song or "")
    if song_tokens:
        profile_tokens = _profile_text_tokens(profile)
        title_overlap = song_tokens & profile_tokens
        if title_overlap:
            score += min(24, 6 * len(title_overlap))
            if source not in ("artist_match", "genre_match"):
                source = "tag_match"
                matched_key = " ".join(sorted(title_overlap))
            reasons.append(
                "Indice dans le titre/profil : "
                + ", ".join(sorted(title_overlap))
                + "."
            )

    return score, reasons, source, matched_key


def _profile_text_tokens(profile: RigProfile) -> set[str]:
    text = " ".join(
        (
            profile.name,
            profile.artist or "",
            profile.genre or "",
            " ".join(profile.tags),
            profile.notes,
        )
    )
    return _tokens(text)


def infer_rig_profile_genre(
    *,
    name: str,
    artist: str | None = None,
    tags: Iterable[str] = (),
    notes: str = "",
) -> str | None:
    """Infer a useful editable genre guess for a GP-180 profile.

    This is intentionally conservative and deterministic. It is used only when
    a stored profile has no explicit genre, so the Settings page can still offer
    a starting point for every preset without overwriting user edits.
    """

    haystack = _normalize(" ".join((name, artist or "", " ".join(tags), notes)))
    for genre, keywords in _GENRE_KEYWORDS:
        for keyword in keywords:
            if _normalize(keyword) in haystack:
                return genre
    tokens = _tokens(haystack)
    for token in tokens:
        family = _GENRE_FAMILIES.get(token)
        if family:
            return family
    return "general"


def _genre_similarity(
    requested_genre: str,
    profile_genre: str | None,
    profile: RigProfile,
) -> tuple[int, str, str]:
    candidate = profile_genre or "general"
    requested_tokens = _tokens(requested_genre)
    candidate_tokens = _tokens(candidate)
    profile_tokens = _profile_text_tokens(profile)
    overlap = requested_tokens & (candidate_tokens | profile_tokens)
    score = 0
    reason_parts: list[str] = []

    if overlap:
        score += 24 + 8 * len(overlap)
        reason_parts.append("mots communs " + ", ".join(sorted(overlap)))

    requested_families = _genre_families(requested_tokens)
    candidate_families = _genre_families(candidate_tokens | profile_tokens)
    family_overlap = requested_families & candidate_families
    if family_overlap:
        score += 18 + 5 * len(family_overlap)
        reason_parts.append("famille " + ", ".join(sorted(family_overlap)))

    requested_norm = _normalize(requested_genre)
    candidate_norm = _normalize(candidate)
    if requested_norm and candidate_norm:
        ratio = SequenceMatcher(None, requested_norm, candidate_norm).ratio()
        if ratio >= 0.72:
            score += int(20 * ratio)
            reason_parts.append("libellé proche")
        elif requested_norm in candidate_norm or candidate_norm in requested_norm:
            score += 12
            reason_parts.append("sous-genre inclus")

    if score <= 0:
        return 0, "", ""
    score = min(score, 74)
    reason = (
        f"Genre approchant : fiche « {requested_genre} » -> "
        f"profil « {candidate} » ({'; '.join(reason_parts)})."
    )
    return score, reason, candidate


def _genre_families(tokens: set[str]) -> set[str]:
    return {family for token in tokens if (family := _GENRE_FAMILIES.get(token))}


def _tokens(text: str) -> set[str]:
    normalized = _normalize(text).replace("_", " ")
    return {
        token
        for token in normalized.split()
        if len(token) >= 2 and token not in _TOKEN_STOPWORDS
    }


def _validate_midi_range(name: str, value: int, *, low: int = 0, high: int = 127) -> None:
    if value < low or value > high:
        raise RigBankError(f"{name} must be between {low} and {high}")


def _object_item(item: object, label: str) -> Mapping[str, object]:
    if not isinstance(item, dict):
        raise RigBankError(f"rig bank {label} entry must be an object")
    return item


def _str_field(data: Mapping[str, object], name: str, *, default: str | None = None) -> str:
    raw = data.get(name, default)
    if raw is None:
        raise RigBankError(f"missing string field: {name}")
    if not isinstance(raw, str):
        raise RigBankError(f"field {name!r} must be a string")
    return raw


def _optional_str_field(data: Mapping[str, object], name: str) -> str | None:
    raw = data.get(name)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise RigBankError(f"field {name!r} must be a string")
    return raw or None


def _int_field(data: Mapping[str, object], name: str, *, default: int | None = None) -> int:
    raw = data.get(name, default)
    if raw is None:
        raise RigBankError(f"missing integer field: {name}")
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise RigBankError(f"field {name!r} must be an integer")
    return raw


def _optional_int_field(data: Mapping[str, object], name: str) -> int | None:
    raw = data.get(name)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise RigBankError(f"field {name!r} must be an integer")
    return raw


def _str_list_field(data: Mapping[str, object], name: str) -> list[str]:
    raw = data.get(name, [])
    if not isinstance(raw, list):
        raise RigBankError(f"field {name!r} must be a list")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise RigBankError(f"field {name!r} must contain strings")
        values.append(item)
    return values
