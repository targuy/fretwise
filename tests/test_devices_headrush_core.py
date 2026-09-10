"""Tests for the read-only HeadRush Core driver.

The device is a physical box on the LAN, so everything here runs against a fake
transport built from the shape of a real ``subtree`` dump. The values are the
ones actually observed on firmware 5.1.0.2a63755 (see ``docs/headrush_core.md``).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fretwise.devices.headrush_core import (
    CATALOG_SCHEMA_VERSION,
    ChainSlot,
    CoreClient,
    DeviceIdentity,
    DeviceSnapshot,
    RigSnapshot,
    RigSummary,
    UnsafeMethodError,
    build_catalog,
    capture_rig,
    catalog_path,
    default_snapshot_path,
    diff_snapshots,
    load_snapshot,
    parse_blocks,
    resolve_host,
    write_catalog,
    write_snapshot,
)
from fretwise.devices.headrush_core.catalog import ParamSchema, load_catalog
from fretwise.devices.headrush_core.chain import (
    FREE_SLOTS,
    FROZEN_HEAD,
    REVERB_SLOT,
    ChainError,
    Placement,
    assign_slots,
    check_relocation,
    placement_calls,
    validate_order,
)
from fretwise.devices.headrush_core.client import DEFAULT_HOST, HOST_ENV_VAR
from fretwise.devices.headrush_core.params import (
    ALGO_NAMES,
    ALGOS_IN_USE,
    ParamError,
    device_value,
    enum_index,
    enum_label,
    format_display,
    fround,
    round_trip_error,
    to_display,
    to_normalized,
    within_grid,
)
from fretwise.devices.headrush_core.plan import (
    BINDING_SCHEMA_VERSION,
    GENERATED_PREFIX,
    PlanError,
    Step,
    build_plan,
    load_binding,
)
from fretwise.devices.headrush_core.pusher import (
    WRITE_ENV_VAR,
    WriteRefused,
    apply_plan,
    plan_token,
)

# --- fake device -------------------------------------------------------------

_MODULE_TYPES = [
    "Empty Slot", "Amp", "Amp 2", "ReValver Amp", "ReValver Amp 2", "ReValver Cab",
    "ReValver Cab 2", "Cab", "Cab 2", "IR", "IR 2",
    # appended, so the indices asserted elsewhere stay valid
    "BBD Delay", "BBD Delay 2",
]

_PATCH_SUBTREE: dict[str, Any] = {
    "/Evil/Engine/Patch/Amp": {
        "meta": {
            "properties": {
                "GainA": {
                    "type": "number", "minimum": 0.0, "maximum": 100.0,
                    "x-options": {"default": 0.5, "format": "%.0f %%", "grid": 1.0},
                },
                "Type": {
                    "type": "integer", "minimum": 0.0, "maximum": 2.0,
                    "x-options": {
                        "strings": ["59 Tweed Deluxe", "64 Black Lux Vib", "82 Lead 800"]
                    },
                },
                "On": {"type": "boolean", "x-options": {"default": True}},
                "labels": {"type": "array"},
                "order": {"type": "array"},
            }
        },
        "value": {"GainA": 0.5, "Type": 1, "On": True, "labels": ["Gain"], "order": ["GainA"]},
    },
    "/Evil/Engine/Patch/BBD_Delay": {
        "meta": {
            "properties": {
                "Time": {
                    "type": "number", "minimum": 32.0, "maximum": 1520.0,
                    "x-options": {"default": 0.18010753, "format": "%.0f ms", "normalizeAlgo": 3},
                },
                "Mix": {
                    "type": "number", "minimum": 0.0, "maximum": 100.0,
                    "x-options": {"default": 0.3, "format": "%.0f %%"},
                },
            }
        },
        "value": {"Time": 0.18010753, "Mix": 0.3},
    },
    # Non-block objects that share the Patch root must be skipped.
    "/Evil/Engine/Patch/Chain": {
        "meta": {"properties": {"ModuleType1": {"type": "integer"}}},
        "value": {"ModuleType1": 1},
    },
}


class FakeTransport:
    """In-memory stand-in for a real device, satisfying ``DeviceTransport``."""

    def __init__(self, **overrides: Any) -> None:
        self.calls: list[tuple[str, str, list[Any]]] = []
        self._properties: dict[str, dict[str, Any]] = {
            "/Evil/Gui": {
                "AppVersion": "5.1.0.2a63755",
                "DeviceName": "HeadRush Core_3570",
            },
            "/Evil/API/Rigs": {
                "product": "HV01",
                "AllRigIds": ["id-a", "id-b", "id-c"],
                "AllRigNames": ["#HR - 01 Super Classic Crunch", "Lorenzo solo 1", "Accoustique"],
                "AllRigColors": [9, 4, 5],
                "loadedID": "id-b",
                "loadedName": "Lorenzo solo 1",
                "loadedColor": 4,
                "loadedProgMIDICC": -1,
                "availableProgMIDICC": list(range(128)),
            },
            "/Evil/API/Blocks": {
                "ModuleTypes": _MODULE_TYPES,
                "BlockSelectorCategories": ["Amp", "Cab"],
            },
            "/Evil/Engine/Patch/Chain": {
                "ModuleType1": 1, "ModuleType2": 7, "ModuleType3": 9,
                **{f"ModuleType{n}": 0 for n in range(4, 15)},
            },
            "/Evil/Engine/CPUMeter": {"CPUTimeSmoothed": 0.295},
            "/Evil/Engine/Settings/Midi": {
                "Channel": 0, "ReceiveProgramChange": True, "MBCIn": True, "MIDIThrough": False,
            },
            "/Evil/Engine/Settings/General": {"AutoAmpCab": True, "AutoAssignments": True},
        }
        for path, patch in overrides.items():
            self._properties.setdefault(path.replace("__", "/"), {}).update(patch)

    def subtree(self, path: str) -> dict[str, Any]:
        return {k: v for k, v in _PATCH_SUBTREE.items() if k.startswith(path)}

    def meta(self, path: str) -> dict[str, Any]:
        node = _PATCH_SUBTREE.get(path) or {}
        return node.get("meta") or {}

    def properties(self, path: str) -> dict[str, Any]:
        if path in self._properties:
            return dict(self._properties[path])
        # Block parameter objects live in the Patch subtree. Only the two blocks
        # defined above exist here, so a chain referencing anything else models a
        # module whose Patch object cannot be resolved.
        node = _PATCH_SUBTREE.get(path) or {}
        return dict(node.get("value") or {})

    def query(self, path: str, method: str, arguments: list[Any]) -> Any:
        self.calls.append((path, method, arguments))
        return {"Amp": ["Amp", "ReValver Amp"], "Cab": ["Cab", "IR"]}[arguments[0]]


# --- host resolution ---------------------------------------------------------


def test_resolve_host_explicit_argument_wins_over_environment(monkeypatch):
    monkeypatch.setenv(HOST_ENV_VAR, "192.168.1.50")
    assert resolve_host("10.0.0.9") == "10.0.0.9"


def test_resolve_host_falls_back_to_environment_then_default(monkeypatch):
    monkeypatch.setenv(HOST_ENV_VAR, "192.168.1.50")
    assert resolve_host(None) == "192.168.1.50"
    monkeypatch.delenv(HOST_ENV_VAR)
    assert resolve_host(None) == DEFAULT_HOST


# --- the read-only guarantee -------------------------------------------------


def test_query_unlisted_method_raises_before_any_network_call():
    client = CoreClient("unreachable.invalid")
    with pytest.raises(UnsafeMethodError):
        client.query("/Evil/API/Rigs", "deleteRig", ["id-a"])


@pytest.mark.parametrize(
    "path,method",
    [
        ("/Evil/API/Rigs", "saveRigAs"),
        ("/Evil/API/Rigs", "makeNewRig"),
        ("/Evil/API/Rigs", "loadRig"),
        ("/Evil/Engine/Patch/Chain", "setModuleTypeInternal"),
        ("/Evil/API/Blocks", "deserializeBlock"),
        ("/Evil/API/Setlists", "saveSetlist"),
    ],
)
def test_query_refuses_every_mutating_method(path, method):
    client = CoreClient("unreachable.invalid")
    with pytest.raises(UnsafeMethodError):
        client.query(path, method, [])


def test_client_exposes_no_write_members():
    """The read path must not grow a writer by accident."""
    forbidden = {"put", "set_properties", "write", "call_method", "save", "apply"}
    assert forbidden.isdisjoint({name for name in dir(CoreClient) if not name.startswith("_")})


# --- catalog parsing ---------------------------------------------------------


def test_parse_blocks_skips_chain_and_keeps_real_blocks():
    blocks = parse_blocks(_PATCH_SUBTREE)
    assert [b.name for b in blocks] == ["Amp", "BBD_Delay"]


def test_parse_blocks_reads_enum_labels_from_x_options():
    amp = next(b for b in parse_blocks(_PATCH_SUBTREE) if b.name == "Amp")
    amp_type = amp.param("Type")
    assert amp_type is not None
    assert amp_type.is_enum
    assert amp_type.options == ("59 Tweed Deluxe", "64 Black Lux Vib", "82 Lead 800")


def test_parse_blocks_keeps_display_units_and_grid():
    amp = next(b for b in parse_blocks(_PATCH_SUBTREE) if b.name == "Amp")
    gain = amp.param("GainA")
    assert gain is not None
    assert (gain.minimum, gain.maximum) == (0.0, 100.0)
    assert gain.unit_format == "%.0f %%"
    assert gain.grid == 1.0


def test_parse_blocks_drops_ui_only_keys():
    amp = next(b for b in parse_blocks(_PATCH_SUBTREE) if b.name == "Amp")
    assert {p.name for p in amp.params} == {"GainA", "Type", "On"}
    assert amp.labels == ("Gain",)


def test_delay_ratio_parameter_is_flagged_unsafe_to_write():
    """normalizeAlgo 3 has no denormalization entry, even in the device's own UI."""
    delay = next(b for b in parse_blocks(_PATCH_SUBTREE) if b.name == "BBD_Delay")
    time = delay.param("Time")
    mix = delay.param("Mix")
    assert time is not None and mix is not None
    assert time.normalize_algo == 3
    assert not time.is_writable_safely
    assert mix.is_writable_safely


