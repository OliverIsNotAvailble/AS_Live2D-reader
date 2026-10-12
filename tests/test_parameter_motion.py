"""Regression: active motion's Parameter curves must animate even when
live2d-py native UpdateMotion returns None instead of a bool.
No proprietary user model or game motions are committed.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from as_live2d.part_visibility import (
    PartTrack, apply_parameter_tracks, read_motion_tracks,
)


class ParameterMotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sample.motion3.json"
        self.path.write_text(json.dumps({
            "Meta": {"Duration": 9, "Fps": 60},
            "Curves": [
                {"Target": "Parameter", "Id": "ParamBodyAngleX",
                 "Segments": [0, -30, 0, 1, 30, 0, 2, -30]},
                {"Target": "PartOpacity", "Id": "head_1",
                 "Segments": [0, 0, 0, 9, 0]},
                {"Target": "Parameter", "Id": "ParamMouthOpenY",
                 "Segments": [0, 0, 0, 1, 1, 0, 2, 0]},
                {"Target": "PartOpacity", "Id": "head_2",
                 "Segments": [0, 1, 0, 9, 1]},
            ]
        }), encoding="utf-8")

    def test_parse_parameter_and_part_curves_in_any_order(self):
        parameters, parts, interleaved = read_motion_tracks(self.path)
        self.assertTrue(interleaved)
        self.assertEqual(set(parameters), {"ParamBodyAngleX", "ParamMouthOpenY"})
        self.assertEqual(set(parts), {"head_1", "head_2"})
        self.assertAlmostEqual(parameters["ParamBodyAngleX"].value_at(.5), 0)
        self.assertAlmostEqual(parameters["ParamBodyAngleX"].value_at(1), 30)
        self.assertAlmostEqual(parameters["ParamMouthOpenY"].value_at(1), 1)

    def test_interpolated_values_are_sent_to_native_parameter_indices(self):
        parameters, _, _ = read_motion_tracks(self.path)
        mock_model = Mock()
        lookup = {"ParamBodyAngleX": 7, "ParamMouthOpenY": 10}
        mapping = [(lookup[k], curve) for k, curve in parameters.items()
                   if k in lookup]
        count = apply_parameter_tracks(mock_model, mapping, .5)
        self.assertEqual(count, 2)
        mock_model.SetParamByIndex.assert_any_call(7, 0.0)
        mock_model.SetParamByIndex.assert_any_call(10, .5)
        calls_at_one = apply_parameter_tracks(mock_model, mapping, 1.0)
        self.assertEqual(calls_at_one, 2)
        mock_model.SetParamByIndex.assert_any_call(7, 30.0)

    def test_unknown_parameter_ids_are_not_sent_to_native(self):
        parameters, _, _ = read_motion_tracks(self.path)
        fake_model = Mock()
        indices = {"ParamUnknown": 0}
        mapping = [(indices[k], curve) for k, curve in parameters.items()
                   if k in indices]
        self.assertEqual(apply_parameter_tracks(fake_model, mapping, 1.0), 0)
        fake_model.SetParamByIndex.assert_not_called()


class MotionTickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_direct_motion_updates_even_if_native_returns_none(self):
        from as_live2d.viewer import Live2DViewer
        view = Live2DViewer()
        view.timer.stop()
        try:
            native = Mock()
            native.IsMotionFinished.return_value = False
            native.UpdateMotion.return_value = None
            model = Mock()
            model._model = native
            view.model = model
            view.motion = ("Idle", 0)
            view.repeat = False
            view.auto_blink = True
            view.auto_breath = False
            view.auto_physics = False
            view._has_eye_tracks = True
            view._part_ids = {}
            view._mapped_param_tracks = [(4, PartTrack([0, -30, 0, 1, 30]))]
            view._motion_duration = 1
            view._motion_elapsed = 0.0

            view.advance(.5)

            native.UpdateMotion.assert_called_once_with(.5)
            native.UpdateBlink.assert_not_called()
            model.SetParamByIndex.assert_called_once_with(4, 0.0)
            self.assertAlmostEqual(view._motion_elapsed, .5)
        finally:
            view.model = None
            view.close()
