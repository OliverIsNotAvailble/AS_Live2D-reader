"""Non-destructive normalization for Unity-exported Cubism motion3 curves.

Cubism Native Framework evaluates motion targets in consecutive Model,
Parameter, PartOpacity groups. Some exporters interleave groups, causing the
rest of the parameters and opacity curves to be silently ignored. The viewer
uses LoadExtraMotion to play a *temporary* normalized file without changing
the user's exported assets.
"""
from __future__ import annotations

import json
from pathlib import Path


TARGET_RANK = {"Model": 0, "Parameter": 1, "PartOpacity": 2}


def normalize_motion_data(motion: dict) -> tuple[dict, bool]:
    if not isinstance(motion, dict) or not isinstance(motion.get("Curves"), list):
        raise ValueError("Invalid motion3.json: missing Curves array")
    curves = motion["Curves"]
    indexed = list(enumerate(curves))
    order = sorted(indexed, key=lambda item: (
        TARGET_RANK.get(item[1].get("Target"), 3)
        if isinstance(item[1], dict) else 3,
        item[0]))
    changed = [idx for idx, _ in order] != list(range(len(curves)))
    if not changed:
        return motion, False
    # Make an independent manifest but preserve each original curve/segment
    # object exactly; ordering is the sole modification.
    normalized = dict(motion)
    normalized["Curves"] = [curve for _, curve in order]
    return normalized, True


def prepare_motion(source: str | Path, output_dir: str | Path) -> tuple[Path, bool]:
    source = Path(source).resolve()
    with source.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    result, changed = normalize_motion_data(data)
    if not changed:
        return source, False
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / source.name
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                      encoding="utf-8")
    return target, True
