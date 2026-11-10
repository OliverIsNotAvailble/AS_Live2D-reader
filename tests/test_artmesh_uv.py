"""Actual per-ArtMesh UV/triangle isolation, no whole-atlas fallback.

Synthetic MOC3 section names reproduce the layout observed in an actual
A2C5H1.moc3 supplied by the user: 127 valid drawables, UV float offsets,
and swapped vertex/triangle count labels in py-moc3 0.1.0.
No proprietary assets or textures are checked into Git.
"""
import os
import unittest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from as_live2d.artmesh_uv import (
    ArtMeshUV, _uv_stride, meshes_from_moc, isolated_mesh,
    apply_mesh_patch, apply_mesh_stroke,
)
from as_live2d.texture_mod import Stroke


def synthetic_moc():
    # A2C5H1 has the same section naming semantics:
    # position_index_counts = vertex counts; vertex_counts = index counts.
    return {
        "art_mesh.ids": ["ArtMesh9", "Eye", "Leg"],
        "art_mesh.texture_indices": [0, 1, 0],
        "art_mesh.position_index_counts": [3, 4, 3],
        "art_mesh.vertex_counts": [3, 6, 3],
        "art_mesh.uv_begin_indices": [0, 6, 14],
        "art_mesh.position_index_begin_indices": [0, 3, 9],
        "uv.xys": [
            .2, .2, .6, .2, .2, .6,
            .25, .25, .75, .25, .75, .75, .25, .75,
            .7, .7, .9, .7, .7, .9,
        ],
        "position_index.indices": [
            0, 1, 2, 0, 1, 2, 0, 2, 3, 0, 1, 2
        ],
    }


def image(width=80, height=80):
    result = QImage(width, height, QImage.Format.Format_ARGB32)
    result.fill(QColor(100, 140, 190, 255))
    return result


class ActualArtMeshTests(unittest.TestCase):
    def test_correct_moc3_index_count_semantics(self):
        moc = synthetic_moc()
        self.assertEqual(_uv_stride(moc), 1)
        meshes = meshes_from_moc(moc, 2)
        self.assertEqual([m.mesh_id for m in meshes],
                         ["ArtMesh9", "Eye", "Leg"])
        self.assertEqual([m.texture_index for m in meshes], [0, 1, 0])
        self.assertEqual(meshes[1].triangles, ((0, 1, 2), (0, 2, 3)))
        self.assertEqual(len(meshes[1].uv), 4)

    def test_isolated_crop_masks_unrelated_atlas_pixels(self):
        mesh = meshes_from_moc(synthetic_moc(), 2)[0]
        source = image()
        visible, rect = isolated_mesh(source, mesh, flip_v=False)
        self.assertLess(rect.width(), source.width())
        self.assertLess(rect.height(), source.height())
        self.assertEqual(visible.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(visible.pixelColor(24, 20).alpha(), 255)
        self.assertEqual(source.pixelColor(1, 1).alpha(), 255)

    def test_brush_erase_clipped_to_artmesh_uv_triangles(self):
        mesh = meshes_from_moc(synthetic_moc(), 2)[0]
        source = image()
        _, rect = isolated_mesh(source, mesh, flip_v=False)
        stroke = Stroke(
            "rectangle", ((0, 0), (rect.width(), rect.height())))
        modified = apply_mesh_stroke(source, mesh, stroke, flip_v=False)
        self.assertEqual(modified.pixelColor(20, 20).alpha(), 0)
        self.assertEqual(modified.pixelColor(64, 64).alpha(), 255)
        self.assertEqual(modified.pixelColor(4, 4).alpha(), 255)
        self.assertEqual(source.pixelColor(20, 20).alpha(), 255)

    def test_imported_png_only_changes_selected_mesh_area(self):
        mesh = meshes_from_moc(synthetic_moc(), 2)[0]
        source = image()
        rect = mesh.crop_bounds(source.width(), source.height(), False)
        patch = QImage(rect.size(), QImage.Format.Format_ARGB32)
        patch.fill(QColor(255, 40, 0, 255))
        edited = apply_mesh_patch(source, mesh, patch, False)
        self.assertEqual(edited.pixelColor(20, 20).red(), 255)
        self.assertEqual(edited.pixelColor(64, 64).red(), 100)
        self.assertEqual(source.pixelColor(20, 20).red(), 100)

    def test_invalid_mesh_indices_rejected(self):
        moc = synthetic_moc()
        moc["position_index.indices"][0] = 500
        meshes = meshes_from_moc(moc, 2)
        self.assertNotIn("ArtMesh9", [m.mesh_id for m in meshes])
        self.assertIn("Leg", [m.mesh_id for m in meshes])

    def test_wrong_texture_page_rejected(self):
        moc = synthetic_moc()
        self.assertEqual([m.mesh_id for m in meshes_from_moc(moc, 1)],
                         ["ArtMesh9", "Leg"])


if __name__ == "__main__":
    unittest.main()
