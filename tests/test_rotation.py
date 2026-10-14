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

    def test_gpu_preview_route_draws_background_without_rotating_it(self):
        viewer = self.window.viewer
        viewer.model = object()
        viewer.rotation_deg = 30
        with patch.object(viewer, "_render_size", return_value=(400, 250)), \
             patch.object(viewer, "_render_model_to_rotation_fbo",
                          return_value="model-layer") as render_layer, \
             patch.object(viewer, "_draw_model") as draw_scene, \
             patch.object(viewer, "_draw_rotated_model") as draw_rotated, \
             patch("as_live2d.viewer.GL.glBindFramebuffer"), \
             patch("as_live2d.viewer.GL.glViewport"):
            viewer.paintGL()
            render_layer.assert_called_once_with(400, 250, export=False)
            self.assertEqual(draw_scene.call_args.kwargs["include_model"], False)
            self.assertTrue(draw_scene.call_args.kwargs["preview"])
            draw_rotated.assert_called_once_with("model-layer", 400, 250)
        viewer.model = None

    def test_export_readback_uses_same_rotation_as_preview(self):
        viewer = self.window.viewer
        viewer.rotation_deg = 30
        viewer._export_rot_fbo = "export-model-layer"
        viewer._fbo = Mock()
        viewer._fbo.handle.return_value = 11
        with patch.object(viewer, "_draw_model") as render_scene, \
             patch.object(viewer, "_draw_rotated_model") as draw_rotated, \
             patch("as_live2d.viewer.GL.glBindFramebuffer"), \
             patch("as_live2d.viewer.GL.glViewport"), \
             patch("as_live2d.viewer.GL.glReadBuffer"), \
             patch("as_live2d.viewer.GL.glPixelStorei"), \
             patch("as_live2d.viewer.GL.glReadPixels",
                   return_value=bytes([0] * (8 * 6 * 4))):
            frame = viewer._read_fbo(8, 6, (0, 0, 0, 1))
            self.assertEqual(frame.shape, (6, 8, 4))
            self.assertFalse(render_scene.call_args.kwargs["include_model"])
            draw_rotated.assert_called_once_with("export-model-layer", 8, 6)
        viewer._fbo = None
        viewer._export_rot_fbo = None

    def test_unrotated_preview_skips_offscreen_framebuffer(self):
        viewer = self.window.viewer
        viewer.model = object()
        viewer.rotation_deg = 0.0
        with patch.object(viewer, "_render_size", return_value=(400, 250)), \
             patch.object(viewer, "_render_model_to_rotation_fbo") as layer, \
             patch.object(viewer, "_draw_model") as paint, \
             patch("as_live2d.viewer.GL.glBindFramebuffer"), \
             patch("as_live2d.viewer.GL.glViewport"):
            viewer.paintGL()
            layer.assert_not_called()
            self.assertTrue(paint.call_args.kwargs["include_model"])
        viewer.model = None
