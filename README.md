# AS Live2D Reader

Dedicated Live2D Cubism viewer and motion exporter for Windows. Built with Python, PySide6, native **live2d-py v3** and FFmpeg.

> Initial release **v0.1.0**. Preview uses native OpenGL directly; only exports read pixels back from the GPU. Windows runtime compatibility and performance must still be tested with actual models.

## Features

- Load **.model3.json** files; switch models in the same window safely.
- Interactive native OpenGL preview, play/pause motions, loop, zoom, pan and frame-fit.
- Inspect motion groups, expressions, parameters and referenced files. Missing dependencies are highlighted.
- Save per-model profile JSON (framing, output settings and selected motion).
- Export selected motions to **MP4**, **animated WebP**, **PNG sequence**, or MP4 + WebP.
- Transparent WebP/PNG or solid-color/image backgrounds; FFmpeg runs on a separate encoder thread so the UI can still respond.
- Atomic outputs: temporary files are renamed only after encoding succeeds. Cancel safely keeps previous completed outputs.

## Requirements

- Windows 10/11, GPU OpenGL 3.3+.
- Python **3.10 or 3.11** (64-bit) recommended.
- FFmpeg installed in PATH or at `tools/ffmpeg/bin/ffmpeg.exe`.

In PowerShell in the extracted ZIP folder:

```powershell
py -3.10 -m pip install -r requirements.txt
py -3.10 main.py
```

If your Python 3.10 environment is already configured, the same commands work there. A missing model/reference is a *model-data* issue, not automatically a missing Cubism runtime asset.

## Model loading

Select a `.model3.json` in **Open Model**. The application checks `FileReferences` paths against the model directory. To switch models, just open another JSON; it does not replace or delete the underlying Qt widget.

## Export

Choose motions, folder, size/FPS and output format. The preview remains scaled to the available workspace; **export resolution is independent** of the preview widget resolution. Encoder files are written as `.part.mp4` / `.part.webp` and renamed after a successful FFmpeg exit. PNG sequence is placed in a dedicated folder.

## Repository

- `main.py` — startup and OpenGL context settings.
- `as_live2d/model.py` — manifest scan, motion catalog and dependency checks.
- `as_live2d/viewer.py` — native GL preview, camera and offscreen export frame capture.
- `as_live2d/encoder.py` — background FFmpeg / PNG encoding worker.
- `as_live2d/window.py` — GUI, controls, profiles and export orchestration.
- `CHANGELOG.md` — append on **every code update**.

## Limitations

Live2D model geometry is controlled by Cubism; a model without motions can be viewed, but motion export needs valid motion files. The current version does not edit the underlying Cubism mesh/rig and does not yet provide a full parts/parameters editor. Native GPU/Cubism errors can depend on the installed runtime and actual model data. Tested here by syntax checks, not full interactive Windows rendering.

Live2D/Cubism Core has separate distribution and licensing terms; this project does **not** bundle proprietary Cubism runtimes or sample models. Install live2d-py and review its license/runtime requirements before distributing packaged binaries.