def test_second_instance_suffix_is_detected():
    blocks = parse_blocks(
        {"/Evil/Engine/Patch/Cab_2": {"meta": {"properties": {"CabType": {"type": "integer"}}}}}
    )
    assert blocks[0].is_second_instance


# --- catalog assembly --------------------------------------------------------


def test_build_catalog_captures_firmware_anchor():
    catalog = build_catalog(FakeTransport())
    assert catalog.schema_version == CATALOG_SCHEMA_VERSION
    assert catalog.app_version == "5.1.0.2a63755"
    assert catalog.product == "HV01"
    assert catalog.device_name == "HeadRush Core_3570"


def test_build_catalog_resolves_category_blocks_via_allow_listed_query():
    transport = FakeTransport()
    catalog = build_catalog(transport)
    assert catalog.category_blocks["Amp"] == ("Amp", "ReValver Amp")
    assert [c[1] for c in transport.calls] == ["categoryBlocks", "categoryBlocks"]


def test_build_catalog_without_categories_makes_no_method_calls():
    transport = FakeTransport()
    catalog = build_catalog(transport, with_categories=False)
    assert transport.calls == []
    assert catalog.category_blocks == {}


def test_module_type_id_round_trips_through_names():
    catalog = build_catalog(FakeTransport(), with_categories=False)
    assert catalog.module_type_id("IR") == 9
    assert catalog.module_types[9] == "IR"
    assert catalog.module_type_id("Nonexistent Block") is None


