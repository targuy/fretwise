# ruff: noqa: E501 — long lines are verbatim LLM prompt/skill strings ported from SongsGears.
import json
import os
import urllib.error
import urllib.request

from .models import confidence_needs_review, normalize_rig
from .schema import parse_json_object, validate_rig


class LlmError(Exception):
    pass


def build_prompt(song, skill_prompt, output_schema, allowed_catalog=""):
    schema_text = json.dumps(output_schema, ensure_ascii=False, indent=2)
    song_text = json.dumps(song, ensure_ascii=False, indent=2)
    catalog_section = f"\n\n{allowed_catalog.strip()}\n" if allowed_catalog else ""
    return f"""# TASK

Generate exactly one guitar rig recommendation for the request below.

The reference material and skills are provided after the output schema. Use them as expert guidance, but keep this concrete request as the task to answer:

```json
{song_text}
```

Target result:
- fill `general` with the song's ideal or generic target sound and the best possible real-world equipment, without being limited by the GP-180;
- fill `gp180` with the best possible Valeton GP-180 preset using only existing GP-180 models from the reference material. Do not invent GP-180 model names. If the exact ideal model is absent, choose the closest existing GP-180 model and document the gap on the block;
- fill `improvements` with NAM, SnapTone, and IR proposals, each with priority P1/P2/P3/none. Use P1 when the GP-180 lacks a key target amp, cab, or capture;
- return only JSON matching the schema;
- do not add markdown fences or commentary in the answer.
{catalog_section}

# OUTPUT JSON SCHEMA

```json
{schema_text}
```

# REFERENCE MATERIAL / SKILLS

{skill_prompt}

Execution model:
Apply the skill stages in order. First create the general musical and gear intent with ideal equipment. Then translate it to the target GP-180 equipment with a forced best match from existing GP-180 models. Then propose NAM/SnapTone or IR replacements only where they improve the rig or compensate for a GP-180 model gap.

# FINAL INSTRUCTION

Answer the task at the top for this exact request:

```json
{song_text}
```

Return only valid JSON. Do not include markdown fences.
"""


def build_stage_prompt(stage, request, reference, previous=None, allowed_catalog=""):
    request_text = json.dumps(request, ensure_ascii=False, indent=2)
    previous = previous or {}
    previous_text = json.dumps(previous, ensure_ascii=False, indent=2)
    schema_text = json.dumps(_stage_schema(stage), ensure_ascii=False, indent=2)
    catalog_section = (
        f"\n\n# GP-180 ALLOWED MODEL CATALOG\n\n{allowed_catalog.strip()}\n"
        if allowed_catalog
        else ""
    )
    stage_title = {
        "general": "Stage 1/3 - General Tone Research",
        "gp180": "Stage 2/3 - GP-180 Translation",
        "improvements": "Stage 3/3 - NAM / IR Improvements",
    }[stage]
    stage_goal = {
        "general": "Find the ideal or generic target sound and best possible real-world gear. Do not think about GP-180 limitations in this step.",
        "gp180": "Translate the previous general result into a Valeton GP-180 best match. Use only exact model names from the GP-180 catalog.",
        "improvements": "Propose NAM, SnapTone, and IR upgrades only where they improve or replace weak GP-180 matches.",
    }[stage]
    previous_section = ""
    if previous:
        previous_section = f"""
# PREVIOUS STAGE RESULT

```json
{previous_text}
```
"""
    return f"""# {stage_title}

{stage_goal}

# REQUEST

```json
{request_text}
```
{previous_section}{catalog_section}

# OUTPUT JSON SCHEMA

```json
{schema_text}
```

# STAGE REFERENCE MATERIAL

{reference}

# FINAL INSTRUCTION

Return only valid JSON for this stage. Do not include markdown fences or commentary.
"""


def stage_schema(stage):
    return _stage_schema(stage)


def generate_rig(provider, model, request, skill_prompt, output_schema, config, allowed_catalog=""):
    provider = provider.lower()
    prompt = build_prompt(request, skill_prompt, output_schema, allowed_catalog)
    if provider == "mock":
        rig = _mock_rig(request)
    else:
        rig, _raw_text = request_json(
            provider, prompt, model, config, output_schema, schema_name="song_tone_profile"
        )
    return validate_rig(normalize_rig(rig))


