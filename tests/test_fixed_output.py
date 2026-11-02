"""Fixed output folder must never be auto-populated or saved per model."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from as_live2d.model import ModelCatalog, Motion
from as_live2d.output import fixed_output_for_model, model_export_folder_name
from as_live2d.window import ReaderWindow


class FixedOutputPathTests(TestCase):
    def test_plain_and_cubism_json_names(self):
        self.assertEqual(model_export_folder_name(Path("animação_55.json")),
                         "animação_55")
        self.assertEqual(model_export_folder_name(Path("Char100_Pose3.model3.json")),
                         "Char100_Pose3")
        self.assertEqual(model_export_folder_name(Path("Cena A.JSON")), "Cena A")

    def test_folder_is_based_on_json_not_catalog_display_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = fixed_output_for_model(str(root), Path("model_01.model3.json"))
            self.assertEqual(output, root.resolve() / "model_01")
            self.assertFalse(output.exists())  # no directories before exporting

    def test_blank_and_invalid_fixed_roots_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path("animação10.json")
            with self.assertRaisesRegex(ValueError, "não definida"):
                fixed_output_for_model("", source)
            with self.assertRaisesRegex(ValueError, "não existe"):
                fixed_output_for_model(str(Path(temp) / "missing"), source)


class FixedOutputGuiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = ReaderWindow()

    def tearDown(self):
        self.window.viewer.model = None
        self.window.close()

    def test_output_starts_blank_each_new_window(self):
        self.assertEqual(self.window.output.text(), "")
        self.window.output.setText(r"C:\EXT")
        self.window.close()
        other = ReaderWindow()
        try:
            self.assertEqual(other.output.text(), "")
        finally:
            other.close()

    def test_output_remains_same_for_multiple_models(self):
        with tempfile.TemporaryDirectory() as temp:
            self.window.output.setText(temp)
            for json_name in ("animação10.model3.json", "animação_55.model3.json"):
                model_json = Path(temp) / json_name
                candidate = ModelCatalog(path=model_json, name="Display Name",
                                         motions=[Motion("Idle", 0, Path("idle.motion3.json"), 1.0, 30.0)])
                with patch("as_live2d.window.inspect_model", return_value=candidate), \
                     patch.object(self.window.viewer, "load_model"):
                    self.window.open_path(model_json)
                self.assertEqual(self.window.output.text(), temp)
                _, folder = self.window._settings_for_export()
                self.assertEqual(folder, Path(temp).resolve() / json_name.replace(".model3.json", ""))

    def test_export_without_fixed_folder_opens_warning(self):
        self.window.viewer.model = object()
        self.window.output.setText("")
        with patch.object(QMessageBox, "warning") as warning:
            self.window.start_export()
        warning.assert_called_once()
        self.assertIn("Pasta de saída fixa", warning.call_args.args[1])
        self.assertFalse(self.window._busy)
