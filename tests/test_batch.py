"""Recursive Live2D model batch: discovery, queue, output and cancellation."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QMessageBox

from as_live2d.batch import discover_models, batch_model_output
from as_live2d.model import ModelCatalog, Motion
from as_live2d.window import ReaderWindow


def model_file(path: Path, *, valid=True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"FileReferences":{"Moc":"rig.moc3"}}'
                    if valid else '{"Other":"data"}', encoding="utf-8")
    return path


class BatchScannerTests(TestCase):
    def test_recursively_finds_cubism_and_legacy_manifests_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = model_file(root / "A" / "Luna.model3.json")
            b = model_file(root / "B" / "Luna.MODEL3.JSON")
            c = model_file(root / "B" / "OldFormat.json")
            model_file(root / "B" / "Walk.motion3.json", valid=False)
            model_file(root / "B" / "Luna.model3.json.as-reader.json")
            model_file(root / "B" / "normal.json", valid=False)
            found = discover_models(root)
            self.assertEqual(found, [a.resolve(), b.resolve(), c.resolve()])

    def test_distinct_subfolders_cannot_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "input"
            dest = Path(tmp) / "export"
            a = model_file(root / "A" / "model3.json")
            b = model_file(root / "B" / "model3.json")
            # User selects the destination; the scanner/planner never creates it.
            dest.mkdir()
            out_a = batch_model_output(dest, root, a)
            out_b = batch_model_output(dest, root, b)
            self.assertEqual(out_a, dest.resolve() / "A" / "model3")
            self.assertEqual(out_b, dest.resolve() / "B" / "model3")
            self.assertNotEqual(out_a, out_b)
            self.assertFalse(out_a.exists())
            self.assertFalse(out_b.exists())

    def test_invalid_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "raiz"):
                discover_models(Path(tmp) / "nope")


class BatchUiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = ReaderWindow()

    def tearDown(self):
        self.window._batch_active = False
        self.window._busy = False
        self.window.viewer.model = None
        self.window.close()
        self.app.processEvents()

    def pump(self):
        for _ in range(12):
            self.app.processEvents()

    def test_gui_has_root_and_batch_controls(self):
        self.assertEqual(self.window.batch_root_input.text(), "")
        self.assertTrue(self.window.batch_export_button.isEnabled())
        self.assertIn("lote", self.window.batch_export_button.text().lower())

    def test_root_or_output_absent_does_not_start_queue(self):
        with patch.object(QMessageBox, "warning") as warning:
            self.window.start_batch()
            warning.assert_called_once()
            self.assertFalse(self.window._batch_active)
            warning.reset_mock()
            with tempfile.TemporaryDirectory() as tmp:
                self.window.output.setText(tmp)
                self.window.start_batch()
                warning.assert_called_once()
                self.assertIn("raiz", warning.call_args.args[-1])
                self.assertFalse(self.window._batch_active)

    def test_two_models_export_sequentially_with_existing_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "input"
            dest = Path(tmp) / "ext"
            first = model_file(root / "A" / "model3.json")
            second = model_file(root / "B" / "model3.json")
            dest.mkdir()
            self.window.output.setText(str(dest))
            self.window.batch_root_input.setText(str(root))
            exported = []
            opened = []

            def inspect(path):
                return ModelCatalog(
                    path=Path(path), name=Path(path).stem,
                    motions=[Motion("Idle", 0, Path("idle.motion3.json"), 1.0, 30)])

            def load(path):
                opened.append(Path(path))
                self.window.viewer.model = MagicMock()
                self.window.viewer.model_path = Path(path)
                self.window._model_loaded(Path(path).name)

            def export():
                exported.append((self.window.current_path,
                                 self.window._settings_for_export()[1],
                                 len(self.window.checked_motions())))
                self.window._export_jobs = self.window.checked_motions()
                self.window._export_position = len(self.window._export_jobs)
                self.window._busy = True
                self.window._set_enabled(True)

            with patch("as_live2d.window.inspect_model", side_effect=inspect), \
                 patch.object(self.window.viewer, "load_model", side_effect=load), \
                 patch.object(self.window, "_fill_parts"), \
                 patch.object(self.window, "_fill_parameters"), \
                 patch.object(self.window, "start_export", side_effect=export):
                self.window.start_batch()
                self.pump()
                self.assertEqual(opened, [first.resolve()])
                self.assertEqual(self.window._batch_phase, "exporting")
                self.assertFalse(self.window.open_button.isEnabled())
                self.assertTrue(self.window.cancel_button.isEnabled())
                self.assertEqual(exported[0], (first.resolve(),
                    dest.resolve() / "A" / "model3", 1))

                # Pretend the existing motion-export loop has finished.
                self.window._next_motion()
                self.pump()
                self.assertEqual(opened, [first.resolve(), second.resolve()])
                self.assertEqual(self.window._batch_phase, "exporting")
                self.assertEqual(exported[1], (second.resolve(),
                    dest.resolve() / "B" / "model3", 1))
                self.window._next_motion()
                self.pump()

            self.assertFalse(self.window._batch_active)
            self.assertEqual(self.window._batch_success, 2)
            self.assertFalse(self.window._batch_skipped)
            self.assertEqual(self.window.output.text(), str(dest))
            # Last model is left visible in the same viewer.
            self.assertEqual(self.window.current_path, second.resolve())

    def test_cancel_stops_queue_before_next_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "src"
            dest = Path(tmp) / "ext"
            model_file(root / "A" / "a.model3.json")
            model_file(root / "B" / "b.model3.json")
            dest.mkdir()
            self.window.output.setText(str(dest))
            self.window.batch_root_input.setText(str(root))
            opened = []

            def inspect(path):
                return ModelCatalog(
                    path=Path(path), name="Test",
                    motions=[Motion("Idle", 0, Path("idle.motion3.json"), 1, 30)])

            def load(path):
                opened.append(Path(path))
                self.window.viewer.model = MagicMock()
                self.window.viewer.model_path = Path(path)
                self.window._model_loaded(Path(path).name)

            def export():
                self.window._busy = True
                self.window._set_enabled(True)

            with patch("as_live2d.window.inspect_model", side_effect=inspect), \
                 patch.object(self.window.viewer, "load_model", side_effect=load), \
                 patch.object(self.window, "_fill_parts"), \
                 patch.object(self.window, "_fill_parameters"), \
                 patch.object(self.window, "start_export", side_effect=export):
                self.window.start_batch()
                self.pump()
                self.assertEqual(len(opened), 1)
                self.window.cancel_export()
                self.pump()
                self.assertFalse(self.window._batch_active)
                self.assertFalse(self.window._busy)
                self.assertEqual(len(opened), 1)

    def test_bad_manifest_skips_to_next_model_without_popup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "src"
            dest = Path(tmp) / "ext"
            model_file(root / "A" / "bad.model3.json")
            good = model_file(root / "B" / "good.model3.json")
            dest.mkdir()
            self.window.output.setText(str(dest))
            self.window.batch_root_input.setText(str(root))
            opened = []

            def inspect(path):
                if Path(path).name == "bad.model3.json":
                    raise ValueError("JSON sem MOC")
                return ModelCatalog(path=Path(path), name="Good",
                    motions=[Motion("Idle", 0, Path("idle.motion3.json"), 1, 30)])

            def load(path):
                opened.append(Path(path))
                self.window.viewer.model = MagicMock()
                self.window.viewer.model_path = Path(path)
                self.window._model_loaded(Path(path).name)

            def export():
                self.window._export_jobs = self.window.checked_motions()
                self.window._export_position = len(self.window._export_jobs)
                self.window._busy = True

            with patch("as_live2d.window.inspect_model", side_effect=inspect), \
                 patch.object(self.window.viewer, "load_model", side_effect=load), \
                 patch.object(self.window, "_fill_parts"), \
                 patch.object(self.window, "_fill_parameters"), \
                 patch.object(self.window, "start_export", side_effect=export), \
                 patch.object(QMessageBox, "critical") as modal:
                self.window.start_batch()
                self.pump()
                self.assertEqual(opened, [good.resolve()])
                self.assertEqual(len(self.window._batch_skipped), 1)
                self.window._next_motion()
                self.pump()
                modal.assert_not_called()
            self.assertFalse(self.window._batch_active)
            self.assertEqual(self.window._batch_success, 1)
