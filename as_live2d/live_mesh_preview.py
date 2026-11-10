"""Transient per-ArtMesh model for immediate preview and export.

No MOD is produced: a temporary manifest and compiled MOC3 reference the
original assets, and are discarded when the application closes.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .mesh_visibility import write_visibility_copy
from .model import read_json, reference_path


def _relative_asset(source_dir: Path, temp_dir: Path, ref: str) -> str:
    source = reference_path(source_dir, ref)
    if not source.is_file():
        raise FileNotFoundError(f"Recurso não encontrado: {source}")
    return os.path.relpath(source, temp_dir).replace(os.sep, "/")


def write_live_preview(manifest: Path, temp_dir: Path,
                       choices: dict[str, bool], generation: int) -> Path:
    manifest = Path(manifest).resolve()
    if not choices:
        return manifest
    temp_dir = Path(temp_dir).resolve()
    info = deepcopy(read_json(manifest))
    refs = info.get("FileReferences")
    if not isinstance(refs, dict) or not refs.get("Moc"):
        raise ValueError("Modelo Cubism sem FileReferences.Moc")
    original_moc = reference_path(manifest.parent, refs["Moc"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    patch_name = f"mesh_live_{generation:06d}.moc3"
    write_visibility_copy(original_moc, temp_dir / patch_name, choices)
    refs["Moc"] = patch_name
    for key in ("Physics", "Pose", "DisplayInfo", "UserData"):
        if refs.get(key):
            refs[key] = _relative_asset(manifest.parent, temp_dir, refs[key])
    refs["Textures"] = [
        _relative_asset(manifest.parent, temp_dir, ref)
        for ref in (refs.get("Textures") or [])
    ]
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