def generate_profile(provider, model, song, skill_prompt, output_schema, config):
    return generate_rig(provider, model, song, skill_prompt, output_schema, config)


def _mock_rig(request):
    artist = request.get("artist") or request.get("song", {}).get("artist") or "Unknown artist"
    title = request.get("title") or request.get("song", {}).get("title") or "Unknown title"
    album = request.get("album") or request.get("song", {}).get("album") or ""
    year = _safe_int(request.get("year") or request.get("song", {}).get("year"))
    equipment = request.get("equipment") or request.get("targetEquipment") or "Valeton GP-180"
    guitar = request.get("guitar") or request.get("targetGuitar") or "Default electric guitar"
    output = request.get("output") or "FRFR / headphones"
    lower = f"{artist} {title} {equipment} {guitar}".lower()
    if "u2" in lower:
        tone_profile = "Vox chime with dotted eighth delay"
        confidence = "medium/high"
        ideal_equipment = [
            {
                "role": "amp",
                "model": "Vox AC30 Top Boost",
                "reason": "Core bright chime and upper-mid compression.",
            },
            {
                "role": "delay",
                "model": "TC 2290-style digital delay",
                "reason": "Precise dotted-eighth repeats.",
            },
        ]
        blocks = [
            _block(
                1,
                "dynamics",
                "PRE",
                "COMP",
                {"Sustain": 45, "Level": "unity"},
                "Even out arpeggiated picking.",
            ),
            _block(
                2,
                "amp",
                "AMP",
                "AC30-style clean",
                {"Gain": 28, "Bass": 42, "Mid": 48, "Treble": 68, "Level": 90},
                "Bright chime foundation.",
            ),
            _block(
                3,
                "delay",
                "DLY",
                "Digital Delay",
                {"Time": "3/16 or dotted eighth", "Feedback": 38, "Mix": 32},
                "Core rhythmic repeat.",
            ),
            _block(4, "reverb", "RVB", "Plate", {"Decay": "2.6s", "Mix": 18}, "Studio ambience."),
        ]
    elif "pink floyd" in lower:
        tone_profile = "Gilmour sustaining lead"
        confidence = "medium"
        ideal_equipment = [
            {
                "role": "amp",
                "model": "Hiwatt DR103",
                "reason": "Clean headroom and focused midrange under pedals.",
            },
            {
                "role": "drive",
                "model": "Big Muff-style sustain",
                "reason": "Long singing lead sustain.",
            },
        ]
        blocks = [
            _block(
                1,
                "drive",
                "DST",
                "Sustain Drive / Muff-style",
                {"Gain": 55, "Tone": 52, "Level": 85},
                "Long sustain lead voice.",
            ),
            _block(
                2,
                "amp",
                "AMP",
                "Hiwatt-style clean",
                {"Gain": 34, "Bass": 50, "Mid": 58, "Treble": 61, "Level": 90},
                "Clean headroom under drive.",
            ),
            _block(
                3,
                "delay",
                "DLY",
                "Analog Delay",
                {"Time": "430ms", "Feedback": 32, "Mix": 24},
                "Lead depth.",
            ),
            _block(4, "reverb", "RVB", "Plate", {"Decay": "2.8s", "Mix": 16}, "Record-like tail."),
        ]
    elif "police" in lower:
        tone_profile = "Compressed chorus clean"
        confidence = "medium"
        ideal_equipment = [
            {
                "role": "amp",
                "model": "Roland JC-120 or bright clean amp",
                "reason": "Fast clean transient and stereo-friendly headroom.",
            },
            {
                "role": "modulation",
                "model": "Analog chorus",
                "reason": "Wide but controlled clean shimmer.",
            },
        ]
        blocks = [
            _block(
                1,
                "dynamics",
                "PRE",
                "COMP",
                {"Sustain": 50, "Attack": "fast", "Level": "unity"},
                "Snappy clean attack.",
            ),
            _block(
                2,
                "amp",
                "AMP",
                "Bright Clean",
                {"Gain": 24, "Bass": 40, "Mid": 50, "Treble": 66, "Level": 90},
                "Clean rhythmic base.",
            ),
            _block(
                3,
                "modulation",
                "MOD",
                "Chorus",
                {"Rate": 28, "Depth": 42, "Mix": 32},
                "Signature shimmer.",
            ),
            _block(
                4,
                "delay",
                "DLY",
                "Short Digital Delay",
                {"Time": "120ms", "Feedback": 18, "Mix": 12},
                "Adds width without washing the riff.",
            ),
        ]
    else:
        tone_profile = "General purpose song rig"
        confidence = "low"
        ideal_equipment = [
            {
                "role": "amp",
                "model": "Reference amp for the target artist",
                "reason": "Replace this mock value with researched gear.",
            },
            {
                "role": "cab",
                "model": "Reference cabinet or IR for the target record",
                "reason": "Speaker choice is usually decisive for realism.",
            },
        ]
        blocks = [
            _block(
                1,
                "drive",
                "DST",
                "Low Gain OD",
                {"Gain": 25, "Tone": 55, "Level": "unity"},
                "Adds harmonic density.",
            ),
            _block(
                2,
                "amp",
                "AMP",
                "Clean British Combo",
                {"Gain": 32, "Bass": 45, "Mid": 50, "Treble": 62, "Level": 90},
                "Flexible starting amp.",
            ),
            _block(
                3,
                "delay",
                "DLY",
                "Digital Delay",
                {"Time": "360ms", "Feedback": 30, "Mix": 22},
                "General ambience.",
            ),
            _block(4, "reverb", "RVB", "Plate", {"Decay": "2.4s", "Mix": 18}, "Record-like space."),
        ]
    signal_chain = " -> ".join(f"{block['module']} {block['model']}" for block in blocks)
    general = {
        "targetSound": tone_profile,
        "toneProfile": tone_profile,
        "referenceArtists": [artist] if artist != "Unknown artist" else [],
        "referenceTracks": [title] if title != "Unknown title" else [],
        "idealSignalChain": " -> ".join(
            f"{item['role']}: {item['model']}" for item in ideal_equipment
        ),
        "bestPossibleEquipment": ideal_equipment,
        "productionNotes": ["Mock provider uses broad references only."],
    }
    gp180 = {
        "equipment": {"model": equipment, "ownedItem": request.get("ownedEquipment", equipment)},
        "guitar": guitar,
        "output": output,
        "choicePolicy": "Use only existing GP-180 models; when exact gear is absent, choose the closest existing best match and document the gap.",
        "bestMatchSummary": signal_chain,
        "blocks": blocks,
    }
    improvements = {
        "summary": "Use external captures or IRs when the GP-180 best match lacks the exact amp or cabinet character.",
        "proposals": [
            {
                "priority": "P2",
                "type": "IR",
                "target": "Cabinet realism",
                "replacesBlockOrder": 2 if len(blocks) > 1 else None,
                "recommendedAsset": "Artist-appropriate cabinet IR",
                "reason": "Factory cabinet choices are usually less precise than a dedicated IR.",
                "whenToUse": "Use when the GP-180 cab block sounds too generic through FRFR or headphones.",
                "expectedGain": "More realistic speaker color and mic placement.",
                "requiredIfGp180Gap": False,
            }
        ],
    }
    return {
        "rigName": f"{title} - {equipment} - {guitar}",
        "song": {"artist": artist, "title": title, "album": album, "year": year},
        "equipment": {"model": equipment, "ownedItem": request.get("ownedEquipment", "")},
        "guitar": guitar,
        "output": output,
        "toneProfile": tone_profile,
        "status": "draft",
        "confidence": confidence,
        "signalChainSummary": signal_chain,
        "blocks": blocks,
        "general": general,
        "gp180": gp180,
        "improvements": improvements,
        "assumptions": [
            "Mock output is for pipeline testing, not a final musicological answer.",
            "Settings are starting points and should be adjusted by ear.",
        ],
        "warnings": ["Validate final levels on the actual output system."],
        "sources": ["mock provider"],
        "createdFrom": "generated",
        "needsReview": confidence_needs_review(confidence),
    }