def test_contract_hash_changes_when_module_table_shifts():
    """A firmware that inserts a module must invalidate the pinned contract."""
    base = build_catalog(FakeTransport(), with_categories=False)
    shifted = FakeTransport()
    shifted._properties["/Evil/API/Blocks"]["ModuleTypes"] = ["Empty Slot", "New Block"] + (
        _MODULE_TYPES[1:]
    )
    assert build_catalog(shifted, with_categories=False).contract_hash != base.contract_hash


def test_catalog_block_lookup_accepts_spaces_or_underscores():
    catalog = build_catalog(FakeTransport(), with_categories=False)
    assert catalog.block("BBD Delay") is not None
    assert catalog.block("BBD_Delay") is not None


def test_write_catalog_emits_readable_json(tmp_path: Path):
    catalog = build_catalog(FakeTransport(), with_categories=False)
    destination = write_catalog(catalog, tmp_path / "cat.json")
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["appVersion"] == "5.1.0.2a63755"
    assert payload["moduleTypes"][9] == "IR"
    assert payload["contractHash"] == catalog.contract_hash


def test_catalog_path_is_versioned_on_firmware(tmp_path: Path):
    catalog = build_catalog(FakeTransport(), with_categories=False)
    path = catalog_path(tmp_path, catalog)
    assert path.parent == tmp_path / "devices" / "headrush-core" / "catalog"
    assert path.name == "5.1.0.2a63755.json"


# --- snapshot semantics ------------------------------------------------------


def _snapshot_via_client() -> DeviceSnapshot:
    """Build a snapshot through CoreClient's logic but a fake transport."""
    transport = FakeTransport()
    client = CoreClient("unreachable.invalid")
    client.properties = transport.properties  # type: ignore[method-assign]
    return client.snapshot()


def test_snapshot_reports_cpu_on_the_device_display_scale():
    """object-meta declares maximum 200, so 0.295 is 59 % on screen, not 29 %."""
    assert _snapshot_via_client().cpu_percent == pytest.approx(59.0)


def test_snapshot_maps_chain_slots_to_module_names():
    chain = _snapshot_via_client().chain
    assert len(chain) == 14
    assert chain[0] == ChainSlot(slot=1, module_type=1, module_name="Amp")
    assert chain[2].module_name == "IR"
    assert chain[3].is_empty


def test_snapshot_treats_unassigned_program_change_as_none():
    """The device stores -1 for 'no MIDI PROG'; that must not leak as a number."""
    assert _snapshot_via_client().loaded_rig.program_change is None


def test_assigned_program_changes_is_the_complement_of_available():
    snapshot = DeviceSnapshot(
        identity=DeviceIdentity("v", "n", "p"),
        loaded_rig=RigSummary("id", "name", 0),
        rigs=(),
        chain=(),
        cpu_percent=0.0,
        midi_settings={},
        general_settings={},
        available_program_changes=tuple(pc for pc in range(128) if pc not in {3, 17}),
    )
    assert snapshot.assigned_program_changes == (3, 17)


