"""Read real Cubism ArtMesh UV triangles from compiled MOC3, non-destructively.

The live2d-py runtime exposes drawable IDs but not their UVs through Python.
py-moc3 parses those immutable texture/page/UV/triangle arrays directly from
the model. All edits below are clipped to the selected ArtMesh UV triangles;
the copied .moc3 remains untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen

from .model import read_json, reference_path
from .texture_mod import Stroke


@dataclass(frozen=True)
class ArtMeshUV:
    mesh_id: str
    texture_index: int
    uv: tuple[tuple[float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]

    def path(self, width: int, height: int, flip_v: bool = True) -> QPainterPath:
        p = QPainterPath()
        p.setFillRule(Qt.FillRule.WindingFill)

        def point(index: int) -> QPointF:
            u, v = self.uv[index]
            return QPointF(u * width, (1 - v if flip_v else v) * height)

        for a, b, c in self.triangles:
            p.moveTo(point(a))
            p.lineTo(point(b))
            p.lineTo(point(c))
            p.closeSubpath()
        return p

    def crop_bounds(self, width: int, height: int, flip_v: bool = True) -> QRect:
        bounds = self.path(width, height, flip_v).boundingRect()
        if not bounds.isValid() or bounds.isEmpty():
            raise ValueError(f"ArtMesh {self.mesh_id} has no usable UV region")
        # Small margin shows antialiased UV edges and avoids a tight clipped view.
        return bounds.toAlignedRect().adjusted(-8, -8, 8, 8).intersected(
            QRect(0, 0, width, height))


def _uv_stride(moc) -> int:
    """Some MOC3 versions index UVs by vectors, others by packed floats.

    Prefer evidence from consecutive art meshes; never silently choose a
    mode that points beyond the section's valid bounds.
    """
    begins = moc["art_mesh.uv_begin_indices"]
    counts = moc["art_mesh.vertex_counts"]
    uv_length = len(moc["uv.xys"])
    score = {1: 0, 2: 0}
    for i in range(len(begins) - 1):
        delta = begins[i + 1] - begins[i]
        n = counts[i]
        if n > 0 and delta > 0:
            if delta == n:
                score[2] += 1
            if delta == 2 * n:
                score[1] += 1

    # If no adjacent-mesh evidence, prefer byte-float offsets (stride 1).
    order = (2, 1) if score[2] > score[1] else (1, 2)
    for stride in order:
        if all(
            begin >= 0 and count >= 0 and
            stride * begin + 2 * count <= uv_length
            for begin, count in zip(begins, counts)
        ):
            return stride
    raise ValueError("MOC3 UV offsets/counts do not match available coordinate data")


def meshes_from_moc(moc, texture_count: int) -> list[ArtMeshUV]:
    ids = moc["art_mesh.ids"]
    pages = moc["art_mesh.texture_indices"]
    vertex_counts = moc["art_mesh.vertex_counts"]
    uv_begins = moc["art_mesh.uv_begin_indices"]
    index_counts = moc["art_mesh.position_index_counts"]
    index_begins = moc["art_mesh.position_index_begin_indices"]
    all_uv = moc["uv.xys"]
    all_indices = moc["position_index.indices"]
    n = len(ids)
    if not all(len(arr) == n for arr in
               (pages, vertex_counts, uv_begins, index_counts, index_begins)):
        raise ValueError("MOC3 ArtMesh section sizes disagree; refusing an unsafe UV mapping")
    stride = _uv_stride(moc)
    regions: list[ArtMeshUV] = []
    for i, mesh_id in enumerate(ids):
        count = vertex_counts[i]
        begin = uv_begins[i] * stride
        count_indices = index_counts[i]
        begin_indices = index_begins[i]
        page = pages[i]
        if page < 0 or page >= texture_count or count < 3 or count > 100000:
            continue
        if begin < 0 or begin + 2 * count > len(all_uv):
            continue
        if count_indices < 3 or count_indices % 3 != 0 or begin_indices < 0 or \
                begin_indices + count_indices > len(all_indices):
            continue
        uv_pairs = tuple(
            (float(all_uv[begin + 2*j]), float(all_uv[begin + 2*j + 1]))
            for j in range(count)
        )
        if not all(
            math.isfinite(u) and math.isfinite(v) and
            -0.01 <= u <= 1.01 and -0.01 <= v <= 1.01
            for u, v in uv_pairs
        ):
            continue
        indices = all_indices[begin_indices:begin_indices + count_indices]
        if any(int(k) < 0 or int(k) >= count for k in indices):
            continue
        triangles = tuple(tuple(map(int, indices[j:j+3]))
                          for j in range(0, count_indices, 3))
        if not triangles or not mesh_id:
            continue
        regions.append(ArtMeshUV(str(mesh_id), int(page), uv_pairs, triangles))
    return regions


def read_artmeshes(manifest: Path) -> list[ArtMeshUV]:
    """Read .moc3 without runtime hooks, recompiling or modifying it."""
    try:
        from moc3 import Moc3
    except ImportError as exc:
        raise RuntimeError(
            "É necessário instalar py-moc3: python -m pip install py-moc3==0.1.0"
        ) from exc
    root = Path(manifest)
    info = read_json(root)
    refs = info.get("FileReferences") or {}
    moc_file = reference_path(root.parent, refs.get("Moc", ""))
    if not moc_file.is_file():
        raise ValueError("Não achei o arquivo .moc3 original")
    model = Moc3.from_file(moc_file)
    meshes = meshes_from_moc(model, len(refs.get("Textures") or []))
    if not meshes:
        raise ValueError("Este MOC3 não expôs UVs/triângulos válidos para edição isolada.")
    return meshes


def isolated_mesh(source: QImage, mesh: ArtMeshUV,
                  flip_v: bool = True) -> tuple[QImage, QRect]:
    """Return ONLY selected ArtMesh pixels, transparent outside its triangles."""
    path = mesh.path(source.width(), source.height(), flip_v)
    rect = mesh.crop_bounds(source.width(), source.height(), flip_v)
    result = source.copy(rect).convertToFormat(QImage.Format.Format_ARGB32)
    mask = QImage(rect.size(), QImage.Format.Format_ARGB32)
    mask.fill(Qt.GlobalColor.transparent)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(-rect.left(), -rect.top())
    painter.fillPath(path, Qt.GlobalColor.white)
    painter.end()
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, mask)
    painter.end()
    return result, rect


def _draw_brush(painter: QPainter, stroke: Stroke, left: int, top: int):
    coords = [QPointF(x + left, y + top) for x, y in stroke.points]
    if stroke.mode == "rectangle" and len(coords) >= 2:
        painter.fillRect(
            __import__("PySide6.QtCore", fromlist=["QRectF"]).QRectF(
                coords[0], coords[-1]).normalized(), Qt.GlobalColor.transparent)
    elif stroke.mode == "brush" and coords:
        if len(coords) == 1:
            path = QPainterPath()
            path.addEllipse(coords[0], stroke.size/2, stroke.size/2)
            painter.fillPath(path, Qt.GlobalColor.transparent)
        else:
            path = QPainterPath(coords[0])
            for point in coords[1:]:
                path.lineTo(point)
            painter.setPen(QPen(Qt.GlobalColor.transparent, max(1, stroke.size),
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)


def apply_mesh_stroke(image: QImage, mesh: ArtMeshUV, stroke: Stroke,
                      flip_v: bool = True) -> QImage:
    """Edit in a cropped view but erase ONLY pixels inside UV triangles."""
    result = image.copy().convertToFormat(QImage.Format.Format_ARGB32)
    rect = mesh.crop_bounds(image.width(), image.height(), flip_v)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setClipPath(mesh.path(image.width(), image.height(), flip_v))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    _draw_brush(painter, stroke, rect.left(), rect.top())
    painter.end()
    return result


def apply_mesh_patch(image: QImage, mesh: ArtMeshUV, patch: QImage,
                     flip_v: bool = True) -> QImage:
    """Import cropped PNG but copy only within the ArtMesh UV footprint."""
    rect = mesh.crop_bounds(image.width(), image.height(), flip_v)
    if patch.isNull() or patch.size() != rect.size():
        raise ValueError(f"PNG precisa ter {rect.width()}×{rect.height()} pixels")
    result = image.copy().convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setClipPath(mesh.path(image.width(), image.height(), flip_v))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawImage(rect.topLeft(), patch)
    painter.end()
    return result