def _block(order, role, module, model, settings, purpose):
    return {
        "order": order,
        "role": role,
        "module": module,
        "model": model,
        "active": True,
        "settings": settings,
        "purpose": purpose,
        "alternatives": [],
    }


def request_json(
    provider,
    prompt,
    model,
    config,
    output_schema=None,
    schema_name="llm_json",
    ollama_options=None,
    openai_options=None,
):
    parsed, raw_text, _usage = request_json_with_usage(
        provider,
        prompt,
        model,
        config,
        output_schema=output_schema,
        schema_name=schema_name,
        ollama_options=ollama_options,
        openai_options=openai_options,
    )
    return parsed, raw_text


def request_json_with_usage(
    provider,
    prompt,
    model,
    config,
    output_schema=None,
    schema_name="llm_json",
    ollama_options=None,
    openai_options=None,
):
    provider = provider.lower()
    if provider == "ollama":
        raw_text, usage = _ollama_raw_with_usage(
            prompt, model, config, ollama_options=ollama_options
        )
    elif provider == "openai":
        raw_text, usage = _openai_raw_with_usage(
            prompt,
            model,
            output_schema,
            config,
            schema_name=schema_name,
            openai_options=openai_options,
        )
    elif provider == "claude":
        raw_text = _claude_raw(prompt, model, config)
        usage = {}
    else:
        raise LlmError(f"Unknown provider: {provider}")
    return parse_json_object(raw_text), raw_text, usage


