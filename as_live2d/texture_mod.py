"""Safe visual ArtMesh fixes via a *copy* of the Cubism texture atlas.

Cubism's compiled .moc3 mesh geometry is deliberately NOT modified. The
pinned live2d-py has GetDrawableIds but no writable vertex/UV setters.
Erase selected pixels, or replace an atlas PNG, and copy the entire manifest
resource graph to model-parent/mod/<model>_mod_001/. Original files are intact.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen

from .model import read_json, reference_path
from .layer_mod import write_moc_with_draw_depths
from .mesh_visibility import write_visibility_copy


@dataclass(frozen=True)
class Stroke:
    mode: str
    points: tuple[tuple[float, float], ...]
    size: int = 30


def erase_regions(source: QImage, operations: list[Stroke]) -> QImage:
    """Transparent rectangle/brush erasing; repeatable for Undo/Reset."""
    if source.isNull():
        raise ValueError("Atlas image unavailable")
    image = source.convertToFormat(QImage.Format.Format_ARGB32).copy()
    if not operations:
        return image
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    try:
        for op in operations:
            if not op.points:
                continue
            if op.mode == "rectangle" and len(op.points) >= 2:
                a = op.points[0]
                b = op.points[-1]
                p.fillRect(QRectF(QPointF(*a), QPointF(*b)).normalized(),
                           Qt.GlobalColor.transparent)
            elif op.mode == "brush":
                coords = op.points
                if len(coords) == 1:
                    cx, cy = coords[0]
                    path = QPainterPath()
                    path.addEllipse(QPointF(cx, cy), op.size / 2, op.size / 2)
                    p.fillPath(path, Qt.GlobalColor.transparent)
                else:
                    path = QPainterPath(QPointF(*coords[0]))
                    for point in coords[1:]:
                        path.lineTo(*point)
                    p.setPen(QPen(Qt.GlobalColor.transparent, max(1, op.size),
                                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                  Qt.PenJoinStyle.RoundJoin))
                    p.drawPath(path)
    finally:
        p.end()
    return image


def _safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:100] or "model"


def clone_mod_bundle(
    manifest: Path, replacements: dict[int, QImage],
    *, layer_overrides: dict[str, int] | None = None,
    visibility_overrides: dict[str, bool] | None = None,
) -> Path:
    """Create a self-contained, never-overwriting Cubism model in /mod.

    Original files are never overwritten. By default the MOC3 is copied
    byte-for-byte; optional experimental layer edits patch only the MOC3 COPY
    inside the temporary stage. References and sound resources stay independent.
    """
    layer_overrides = dict(layer_overrides or {})
    visibility_overrides = dict(visibility_overrides or {})
    manifest = Path(manifest).expanduser().resolve()
    info = deepcopy(read_json(manifest))
    refs = info.get("FileReferences")
    if not isinstance(refs, dict) or not isinstance(refs.get("Moc"), str):
        raise ValueError("Invalid model3.json: FileReferences.Moc is missing")
    atlas_list = refs.get("Textures")
    if not isinstance(atlas_list, list) or not atlas_list:
        raise ValueError("Invalid model3.json: no textures referenced")
    if not replacements and not layer_overrides and not visibility_overrides:
        raise ValueError("No edited textures or layer changes to save")
    for index, image in replacements.items():
        if (not isinstance(index, int) or index < 0 or
                index >= len(atlas_list) or not isinstance(image, QImage) or
                image.isNull()):
            raise ValueError("Invalid edited atlas index/image")

    stem = manifest.name
    stem = stem[:-12] if stem.lower().endswith(".model3.json") else manifest.stem
    stem = _safe_filename(stem)
    # Re-editing a saved model creates a sibling instead of nesting mod/mod.
    parent = manifest.parent
    if parent.parent.name.casefold() == "mod":
        mod_root = parent.parent
    else:
        mod_root = parent / "mod"
    mod_root.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        result = mod_root / f"{stem}_mod_{suffix:03d}"
        if not result.exists():
            break
        suffix += 1

    stage = Path(tempfile.mkdtemp(prefix=".live2d_mod_temp_", dir=mod_root))
    try:
        def copy_file(ref: str, name: str) -> str:
            src = reference_path(manifest.parent, ref)
            if not src.is_file():
                raise FileNotFoundError(f"Missing referenced file: {src}")
            rel = name.replace("\\", "/")
            target = stage / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            return rel

        for key in ("Moc", "Physics", "Pose", "DisplayInfo", "UserData"):
            if refs.get(key):
                old = str(refs[key])
                filename = _safe_filename(Path(old.replace("\\", "/")).name)
                refs[key] = copy_file(old, f"assets/{key}_{filename}")

        if layer_overrides:
            # Patch only the staging COPY, not the source model. Write to a
            # separate file first, verify it, then atomically replace the copy.
            copied_moc = stage / refs["Moc"]
            changed_moc = stage / "experimental_layer_patch.moc3"
            write_moc_with_draw_depths(copied_moc, changed_moc, layer_overrides)
            os.replace(changed_moc, copied_moc)
            (stage / "LAYER_MOD.json").write_text(
                json.dumps(layer_overrides, indent=2, ensure_ascii=False),
                encoding="utf-8")

        if visibility_overrides:
            copied_moc = stage / refs["Moc"]
            patched = stage / "mesh_visibility_patch.moc3"
            write_visibility_copy(copied_moc, patched, visibility_overrides)
            os.replace(patched, copied_moc)
            (stage / "MESH_VISIBILITY.json").write_text(
                json.dumps(visibility_overrides, indent=2, ensure_ascii=False),
                encoding="utf-8")

        # Keep Cubism texture index ordering, including unused/unchanged pages.
        for index, old in enumerate(atlas_list):
            src = reference_path(manifest.parent, old)
            if not src.is_file():
                raise FileNotFoundError(f"Texture {index} not found: {src}")
            rel = f"textures/texture_{index:02d}.png"
            target = stage / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if index in replacements:
                original = QImage(str(src))
                edited = replacements[index]
                if original.isNull() or edited.size() != original.size():
                    raise ValueError(
                        f"Edited atlas {index} has different dimensions; refusing to save")
                if not edited.save(str(target), "PNG"):
                    raise OSError(f"Cannot write edited PNG: {target}")
            else:
                image = QImage(str(src))
                if image.isNull() or not image.save(str(target), "PNG"):
                    raise OSError(f"Cannot copy texture as PNG: {src}")
            atlas_list[index] = rel

        motions = refs.get("Motions") or {}
        if isinstance(motions, dict):
            for group, entries in motions.items():
                if not isinstance(entries, list):
                    continue
                for i, entry in enumerate(entries):
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("File"):
                        entry["File"] = copy_file(
                            entry["File"], f"motions/{_safe_filename(str(group))}_{i:03d}.motion3.json")
                    if entry.get("Sound"):
                        old = str(entry["Sound"])
                        ext = Path(old.replace("\\", "/")).suffix
                        entry["Sound"] = copy_file(
                            old, f"sounds/{_safe_filename(str(group))}_{i:03d}{ext}")

        expressions = refs.get("Expressions") or []
        if isinstance(expressions, list):
            for i, entry in enumerate(expressions):
                if isinstance(entry, dict) and entry.get("File"):
                    entry["File"] = copy_file(
                        entry["File"], f"expressions/expression_{i:03d}.exp3.json")

        new_manifest = f"{stem}_mod.model3.json"
        (stage / new_manifest).write_text(
            json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        (stage / "MOD_INFO.txt").write_text(
            "AS Live2D Reader - Non-destructive atlas/ArtMesh visual patch\n"
            f"Original manifest: {manifest}\n"
            f"Edited texture pages: {', '.join(str(i) for i in sorted(replacements))}\n"
            "This copy retains the ORIGINAL MOC3 geometry and motion data.\n"
            f"Experimental ArtMesh depth overrides: {layer_overrides!r}\n"
            "Draw-order groups and parameter-driven states may affect visible layering.\n"
            "Transparent pixels visually trim model textures; shared UV areas may also change.\n"
            "No original resource was overwritten.\n", encoding="utf-8")

        # A source folder may contain massive assets: no backup/overwrite.
        os.rename(stage, result)
        return result / new_manifest
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
