"""Regression coverage for Live2D-only clockwise rotation, fitting and profiles.

Qt/OpenGL paint call tests mock GPU operations; they verify route consistency,
but actual GPU pixels must still be validated with a model on Windows.
"""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication
from as_live2d.rotation import rotation_fit_factor, source_pixel_for_rotation
from as_live2d.model import load_profile
from as_live2d.window import ReaderWindow
from as_live2d.viewer import Live2DViewer


class RotationGeometryTests(unittest.TestCase):
    def test_zero_degrees_does_not_adjust_frame(self):
        self.assertEqual(rotation_fit_factor(1280, 720, 0), 1.0)
        self.assertEqual(
            source_pixel_for_rotation(900, 300, 1280, 720, 0), (900, 300))

    def test_positive_right_rotation_is_clockwise(self):
        # Output right of center samples from above center at +90 degrees,
        # meaning the original top moves visually to the output's right.
        x, y = source_pixel_for_rotation(650, 360, 1280, 720, 90)
        self.assertAlmostEqual(x, 640)
        self.assertAlmostEqual(y, 370)
        x, y = source_pixel_for_rotation(650, 360, 1280, 720, -90)
        self.assertAlmostEqual(x, 640)
        self.assertAlmostEqual(y, 350)

    def test_non_square_canvas_uses_pixel_space_rotation(self):
        x, y = source_pixel_for_rotation(840, 360, 1280, 720, 30)
        self.assertAlmostEqual(x, 640 + math.cos(math.pi / 6) * 200)
        self.assertAlmostEqual(y, 360 + math.sin(math.pi / 6) * 200)

    def test_fit_factor_guarantees_rotated_canvas_inside_output(self):
        for w, h, angle in ((1280, 720, 30), (720, 1280, -35),
                            (1024, 1024, 45), (3840, 2160, 90)):
            fit = rotation_fit_factor(w, h, angle)
            self.assertGreater(fit, 0)
            self.assertLessEqual(fit, 1)
            radians = math.radians(angle)
            cw, sw = abs(math.cos(radians)), abs(math.sin(radians))
            self.assertLessEqual(
                fit * (w * cw + h * sw), w + 0.000001)
            self.assertLessEqual(
                fit * (w * sw + h * cw), h + 0.000001)

    def test_invalid_frame_or_angle(self):
        for args in ((0, 720, 15), (1280, -1, 15), (500, 500, float("nan"))):
            with self.assertRaises(ValueError):
                rotation_fit_factor(*args)


class RotationWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = ReaderWindow()
        self.window.viewer.timer.stop()

    def tearDown(self):
        self.window.close()

    def test_rotation_controls_update_viewer_and_reset(self):
        self.window.rotation.setValue(30)
        self.assertEqual(self.window.viewer.rotation_deg, 30)
        self.assertFalse(self.window.viewer.fit_rotation)
        self.window.fit_rotation_box.setChecked(True)
        self.assertTrue(self.window.viewer.fit_rotation)
        self.window.rotation.setValue(-35)
        self.assertEqual(self.window.viewer.rotation_deg, -35)
        self.window.rotation.setValue(0)
        self.assertEqual(self.window.viewer.rotation_deg, 0)

    def test_rotation_profile_roundtrip_and_model_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "one.model3.json"
            two = Path(tmp) / "two.model3.json"
            self.window.current_path = one
            self.window.rotation.setValue(30)
            self.window.fit_rotation_box.setChecked(True)
            self.window.save_current_profile()
            p = load_profile(one)
            self.assertEqual(p["rotation_deg"], 30)
            self.assertTrue(p["fit_rotation"])
            self.window.rotation.setValue(0)
            self.window.fit_rotation_box.setChecked(False)
            self.window._restore_profile()
            self.assertEqual(self.window.rotation.value(), 30)
            self.assertTrue(self.window.viewer.fit_rotation)
            self.window.current_path = two
            self.window._restore_profile()
            self.assertEqual(self.window.rotation.value(), 0)
            self.assertFalse(self.window.fit_rotation_box.isChecked())

    def test_pinned_native_runtime_exposes_pre_raster_rotation(self):
        # Checks the actual installed live2d-py extension and public wrapper.
        from live2d.v3 import LAppModel
        from live2d.v3._v3cpp import Model
        self.assertTrue(callable(getattr(LAppModel, "Rotate", None)))
        self.assertTrue(callable(getattr(Model, "Rotate", None)))

    def test_native_rotation_is_clockwise_positive_in_ui(self):
        viewer = self.window.viewer
        native = Mock()
        viewer.model = native
        viewer._model_render_size = (1280, 720)
        try:
            viewer.set_rotation(30)
            native.Rotate.assert_called_with(-30.0)
            native.SetScale.assert_called_with(1.0)
            viewer.set_rotation(-45)
            native.Rotate.assert_called_with(45.0)
            viewer.set_rotation(0)
            native.Rotate.assert_called_with(0.0)
        finally:
            viewer.model = None

    def test_fit_scales_native_model_at_current_render_resolution(self):
        viewer = self.window.viewer
        native = Mock()
        viewer.model = native
        viewer.scale = 1.5
        viewer._model_render_size = (1280, 720)
        try:
            viewer.set_rotation(30, fit=True)
            native.SetScale.assert_called_with(
                1.5 * rotation_fit_factor(1280, 720, 30))
            viewer._model_render_size = (720, 1280)
            viewer._set_model_camera()
            native.SetScale.assert_called_with(
                1.5 * rotation_fit_factor(720, 1280, 30))
        finally:
            viewer.model = None
            viewer.scale = 1.0

    def test_rotated_preview_draws_native_geometry_directly_over_static_bg(self):
        viewer = self.window.viewer
        native = Mock()
        viewer.model = native
        viewer.rotation_deg = 30
        try:
            with patch.object(viewer, "_render_size", return_value=(400, 250)), \
                 patch.object(viewer, "_draw_model") as draw_scene, \
                 patch("as_live2d.viewer.GL.glBindFramebuffer"), \
                 patch("as_live2d.viewer.GL.glViewport"):
                viewer.paintGL()
                draw_scene.assert_called_once()
                self.assertEqual(draw_scene.call_args.kwargs, {"preview": True})
                self.assertEqual(len(draw_scene.call_args.args), 1)
                # There is no intermediate rotated 400x250 texture to clip.
                self.assertFalse(hasattr(viewer, "_preview_rot_fbo"))
        finally:
            viewer.model = None

    def test_export_readback_draws_native_model_without_rotated_layer(self):
        viewer = self.window.viewer
        viewer.rotation_deg = 30
        viewer._fbo = Mock()
        viewer._fbo.handle.return_value = 11
        try:
            with patch.object(viewer, "_draw_model") as render_scene, \
                 patch("as_live2d.viewer.GL.glBindFramebuffer"), \
                 patch("as_live2d.viewer.GL.glViewport"), \
                 patch("as_live2d.viewer.GL.glReadBuffer"), \
                 patch("as_live2d.viewer.GL.glPixelStorei"), \
                 patch("as_live2d.viewer.GL.glReadPixels",
                       return_value=bytes([0] * (8 * 6 * 4))):
                frame = viewer._read_fbo(8, 6, (0, 0, 0, 1))
                self.assertEqual(frame.shape, (6, 8, 4))
                render_scene.assert_called_once_with((0, 0, 0, 1))
                self.assertFalse(hasattr(viewer, "_export_rot_fbo"))
        finally:
            viewer._fbo = None

    def test_export_render_resolution_and_preview_restoration(self):
        # Rotation and fit must apply at each respective size and preview
        # transform must be fully restored after an export capture.
        viewer = self.window.viewer
        viewer.model = Mock()
        viewer._fbo = Mock()
        viewer._fbo.width.return_value = 16
        viewer._fbo.height.return_value = 12
        viewer._fbo.isValid.return_value = True
        viewer.rotation_deg = 30
        viewer.fit_rotation = True
        viewer._model_render_size = (1280, 720)
        try:
            import numpy as np
            with patch.object(viewer, "makeCurrent"), \
                 patch.object(viewer, "doneCurrent"), \
                 patch.object(viewer, "update"), \
                 patch.object(viewer, "_render_size", return_value=(1280, 720)), \
                 patch.object(viewer, "_read_fbo",
                              return_value=np.zeros((12, 16, 4), dtype=np.uint8)), \
                 patch("as_live2d.viewer.GL.glBindFramebuffer"), \
                 patch("as_live2d.viewer.GL.glViewport"):
                frame = viewer.capture_rgba(16, 12)
                self.assertEqual(frame.shape, (12, 16, 4))
                self.assertEqual(viewer.model.Resize.call_args_list[-2].args,
                                 (16, 12))
                self.assertEqual(viewer.model.Resize.call_args_list[-1].args,
                                 (1280, 720))
                viewer.model.Rotate.assert_called_with(-30.0)
                self.assertEqual(viewer._model_render_size, (1280, 720))
        finally:
            viewer.model = None
            viewer._fbo = None