def test_snapshot_lists_every_stored_rig_with_its_colour():
    rigs = _snapshot_via_client().rigs
    assert len(rigs) == 3
    assert rigs[1] == RigSummary(rig_id="id-b", name="Lorenzo solo 1", colour=4)


# --- rig snapshots -----------------------------------------------------------


def _capture() -> RigSnapshot:
    """Capture a snapshot from the fake device at a fixed timestamp."""
    return capture_rig(FakeTransport(), now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC))


def test_capture_rig_reads_only_blocks_present_in_the_chain():
    """A rig is defined by its occupied slots, not by all 282 Patch objects."""
    snapshot = _capture()
    assert set(snapshot.blocks) == {"Amp"}
    assert len(snapshot.occupied_slots) == 3


def test_capture_rig_records_the_firmware_it_was_taken_on():
    snapshot = _capture()
    assert snapshot.identity.app_version == "5.1.0.2a63755"
    assert snapshot.captured_at == "2026-09-10T12:00:00+00:00"


def test_capture_rig_flags_chain_modules_with_no_patch_object():
    """A module the Patch tree cannot resolve must be reported, not dropped."""
    snapshot = _capture()
    assert "Cab" in {s.module_name for s in snapshot.occupied_slots}
    assert "Cab" in snapshot.unresolved_modules


def test_snapshot_round_trips_through_disk(tmp_path: Path):
    original = _capture()
    restored = load_snapshot(write_snapshot(original, tmp_path / "rig.json"))
    assert restored.rig_id == original.rig_id
    assert restored.chain == original.chain
    assert restored.blocks == original.blocks
    assert diff_snapshots(original, restored) == []


def test_load_snapshot_rejects_a_foreign_document(tmp_path: Path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"schemaVersion": "something.else.v9"}), encoding="utf-8")
    with pytest.raises(ValueError, match="not a fretwise.device.state"):
        load_snapshot(path)


def test_diff_reports_a_changed_block_parameter():
    before = _capture()
    after = _capture()
    after.blocks["Amp"]["GainA"] = 0.75
    changes = diff_snapshots(before, after)
    assert [str(c) for c in changes] == ["blocks.Amp.GainA: 0.5 -> 0.75"]


def test_diff_reports_a_changed_chain_slot():
    before = _capture()
    after = _capture()
    changed = list(after.chain)
    changed[0] = ChainSlot(slot=1, module_type=9, module_name="IR")
    after_with_chain = replace(after, chain=tuple(changed))
    assert [str(c) for c in diff_snapshots(before, after_with_chain)] == [
        "chain.slot1: 'Amp' -> 'IR'"
    ]


def test_diff_ignores_float32_rounding_noise():
    """The device returns float32; an exact compare would flag noise every read."""
    before = _capture()
    after = _capture()
    after.blocks["Amp"]["GainA"] = 0.5 + 1e-9
    assert diff_snapshots(before, after) == []


def test_diff_reports_program_change_assignment():
    before = _capture()
    after = replace(before, program_change=112)
    assert [str(c) for c in diff_snapshots(before, after)] == [
        "rig.programChange: None -> 112"
    ]


def test_default_snapshot_path_keys_on_guid_not_name(tmp_path: Path):
    """Rig names are editable on the device and not unique; GUIDs are stable."""
    path = default_snapshot_path(tmp_path, _capture())
    assert path.parent == tmp_path / "devices" / "headrush-core" / "backups"
    assert path.name == "id-b.json"


def test_assigned_program_changes_includes_the_loaded_rig_own_assignment():
    """The device offers a rig its own PC as 'available'; the raw complement misses it.

    Verified on hardware: from another rig the owner's PC was excluded (127 entries),
    but from the owning rig itself the list held all 128.
    """
    snapshot = DeviceSnapshot(
        identity=DeviceIdentity("v", "n", "p"),
        loaded_rig=RigSummary("id", "#FW - SCRATCH", 0, program_change=112),
        rigs=(),
        chain=(),
        cpu_percent=0.0,
        midi_settings={},
        general_settings={},
        available_program_changes=tuple(range(128)),  # 112 looks free to its owner
    )
    assert snapshot.assigned_program_changes == (112,)


def test_catalog_json_keeps_zero_valued_bounds():
    """0.0 == False in Python: a truthiness filter would drop `minimum: 0.0`.

    Most percentage parameters have a lower bound of exactly 0.0, and losing it
    would make every denormalization against that parameter wrong.
    """
    catalog = build_catalog(FakeTransport(), with_categories=False)
    amp = catalog.block("Amp")
    assert amp is not None
    gain = next(p for p in amp.params if p.name == "GainA")
    assert gain.minimum == 0.0
    payload = catalog.to_json()
    amp_json = next(b for b in payload["blocks"] if b["name"] == "Amp")
    gain_json = next(p for p in amp_json["params"] if p["name"] == "GainA")
    assert gain_json["minimum"] == 0.0, "minimum 0.0 was dropped from the artifact"
    assert gain_json["maximum"] == 100.0


# --- parameter conversion (parity with the device's own editor) ---------------

