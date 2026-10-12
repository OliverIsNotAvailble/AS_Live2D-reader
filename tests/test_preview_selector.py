"""Qt regression tests: preview selector does not alter the export checklist."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from as_live2d.model import ModelCatalog, Motion, load_profile
from as_live2d.window import ReaderWindow


class PreviewSelectorTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = ReaderWindow()
        self.motions = [
            Motion("Idle", 0, Path("first.motion3.json"), 9.0, 60),
            Motion("Clothes", 0, Path("second.motion3.json"), 5.0, 30),
            Motion("Idle", 1, Path("third.motion3.json"), 3.0, 60),
        ]
        self.window.catalog = ModelCatalog(
            path=Path("fake.model3.json"), name="Test Model",
            motions=self.motions)
        self.window._fill_motions()

    def tearDown(self):
        self.window.viewer.model = None
        self.window.close()

    def test_combo_and_export_checkboxes_are_independent(self):
        self.assertEqual(self.window.preview_combo.count(), 3)
        self.assertIs(self.window.preview_combo.currentData(), self.motions[0])
        self.assertEqual(len(self.window.checked_motions()), 3)

        with patch.object(self.window, "play_selected") as play:
            self.window.motion_list.item(0).setCheckState(Qt.CheckState.Unchecked)
            self.assertEqual(self.window.preview_combo.currentIndex(), 0)
            self.window.motion_list.setCurrentRow(2)
            self.assertEqual(self.window.preview_combo.currentIndex(), 0)
            play.assert_not_called()

            # Select the preview via the top dropdown.
            self.window.viewer.model = object()
            self.window.preview_combo.setCurrentIndex(1)
            play.assert_called_once()
            self.assertIs(self.window.preview_combo.currentData(), self.motions[1])
        # The export checklist remains unchanged, including the unchecked row.
        self.assertEqual(self.window.motion_list.item(0).checkState(),
                         Qt.CheckState.Unchecked)
        self.assertEqual(self.window.motion_list.item(1).checkState(),
                         Qt.CheckState.Checked)
        self.assertEqual(len(self.window.checked_motions()), 2)

    def test_play_button_uses_top_dropdown_not_highlighted_export_row(self):
        self.window.viewer.model = object()
        with patch.object(self.window.viewer, "play_motion") as play:
            self.window.preview_combo.setCurrentIndex(1)
            play.reset_mock()
            self.window.motion_list.setCurrentRow(2)
            self.window.play_selected()
            play.assert_called_once_with(
                "Clothes", 0, repeat=True,
                motion_path=Path("second.motion3.json"), duration=5.0)

    def test_preview_choice_is_saved_separately_from_export_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "avatar.model3.json"
            self.window.current_path = path
            self.window.preview_combo.setCurrentIndex(2)
            self.window.motion_list.item(1).setCheckState(Qt.CheckState.Unchecked)
            self.window.save_current_profile()
            saved = load_profile(path)
            self.assertEqual(saved["preview_motion"], ["Idle", 1])
            self.assertEqual(saved["selected_motions"], [["Idle", 0], ["Idle", 1]])

            self.window.preview_combo.setCurrentIndex(0)
            self.window._restore_profile()
            self.assertEqual(self.window.preview_combo.currentData(), self.motions[2])

    def test_preview_combo_disables_while_export_running(self):
        self.window._busy = True
        self.window._set_enabled(True)
        self.assertFalse(self.window.preview_combo.isEnabled())
        self.window._busy = False
        self.window._set_enabled(True)
        self.assertTrue(self.window.preview_combo.isEnabled())
