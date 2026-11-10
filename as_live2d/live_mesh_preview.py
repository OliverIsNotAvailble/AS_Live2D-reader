"""Temporary transparent-atlas preview for selected Cubism ArtMeshes.

The compiled MOC3 remains byte-identical: its original path is referenced
directly by the temporary model3.json. The only generated model assets are
temporary PNG copies of affected texture pages, with pixels cleared inside
the selected mesh's real UV triangles.

IMPORTANT: overlapping ArtMeshes can share atlas pixels. An alpha edit
cannot isolate two meshes sampling identical pixels; this is a renderer
limitation and is not presented as a native Drawable visibility override.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPainter

from .artmesh_uv import ArtMeshUV, read_artmeshes
from .model import read_json, reference_path


def _relative_asset(source_dir: Path, temp_dir: Path, ref: str) -> str:
    source = reference_path(source_dir, ref)
    if not source.is_file():
        raise FileNotFoundError(f"Recurso não encontrado: {source}")
    return os.path.relpath(source, temp_dir).replace(os.sep, "/")


def clear_mesh_regions(image: QImage, meshes: list[ArtMeshUV],
                       flip_v: bool = True) -> QImage:
    """Erase selected mesh UV triangles, leaving the rest of the atlas intact."""
    if image.isNull():
        raise ValueError("Atlas inválido.")
    output = image.convertToFormat(QImage.Format.Format_ARGB32)
    output = output.copy()
    painter = QPainter(output)
    try:
        # No antialiasing: opacity along the erased triangle boundary must
        # reach 0 rather than leave a semi-transparent fringe.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        for mesh in meshes:
            painter.fillPath(
                mesh.path(output.width(), output.height(), flip_v),
                Qt.GlobalColor.white)
    finally:
        painter.end()
    return output


def write_live_preview(manifest: Path, temp_dir: Path,
                       choices: dict[str, bool], generation: int) -> Path:
    """Make only a transient altered atlas, never write/repack the source MOC3."""
    manifest = Path(manifest).resolve()
    if not choices:
        return manifest
    if any(type(value) is not bool for value in choices.values()):
        raise ValueError("A visibilidade das ArtMeshes deve ser booleana.")
    if any(choices.values()):
        # Native SHOW cannot be forced by a texture swap when the original
        # MOC3 already has a hidden drawable.
        raise ValueError(
            "Não é possível forçar SHOW de uma ArtMesh oculta no MOC3 "
            "sem um controle nativo de Drawable.")

    temp_dir = Path(temp_dir).resolve()
    info = deepcopy(read_json(manifest))
    refs = info.get("FileReferences")
    if not isinstance(refs, dict) or not isinstance(refs.get("Moc"), str):
        raise ValueError("Modelo Cubism sem FileReferences.Moc")
    originals = refs.get("Textures")
    if not isinstance(originals, list) or not originals:
        raise ValueError("Modelo sem texturas referenciadas")

    all_meshes = {mesh.mesh_id: mesh for mesh in read_artmeshes(manifest)}
    missing = set(choices).difference(all_meshes)
    if missing:
        raise ValueError(
            "UVs não encontradas para ArtMesh(s): " +
            ", ".join(sorted(missing)[:10]))
    page_groups: dict[int, list[ArtMeshUV]] = {}
    for ident in choices:
        mesh = all_meshes[ident]
        page_groups.setdefault(mesh.texture_index, []).append(mesh)

    temp_dir.mkdir(parents=True, exist_ok=True)
    # Never copy/recompile or reserialize the compiled MOC3.
    refs["Moc"] = _relative_asset(manifest.parent, temp_dir, refs["Moc"])
    for key in ("Physics", "Pose", "DisplayInfo", "UserData"):
        if refs.get(key):
            refs[key] = _relative_asset(manifest.parent, temp_dir, refs[key])
    new_textures = []
    for page, ref in enumerate(originals):
        if page in page_groups:
            source_path = reference_path(manifest.parent, ref)
            source = QImage(str(source_path))
            if source.isNull():
                raise ValueError(f"Não foi possível ler o atlas {source_path}")
            output = clear_mesh_regions(source, page_groups[page], flip_v=True)
            target = temp_dir / f"atlas_hidden_{generation:06d}_{page:03d}.png"
            if not output.save(str(target), "PNG"):
                raise OSError(f"Falha ao gerar PNG temporário: {target}")
            new_textures.append(target.name)
        else:
            new_textures.append(_relative_asset(manifest.parent, temp_dir, ref))
    refs["Textures"] = new_textures
    for entries in (refs.get("Motions") or {}).values():
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    for key in ("File", "Sound"):
                        if entry.get(key):
                            entry[key] = _relative_asset(
                                manifest.parent, temp_dir, entry[key])
    for entry in (refs.get("Expressions") or []):
        if isinstance(entry, dict) and entry.get("File"):
            entry["File"] = _relative_asset(
                manifest.parent, temp_dir, entry["File"])
    shadow = temp_dir / f"mesh_live_{generation:06d}.model3.json"
    shadow.write_text(json.dumps(info, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return shadow


class LiveMeshPreviewWorker(QThread):
    ready = Signal(object, object, int)
    failed = Signal(str, object, int)

    def __init__(self, manifest: Path, folder: Path, choices: dict[str, bool],
                 generation: int, parent=None):
        super().__init__(parent)
        self.manifest = Path(manifest)
        self.folder = Path(folder)
        self.choices = dict(choices)
        self.generation = generation

    def run(self):
        try:
            result = write_live_preview(
                self.manifest, self.folder, self.choices, self.generation)
        except Exception as exc:
            self.failed.emit(str(exc), self.manifest, self.generation)
        else:
            self.ready.emit(result, self.manifest, self.generation)
