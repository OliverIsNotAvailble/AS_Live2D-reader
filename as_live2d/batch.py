"""Discover Live2D model manifests recursively without confusing motion JSONs.

The input root is a session-only selection. This scanner never creates files
or modifies the user's Cubism assets.
"""
from __future__ import annotations

import os
from pathlib import Path

from .model import read_json


def discover_models(root: str | Path) -> list[Path]:
    """Find model3.json and legacy model manifests beneath a selected root.

    Motion3, expression, physics and saved-profile JSONs are excluded unless
    they genuinely reference a Cubism MOC via FileReferences.Moc.
    Output is deterministic, and os.walk never follows directory symlinks.
    """
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise ValueError(f"Pasta raiz inválida: {base}")

    matches: list[Path] = []
    for directory, subdirs, filenames in os.walk(base, followlinks=False):
        subdirs[:] = sorted(
            (d for d in subdirs if not (Path(directory) / d).is_symlink()),
            key=str.casefold,
        )
        for name in sorted(filenames, key=str.casefold):
            lower = name.lower()
            if not lower.endswith(".json") or lower.endswith(".as-reader.json"):
                continue
            file = Path(directory) / name
            if not file.is_file() or file.is_symlink():
                continue
            if lower.endswith(".model3.json"):
                matches.append(file.resolve())
                continue
            if lower.endswith((
                ".motion3.json", ".physics3.json", ".pose3.json",
                ".exp3.json", ".cdi3.json", ".userdata3.json",
            )):
                continue
            # A few game exports name the manifest "Character.json" rather
            # than "*.model3.json". Only accept a real model reference.
            try:
                info = read_json(file)
            except (OSError, ValueError, TypeError):
                continue
            refs = info.get("FileReferences")
            if isinstance(refs, dict) and isinstance(refs.get("Moc"), str):
                matches.append(file.resolve())
    return sorted(matches, key=lambda p: str(p.relative_to(base)).casefold())


def batch_model_output(
    fixed_output_root: str | Path, input_root: str | Path, model_path: Path,
) -> Path:
    """Preserve input subfolders during batch export to avoid overwrites.

    Single-model exports keep their existing <output>/<json_name> convention.
    Batch exports go to <output>/<relative parent>/<json_name>, preventing
    collisions for e.g. A/model3.json and B/model3.json.
    """
    from .output import fixed_output_for_model

    base = Path(input_root).expanduser().resolve()
    path = Path(model_path).expanduser().resolve()
    rel = path.relative_to(base)
    per_model = fixed_output_for_model(str(fixed_output_root), path)
    return per_model.parent / rel.parent / per_model.name
