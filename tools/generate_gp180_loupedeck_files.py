"""Generate Loupedeck GP-180 plugin source and importable starter profiles.

The deterministic GP-180 actions must not round-trip through FretWise: the
generated Loupedeck plugin sends MIDI Program Change messages directly to the
Valeton device. FretWise remains useful only for contextual actions such as
"recommend a preset from the current song/artist/genre".
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import uuid
import zipfile
from pathlib import Path
from textwrap import dedent
from typing import Any

from fretwise.control_surface import build_gp180_control_surface_catalog
from fretwise.rig_bank import load_rig_bank

DEFAULT_OUT = Path("exports/loupedeck/gp180")
PLUGIN_NAME = "ValetonGP180"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rig-bank", default="partitions/rigs/rig_bank.json")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    rig_bank_path = Path(args.rig_bank)
    out_dir = Path(args.out)
    bank = load_rig_bank(rig_bank_path)
    catalog = build_gp180_control_surface_catalog(bank)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "gp180_control_surface_catalog.json", catalog)
    _write_pages(out_dir, catalog, "ct", "CT")
    _write_pages(out_dir, catalog, "s", "S")
    _write_direct_midi_reference(out_dir, catalog)
    _write_loupedeck_profiles(out_dir, catalog)
    _write_plugin_source(out_dir, catalog)
    _write_readme(out_dir, rig_bank_path, catalog)
    print(f"Wrote GP-180 Loupedeck files to {out_dir}")


def _write_pages(out_dir: Path, catalog: dict[str, Any], device_key: str, label: str) -> None:
    actions = _action_map(catalog)
    layout = catalog["layouts"][device_key]
    for page in layout.get("touch_pages", []):
        rows = []
        for index, action_id in enumerate(page.get("actions", [])):
            action = actions.get(action_id)
            if not action:
                continue
            rows.append(
                {
                    "index": str(index),
                    "display_name": _short_label(str(action.get("label") or action_id)),
                    "kind": "existing-action",
                    "action_id": str(action.get("loupedeck_action_id") or ""),
                    "route": str(action.get("loupedeck_route") or ""),
                    "color": _color_for_action(action),
                    "status": str(action.get("status") or ""),
                    "fretwise_action_id": action_id,
                    "midi": json.dumps(action.get("midi", []), separators=(",", ":")),
                    "notes": str(action.get("description") or ""),
                }
            )
        filename = f"{label}_{_slug(str(page.get('name') or 'page'))}.csv"
        _write_csv(out_dir / filename, rows)

    encoder_rows = []
    for page in layout.get("encoder_pages", []):
        for index, action_id in enumerate(page.get("encoders", [])):
            action = actions.get(action_id)
            if not action:
                continue
            encoder_rows.append(
                {
                    "page": str(page.get("name") or ""),
                    "encoder_index": str(index),
                    "display_name": _short_label(str(action.get("label") or action_id)),
                    "action_id": str(action.get("loupedeck_action_id") or ""),
                    "route": str(action.get("loupedeck_route") or ""),
                    "status": str(action.get("status") or ""),
                    "fretwise_action_id": action_id,
                    "notes": str(action.get("description") or ""),
                }
            )
    if encoder_rows:
        _write_csv(out_dir / f"{label}_encoder_pages.csv", encoder_rows)


def _write_direct_midi_reference(out_dir: Path, catalog: dict[str, Any]) -> None:
    rows = []
    for action in _ready_direct_midi_actions(catalog):
        rows.append(
            {
                "display_name": str(action.get("label") or ""),
                "profile_id": str(action.get("profile_id") or ""),
                "genre": str(action.get("genre") or ""),
                "loupedeck_action_id": str(action.get("loupedeck_action_id") or ""),
                "midi_hex": _midi_hex(action.get("midi", [])),
                "midi_decimal": json.dumps(action.get("midi", []), separators=(",", ":")),
                "notes": str(action.get("description") or ""),
            }
        )
    _write_csv(out_dir / "direct_midi_reference.csv", rows)


def _write_loupedeck_profiles(out_dir: Path, catalog: dict[str, Any]) -> None:
    profile_root = out_dir / "profiles"
    profile_root.mkdir(parents=True, exist_ok=True)
    for device_key, label, device_type, slots in (
        ("ct", "GP180_CT", "Loupedeck20", 15),
        ("s", "GP180_S", "Loupedeck40", 12),
    ):
        profile_dir = profile_root / label
        profile_dir.mkdir(parents=True, exist_ok=True)
        profile_info = _profile_info(catalog, device_key, label.replace("_", " "), device_type, slots)
        application_info = _application_info(profile_info["name"], device_type)
        _write_json(profile_dir / "ProfileInfo.json", profile_info)
        _write_json(profile_dir / "ApplicationInfo.json", application_info)
        metadata_dir = profile_dir / "metadata"
        metadata_dir.mkdir(exist_ok=True)
        _write_json(
            metadata_dir / "AdvancedInfo.json",
            {
                "version": "1.0",
                "generatedBy": "FretWise GP-180",
                "pluginName": PLUGIN_NAME,
                "deviceType": device_type,
            },
        )
        _zip_dir(profile_dir, out_dir / f"{label}.lp5")


def _profile_info(
    catalog: dict[str, Any],
    device_key: str,
    display_name: str,
    device_type: str,
    slots: int,
) -> dict[str, Any]:
    layout = catalog["layouts"][device_key]
    actions = _action_map(catalog)
    touch_pages = []
    touch_page_names = []
    for page in layout.get("touch_pages", []):
        page_name = _guid()
        touch_page_names.append(page_name)
        page_actions = []
        for action_id in page.get("actions", [])[:slots]:
            action = actions.get(action_id)
            command_id = str(action.get("loupedeck_action_id") or "") if action else ""
            page_actions.append(command_id)
        touch_pages.append(_touch_page(page_name, str(page.get("name") or ""), page_actions, slots))

    encoder_pages = []
    encoder_page_names = []
    if device_key == "ct":
        for page in layout.get("encoder_pages", []):
            page_name = _guid()
            encoder_page_names.append(page_name)
            encoder_pages.append(_encoder_page(page_name, str(page.get("name") or "")))

    workspace_name = _guid()
    profile_name = _guid()
    return {
        "$type": "Loupedeck.Service.ApplicationProfile, LoupedeckService",
        "name": profile_name,
        "profileFlags": "None",
        "displayName": display_name,
        "description": "GP-180 direct MIDI starter profile generated by FretWise.",
        "deviceType": device_type,
        "applicationName": "@_defaultwin",
        "nativePluginName": "DefaultWin",
        "hasNativePlugin": True,
        "additionalNativePluginNames": [PLUGIN_NAME],
        "profileSettings": {
            "$type": "Loupedeck.DictionaryNoCase`1[[System.String, System.Private.CoreLib]], "
            "PluginApi",
            "midi": "false",
        },
        "actionImages90": None,
        "actionImages60": None,
        "wheelImages": None,
        "actionColors": None,
        "layout": {
            "$type": "Loupedeck.Service.ProfileLayout20, LoupedeckService",
            "deviceType": device_type,
            "profileFlags": "None",
            "layoutModes": [
                {
                    "$type": "Loupedeck.Service.ProfileLayoutMode20, LoupedeckService",
                    "deviceType": device_type if device_type == "Loupedeck20" else "None",
                    "modeName": "System",
                    "parentModeName": None,
                    "actions": None,
                    "dynamicButtonPages": None,
                    "dynamicEncoderPages": None,
                    "touchPages": touch_pages,
                    "encoderPages": encoder_pages,
                    "wheelPages": [],
                    "workspaces": [
                        {
                            "$type": "Loupedeck.Service.ProfileLayoutWorkspace20, "
                            "LoupedeckService",
                            "name": workspace_name,
                            "displayName": "GP-180",
                            "description": None,
                            "touchPageNames": touch_page_names,
                            "encoderPageNames": encoder_page_names,
                            "wheelPageNames": [],
                            "activationActions": [],
                        }
                    ],
                    "homeWorkspaceName": workspace_name,
                }
            ],
        },
        "macroCommands": [],
        "macroAdjustments": [],
        "profileCommands": [],
        "profileAdjustments": [],
        "conversionHistory": None,
        "packageName": None,
        "packageVersion": "1.0.0",
        "profileActions": [],
    }


def _application_info(profile_name: str, device_type: str) -> dict[str, Any]:
    return {
        "$type": "Loupedeck.Service.SupportedApplicationInfo, LoupedeckService",
        "name": "@_defaultwin",
        "displayName": "Default",
        "deviceType": device_type,
        "nativePluginName": "DefaultWin",
        "hasNativePlugin": True,
        "processOrBundleName": "",
        "defaultProfileName": profile_name,
        "isEnabled": True,
        "modes": [
            {
                "$type": "Loupedeck.Service.ApplicationMode, LoupedeckService",
                "name": "System",
                "displayName": "System",
            }
        ],
    }


def _touch_page(name: str, display_name: str, action_ids: list[str], slots: int) -> dict[str, Any]:
    controls = []
    padded_actions = [*action_ids, *[""] * max(0, slots - len(action_ids))]
    for action_id in padded_actions[:slots]:
        controls.append(
            {
                "$type": "Loupedeck.Service.ProfileLayoutButton, LoupedeckService",
                "pressAction": action_id,
                "fnPressAction": None,
            }
        )
    return {
        "$type": "Loupedeck.Service.ProfileLayoutButtonPage, LoupedeckService",
        "name": name,
        "displayName": display_name,
        "description": None,
        "controls": controls,
        "dynamicPageName": None,
        "dynamicPagePluginName": None,
        "dynamicPageNumber": 0,
    }


def _encoder_page(name: str, display_name: str) -> dict[str, Any]:
    return {
        "$type": "Loupedeck.Service.ProfileLayoutEncoderPage, LoupedeckService",
        "name": name,
        "displayName": display_name,
        "description": None,
        "controls": [
            {
                "$type": "Loupedeck.Service.ProfileLayoutEncoder, LoupedeckService",
                "pressAction": None,
                "fnPressAction": None,
                "rotateAction": None,
                "fnRotateAction": None,
            }
            for _ in range(6)
        ],
        "dynamicPageName": None,
        "dynamicPagePluginName": None,
        "dynamicPageNumber": 0,
    }


def _write_plugin_source(out_dir: Path, catalog: dict[str, Any]) -> None:
    plugin_dir = out_dir / "plugin-src" / PLUGIN_NAME
    package_dir = plugin_dir / "package"
    (plugin_dir / "Actions").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "Gp180").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "Helpers").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "Midi").mkdir(parents=True, exist_ok=True)
    (package_dir / "metadata").mkdir(parents=True, exist_ok=True)

    _write_text(plugin_dir / f"{PLUGIN_NAME}.csproj", _csproj())
    _write_text(plugin_dir / f"{PLUGIN_NAME}Plugin.cs", _plugin_cs())
    _write_text(plugin_dir / "Actions" / "Gp180ProfileCommand.cs", _profile_command_cs())
    _write_text(plugin_dir / "Actions" / "FretWiseRecommendCommand.cs", _recommend_command_cs())
    _write_text(plugin_dir / "Actions" / "Gp180PlannedCommand.cs", _planned_command_cs())
    _write_text(plugin_dir / "Gp180" / "Gp180Catalog.cs", _catalog_cs())
    _write_text(plugin_dir / "Gp180" / "Gp180Profile.cs", _profile_cs())
    _write_text(plugin_dir / "Helpers" / "PluginLog.cs", _plugin_log_cs())
    _write_text(plugin_dir / "Midi" / "WinMidiOut.cs", _win_midi_out_cs())
    _write_text(package_dir / "metadata" / "LoupedeckPackage.yaml", _package_yaml())
    _write_json(package_dir / "gp180_profiles.json", _plugin_profiles(catalog))
    _write_text(plugin_dir / "README.md", _plugin_readme())


def _plugin_profiles(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = []
    seen: set[str] = set()
    for action in _ready_direct_midi_actions(catalog):
        profile_id = str(action.get("profile_id") or "")
        if not profile_id or profile_id in seen:
            continue
        seen.add(profile_id)
        midi = action.get("midi", [])
        program = 0
        bank_msb = 0
        channel = 0
        if isinstance(midi, list):
            for message in midi:
                if not isinstance(message, list) or not message:
                    continue
                status = int(message[0])
                channel = status & 0x0F
                if status & 0xF0 == 0xB0 and len(message) >= 3 and int(message[1]) == 0:
                    bank_msb = int(message[2])
                if status & 0xF0 == 0xC0 and len(message) >= 2:
                    program = int(message[1])
        profiles.append(
            {
                "id": profile_id,
                "label": str(action.get("label") or profile_id),
                "genre": str(action.get("genre") or ""),
                "group": _profile_group(str(action.get("genre") or "")),
                "channel": channel,
                "bankMsb": bank_msb,
                "program": program,
            }
        )
    return sorted(profiles, key=lambda item: (int(item["bankMsb"]), int(item["program"])))


def _csproj() -> str:
    return dedent(
        """\
        <Project Sdk="Microsoft.NET.Sdk">
          <PropertyGroup>
            <TargetFramework>net8.0</TargetFramework>
            <ImplicitUsings>enable</ImplicitUsings>
            <Nullable>enable</Nullable>
            <RootNamespace>ValetonGP180</RootNamespace>
            <AssemblyName>ValetonGP180Plugin</AssemblyName>
            <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>
            <CopyLocalLockFileAssemblies>true</CopyLocalLockFileAssemblies>
            <OutputPath>bin\\$(Configuration)\\bin\\</OutputPath>
            <PluginName>ValetonGP180</PluginName>
          </PropertyGroup>

          <ItemGroup>
            <Reference Include="PluginApi">
              <HintPath>C:\\Program Files\\Logi\\LogiPluginService\\PluginApi.dll</HintPath>
            </Reference>
          </ItemGroup>

          <Target Name="CopyPackage" AfterTargets="Build">
            <ItemGroup>
              <PackageFiles Include="package\\**\\*" />
            </ItemGroup>
            <Copy SourceFiles="@(PackageFiles)" DestinationFolder="$(OutputPath)..\\%(RecursiveDir)" />
          </Target>

          <Target Name="WritePluginLink" AfterTargets="Build">
            <MakeDir Directories="$(LOCALAPPDATA)\\Logi\\LogiPluginService\\Plugins" />
            <WriteLinesToFile
              File="$(LOCALAPPDATA)\\Logi\\LogiPluginService\\Plugins\\$(PluginName).link"
              Lines="$(MSBuildProjectDirectory)\\bin\\$(Configuration)"
              Overwrite="true" />
          </Target>
        </Project>
        """
    )


def _plugin_cs() -> str:
    return dedent(
        """\
        namespace ValetonGP180;

        using ValetonGP180.Gp180;
        using Loupedeck;

        public class ValetonGP180Plugin : Plugin
        {
            public override Boolean UsesApplicationApiOnly => true;

            public override Boolean HasNoApplication => true;

            public ValetonGP180Plugin()
            {
                PluginLog.Init(this.Log);
            }

            public override void Load()
            {
                try
                {
                    Gp180Catalog.Load();
                    PluginLog.Info("FretWise GP-180 loaded; profile actions use direct MIDI.");
                }
                catch (Exception ex)
                {
                    PluginLog.Error(ex, "FretWise GP-180 load failed.");
                }
            }

            public override void Unload()
            {
                try
                {
                    ValetonGP180.Midi.WinMidiOut.Shutdown();
                }
                catch (Exception ex)
                {
                    PluginLog.Error(ex, "FretWise GP-180 unload failed.");
                }
            }
        }
        """
    )


def _profile_command_cs() -> str:
    return dedent(
        """\
        namespace ValetonGP180.Actions;

        using ValetonGP180.Gp180;
        using ValetonGP180.Midi;
        using Loupedeck;

        public sealed class Gp180ProfileCommand : PluginDynamicCommand
        {
            public Gp180ProfileCommand()
                : base("GP-180 Profile", "Send a GP-180 Program Change.", "GP-180")
            {
            }

            protected override Boolean OnLoad()
            {
                this.RemoveAllParameters();
                foreach (var profile in Gp180Catalog.Profiles)
                {
                    this.AddParameter(profile.Id, profile.Label, profile.Group);
                }

                this.ParametersChanged();
                return true;
            }

            protected override void RunCommand(String actionParameter)
            {
                var profile = Gp180Catalog.FindProfile(actionParameter);
                if (profile is null)
                {
                    PluginLog.Warning($"Unknown GP-180 profile '{actionParameter}'.");
                    return;
                }

                WinMidiOut.SendPreset(profile.Channel, profile.BankMsb, profile.Program);
                PluginLog.Info($"GP-180 preset sent: {profile.Label} ({profile.Id}).");
            }
        }
        """
    )


def _recommend_command_cs() -> str:
    return dedent(
        """\
        namespace ValetonGP180.Actions;

        using Loupedeck;

        public sealed class FretWiseRecommendCommand : PluginDynamicCommand
        {
            public FretWiseRecommendCommand()
                : base("FretWise Recommend", "Ask FretWise for a contextual preset.", "GP-180")
            {
            }

            protected override void RunCommand(String actionParameter)
            {
                PluginLog.Warning(
                    "Recommendation needs FretWise song context. Use the FretWise UI for now.");
            }
        }
        """
    )


def _planned_command_cs() -> str:
    return dedent(
        """\
        namespace ValetonGP180.Actions;

        using Loupedeck;

        public sealed class Gp180PlannedCommand : PluginDynamicCommand
        {
            public Gp180PlannedCommand()
                : base("GP-180 Planned", "Placeholder for unverified GP-180 controls.", "GP-180")
            {
            }

            protected override void RunCommand(String actionParameter)
            {
                PluginLog.Warning($"GP-180 command not implemented yet: {actionParameter}.");
            }
        }
        """
    )


def _catalog_cs() -> str:
    return dedent(
        """\
        namespace ValetonGP180.Gp180;

        using System.Text.Json;

        internal static class Gp180Catalog
        {
            private static IReadOnlyList<Gp180Profile> _profiles = Array.Empty<Gp180Profile>();

            public static IReadOnlyList<Gp180Profile> Profiles => _profiles;

            public static void Load()
            {
                var path = FindCatalogPath();
                if (!File.Exists(path))
                {
                    PluginLog.Warning($"GP-180 catalog not found: {path}");
                    _profiles = Array.Empty<Gp180Profile>();
                    return;
                }

                var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
                var json = File.ReadAllText(path);
                _profiles = JsonSerializer.Deserialize<List<Gp180Profile>>(json, options)
                    ?? new List<Gp180Profile>();
                PluginLog.Info($"Loaded {_profiles.Count} GP-180 profiles.");
            }

            public static Gp180Profile? FindProfile(String id) =>
                _profiles.FirstOrDefault(profile =>
                    String.Equals(profile.Id, id, StringComparison.OrdinalIgnoreCase));

            private static String FindCatalogPath()
            {
                var rootPath = Path.Combine(AppContext.BaseDirectory, "gp180_profiles.json");
                if (File.Exists(rootPath))
                {
                    return rootPath;
                }

                return Path.Combine(AppContext.BaseDirectory, "package", "gp180_profiles.json");
            }
        }
        """
    )


def _profile_cs() -> str:
    return dedent(
        """\
        namespace ValetonGP180.Gp180;

        internal sealed record Gp180Profile(
            String Id,
            String Label,
            String Genre,
            String Group,
            Int32 Channel,
            Int32 BankMsb,
            Int32 Program);
        """
    )


def _plugin_log_cs() -> str:
    return dedent(
        """\
        namespace ValetonGP180;

        using Loupedeck;

        internal static class PluginLog
        {
            private static PluginLogFile? _pluginLogFile;

            public static void Init(PluginLogFile pluginLogFile) => _pluginLogFile = pluginLogFile;

            public static void Info(String text) => _pluginLogFile?.Info(text);

            public static void Warning(String text) => _pluginLogFile?.Warning(text);

            public static void Error(Exception ex, String text) =>
                _pluginLogFile?.Error(ex, text);
        }
        """
    )


def _win_midi_out_cs() -> str:
    return dedent(
        """\
        namespace ValetonGP180.Midi;

        using System.Runtime.InteropServices;
        using System.Text;

        internal static class WinMidiOut
        {
            private static IntPtr _handle = IntPtr.Zero;

            public static void Initialize()
            {
                Shutdown();
                var deviceId = FindGp180Device();
                if (deviceId < 0)
                {
                    PluginLog.Warning("No MIDI output device found for GP-180.");
                    return;
                }

                var result = midiOutOpen(out _handle, deviceId, IntPtr.Zero, IntPtr.Zero, 0);
                if (result != 0)
                {
                    PluginLog.Warning($"midiOutOpen failed for device {deviceId}: {result}.");
                    _handle = IntPtr.Zero;
                    return;
                }

                PluginLog.Info($"Opened MIDI output device {deviceId}: {GetDeviceName(deviceId)}.");
            }

            public static void Shutdown()
            {
                if (_handle == IntPtr.Zero)
                {
                    return;
                }

                midiOutClose(_handle);
                _handle = IntPtr.Zero;
            }

            public static void SendPreset(Int32 channel, Int32 bankMsb, Int32 program)
            {
                if (_handle == IntPtr.Zero)
                {
                    Initialize();
                }

                if (_handle == IntPtr.Zero)
                {
                    return;
                }

                SendShort(0xB0 | (channel & 0x0F), 0, bankMsb);
                SendShort(0xC0 | (channel & 0x0F), program, 0);
            }

            private static void SendShort(Int32 status, Int32 data1, Int32 data2)
            {
                var message = status | (data1 << 8) | (data2 << 16);
                var result = midiOutShortMsg(_handle, message);
                if (result != 0)
                {
                    PluginLog.Warning($"midiOutShortMsg failed: {result}.");
                }
            }

            private static Int32 FindGp180Device()
            {
                var preferred = Environment.GetEnvironmentVariable("FRETWISE_GP180_MIDI_OUT");
                var count = midiOutGetNumDevs();
                for (var index = 0; index < count; index++)
                {
                    var name = GetDeviceName(index);
                    if (!String.IsNullOrWhiteSpace(preferred)
                        && name.Contains(preferred, StringComparison.OrdinalIgnoreCase))
                    {
                        return index;
                    }
                }

                for (var index = 0; index < count; index++)
                {
                    var name = GetDeviceName(index);
                    if (name.Contains("GP-180", StringComparison.OrdinalIgnoreCase)
                        || name.Contains("GP180", StringComparison.OrdinalIgnoreCase)
                        || name.Contains("Valeton", StringComparison.OrdinalIgnoreCase))
                    {
                        return index;
                    }
                }

                return count > 0 ? 0 : -1;
            }

            private static String GetDeviceName(Int32 deviceId)
            {
                var caps = new MIDIOUTCAPS();
                var result = midiOutGetDevCaps(
                    (UIntPtr)deviceId,
                    ref caps,
                    (UInt32)Marshal.SizeOf<MIDIOUTCAPS>());
                return result == 0 ? caps.szPname : String.Empty;
            }

            [DllImport("winmm.dll")]
            private static extern Int32 midiOutGetNumDevs();

            [DllImport("winmm.dll")]
            private static extern Int32 midiOutOpen(
                out IntPtr handle,
                Int32 deviceId,
                IntPtr callback,
                IntPtr instance,
                Int32 flags);

            [DllImport("winmm.dll")]
            private static extern Int32 midiOutShortMsg(IntPtr handle, Int32 message);

            [DllImport("winmm.dll")]
            private static extern Int32 midiOutClose(IntPtr handle);

            [DllImport("winmm.dll", CharSet = CharSet.Auto)]
            private static extern Int32 midiOutGetDevCaps(
                UIntPtr deviceId,
                ref MIDIOUTCAPS caps,
                UInt32 size);

            [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
            private struct MIDIOUTCAPS
            {
                public UInt16 wMid;
                public UInt16 wPid;
                public UInt32 vDriverVersion;

                [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
                public String szPname;

                public UInt16 wTechnology;
                public UInt16 wVoices;
                public UInt16 wNotes;
                public UInt16 wChannelMask;
                public UInt32 dwSupport;
            }
        }
        """
    )


def _package_yaml() -> str:
    return dedent(
        """\
        type: plugin4
        name: ValetonGP180
        displayName: Valeton GP-180
        description: Direct MIDI control for Valeton GP-180 presets.
        pluginFileName: ValetonGP180Plugin.dll
        version: 0.1.0
        author: FretWise
        copyright: FretWise
        pluginFolderWin: bin
        supportedDevices:
          - LoupedeckCtFamily
        pluginCapabilities: []
        minimumLoupedeckVersion: 6.0
        """
    )


def _plugin_readme() -> str:
    return dedent(
        """\
        # ValetonGP180 Loupedeck plugin

        This plugin sends GP-180 preset selection over MIDI directly from
        Loupedeck. FretWise is not in the activation path.

        Build:

        ```powershell
        dotnet build .\\ValetonGP180.csproj -c Debug
        ```

        The project writes a `.link` file into:

        `%LOCALAPPDATA%\\Logi\\LogiPluginService\\Plugins\\ValetonGP180.link`

        The MIDI output is auto-selected by name: `GP-180`, `GP180`, or
        `Valeton`. To force a port, set:

        ```powershell
        $env:FRETWISE_GP180_MIDI_OUT = "GP-180"
        ```
        """
    )


def _write_readme(out_dir: Path, rig_bank_path: Path, catalog: dict[str, Any]) -> None:
    actions = catalog.get("actions", [])
    direct = sum(
        1
        for action in actions
        if isinstance(action, dict) and action.get("loupedeck_route") == "direct_midi"
    )
    contextual = sum(
        1
        for action in actions
        if isinstance(action, dict) and action.get("loupedeck_route") == "fretwise_required"
    )
    planned = sum(
        1 for action in actions if isinstance(action, dict) and action.get("status") == "planned"
    )
    text = f"""# FretWise GP-180 Loupedeck CT/S

Generated from `{rig_bank_path}`.

## Importable files

- `GP180_CT.lp5`: starter profile for Loupedeck CT.
- `GP180_S.lp5`: starter profile for Loupedeck S / Live S family.
- `plugin-src/ValetonGP180`: C# Loupedeck plugin source.

Build and install the plugin first, then import the `.lp5` profile in the
Loupedeck application. The profile buttons reference plugin actions such as:

`$ValetonGP180___ValetonGP180.Actions.Gp180ProfileCommand___gp180-046-back-in-dc`

## Routing

- Direct MIDI actions: {direct}
- FretWise contextual actions: {contextual}
- Planned actions awaiting verified GP-180 CC/SysEx: {planned}

Profile and genre buttons send `CC0 bank select` followed by `Program Change`
directly from the Loupedeck plugin to the GP-180.

FretWise is only needed when a button must resolve context, for example:
current song, artist, genre, or the recommended profile.

## Reference files

- `gp180_control_surface_catalog.json`: complete action/layout catalog.
- `direct_midi_reference.csv`: profile IDs, action IDs, and raw MIDI bytes.
- `CT_*.csv` and `S_*.csv`: page plans for manual editing or regeneration.

"""
    _write_text(out_dir / "README.md", text)


def _action_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(action["id"]): action
        for action in catalog.get("actions", [])
        if isinstance(action, dict) and action.get("id")
    }


def _ready_direct_midi_actions(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        action
        for action in catalog.get("actions", [])
        if isinstance(action, dict)
        and action.get("status") == "ready"
        and action.get("loupedeck_route") == "direct_midi"
        and action.get("midi")
    ]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["index", "display_name", "kind", "action_id"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _zip_dir(source_dir: Path, target: Path) -> None:
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            archive.write(file_path, file_path.relative_to(source_dir).as_posix())


def _short_label(label: str) -> str:
    clean = label.replace("GP-180", "").strip()
    if len(clean) <= 18:
        return clean
    return clean[:15].rstrip() + "..."


def _color_for_action(action: dict[str, Any]) -> str:
    if action.get("status") != "ready":
        return "#6B7280"
    group = str(action.get("group") or "")
    if group == "Genres":
        return "#1D4ED8"
    if group == "Profiles":
        return "#047857"
    if group == "Live":
        return "#B45309"
    return "#374151"


def _midi_hex(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    parts = []
    for message in messages:
        if isinstance(message, list):
            parts.append(" ".join(f"{int(byte):02X}" for byte in message))
    return " | ".join(parts)


def _profile_group(genre: str) -> str:
    if not genre:
        return "GP-180 - Profiles"
    return f"GP-180 - {genre.title()}"


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_") or "page"


def _guid() -> str:
    return uuid.uuid4().hex.upper()


if __name__ == "__main__":
    main()
