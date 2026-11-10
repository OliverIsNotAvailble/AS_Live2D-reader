"""AS Live2D Reader startup."""
import os
import sys
import traceback

# Keep one Qt scaling coordinate space for GL capture/viewer consistency.
# Never change or disable Windows desktop DPI scaling globally.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication, QMessageBox

import live2d.v3 as live2d
from as_live2d.window import ReaderWindow
from as_live2d.theme import apply_dark_theme


def main() -> int:
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    fmt.setAlphaBufferSize(8)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(0)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setApplicationName("AS Live2D Reader")
    app.setOrganizationName("AS_Reader")
    apply_dark_theme(app)

    live2d.init()
    window = ReaderWindow()
    window.showMaximized()

    def close_live2d():
        window.viewer.cleanup()
        try:
            live2d.dispose()
        except Exception as exc:
            print("[Cubism cleanup]", exc)

    app.aboutToQuit.connect(close_live2d)
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
