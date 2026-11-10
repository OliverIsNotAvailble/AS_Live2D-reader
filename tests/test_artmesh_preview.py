"""Preview generation must be UV-clipped, bounded and independent of edits."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QColor

from as_live2d.artmesh_uv import ArtMeshUV
from as_live2d.artmesh_preview import render_mesh_preview


class ArtMeshThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.source = QImage(1200, 800, QImage.Format.Format_ARGB32)
        self.source.fill(QColor(10, 100, 220, 255))
        self.mesh = ArtMeshUV(
            "SmallTriangle", 0,
            ((.1, .1), (.6, .1), (.1, .6)),
            ((0, 1, 2),))

    def test_bounded_thumbnail_masks_unrelated_pixels(self):
        thumb = render_mesh_preview(self.source, self.mesh, False, 128)
        self.assertLessEqual(max(thumb.width(), thumb.height()), 128)
        self.assertGreater(thumb.width(), 0)
        self.assertEqual(thumb.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(thumb.pixelColor(15, 15).alpha(), 255)
        self.assertEqual(thumb.pixelColor(thumb.width()-1,
                                          thumb.height()-1).alpha(), 0)
        self.assertEqual(self.source.pixelColor(0, 0).alpha(), 255)

    def test_vertical_orientation_changes_uv_crop(self):
        # Only a corner of the atlas is red; flipping V samples elsewhere.
        self.source.fill(QColor(0, 0, 220, 255))
        for y in range(0, 350):
            for x in range(0, 700):
                self.source.setPixelColor(x, y, QColor(220, 0, 0, 255))
        top = render_mesh_preview(self.source, self.mesh, False, 80)
        bottom = render_mesh_preview(self.source, self.mesh, True, 80)
        self.assertGreater(top.pixelColor(10, 10).red(), 100)
        self.assertLess(bottom.pixelColor(10, 10).red(), 100)

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError):
            render_mesh_preview(QImage(), self.mesh)
        with self.assertRaises(ValueError):
            render_mesh_preview(self.source, self.mesh, max_dimension=0)


if __name__ == "__main__":
    unittest.main()