# Schemas transcribed from the real object-meta of firmware 5.1.0.2a63755.
_TEMPO = ParamSchema(name="Tempo", type="number", minimum=30.0, maximum=240.0,
                     unit_format="%.2f BPM", grid=0.01)
_DELAY = ParamSchema(name="Delay", type="number", minimum=32.0, maximum=1520.0,
                     unit_format="%.0f ms", grid=1.0)
_GAIN = ParamSchema(name="GainA", type="number", minimum=0.0, maximum=100.0,
                    unit_format="%.0f %%", grid=1.0)
_CPU = ParamSchema(name="CPUTimeSmoothed", type="number", minimum=0.0, maximum=200.0,
                   unit_format="%.0f %%", grid=1.0)
_LOCUT = ParamSchema(name="LoCut", type="number", minimum=20.0, maximum=5000.0,
                     unit_format="%.0f Hz", grid=1.0, normalize_algo=6)
_RVB_TIME = ParamSchema(name="Time", type="number", minimum=0.44999998807907104,
                        maximum=144.0, unit_format="%.1f sec", grid=0.1, normalize_algo=10)
_RATIO = ParamSchema(name="Ratio", type="number", minimum=0.0, maximum=1.0, normalize_algo=3)
_CABTYPE = ParamSchema(name="CabType", type="integer", minimum=0.0, maximum=14.0,
                       options=("1x8 Custom", "1x12 Black Panel Lux", "4x12 Green 25W"))
_ON = ParamSchema(name="On", type="boolean", default=True)


@pytest.mark.parametrize(
    "param,normalized,expected,tolerance",
    [
        # Read live off the device and cross-checked against its own screen.
        (_TEMPO, 0.4285714328289032, 120.0, 0.01),
        (_TEMPO, 0.5714286, 150.0, 0.01),
        (_DELAY, 0.18010753393173218, 300.0, 0.5),
        (_GAIN, 0.5, 50.0, 0.01),
        (_CPU, 0.295, 59.0, 0.01),
    ],
)
def test_to_display_matches_values_observed_on_the_device(param, normalized, expected, tolerance):
    assert to_display(param, normalized) == pytest.approx(expected, abs=tolerance)


def test_tempo_normalization_is_the_formula_used_against_the_hardware():
    """150 BPM was written to the device this way and the tuner showed 150.00."""
    assert to_normalized(_TEMPO, 150.0) == pytest.approx((150 - 30) / 210, abs=1e-6)


@pytest.mark.parametrize("param", [_TEMPO, _DELAY, _GAIN, _LOCUT, _RVB_TIME])
def test_round_trip_stays_within_one_grid_step(param):
    low = param.minimum or 0.0
    high = param.maximum or 1.0
    for fraction in (0.05, 0.25, 0.5, 0.75, 0.95):
        value = low + (high - low) * fraction
        assert within_grid(param, round_trip_error(param, value))


def test_normalized_output_is_float32_like_the_device_editor():
    """The editor applies Math.fround on the normalize direction; we must too."""
    value = to_normalized(_LOCUT, 1234.0)
    assert value == fround(value)


def test_delay_ratio_curve_is_refused_rather_than_guessed():
    with pytest.raises(ParamError, match="DelayRatio"):
        to_normalized(_RATIO, 0.5)


def test_out_of_range_value_is_refused():
    with pytest.raises(ParamError, match="outside"):
        to_normalized(_GAIN, 150.0)


def test_read_only_parameter_is_refused():
    ro = ParamSchema(name="loadedName", type="string", read_only=True)
    with pytest.raises(ParamError, match="read-only"):
        to_normalized(ro, 1.0)


def test_exponential_curve_spans_its_range_monotonically():
    values = [to_display(_LOCUT, x / 10) for x in range(11)]
    assert values == sorted(values)
    assert values[0] == pytest.approx(20.0, abs=0.01)
    assert values[-1] == pytest.approx(5000.0, abs=1.0)


def test_enum_is_addressed_by_label_not_index():
    """A stale index silently selects the wrong cab; a stale name raises."""
    assert enum_index(_CABTYPE, "4x12 Green 25W") == 2
    assert enum_label(_CABTYPE, 0) == "1x8 Custom"
    with pytest.raises(ParamError, match="not a valid option"):
        enum_index(_CABTYPE, "4x12 Greenback")


def test_device_value_dispatches_on_parameter_type():
    assert device_value(_ON, True) is True
    assert device_value(_CABTYPE, "1x12 Black Panel Lux") == 1
    assert device_value(_GAIN, 50.0) == pytest.approx(0.5, abs=1e-6)


def test_device_value_rejects_a_boolean_for_a_numeric_parameter():
    with pytest.raises(ParamError, match="expects a number"):
        device_value(_GAIN, True)


def test_format_display_uses_the_device_printf_pattern():
    assert format_display(_GAIN, 50.0) == "50 %"
    assert format_display(_TEMPO, 120.0) == "120.00 BPM"
    assert format_display(_DELAY, 300.0) == "300 ms"


