"""Rotation geometry shared by the Qt controls and GPU compositor."""
from __future__ import annotations

import math


def rotation_fit_factor(width: int, height: int, degrees: float) -> float:
    """Scale to keep the entire rotated layer inside its fixed output frame.

    The optional fit is conservative (full canvas, not model bounding box).
    Background pixels are neither rotated nor cropped by this operation.
    """
    if width <= 0 or height <= 0:
        raise ValueError("Frame size must be positive")
    if not math.isfinite(degrees):
        raise ValueError("Rotation angle must be finite")
    radians = math.radians(degrees)
    c, s = abs(math.cos(radians)), abs(math.sin(radians))
    rotated_width = width * c + height * s
    rotated_height = width * s + height * c
    return min(1.0, width / rotated_width, height / rotated_height)


def source_pixel_for_rotation(x: float, y: float, width: int, height: int,
                              degrees: float, *, fit: bool = False):
    """Reference inverse map for the fragment shader.

    Input/output coordinates have a bottom-left origin (OpenGL). Positive
    degrees rotate the visible model clockwise, independent of aspect ratio.
    """
    factor = rotation_fit_factor(width, height, degrees) if fit else 1.0
    dx, dy = x - width / 2.0, y - height / 2.0
    r = math.radians(degrees)
    c, s = math.cos(r), math.sin(r)
    return (width / 2.0 + (c * dx - s * dy) / factor,
            height / 2.0 + (s * dx + c * dy) / factor)
