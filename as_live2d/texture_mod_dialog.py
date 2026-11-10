"""Optional ArtMesh-oriented atlas retouch dialog.

Reads the selected ArtMesh's actual UV triangles from the compiled .moc3
with py-moc3. Displays ONLY the selected piece instead of the entire atlas.
All erase/replacement operations are clipped to those triangles; a separate
copy is saved under mod/ without touching source files.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QThreadPool
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
from .artmesh_preview import PreviewBuilder
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
        self.edit_enabled = False
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
        if (self.edit_enabled and event.button() == Qt.MouseButton.LeftButton and
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

    def __init__(self, manifest: Path, drawable_ids=(), parent=None,
                 initial_mesh_id: str | None = None,
                 visibility_overrides: dict[str, bool] | None = None):
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
        self._visibility_overrides = dict(visibility_overrides or {})
        self._preview_crop = None
        # Small previews are built in a background thread and never re-rendered
        # when navigating the selector. Full-resolution work requires "Editar".
        self._previews: dict[str, QImage] = {}
        self._preview_workers: dict[int, PreviewBuilder] = {}
        self._preview_generation = 0
        self._building_previews = False
        self._edit_mode = False
        self._atlas_cache: dict[int, QImage] = {}
        self.created_manifest: Path | None = None

        self.setWindowTitle("Live2D · Editar ArtMesh isolada → mod")
        self.resize(1120, 820)
        self.setMinimumSize(650, 480)
        # All inputs and QComboBox popup lists inherit the global dark palette.
        # The old local stylesheet made mesh dropdown items white-on-white.
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
        if initial_mesh_id is not None:
            index = self.drawable_choice.findData(initial_mesh_id)
            if index >= 0:
                self.drawable_choice.setCurrentIndex(index)
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

        preview_tools = QHBoxLayout()
        self.build_button = QPushButton("Construir previews")
        self.build_button.setToolTip(
            "Gera miniaturas de todas as ArtMeshes em segundo plano. "
            "A troca de seleção depois usa apenas imagens em cache.")
        preview_tools.addWidget(self.build_button)
        self.edit_button = QPushButton("Editar peça selecionada")
        self.edit_button.setToolTip(
            "Abre o recorte original em resolução completa e habilita "
            "as ferramentas de edição apenas para esta peça.")
        preview_tools.addWidget(self.edit_button)
        self.preview_status = QLabel(
            "Clique em Construir previews para carregar as miniaturas.")
        preview_tools.addWidget(self.preview_status, 1)
        layout.addLayout(preview_tools)

        if self._visibility_overrides:
            note = QLabel(
                f"{len(self._visibility_overrides)} ArtMesh(es) com mudança "
                "de visibilidade pendente serão incluídas neste mod.")
            note.setWordWrap(True)
            layout.addWidget(note)

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
            "Desmarcado por padrão: usa a orientação original do atlas. "
            "Marque só se o modelo realmente usar UV invertida.")
        self.flip_v.setChecked(False)
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
        self._edit_controls = (self.tool_choice, self.size_choice,
                               self.external_button, self.import_button,
                               undo, clear, remove)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        save = QPushButton("Salvar mod e abrir")
        save.clicked.connect(self._save_mod)
        self.save_button = save
        actions.addWidget(save)
        layout.addLayout(actions)

        self.drawable_choice.currentIndexChanged.connect(self._mesh_changed)
        self.flip_v.toggled.connect(self._flip_changed)
        self.tool_choice.currentIndexChanged.connect(self._sync_tool)
        self.size_choice.valueChanged.connect(self._sync_tool)
        self.fit_button.clicked.connect(self.canvas.fit_to_image)
        self.external_button.clicked.connect(self._export_png)
        self.import_button.clicked.connect(self._import_png)
        self.build_button.clicked.connect(self._build_previews)
        self.edit_button.clicked.connect(self._enter_edit)
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
        # Reuse the composited atlas across brush strokes and mesh switches.
        # Undo/restore invalidate only the affected texture page.
        if index in self._atlas_cache:
            return self._atlas_cache[index]
        result = self._original(index)
        for mesh_id, kind, value, flipped in self._history:
            mesh = self.meshes[mesh_id]
            if mesh.texture_index != index:
                continue
            if kind == "stroke":
                result = apply_mesh_stroke(result, mesh, value, flipped)
            elif kind == "patch":
                result = apply_mesh_patch(result, mesh, value, flipped)
        self._atlas_cache[index] = result
        return result

    def _set_edit_mode(self, enabled: bool):
        self._edit_mode = enabled
        self.canvas.edit_enabled = enabled
        for widget in self._edit_controls:
            widget.setEnabled(enabled)
        self.edit_button.setEnabled(
            not enabled and str(self.drawable_choice.currentData()) in self._previews)
        self.edit_button.setText(
            "Editando esta peça" if enabled else "Editar peça selecionada")

    def _show_preview(self):
        mesh = self._selected()
        self._preview_crop = None
        image = self._previews.get(mesh.mesh_id)
        self.canvas.set_image(image if image is not None else QImage())
        self._set_edit_mode(False)
        if image is None:
            self.state.setText(
                f"{mesh.mesh_id}: prévia ainda não gerada. "
                "Clique em Construir previews.")
        else:
            self.state.setText(
                f"{mesh.mesh_id}: prévia {image.width()}×{image.height()} · "
                f"{len(mesh.triangles)} triângulos · clique em Editar "
                "para trabalhar na resolução original.")

    def _mesh_changed(self, *_):
        if not self.meshes:
            return
        mesh = self._selected()
        signals = self.atlas_choice.blockSignals(True)
        self.atlas_choice.setCurrentIndex(mesh.texture_index)
        self.atlas_choice.blockSignals(signals)
        self.canvas._zoom_changed = False
        self._show_preview()

    def _cancel_previews(self):
        for worker in self._preview_workers.values():
            worker.cancel()

    def _build_previews(self):
        self._cancel_previews()
        self._preview_generation += 1
        generation = self._preview_generation
        self._previews.clear()
        self._building_previews = True
        self.build_button.setEnabled(False)
        self.build_button.setText("Construindo...")
        self.preview_status.setText(
            f"Preparando 0/{len(self.meshes)} miniaturas...")
        self._show_preview()
        worker = PreviewBuilder(
            self.paths, tuple(self.meshes.values()),
            self.flip_v.isChecked(), generation)
        self._preview_workers[generation] = worker
        worker.signals.image_ready.connect(self._preview_ready)
        worker.signals.failed.connect(self._preview_failed)
        worker.signals.finished.connect(self._preview_finished)
        QThreadPool.globalInstance().start(worker)

    def _preview_ready(self, generation, mesh_id, image, done, total):
        if generation != self._preview_generation:
            return
        self._previews[mesh_id] = image
        self.preview_status.setText(f"Construindo previews: {done}/{total}")
        if not self._edit_mode and mesh_id == str(self.drawable_choice.currentData()):
            self._show_preview()

    def _preview_failed(self, generation, message):
        if generation == self._preview_generation:
            self.preview_status.setText(f"Erro ao gerar miniaturas: {message}")

    def _preview_finished(self, generation, cancelled):
        self._preview_workers.pop(generation, None)
        if generation != self._preview_generation:
            return
        self._building_previews = False
        self.build_button.setEnabled(True)
        self.build_button.setText("Reconstruir previews")
        if not cancelled:
            self.preview_status.setText(
                f"{len(self._previews)}/{len(self.meshes)} previews prontos. "
                "As miniaturas mostram as texturas originais.")
        elif not self.preview_status.text().startswith("Erro"):
            self.preview_status.setText("Construção interrompida.")

    def _flip_changed(self, *_):
        # The V orientation changes the UV crop, so old previews are invalid.
        self._cancel_previews()
        self._preview_generation += 1
        self._previews.clear()
        self._building_previews = False
        self.build_button.setEnabled(True)
        self.build_button.setText("Construir previews")
        self.preview_status.setText(
            "Orientação V alterada. Reconstrua as miniaturas.")
        self._mesh_changed()

    def _enter_edit(self):
        if str(self.drawable_choice.currentData()) not in self._previews:
            return
        self.canvas._zoom_changed = False
        self._set_edit_mode(True)
        self._render()

    def _render(self, *_):
        if not self._edit_mode:
            return
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

    def _record_edit(self, mesh, kind, value):
        flipped = self.flip_v.isChecked()
        self._history.append((mesh.mesh_id, kind, value, flipped))
        page = mesh.texture_index
        if page in self._atlas_cache:
            if kind == "stroke":
                self._atlas_cache[page] = apply_mesh_stroke(
                    self._atlas_cache[page], mesh, value, flipped)
            else:
                self._atlas_cache[page] = apply_mesh_patch(
                    self._atlas_cache[page], mesh, value, flipped)
        self._render()

    def _add_stroke(self, stroke):
        if self._edit_mode:
            self._record_edit(self._selected(), "stroke", stroke)

    def _undo(self):
        key = self._selected().mesh_id
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i][0] == key:
                self._history.pop(i)
                self._atlas_cache.pop(self.meshes[key].texture_index, None)
                self._render()
                return

    def _restore(self):
        key = self._selected().mesh_id
        self._history = [op for op in self._history if op[0] != key]
        self._atlas_cache.pop(self.meshes[key].texture_index, None)
        self._render()

    def _erase_selected(self):
        if not self._edit_mode:
            return
        mesh = self._selected()
        rect = self._preview_crop
        if rect is None:
            return
        self._record_edit(
            mesh, "stroke",
            Stroke("rectangle", ((0, 0), (rect.width(), rect.height()))))

    def _export_png(self):
        if not self._edit_mode:
            return
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
        if not self._edit_mode:
            return
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
        self._record_edit(
            mesh, "patch",
            image.convertToFormat(QImage.Format.Format_ARGB32))

    def _save_mod(self):
        indices = sorted({
            self.meshes[key].texture_index for key, *_ in self._history
        })
        if not indices and not self._visibility_overrides:
            QMessageBox.information(
                self, "Sem alterações",
                "Edite uma textura ou escolha SHOW/HIDDEN na aba Meshes.")
            return
        try:
            changed = {i: self._image(i) for i in indices}
            self.created_manifest = clone_mod_bundle(
                self.manifest, changed,
                visibility_overrides=self._visibility_overrides)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Falha ao salvar mod", str(exc))
            return
        self.accept()

    def done(self, result):
        # Never wait for background rendering when the dialog is dismissed.
        self._cancel_previews()
        super().done(result)
