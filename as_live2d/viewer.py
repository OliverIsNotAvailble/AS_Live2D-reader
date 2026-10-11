"""Direct native OpenGL preview; readback is strictly an export operation."""
from __future__ import annotations

import time
from pathlib import Path

import live2d.v3 as live2d
import numpy as np
from OpenGL import GL
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtOpenGL import QOpenGLFramebufferObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget


class Live2DViewer(QOpenGLWidget):
    model_loaded = Signal(str)
    model_failed = Signal(str)
    camera_changed = Signal(float, float, float)
    performance = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.model_path: Path | None = None
        self._gl_ready = False
        self._pending_path: Path | None = None
        self._fbo = None
        self._closed = False
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.drag_enabled = True
        self._drag_start = None
        self.playing = False
        self.repeat = True
        self.motion = None
        self.auto_blink = True
        self.auto_breath = False
        self.auto_physics = True
        self._previous_tick = time.monotonic()
        self._last_fps_emit = time.monotonic()
        self._paint_frames = 0
        self.setMinimumSize(240, 180)
        self.setMouseTracking(True)
        self.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.NoPartialUpdate)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def initializeGL(self):
        live2d.glInit()
        self._gl_ready = True
        self.context().aboutToBeDestroyed.connect(self.cleanup)
        if self._pending_path:
            pending = self._pending_path
            self._pending_path = None
            QTimer.singleShot(0, lambda: self.load_model(pending))

    def _render_size(self):
        ratio = self.devicePixelRatioF()
        return max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))

    def resizeGL(self, width, height):
        if self.model is not None:
            pw, ph = self._render_size()
            self.model.Resize(pw, ph)
            self._set_model_camera()

    def _set_model_camera(self):
        if self.model is not None:
            self.model.SetScale(float(self.scale))
            self.model.SetOffset(float(self.offset_x), float(self.offset_y))

    def load_model(self, path: Path):
        """Reuse this widget/GL context: NEVER replace/delete a splitter widget."""
        path = Path(path).resolve()
        if not self._gl_ready:
            self._pending_path = path
            return
        self.playing = False
        self.motion = None
        self.makeCurrent()
        try:
            self._release_model()
            live2d.glInit()
            new_model = live2d.LAppModel()
            try:
                new_model.LoadModelJson(str(path))
                width, height = self._render_size()
                new_model.Resize(width, height)
                new_model.SetScale(float(self.scale))
                new_model.SetOffset(float(self.offset_x), float(self.offset_y))
                new_model.SetAutoBlinkEnable(self.auto_blink)
                new_model.SetAutoBreathEnable(self.auto_breath)
            except Exception:
                try:
                    new_model.DestroyRenderer()
                except Exception:
                    pass
                raise
            self.model = new_model
            self.model_path = path
            self._previous_tick = time.monotonic()
            self.model_loaded.emit(path.name)
        except Exception as exc:
            self.model = None
            self.model_path = None
            self.model_failed.emit(str(exc))
        finally:
            self.doneCurrent()
            self.update()

    def _release_model(self):
        if self.model is not None:
            try:
                self.model.StopAllMotions()
                self.model.DestroyRenderer()
            except Exception as exc:
                print("[Live2D cleanup]", exc)
            finally:
                self.model = None
                self.model_path = None

    def cleanup(self):
        if self._closed:
            return
        self.timer.stop()
        self._closed = True
        if self.context() is None or not self._gl_ready:
            return
        try:
            self.makeCurrent()
            self._release_model()
            self._fbo = None
            self.doneCurrent()
        except Exception as exc:
            print("[OpenGL cleanup]", exc)

    def _draw_model(self, rgba_background):
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFuncSeparate(
            GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA,
            GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        live2d.clearBuffer(*(float(c) for c in rgba_background))
        if self.model is not None:
            self.model.Draw()

    def paintGL(self):
        pw, ph = self._render_size()
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
        GL.glViewport(0, 0, pw, ph)
        self._draw_model((0.13, 0.14, 0.16, 1.0))
        self._paint_frames += 1
        now = time.monotonic()
        if now - self._last_fps_emit >= 1.0:
            self.performance.emit(self._paint_frames / (now - self._last_fps_emit))
            self._paint_frames = 0
            self._last_fps_emit = now

    def _tick(self):
        if self.model is None:
            return
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self._previous_tick))
        self._previous_tick = now
        if self.playing:
            self.advance(dt)
        self.update()

    def advance(self, dt: float):
        if self.model is None:
            return
        internal = self.model._model
        internal.LoadParameters()
        if self.motion is not None and internal.IsMotionFinished() and self.repeat:
            self.model.StartMotion(self.motion[0], self.motion[1], live2d.MotionPriority.FORCE)
        motion_updated = False
        if not internal.IsMotionFinished():
            motion_updated = internal.UpdateMotion(float(dt))
        internal.SaveParameters()
        if not motion_updated and self.auto_blink:
            internal.UpdateBlink(float(dt))
        internal.UpdateExpression(float(dt))
        internal.UpdateDrag(float(dt))
        if self.auto_breath:
            internal.UpdateBreath(float(dt))
        if self.auto_physics:
            internal.UpdatePhysics(float(dt))
        internal.UpdatePose(float(dt))
        self.update()

    def play_motion(self, group: str, index: int, *, repeat: bool = True):
        if self.model is None:
            raise RuntimeError("Open a model first")
        self.model.StopAllMotions()
        self.model.ResetParameters()
        self.model.ResetPose()
        self._set_model_camera()
        self.model.StartMotion(group, index, live2d.MotionPriority.FORCE)
        self.motion = (group, index)
        self.repeat = repeat
        self.playing = True
        self._previous_tick = time.monotonic()

    def reset_for_export(self, group: str, index: int):
        if self.model is None:
            raise RuntimeError("No model loaded")
        self.playing = False
        self.model.StopAllMotions()
        self.model.ResetParameters()
        self.model.ResetPose()
        if hasattr(self.model, "ResetExpression"):
            self.model.ResetExpression()
        self.model.StartMotion(group, index, live2d.MotionPriority.FORCE)
        self.motion = (group, index)

    def set_camera(self, scale: float, x: float, y: float):
        self.scale = max(0.01, min(15.0, float(scale)))
        self.offset_x = max(-10, min(10, float(x)))
        self.offset_y = max(-10, min(10, float(y)))
        self._set_model_camera()
        self.camera_changed.emit(self.scale, self.offset_x, self.offset_y)
        self.update()

    def mousePressEvent(self, event):
        if self.drag_enabled and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = (event.position(), self.offset_x, self.offset_y)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            origin, x, y = self._drag_start
            pixels = max(1, min(self.width(), self.height()))
            dx = 2 * (event.position().x() - origin.x()) / pixels
            dy = 2 * (origin.y() - event.position().y()) / pixels
            self.set_camera(self.scale, x + dx, y + dy)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if not self.drag_enabled:
            return super().wheelEvent(event)
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        before = self.scale
        after = max(0.01, min(15.0, before * 1.12 ** steps))
        pixels = max(1, min(self.width(), self.height()))
        px = 2 * (event.position().x() - self.width() / 2) / pixels
        py = 2 * (self.height() / 2 - event.position().y()) / pixels
        factor = after / before
        self.set_camera(after, px - (px - self.offset_x) * factor,
                        py - (py - self.offset_y) * factor)
        event.accept()

    def _read_fbo(self, width, height, background):
        self._fbo.bind()
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, int(self._fbo.handle()))
        GL.glViewport(0, 0, width, height)
        self._draw_model(background)
        GL.glReadBuffer(GL.GL_COLOR_ATTACHMENT0)
        GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
        pixels = GL.glReadPixels(0, 0, width, height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        return np.flipud(np.frombuffer(pixels, dtype=np.uint8)
                         .reshape(height, width, 4)).copy()

    def capture_rgba(self, width: int, height: int) -> np.ndarray:
        """Slow but accurate two-pass alpha capture; never called from paintGL."""
        if self.model is None:
            raise RuntimeError("No model loaded for capture")
        self.makeCurrent()
        try:
            if (self._fbo is None or self._fbo.width() != width or
                    self._fbo.height() != height):
                self._fbo = None
                self._fbo = QOpenGLFramebufferObject(
                    width, height,
                    QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            if not self._fbo.isValid():
                raise RuntimeError("Unable to create GPU export framebuffer")
            self.model.Resize(width, height)
            self._set_model_camera()
            black = self._read_fbo(width, height, (0, 0, 0, 1))
            white = self._read_fbo(width, height, (1, 1, 1, 1))
            b = black[..., :3].astype(np.float32)
            w = white[..., :3].astype(np.float32)
            alpha = np.clip(255.0 - np.mean(w - b, axis=2), 0, 255)
            rgb = np.zeros_like(b, dtype=np.float32)
            visible = alpha > 0.5
            rgb[visible] = b[visible] * (255.0 / alpha[visible, None])
            out = np.empty((height, width, 4), dtype=np.uint8)
            out[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
            out[..., 3] = np.rint(alpha).astype(np.uint8)
            out[out[..., 3] == 0, :3] = 0
            return out
        finally:
            if self._fbo is not None:
                self._fbo.release()
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            pw, ph = self._render_size()
            GL.glViewport(0, 0, pw, ph)
            if self.model is not None:
                self.model.Resize(pw, ph)
                self._set_model_camera()
            self.doneCurrent()
            self.update()
