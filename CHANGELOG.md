# AS Live2D Reader — CHANGELOG

## Maintenance rule

Every code modification must update this CHANGELOG in the **same commit**. Development changes go directly to `main`; a separate final-version branch is created only when a whole version series is closed. Include concrete changes, changed files, verification and known issues. The README is set up once and does not need editing for routine updates.

## 0.1.2 — 2026-10-11 — Background image in real-time preview

- Fixed report: selecting Background image and a PNG (e.g. `char0200_hsceneBg.png`) previously did nothing in the viewer: the background was used only by the export worker and `paintGL` always cleared to dark gray. Preview now draws the chosen image in the OpenGL context behind the animated Cubism model.
- GPU caching: compile a small OpenGL 3.3 textured-quad shader lazily and upload the fitted background only when the file, mode or export aspect changes. Normal animation playback stays entirely on the GPU, with no screenshot/readback/NumPy blending per frame.
- `Transparent` retains the neutral preview backdrop; `Solid color` now displays the selected RGB color in preview. Image mode renders the selected background filling the export frame (center-cropped with `ImageOps.fit`), stationary while pan/zoom affects the model.
- Refactored preview and encoder to share the exact same image fit/crop utility. Preview caps BG texture dimensions at 2048 pixels for performance; export composites the source image at full output resolution. Changes to width/height re-fit both layouts consistently.
- UI now immediately refreshes BG after selecting an image, changing the mode/color or restoring a per-model profile. Added **Reload background image** to refresh a PNG modified externally, without reopening the Live2D model.
- Background GPU resources are freed along with the OpenGL context; loading a corrupt/missing background reports an error and falls back to a neutral preview without interrupting animation. The export path retains the original RGB alpha compositing logic.
- Tests: new `test_background.py` checks exact size, center crop, preview/export agreement, dimension cap and missing file. CI installs dependencies before running model and BG tests.
- Version title/package updated to v0.1.2, with direct changes to `main`. README untouched.
- Files: `as_live2d/background.py` (new), `as_live2d/viewer.py`, `as_live2d/encoder.py`, `as_live2d/window.py`, `as_live2d/__init__.py`, `tests/test_background.py` (new), `.github/workflows/validate.yml`, this changelog.
- Verification: Windows Python 3.10 CI **passed** (source compilation, manifest and image-crop tests, package installation and Qt construction): https://github.com/OliverIsNotAvailble/AS_Live2D-reader/actions/runs/38148410965. The runner does **not** validate a real OpenGL/Cubism model drawing frame; user visual confirmation and a real MP4/WebP export remain required.

## 0.1.1 — 2026-10-10 — Export lifecycle hardening

- Prevent resolution, background, motion-selection or framing controls from changing while an export is active. Disable mouse camera motion during export and restore user controls when the encoder finishes or fails.
- Parent the active EncodeWorker QThread to the main window to ensure Qt owns it until its finished/deleteLater lifecycle; avoids destruction of a still-running QThread when the next motion starts.
- Stop pending bounded-queue capture retries immediately after cancel is requested instead of incorrectly turning a normal cancellation into an export error.
- Reset the renderer cleanup guard whenever Qt initializes a new OpenGL context.
- Program title updated to v0.1.1. Initial README intentionally unchanged.
- Files: `as_live2d/window.py`, `as_live2d/viewer.py`, `as_live2d/__init__.py`, `CHANGELOG.md`.
- Verification: Windows Python 3.10 source compilation and model/manifest tests **passed**: https://github.com/OliverIsNotAvailble/AS_Live2D-reader/actions/runs/38106534653. Hardware GPU/Cubism integration still requires real-model testing.
- Added CI runtime smoke that installs `requirements.txt`, imports native `live2d.v3`, and constructs/closes the PySide6 desktop window with the offscreen Qt platform. It checks Windows dependencies/UI wiring but not actual GPU rendering. **Passed** on Windows Python 3.10: https://github.com/OliverIsNotAvailble/AS_Live2D-reader/actions/runs/38106602187. This checks package installation and Qt window construction, not live GPU rendering. Changed `.github/workflows/validate.yml` and this changelog.

## 0.1.0 — 2026-10-10 — Initial standalone Live2D Reader

- New standalone Python / PySide6 / live2d-py application in `AS_Live2D-reader`; no changes to FBX Reader or AS19 repositories.
- **Open multiple models in one window:** reuses the same OpenGL widget/context and destroys the previous Cubism renderer before creating the next; removes the old Qt splitter `None.deleteLater` failure path. Failed model loading is surfaced as an error without keeping a misleading old model selected.
- **Native GPU preview:** native Cubism draw straight to QOpenGLWidget at an approximately 16 ms timer interval, with separate motion update and draw. Normal preview does **not** read GPU pixels, perform black/white alpha passes, or convert every frame to a QImage/NumPy frame. Provides loop, pause/play, wheel zoom, pan, camera reset and live FPS indicator.
- **Independent export resolution:** QOpenGLFramebufferObject with two-pass black/white alpha reconstruction only during export; restores the preview's framebuffer, viewport and model resolution afterward.
- **Per-model validation:** parses model3.json FileReferences; resolves MOC, textures, motions, physics, expressions and other declared files; Files tab displays missing references. Models with zero motions can be viewed. Model manifests are never modified.
- **Export engine:** select motions and export MP4 (H.264), animated WebP with alpha, PNG sequences or MP4+WebP. Supports motion FPS or override, output resolution, color/image/transparent background and WebP quality. FFmpeg or PNG encoding runs on a bounded-queue QThread, avoiding writing video pipes on the GUI thread. Temporary outputs are committed only after success and removed on error/cancel.
- **Profile:** per-model `*.model3.json.as-reader.json` with camera, output format, background and selected motion settings; saved atomically, without touching Cubism source files.
- Initial README, requirements, `main.py`, modules under `as_live2d`, Python model-manifest tests and GitHub Actions CI.
- Files: `README.md`, `CHANGELOG.md`, `.gitignore`, `requirements.txt`, `main.py`, `as_live2d/__init__.py`, `as_live2d/model.py`, `as_live2d/viewer.py`, `as_live2d/encoder.py`, `as_live2d/window.py`, `tests/test_model.py`, `.github/workflows/validate.yml`.
- Verification: initial Windows Python 3.10 source compilation and manifest tests **passed**: https://github.com/OliverIsNotAvailble/AS_Live2D-reader/actions/runs/38106421076. Native Live2D GPU rendering/export still requires actual Windows model testing; 60 FPS is a target, not a guarantee.
- Current limits: no live editing of Cubism rig geometry or part opacity; Expressions panel lists referenced expression files, but does not yet modify active expression playback. FFmpeg is a separate installation. No proprietary Cubism Core binary distributed.
