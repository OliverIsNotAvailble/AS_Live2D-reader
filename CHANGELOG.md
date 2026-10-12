# AS Live2D Reader — CHANGELOG

## Maintenance rule

Every code modification must update this CHANGELOG in the **same commit**. Development changes go directly to `main`; a separate final-version branch is created only when a whole version series is closed. Include concrete changes, changed files, verification and known issues. The README is set up once and does not need editing for routine updates.

## 0.1.4 — 2026-10-12 — Native motion repair and standalone part baseline

- Reproduced the cause from the attached `ahcy1_I_clothes_turnOff.motion3.json`: the clip hides `head_1` throughout its nine seconds but never sets `head_2` visible. If a preceding clip leaves that alternative head hidden, a standalone export renders a headless figure. The transition is state-dependent; this is not a missing texture or MOC3 defect.
- Confirmed all three supplied idle/transition motions contain interleaved Target groups (Parameter → PartOpacity → Parameter → PartOpacity). The Native Cubism motion evaluator traverses these target classes in contiguous order and can fail to apply *both* later Parameter and PartOpacity tracks. The previous post-pose PartOpacity fix covered visibility only; skipped native Parameter curves could still deform the model incorrectly.
- Added `motion_runtime.py` to create on-demand normalized temporary copies of interleaved `.motion3.json` files. Stable-sorts curves into Model → Parameter → PartOpacity while preserving every individual curve, segment, Meta value and UserData. Native runtime loads these corrected files via `LAppModel.LoadExtraMotion`, and both preview and offscreen export use the corrected native motion. It caches each motion and cleans temporary files when switching models/closing. Source Unity/game files are **never modified**.
- Added **Independent motions (reset Parts)** toggle, enabled by default. At the beginning of each preview/export clip it sets part visibility to a known 100% baseline, then applies the active motion's own PartOpacity curves (and any manually saved overrides). This avoids invisible parts leaking from the prior clip. Turn it off when intentionally chaining transitions that depend on the preceding animation's state; because the runtime doesn't expose the original MOC part defaults, baseline 100% may expose unspecified alternative parts in some rigs, adjustable using the Parts tab.
- Persists the new toggle in each model's AS Reader profile under `standalone_parts`. Existing profiles default to independent mode.
- Added focused tests for target sorting, exact preservation of curves/Meta/UserData, source-file immutability and standalone PartOpacity tracks. No game assets were added to this public repository.
- Program title and Python package now 0.1.4. Files: `as_live2d/motion_runtime.py` (new), `as_live2d/viewer.py`, `as_live2d/window.py`, `as_live2d/__init__.py`, `tests/test_motion_runtime.py` (new), this changelog. README untouched; direct changes to main.
- Verification: Windows Python 3.10 CI pending; interactive testing with original user model and MP4/WebP output still required.

## 0.1.3 — 2026-10-12 — PartOpacity motion support and alternate mesh visibility

- Diagnosed the uploaded `Char100_Pose3.moc3`, `Char100_Pose3.model3.json` and the two `ahcy1_I_idle_*.motion3.json` examples **without uploading these game files to this public repository**. The MOC3 contains both `head_1` and `head_2` parts. Both idle motions explicitly set `head_1` PartOpacity to 0, but their curve ordering is mixed: 20 Parameters, one PartOpacity, 64 more Parameters, then 14/18 more PartOpacity curves. The Native SDK expects a Model → Parameter → PartOpacity sequence and may not evaluate the later tracks.
- Added pure-Python motion `PartOpacity` evaluation independent of Native SDK curve iteration. Supports linear, Bézier, stepped and inverse-stepped Cubism segments. Curves are parsed once per selected motion, not per render frame.
- `Live2DViewer` now enumerates Cubism part IDs after loading a model and applies the currently active motion's part opacities *after* the native motion/physics/pose update on each preview/export frame. This hides intentional alternate heads, arms, legs and clothing when their motion contains explicit hide tracks. Reports interleaved motion targets to the console. Original `.moc3`, `.model3.json`, PNG and `.motion3.json` files remain untouched.
- Added **Parts** tab with searchable part IDs and tri-state visibility controls: Auto (motion controlled), Show and Hide. Manual visibility overrides win over motion curves and are saved in the existing model-specific profile under `part_overrides`. Reset restores motion-controlled state, and switching models resets transient overrides before applying that model's profile.
- Motions and exports pass their original motion JSON path and duration to the viewer; the same opacity handling applies to preview and offscreen frames. Export is still processed in the encoder worker.
- Note: mixed ordering can also prevent the native SDK from applying **Parameter** curves after the first PartOpacity. This version safeguards part visibility; reordering `Model`, `Parameter`, `PartOpacity` in the actual motion files remains recommended for complete motion fidelity. This change does not silently rewrite game files or model rigs.
- Added unit tests for the four segment types, malformed data and detection of interleaved motion targets. Version title/package updated to 0.1.3.
- Files: `as_live2d/part_visibility.py` (new), `as_live2d/viewer.py`, `as_live2d/window.py`, `as_live2d/__init__.py`, `tests/test_part_visibility.py` (new) and this `CHANGELOG.md`. README untouched. Direct commit to `main`, no new branch.
- Verification: Windows Python 3.10 CI **passed** (syntax, model manifest, BG and all PartOpacity curve/evaluation tests, PySide6 GUI construction): https://github.com/OliverIsNotAvailble/AS_Live2D-reader/actions/runs/38309358001. Actual GPU, skin/rig part-opacity behavior and export require the user's original model to be tested locally.

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
