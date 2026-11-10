"""Synchronize individual ArtMesh checkboxes with the Live2D runtime.

The installed live2d-py 0.7.0.4 exposes no writable Drawable opacity API.
Use an *ephemeral* MOC3 shadow of the current visibility state, reload it
automatically and render/export via the existing shared Live2DViewer.
No user MOD, persistent model copy or texture changes are made.
"""
from pathlib import Path
import tempfile

from PySide6.QtCore import QObject

from .live_mesh_preview import LiveMeshPreviewWorker


class MeshVisibilityController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.worker = None
        self.owners = []
        self.folder = None
        self.revision = 0
        self.applied = 0
        self.error = False
        self.reloading = False

    def on_source_change(self):
        self.revision += 1
        self.applied = self.revision
        self.error = False
        self.folder = None
        self.window.mesh_status.setText("")

    def on_model_loaded(self):
        if (self.window.current_path is not None and
                self.window.viewer.model_path == self.window.current_path and
                self.window._mesh_overrides and not self.reloading):
            self.revision += 1
            self.refresh()
        elif not self.window._mesh_overrides:
            self.window.mesh_status.setText("")

    def changed(self):
        self.revision += 1
        self.error = False
        self.refresh()

    def refresh(self):
        win = self.window
        if self.worker is not None:
            win.mesh_status.setText("Atualizando ArtMeshes...")
            return
        if win.current_path is None or win._busy or self.error:
            return
        if not win._mesh_overrides:
            self.applied = self.revision
            if (win.viewer.model is not None and
                    win.viewer.model_path != win.current_path):
                self._reload(win.current_path)
            win.mesh_status.setText("ArtMeshes atualizadas.")
            return
        try:
            if self.folder is None:
                # Same directory avoids copies of massive atlases/motion files.
                owner = tempfile.TemporaryDirectory(
                    prefix=".as_live2d_preview_", dir=win.current_path.parent)
                self.owners.append(owner)
                self.folder = Path(owner.name)
        except OSError as exc:
            self.error = True
            win.mesh_status.setText(f"Falha ao criar cache de preview: {exc}")
            win._log(f"ArtMesh cache: {exc}")
            return
        job = LiveMeshPreviewWorker(
            win.current_path, self.folder, win._mesh_overrides,
            self.revision, win)
        self.worker = job
        job.ready.connect(self._ready)
        job.failed.connect(self._failed)
        job.finished.connect(self._finished)
        win.mesh_status.setText("Atualizando preview/exportação...")
        win.export_button.setEnabled(False)
        job.start()

    def _reload(self, manifest):
        win = self.window
        win._saved_part_overrides = win.viewer.get_part_overrides()
        win._saved_parameter_overrides = win.viewer.get_parameter_overrides()
        self.reloading = True
        try:
            win.viewer.load_model(Path(manifest))
        finally:
            self.reloading = False

    def _ready(self, manifest, source, revision):
        win = self.window
        if source != win.current_path or revision != self.revision:
            return
        self.applied = revision
        self._reload(manifest)
        if not self.error:
            win.mesh_status.setText(
                "ArtMeshes sincronizadas no preview e na exportação.")

    def _failed(self, reason, source, revision):
        if source != self.window.current_path or revision != self.revision:
            return
        self.error = True
        self.applied = revision
        self.window.mesh_status.setText(f"ArtMesh não aplicada: {reason}")
        self.window._log(f"ArtMesh preview: {reason}")

    def _finished(self):
        self.worker = None
        if not self.error and self.applied != self.revision:
            self.refresh()
        else:
            self.window._set_enabled(
                self.window.viewer.model is not None and not self.error)

    def failed_loading(self):
        """Handle an invalid temporary runtime without a retry loop."""
        if not self.reloading or self.window.current_path is None:
            return False
        self.error = True
        self.window.mesh_status.setText(
            "Não foi possível renderizar ArtMesh individual; restaurando original.")
        self.window._mesh_overrides.clear()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(
            0, lambda: self.window.viewer.load_model(self.window.current_path))
        return True

    def can_export(self):
        return (not self.error and self.worker is None and
                self.applied == self.revision)

    def cleanup(self):
        if self.worker is not None and self.worker.isRunning():
            return False
        for owner in self.owners:
            try:
                owner.cleanup()
            except OSError:
                pass
        self.owners.clear()
        return True
