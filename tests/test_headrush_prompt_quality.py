"""Prompt/catalog contract and malformed LLM response regression coverage.

These tests prove importer compatibility, not historic or acoustic fidelity.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fretwise.devices.headrush_core.catalog import Catalog, load_catalog
from fretwise.devices.headrush_core.params import ParamError, device_value
from fretwise.devices.headrush_core.plan import BINDING_SCHEMA_VERSION, build_plan
from fretwise.devices.headrush_core.prompt import PromptError, build_rig_prompt, parse_rig_response
from fretwise.devices.headrush_core.prompt_catalog import offered_modules, writable_params

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return load_catalog(ROOT / "data/devices/headrush-core/catalog/5.1.0.2a63755.json")


@pytest.fixture(scope="module")
def prompt(catalog: Catalog) -> str:
    return build_rig_prompt("Artist", "Song", catalog)


def _module_line(prompt: str, module: str) -> str:
    marker = f"- **{module}** : "
    return next(line for line in reversed(prompt.splitlines()) if line.startswith(marker))


def test_every_proposed_enum_is_complete_and_resolves_to_the_real_catalog(
    catalog: Catalog, prompt: str,
) -> None:
    definitions = {
        match.group(1): tuple(json.loads(match.group(2)))
        for match in re.finditer(r"^- `([^`]+)` : (\[.*\])$", prompt, re.MULTILINE)
    }
    enum_count = 0
    for module in offered_modules(catalog):
        block = catalog.block(module)
        assert block is not None
        for param in writable_params(block):
            if not param.options or param.type == "boolean":
                continue
            reference = re.search(
                rf"(?<![\w-]){re.escape(param.name)} \(voir `([^`]+)`\)",
                _module_line(prompt, module),
            )
            assert reference is not None, (module, param.name)
            assert definitions[reference.group(1)] == param.options
            for option in definitions[reference.group(1)]:
                assert isinstance(device_value(param, option), int)
            enum_count += 1
    assert enum_count > 70  # Includes effects and ReValver Cab, beyond the old four lists.
    assert len(definitions) < enum_count  # Shared time divisions are emitted once.
    assert "liste," not in prompt


def test_every_printed_numeric_endpoint_passes_the_importer(
    catalog: Catalog, prompt: str,
) -> None:
    for module in offered_modules(catalog):
        block = catalog.block(module)
        assert block is not None
        for param in writable_params(block):
            if param.options or param.type == "boolean":
                continue
            bounds = re.search(
                rf"(?<![\w-]){re.escape(param.name)} \[([^\]]+) à ([^\]]+)\]",
                _module_line(prompt, module),
            )
            assert bounds is not None, (module, param.name)
            for endpoint in bounds.groups():
                device_value(param, float(endpoint))


def test_boolean_options_do_not_turn_into_rejected_string_values(
    catalog: Catalog, prompt: str,
) -> None:
    block = catalog.block("Amp Clone")
    assert block is not None
    switch = block.param("CabOff")
    assert switch is not None and switch.options
    assert "CabOff (true/false)" in _module_line(prompt, "Amp Clone")
    assert device_value(switch, False) is False
    with pytest.raises(ParamError, match="boolean"):
        device_value(switch, switch.options[0])


def test_real_suffix_two_controls_survive_while_doubled_amp_channel_stays_out(
    prompt: str,
) -> None:
    assert "Bit2 (voir" in _module_line(prompt, "8-Bit Crush")
    assert "Type2" not in _module_line(prompt, "Amp")


def test_units_do_not_leak_printf_or_invent_units_for_resampling(prompt: str) -> None:
    nam = _module_line(prompt, "Neural Amp Modeler")
    assert "Input [-20 à 20] dB" in nam
    assert "Output [-40 à 40] dB" in nam
    assert "%." not in nam and "% ." not in nam
    crush = _module_line(prompt, "8-Bit Crush")
    assert "Resampling [0.0033333334140479565 à 1]" in crush
    assert "Resampling [0.0033333334140479565 à 1] Hz" not in crush


def test_unwriteable_file_and_reversed_bound_controls_are_explained_not_offered(
    catalog: Catalog, prompt: str,
) -> None:
    assert "LoadedClone" not in _module_line(prompt, "Neural Amp Modeler")
    assert "ReverbFile" not in _module_line(prompt, "C-Verb")
    assert "Proximity" not in _module_line(prompt, "ReValver Cab")
    assert "`ReValver Cab.Proximity` (bornes inversées" in prompt
    assert "ne charge pas de chemin de fichier" in prompt
    block = catalog.block("ReValver Cab")
    assert block is not None
    proximity = block.param("Proximity")
    assert proximity is not None
    with pytest.raises(ParamError, match="outside"):
        device_value(proximity, 0)


def test_example_preserves_binding_contract_and_imports_without_repair(
    catalog: Catalog, prompt: str,
) -> None:
    example = json.loads(prompt.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert set(example) == {
        "schemaVersion", "device", "rig", "song", "tone", "confidence", "sources", "blocks",
    }
    assert set(example["blocks"][0]) == {"module", "why", "params"}
    parsed, warnings = parse_rig_response(json.dumps(example), catalog)
    assert parsed == example
    assert warnings == []
    assert build_plan(parsed, catalog).is_applicable


def test_context_and_proof_hierarchy_use_existing_guidance_and_fields(catalog: Catalog) -> None:
    guidance = "Album original, solo; guitare P-90, entrée faible, casque, moins de gain."
    text = build_rig_prompt("Artist", "Song", catalog, guidance=guidance)
    assert guidance in text
    assert "version/enregistrement" in text and "guitare et micros" in text
    assert "niveau d'entrée" in text and "casque, FRFR" in text
    assert "matériel live ou actuel ne prouve pas le matériel studio" in text
    assert "FAIT SOURCÉ" in text and "ADAPTATION" in text and "À TESTER" in text
    assert "ni la preuve d'une écoute ou d'un import réel" in text
    assert "sans minimum" in text and "59 %" not in text and "5 à 9" not in text
    assert "seules les valeurs demandées sont écrites" in text


def test_layout_is_an_importer_profile_and_double_amp_remains_rejected(
    catalog: Catalog, prompt: str,
) -> None:
    assert "pas une restriction universelle du HeadRush" in prompt
    document = {"rig": {"name": "#FW - Layout"}, "blocks": [
        {"module": "Amp", "params": {}}, {"module": "Amp 2", "params": {}},
    ]}
    assert catalog.module_type_id("Amp 2") is not None
    assert not build_plan(document, catalog).is_applicable
    with pytest.raises(PromptError):
        parse_rig_response(document, catalog)


@pytest.mark.parametrize("module,own_param,foreign_param", [
    ("Graphic EQ", "LoGain", "Gain100Hz"),
    ("G EQ", "Gain100Hz", "LoGain"),
])
def test_eq_parameters_cannot_be_borrowed_from_another_catalog_module(
    catalog: Catalog, prompt: str, module: str, own_param: str, foreign_param: str,
) -> None:
    line = _module_line(prompt, module)
    assert f"{own_param} [" in line
    assert f"{foreign_param} [" not in line
    document = {"rig": {"name": "#FW - EQ"}, "blocks": [
        {"module": module, "params": {own_param: 0}},
    ]}
    parsed, _ = parse_rig_response(document, catalog)
    assert build_plan(parsed, catalog).is_applicable
    document["blocks"][0]["params"] = {foreign_param: 0}
    with pytest.raises(PromptError, match=foreign_param):
        parse_rig_response(document, catalog)


def test_minimal_amp_cab_rig_does_not_need_filler_effects(catalog: Catalog) -> None:
    document = {"rig": {"name": "#FW - Minimal"}, "blocks": [
        {"module": "Amp", "params": {}}, {"module": "Cab", "params": {}},
    ]}
    parsed, _ = parse_rig_response(document, catalog)
    assert [block["module"] for block in parsed["blocks"]] == ["Amp", "Cab"]
    assert build_plan(parsed, catalog).is_applicable


def test_final_check_follows_user_context_and_checks_module_parameter_pair(
    catalog: Catalog,
) -> None:
    text = build_rig_prompt("Artist", "Song", catalog, guidance="Contexte fourni.")
    last_paragraph = text.rsplit("\n\n", 1)[1]
    assert text.index(last_paragraph) > text.index("Contexte fourni.")
    assert "chaque paire `module` / clé de `params`" in last_paragraph
    assert "aucune clé empruntée à un autre EQ ou ampli" in last_paragraph
    assert "sans remplir les slots" in last_paragraph


@pytest.mark.parametrize("field,value", [
    ("rig", []), ("device", "headrush"), ("song", None), ("tone", []),
    ("rig", {"name": []}), ("song", {"artist": []}), ("tone", {"summary": {}}),
    ("rig", {"programChange": True}), ("rig", {"programChange": -1}),
    ("rig", {"programChange": 128}), ("rig", {"programChange": 1.5}),
    ("confidence", []), ("confidence", "certain"),
    ("sources", "https://example.org"), ("sources", [{}]),
    ("tone", {"mustHave": "gain"}), ("tone", {"avoid": [1]}),
    ("blocks", []), ("blocks", {}), ("blocks", [None]),
    ("blocks", [{"module": []}]), ("blocks", [{"module": "Amp", "why": []}]),
    ("blocks", [{"module": "Amp", "params": []}]),
    ("blocks", [{"module": "Amp", "params": {"GainA": {"value": 2}}}]),
    ("blocks", [{"module": "Amp", "params": {"GainA": float("nan")}}]),
    ("blocks", [{"module": "Amp", "params": {"GainA": float("inf")}}]),
])
def test_malformed_binding_fields_raise_prompt_error(
    catalog: Catalog, field: str, value: object,
) -> None:
    document = {"rig": {"name": "#FW - Test"}, "blocks": [{"module": "Amp"}]}
    document[field] = value
    with pytest.raises(PromptError):
        parse_rig_response(document, catalog)


@pytest.mark.parametrize("change", [
    {"schemaVersion": "another.schema"},
    {"device": {"deviceId": "valeton-gp180"}},
    {"device": {"appVersion": "0.0.0"}},
])
def test_supplied_incompatible_schema_or_device_is_rejected(
    catalog: Catalog, change: dict[str, object],
) -> None:
    document = {"rig": {"name": "#FW - Test"}, "blocks": [{"module": "Amp"}]}
    document.update(change)
    with pytest.raises(PromptError):
        parse_rig_response(document, catalog)


@pytest.mark.parametrize("raw", ["[]", "[{}]", "null", "true", "42"])
def test_complete_non_object_json_is_rejected(catalog: Catalog, raw: str) -> None:
    with pytest.raises(PromptError, match="objet JSON"):
        parse_rig_response(raw, catalog)


def test_optional_manual_fields_still_receive_legacy_defaults(catalog: Catalog) -> None:
    document = {"blocks": [{"module": "Amp"}]}
    parsed, _ = parse_rig_response(document, catalog, artist="A", title="B")
    assert parsed["schemaVersion"] == BINDING_SCHEMA_VERSION
    assert parsed["device"] == {"deviceId": "headrush-core", "appVersion": catalog.app_version}
    assert parsed["rig"]["name"] == "#FW - A - B"


def test_existing_stored_binding_and_sources_remain_compatible(catalog: Catalog) -> None:
    document = json.loads(
        (ROOT / "data/devices/headrush-core/rigs/ac-dc__highway-to-hell.json").read_text("utf-8"),
    )
    document["sources"] = ["Interview datée, portée : album, morceau non confirmé."]
    before = json.dumps(document, sort_keys=True)
    parsed, _ = parse_rig_response(document, catalog)
    assert json.dumps(parsed, sort_keys=True) == before
