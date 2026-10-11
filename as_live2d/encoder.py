"""Bounded background encoder: Qt/GL stays on the UI thread."""
from __future__ import annotations

from pathlib import Path
import os
import queue
import shutil
import subprocess
import threading

import numpy as np
from PIL import Image
from .background import fitted_background
from PySide6.QtCore import QThread, Signal


def find_ffmpeg(project_root: Path) -> str:
    local = project_root / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if local.is_file():
        return str(local)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError(
        "FFmpeg not found. Add it to PATH or tools/ffmpeg/bin/ffmpeg.exe")


class EncodeWorker(QThread):
    completed = Signal(str)
    error = Signal(str)
    aborted = Signal()

    def __init__(self, *, ffmpeg: str | None, output: Path, stem: str,
                 width: int, height: int, fps: float, formats: tuple[str, ...],
                 background: str = "transparent", color=(35, 39, 42),
                 image_path: str = "", webp_quality: int = 95, parent=None):
        super().__init__(parent)
        self.ffmpeg = ffmpeg
        self.output = Path(output)
        self.stem = stem
        self.width = width
        self.height = height
        self.fps = fps
        self.formats = formats
        self.background = background
        self.color = tuple(color)
        self.image_path = image_path
        self.webp_quality = webp_quality
        self.frames = queue.Queue(maxsize=3)
        self.finish_requested = threading.Event()
        self.cancel_requested = threading.Event()
        self._processes = []
        self._pending = []
        self._png_pending = None

    def offer(self, frame: np.ndarray) -> bool:
        if self.cancel_requested.is_set() or self.finish_requested.is_set():
            return False
        try:
            self.frames.put_nowait(np.ascontiguousarray(frame).tobytes())
            return True
        except queue.Full:
            return False

    def finish(self):
        self.finish_requested.set()

    def stop(self):
        self.cancel_requested.set()

    def _background_rgb(self):
        if self.background == "image":
            # Same fit/crop algorithm as the GPU preview, at final resolution.
            return fitted_background(self.image_path, self.width, self.height)
        return np.asarray(self.color[:3], dtype=np.uint8)

    def _composite(self, frame, background):
        alpha = frame[..., 3:4].astype(np.float32) / 255.0
        rgb = frame[..., :3].astype(np.float32)
        return np.clip(np.rint(rgb * alpha + background * (1 - alpha)),
                       0, 255).astype(np.uint8)

    def _start_ffmpeg(self, fmt):
        if self.ffmpeg is None:
            raise RuntimeError("FFmpeg required for MP4/WebP export")
        temporary = self.output / f"{self.stem}.part.{fmt}"
        final = self.output / f"{self.stem}.{fmt}"
        temporary.unlink(missing_ok=True)
        common = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                  "-f", "rawvideo", "-pix_fmt",
                  "rgba" if fmt == "webp" else "rgb24",
                  "-s", f"{self.width}x{self.height}",
                  "-r", str(self.fps), "-i", "pipe:0", "-an"]
        if fmt == "mp4":
            common += ["-c:v", "libx264", "-preset", "medium",
                       "-crf", "20", "-pix_fmt", "yuv420p", str(temporary)]
        elif fmt == "webp":
            common += ["-c:v", "libwebp_anim", "-quality",
                       str(self.webp_quality), "-loop", "0", str(temporary)]
        else:
            raise ValueError("Unexpected encoder format: " + fmt)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(common, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                                creationflags=flags)
        self._processes.append((fmt, proc))
        self._pending.append((temporary, final))

    def run(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            background = self._background_rgb()
            for fmt in self.formats:
                if fmt in ("mp4", "webp"):
                    self._start_ffmpeg(fmt)
                elif fmt == "png":
                    self._png_pending = self.output / (self.stem + "_frames.part")
                    if self._png_pending.exists():
                        shutil.rmtree(self._png_pending)
                    self._png_pending.mkdir()
                else:
                    raise ValueError("Unknown output format: " + fmt)

            index = 0
            while not self.cancel_requested.is_set():
                try:
                    payload = self.frames.get(timeout=0.08)
                except queue.Empty:
                    if self.finish_requested.is_set():
                        break
                    continue
                rgba = np.frombuffer(payload, dtype=np.uint8).reshape(
                    self.height, self.width, 4)
                is_transparent = self.background == "transparent"
                rgb = None
                if not is_transparent or "mp4" in self.formats:
                    rgb = self._composite(rgba, background)
                for fmt, proc in self._processes:
                    if self.cancel_requested.is_set():
                        break
                    if proc.poll() is not None:
                        err = proc.stderr.read().decode("utf-8", "replace")
                        raise RuntimeError(f"FFmpeg {fmt} exited early: {err}")
                    if fmt == "mp4":
                        proc.stdin.write(rgb.tobytes())
                    else:
                        if is_transparent:
                            proc.stdin.write(payload)
                        else:
                            opaque = np.empty_like(rgba)
                            opaque[..., :3] = rgb
                            opaque[..., 3] = 255
                            proc.stdin.write(opaque.tobytes())
                if self._png_pending is not None and not self.cancel_requested.is_set():
                    if is_transparent:
                        Image.fromarray(rgba.copy(), "RGBA").save(
                            self._png_pending / f"frame_{index:06d}.png")
                    else:
                        Image.fromarray(rgb, "RGB").save(
                            self._png_pending / f"frame_{index:06d}.png")
                index += 1

            if self.cancel_requested.is_set():
                self.aborted.emit()
                return

            for fmt, proc in self._processes:
                proc.stdin.close()
                err = proc.stderr.read().decode("utf-8", "replace")
                code = proc.wait()
                if code != 0:
                    raise RuntimeError(f"FFmpeg {fmt} failed ({code}): {err}")

            for temporary, final in self._pending:
                if not temporary.is_file() or temporary.stat().st_size == 0:
                    raise RuntimeError(f"Encoder produced no file: {temporary}")
            for temporary, final in self._pending:
                os.replace(temporary, final)
            if self._png_pending is not None:
                final_dir = self.output / (self.stem + "_frames")
                if final_dir.exists():
                    shutil.rmtree(final_dir)
                self._png_pending.rename(final_dir)
                self._png_pending = None
            self._pending.clear()
            self.completed.emit(f"Encoded {index} frame(s): {self.stem}")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            for fmt, proc in self._processes:
                if proc.poll() is None:
                    proc.kill()
                if proc.stdin:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                if proc.stderr:
                    proc.stderr.close()
                proc.wait()
            for temporary, _ in self._pending:
                temporary.unlink(missing_ok=True)
            if self._png_pending is not None and self._png_pending.exists():
                shutil.rmtree(self._png_pending, ignore_errors=True)
