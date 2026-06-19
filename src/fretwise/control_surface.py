"""Control-surface action catalog for Valeton GP-180 integrations.

The web UI, Loupedeck CT/S files, and native plugins share the same abstract
GP-180 actions instead of each surface inventing its own mapping. Deterministic
profile/genre actions are direct MIDI actions for Loupedeck; FretWise is only
needed for contextual recommendation/resolution.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from fretwise.rig_bank import RigBank, RigProfile

CONTROL_SURFACE_SCHEMA_VERSION = "fretwise_gp180_control_surface_v1"
LOUPEDECK_PLUGIN_NAME = "ValetonGP180"
LOUPEDECK_PROFILE_COMMAND = "ValetonGP180.Actions.Gp180ProfileCommand"
LOUPEDECK_RECOMMEND_COMMAND = "ValetonGP180.Actions.FretWiseRecommendCommand"
LOUPEDECK_PLANNED_COMMAND = "ValetonGP180.Actions.Gp180PlannedCommand"

ActionStatus = Literal["ready", "planned"]
ActionKind = Literal[
    "activate_profile",
    "activate_genre_profile",
    "recommend_context",
    "effect_toggle",
    "parameter_adjust",
    "utility",
]


@dataclass(frozen=True)
class ControlSurfaceAction:
    """One abstract action a hardware surface can expose."""

    id: str
    label: str
    kind: ActionKind
    group: str
    status: ActionStatus
    loupedeck_action_id: str
    loupedeck_route: str
    description: str = ""
    profile_id: str | None = None
    genre: str | None = None
    midi: tuple[tuple[int, ...], ...] = field(default_factory=tuple)
    candidates: tuple[str, ...] = field(default_factory=tuple)
    device_targets: tuple[str, ...] = ("ct", "s")

    def to_json(self) -> dict[str, object]:
        """Serialize for the web API and Loupedeck file generation."""

        payload: dict[str, object] = {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "group": self.group,
            "status": self.status,
            "loupedeck_action_id": self.loupedeck_action_id,
            "loupedeck_route": self.loupedeck_route,
            "description": self.description,
            "device_targets": list(self.device_targets),
        }
        if self.profile_id:
            payload["profile_id"] = self.profile_id
        if self.genre:
            payload["genre"] = self.genre
        if self.midi:
            payload["midi"] = [list(message) for message in self.midi]
        if self.candidates:
            payload["candidates"] = list(self.candidates)
        return payload


def build_gp180_control_surface_catalog(bank: RigBank) -> dict[str, object]:
    """Build the complete GP-180 action/layout catalog for CT and S surfaces."""

    actions = [
        *_utility_actions(),
        *_profile_actions(bank.profiles),
        *_genre_actions(bank.profiles),
        *_effect_actions(),
        *_parameter_actions(),
    ]
    return {
        "schema_version": CONTROL_SURFACE_SCHEMA_VERSION,
        "plugin_name": LOUPEDECK_PLUGIN_NAME,
        "devices": {
            "ct": {
                "name": "Loupedeck CT",
                "touch_slots": 15,
                "encoders": 6,
                "intent": "Edition fine du son + activation live.",
            },
            "s": {
                "name": "Loupedeck S",
                "touch_slots": 12,
                "encoders": 0,
                "intent": "Setlist, genres, artistes et profils rapides.",
            },
        },
        "actions": [action.to_json() for action in actions],
        "layouts": {
            "ct": _ct_layout(bank, actions),
            "s": _s_layout(bank, actions),
        },
    }


def find_gp180_control_surface_action(
    catalog: Mapping[str, object],
    action_id: str,
) -> Mapping[str, object] | None:
    """Return one action object from a serialized catalog by id."""

    actions_obj = catalog.get("actions", [])
    if not isinstance(actions_obj, list):
        return None
    for action in actions_obj:
        if isinstance(action, dict) and action.get("id") == action_id:
            return action
    return None


def profile_id_for_surface_action(
    action: Mapping[str, object],
    bank: RigBank,
) -> str | None:
    """Return the GP-180 profile id that a ready action activates, if any."""

    profile_id = _optional_text(action.get("profile_id"))
    if profile_id and bank.get_profile(profile_id) is not None:
        return profile_id
    candidates_obj = action.get("candidates", [])
    if isinstance(candidates_obj, list):
        for candidate in candidates_obj:
            candidate_id = _optional_text(candidate)
            if candidate_id and bank.get_profile(candidate_id) is not None:
                return candidate_id
    return None


def loupedeck_action_id(action_id: str) -> str:
    """Return the native Loupedeck plugin action id for an abstract action."""

    if action_id == "gp180.recommend.context":
        return f"${LOUPEDECK_PLUGIN_NAME}___{LOUPEDECK_RECOMMEND_COMMAND}"
    if action_id.startswith("gp180.profile."):
        parameter = action_id.rsplit(".", 1)[1]
        return loupedeck_profile_action_id(parameter)
    parameter = re.sub(r"[^A-Za-z0-9_.-]+", "_", action_id).strip("_")
    return f"${LOUPEDECK_PLUGIN_NAME}___{LOUPEDECK_PLANNED_COMMAND}___{parameter}"


def loupedeck_profile_action_id(profile_id: str) -> str:
    """Return the native Loupedeck action id for a direct GP-180 profile preset."""

    return f"${LOUPEDECK_PLUGIN_NAME}___{LOUPEDECK_PROFILE_COMMAND}___{profile_id}"


def _profile_actions(profiles: Sequence[RigProfile]) -> list[ControlSurfaceAction]:
    return [
        ControlSurfaceAction(
            id=f"gp180.profile.{profile.id}",
            label=profile.name,
            kind="activate_profile",
            group="Profiles",
            status="ready",
            loupedeck_action_id=loupedeck_action_id(f"gp180.profile.{profile.id}"),
            loupedeck_route="direct_midi",
            description=f"Activate GP-180 preset {profile.display_program:03d}.",
            profile_id=profile.id,
            genre=profile.genre,
            midi=profile.midi_bytes(),
        )
        for profile in sorted(profiles, key=lambda item: item.program)
    ]


def _genre_actions(profiles: Sequence[RigProfile]) -> list[ControlSurfaceAction]:
    by_genre: dict[str, list[RigProfile]] = defaultdict(list)
    for profile in profiles:
        if profile.genre:
            by_genre[profile.genre].append(profile)

    actions: list[ControlSurfaceAction] = []
    for genre, bucket in sorted(by_genre.items(), key=lambda item: item[0].lower()):
        ordered = sorted(bucket, key=lambda item: item.program)
        primary = ordered[0]
        action_id = f"gp180.genre.{_slug(genre)}"
        actions.append(
            ControlSurfaceAction(
                id=action_id,
                label=genre.title(),
                kind="activate_genre_profile",
                group="Genres",
                status="ready",
                loupedeck_action_id=loupedeck_profile_action_id(primary.id),
                loupedeck_route="direct_midi",
                description=(
                    f"Activate the first GP-180 profile tagged {genre!r}; "
                    f"other same-genre profiles remain listed as candidates."
                ),
                profile_id=primary.id,
                genre=genre,
                midi=primary.midi_bytes(),
                candidates=tuple(profile.id for profile in ordered),
                device_targets=("ct", "s"),
            )
        )
    return actions


def _utility_actions() -> list[ControlSurfaceAction]:
    return [
        ControlSurfaceAction(
            id="gp180.recommend.context",
            label="Recommended",
            kind="recommend_context",
            group="Live",
            status="ready",
            loupedeck_action_id=loupedeck_action_id("gp180.recommend.context"),
            loupedeck_route="fretwise_required",
            description=(
                "Ask FretWise to recommend a profile from the current song/artist/genre context."
            ),
            device_targets=("ct", "s"),
        ),
        ControlSurfaceAction(
            id="gp180.utility.resend",
            label="Resend",
            kind="utility",
            group="Live",
            status="planned",
            loupedeck_action_id=loupedeck_action_id("gp180.utility.resend"),
            loupedeck_route="planned",
            description="Resend the last selected Program Change once session state is persisted.",
            device_targets=("ct", "s"),
        ),
        ControlSurfaceAction(
            id="gp180.utility.tuner",
            label="Tuner",
            kind="utility",
            group="Emergency",
            status="planned",
            loupedeck_action_id=loupedeck_action_id("gp180.utility.tuner"),
            loupedeck_route="planned",
            description=(
                "Requires the GP-180 tuner MIDI command; "
                "not documented in the captured manual."
            ),
            device_targets=("ct", "s"),
        ),
    ]


def _effect_actions() -> list[ControlSurfaceAction]:
    effects = ("NR", "PRE", "WAH", "DST", "AMP", "CAB", "EQ", "MOD", "DLY", "RVB")
    actions: list[ControlSurfaceAction] = []
    for effect in effects:
        action_id = f"gp180.effect.{effect.lower()}.toggle"
        actions.append(
            ControlSurfaceAction(
                id=action_id,
                label=effect,
                kind="effect_toggle",
                group="Stompbox",
                status="planned",
                loupedeck_action_id=loupedeck_action_id(action_id),
                loupedeck_route="planned",
                description=(
                    f"Toggle {effect}; waiting for verified GP-180 CC/SysEx control code."
                ),
                device_targets=("ct", "s"),
            )
        )
    return actions


def _parameter_actions() -> list[ControlSurfaceAction]:
    params = (
        ("amp.gain", "Gain"),
        ("amp.bass", "Bass"),
        ("amp.mid", "Mid"),
        ("amp.treble", "Treble"),
        ("amp.presence", "Presence"),
        ("amp.level", "Level"),
        ("dly.mix", "Delay Mix"),
        ("dly.feedback", "Delay FB"),
        ("rvb.mix", "Reverb Mix"),
        ("mod.depth", "Mod Depth"),
    )
    return [
        ControlSurfaceAction(
            id=f"gp180.param.{param}",
            label=label,
            kind="parameter_adjust",
            group="Encoders",
            status="planned",
            loupedeck_action_id=loupedeck_action_id(f"gp180.param.{param}"),
            loupedeck_route="planned",
            description=(
                f"Encoder target {label}; waiting for verified GP-180 parameter CC/SysEx."
            ),
            device_targets=("ct",),
        )
        for param, label in params
    ]


def _ct_layout(bank: RigBank, actions: Sequence[ControlSurfaceAction]) -> dict[str, object]:
    top_profiles = _top_profile_actions(bank, actions, limit=10)
    genre_actions = [action.id for action in actions if action.group == "Genres"][:15]
    profile_action_ids = [
        f"gp180.profile.{profile.id}" for profile in sorted(bank.profiles, key=lambda p: p.program)
    ]
    profile_pages = _chunked(
        profile_action_ids,
        15,
    )
    return {
        "touch_pages": [
            {
                "name": "Live",
                "actions": [
                    "gp180.recommend.context",
                    *top_profiles[:10],
                    "gp180.utility.resend",
                    "gp180.utility.tuner",
                ][:15],
            },
            {"name": "Genres", "actions": genre_actions},
            *[
                {"name": f"Profiles {index + 1}", "actions": chunk}
                for index, chunk in enumerate(profile_pages)
            ],
            {
                "name": "Stompbox",
                "actions": [action.id for action in actions if action.group == "Stompbox"][:15],
            },
        ],
        "encoder_pages": [
            {
                "name": "Amp",
                "encoders": [
                    "gp180.param.amp.gain",
                    "gp180.param.amp.bass",
                    "gp180.param.amp.mid",
                    "gp180.param.amp.treble",
                    "gp180.param.amp.presence",
                    "gp180.param.amp.level",
                ],
            },
            {
                "name": "FX",
                "encoders": [
                    "gp180.param.dly.mix",
                    "gp180.param.dly.feedback",
                    "gp180.param.rvb.mix",
                    "gp180.param.mod.depth",
                ],
            },
        ],
    }


def _s_layout(bank: RigBank, actions: Sequence[ControlSurfaceAction]) -> dict[str, object]:
    top_profiles = _top_profile_actions(bank, actions, limit=10)
    genre_actions = [action.id for action in actions if action.group == "Genres"][:12]
    profile_action_ids = [
        f"gp180.profile.{profile.id}" for profile in sorted(bank.profiles, key=lambda p: p.program)
    ]
    profile_pages = _chunked(
        profile_action_ids,
        12,
    )
    return {
        "touch_pages": [
            {
                "name": "Live",
                "actions": [
                    "gp180.recommend.context",
                    *top_profiles[:9],
                    "gp180.utility.resend",
                ][:12],
            },
            {"name": "Genres", "actions": genre_actions},
            *[
                {"name": f"Profiles {index + 1}", "actions": chunk}
                for index, chunk in enumerate(profile_pages)
            ],
        ]
    }


def _top_profile_actions(
    bank: RigBank,
    actions: Sequence[ControlSurfaceAction],
    *,
    limit: int,
) -> list[str]:
    profile_ids = {
        action.profile_id
        for action in actions
        if action.group == "Profiles" and action.profile_id is not None
    }
    bound_ids = [
        binding.profile_id
        for binding in bank.bindings
        if binding.scope in {"song", "artist"} and binding.profile_id in profile_ids
    ]
    deduped: list[str] = []
    for profile_id in bound_ids:
        action_id = f"gp180.profile.{profile_id}"
        if action_id not in deduped:
            deduped.append(action_id)
    if len(deduped) >= limit:
        return deduped[:limit]
    for profile in sorted(bank.profiles, key=lambda item: item.program):
        action_id = f"gp180.profile.{profile.id}"
        if action_id not in deduped:
            deduped.append(action_id)
        if len(deduped) >= limit:
            break
    return deduped


def _chunked(values: Sequence[str], size: int) -> list[list[str]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unknown"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
