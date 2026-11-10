"""Runtime transparency atlases never reserialize Cubism MOC3 binaries."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage

from as_live2d.artmesh_uv import ArtMeshUV
from as_live2d.live_mesh_preview import clear_mesh_regions, write_live_preview


class AtlasShadowTests(unittest.TestCase):
    def setUp(self):
        self.mesh = ArtMeshUV(
            "Overlay", 0,
            ((0.1, .1), (.6, .1), (.1, .6)),
            ((0, 1, 2),))
        self.other = ArtMeshUV(
            "Other", 0,
            ((.7, .7), (.9, .7), (.7, .9)),
            ((0, 1, 2),))

    def test_erase_single_triangle_only(self):
        original = QImage(100, 100, QImage.Format.Format_ARGB32)
        original.fill(QColor(20, 90, 140, 255))
        changed = clear_mesh_regions(original, [self.mesh], flip_v=False)
        self.assertEqual(changed.pixelColor(20, 20).alpha(), 0)
        self.assertEqual(changed.pixelColor(80, 80).alpha(), 255)
        self.assertEqual(original.pixelColor(20, 20).alpha(), 255)

    def test_model_uses_exact_original_moc_and_only_modified_texture(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "original"
            source.mkdir()
            (source / "atlas").mkdir()
            (source / "motion").mkdir()
            moc = source / "model.moc3"
            moc.write_bytes(b"MOC3-ORIGINAL-BYTES")
            texture = source / "atlas/a.png"
            image = QImage(100, 100, QImage.Format.Format_ARGB32)
            image.fill(QColor(20, 90, 140, 255))
            self.assertTrue(image.save(str(texture), "PNG"))
            (source / "motion/idle.motion3.json").write_text("{}")
            manifest = source / "model.model3.json"
            data = {"FileReferences": {
                "Moc": "model.moc3",
                "Textures": ["atlas/a.png"],
                "Motions": {
                    "Idle": [{"File": "motion/idle.motion3.json"}]}}}
            manifest.write_text(json.dumps(data))
            temp = source / ".shadow"
            with patch("as_live2d.live_mesh_preview.read_artmeshes",
                       return_value=[self.mesh, self.other]):
                rendered = write_live_preview(
                    manifest, temp, {"Overlay": False}, 2)
            refs = json.loads(rendered.read_text())["FileReferences"]
            self.assertEqual((temp / refs["Moc"]).resolve(), moc.resolve())
            self.assertEqual((temp / refs["Moc"]).read_bytes(), moc.read_bytes())
            edited = QImage(str(temp / refs["Textures"][0]))
            self.assertEqual(edited.pixelColor(25, 75).alpha(), 0)
            self.assertEqual(edited.pixelColor(80, 20).alpha(), 255)
            self.assertEqual(QImage(str(texture)).pixelColor(25, 75).alpha(), 255)
            self.assertEqual(
                (temp / refs["Motions"]["Idle"][0]["File"]).read_text(), "{}")
            self.assertEqual(json.loads(manifest.read_text()), data)
            self.assertFalse((source / "mod").exists())

    def test_unknown_mesh_fails_without_replacing_model(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "model.model3.json"
            model.write_text(json.dumps({"FileReferences": {
                "Moc": "model.moc3", "Textures": ["atlas.png"]}}))
            with patch("as_live2d.live_mesh_preview.read_artmeshes",
                       return_value=[self.mesh]):
                with self.assertRaises(ValueError):
                    write_live_preview(
                        model, Path(folder) / ".shadow", {"Missing": False}, 1)
            self.assertFalse((Path(folder) / ".shadow").exists())

    def test_empty_override_returns_original(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "model.model3.json"
            self.assertEqual(write_live_preview(p, Path(folder), {}, 1),
                             p.resolve())


if __name__ == "__main__":
    unittest.main()