def test_only_five_curves_are_exercised_by_this_firmware():
    """Documents the coverage gap instead of implying the other six are tested."""
    assert ALGOS_IN_USE == {0, 5, 6, 8, 10}
    assert set(ALGO_NAMES) - ALGOS_IN_USE == {1, 2, 3, 4, 7, 9}


# --- slot layout (derived from the 119-rig corpus) ----------------------------


def test_frozen_head_covers_slots_one_to_seven_and_reverb_closes():
    assert sorted(FROZEN_HEAD) == [1, 2, 3, 4, 5, 6, 7]
    assert FROZEN_HEAD[6] == "Amp"
    assert FROZEN_HEAD[7] == "Cab"
    assert REVERB_SLOT == 14
    assert set(FREE_SLOTS).isdisjoint(FROZEN_HEAD)


def test_bypass_cc_follows_the_manual_block_numbering():
    """Manual v5.1.0 p.71: CC 75-88 = Block 1..14 Toggle, and Block N is slot N."""
    assert Placement(1, "Gate", "Utility").bypass_cc == 75
    assert Placement(6, "Amp", "Amp").bypass_cc == 80
    assert Placement(14, "Eleven Reverb", "Reverb").bypass_cc == 88


def test_assign_slots_puts_head_categories_at_their_frozen_positions():
    placements = assign_slots([
        ("Gate", "Utility"), ("Black Wah", "Filter"), ("Green JRC-OD", "Overdrive"),
        ("Amp", "Amp"), ("Cab", "Cab"), ("Eleven Reverb", "Reverb"),
    ])
    by_slot = {p.slot: p.module for p in placements}
    assert by_slot[1] == "Gate"
    assert by_slot[2] == "Black Wah"
    assert by_slot[4] == "Green JRC-OD"
    assert by_slot[6] == "Amp"
    assert by_slot[7] == "Cab"
    assert by_slot[14] == "Eleven Reverb"


def test_assign_slots_accepts_a_clone_in_the_amp_position():
    """A NAM capture is category 'Clone' but occupies the amp slot."""
    placements = assign_slots([("Neural Amp Modeler", "Clone"), ("IR", "Cab")])
    assert {p.slot: p.category for p in placements} == {6: "Clone", 7: "Cab"}


def test_free_tail_keeps_the_order_the_song_asked_for():
    """Cab<Delay is a 57% coin flip in the corpus: the song decides, not the layout."""
    placements = assign_slots([
        ("Amp", "Amp"), ("Cab", "Cab"),
        ("BBD Delay", "Delay"), ("C2 Chorus", "Chorus"), ("Volume", "Dynamics"),
    ])
    tail = [(p.slot, p.module) for p in placements if p.slot in FREE_SLOTS]
    assert tail == [(8, "BBD Delay"), (9, "C2 Chorus"), (10, "Volume")]


def test_assign_slots_refuses_two_blocks_in_one_frozen_slot():
    with pytest.raises(ChainError, match="claimed twice"):
        assign_slots([("Amp", "Amp"), ("ReValver Amp", "Amp")])


def test_assign_slots_refuses_a_tail_overflow():
    blocks = [("Amp", "Amp"), ("Cab", "Cab")] + [
        (f"Delay {i}", "Delay") for i in range(len(FREE_SLOTS) + 1)
    ]
    with pytest.raises(ChainError, match="free slots"):
        assign_slots(blocks)


def test_validate_order_flags_a_hundred_percent_rule_violation():
    placements = [Placement(6, "Cab", "Cab"), Placement(8, "Amp", "Amp")]
    problems = validate_order(placements)
    assert any("Amp" in p and "must precede" in p for p in problems)


def test_validate_order_accepts_a_delay_placed_before_the_cab():
    """57% of the corpus does it; it must not be reported as an error."""
    placements = assign_slots([("Amp", "Amp"), ("Cab", "Cab"), ("BBD Delay", "Delay")])
    assert [p for p in validate_order(placements) if not p.startswith("note:")] == []


def test_placement_calls_emit_zero_based_slot_arguments():
    """Verified on hardware: argument 9 lands in slot 10, not slot 9."""
    calls = placement_calls([Placement(10, "Volume", "Dynamics")])
    assert calls == [(9, "Volume")]


def test_check_relocation_catches_a_duplicated_module_type():
    """The device MOVES an existing instance instead of adding a second one."""
    problems = check_relocation([Placement(6, "Amp", "Amp"), Placement(8, "Amp", "Amp")])
    assert len(problems) == 1
    assert "Amp 2" in problems[0]


def test_check_relocation_is_silent_when_the_twin_is_named():
    problems = check_relocation([Placement(6, "Amp", "Amp"), Placement(8, "Amp 2", "Amp")])
    assert problems == []


# --- offline write plan -------------------------------------------------------


def _catalog_for_plan() -> Any:
    """A catalog whose category map lets the planner resolve the fake blocks."""
    catalog = build_catalog(FakeTransport(), with_categories=False)
    return replace(catalog, category_blocks={"Amp": ("Amp",), "Delay": ("BBD Delay",)})


