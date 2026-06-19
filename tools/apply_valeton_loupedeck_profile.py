"""Patch the existing Loupedeck CT ValetonSuite profile in place.

This avoids importing a synthetic ``.lp5``. The script preserves the existing
ApplicationInfo/ProfileInfo envelope created by the Loupedeck application and
only replaces the touch pages with GP-180 actions.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROFILE_DISPLAY_NAME = "ValetonSuite"
APP_NAME = "valeton suite"
PLUGIN_NAME = "LoupedeckMSFSG1000"
LEGACY_PLUGIN_NAMES = {"FretWiseGP180", "ValetonGP180"}
PROFILE_PAGE_SIZE = 12

CONTROL_COMMANDS = [
    "ValetonGp180PresetDownCommand",
    "ValetonGp180PresetUpCommand",
    "ValetonGp180TunerCommand",
    "ValetonGp180TapTempoCommand",
    "ValetonGp180PatchModeCommand",
    "ValetonGp180StompModeCommand",
    "ValetonGp180CtrlACommand",
    "ValetonGp180CtrlBCommand",
    "ValetonGp180CtrlCCommand",
    "ValetonGp180AnalogBypassCommand",
    "ValetonGp180DspBypassCommand",
    "ValetonGp180DrumCommand",
]

ENCODER_COMMANDS = [
    "ValetonGp180PatchVolumeAdjustment",
    "ValetonGp180ExpressionAdjustment",
    "ValetonGp180Quick1Adjustment",
    "ValetonGp180Quick2Adjustment",
    "ValetonGp180Quick3Adjustment",
    "ValetonGp180TempoAdjustment",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        default="exports/loupedeck/gp180/gp180_control_surface_catalog.json",
    )
    parser.add_argument(
        "--plugin-build",
        default="D:/DocumentsBenoit/LoupedeckG1000/Loupedeck-MSFS-G1000/bin/Debug",
    )
    parser.add_argument(
        "--backup-root",
        default="maintenance_backups",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    local_app_data = Path(os.environ["LOCALAPPDATA"])
    app_dir = local_app_data / "Logi" / "LogiPluginService" / "Applications" / "Loupedeck20"
    profile_info = _find_profile_info(app_dir)
    catalog_path = Path(args.catalog)
    plugin_build = Path(args.plugin_build).resolve()
    profile_app_dir = profile_info.parents[2]

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_info.read_text(encoding="utf-8"))
    application_info = profile_app_dir / "ApplicationInfo.json"
    application = json.loads(application_info.read_text(encoding="utf-8"))

    if application.get("defaultProfileName") != profile.get("name"):
        raise RuntimeError(
            f"{application_info} does not point to {profile.get('name')} as default profile"
        )

    patched = _patch_profile(profile, catalog)

    if args.dry_run:
        print(f"Would patch {profile_info}")
        print(f"Would use local plugin build {plugin_build}")
        print(f"Would back up {profile_app_dir} into {Path(args.backup_root)}")
        return

    backup_dir = _backup(profile_app_dir, Path(args.backup_root))
    profile_info.write_text(
        json.dumps(patched, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )

    print(f"Patched {profile_info}")
    print(f"Using plugin build {plugin_build}")
    print(f"Backup: {backup_dir}")


def _find_profile_info(app_dir: Path) -> Path:
    for profile_info in app_dir.rglob("ProfileInfo.json"):
        try:
            payload = json.loads(profile_info.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("displayName") == PROFILE_DISPLAY_NAME and payload.get("applicationName") == APP_NAME:
            return profile_info
    raise FileNotFoundError(f"Could not find Loupedeck profile {PROFILE_DISPLAY_NAME!r}")


def _backup(app_profile_dir: Path, backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / f"loupedeck_valetonsuite_{stamp}"
    shutil.copytree(app_profile_dir, backup_dir)
    return backup_dir


def _patch_profile(profile: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    patched = json.loads(json.dumps(profile))
    native_plugins = [
        plugin
        for plugin in (patched.get("additionalNativePluginNames") or [])
        if plugin not in LEGACY_PLUGIN_NAMES
    ]
    if PLUGIN_NAME not in native_plugins:
        native_plugins.append(PLUGIN_NAME)
    patched["additionalNativePluginNames"] = native_plugins
    patched["lastModifiedTimeUtc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    profile_settings = patched.setdefault(
        "profileSettings",
        {"$type": "Loupedeck.DictionaryNoCase`1[[System.String, System.Private.CoreLib]], PluginApi"},
    )
    profile_settings["midi"] = "true"

    mode = patched["layout"]["layoutModes"][0]
    profile_actions = _profile_actions(catalog)
    genre_actions = _genre_actions(catalog)
    pages = [
        _touch_page("GP-180 Control", _control_action_ids()),
        _touch_page("Genres", genre_actions[:PROFILE_PAGE_SIZE]),
    ]
    for index, chunk in enumerate(_chunks(profile_actions, PROFILE_PAGE_SIZE), start=1):
        first = (index - 1) * PROFILE_PAGE_SIZE + 1
        last = first + len(chunk) - 1
        pages.append(_touch_page(f"Profiles {first:03d}-{last:03d}", chunk))

    workspace = mode["workspaces"][0]
    _add_navigation(profile=patched, mode=mode, workspace_name=workspace["name"], pages=pages)
    mode["touchPages"] = pages
    encoder_pages = [_encoder_page("GP-180 MIDI", _encoder_action_ids())]
    mode["encoderPages"] = encoder_pages
    workspace["displayName"] = "ValetonSuite"
    workspace["touchPageNames"] = [page["name"] for page in pages]
    workspace["encoderPageNames"] = [page["name"] for page in encoder_pages]
    return patched


def _profile_actions(catalog: dict[str, Any]) -> list[str]:
    actions = [
        action
        for action in catalog.get("actions", [])
        if isinstance(action, dict)
        and action.get("kind") == "activate_profile"
        and action.get("status") == "ready"
        and action.get("profile_id")
    ]
    actions.sort(key=lambda action: str(action.get("label") or ""))
    return [_g1000_host_action_id(action) for action in actions]


def _genre_actions(catalog: dict[str, Any]) -> list[str]:
    actions = [
        action
        for action in catalog.get("actions", [])
        if isinstance(action, dict)
        and action.get("kind") == "activate_genre_profile"
        and action.get("status") == "ready"
        and action.get("profile_id")
    ]
    actions.sort(key=lambda action: str(action.get("label") or ""))
    return [_g1000_host_action_id(action) for action in actions]


def _g1000_host_action_id(action: dict[str, Any]) -> str:
    program = _display_program(action)
    command = f"LoupedeckMSFSG1000.Actions.ValetonGp180Profile{program:03d}Command"
    return f"${PLUGIN_NAME}___{command}"


def _fixed_action_id(class_name: str) -> str:
    return f"${PLUGIN_NAME}___LoupedeckMSFSG1000.Actions.{class_name}"


def _control_action_ids() -> list[str]:
    return [_fixed_action_id(command) for command in CONTROL_COMMANDS]


def _encoder_action_ids() -> list[str]:
    return [_fixed_action_id(command) for command in ENCODER_COMMANDS]


def _display_program(action: dict[str, Any]) -> int:
    midi = action.get("midi", [])
    if isinstance(midi, list):
        for message in midi:
            if isinstance(message, list) and message and (int(message[0]) & 0xF0) == 0xC0:
                return int(message[1]) + 1
    profile_id = str(action.get("profile_id") or "")
    digits = "".join(char for char in profile_id if char.isdigit())
    if digits:
        return int(digits[:3])
    return 1


def _touch_page(display_name: str, action_ids: list[str]) -> dict[str, Any]:
    padded = [*action_ids[:15], *[""] * max(0, 15 - len(action_ids))]
    return {
        "$type": "Loupedeck.Service.ProfileLayoutButtonPage, LoupedeckService",
        "name": uuid.uuid4().hex.upper(),
        "displayName": display_name,
        "description": None,
        "controls": [
            {
                "$type": "Loupedeck.Service.ProfileLayoutButton, LoupedeckService",
                "pressAction": action_id,
                "fnPressAction": None,
            }
            for action_id in padded[:15]
        ],
        "dynamicPageName": None,
        "dynamicPagePluginName": None,
        "dynamicPageNumber": 0,
    }


def _encoder_page(display_name: str, action_ids: list[str]) -> dict[str, Any]:
    padded = [*action_ids[:6], *[""] * max(0, 6 - len(action_ids))]
    return {
        "$type": "Loupedeck.Service.ProfileLayoutEncoderPage, LoupedeckService",
        "name": uuid.uuid4().hex.upper(),
        "displayName": display_name,
        "description": None,
        "controls": [
            {
                "$type": "Loupedeck.Service.ProfileLayoutEncoder, LoupedeckService",
                "pressAction": action_id,
                "fnPressAction": None,
                "rotateAction": action_id,
                "fnRotateAction": None,
            }
            for action_id in padded[:6]
        ],
        "dynamicPageName": None,
        "dynamicPagePluginName": None,
        "dynamicPageNumber": 0,
    }


def _add_navigation(
    *,
    profile: dict[str, Any],
    mode: dict[str, Any],
    workspace_name: str,
    pages: list[dict[str, Any]],
) -> None:
    if not pages:
        return

    for index, page in enumerate(pages):
        controls = page.get("controls") or []
        if len(controls) < 3:
            continue
        previous_page = pages[index - 1]
        next_page = pages[(index + 1) % len(pages)]
        controls[-3]["pressAction"] = _ensure_actions_macro(
            profile,
            "GP180 HOME",
            [_touch_page_change_action(mode, workspace_name, pages[0]["name"])],
        )
        controls[-2]["pressAction"] = _ensure_actions_macro(
            profile,
            f"GP180 PREV {page['displayName']}",
            [_touch_page_change_action(mode, workspace_name, previous_page["name"])],
        )
        controls[-1]["pressAction"] = _ensure_actions_macro(
            profile,
            f"GP180 NEXT {page['displayName']}",
            [_touch_page_change_action(mode, workspace_name, next_page["name"])],
        )


def _touch_page_change_action(mode: dict[str, Any], workspace_name: str, page_name: str) -> str:
    return f"$@Generic___@ChangeTouchPage___{mode['modeName']}|{workspace_name}|{page_name}"


def _macro_action(macro_id: str) -> str:
    return f"$@Generic___@Macro___{macro_id}"


def _ensure_actions_macro(profile: dict[str, Any], display_name: str, actions: list[str]) -> str:
    macros = profile.setdefault("macroCommands", [])
    for macro in macros:
        if isinstance(macro, dict) and macro.get("displayName") == display_name:
            macro["groupName"] = "Valeton GP-180"
            macro["actions"] = actions
            return _macro_action(str(macro["name"]))

    macro_id = uuid.uuid4().hex.upper()
    macros.append(
        {
            "$type": "Loupedeck.Service.ApplicationProfileMacroCommand, LoupedeckService",
            "isCommand": True,
            "name": macro_id,
            "displayName": display_name,
            "description": "",
            "groupName": "Valeton GP-180",
            "superGroupName": "@macro",
            "supportedOs": "All",
            "supportedModes": ["system"],
            "showAsSingleAction": True,
            "actionEditorCommands": [],
            "isMultiState": False,
            "actions": actions,
        }
    )
    return _macro_action(macro_id)


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


if __name__ == "__main__":
    main()
