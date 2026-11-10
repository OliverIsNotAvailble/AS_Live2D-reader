"""Build an independent Cubism mod without freezing the Qt UI."""
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from .texture_mod import clone_mod_bundle

class MeshModWorker(QThread):
    saved = Signal(object)
    failed = Signal(str)

    def __init__(self, manifest: Path, overrides: dict[str, bool], parent=None):
        super().__init__(parent)
        self.manifest = Path(manifest)
        self.overrides = dict(overrides)

    def run(self):
        try:
            new_manifest = clone_mod_bundle(
                self.manifest, {}, visibility_overrides=self.overrides)
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.saved.emit(new_manifest)
