"""Optional ArtMesh-oriented atlas retouch dialog.

Reads the selected ArtMesh's actual UV triangles from the compiled .moc3
with py-moc3. Displays ONLY the selected piece instead of the entire atlas.
All erase/replacement operations are clipped to those triangles; a separate
copy is saved under mod/ without touching source files.
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
    QCheckBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
    QVBoxLayout,
)

from .model import read_json, reference_path
from .texture_mod import Stroke, clone_mod_bundle
from .artmesh_uv import (
    read_artmeshes, isolated_mesh, apply_mesh_stroke, apply_mesh_patch,
)


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
    """A real per-ArtMesh texture editor. No editable MOC3 geometry claim."""

    def __init__(self, manifest: Path, drawable_ids=(), parent=None):
        super().__init__(parent)
        self.manifest = Path(manifest).resolve()
        refs = read_json(self.manifest).get("FileReferences") or {}
        self.paths = [
            reference_path(self.manifest.parent, value)
            for value in (refs.get("Textures") or [])
        ]
        if not self.paths:
            raise ValueError("O modelo não tem atlas de textura.")

        # This is the important change: actual UV geometry, NOT the complete
        # PNG with a decorative ArtMesh selector.
        mesh_list = read_artmeshes(self.manifest)
        all_meshes = {mesh.mesh_id: mesh for mesh in mesh_list}
        live_ids = {str(name) for name in drawable_ids}
        self.meshes = {
            name: all_meshes[name]
            for name in sorted(all_meshes, key=lambda x: (x not in live_ids, x.lower()))
        }
        if not self.meshes:
            raise ValueError("Não consegui extrair nenhuma ArtMesh com UV válida.")

        self._originals: dict[int, QImage] = {}
        # (ArtMesh ID, "stroke"|"patch", Stroke|QImage, flipV at edit time).
        # Actions are replayed in order so Undo is reliable across many pages.
        self._history: list[tuple[str, str, object, bool]] = []
        self._preview_crop = None
        self.created_manifest: Path | None = None

        self.setWindowTitle("Live2D · Editar ArtMesh isolada → mod")
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
            "Mostrando SOMENTE a ArtMesh selecionada, recortada pelos seus "
            "triângulos UV. Pincel, remoção e PNG externo só alteram essa "
            "região. O .moc3 original não é alterado. Se outra peça usar "
            "os mesmos pixels, ela também poderá ser afetada.")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        first = QHBoxLayout()
        first.addWidget(QLabel("ArtMesh:"))
        self.drawable_choice = QComboBox()
        for ident, mesh in self.meshes.items():
            self.drawable_choice.addItem(
                f"{ident}  [{len(mesh.triangles)} triângulos]", ident)
        self.drawable_choice.setToolTip(
            "Cada opção vem dos triângulos e UVs reais do MOC3.")
        first.addWidget(self.drawable_choice, 3)
        first.addWidget(QLabel("Textura ligada:"))
        self.atlas_choice = QComboBox()
        for i, p in enumerate(self.paths):
            self.atlas_choice.addItem(f"{i}: {p.name}", i)
        self.atlas_choice.setEnabled(False)
        self.atlas_choice.setToolTip(
            "Selecionado automaticamente pelo índice de textura da ArtMesh.")
        first.addWidget(self.atlas_choice, 2)
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
        self.flip_v = QCheckBox("Inverter V (se atlas espelhado)")
        self.flip_v.setToolTip(
            "Se aparecer o trecho errado da textura, troque a orientação V.")
        self.flip_v.setChecked(True)
        tools.addWidget(self.flip_v)
        self.fit_button = QPushButton("Enquadrar")
        tools.addWidget(self.fit_button)
        tools.addStretch(1)
        self.external_button = QPushButton("Exportar peça PNG")
        self.import_button = QPushButton("Importar peça editada")
        tools.addWidget(self.external_button)
        tools.addWidget(self.import_button)
        layout.addLayout(tools)

        self.canvas = AtlasCanvas()
        self.canvas.stroke_created.connect(self._add_stroke)
        layout.addWidget(self.canvas, 1)

        actions = QHBoxLayout()
        self.state = QLabel("")
        actions.addWidget(self.state, 1)
        undo = QPushButton("Desfazer nesta peça")
        undo.clicked.connect(self._undo)
        actions.addWidget(undo)
        clear = QPushButton("Restaurar peça")
        clear.clicked.connect(self._restore)
        actions.addWidget(clear)
        remove = QPushButton("Apagar peça inteira")
        remove.setToolTip(
            "Apaga só os pixels cobertos pelos triângulos UV dessa ArtMesh, "
            "sem excluir nem modificar a geometria no MOC3.")
        remove.clicked.connect(self._erase_selected)
        actions.addWidget(remove)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        save = QPushButton("Salvar mod e abrir")
        save.clicked.connect(self._save_mod)
        actions.addWidget(save)
        layout.addLayout(actions)

        self.drawable_choice.currentIndexChanged.connect(self._mesh_changed)
        self.flip_v.toggled.connect(self._mesh_changed)
        self.tool_choice.currentIndexChanged.connect(self._sync_tool)
        self.size_choice.valueChanged.connect(self._sync_tool)
        self.fit_button.clicked.connect(self.canvas.fit_to_image)
        self.external_button.clicked.connect(self._export_png)
        self.import_button.clicked.connect(self._import_png)
        self._sync_tool()
        self._mesh_changed()

    def _selected(self):
        key = self.drawable_choice.currentData()
        return self.meshes[str(key)]

    def _index(self):
        return self._selected().texture_index

    def _original(self, index):
        if index not in self._originals:
            image = QImage(str(self.paths[index]))
            if image.isNull():
                raise ValueError(f"Não foi possível abrir o atlas {self.paths[index]}")
            self._originals[index] = image.convertToFormat(
                QImage.Format.Format_ARGB32)
        return self._originals[index]

    def _image(self, index):
        result = self._original(index)
        for mesh_id, kind, value, flipped in self._history:
            mesh = self.meshes[mesh_id]
            if mesh.texture_index != index:
                continue
            if kind == "stroke":
                result = apply_mesh_stroke(result, mesh, value, flipped)
            elif kind == "patch":
                result = apply_mesh_patch(result, mesh, value, flipped)
        return result

    def _mesh_changed(self, *_):
        if not self.meshes:
            return
        mesh = self._selected()
        signals = self.atlas_choice.blockSignals(True)
        self.atlas_choice.setCurrentIndex(mesh.texture_index)
        self.atlas_choice.blockSignals(signals)
        self.canvas._zoom_changed = False
        self._render()

    def _render(self, *_):
        try:
            mesh = self._selected()
            image = self._image(mesh.texture_index)
            cutout, rect = isolated_mesh(image, mesh, self.flip_v.isChecked())
            self._preview_crop = rect
            self.canvas.set_image(cutout)
            n = sum(1 for m, *_ in self._history if m == mesh.mesh_id)
            self.state.setText(
                f"{mesh.mesh_id}: {len(mesh.triangles)} triângulos · "
                f"recorte {cutout.width()}×{cutout.height()} · "
                f"{n} edição(ões) · atlas {mesh.texture_index}")
        except (ValueError, OSError, IndexError, KeyError) as exc:
            QMessageBox.warning(self, "Erro ao isolar a ArtMesh", str(exc))

    def _sync_tool(self, *_):
        self.canvas.tool = self.tool_choice.currentData()
        self.canvas.size = self.size_choice.value()

    def _add_stroke(self, stroke):
        mesh = self._selected()
        self._history.append((mesh.mesh_id, "stroke", stroke,
                              self.flip_v.isChecked()))
        self._render()

    def _undo(self):
        key = self._selected().mesh_id
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i][0] == key:
                self._history.pop(i)
                self._render()
                return

    def _restore(self):
        key = self._selected().mesh_id
        self._history = [op for op in self._history if op[0] != key]
        self._render()

    def _erase_selected(self):
        mesh = self._selected()
        rect = self._preview_crop
        if rect is None:
            return
        self._history.append((
            mesh.mesh_id, "stroke",
            Stroke("rectangle", ((0, 0), (rect.width(), rect.height()))),
            self.flip_v.isChecked(),
        ))
        self._render()

    def _export_png(self):
        mesh = self._selected()
        name, _ = QFileDialog.getSaveFileName(
            self, "Exportar ArtMesh isolada",
            str(self.manifest.parent / f"{mesh.mesh_id}_isolada.png"),
            "PNG (*.png)")
        if name:
            image, _ = isolated_mesh(
                self._image(mesh.texture_index), mesh, self.flip_v.isChecked())
            if not image.save(name, "PNG"):
                QMessageBox.warning(self, "Erro", "Não consegui salvar o PNG.")

    def _import_png(self):
        mesh = self._selected()
        name, _ = QFileDialog.getOpenFileName(
            self, "Importar ArtMesh isolada editada",
            str(self.manifest.parent), "PNG (*.png)")
        if not name:
            return
        image = QImage(name)
        source = self._original(mesh.texture_index)
        crop = mesh.crop_bounds(
            source.width(), source.height(), self.flip_v.isChecked())
        if image.isNull() or image.size() != crop.size():
            QMessageBox.warning(
                self, "Tamanho incompatível",
                f"O PNG isolado precisa ter {crop.width()} × "
                f"{crop.height()} pixels.")
            return
        self._history.append((
            mesh.mesh_id, "patch",
            image.convertToFormat(QImage.Format.Format_ARGB32),
            self.flip_v.isChecked(),
        ))
        self._render()

    def _save_mod(self):
        indices = sorted({
            self.meshes[key].texture_index for key, *_ in self._history
        })
        if not indices:
            QMessageBox.information(
                self, "Sem alterações",
                "Apaga um trecho ou importa o PNG isolado primeiro.")
            return
        try:
            changed = {i: self._image(i) for i in indices}
            self.created_manifest = clone_mod_bundle(self.manifest, changed)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Falha ao salvar mod", str(exc))
            return
        self.accept()
