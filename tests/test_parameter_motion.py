"""Regression: active motion's Parameter curves must animate even when
live2d-py native UpdateMotion returns None instead of a bool.
No proprietary user model or game motions are committed.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

from as_live2d.part_visibility import (
    PartTrack, apply_parameter_tracks, read_motion_tracks,
)


class InstalledNativeApiContractTests(unittest.TestCase):
    def test_pinned_live2d_v3_model_exposes_actual_setter(self):
        # This is the installed CPython extension, NOT an unrestricted Mock.
        # Version 0.7.0.4's Model method is SetParameterValue, whereas
        # new upstream versions call the method SetParamByIndex.
        from live2d.v3._v3cpp import Model
        self.assertTrue(callable(getattr(Model, "SetParameterValue", None)))
        self.assertFalse(hasattr(Model, "SetParamByIndex"))


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
        native = Mock(spec_set=["SetParameterValue"])
        wrapper = SimpleNamespace(_model=native)  # LAppModel has NO setter
        lookup = {"ParamBodyAngleX": 7, "ParamMouthOpenY": 10}
        mapping = [(lookup[k], curve) for k, curve in parameters.items()
                   if k in lookup]
        count = apply_parameter_tracks(wrapper._model, mapping, .5)
        self.assertEqual(count, 2)
        native.SetParameterValue.assert_any_call(7, 0.0)
        native.SetParameterValue.assert_any_call(10, .5)
        calls_at_one = apply_parameter_tracks(wrapper._model, mapping, 1.0)
        self.assertEqual(calls_at_one, 2)
        native.SetParameterValue.assert_any_call(7, 30.0)

    def test_unknown_parameter_ids_are_not_sent_to_native(self):
        parameters, _, _ = read_motion_tracks(self.path)
        fake_model = Mock(spec_set=["SetParameterValue"])
        indices = {"ParamUnknown": 0}
        mapping = [(indices[k], curve) for k, curve in parameters.items()
                   if k in indices]
        self.assertEqual(apply_parameter_tracks(fake_model, mapping, 1.0), 0)
        fake_model.SetParameterValue.assert_not_called()


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
            native = Mock(spec_set=[
                "IsMotionFinished", "UpdateMotion", "LoadParameters",
                "SaveParameters", "UpdateExpression", "UpdateDrag",
                "UpdatePose", "SetParameterValue"
            ])
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
            native.SetParameterValue.assert_called_once_with(4, 0.0)
            self.assertNotIn("SetParameterValue", model.__dict__)
            self.assertAlmostEqual(view._motion_elapsed, .5)
        finally:
            view.model = None
            view.close()

    def test_interleaved_motion_does_not_start_unregistered_fixed_group(self):
        from as_live2d.viewer import Live2DViewer
        from PySide6.QtCore import Qt
        view = Live2DViewer()
        view.timer.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "interleaved.motion3.json"
                path.write_text(json.dumps({
                    "Curves": [
                        {"Target": "Parameter", "Id": "ParamAngleX",
                         "Segments": [0, -30, 0, 1, 30]},
                        {"Target": "PartOpacity", "Id": "head_1",
                         "Segments": [0, 0, 0, 1, 0]},
                        {"Target": "Parameter", "Id": "ParamEyeLOpen",
                         "Segments": [0, 1, 0, 1, 0]},
                    ]
                }), encoding="utf-8")
                native = Mock()
                model = Mock()
                model._model = native
                view.model = model
                view._param_ids = {"ParamAngleX": 0, "ParamEyeLOpen": 1}
                view._part_ids = {"head_1": 0}
                view.play_motion("Idle", 0, repeat=True,
                                 motion_path=path, duration=1.0)
                self.assertTrue(view._manual_only)
                self.assertIsNone(view.motion)
                model.StartMotion.assert_not_called()
                model.LoadExtraMotion.assert_not_called()
                view.advance(0.5)
                native.SetParameterValue.assert_any_call(0, 0.0)
                view.advance(0.25)
                native.SetParameterValue.assert_any_call(0, 15.0)
                model.StartMotion.assert_not_called()
        finally:
            view.model = None
            view.close()

    def test_tick_stops_after_one_failure_not_each_frame(self):
        from as_live2d.viewer import Live2DViewer
        view = Live2DViewer()
        view.timer.stop()
        try:
            native = Mock()
            native.LoadParameters.side_effect = RuntimeError("broken native API")
            model = Mock()
            model._model = native
            view.model = model
            view.playing = True
            view.repeat = False
            messages = []
            view.playback_failed.connect(messages.append)
            view._tick()
            self.assertFalse(view.playing)
            self.assertEqual(messages, ["broken native API"])
            view._tick()
            native.LoadParameters.assert_called_once()
        finally:
            view.model = None
            view.close()
