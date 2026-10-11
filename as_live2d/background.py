"""Shared image fitting for the GPU preview and final video encoder.

The source is cropped to fill the complete output frame (ImageOps.fit), matching
the red export frame's aspect ratio. GPU upload happens only when BG changes.
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps


def fitted_background(path: str | Path, width: int, height: int,
                      max_dimension: int | None = None) -> np.ndarray:
    if width <= 0 or height <= 0:
        raise ValueError("Background dimensions must be positive")
    file = Path(path).expanduser()
    if not file.is_file():
        raise FileNotFoundError(f"Background image not found: {file}")
    target_width, target_height = int(width), int(height)
    if max_dimension is not None and max(target_width, target_height) > max_dimension:
        ratio = max_dimension / max(target_width, target_height)
        target_width = max(1, round(target_width * ratio))
        target_height = max(1, round(target_height * ratio))
    with Image.open(file) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"), (target_width, target_height),
            method=Image.Resampling.LANCZOS)
        return np.asarray(fitted, dtype=np.uint8).copy()
