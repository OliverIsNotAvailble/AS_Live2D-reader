"""Live2D force/face recovery regression tests without user model data."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from as_live2d.part_visibility import PartTrack
from as_live2d.viewer import Live2DViewer
from as_live2d.window import ReaderWindow

class ForceParameterTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_force_then_restore_original_motion(self):
        view = Live2DViewer()
        view.timer.stop()
        try:
            native = Mock()
            native.GetParameterMinimumValue.return_value = 0.0
            native.GetParameterMaximumValue.return_value = 1.0
            native.GetParameterDefaultValue.return_value = 0.5
            view.model = SimpleNamespace(_model=native)
            view._param_ids = {"ParamEyeLOpen": 0}
            view._param_tracks = {"ParamEyeLOpen": PartTrack([0, 0, 0, 2, 0])}
            view._motion_elapsed = 1.0
            self.assertEqual(view.get_parameter_specs(), [("ParamEyeLOpen", 0, 1, .5)])
            view.set_parameter_override("ParamEyeLOpen", 1.0)
            view._apply_parameter_overrides()
            native.SetParameterValue.assert_any_call(0, 1.0)
            view.set_parameter_override("ParamEyeLOpen", None)
            self.assertEqual(view.get_parameter_overrides(), {})
            native.SetParameterValue.assert_called_with(0, 0.0)
            view.set_parameter_override("missing", 1.0)
            view.set_parameter_override("ParamEyeLOpen", float("nan"))
            self.assertEqual(view.get_parameter_overrides(), {})
        finally:
            view.model = None
            view.close()

class LayoutAndEmotionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_ui_and_lion_face_recovery(self):
        win = ReaderWindow()
        win.viewer.timer.stop()
        try:
            self.assertEqual(win.sidebar_tabs.count(), 2)
            self.assertEqual(win.sidebar_tabs.tabText(1), "Meshes")
            native = Mock()
            native.GetParameterMinimumValue.return_value = 0.0
            native.GetParameterMaximumValue.return_value = 1.0
            native.GetParameterDefaultValue.return_value = 0.0
            wrapper = Mock()
            wrapper._model = native
            view = win.viewer
            view.model = wrapper
            view._part_ids = {"Mouth": 0, "Brows": 1, "Idle": 2, "Angreee": 3}
            view._param_ids = {"ParamEyeLOpen": 0, "ParamEyeROpen": 1,
                               "Param14": 2, "Param15": 3}
            win._parameter_display_names = {"Param14": "Idle", "Param15": "Ablush"}
            win._fill_parts()
            win._fill_parameters()
            win._recover_face()
            self.assertEqual(view.get_parameter_overrides(),
                             {"ParamEyeLOpen": 1., "ParamEyeROpen": 1., "Param14": 1.})
            self.assertEqual(view.get_part_overrides(),
                             {"Mouth": 1., "Brows": 1., "Idle": 1.})
            self.assertNotIn("Param15", view.get_parameter_overrides())
            win._reset_parameter_overrides()
            win._reset_part_overrides()
            self.assertFalse(view.get_parameter_overrides())
            self.assertFalse(view.get_part_overrides())
        finally:
            win.viewer.model = None
            win.close()
