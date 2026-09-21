"""Move supplied provider keys into private server storage without printing them."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fretwise.rig_ai import RigAIError, save_settings  # noqa: E402


def migrate(source: Path, destination: Path, *, apply: bool = False) -> None:
    """Move exactly one key per provider; keep source on any failed verification."""
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 65_536:
        raise ValueError("Fichier source absent, lien symbolique ou taille invalide")
    source = source.resolve()
    destination = destination.absolute()
    if destination.is_symlink():
        raise ValueError("Destination symbolique refusée")
    # The supplied root file must leave its containing repository, not merely
    # move into another subdirectory accidentally eligible for a Git archive.
    for parent in source.parents:
        if (parent / ".git").exists():
            if destination.resolve().is_relative_to(parent):
                raise ValueError("La destination doit être hors du dépôt Git")
            break
    text = source.read_text(encoding="utf-8-sig")
    anthropic = set(re.findall(r"sk-ant-[A-Za-z0-9_-]+", text))
    openai = set(re.findall(r"sk-(?!ant-)[A-Za-z0-9_-]+", text))
    if len(anthropic) != 1 or len(openai) != 1:
        raise ValueError("Une clé unique Claude et une clé unique OpenAI sont requises")
    expected = {"OPENAI_API_KEY": openai.pop(), "ANTHROPIC_API_KEY": anthropic.pop()}
    if destination.is_file():
        previous = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(previous, dict) or any(
            previous.get(name) not in (None, "", value) for name, value in expected.items()
        ):
            raise ValueError("Clés existantes différentes : migration arrêtée sans écrasement")
    if not apply:
        print("Deux clés détectées. Simulation uniquement ; aucun fichier modifié.")
        return
    if any(os.environ.get(name) for name in expected):
        raise ValueError("Clé imposée par environnement : migration arrêtée sans modification")
    os.environ["FRETWISE_RIG_AI_SECRETS_FILE"] = str(destination)
    save_settings({
        "openai_api_key": expected["OPENAI_API_KEY"],
        "anthropic_api_key": expected["ANTHROPIC_API_KEY"],
    })
    stored = json.loads(destination.read_text(encoding="utf-8"))
    if any(stored.get(name) != value for name, value in expected.items()):
        raise ValueError("Vérification destination échouée ; source conservée")
    source.unlink()
    print(f"Deux clés transférées vers {destination}. Source retirée du dépôt.")


def main() -> int:
    """Run a dry run unless the operator explicitly passes --apply."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd() / "fretwise-keys.txt")
    config = Path(os.environ.get("FRETWISE_CONFIG_DIR", str(Path.home() / ".fretwise")))
    parser.add_argument("--destination", type=Path, default=config / "rig-ai-secrets.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        migrate(args.source, args.destination, apply=args.apply)
    except (OSError, ValueError, RigAIError):
        # Do not include exceptions that may contain JSON contents or credentials.
        print("Migration impossible ; source conservée. Vérifier format, destination et droits.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
