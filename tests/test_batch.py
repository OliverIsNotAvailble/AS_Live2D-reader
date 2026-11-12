"""VLote-style Live2D batch queue, classifications and safe project moves."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QMessageBox

from as_live2d.batch import (
    discover_models, project_folder, batch_model_output,
    available_destination, move_project,
)
from as_live2d.model import ModelCatalog, Motion
from as_live2d.window import ReaderWindow


def model_file(path: Path, *, valid: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"FileReferences":{"Moc":"rig.moc3"}}'
                    if valid else '{"Other":"data"}', encoding="utf-8")
    return path


class BatchScannerTests(TestCase):
    def test_recursively_finds_models_only_outside_category_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = model_file(root / "A" / "Luna.model3.json")
            b = model_file(root / "B" / "Luna.MODEL3.JSON")
            c = model_file(root / "B" / "OldFormat.json")
            model_file(root / "B" / "Walk.motion3.json", valid=False)
            model_file(root / "B" / "normal.json", valid=False)
            model_file(root / "_Done" / "finished.model3.json")
            model_file(root / "_Null" / "skipped.model3.json")
            model_file(root / "_EXT" / "exported.model3.json")
            model_file(root / "direct.model3.json")
            self.assertEqual(discover_models(root),
                             [a.resolve(), b.resolve(), c.resolve()])

    def test_output_under_ext_without_any_fixed_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = model_file(root / "A" / "model3.json")
            b = model_file(root / "B" / "model3.json")
            sub = model_file(root / "B" / "other" / "nested.model3.json")
            self.assertEqual(project_folder(root, sub), (root / "B").resolve())
            self.assertEqual(batch_model_output(root, a),
                             root.resolve() / "_EXT" / "A")
            self.assertEqual(batch_model_output(root, b, multiple_in_project=True),
                             root.resolve() / "_EXT" / "B" / "model3")
            self.assertEqual(batch_model_output(root, sub, multiple_in_project=True),
                             root.resolve() / "_EXT" / "B" / "other" / "nested")
            self.assertFalse((root / "_EXT").exists())

    def test_null_moves_entire_project_and_skips_future_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m = model_file(root / "Character" / "nested" / "hero.model3.json")
            (m.parent / "texture.png").write_bytes(b"png")
            dest = move_project(root, m, "null")
            self.assertEqual(dest, root.resolve() / "_Null" / "Character")
            self.assertTrue((dest / "nested" / "texture.png").is_file())
            self.assertFalse((root / "Character").exists())
            self.assertFalse(discover_models(root))

    def test_done_never_overwrites_existing_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "_Done" / "Character"
            existing.mkdir(parents=True)
            (existing / "sentinel.txt").write_text("keep", encoding="utf-8")
            m = model_file(root / "Character" / "character.model3.json")
            dest = move_project(root, m, "done")
            self.assertEqual(dest, root.resolve() / "_Done" / "Character (2)")
            self.assertEqual((existing / "sentinel.txt").read_text(), "keep")
            self.assertTrue((dest / "character.model3.json").is_file())

    def test_no_root_move_and_invalid_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m = model_file(root / "a.model3.json")
            with self.assertRaises(ValueError):
                project_folder(root, m)
            with self.assertRaises(ValueError):
                move_project(root, m, "null")
            m2 = model_file(root / "A" / "model3.json")
            with self.assertRaises(ValueError):
                move_project(root, m2, "something")
            with self.assertRaises(ValueError):
                discover_models(root / "missing")

    def test_existing_export_folder_uses_unique_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A").mkdir()
            self.assertEqual(available_destination(root, "A"),
                             root / "A (2)")


class BatchUiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = ReaderWindow()

    def tearDown(self):
        self.win._batch_active = False
        self.win._busy = False
        self.win._worker = None
        self.win._batch_cleanup_stage()
        self.win.viewer.model = None
        self.win.close()
        self.app.processEvents()

    def pump(self):
        for _ in range(15):
            self.app.processEvents()

    @staticmethod
    def manifest(path):
        path = Path(path)
        return ModelCatalog(
            path=path, name=path.stem,
            motions=[Motion("Idle", 0, path.parent / "idle.motion3.json", 1, 30)])

    def mocked_viewer(self, opened):
        def load(path):
            opened.append(Path(path))
            self.win.viewer.model = MagicMock()
            self.win.viewer.model_path = Path(path)
            self.win._model_loaded(Path(path).name)
        return load

    def fake_export(self):
        self.assertEqual(self.win._batch_phase, "exporting")
        self.assertTrue(self.win._batch_stage.is_dir())
        # The fake encoder writes a file to the temporary output staging area.
        (self.win._batch_stage / "Idle.mp4").write_bytes(b"fake mp4")
        self.win._busy = True
        self.win._export_jobs = self.win.checked_motions()
        self.win._export_position = len(self.win._export_jobs)
        self.win._set_enabled(True)

    def test_ui_root_is_the_only_required_input(self):
        self.assertEqual(self.win.batch_root_input.text(), "")
        self.assertEqual(self.win.output.text(), "")
        self.assertIn("_Done", self.win.batch_export_button.text())
        self.assertIn("_Null", self.win.batch_null_button.text())
        self.assertFalse(self.win.batch_export_button.isEnabled())

    def test_choosing_root_opens_first_without_starting_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = model_file(root / "A" / "char.model3.json")
            self.win.batch_root_input.setText(str(root))
            opened = []
            with patch("as_live2d.window.inspect_model", self.manifest), \
                 patch.object(self.win.viewer, "load_model",
                              side_effect=self.mocked_viewer(opened)), \
                 patch.object(self.win, "_fill_parts"), \
                 patch.object(self.win, "_fill_parameters"):
                self.win.preview_batch_root()
                self.pump()
                self.assertEqual(opened, [a.resolve()])
                self.assertEqual(self.win._batch_phase, "ready")
                self.assertTrue(self.win.batch_export_button.isEnabled())
                self.assertTrue(self.win.batch_null_button.isEnabled())
                self.assertFalse((root / "_EXT").exists())
                self.assertEqual(self.win.output.text(), "")

    def test_export_moves_done_then_opens_next_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = model_file(root / "A" / "char.model3.json")
            b = model_file(root / "B" / "char.model3.json")
            self.win.batch_root_input.setText(str(root))
            opened = []
            with patch("as_live2d.window.inspect_model", self.manifest), \
                 patch.object(self.win.viewer, "load_model",
                              side_effect=self.mocked_viewer(opened)), \
                 patch.object(self.win, "_fill_parts"), \
                 patch.object(self.win, "_fill_parameters"), \
                 patch.object(self.win, "start_export", side_effect=self.fake_export):
                self.win.preview_batch_root()
                self.pump()
                self.win._batch_export_current()
                self.assertEqual(self.win._batch_phase, "exporting")
                self.win._next_motion()
                self.pump()
                self.assertTrue((root / "_EXT" / "A" / "Idle.mp4").is_file())
                self.assertTrue((root / "_Done" / "A" / "char.model3.json").is_file())
                self.assertFalse((root / "A").exists())
                self.assertEqual(opened, [a.resolve(), b.resolve()])
                self.win._batch_mark_null()
                self.pump()
                self.assertTrue((root / "_Null" / "B" / "char.model3.json").is_file())
                self.assertFalse(self.win._batch_active)
                self.assertEqual(self.win._batch_success, 1)
                self.assertFalse((root / "_EXT" / "B").exists())

    def test_null_without_export_moves_folder_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = model_file(root / "A" / "char.model3.json")
            self.win.batch_root_input.setText(str(root))
            with patch("as_live2d.window.inspect_model", self.manifest), \
                 patch.object(self.win.viewer, "load_model",
                              side_effect=self.mocked_viewer([])), \
                 patch.object(self.win, "_fill_parts"), \
                 patch.object(self.win, "_fill_parameters"):
                self.win.preview_batch_root()
                self.pump()
                self.win._batch_mark_null()
                self.pump()
            self.assertTrue((root / "_Null" / "A" / a.name).is_file())
            self.assertFalse((root / "_EXT").exists())
            self.assertEqual(self.win._batch_decisions[a.resolve()], "null")

    def test_bad_model_stays_in_queue_for_manual_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = model_file(root / "A" / "bad.model3.json")
            good = model_file(root / "B" / "good.model3.json")
            self.win.batch_root_input.setText(str(root))
            opened = []
            def inspect(path):
                if Path(path).name.startswith("bad"):
                    raise ValueError("invalid MOC")
                return self.manifest(path)
            with patch("as_live2d.window.inspect_model", side_effect=inspect), \
                 patch.object(self.win.viewer, "load_model",
                              side_effect=self.mocked_viewer(opened)), \
                 patch.object(self.win, "_fill_parts"), \
                 patch.object(self.win, "_fill_parameters"), \
                 patch.object(QMessageBox, "critical") as modal:
                self.win.preview_batch_root()
                self.pump()
                self.assertEqual(self.win._batch_phase, "invalid")
                self.assertEqual(opened, [])
                self.assertTrue(self.win.batch_null_button.isEnabled())
                self.win._batch_mark_null()
                self.pump()
                self.assertTrue((root / "_Null" / "A" / bad.name).is_file())
                self.assertEqual(opened, [good.resolve()])
                modal.assert_not_called()

    def test_shared_project_moves_only_after_last_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = model_file(root / "P" / "a.model3.json")
            second = model_file(root / "P" / "b.model3.json")
            self.win.batch_root_input.setText(str(root))
            with patch("as_live2d.window.inspect_model", self.manifest), \
                 patch.object(self.win.viewer, "load_model",
                              side_effect=self.mocked_viewer([])), \
                 patch.object(self.win, "_fill_parts"), \
                 patch.object(self.win, "_fill_parameters"):
                self.win.preview_batch_root()
                self.pump()
                self.win._batch_mark_null()
                self.pump()
                self.assertTrue(first.exists())
                self.assertEqual(self.win._batch_current, second.resolve())
                self.win._batch_mark_null()
                self.pump()
            self.assertFalse((root / "P").exists())
            self.assertTrue((root / "_Null" / "P" / first.name).is_file())
            self.assertTrue((root / "_Null" / "P" / second.name).is_file())

    def test_cancel_does_not_move_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = model_file(root / "A" / "model3.json")
            self.win.batch_root_input.setText(str(root))
            with patch("as_live2d.window.inspect_model", self.manifest), \
                 patch.object(self.win.viewer, "load_model",
                              side_effect=self.mocked_viewer([])), \
                 patch.object(self.win, "_fill_parts"), \
                 patch.object(self.win, "_fill_parameters"):
                self.win.preview_batch_root()
                self.pump()
                self.win.cancel_export()
                self.pump()
            self.assertTrue(original.exists())
            self.assertFalse(self.win._batch_active)
            self.assertFalse((root / "_Done").exists())

    def test_missing_root_is_explained_in_status(self):
        self.win.preview_batch_root()
        self.assertIn("pasta raiz", self.win.batch_status.text().lower())