def request_claude_cached_json(system_prompt, user_prompt, model, config, max_tokens=None):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LlmError("ANTHROPIC_API_KEY is not set")
    body = {
        "model": model,
        "max_tokens": max_tokens or config["llm"].get("max_tokens", 900),
        "temperature": config["llm"].get("temperature", 0.0),
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": user_prompt}],
            }
        ],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    result = _post_json("https://api.anthropic.com/v1/messages", body, headers)
    text = "\n".join(
        part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"
    )
    return parse_json_object(text), text, result.get("usage", {})


def _ollama(prompt, model, config):
    return parse_json_object(_ollama_raw(prompt, model, config))


def _ollama_raw(prompt, model, config, ollama_options=None):
    raw_text, _usage = _ollama_raw_with_usage(prompt, model, config, ollama_options=ollama_options)
    return raw_text


def _ollama_raw_with_usage(prompt, model, config, ollama_options=None):
    url = config["llm"].get("ollama_url", "http://localhost:11434/api/generate")
    options = {"temperature": config["llm"].get("temperature", 0.2)}
    if ollama_options:
        options.update(ollama_options)
    body = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": options,
    }
    result = _post_json(url, body, {})
    usage = {
        "prompt_eval_count": result.get("prompt_eval_count"),
        "eval_count": result.get("eval_count"),
        "total_duration": result.get("total_duration"),
        "prompt_eval_duration": result.get("prompt_eval_duration"),
        "eval_duration": result.get("eval_duration"),
    }
    return result.get("response", ""), {
        key: value for key, value in usage.items() if value is not None
    }


def _openai(prompt, model, output_schema, config):
    return parse_json_object(
        _openai_raw(prompt, model, output_schema, config, schema_name="song_tone_profile")
    )


def _openai_raw(prompt, model, output_schema, config, schema_name="llm_json"):
    text, _usage = _openai_raw_with_usage(
        prompt, model, output_schema, config, schema_name=schema_name
    )
    return text


def _openai_raw_with_usage(
    prompt, model, output_schema, config, schema_name="llm_json", openai_options=None
):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LlmError("OPENAI_API_KEY is not set")
    options = {**config.get("llm", {}).get("openai_options", {}), **(openai_options or {})}
    body = {
        "model": model,
        "input": prompt,
    }
    if options.get("prompt_cache_key"):
        body["prompt_cache_key"] = options["prompt_cache_key"]
    if options.get("prompt_cache_retention"):
        body["prompt_cache_retention"] = options["prompt_cache_retention"]
    if options.get("reasoning_effort"):
        body["reasoning"] = {"effort": options["reasoning_effort"]}
    if output_schema:
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": output_schema,
                "strict": bool(config["llm"].get("strict_json_schema", False)),
            }
        }
    if options.get("text_verbosity"):
        body.setdefault("text", {})["verbosity"] = options["text_verbosity"]
    headers = {"Authorization": f"Bearer {api_key}"}
    result = _post_json("https://api.openai.com/v1/responses", body, headers)
    if "output_text" in result:
        return result["output_text"], result.get("usage", {})
    chunks = []
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                chunks.append(content.get("text", ""))
    return "\n".join(chunks), result.get("usage", {})


def _claude(prompt, model, config):
    return parse_json_object(_claude_raw(prompt, model, config))


