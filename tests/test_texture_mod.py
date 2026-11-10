"""Safe, repeatable visual texture mods; source Cubism bundles untouched."""
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from as_live2d.model import inspect_model
from as_live2d.texture_mod import Stroke, erase_regions, clone_mod_bundle
from as_live2d.texture_mod_dialog import TextureModDialog
from as_live2d.artmesh_uv import ArtMeshUV


def png(path: Path, color=QColor(200, 100, 30, 255), width=32, height=32):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(color)
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path), "PNG")
    return image


def fixture(root: Path) -> Path:
    (root / "model.moc3").write_bytes(b"fake-moc3-stays-identical")
    (root / "motion.motion3.json").write_text(
        json.dumps({"Meta": {"Duration": 2.5, "Fps": 30}}), encoding="utf8")
    (root / "voice.ogg").write_bytes(b"fake-voice")
    (root / "emotion.exp3.json").write_text("{}", encoding="utf8")
    (root / "physics.physics3.json").write_text("{}", encoding="utf8")
    (root / "info.cdi3.json").write_text("{}", encoding="utf8")
    png(root / "textures" / "a.png")
    png(root / "textures" / "b.png", QColor(50, 80, 120, 255))
    manifest = root / "Character.model3.json"
    manifest.write_text(json.dumps({
        "Version": 3,
        "FileReferences": {
            "Moc": "model.moc3",
            "Textures": ["textures/a.png", "textures/b.png"],
            "Physics": "physics.physics3.json",
            "DisplayInfo": "info.cdi3.json",
            "Motions": {"Idle": [
                {"File": "motion.motion3.json", "Sound": "voice.ogg"}
            ]},
            "Expressions": [{"Name": "Happy", "File": "emotion.exp3.json"}]
        }
    }), encoding="utf8")
    return manifest


class EraseTests(unittest.TestCase):
    def test_rect_and_brush_are_transparent_and_undo_is_replay(self):
        image = QImage(30, 30, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 0, 0, 255))
        rect = Stroke("rectangle", ((3, 3), (10, 10)))
        brush = Stroke("brush", ((20, 20),), 6)
        result = erase_regions(image, [rect, brush])
        self.assertEqual(result.pixelColor(5, 5).alpha(), 0)
        self.assertEqual(result.pixelColor(20, 20).alpha(), 0)
        self.assertEqual(result.pixelColor(0, 0).alpha(), 255)
        self.assertEqual(image.pixelColor(5, 5).alpha(), 255)
        undone = erase_regions(image, [rect])
        self.assertEqual(undone.pixelColor(20, 20).alpha(), 255)

    def test_empty_edits_leave_original_visible(self):
        image = QImage(5, 5, QImage.Format.Format_ARGB32)
        image.fill(QColor(10, 20, 30, 255))
        self.assertEqual(erase_regions(image, []).pixelColor(1, 1),
                         image.pixelColor(1, 1))


class ModBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mod_has_its_own_moc_motions_sounds_and_png(self):
        with TemporaryDirectory() as path:
            root = Path(path)
            manifest = fixture(root)
            original_manifest = manifest.read_bytes()
            original_texture = (root / "textures" / "a.png").read_bytes()
            moc_bytes = (root / "model.moc3").read_bytes()
            base = QImage(str(root / "textures" / "a.png"))
            edited = erase_regions(
                base, [Stroke("rectangle", ((2, 2), (15, 15)))])
            edited_manifest = clone_mod_bundle(manifest, {0: edited})
            self.assertEqual(edited_manifest.parent.parent.name, "mod")
            self.assertTrue(edited_manifest.name.endswith(".model3.json"))
            self.assertTrue((edited_manifest.parent / "MOD_INFO.txt").exists())
            refs = json.loads(edited_manifest.read_text("utf8"))["FileReferences"]
            for name in ("Moc", "Physics", "DisplayInfo"):
                self.assertTrue((edited_manifest.parent / refs[name]).is_file())
            self.assertEqual((edited_manifest.parent / refs["Moc"]).read_bytes(),
                             moc_bytes)
            for idx, relative in enumerate(refs["Textures"]):
                self.assertTrue((edited_manifest.parent / relative).is_file())
            new_texture = QImage(str(edited_manifest.parent / refs["Textures"][0]))
            self.assertEqual(new_texture.pixelColor(4, 4).alpha(), 0)
            self.assertEqual(new_texture.pixelColor(20, 20).alpha(), 255)
            self.assertTrue((edited_manifest.parent /
                             refs["Motions"]["Idle"][0]["File"]).exists())
            self.assertTrue((edited_manifest.parent /
                             refs["Motions"]["Idle"][0]["Sound"]).exists())
            self.assertTrue((edited_manifest.parent /
                             refs["Expressions"][0]["File"]).exists())
            self.assertEqual(original_manifest, manifest.read_bytes())
            self.assertEqual(original_texture,
                             (root / "textures" / "a.png").read_bytes())
            self.assertTrue(inspect_model(edited_manifest).can_load)

            next_mod = clone_mod_bundle(manifest, {0: edited})
            self.assertNotEqual(next_mod.parent, edited_manifest.parent)
            self.assertTrue(edited_manifest.exists())  # versioned, no overwrite
            # Editing a MOD starts another sibling and doesn't create mod/mod.
            next_version = clone_mod_bundle(edited_manifest, {0: edited})
            self.assertEqual(next_version.parent.parent,
                             edited_manifest.parent.parent)

    def test_visibility_mod_does_not_modify_original(self):
        with TemporaryDirectory() as path:
            root = Path(path)
            manifest = fixture(root)
            original = (root / "model.moc3").read_bytes()

            def fake_patch(source, target, overrides):
                self.assertEqual(overrides, {"ArtMeshLeg": False})
                self.assertEqual(source.read_bytes(), original)
                target.write_bytes(b"changed-only-copy")

            with patch("as_live2d.texture_mod.write_visibility_copy",
                       side_effect=fake_patch):
                new = clone_mod_bundle(
                    manifest, {},
                    visibility_overrides={"ArtMeshLeg": False})
            refs = json.loads(new.read_text("utf8"))["FileReferences"]
            self.assertEqual((new.parent / refs["Moc"]).read_bytes(),
                             b"changed-only-copy")
            self.assertEqual((root / "model.moc3").read_bytes(), original)
            self.assertEqual(json.loads(
                (new.parent / "MESH_VISIBILITY.json").read_text("utf8")),
                {"ArtMeshLeg": False})

    def test_rejects_size_change_and_preserves_original(self):
        with TemporaryDirectory() as path:
            root = Path(path)
            manifest = fixture(root)
            small = QImage(8, 8, QImage.Format.Format_ARGB32)
            small.fill(Qt.GlobalColor.red)
            with self.assertRaises(ValueError):
                clone_mod_bundle(manifest, {0: small})
            self.assertEqual(list((root / "mod").iterdir()), [])
            self.assertTrue((root / "textures" / "a.png").is_file())

    def test_gui_isolates_selected_mesh_instead_of_entire_atlas(self):
        with TemporaryDirectory() as path:
            manifest = fixture(Path(path))
            # The old fixture uses placeholder MOC bytes; here we mock the
            # real MOC parser so we can assert UI behavior independently.
            meshes = [
                ArtMeshUV("ArtMeshLeg", 0,
                          ((.1, .1), (.5, .1), (.5, .5)),
                          ((0, 1, 2),)),
                ArtMeshUV("ArtMeshEye", 1,
                          ((.4, .4), (.6, .4), (.6, .6)),
                          ((0, 1, 2),))
            ]
            with patch("as_live2d.texture_mod_dialog.read_artmeshes",
                       return_value=meshes):
                dialog = TextureModDialog(manifest, ["ArtMeshLeg", "ArtMeshEye"])
            try:
                self.assertEqual(dialog.drawable_choice.count(), 2)
                self.assertFalse(dialog.flip_v.isChecked())
                self.assertEqual(dialog.atlas_choice.count(), 2)
                self.assertFalse(dialog.atlas_choice.isEnabled())
                self.assertIn("SOMENTE a ArtMesh", 
                              dialog.layout().itemAt(0).widget().text())
                self.assertIsNone(dialog._preview_crop)
                self.assertFalse(dialog.canvas.edit_enabled)
                self.assertIsNone(dialog.created_manifest)
                # Building thumbnails must not invoke the costly full atlas
                # replay used by the editing canvas.
                with patch.object(dialog, "_image",
                                  side_effect=AssertionError("full render during preview")):
                    dialog._build_previews()
                    deadline = time.monotonic() + 8
                    while dialog._building_previews and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(0.01)
                self.assertFalse(dialog._building_previews)
                self.assertEqual(set(dialog._previews),
                                 {"ArtMeshLeg", "ArtMeshEye"})
                self.assertFalse(dialog.canvas.edit_enabled)
                dialog._enter_edit()
                self.assertTrue(dialog.canvas.edit_enabled)
                self.assertIsNotNone(dialog._preview_crop)
                self.assertLess(dialog._preview_crop.width(), 32)
                dialog._erase_selected()
                self.assertEqual(len(dialog._history), 1)
                self.assertEqual(dialog._history[0][0], "ArtMeshEye")
                edited = dialog._image(1)
                self.assertEqual(edited.pixelColor(18, 16).alpha(), 0)
                self.assertEqual(edited.pixelColor(0, 0).alpha(), 255)
                dialog._undo()
                self.assertEqual(len(dialog._history), 0)
                # Each UI selection really changes the bound page.
                dialog.drawable_choice.setCurrentIndex(1)
                self.assertEqual(dialog._index(), 0)
                self.assertFalse(dialog.canvas.edit_enabled)
                self.assertIsNone(dialog._preview_crop)
                self.assertTrue(dialog.edit_button.isEnabled())
            finally:
                dialog.close()


if __name__ == "__main__":
    unittest.main()
