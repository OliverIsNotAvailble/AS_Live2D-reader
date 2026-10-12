"""AS Live2D Reader main window and non-blocking export controller."""
from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QSplitter, QScrollArea, QVBoxLayout,
    QHBoxLayout, QFormLayout, QGroupBox, QLabel, QPushButton, QFileDialog,
    QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget,
    QListWidgetItem, QTreeWidget, QTreeWidgetItem, QTabWidget, QMessageBox,
    QColorDialog, QProgressBar, QApplication, QPlainTextEdit,
)
from .model import Motion, ModelCatalog, inspect_model, load_profile, save_profile
from .viewer import Live2DViewer
from .encoder import EncodeWorker, find_ffmpeg


def safe_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return (name[:90] or "motion")


class FittedStage(QWidget):
    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        self.aspect_width, self.aspect_height = 1280, 720
        self.frame = QFrame(self)
        self.frame.setObjectName("exportFrame")
        self.frame.setStyleSheet(
            "QFrame#exportFrame {border: 2px solid #E65A63; background: #171b23;}")
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        layout.addWidget(viewer)

    def set_aspect(self, width, height):
        self.aspect_width = max(1, width)
        self.aspect_height = max(1, height)
        self.fit()

    def fit(self):
        available_w = max(1, self.width() - 24)
        available_h = max(1, self.height() - 24)
        aspect = self.aspect_width / self.aspect_height
        width = min(available_w, max(1, int(available_h * aspect)))
        height = min(available_h, max(1, int(width / aspect)))
        self.frame.setGeometry((self.width() - width - 4) // 2,
                               (self.height() - height - 4) // 2,
                               width + 4, height + 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()


class ReaderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AS Live2D Reader — v0.1.3")
        self.resize(1580, 900)
        self.setMinimumSize(950, 630)
        self.catalog: ModelCatalog | None = None
        self.current_path: Path | None = None
        self._busy = False
        self._closing = False
        self._worker: EncodeWorker | None = None
        self._export_jobs: list[Motion] = []
        self._export_position = 0
        self._export_frame = 0
        self._export_frames_total = 0
        self._current_motion: Motion | None = None
        self._waiting_for_encode = False
        self._output_path: Path | None = None
        self._formats: tuple[str, ...] = ()
        self._fps = 30.0
        self._ffmpeg = None
        self._frame_background = "transparent"
        self._frame_image = ""
        self._frame_color = (35, 39, 42)
        self._color = QColor(35, 39, 42)
        self._background_file = ""
        self._saved_part_overrides = {}
        self._background_timer = QTimer(self)
        self._background_timer.setSingleShot(True)
        self._background_timer.timeout.connect(self._apply_background_preview)
        self._prefs = QSettings("AS_Reader", "Live2D_Reader")

        self.viewer = Live2DViewer()
        self.viewer.model_loaded.connect(self._model_loaded)
        self.viewer.model_failed.connect(self._model_failed)
        self.viewer.camera_changed.connect(self._sync_camera)
        self.viewer.performance.connect(lambda fps: self.fps_label.setText(
            f"Preview  {fps:.0f} FPS"))

        self._build_ui()
        self._build_menu()
        self._set_enabled(False)
        self._log("AS Live2D Reader v0.1.0 started. Open a .model3.json to begin.")

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        action = QAction("Open model3.json…", self)
        action.setShortcut("Ctrl+O")
        action.triggered.connect(self.open_model)
        file_menu.addAction(action)
        save_action = QAction("Save model profile", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_current_profile)
        file_menu.addAction(save_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        view_menu = self.menuBar().addMenu("&View")
        reset = QAction("Reset camera", self)
        reset.setShortcut("Ctrl+0")
        reset.triggered.connect(self.reset_camera)
        view_menu.addAction(reset)

    @staticmethod
    def _spin(value, minimum, maximum, step=1):
        s = QSpinBox()
        s.setRange(minimum, maximum)
        s.setSingleStep(step)
        s.setValue(value)
        return s

    @staticmethod
    def _decimal(value, minimum, maximum, step=0.1, decimals=3):
        s = QDoubleSpinBox()
        s.setDecimals(decimals)
        s.setRange(minimum, maximum)
        s.setSingleStep(step)
        s.setValue(value)
        return s

    def _build_ui(self):
        root = QWidget()
        vertical = QVBoxLayout(root)
        vertical.setContentsMargins(8, 8, 8, 8)
        vertical.setSpacing(7)

        bar = QHBoxLayout()
        open_button = QPushButton("Open model…")
        self.open_button = open_button
        open_button.clicked.connect(self.open_model)
        bar.addWidget(open_button)
        self.model_title = QLabel("No model loaded")
        self.model_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        bar.addWidget(self.model_title, 1)
        self.play_button = QPushButton("Play motion")
        self.play_button.clicked.connect(self.play_selected)
        bar.addWidget(self.play_button)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_pause)
        bar.addWidget(self.pause_button)
        self.loop_box = QCheckBox("Loop")
        self.loop_box.setChecked(True)
        bar.addWidget(self.loop_box)
        self.fps_label = QLabel("Preview  — FPS")
        bar.addWidget(self.fps_label)
        vertical.addLayout(bar)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        vertical.addWidget(self.split, 1)
        sidebar = QScrollArea()
        self.sidebar = sidebar
        sidebar.setWidgetResizable(True)
        sidebar.setMinimumWidth(295)
        sidebar.setMaximumWidth(520)
        sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        config = QWidget()
        controls = QVBoxLayout(config)
        controls.setContentsMargins(9, 9, 9, 9)
        controls.setSpacing(9)
        sidebar.setWidget(config)
        self.split.addWidget(sidebar)

        model_box = QGroupBox("Model & output")
        model_form = QFormLayout(model_box)
        self.model_path_label = QLabel("—")
        self.model_path_label.setWordWrap(True)
        model_form.addRow("Current", self.model_path_label)
        self.output = QLineEdit()
        output_button = QPushButton("…")
        output_button.setFixedWidth(36)
        output_button.clicked.connect(self.pick_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output)
        output_row.addWidget(output_button)
        model_form.addRow("Output", output_row)
        self.profile_button = QPushButton("Save profile")
        self.profile_button.clicked.connect(self.save_current_profile)
        model_form.addRow(self.profile_button)
        controls.addWidget(model_box)

        camera = QGroupBox("Camera & frame")
        camera_form = QFormLayout(camera)
        self.width = self._spin(1280, 64, 4096, 2)
        self.height = self._spin(720, 64, 4096, 2)
        self.scale = self._decimal(1.0, 0.01, 15, 0.05)
        self.x = self._decimal(0.0, -10, 10, 0.05)
        self.y = self._decimal(0.0, -10, 10, 0.05)
        camera_form.addRow("Width", self.width)
        camera_form.addRow("Height", self.height)
        camera_form.addRow("Zoom", self.scale)
        camera_form.addRow("X", self.x)
        camera_form.addRow("Y", self.y)
        self.camera_box = QCheckBox("Drag to pan / wheel to zoom")
        self.camera_box.setChecked(True)
        self.camera_box.toggled.connect(lambda b: setattr(self.viewer, "drag_enabled", b))
        camera_form.addRow(self.camera_box)
        reset = QPushButton("Reset camera")
        reset.clicked.connect(self.reset_camera)
        camera_form.addRow(reset)
        controls.addWidget(camera)

        render = QGroupBox("Video / image export")
        render_form = QFormLayout(render)
        self.format = QComboBox()
        self.format.addItem("MP4", ("mp4",))
        self.format.addItem("WebP (animated)", ("webp",))
        self.format.addItem("PNG frames", ("png",))
        self.format.addItem("MP4 + WebP", ("mp4", "webp"))
        render_form.addRow("Format", self.format)
        self.fps = self._decimal(0.0, 0, 120, 1, 1)
        self.fps.setSpecialValueText("Motion FPS")
        render_form.addRow("FPS", self.fps)
        self.background = QComboBox()
        self.background.addItem("Transparent (WebP/PNG)", "transparent")
        self.background.addItem("Solid color", "color")
        self.background.addItem("Background image", "image")
        render_form.addRow("Background", self.background)
        self.background.currentIndexChanged.connect(self._schedule_background_preview)
        self.color_button = QPushButton("Choose background color")
        self.color_button.clicked.connect(self.pick_color)
        render_form.addRow(self.color_button)
        self.image_button = QPushButton("Choose background image…")
        self.image_button.clicked.connect(self.pick_background)
        render_form.addRow(self.image_button)
        self.reload_bg_button = QPushButton("Reload background image")
        self.reload_bg_button.setToolTip(
            "Update the preview after editing the background image externally")
        self.reload_bg_button.clicked.connect(self.reload_background)
        render_form.addRow(self.reload_bg_button)
        self.quality = self._spin(95, 1, 100)
        render_form.addRow("WebP quality", self.quality)
        controls.addWidget(render)

        effects = QGroupBox("Effects")
        effects_layout = QVBoxLayout(effects)
        self.blink = QCheckBox("Automatic blink")
        self.blink.setChecked(True)
        self.breath = QCheckBox("Automatic breath")
        self.physics = QCheckBox("Physics")
        self.physics.setChecked(True)
        for widget in (self.blink, self.breath, self.physics):
            effects_layout.addWidget(widget)
        self.blink.toggled.connect(self._set_effects)
        self.breath.toggled.connect(self._set_effects)
        self.physics.toggled.connect(self._set_effects)
        controls.addWidget(effects)

        tabs = QTabWidget()
        self.motion_list = QListWidget()
        self.motion_list.currentItemChanged.connect(lambda *_: self._motion_highlighted())
        self.motion_filter = QLineEdit()
        self.motion_filter.setPlaceholderText("Filter motions…")
        self.motion_filter.textChanged.connect(self._filter_motions)
        motion_tab = QWidget()
        motion_layout = QVBoxLayout(motion_tab)
        motion_layout.setContentsMargins(4, 4, 4, 4)
        motion_layout.addWidget(self.motion_filter)
        motion_layout.addWidget(self.motion_list)
        selects = QHBoxLayout()
        select_all = QPushButton("All")
        select_all.clicked.connect(lambda: self.check_motions(True))
        select_none = QPushButton("None")
        select_none.clicked.connect(lambda: self.check_motions(False))
        selects.addWidget(select_all)
        selects.addWidget(select_none)
        motion_layout.addLayout(selects)
        self.files_tree = QTreeWidget()
        self.files_tree.setHeaderLabels(["Type", "File / status"])
        self.files_tree.setRootIsDecorated(False)
        self.expressions = QListWidget()
        parts_tab = QWidget()
        parts_layout = QVBoxLayout(parts_tab)
        parts_layout.setContentsMargins(4, 4, 4, 4)
        parts_tip = QLabel("Part opacity: ◩ Auto (motion) · ☑ Show · ☐ Hide")
        parts_tip.setWordWrap(True)
        parts_layout.addWidget(parts_tip)
        self.parts_filter = QLineEdit()
        self.parts_filter.setPlaceholderText("Find head, arm, clothes…")
        self.parts_filter.textChanged.connect(self._filter_parts)
        parts_layout.addWidget(self.parts_filter)
        self.parts_tree = QTreeWidget()
        self.parts_tree.setRootIsDecorated(False)
        self.parts_tree.setHeaderLabels(["Cubism Part ID", "Visibility"])
        self.parts_tree.itemChanged.connect(self._part_visibility_changed)
        parts_layout.addWidget(self.parts_tree)
        reset_parts = QPushButton("Reset all to Auto (motion)")
        reset_parts.clicked.connect(self._reset_part_overrides)
        parts_layout.addWidget(reset_parts)
        tabs.addTab(motion_tab, "Motions")
        tabs.addTab(parts_tab, "Parts")
        tabs.addTab(self.expressions, "Expressions")
        tabs.addTab(self.files_tree, "Files")
        tabs.setMinimumHeight(240)
        controls.addWidget(tabs, 1)
        controls.addStretch()
        self.stage = FittedStage(self.viewer)
        self.split.addWidget(self.stage)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([370, 1200])

        status_row = QHBoxLayout()
        self.status = QLabel("Open a model to begin.")
        status_row.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(250)
        status_row.addWidget(self.progress)
        self.export_button = QPushButton("Export selected")
        self.export_button.clicked.connect(self.start_export)
        status_row.addWidget(self.export_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_export)
        self.cancel_button.setEnabled(False)
        status_row.addWidget(self.cancel_button)
        vertical.addLayout(status_row)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumHeight(92)
        vertical.addWidget(self.logs)
        self.setCentralWidget(root)

        for field in (self.scale, self.x, self.y):
            field.valueChanged.connect(self._camera_fields_changed)
        self.width.valueChanged.connect(self._fit_frame)
        self.height.valueChanged.connect(self._fit_frame)
        QTimer.singleShot(0, self._fit_frame)

    def _log(self, message: str):
        self.logs.appendPlainText(message)
        self.status.setText(message[:160])
        print("[AS Live2D]", message)

    def _set_enabled(self, ready: bool):
        for widget in (self.play_button, self.pause_button, self.profile_button,
                       self.export_button):
            widget.setEnabled(ready and not self._busy)
        self.cancel_button.setEnabled(self._busy)
        self.open_button.setEnabled(not self._busy)
        self.sidebar.setEnabled(not self._busy)
        self.loop_box.setEnabled(not self._busy)
        self.viewer.drag_enabled = (not self._busy and self.camera_box.isChecked())

    def _fit_frame(self, *_):
        self.stage.set_aspect(self.width.value(), self.height.value())
        self._schedule_background_preview()

    def _schedule_background_preview(self, *_):
        if not self._busy:
            self._background_timer.start(90)

    def _apply_background_preview(self, *, force_reload=False):
        if self._busy:
            return
        mode = self.background.currentData()
        color = (self._color.red(), self._color.green(), self._color.blue())
        try:
            self.viewer.set_background(
                mode, color, self._background_file,
                self.width.value(), self.height.value(),
                force_reload=force_reload)
        except Exception as exc:
            # Never let a corrupt/missing image break Live2D animation.
            self.viewer.set_background(
                "transparent", color, "",
                self.width.value(), self.height.value())
            self._log(f"Background preview unavailable: {exc}")

    def reload_background(self):
        if self._busy:
            return
        self._background_timer.stop()
        self._apply_background_preview(force_reload=True)
        if self.background.currentData() == "image" and self._background_file:
            self._log(f"Background preview reloaded: {Path(self._background_file).name}")

    def _sync_camera(self, scale, x, y):
        for field, val in ((self.scale, scale), (self.x, x), (self.y, y)):
            blocked = field.blockSignals(True)
            field.setValue(val)
            field.blockSignals(blocked)

    def _camera_fields_changed(self, *_):
        self.viewer.set_camera(self.scale.value(), self.x.value(), self.y.value())

    def reset_camera(self):
        self.viewer.set_camera(1.0, 0.0, 0.0)

    def _set_effects(self, *_):
        self.viewer.auto_blink = self.blink.isChecked()
        self.viewer.auto_breath = self.breath.isChecked()
        self.viewer.auto_physics = self.physics.isChecked()
        if self.viewer.model is not None:
            self.viewer.model.SetAutoBlinkEnable(self.viewer.auto_blink)
            self.viewer.model.SetAutoBreathEnable(self.viewer.auto_breath)

    def pick_color(self):
        choice = QColorDialog.getColor(self._color, self, "Background color")
        if choice.isValid():
            self._color = choice
            self.color_button.setText(choice.name())
            self._schedule_background_preview()

    def pick_background(self):
        start = str(self.current_path.parent if self.current_path else Path.home())
        name, _ = QFileDialog.getOpenFileName(
            self, "Background image", start, "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if name:
            self._background_file = name
            self.image_button.setText(Path(name).name)
            self.background.setCurrentIndex(self.background.findData("image"))
            self.reload_background()

    def pick_output(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Export folder", self.output.text() or str(Path.home()))
        if folder:
            self.output.setText(folder)

    def open_model(self):
        if self._busy:
            return
        previous = self._prefs.value("last_directory", str(Path.home()))
        name, _ = QFileDialog.getOpenFileName(
            self, "Open Live2D .model3.json", str(previous),
            "Live2D model (*.model3.json);;JSON (*.json)")
        if name:
            self.open_path(Path(name))

    def open_path(self, path: Path):
        if self._busy:
            return
        try:
            candidate = inspect_model(path)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot read model3.json", str(exc))
            return
        if not candidate.can_load:
            QMessageBox.warning(self, "Missing model files",
                "Cannot initialize this model.\n" + "\n".join(candidate.missing[:12]))
            return

        self.catalog = candidate
        self.current_path = candidate.path
        self._prefs.setValue("last_directory", str(candidate.path.parent))
        self.model_title.setText(candidate.name)
        self.model_path_label.setText(candidate.path.name)
        self.model_path_label.setToolTip(str(candidate.path))
        self.output.setText(str(candidate.path.parent / "ext"))
        self._fill_motions()
        self._fill_inspector()
        self._restore_profile()
        self._set_effects()
        self._set_enabled(False)
        self._log(f"Loading {candidate.path.name}…")
        self.viewer.load_model(candidate.path)

    def _fill_motions(self):
        self.motion_list.clear()
        for motion in self.catalog.motions:
            item = QListWidgetItem(motion.label)
            item.setData(Qt.ItemDataRole.UserRole, motion)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(str(motion.path))
            self.motion_list.addItem(item)
        if self.motion_list.count():
            self.motion_list.setCurrentRow(0)

    def _fill_parts(self):
        self.parts_tree.blockSignals(True)
        self.parts_tree.clear()
        current = self.viewer.get_part_overrides()
        for part_id in self.viewer.get_part_ids():
            state = (Qt.CheckState.PartiallyChecked if part_id not in current else
                     Qt.CheckState.Checked if current[part_id] >= 0.5 else
                     Qt.CheckState.Unchecked)
            label = ("Auto" if state == Qt.CheckState.PartiallyChecked else
                     "Shown" if state == Qt.CheckState.Checked else "Hidden")
            item = QTreeWidgetItem([part_id, label])
            item.setData(0, Qt.ItemDataRole.UserRole, part_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserTristate |
                          Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, state)
            item.setToolTip(0, "Click checkbox to cycle: Auto / Show / Hide. "
                            "Manual overrides are saved only in AS Reader profile.")
            self.parts_tree.addTopLevelItem(item)
        self.parts_tree.resizeColumnToContents(0)
        self.parts_tree.blockSignals(False)
        self._filter_parts(self.parts_filter.text())

    def _filter_parts(self, text):
        search = text.strip().lower()
        for i in range(self.parts_tree.topLevelItemCount()):
            row = self.parts_tree.topLevelItem(i)
            row.setHidden(search not in row.text(0).lower())

    def _part_visibility_changed(self, item, column):
        if column != 0 or self._busy:
            return
        state = item.checkState(0)
        override = (None if state == Qt.CheckState.PartiallyChecked else
                    1.0 if state == Qt.CheckState.Checked else 0.0)
        self.viewer.set_part_override(item.data(0, Qt.ItemDataRole.UserRole),
                                      override)
        item.setText(1, "Auto" if override is None else
                        "Shown" if override == 1.0 else "Hidden")

    def _reset_part_overrides(self):
        for i in range(self.parts_tree.topLevelItemCount()):
            row = self.parts_tree.topLevelItem(i)
            row.setCheckState(0, Qt.CheckState.PartiallyChecked)
        self._log("All part visibility overrides reset to motion-controlled.")

    def _fill_inspector(self):
        self.files_tree.clear()
        self.expressions.clear()
        for kind, path, exists in self.catalog.assets:
            item = QTreeWidgetItem([kind, ("OK  " if exists else "MISSING  ") + path.name])
            item.setToolTip(1, str(path))
            if not exists:
                item.setForeground(1, QColor("#ef7676"))
            self.files_tree.addTopLevelItem(item)
        self.files_tree.resizeColumnToContents(0)
        for name, path in self.catalog.expressions:
            self.expressions.addItem(f"{name}  ·  {path.name}")
        if self.catalog.warnings:
            self._log(f"Model references: {len(self.catalog.warnings)} warning(s). Check Files tab.")

    def _restore_profile(self):
        self._saved_part_overrides = {}
        try:
            values = load_profile(self.current_path)
        except Exception as exc:
            self._log(f"Cannot load saved profile: {exc}")
            return
        for key, widget in (("width", self.width), ("height", self.height),
                            ("scale", self.scale), ("x", self.x), ("y", self.y),
                            ("fps", self.fps), ("webp_quality", self.quality)):
            if key in values:
                widget.setValue(values[key])
        fmt = tuple(values.get("formats", ["mp4"]))
        for n in range(self.format.count()):
            if self.format.itemData(n) == fmt:
                self.format.setCurrentIndex(n)
                break
        mode = values.get("background", "transparent")
        i = self.background.findData(mode)
        if i >= 0:
            self.background.setCurrentIndex(i)
        self._background_file = str(values.get("background_file", ""))
        self.image_button.setText(Path(self._background_file).name
                                  if self._background_file else "Choose background image…")
        col = values.get("color", [35, 39, 42])
        if isinstance(col, list) and len(col) == 3:
            self._color = QColor(*(int(x) for x in col))
        checked = {tuple(x) for x in values.get("selected_motions", [])}
        if checked:
            for n in range(self.motion_list.count()):
                item = self.motion_list.item(n)
                motion = item.data(Qt.ItemDataRole.UserRole)
                item.setCheckState(Qt.CheckState.Checked if
                                   (motion.group, motion.index) in checked else
                                   Qt.CheckState.Unchecked)
        self._saved_part_overrides = {
            str(k): float(v)
            for k, v in (values.get("part_overrides") or {}).items()
            if v in (0, 0.0, 1, 1.0)
        }
        self.viewer.set_camera(self.scale.value(), self.x.value(), self.y.value())
        self._schedule_background_preview()

    def save_current_profile(self):
        if self.current_path is None:
            return
        checked = [[m.group, m.index] for m in self.checked_motions()]
        values = dict(
            width=self.width.value(), height=self.height.value(),
            scale=self.scale.value(), x=self.x.value(), y=self.y.value(),
            fps=self.fps.value(), formats=list(self.format.currentData()),
            background=self.background.currentData(),
            background_file=self._background_file,
            color=[self._color.red(), self._color.green(), self._color.blue()],
            webp_quality=self.quality.value(), selected_motions=checked,
            part_overrides=self.viewer.get_part_overrides())
        try:
            target = save_profile(self.current_path, values)
            self._log(f"Profile saved: {target.name}")
        except Exception as exc:
            QMessageBox.warning(self, "Could not save profile", str(exc))

    def _model_loaded(self, name):
        self._log(f"Loaded {name} — {len(self.catalog.motions)} motion(s)")
        for part_id, opacity in self._saved_part_overrides.items():
            self.viewer.set_part_override(part_id, opacity)
        self._fill_parts()
        self._set_enabled(True)
        self._set_effects()
        if self.motion_list.count():
            QTimer.singleShot(0, self.play_selected)

    def _model_failed(self, error):
        self._set_enabled(False)
        self._log(f"Model load failed: {error}")
        QMessageBox.critical(self, "Cannot open Live2D model", error)

    def _motion_highlighted(self):
        if self.motion_list.currentItem() is not None:
            item = self.motion_list.currentItem()
            m = item.data(Qt.ItemDataRole.UserRole)
            self.status.setText(f"Selected: {m.label}")

    def _filter_motions(self, text):
        target = text.strip().lower()
        for index in range(self.motion_list.count()):
            item = self.motion_list.item(index)
            item.setHidden(target not in item.text().lower())

    def check_motions(self, checked):
        for n in range(self.motion_list.count()):
            self.motion_list.item(n).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def checked_motions(self) -> list[Motion]:
        return [self.motion_list.item(n).data(Qt.ItemDataRole.UserRole)
                for n in range(self.motion_list.count())
                if self.motion_list.item(n).checkState() == Qt.CheckState.Checked]

    def play_selected(self):
        if self._busy or self.viewer.model is None:
            return
        item = self.motion_list.currentItem()
        if item is None:
            return
        motion = item.data(Qt.ItemDataRole.UserRole)
        try:
            self.viewer.play_motion(motion.group, motion.index,
                                    repeat=self.loop_box.isChecked(),
                                    motion_path=motion.path, duration=motion.duration)
            self.pause_button.setText("Pause")
            self._log(f"Preview: {motion.group} [{motion.index}]")
        except Exception as exc:
            QMessageBox.warning(self, "Cannot play motion", str(exc))

    def toggle_pause(self):
        if self.viewer.model is None or self._busy:
            return
        self.viewer.playing = not self.viewer.playing
        self.viewer._previous_tick = __import__("time").monotonic()
        self.pause_button.setText("Pause" if self.viewer.playing else "Resume")

    def _settings_for_export(self):
        formats = tuple(self.format.currentData())
        if ("mp4" in formats and
                (self.width.value() % 2 != 0 or self.height.value() % 2 != 0)):
            raise ValueError("MP4 H.264 needs even width and height.")
        if self.background.currentData() == "image" and not Path(
                self._background_file).is_file():
            raise ValueError("Choose an existing background image first.")
        path_text = self.output.text().strip()
        if not path_text:
            raise ValueError("Choose an output folder.")
        return formats, Path(path_text).expanduser().resolve()

    def start_export(self):
        if self._busy or self.viewer.model is None:
            return
        jobs = self.checked_motions()
        if not jobs:
            QMessageBox.information(self, "Export", "Select at least one motion.")
            return
        try:
            formats, path = self._settings_for_export()
            self._ffmpeg = find_ffmpeg(Path(__file__).resolve().parents[1]) if any(
                f in formats for f in ("mp4", "webp")) else None
        except Exception as exc:
            QMessageBox.warning(self, "Cannot export", str(exc))
            return
        self._busy = True
        self._export_jobs = jobs
        self._export_position = 0
        self._output_path = path
        self._formats = formats
        self._frame_background = str(self.background.currentData())
        self._frame_image = self._background_file
        self._frame_color = (self._color.red(), self._color.green(), self._color.blue())
        self.viewer.playing = False
        self._set_enabled(True)
        self._log(f"Exporting {len(jobs)} motion(s)…")
        QTimer.singleShot(0, self._next_motion)

    def _next_motion(self):
        if not self._busy or self._closing:
            return
        if self._export_position >= len(self._export_jobs):
            self._busy = False
            self._set_enabled(True)
            self.progress.setValue(self.progress.maximum())
            self._log(f"Export complete: {len(self._export_jobs)} motion(s)")
            return
        motion = self._export_jobs[self._export_position]
        self._current_motion = motion
        self._export_frame = 0
        self._fps = self.fps.value() or motion.fps
        self._export_frames_total = motion.frames(self._fps)
        self._waiting_for_encode = False
        count_in_group = sum(m.group == motion.group for m in self._export_jobs)
        stem = safe_name(motion.group)
        if count_in_group > 1:
            stem += f"_{motion.index:02d}"
        # Different model exports always use the destination chosen by user.
        self.progress.setRange(0, self._export_frames_total)
        self.progress.setValue(0)
        try:
            self.viewer.reset_for_export(
                motion.group, motion.index,
                motion_path=motion.path, duration=motion.duration)
            worker = EncodeWorker(
                ffmpeg=self._ffmpeg, output=self._output_path, stem=stem,
                width=self.width.value(), height=self.height.value(),
                fps=self._fps, formats=self._formats,
                background=self._frame_background, color=self._frame_color,
                image_path=self._frame_image, webp_quality=self.quality.value(),
                parent=self)
            self._worker = worker
            worker.completed.connect(self._motion_encoded)
            worker.error.connect(self._encoding_failed)
            worker.aborted.connect(self._encoding_aborted)
            worker.finished.connect(worker.deleteLater)
            worker.start()
            self._log(f"Exporting {motion.group}[{motion.index}] "
                      f"({self._export_frames_total} frames @ {self._fps:g} FPS)")
            QTimer.singleShot(0, self._capture_next)
        except Exception as exc:
            self._encoding_failed(str(exc))

    def _capture_next(self):
        if not self._busy or self._closing or self._worker is None or self._worker.cancel_requested.is_set():
            return
        if self._waiting_for_encode:
            return
        if self._export_frame >= self._export_frames_total:
            self._waiting_for_encode = True
            self._worker.finish()
            return
        try:
            if self._export_frame == 0:
                self.viewer.advance(0.0)
            else:
                self.viewer.advance(1.0 / self._fps)
            rgba = self.viewer.capture_rgba(self.width.value(), self.height.value())
            if not self._worker.offer(rgba):
                # The encoder consumes at its own pace. Do not let a large
                # unbounded queue eat all RAM on 4K outputs.
                if not self._worker.isRunning():
                    raise RuntimeError("Encoder thread exited unexpectedly")
                QTimer.singleShot(10, lambda frame=rgba: self._retry_frame(frame))
                return
            self._export_frame += 1
            self.progress.setValue(self._export_frame)
            QTimer.singleShot(0, self._capture_next)
        except Exception as exc:
            self._encoding_failed(str(exc))

    def _retry_frame(self, rgba):
        if not self._busy or self._worker is None or self._closing or self._worker.cancel_requested.is_set():
            return
        if not self._worker.isRunning():
            self._encoding_failed("Encoder thread stopped before accepting frame")
            return
        if self._worker.offer(rgba):
            self._export_frame += 1
            self.progress.setValue(self._export_frame)
            QTimer.singleShot(0, self._capture_next)
        else:
            QTimer.singleShot(10, lambda frame=rgba: self._retry_frame(frame))

    def _motion_encoded(self, message):
        if not self._busy:
            return
        self._log(message)
        self._worker = None
        self._export_position += 1
        QTimer.singleShot(0, self._next_motion)

    def _encoding_failed(self, message):
        if self._worker is not None:
            self._worker.stop()
        self._busy = False
        self._set_enabled(self.viewer.model is not None)
        self._log("Export failed: " + message)
        QMessageBox.critical(self, "Export failed", str(message))

    def _encoding_aborted(self):
        self._busy = False
        self._worker = None
        self._set_enabled(self.viewer.model is not None)
        self._log("Canceled. Previously completed files were kept.")

    def cancel_export(self):
        if self._worker is not None:
            self._worker.stop()
            self.cancel_button.setEnabled(False)
            self._log("Canceling encoder…")
        else:
            self._busy = False
            self._set_enabled(self.viewer.model is not None)

    def closeEvent(self, event):
        self._closing = True
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            if not self._worker.wait(5000):
                self._closing = False
                QMessageBox.warning(self, "Export running",
                    "Waiting for the encoder to stop. Try closing again.")
                event.ignore()
                return
        self.viewer.cleanup()
        super().closeEvent(event)
