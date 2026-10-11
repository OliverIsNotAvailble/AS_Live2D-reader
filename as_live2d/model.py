"""Read model3 manifests without requiring a GPU or live2d-py."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import math


@dataclass(frozen=True)
class Motion:
    group: str
    index: int
    path: Path
    duration: float
    fps: float

    @property
    def label(self) -> str:
        return f"{self.group} [{self.index}]  ·  {self.duration:.2f}s  ·  {self.fps:g} FPS"

    def frames(self, fps_override: float | None = None) -> int:
        rate = fps_override if fps_override and fps_override > 0 else self.fps
        return max(1, math.ceil(self.duration * rate))


@dataclass
class ModelCatalog:
    path: Path
    name: str
    motions: list[Motion] = field(default_factory=list)
    expressions: list[tuple[str, Path]] = field(default_factory=list)
    assets: list[tuple[str, Path, bool]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        return [f"{kind}: {path}" for kind, path, exists in self.assets if not exists]

    @property
    def can_load(self) -> bool:
        return not any(
            not exists and kind in ("MOC3", "Texture")
            for kind, _, exists in self.assets
        )

    @property
    def groups(self) -> list[str]:
        return list(dict.fromkeys(m.group for m in self.motions))


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def reference_path(base: Path, name: str) -> Path:
    # Cubism paths use forward slashes, even on Windows.
    return (base / name.replace("\\", "/")).resolve()


def inspect_model(model_path: str | Path) -> ModelCatalog:
    model_path = Path(model_path).expanduser().resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    info = read_json(model_path)
    refs = info.get("FileReferences")
    if not isinstance(refs, dict):
        raise ValueError("FileReferences is missing from model3.json")

    catalog = ModelCatalog(path=model_path, name=str(info.get("Name") or model_path.stem))
    base = model_path.parent

    def add_reference(kind: str, value: str | None) -> Path | None:
        if not value or not isinstance(value, str):
            return None
        target = reference_path(base, value)
        catalog.assets.append((kind, target, target.is_file()))
        return target

    if not add_reference("MOC3", refs.get("Moc")):
        catalog.warnings.append("Missing FileReferences.Moc")
        catalog.assets.append(("MOC3", base / "<missing>", False))

    textures = refs.get("Textures") or []
    if not isinstance(textures, list):
        textures = []
        catalog.warnings.append("Invalid FileReferences.Textures")
    if not textures:
        catalog.warnings.append("Model does not reference any textures")
    for value in textures:
        add_reference("Texture", value)

    for key in ("Physics", "Pose", "DisplayInfo", "UserData"):
        add_reference(key, refs.get(key))

    expressions = refs.get("Expressions") or []
    if isinstance(expressions, list):
        for index, entry in enumerate(expressions):
            if not isinstance(entry, dict):
                continue
            path = add_reference("Expression", entry.get("File"))
            if path is not None:
                catalog.expressions.append((str(entry.get("Name") or index), path))

    motions = refs.get("Motions") or {}
    if not isinstance(motions, dict):
        catalog.warnings.append("Invalid FileReferences.Motions")
        motions = {}
    for group, entries in motions.items():
        if not isinstance(entries, list):
            catalog.warnings.append(f"Invalid motion group: {group}")
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            target = add_reference("Motion", entry.get("File"))
            if target is None or not target.is_file():
                catalog.warnings.append(f"Unavailable motion: {group}[{index}]")
                continue
            try:
                motion = read_json(target)
                meta = motion.get("Meta") or {}
                duration = float(meta.get("Duration", 0))
                fps = float(meta.get("Fps", 30))
                if not math.isfinite(duration) or duration <= 0:
                    raise ValueError("Invalid Duration")
                if not math.isfinite(fps) or fps <= 0:
                    fps = 30
                catalog.motions.append(Motion(str(group), index, target, duration, fps))
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                catalog.warnings.append(f"{group}[{index}]: {exc}")

    return catalog


def profile_path(model: Path) -> Path:
    # Separate from the project's own Cubism manifest.
    return model.parent / (model.name + ".as-reader.json")


def load_profile(model: Path) -> dict:
    target = profile_path(model)
    if not target.is_file():
        return {}
    data = read_json(target)
    return data if data.get("format") == "AS_Live2D-reader" else {}


def save_profile(model: Path, values: dict) -> Path:
    target = profile_path(model)
    content = dict(values)
    content["format"] = "AS_Live2D-reader"
    content["version"] = 1
    pending = target.with_suffix(target.suffix + ".part")
    pending.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    pending.replace(target)
    return target
