"""Individual Cubism ArtMesh hide with ONE transparent 1x1 texture.

A hidden drawable gets its texture-index field redirected to a new, blank
texture slot in a TEMPORARY MOC3 binary. The source MOC3 is never changed.

Unlike py-moc3's serializer, patching exactly four bytes in the existing
binary per selected ArtMesh retains the original MOC3 header, offsets, and
all unrelated sections. No atlas is read or copied; UV orientation is not
involved at all.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import struct

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage

from .model import read_json, reference_path


def patch_texture_indices(source: Path, destination: Path,
                          hidden_mesh_ids: set[str],
                          new_texture_index: int) -> None:
    """Redirect selected drawables to a transparent texture page.

    Validates every original 4-byte field against py-moc3's parsed values
    before changing anything. No reserialization and no changes to MOC3 header.
    """
    from moc3 import Moc3

    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if source == destination:
        raise ValueError("Nunca sobrescrever o MOC3 original.")
    if not hidden_mesh_ids:
        raise ValueError("Nenhuma ArtMesh selecionada.")
    if not 0 <= new_texture_index < (1 << 31):
        raise ValueError("Índice de textura transparente inválido.")

    original = source.read_bytes()
    moc = Moc3.from_bytes(original)
    if moc.header.endian != 0:
        raise ValueError("Formato MOC3 big-endian não suportado com segurança.")
    mesh_ids = [str(ident) for ident in moc["art_mesh.ids"]]
    indices = list(map(int, moc["art_mesh.texture_indices"]))
    if len(indices) != len(mesh_ids) or len(set(mesh_ids)) != len(mesh_ids):
        raise ValueError("IDs/índices de ArtMeshes inconsistentes.")
    positions = {ident: i for i, ident in enumerate(mesh_ids)}
    missing = hidden_mesh_ids.difference(positions)
    if missing:
        raise ValueError(
            "ArtMeshes ausentes: " + ", ".join(sorted(missing)[:8]))
    if new_texture_index in indices:
        raise ValueError("A textura transparente já está em uso pelo modelo.")

    names = [entry.name for entry in moc._layout]
    try:
        section_slot = 2 + names.index("art_mesh.texture_indices")
        begin = int(moc._sot_offsets[section_slot])
    except (ValueError, IndexError, AttributeError) as exc:
        raise ValueError("Seção de índices de textura não encontrada.") from exc
    end = begin + 4 * len(indices)
    if begin < 1984 or end > len(original):
        raise ValueError("Seção de textura fora dos limites do MOC3.")
    if section_slot + 1 < len(moc._sot_offsets):
        next_begin = int(moc._sot_offsets[section_slot + 1])
        if next_begin and end > next_begin:
            raise ValueError("A seção de textura sobrepõe a seção seguinte.")

    # Verify the entire section, not just the selected item. If py-moc3
    # addresses a different slot in this MOC3 version, refuse to patch.
    for i, expected in enumerate(indices):
        actual = struct.unpack_from("<i", original, begin + i * 4)[0]
        if actual != expected:
            raise ValueError(
                "Mapeamento binário do MOC3 divergente; alteração cancelada.")

    patched = bytearray(original)
    for ident in hidden_mesh_ids:
        struct.pack_into(
            "<i", patched, begin + positions[ident] * 4,
            new_texture_index)
    if patched[:begin] != original[:begin] or patched[end:] != original[end:]:
        raise ValueError("Regiões indevidas do MOC3 alteradas.")
    # Explicit byte-difference guard; only hidden mesh texture indices change.
    allowed_bytes = {
        offset
        for ident in hidden_mesh_ids
        for offset in range(begin + positions[ident] * 4,
                            begin + positions[ident] * 4 + 4)
    }
    if any(old != new and index not in allowed_bytes
           for index, (old, new) in enumerate(zip(original, patched))):
        raise ValueError("Alteração além do índice da ArtMesh detectada.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(patched)
    if destination.stat().st_size != len(original):
        raise ValueError("Tamanho do MOC3 temporário mudou.")


def _relative_asset(source_dir: Path, temp_dir: Path, ref: str) -> str:
    source = reference_path(source_dir, ref)
    if not source.is_file():
        raise FileNotFoundError(f"Recurso não encontrado: {source}")
    return os.path.relpath(source, temp_dir).replace(os.sep, "/")


def write_live_preview(manifest: Path, temp_dir: Path,
                       choices: dict[str, bool], generation: int) -> Path:
    """Create a small shadow model referencing ONE tiny transparent PNG."""
    manifest = Path(manifest).resolve()
    if not choices:
        return manifest
    if any(type(value) is not bool for value in choices.values()):
        raise ValueError("Seleção de ArtMesh deve ser booleana.")
    if any(choices.values()):
        # Only hide is needed. SHOW of an originally hidden drawable cannot
        # be forced with a texture slot; restored visible meshes remove their
        # hidden override and use the original texture index again.
        raise ValueError("Esta função apenas oculta ArtMeshes.")
    data = deepcopy(read_json(manifest))
    refs = data.get("FileReferences")
    if not isinstance(refs, dict) or not refs.get("Moc"):
        raise ValueError("O modelo não tem FileReferences.Moc.")
    pages = refs.get("Textures")
    if not isinstance(pages, list) or not pages:
        raise ValueError("O modelo não tem páginas de textura.")

    temp_dir = Path(temp_dir).resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)
    # Two rotating slots avoid filling the cache with dozens of MOC3 files
    # while ensuring we never overwrite the exact file currently loaded.
    suffix = generation % 2
    moc_name = f"mesh_live_{suffix}.moc3"
    original_moc = reference_path(manifest.parent, refs["Moc"])
    patch_texture_indices(original_moc, temp_dir / moc_name,
                          set(choices), len(pages))
    refs["Moc"] = moc_name

    blank_name = "transparent_1x1.png"
    blank_path = temp_dir / blank_name
    if not blank_path.is_file():
        blank = QImage(1, 1, QImage.Format.Format_ARGB32)
        blank.fill(Qt.GlobalColor.transparent)
        if not blank.save(str(blank_path), "PNG"):
            raise OSError("Falha ao criar PNG transparente temporário.")

    refs["Textures"] = [
        _relative_asset(manifest.parent, temp_dir, ref) for ref in pages
    ] + [blank_name]
    for key in ("Physics", "Pose", "DisplayInfo", "UserData"):
        if refs.get(key):
            refs[key] = _relative_asset(manifest.parent, temp_dir, refs[key])
    for entries in (refs.get("Motions") or {}).values():
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    for key in ("File", "Sound"):
                        if entry.get(key):
                            entry[key] = _relative_asset(
                                manifest.parent, temp_dir, entry[key])
    for entry in refs.get("Expressions") or []:
        if isinstance(entry, dict) and entry.get("File"):
            entry["File"] = _relative_asset(
                manifest.parent, temp_dir, entry["File"])

    shadow = temp_dir / f"mesh_live_{suffix}.model3.json"
    shadow.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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