def _binding(**overrides: Any) -> dict[str, Any]:
    doc = {
        "schemaVersion": BINDING_SCHEMA_VERSION,
        "device": {"deviceId": "headrush-core", "appVersion": "5.1.0.2a63755"},
        "rig": {"name": "#FW - Test", "programChange": 112},
        "blocks": [
            {"module": "Amp", "params": {"GainA": 62.0, "Type": "82 Lead 800"}},
            {"module": "BBD Delay", "params": {"Mix": 12.0}},
        ],
    }
    doc.update(overrides)
    return doc


def test_plan_emits_chain_placement_then_parameters_then_program_change():
    plan = build_plan(_binding(), _catalog_for_plan())
    assert plan.is_applicable, plan.errors
    kinds = [s.kind for s in plan.steps]
    assert kinds[0] == "method"
    assert kinds[-1] == "put"
    assert plan.steps[-1].payload == {"loadedProgMIDICC": 112}


def test_plan_converts_display_values_to_device_floats():
    plan = build_plan(_binding(), _catalog_for_plan())
    amp = next(s for s in plan.steps if s.path.endswith("/Amp"))
    assert amp.payload["GainA"] == pytest.approx(0.62, abs=1e-6)
    assert amp.payload["Type"] == 2  # "82 Lead 800" is the third option


def test_plan_refuses_a_rig_name_without_the_guard_prefix():
    """The applier must never be able to overwrite a hand-made rig."""
    plan = build_plan(_binding(rig={"name": "Lorenzo solo 1"}), _catalog_for_plan())
    assert not plan.is_applicable
    assert any(GENERATED_PREFIX in e for e in plan.errors)


def test_plan_refuses_a_firmware_mismatch():
    """Module ids are positional: a catalog from another firmware is not usable."""
    doc = _binding(device={"deviceId": "headrush-core", "appVersion": "9.9.9"})
    plan = build_plan(doc, _catalog_for_plan())
    assert not plan.is_applicable
    assert any("firmware" in e for e in plan.errors)


def test_plan_refuses_an_unknown_module():
    doc = _binding(blocks=[{"module": "Klone", "params": {}}])
    plan = build_plan(doc, _catalog_for_plan())
    assert any("inconnu" in e for e in plan.errors)


def test_plan_refuses_an_out_of_range_parameter():
    doc = _binding(blocks=[{"module": "Amp", "params": {"GainA": 150.0}}])
    plan = build_plan(doc, _catalog_for_plan())
    assert any("outside" in e for e in plan.errors)


def test_plan_refuses_an_invalid_enum_label():
    doc = _binding(blocks=[{"module": "Amp", "params": {"Type": "Marshall JCM800"}}])
    plan = build_plan(doc, _catalog_for_plan())
    assert any("not a valid option" in e for e in plan.errors)


def test_plan_never_emits_save_rig():
    """Committing is the applier's decision, taken after the read-back check."""
    plan = build_plan(_binding(), _catalog_for_plan())
    assert all(s.method != "saveRig" for s in plan.steps)


def test_load_binding_rejects_a_foreign_document(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"schemaVersion": "other.v1"}), encoding="utf-8")
    with pytest.raises(PlanError, match="not a fretwise.device.binding"):
        load_binding(path)


def test_catalog_round_trips_through_disk(tmp_path: Path):
    original = build_catalog(FakeTransport(), with_categories=True)
    restored = load_catalog(write_catalog(original, tmp_path / "c.json"))
    assert restored.contract_hash == original.contract_hash
    assert restored.module_types == original.module_types
    assert restored.category_blocks == original.category_blocks
    amp = restored.block("Amp")
    assert amp is not None
    assert amp.param("GainA").minimum == 0.0


# --- the applier and its safety gates -----------------------------------------


class FakeWriteTransport(FakeTransport):
    """A fake device that records writes, satisfying ``DeviceWriteTransport``."""

    def __init__(self, **overrides: Any) -> None:
        super().__init__(**overrides)
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self.invocations: list[tuple[str, str, list[Any]]] = []
        self._properties["/Evil/API/RigSaveDialog"] = {"displayDialog": False}
        self._properties["/Evil/API/Rigs"]["loadedName"] = "#FW - Test"

    def set_properties(self, path: str, values: dict[str, Any]) -> None:
        self.writes.append((path, values))
        self._properties.setdefault(path, {}).update(values)

    def invoke(self, path: str, method: str, arguments: list[Any]) -> Any:
        self.invocations.append((path, method, arguments))
        if method == "setModuleTypeInternal":
            zero_based, type_id = arguments
            self._properties["/Evil/Engine/Patch/Chain"][f"ModuleType{zero_based + 1}"] = type_id
        return True


def _plan_and_catalog(transport: FakeWriteTransport) -> tuple[Any, Any]:
    catalog = replace(
        build_catalog(transport, with_categories=False),
        category_blocks={"Amp": ("Amp",), "Delay": ("BBD Delay",)},
    )
    return build_plan(_binding(), catalog), catalog


