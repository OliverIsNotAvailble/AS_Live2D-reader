"""Cubism PartOpacity motion tracks.

Cubism 3 motion files may interleave Parameter and PartOpacity curves. The
native SDK expects grouped targets, so some opacity tracks can be skipped.
This module evaluates PartOpacity curves independently without rewriting
user files and applies them through live2d-py's SetPartOpacity.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Segment:
    kind: int
    control: tuple[tuple[float, float], ...]


class PartTrack:
    def __init__(self, raw: list):
        if len(raw) < 2:
            raise ValueError("Invalid motion curve: no first point")
        self.initial = (float(raw[0]), float(raw[1]))
        self.segments: list[Segment] = []
        last = self.initial
        i = 2
        while i < len(raw):
            kind = int(raw[i])
            i += 1
            point_count = 3 if kind == 1 else 1
            if kind not in (0, 1, 2, 3) or i + 2 * point_count > len(raw):
                raise ValueError("Truncated or unsupported motion segment")
            new_points = []
            for _ in range(point_count):
                new_points.append((float(raw[i]), float(raw[i+1])))
                i += 2
            self.segments.append(Segment(kind, (last, *new_points)))
            last = new_points[-1]

    def value_at(self, seconds: float) -> float:
        seconds = float(seconds)
        if seconds <= self.initial[0] or not self.segments:
            return self.initial[1]
        for segment in self.segments:
            start = segment.control[0]
            end = segment.control[-1]
            if seconds > end[0]:
                continue
            dt = end[0] - start[0]
            if dt <= 0:
                return end[1]
            if segment.kind == 2:  # stepped
                return start[1]
            if segment.kind == 3:  # inverse stepped
                return end[1]
            if segment.kind == 0:
                t = max(0.0, min(1.0, (seconds - start[0]) / dt))
                return start[1] + (end[1] - start[1]) * t
            # Bézier: invert x(t) via binary search, then evaluate y(t).
            p0, p1, p2, p3 = segment.control
            low, high = 0.0, 1.0
            for _ in range(28):
                t = (low + high) / 2
                x = (1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] + 3*(1-t)*t*t*p2[0] + t**3*p3[0]
                if x < seconds:
                    low = t
                else:
                    high = t
            t = (low + high) / 2
            return ((1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] +
                    3*(1-t)*t*t*p2[1] + t**3*p3[1])
        return self.segments[-1].control[-1][1]


def read_part_tracks(path: str | Path) -> tuple[dict[str, PartTrack], bool]:
    """Return (id -> opacity curve, interleaved_targets).

    Loading happens when selecting a motion, NOT once per preview frame.
    """
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("Curves"), list):
        raise ValueError("Invalid motion3.json")
    tracks: dict[str, PartTrack] = {}
    ranks = {"Model": 0, "Parameter": 1, "PartOpacity": 2}
    highest_rank = -1
    interleaved = False
    for curve in data["Curves"]:
        if not isinstance(curve, dict):
            continue
        target = curve.get("Target")
        rank = ranks.get(target, 3)
        if rank < highest_rank:
            interleaved = True
        highest_rank = max(highest_rank, rank)
        if target == "PartOpacity" and isinstance(curve.get("Id"), str):
            tracks[curve["Id"]] = PartTrack(curve["Segments"])
    return tracks, interleaved
