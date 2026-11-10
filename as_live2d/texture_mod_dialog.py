"""Optional ArtMesh-oriented atlas retouch dialog.

The compiled .moc3 is untouched: the pinned Cubism runtime can list
ArtMesh IDs, but cannot edit their vertices/UVs or map each drawable to
the exact atlas pixels. The user manually identifies the intended atlas
region and erases/replaces its pixels in a standalone /mod bundle.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QGraphicsPathItem,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from .model import read_json, reference_path
from .texture_mod import Stroke, clone_mod_bundle, erase_regions


class AtlasCanvas(QGraphicsView):
    stroke_created = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._image = QGraphicsPixmapItem()
        self._scene.addItem(self._image)
        self._outline = QGraphicsPathItem()
        self._outline.setZValue(2)
        self._scene.addItem(self._outline)
        self._rectangle = QGraphicsRectItem()
        self._rectangle.setPen(QPen(QColor("#f67e7e"), 2))
        self._rectangle.setBrush(QBrush(QColor(246, 126, 126, 55)))
        self._rectangle.setZValue(2)
        self._scene.addItem(self._rectangle)
        self._rectangle.hide()
        self.tool = "brush"
        self.size = 35
        self._dragging = False
        self._points: list[tuple[float, float]] = []
        self._zoom_changed = False
        tile = QPixmap(20, 20)
        tile.fill(QColor(190, 196, 203))
        painter = QPainter(tile)
        painter.fillRect(0, 0, 10, 10, QColor(244, 247, 250))
        painter.fillRect(10, 10, 10, 10, QColor(244, 247, 250))
        painter.end()
        self.setBackgroundBrush(QBrush(tile))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setMouseTracking(True)

    def set_image(self, image: QImage):
        self._image.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(0, 0, image.width(), image.height())
        self._reset_stroke()
        if not self._zoom_changed:
            self.fit_to_image()

    def fit_to_image(self):
        self._zoom_changed = False
        if not self._image.pixmap().isNull():
            self.fitInView(self._image, Qt.AspectRatioMode.KeepAspectRatio)

    def _pixel(self, position) -> tuple[float, float]:
        point = self.mapToScene(position)
        bounds = self._scene.sceneRect()
        return (max(0.0, min(bounds.width(), point.x())),
                max(0.0, min(bounds.height(), point.y())))

    def _reset_stroke(self):
        self._points.clear()
        self._dragging = False
        self._outline.setPath(QPainterPath())
        self._rectangle.hide()

    def _draw_stroke(self):
        if not self._points:
            return
        if self.tool == "rectangle":
            self._rectangle.show()
            self._rectangle.setRect(
                QRectF(QPointF(*self._points[0]),
                       QPointF(*self._points[-1])).normalized())
        else:
            path = QPainterPath(QPointF(*self._points[0]))
            for point in self._points[1:]:
                path.lineTo(*point)
            self._outline.setPen(QPen(
                QColor(247, 92, 92, 190), self.size,
                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin))
            self._outline.setPath(path)

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and
                not self._image.pixmap().isNull()):
            self._dragging = True
            self._points = [self._pixel(event.position().toPoint())]
            self._draw_stroke()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._points.append(self._pixel(event.position().toPoint()))
            self._draw_stroke()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._points.append(self._pixel(event.position().toPoint()))
            operation = Stroke(self.tool, tuple(self._points), self.size)
            self._reset_stroke()
            self.stroke_created.emit(operation)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        factor = 1.20 if event.angleDelta().y() > 0 else 1 / 1.20
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.scale(factor, factor)
        self._zoom_changed = True
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._zoom_changed and not self._image.pixmap().isNull():
            self.fit_to_image()


class TextureModDialog(QDialog):
    """Edit or erase bad texture regions then save a new self-contained model."""

    def __init__(self, manifest: Path, drawable_ids=(), parent=None):
        super().__init__(parent)
        self.manifest = Path(manifest).resolve()
        refs = read_json(self.manifest).get("FileReferences") or {}
        self.paths = [
            reference_path(self.manifest.parent, value)
            for value in (refs.get("Textures") or [])
        ]
        if not self.paths:
            raise ValueError("The model has no texture atlas.")
        self.created_manifest: Path | None = None
        self._originals: dict[int, QImage] = {}
        self._replaced: dict[int, QImage] = {}
        self._strokes: dict[int, list[Stroke]] = {}
        self.setWindowTitle("Live2D · Mod ArtMesh / textura (sem alterar original)")
        self.resize(1120, 820)
        self.setMinimumSize(650, 480)
        self.setStyleSheet(
            "QDialog { background: #1f2734; color: #f1f6ff; }"
            "QLabel { color: #f1f6ff; }"
            "QPushButton { padding: 7px; background: #354964; color: #f1f6ff;"
            "border: 1px solid #516988; border-radius: 4px; }"
            "QPushButton:hover { background: #45648a; }"
            "QComboBox, QSpinBox { padding: 5px; color: #18202a;"
            "background: #f4f7fc; }")
        layout = QVBoxLayout(self)
        warning = QLabel(
            "O .moc3 é compilado: este editor NÃO altera os vértices/UVs da "
            "ArtMesh. Ele recorta ou substitui a TEXTURA que a peça usa. "
            "Se duas ArtMeshes compartilham os pixels, as duas podem mudar. "
            "O programa cria uma cópia completa em mod/, sem tocar no original.")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        first = QHBoxLayout()
        first.addWidget(QLabel("ArtMesh (referência):"))
        self.drawable_choice = QComboBox()
        self.drawable_choice.addItem("Selecione a peça pelo ID (atlas manual)")
        for ident in drawable_ids:
            self.drawable_choice.addItem(str(ident))
        self.drawable_choice.setToolTip(
            "O live2d-py lista IDs de ArtMesh, mas não expõe os UVs para "
            "selecionar automaticamente sua região no atlas.")
        first.addWidget(self.drawable_choice, 2)
        first.addWidget(QLabel("Atlas:"))
        self.atlas_choice = QComboBox()
        for i, p in enumerate(self.paths):
            self.atlas_choice.addItem(f"{i}: {p.name}", i)
        first.addWidget(self.atlas_choice, 1)
        layout.addLayout(first)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Ferramenta:"))
        self.tool_choice = QComboBox()
        self.tool_choice.addItem("Borracha / pincel", "brush")
        self.tool_choice.addItem("Apagar retângulo", "rectangle")
        tools.addWidget(self.tool_choice)
        tools.addWidget(QLabel("Diâmetro:"))
        self.size_choice = QSpinBox()
        self.size_choice.setRange(1, 512)
        self.size_choice.setValue(35)
        self.size_choice.setSuffix(" px")
        tools.addWidget(self.size_choice)
        self.fit_button = QPushButton("Enquadrar")
        tools.addWidget(self.fit_button)
        tools.addStretch(1)
        self.external_button = QPushButton("Salvar atlas PNG para editar fora")
        self.import_button = QPushButton("Importar PNG editado")
        tools.addWidget(self.external_button)
        tools.addWidget(self.import_button)
        layout.addLayout(tools)

        self.canvas = AtlasCanvas()
        self.canvas.stroke_created.connect(self._add_stroke)
        layout.addWidget(self.canvas, 1)

        actions = QHBoxLayout()
        self.state = QLabel("")
        actions.addWidget(self.state, 1)
        undo = QPushButton("Desfazer")
        undo.clicked.connect(self._undo)
        actions.addWidget(undo)
        restore = QPushButton("Restaurar atlas")
        restore.clicked.connect(self._restore)
        actions.addWidget(restore)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        save = QPushButton("Salvar cópia em mod/ e abrir")
        save.clicked.connect(self._save_mod)
        actions.addWidget(save)
        layout.addLayout(actions)

        self.atlas_choice.currentIndexChanged.connect(self._render)
        self.tool_choice.currentIndexChanged.connect(self._sync_tool)
        self.size_choice.valueChanged.connect(self._sync_tool)
        self.fit_button.clicked.connect(self.canvas.fit_to_image)
        self.external_button.clicked.connect(self._export_png)
        self.import_button.clicked.connect(self._import_png)
        self._sync_tool()
        self._render()

    def _index(self):
        return int(self.atlas_choice.currentData())

    def _original(self, index):
        if index not in self._originals:
            image = QImage(str(self.paths[index]))
            if image.isNull():
                raise ValueError(f"Cannot load texture atlas: {self.paths[index]}")
            self._originals[index] = image.convertToFormat(
                QImage.Format.Format_ARGB32)
        return self._originals[index]

    def _image(self, index):
        starting = self._replaced.get(index, self._original(index))
        return erase_regions(starting, self._strokes.get(index, []))

    def _render(self, *_):
        try:
            image = self._image(self._index())
            self.canvas.set_image(image)
            n = sum(len(x) for x in self._strokes.values())
            self.state.setText(
                f"{image.width()}×{image.height()} · {n} recorte(s)"
                f" · {'PNG substituído' if self._index() in self._replaced else 'PNG original'}"
                f" · role a roda para zoom")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Erro na textura", str(exc))

    def _sync_tool(self, *_):
        self.canvas.tool = self.tool_choice.currentData()
        self.canvas.size = self.size_choice.value()

    def _add_stroke(self, stroke):
        self._strokes.setdefault(self._index(), []).append(stroke)
        self._render()

    def _undo(self):
        items = self._strokes.get(self._index(), [])
        if items:
            items.pop()
            self._render()

    def _restore(self):
        self._strokes.pop(self._index(), None)
        self._replaced.pop(self._index(), None)
        self._render()

    def _export_png(self):
        i = self._index()
        name, _ = QFileDialog.getSaveFileName(
            self, "Exportar atlas PNG para edição externa",
            str(self.manifest.parent / f"atlas_{i:02d}_work.png"),
            "PNG (*.png)")
        if name and not self._image(i).save(name, "PNG"):
            QMessageBox.warning(self, "Erro", "Não consegui salvar o PNG.")

    def _import_png(self):
        i = self._index()
        name, _ = QFileDialog.getOpenFileName(
            self, "Importar PNG editado", str(self.manifest.parent),
            "PNG (*.png)")
        if not name:
            return
        image = QImage(name)
        if image.isNull() or image.size() != self._original(i).size():
            QMessageBox.warning(
                self, "Tamanho incompatível",
                f"O PNG precisa ter exatamente {self._original(i).width()} × "
                f"{self._original(i).height()} pixels.")
            return
        self._replaced[i] = image.convertToFormat(QImage.Format.Format_ARGB32)
        self._strokes.pop(i, None)
        self._render()

    def _save_mod(self):
        indices = sorted(set(self._replaced) |
                         {i for i, xs in self._strokes.items() if xs})
        if not indices:
            QMessageBox.information(
                self, "Sem alterações",
                "Apaga algum pixel ou importa um PNG editado primeiro.")
            return
        try:
            changed = {i: self._image(i) for i in indices}
            self.created_manifest = clone_mod_bundle(self.manifest, changed)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Falha ao salvar mod", str(exc))
            return
        self.accept()