def test_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    report = apply_plan(plan, catalog, transport, dry_run=True, confirm=True)
    assert transport.writes == []
    assert transport.invocations == []
    assert all(a.startswith("[simul") for a in report.applied)


def test_write_refused_without_the_environment_lock(monkeypatch):
    monkeypatch.delenv(WRITE_ENV_VAR, raising=False)
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    with pytest.raises(WriteRefused, match=WRITE_ENV_VAR):
        apply_plan(plan, catalog, transport, dry_run=False, confirm=True)
    assert transport.writes == []


def test_write_refused_without_explicit_confirmation(monkeypatch):
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    with pytest.raises(WriteRefused, match="confirm"):
        apply_plan(plan, catalog, transport, dry_run=False, confirm=False)
    assert transport.writes == []


def test_write_refused_when_the_confirmation_token_is_stale(monkeypatch):
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    with pytest.raises(WriteRefused, match="rim"):
        apply_plan(
            plan, catalog, transport, dry_run=False, confirm=True, confirm_token="deadbeef"
        )
    assert transport.writes == []


def test_write_refused_on_a_rig_without_the_guard_prefix(monkeypatch):
    """The blast radius on the 118 hand-made rigs must be exactly zero."""
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    transport._properties["/Evil/API/Rigs"]["loadedName"] = "Lorenzo solo 1"
    plan, catalog = _plan_and_catalog(transport)
    with pytest.raises(WriteRefused, match="sable"):
        apply_plan(plan, catalog, transport, dry_run=False, confirm=True)
    assert transport.writes == []


def test_write_refused_while_the_save_dialog_is_open(monkeypatch):
    """A pending change blocks rig loads and makes every later read report the old rig."""
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    transport._properties["/Evil/API/RigSaveDialog"] = {"displayDialog": True}
    plan, catalog = _plan_and_catalog(transport)
    with pytest.raises(WriteRefused, match="dialogue"):
        apply_plan(plan, catalog, transport, dry_run=False, confirm=True)


def test_write_refused_on_a_firmware_mismatch(monkeypatch):
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    transport._properties["/Evil/Gui"]["AppVersion"] = "9.9.9"
    with pytest.raises(WriteRefused, match="positionnels"):
        apply_plan(plan, catalog, transport, dry_run=False, confirm=True)


def test_apply_writes_chain_then_parameters_and_verifies(monkeypatch):
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    report = apply_plan(
        plan,
        catalog,
        transport,
        dry_run=False,
        confirm=True,
        confirm_token=plan_token(plan),
        settle_s=0.0,
    )
    assert report.ok, report.mismatches
    placed = [i[1] for i in transport.invocations]
    assert placed == ["setModuleTypeInternal"] * len(plan.placements)
    assert any(path == "/Evil/API/Rigs" for path, _ in transport.writes)


def test_apply_does_not_save_unless_asked(monkeypatch):
    """A PUT alone does not persist, so not saving is a real, visible choice."""
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    report = apply_plan(plan, catalog, transport, dry_run=False, confirm=True, settle_s=0.0)
    assert report.saved is False
    assert all(m != "saveRig" for _, m, _ in transport.invocations)


def test_apply_saves_when_asked_and_verification_passed(monkeypatch):
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    report = apply_plan(
        plan, catalog, transport, dry_run=False, confirm=True, save=True, settle_s=0.0
    )
    assert report.saved is True
    assert ("/Evil/API/Rigs", "saveRig", []) in transport.invocations


def test_verification_catches_a_relocated_module(monkeypatch):
    """The device moves an existing instance instead of adding a second one."""
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    original_invoke = transport.invoke

    def sabotage(path: str, method: str, arguments: list[Any]) -> Any:
        result = original_invoke(path, method, arguments)
        transport._properties["/Evil/Engine/Patch/Chain"]["ModuleType6"] = 0
        return result

    transport.invoke = sabotage  # type: ignore[method-assign]
    report = apply_plan(plan, catalog, transport, dry_run=False, confirm=True, settle_s=0.0)
    assert not report.ok
    assert any("PLAC" in m for m in report.mismatches)


def test_apply_refuses_a_plan_targeting_an_unexpected_object(monkeypatch):
    monkeypatch.setenv(WRITE_ENV_VAR, "1")
    transport = FakeWriteTransport()
    plan, catalog = _plan_and_catalog(transport)
    plan.steps.append(
        Step(
            kind="put",
            path="/Evil/Engine/Settings/Midi",
            method=None,
            payload={"Channel": 3},
            describe="canal MIDI",
        )
    )
    with pytest.raises(WriteRefused, match="autoris"):
        apply_plan(plan, catalog, transport, dry_run=False, confirm=True, settle_s=0.0)


def test_plan_token_changes_with_the_plan():
    transport = FakeWriteTransport()
    plan, _ = _plan_and_catalog(transport)
    first = plan_token(plan)
    plan.steps.pop()
    assert plan_token(plan) != first
