"""ArtMesh hiding redirects just selected texture indices to 1x1 transparent PNG.

No full atlas copies, no UV flipping, no py-moc3 serialization.
"""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage

from as_live2d.live_mesh_preview import (
    patch_texture_indices, write_live_preview,
)


def fake_moc_bytes():
    """Build raw bytes for a known art_mesh.texture_indices SOT location."""
    original = bytearray(3200)
    original[0:4] = b"MOC3"
    begin = 2400
    for i, value in enumerate((0, 1, 0)):
        struct.pack_into("<i", original, begin + i * 4, value)
    model = SimpleNamespace(
        header=SimpleNamespace(endian=0),
        _layout=[
            SimpleNamespace(name="dummy"),
            SimpleNamespace(name="art_mesh.texture_indices"),
            SimpleNamespace(name="next"),
        ],
        _sot_offsets=[1984, 2048, 2176, 2400, 2600],
    )
    tables = {
        "art_mesh.ids": ["Body", "Leg", "Eye"],
        "art_mesh.texture_indices": [0, 1, 0],
    }

    class MockMoc:
        _layout = model._layout
        _sot_offsets = model._sot_offsets
        header = model.header

        def __getitem__(self, key):
            return tables[key]

    return bytes(original), MockMoc()


class BinaryPatchTests(unittest.TestCase):
    def test_only_hidden_mesh_texture_index_changes(self):
        original, parsed = fake_moc_bytes()
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "original.moc3"
            target = Path(td) / "shadow.moc3"
            source.write_bytes(original)
            with patch("moc3.Moc3.from_bytes", return_value=parsed):
                patch_texture_indices(source, target, {"Leg"}, 2)
            result = target.read_bytes()
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(len(result), len(original))
            self.assertEqual(result[:2404], original[:2404])
            self.assertEqual(result[2408:], original[2408:])
            self.assertEqual(struct.unpack_from("<i", result, 2404)[0], 2)
            self.assertEqual(struct.unpack_from("<i", result, 2400)[0], 0)
            self.assertEqual(struct.unpack_from("<i", result, 2408)[0], 0)

    def test_multiple_meshes_share_one_blank_page(self):
        original, parsed = fake_moc_bytes()
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.moc3"
            target = Path(td) / "shadow.moc3"
            source.write_bytes(original)
            with patch("moc3.Moc3.from_bytes", return_value=parsed):
                patch_texture_indices(source, target, {"Body", "Eye"}, 2)
            output = target.read_bytes()
            self.assertEqual(struct.unpack_from("<iii", output, 2400),
                             (2, 1, 2))

    def test_bad_binary_mapping_fails_before_creation(self):
        original, parsed = fake_moc_bytes()
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.moc3"
            target = Path(td) / "shadow.moc3"
            source.write_bytes(original)
            parsed._sot_offsets[3] = 2396
            with patch("moc3.Moc3.from_bytes", return_value=parsed):
                with self.assertRaises(ValueError):
                    patch_texture_indices(source, target, {"Leg"}, 2)
            self.assertFalse(target.exists())

    def test_unknown_mesh_and_non_original_destination(self):
        original, parsed = fake_moc_bytes()
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.moc3"
            target = Path(td) / "shadow.moc3"
            source.write_bytes(original)
            with patch("moc3.Moc3.from_bytes", return_value=parsed):
                with self.assertRaises(ValueError):
                    patch_texture_indices(source, target, {"Unknown"}, 2)
                with self.assertRaises(ValueError):
                    patch_texture_indices(source, source, {"Body"}, 2)
            self.assertFalse(target.exists())


class ShadowPreviewTests(unittest.TestCase):
    def test_only_one_1x1_png_and_original_atlases_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / "original"
            src.mkdir()
            (src / "atlas").mkdir()
            (src / "motion").mkdir()
            moc = src / "model.moc3"
            moc.write_bytes(b"MOC3-ORIGINAL")
            source_texture = src / "atlas/a.png"
            image = QImage(32, 16, QImage.Format.Format_ARGB32)
            image.fill(QColor(50, 100, 150, 255))
            self.assertTrue(image.save(str(source_texture), "PNG"))
            (src / "motion/idle.motion3.json").write_text("{}")
            manifest = src / "model.model3.json"
            data = {"FileReferences": {
                "Moc": "model.moc3",
                "Textures": ["atlas/a.png"],
                "Motions": {"Idle": [
                    {"File": "motion/idle.motion3.json"}]},
            }}
            manifest.write_text(json.dumps(data))
            temp = src / ".shadow"

            def simple_patch(source, target, ids, page):
                self.assertEqual(source.read_bytes(), b"MOC3-ORIGINAL")
                self.assertEqual(ids, {"ArtMesh0"})
                self.assertEqual(page, 1)
                target.write_bytes(b"MOC3-TEMP")

            with patch("as_live2d.live_mesh_preview.patch_texture_indices",
                       side_effect=simple_patch):
                for revision in (2, 3, 4, 5, 6):
                    rendered = write_live_preview(
                        manifest, temp, {"ArtMesh0": False}, revision)
                    refs = json.loads(
                        rendered.read_text(encoding="utf8"))["FileReferences"]
                    self.assertEqual((temp / refs["Moc"]).read_bytes(),
                                     b"MOC3-TEMP")
                    self.assertEqual(len(refs["Textures"]), 2)
                    self.assertEqual(
                        (temp / refs["Textures"][0]).resolve(),
                        source_texture.resolve())
                    blank = QImage(str(temp / refs["Textures"][1]))
                    self.assertEqual((blank.width(), blank.height()), (1, 1))
                    self.assertEqual(blank.pixelColor(0, 0).alpha(), 0)
            self.assertEqual(len(list(temp.glob("*.png"))), 1)
            self.assertLessEqual(len(list(temp.glob("*.moc3"))), 2)
            self.assertLessEqual(len(list(temp.glob("*.model3.json"))), 2)
            self.assertEqual(moc.read_bytes(), b"MOC3-ORIGINAL")
            self.assertEqual(QImage(str(source_texture)).pixelColor(
                4, 4).alpha(), 255)
            self.assertEqual(json.loads(manifest.read_text()), data)
            self.assertFalse((src / "mod").exists())

    def test_invalid_visibility_does_not_make_model(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "model.model3.json"
            temp = Path(td) / "tmp"
            for value in (True, 1, "hidden"):
                with self.assertRaises(ValueError):
                    write_live_preview(
                        manifest, temp, {"ArtMesh0": value}, 2)
            self.assertFalse(temp.exists())

    def test_restore_uses_original_model(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "model.model3.json"
            self.assertEqual(write_live_preview(
                manifest, Path(td), {}, 10), manifest.resolve())


if __name__ == "__main__":
    unittest.main()
