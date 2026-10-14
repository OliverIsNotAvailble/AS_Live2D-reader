"""Direct native OpenGL preview; readback is strictly an export operation."""
from __future__ import annotations

import time
import math
from pathlib import Path

import live2d.v3 as live2d
import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader
from .background import fitted_background
from .rotation import rotation_fit_factor
from .part_visibility import read_motion_tracks, apply_parameter_tracks
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtOpenGL import QOpenGLFramebufferObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget


class Live2DViewer(QOpenGLWidget):
    model_loaded = Signal(str)
    model_failed = Signal(str)
    camera_changed = Signal(float, float, float)
    performance = Signal(float)
    playback_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.model_path: Path | None = None
        self._gl_ready = False
        self._pending_path: Path | None = None
        self._fbo = None
        self._preview_rot_fbo = None
        self._export_rot_fbo = None
        self._rot_program = 0
        self._rot_vao = 0
        self.rotation_deg = 0.0
        self.fit_rotation = False
        self._closed = False
        # Background preview is a cached RGB texture, never a per-frame CPU capture.
        self._bg_mode = "transparent"
        self._bg_color = (35, 39, 42)
        self._bg_path = ""
        self._bg_canvas = (1280, 720)
        self._bg_pixels = None
        self._bg_dirty = False
        self._bg_failed = False
        self._bg_program = 0
        self._bg_vao = 0
        self._bg_texture = 0
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.drag_enabled = True
        self._drag_start = None
        self.playing = False
        self.repeat = True
        self.motion = None
        self._part_ids: dict[str, int] = {}
        self._param_ids: dict[str, int] = {}
        self._param_tracks = {}
        self._mapped_param_tracks = []
        self._has_eye_tracks = False
        self._manual_only = False
        self._part_overrides: dict[str, float] = {}
        self._part_tracks = {}
        self._motion_elapsed = 0.0
        self._motion_duration = 0.0
        self.standalone_parts = True
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
        self._closed = False
        self._preview_rot_fbo = None
        self._export_rot_fbo = None
        self._rot_program = 0
        self._rot_vao = 0
        self._bg_program = 0
        self._bg_vao = 0
        self._bg_texture = 0
        self._bg_dirty = self._bg_pixels is not None
        self._bg_failed = False
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
        self._part_tracks = {}
        self._motion_elapsed = 0.0
        self._motion_duration = 0.0
        self._part_ids = {}
        self._param_ids = {}
        self._param_tracks = {}
        self._mapped_param_tracks = []
        self._has_eye_tracks = False
        self._manual_only = False
        self._part_overrides = {}
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
            try:
                self._part_ids = {
                    part_id: i for i, part_id in enumerate(new_model.GetPartIds())
                }
            except Exception as exc:
                self._part_ids = {}
                print("[Live2D parts] Could not enumerate part IDs:", exc)
            try:
                self._param_ids = {
                    param_id: i for i, param_id in enumerate(new_model.GetParamIds())
                }
            except Exception as exc:
                self._param_ids = {}
                print("[Live2D parameters] Could not enumerate parameter IDs:", exc)
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
                self._part_ids = {}
                self._param_ids = {}
                self._param_tracks = {}
                self._mapped_param_tracks = []
                self._has_eye_tracks = False
                self._manual_only = False
                self._part_overrides = {}
                self._part_tracks = {}

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
            self._preview_rot_fbo = None
            self._export_rot_fbo = None
            self._release_rotation_gl()
            self._release_background_gl()
            self.doneCurrent()
        except Exception as exc:
            print("[OpenGL cleanup]", exc)

    def set_background(self, mode: str, color: tuple[int, int, int],
                       image_path: str, width: int, height: int,
                       *, force_reload: bool = False):
        """Update preview BG and its fitting; actual texture upload uses the GL thread."""
        mode = str(mode)
        if mode not in ("transparent", "color", "image"):
            raise ValueError(f"Unknown background mode: {mode}")
        canvas = (int(width), int(height))
        path = str(image_path or "")
        same_image = (mode == self._bg_mode and path == self._bg_path and
                      canvas == self._bg_canvas)
        if mode == "image" and (not same_image or force_reload or self._bg_pixels is None):
            # Match the encoder's ImageOps.fit crop but cap GPU preview texture size.
            pixels = fitted_background(path, *canvas, max_dimension=2048)
            self._bg_pixels = pixels
            self._bg_dirty = True
            self._bg_failed = False
        self._bg_mode = mode
        self._bg_color = tuple(int(x) for x in color[:3])
        self._bg_path = path
        self._bg_canvas = canvas
        self.update()

    def _release_background_gl(self):
        if self._bg_texture:
            GL.glDeleteTextures([self._bg_texture])
            self._bg_texture = 0
        if self._bg_vao:
            GL.glDeleteVertexArrays(1, [self._bg_vao])
            self._bg_vao = 0
        if self._bg_program:
            GL.glDeleteProgram(self._bg_program)
            self._bg_program = 0
        self._bg_dirty = self._bg_pixels is not None

    def _ensure_background_gl(self):
        if not self._bg_program:
            vertex = """
                #version 330
                out vec2 texCoord;
                void main() {
                    vec2 pos[4] = vec2[4](
                        vec2(-1.0, -1.0), vec2(1.0, -1.0),
                        vec2(-1.0, 1.0), vec2(1.0, 1.0));
                    vec2 xy = pos[gl_VertexID];
                    gl_Position = vec4(xy, 0.0, 1.0);
                    texCoord = (xy + 1.0) * 0.5;
                }
            """
            fragment = """
                #version 330
                uniform sampler2D imageTex;
                in vec2 texCoord;
                out vec4 outColor;
                void main() {
                    outColor = vec4(texture(imageTex, texCoord).rgb, 1.0);
                }
            """
            self._bg_program = compileProgram(
                compileShader(vertex, GL.GL_VERTEX_SHADER),
                compileShader(fragment, GL.GL_FRAGMENT_SHADER))
            self._bg_vao = int(GL.glGenVertexArrays(1))
        if not self._bg_texture:
            self._bg_texture = int(GL.glGenTextures(1))
            self._bg_dirty = True
        if self._bg_dirty and self._bg_pixels is not None:
            pixels = self._bg_pixels
            h, w, _ = pixels.shape
            # Pillow/NumPy start at the top row, GL texcoords at the bottom.
            flipped = np.ascontiguousarray(np.flipud(pixels))
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._bg_texture)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB8, w, h,
                            0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, flipped)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            self._bg_dirty = False

    def _draw_background_image(self):
        if self._bg_pixels is None or self._bg_failed:
            return
        try:
            self._ensure_background_gl()
            GL.glDisable(GL.GL_BLEND)
            GL.glUseProgram(self._bg_program)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._bg_texture)
            GL.glUniform1i(
                GL.glGetUniformLocation(self._bg_program, "imageTex"), 0)
            GL.glBindVertexArray(self._bg_vao)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        except Exception as exc:
            self._bg_failed = True
            print("[BG preview OpenGL]", exc)
        finally:
            GL.glBindVertexArray(0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glUseProgram(0)
            GL.glEnable(GL.GL_BLEND)

    def set_rotation(self, degrees: float, fit: bool = False):
        """Clockwise-positive rotation of the Live2D layer only.

        Keep native Cubism parameters, original motion files and background
        unchanged. The same GPU composition runs in preview and export.
        """
        degrees = float(degrees)
        if not math.isfinite(degrees):
            raise ValueError("Rotation must be a finite number of degrees")
        self.rotation_deg = max(-180.0, min(180.0, degrees))
        self.fit_rotation = bool(fit)
        self.update()

    def _release_rotation_gl(self):
        if self._rot_vao:
            GL.glDeleteVertexArrays(1, [self._rot_vao])
            self._rot_vao = 0
        if self._rot_program:
            GL.glDeleteProgram(self._rot_program)
            self._rot_program = 0

    def _rotation_fbo(self, width: int, height: int, *, export: bool):
        """Two independently cached FBOs avoid reallocating on every frame."""
        attribute = "_export_rot_fbo" if export else "_preview_rot_fbo"
        fbo = getattr(self, attribute)
        if fbo is None or fbo.width() != width or fbo.height() != height:
            fbo = QOpenGLFramebufferObject(
                width, height,
                QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            if not fbo.isValid():
                raise RuntimeError("Unable to allocate Live2D rotation framebuffer")
            setattr(self, attribute, fbo)
        return fbo

    def _render_model_to_rotation_fbo(self, width, height, *, export):
        fbo = self._rotation_fbo(width, height, export=export)
        fbo.bind()
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, int(fbo.handle()))
        GL.glViewport(0, 0, width, height)
        # Native Cubism draws into a transparent, premultiplied-alpha layer.
        # No GPU->CPU readback is needed for the interactive preview.
        self._draw_model((0.0, 0.0, 0.0, 0.0))
        return fbo

    def _ensure_rotation_shader(self):
        if self._rot_program:
            return
        vertex = """
            #version 330
            out vec2 texCoord;
            void main() {
                vec2 positions[4] = vec2[4](
                    vec2(-1., -1.), vec2(1., -1.),
                    vec2(-1., 1.), vec2(1., 1.));
                vec2 point = positions[gl_VertexID];
                gl_Position = vec4(point, 0., 1.);
                texCoord = point * .5 + .5;
            }
        """
        fragment = """
            #version 330
            uniform sampler2D modelTex;
            uniform vec2 canvasSize;
            uniform float angleRadians;
            uniform float fitFactor;
            in vec2 texCoord;
            out vec4 outColor;
            void main() {
                // Pixel-space rotation avoids distortions in wide/tall frames.
                // Inverse-sample CCW(angle) -> image appears clockwise(angle).
                vec2 pixel = (texCoord - vec2(.5)) * canvasSize;
                float c = cos(angleRadians);
                float s = sin(angleRadians);
                vec2 source = vec2(c * pixel.x - s * pixel.y,
                                   s * pixel.x + c * pixel.y) / fitFactor;
                vec2 uv = source / canvasSize + vec2(.5);
                if (any(lessThan(uv, vec2(0.))) ||
                    any(greaterThan(uv, vec2(1.)))) {
                    outColor = vec4(0.);
                } else {
                    outColor = texture(modelTex, uv);
                }
            }
        """
        self._rot_program = compileProgram(
            compileShader(vertex, GL.GL_VERTEX_SHADER),
            compileShader(fragment, GL.GL_FRAGMENT_SHADER))
        self._rot_vao = int(GL.glGenVertexArrays(1))

    def _draw_rotated_model(self, fbo, width, height):
        self._ensure_rotation_shader()
        factor = (rotation_fit_factor(width, height, self.rotation_deg)
                  if self.fit_rotation else 1.0)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFuncSeparate(
            GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA,
            GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glUseProgram(self._rot_program)
        try:
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, int(fbo.texture()))
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glUniform1i(
                GL.glGetUniformLocation(self._rot_program, "modelTex"), 0)
            GL.glUniform2f(
                GL.glGetUniformLocation(self._rot_program, "canvasSize"),
                float(width), float(height))
            GL.glUniform1f(
                GL.glGetUniformLocation(self._rot_program, "angleRadians"),
                math.radians(self.rotation_deg))
            GL.glUniform1f(
                GL.glGetUniformLocation(self._rot_program, "fitFactor"), factor)
            GL.glBindVertexArray(self._rot_vao)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        finally:
            GL.glBindVertexArray(0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glUseProgram(0)

    def _draw_model(self, rgba_background, *, preview=False, include_model=True):
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFuncSeparate(
            GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA,
            GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        live2d.clearBuffer(*(float(c) for c in rgba_background))
        if preview and self._bg_mode == "image":
            self._draw_background_image()
        if include_model and self.model is not None:
            self.model.Draw()

    def paintGL(self):
        pw, ph = self._render_size()
        rotation_active = self.model is not None and abs(self.rotation_deg) > 0.0001
        layer = None
        if rotation_active:
            layer = self._render_model_to_rotation_fbo(pw, ph, export=False)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
        GL.glViewport(0, 0, pw, ph)
        if self._bg_mode == "color":
            clear = tuple(c / 255.0 for c in self._bg_color) + (1.0,)
        else:
            clear = (0.13, 0.14, 0.16, 1.0)
        self._draw_model(
            clear, preview=True, include_model=not rotation_active)
        if layer is not None:
            self._draw_rotated_model(layer, pw, ph)
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
            try:
                self.advance(dt)
            except Exception as exc:
                # Prevent 60 full tracebacks/second on a broken runtime call.
                self.playing = False
                self.playback_failed.emit(str(exc))
                print(f"[Live2D playback stopped] {type(exc).__name__}: {exc}")
                return
        self.update()

    def get_part_ids(self) -> list[str]:
        return list(self._part_ids)

    def get_part_overrides(self) -> dict[str, float]:
        return dict(self._part_overrides)

    def set_part_override(self, part_id: str, opacity: float | None):
        """None = follow motion; 0 or 1 = override; never modifies Cubism source."""
        if part_id not in self._part_ids:
            return
        if opacity is None:
            previous = self._part_overrides.pop(part_id, None)
            if previous is not None and part_id not in self._part_tracks and self.model is not None:
                # No motion curve owns this part: return to the usual visible
                # state instead of leaving the previous forced 0 behind.
                self.model.SetPartOpacity(self._part_ids[part_id], 1.0)
        else:
            self._part_overrides[part_id] = max(0.0, min(1.0, float(opacity)))
        self._apply_part_opacities()
        self.update()

    def _reset_motion_parts(self):
        # Cubism exposes SetPartOpacity but no GetPartOpacity in live2d-py.
        # Transition clips from games can rely on prior script state; without
        # a predictable baseline, a missing head/arm might remain at 0 from
        # the previously selected clip. Independent export defaults to 1 for
        # all parts, then the current motion's hide/show tracks apply.
        # Users can disable standalone mode or override individual parts.
        if self.model is None or not self.standalone_parts:
            return
        for index in self._part_ids.values():
            self.model.SetPartOpacity(index, 1.0)

    def _load_part_tracks(self, motion_path: Path | None, duration: float = 0.0):
        self._motion_elapsed = 0.0
        self._motion_duration = float(duration or 0)
        self._part_tracks = {}
        self._param_tracks = {}
        self._mapped_param_tracks = []
        self._has_eye_tracks = False
        self._manual_only = False
        if motion_path is None:
            return
        try:
            self._param_tracks, self._part_tracks, interleaved = read_motion_tracks(
                motion_path)
            self._mapped_param_tracks = [
                (self._param_ids[param_id], track)
                for param_id, track in self._param_tracks.items()
                if param_id in self._param_ids
            ]
            self._has_eye_tracks = any(
                p in self._param_tracks for p in ("ParamEyeLOpen", "ParamEyeROpen"))
            print(f"[Live2D motion] {Path(motion_path).name}: "
                  f"{len(self._mapped_param_tracks)}/{len(self._param_tracks)} "
                  "Parameter curves matched to MOC3; "
                  f"{len(self._part_tracks)} PartOpacity curves.")
            self._manual_only = interleaved
            if interleaved:
                print("[Live2D] Interleaved curves in "
                      f"{Path(motion_path).name}: using deterministic direct "
                      "Parameter/PartOpacity playback; native fixed-motion "
                      "group disabled.")
            if self._param_tracks and not self._mapped_param_tracks:
                print("[Live2D WARNING] No motion parameters match model; "
                      "check that this motion belongs to the loaded MOC3.")
        except Exception as exc:
            print(f"[Live2D] Cannot read opacity tracks from {motion_path}: {exc}")

    def _apply_part_opacities(self):
        if self.model is None or not self._part_ids:
            return
        # The native Cubism SDK may skip PartOpacity curves in interleaved
        # motion files. Apply those independently, after UpdatePose, so clothes
        # / head / limbs mutually exclusive variants do not all stay visible.
        for part_id, track in self._part_tracks.items():
            if part_id in self._part_overrides:
                continue
            index = self._part_ids.get(part_id)
            if index is not None:
                self.model.SetPartOpacity(index, max(0.0, min(1.0,
                    track.value_at(self._motion_elapsed))))
        for part_id, opacity in self._part_overrides.items():
            index = self._part_ids.get(part_id)
            if index is not None:
                self.model.SetPartOpacity(index, opacity)

    def advance(self, dt: float):
        if self.model is None:
            return
        internal = self.model._model
        dt = max(0.0, float(dt))
        native_active = False

        if not self._manual_only:
            if (self.motion is not None and internal.IsMotionFinished()
                    and self.repeat):
                self.model.StartMotion(
                    self.motion[0], self.motion[1], live2d.MotionPriority.FORCE)
            native_active = not internal.IsMotionFinished()

        internal.LoadParameters()
        if native_active:
            # Native UpdateMotion returns None in live2d-py 0.7.0.4,
            # regardless of whether the model was animated.
            internal.UpdateMotion(dt)
        internal.SaveParameters()

        self._motion_elapsed += dt
        if self._motion_duration > 0:
            if self.repeat:
                self._motion_elapsed %= self._motion_duration
            else:
                self._motion_elapsed = min(
                    self._motion_elapsed, self._motion_duration)

        if self.auto_blink and not self._has_eye_tracks:
            internal.UpdateBlink(dt)
        internal.UpdateExpression(dt)
        internal.UpdateDrag(dt)

        # The low-level PyModel owns SetParamByIndex, NOT the public
        # LAppModel wrapper. Apply every authored curve before physics.
        apply_parameter_tracks(
            internal, self._mapped_param_tracks, self._motion_elapsed)

        if self.auto_breath:
            internal.UpdateBreath(dt)
        if self.auto_physics:
            internal.UpdatePhysics(dt)
        internal.UpdatePose(dt)
        self._apply_part_opacities()
        self.update()

    def _start_motion(self, group: str, index: int, motion_path: Path | None,
                      duration: float, *, repeat: bool):
        self._load_part_tracks(motion_path, duration)
        self.repeat = repeat
        if self._manual_only:
            # Interleaved Unity exports cannot safely be handed to the
            # runtime's dynamic motion group (__ASREADER_FIXED__ would
            # repeatedly fail). Direct interpolation drives the full rig.
            self.motion = None
        else:
            self.model.StartMotion(group, index, live2d.MotionPriority.FORCE)
            self.motion = (group, index)
        self._apply_part_opacities()

    def play_motion(self, group: str, index: int, *, repeat: bool = True,
                    motion_path: Path | None = None, duration: float = 0.0):
        if self.model is None:
            raise RuntimeError("Open a model first")
        self.model.StopAllMotions()
        self.model.ResetParameters()
        self.model.ResetPose()
        self._reset_motion_parts()
        self._set_model_camera()
        self._start_motion(group, index, motion_path, duration, repeat=repeat)
        self.playing = True
        self._previous_tick = time.monotonic()

    def reset_for_export(self, group: str, index: int, *,
                         motion_path: Path | None = None, duration: float = 0.0):
        if self.model is None:
            raise RuntimeError("No model loaded")
        self.playing = False
        self.model.StopAllMotions()
        self.model.ResetParameters()
        self.model.ResetPose()
        if hasattr(self.model, "ResetExpression"):
            self.model.ResetExpression()
        self._reset_motion_parts()
        self._start_motion(group, index, motion_path, duration, repeat=False)

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
        rotating = abs(self.rotation_deg) > 0.0001
        self._draw_model(background, include_model=not rotating)
        if rotating:
            self._draw_rotated_model(self._export_rot_fbo, width, height)
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
            if abs(self.rotation_deg) > 0.0001:
                self._render_model_to_rotation_fbo(
                    width, height, export=True)
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
