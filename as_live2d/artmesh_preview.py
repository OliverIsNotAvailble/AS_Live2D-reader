"""Fast, memory-bounded UV thumbnails built outside the Qt GUI thread.

The worker only uses QImage/QPainter (no QWidget or QPixmap) and never
rewrites a source atlas. Clicking a selector entry shows an existing snapshot.
"""
from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRectF, QRunnable, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QTransform

from .artmesh_uv import ArtMeshUV


def render_mesh_preview(
    source: QImage, mesh: ArtMeshUV, flip_v: bool = True,
    max_dimension: int = 384,
) -> QImage:
    """Sample a UV-clipped, scaled ArtMesh without creating a full-size crop.

    Both the output image and its QPainter mask stay thumbnail-sized even
    when the source atlas is 4096x4096 or larger.
    """
    if source.isNull() or max_dimension < 1:
        raise ValueError("Imagem de atlas inválida ou tamanho de preview inválido")
    rect = mesh.crop_bounds(source.width(), source.height(), flip_v)
    scale = min(1.0, max_dimension / max(rect.width(), rect.height()))
    width = max(1, round(rect.width() * scale))
    height = max(1, round(rect.height() * scale))
    sx, sy = width / rect.width(), height / rect.height()
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    # Map UV polygons directly into the small output, not a giant alpha mask.
    transform = QTransform(sx, 0, 0, sy, -rect.left() * sx, -rect.top() * sy)
    path = transform.map(mesh.path(source.width(), source.height(), flip_v))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setClipPath(path)
        painter.drawImage(QRectF(0, 0, width, height), source, QRectF(rect))
    finally:
        painter.end()
    return image


class PreviewSignals(QObject):
    image_ready = Signal(int, str, QImage, int, int)
    failed = Signal(int, str)
    finished = Signal(int, bool)


class PreviewBuilder(QRunnable):
    """Emit thumbnails individually so the GUI remains responsive.

    One source QImage is retained per texture page for the duration of this
    build. QPixmap conversion is deliberately left to the receiving GUI.
    """

    def __init__(self, paths: list[Path], meshes: tuple[ArtMeshUV, ...],
                 flip_v: bool, generation: int):
        super().__init__()
        self.setAutoDelete(False)
        self.paths = tuple(Path(path) for path in paths)
        self.meshes = meshes
        self.flip_v = flip_v
        self.generation = generation
        self.signals = PreviewSignals()
        self._cancelled = Event()

    def cancel(self):
        self._cancelled.set()

    def run(self):
        try:
            sources: dict[int, QImage] = {}
            total = len(self.meshes)
            for done, mesh in enumerate(self.meshes, 1):
                if self._cancelled.is_set():
                    break
                index = mesh.texture_index
                if index not in sources:
                    source = QImage(str(self.paths[index]))
                    if source.isNull():
                        raise ValueError(
                            f"Não foi possível abrir o atlas {self.paths[index]}")
                    sources[index] = source
                preview = render_mesh_preview(
                    sources[index], mesh, self.flip_v)
                if self._cancelled.is_set():
                    break
                self.signals.image_ready.emit(
                    self.generation, mesh.mesh_id, preview, done, total)
        except Exception as exc:
            self.signals.failed.emit(self.generation, str(exc))
            self._cancelled.set()
        finally:
            self.signals.finished.emit(
                self.generation, self._cancelled.is_set())
