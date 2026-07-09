# ruff: noqa: E501 — long lines are verbatim LLM prompt/skill strings ported from SongsGears.
import os
from pathlib import Path

from .gp180_catalog import build_gp180_allowed_catalog
from .schema import load_text


def default_skills_dir() -> Path:
    """Return the packaged skills/data directory.

    ``FRETWISE_GEARS_SKILLS_DIR`` overrides; defaults to the ``data/skills``
    directory shipped with this package.
    """
    env = os.environ.get("FRETWISE_GEARS_SKILLS_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "data" / "skills"


def resolve_data_path(base_dir, path):
    """Resolve a config-relative data path, falling back to packaged data.

    Order: absolute path as-is; then ``base_dir/path`` (the original SongsGears
    behavior); then ``default_skills_dir()/<basename>`` so the skill briefs and
    schema shipped under ``fretwise/gears/production/data/skills`` resolve even
    when the config lives elsewhere. When nothing exists, the ``base_dir/path``
    candidate is returned unchanged so callers keep their original
    missing-file handling (skip optional stages, raise for required ones).
    """
    if os.path.isabs(path):
        return path
    candidate = os.path.join(base_dir, path)
    if os.path.exists(candidate):
        return candidate
    fallback = default_skills_dir() / os.path.basename(path)
    if fallback.exists():
        return str(fallback)
    return candidate


def load_skill_prompt(base_dir, config):
    paths = config.get("paths", {})
    chain = paths.get("skill_chain") or []
    if chain:
        sections = []
        for index, stage in enumerate(chain, start=1):
            if not stage.get("enabled", True):
                continue
            stage_path = stage.get("path")
            if not stage_path:
                continue
            full_path = resolve_data_path(base_dir, stage_path)
            if not os.path.exists(full_path):
                if stage.get("required", False):
                    raise FileNotFoundError(f"Required skill stage not found: {stage_path}")
                continue
            label = stage.get("label") or stage.get("id") or f"stage-{index}"
            role = stage.get("role", "")
            content = load_text(full_path).strip()
            sections.append(
                "\n".join(
                    [
                        f"## Skill stage {index}: {label}",
                        f"Role: {role}" if role else "",
                        content,
                    ]
                ).strip()
            )
        if sections:
            return "\n\n---\n\n".join(sections)
    return load_text(resolve_data_path(base_dir, paths["skill_prompt"]))


def load_gp180_allowed_catalog(base_dir, config):
    for stage in config.get("paths", {}).get("skill_chain", []):
        if not stage.get("enabled", True):
            continue
        stage_id = stage.get("id", "")
        stage_path = stage.get("path", "")
        if stage_id != "gp180_translation" and "gp180" not in stage_path.lower():
            continue
        full_path = resolve_data_path(base_dir, stage_path)
        if os.path.exists(full_path):
            return build_gp180_allowed_catalog(load_text(full_path))
    return ""


def load_skill_stage(base_dir, config, stage_id):
    for stage in config.get("paths", {}).get("skill_chain", []):
        if stage.get("id") != stage_id or not stage.get("enabled", True):
            continue
        stage_path = stage.get("path")
        if not stage_path:
            break
        full_path = resolve_data_path(base_dir, stage_path)
        if os.path.exists(full_path):
            return load_text(full_path).strip()
        if stage.get("required", False):
            raise FileNotFoundError(f"Required skill stage not found: {stage_path}")
        break
    return ""


def gp180_stage_brief():
    return """GP-180 translation rules:

- Build the GP-180 chain as: NR -> PRE -> WAH -> DST -> N→S -> AMP -> CAB/IR -> EQ -> MOD -> DLY -> RVB -> VOL.
- Use only exact model names from the GP-180 allowed catalog.
- If the ideal amp/cab exists as GP-180 AMP + CAB, prefer AMP + CAB for a stable factory preset.
- If a direct song SnapTone exists, prioritize N→S and decide whether AMP/CAB should be None based on whether the capture is full rig or amp-only.
- If no direct song SnapTone exists, choose the closest AMP and CAB from the catalog and document the gap.
- For Marshall JTM45 / Plexi / JMP targets, prefer UK 45, UK 50, or UK SLP depending on gain and period.
- For Marshall Greenback 4x12 targets, prefer UK Vintage 4x12 or UK Basket 4x12.
- For AC/DC-style classic rock, use moderate gain, strong upper mids, tight bass, almost no modulation, no delay, and very low Room/Plate ambience.
- Each block must include matchQuality and gap.
- Inactive blocks must use model None and active false.
"""