def _claude_raw(prompt, model, config):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LlmError("ANTHROPIC_API_KEY is not set")
    body = {
        "model": model,
        "max_tokens": config["llm"].get("max_tokens", 2200),
        "temperature": config["llm"].get("temperature", 0.2),
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    result = _post_json("https://api.anthropic.com/v1/messages", body, headers)
    return "\n".join(
        part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"
    )


def _post_json(url, body, headers):
    data = json.dumps(body).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LlmError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LlmError(f"Could not reach {url}: {exc}") from exc


def _safe_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except ValueError:
        return None


def _stage_schema(stage):
    if stage == "general":
        return {
            "type": "object",
            "required": ["general", "assumptions", "sources", "confidence", "needsReview"],
            "properties": {
                "general": {
                    "type": "object",
                    "required": [
                        "targetSound",
                        "toneProfile",
                        "idealSignalChain",
                        "bestPossibleEquipment",
                    ],
                    "properties": {
                        "targetSound": {"type": "string"},
                        "toneProfile": {"type": "string"},
                        "referenceArtists": {"type": "array", "items": {"type": "string"}},
                        "referenceTracks": {"type": "array", "items": {"type": "string"}},
                        "idealSignalChain": {"type": "string"},
                        "bestPossibleEquipment": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["role", "model", "reason"],
                                "properties": {
                                    "role": {"type": "string"},
                                    "model": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                            },
                        },
                        "productionNotes": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "sources": {"type": "array", "items": {"type": "string"}},
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium/high", "medium", "low", "unknown"],
                },
                "needsReview": {"type": "boolean"},
            },
        }
    if stage == "gp180":
        return {
            "type": "object",
            "required": ["gp180", "warnings", "confidence", "needsReview"],
            "properties": {
                "gp180": {
                    "type": "object",
                    "required": [
                        "equipment",
                        "guitar",
                        "output",
                        "choicePolicy",
                        "bestMatchSummary",
                        "blocks",
                    ],
                    "properties": {
                        "equipment": {
                            "type": "object",
                            "required": ["model"],
                            "properties": {
                                "model": {"type": "string"},
                                "ownedItem": {"type": "string"},
                            },
                        },
                        "guitar": {"type": "string"},
                        "output": {"type": "string"},
                        "choicePolicy": {"type": "string"},
                        "bestMatchSummary": {"type": "string"},
                        "blocks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "order",
                                    "role",
                                    "module",
                                    "model",
                                    "active",
                                    "settings",
                                    "matchQuality",
                                    "gap",
                                ],
                                "properties": {
                                    "order": {"type": "integer"},
                                    "role": {"type": "string"},
                                    "module": {"type": "string"},
                                    "model": {"type": "string"},
                                    "active": {"type": "boolean"},
                                    "settings": {"type": "object"},
                                    "purpose": {"type": "string"},
                                    "targetReference": {"type": "string"},
                                    "matchQuality": {
                                        "type": "string",
                                        "enum": ["exact", "close", "acceptable", "fallback"],
                                    },
                                    "gap": {"type": "string"},
                                    "alternatives": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                    },
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium/high", "medium", "low", "unknown"],
                },
                "needsReview": {"type": "boolean"},
            },
        }
    if stage == "improvements":
        return {
            "type": "object",
            "required": ["improvements", "warnings", "confidence", "needsReview"],
            "properties": {
                "improvements": {
                    "type": "object",
                    "required": ["summary", "proposals"],
                    "properties": {
                        "summary": {"type": "string"},
                        "proposals": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "priority",
                                    "type",
                                    "target",
                                    "recommendedAsset",
                                    "reason",
                                ],
                                "properties": {
                                    "priority": {
                                        "type": "string",
                                        "enum": ["P1", "P2", "P3", "none"],
                                    },
                                    "type": {
                                        "type": "string",
                                        "enum": ["NAM", "SnapTone", "IR", "NAM+IR", "none"],
                                    },
                                    "target": {"type": "string"},
                                    "replacesBlockOrder": {"type": ["integer", "null"]},
                                    "recommendedAsset": {"type": "string"},
                                    "reason": {"type": "string"},
                                    "whenToUse": {"type": "string"},
                                    "expectedGain": {"type": "string"},
                                    "requiredIfGp180Gap": {"type": "boolean"},
                                },
                            },
                        },
                    },
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium/high", "medium", "low", "unknown"],
                },
                "needsReview": {"type": "boolean"},
            },
        }
    raise LlmError(f"Unknown stage: {stage}")
