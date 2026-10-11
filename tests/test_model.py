"""Pure-Python tests; no OpenGL context needed in CI."""
import json
from pathlib import Path
import tempfile
import unittest

from as_live2d.model import inspect_model, load_profile, profile_path, save_profile


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / "rig.moc3").write_bytes(b"MOC3-test")
        (self.root / "textures").mkdir()
        (self.root / "textures" / "t.png").write_bytes(b"PNG-test")
        (self.root / "motions").mkdir()
        (self.root / "motions" / "idle.motion3.json").write_text(
            json.dumps({"Meta": {"Duration": 1.2, "Fps": 30}}),
            encoding="utf-8")
        self.model = self.root / "avatar.model3.json"
        self.manifest = {
            "Name": "Avatar", "FileReferences": {
                "Moc": "rig.moc3",
                "Textures": ["textures/t.png"],
                "Motions": {"Idle": [{"File": "motions/idle.motion3.json"}]}
            }
        }
        self._save()

    def _save(self):
        self.model.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_complete_model_and_frame_count(self):
        cat = inspect_model(self.model)
        self.assertTrue(cat.can_load)
        self.assertEqual(cat.groups, ["Idle"])
        self.assertEqual(cat.motions[0].frames(), 36)
        self.assertFalse(cat.missing)

    def test_missing_moc_is_blocker(self):
        (self.root / "rig.moc3").unlink()
        cat = inspect_model(self.model)
        self.assertFalse(cat.can_load)
        self.assertEqual(len(cat.missing), 1)

    def test_missing_motion_does_not_block_preview(self):
        (self.root / "motions" / "idle.motion3.json").unlink()
        cat = inspect_model(self.model)
        self.assertTrue(cat.can_load)
        self.assertEqual(cat.motions, [])
        self.assertTrue(cat.warnings)

    def test_model_without_motion_is_viewable(self):
        self.manifest["FileReferences"]["Motions"] = {}
        self._save()
        cat = inspect_model(self.model)
        self.assertTrue(cat.can_load)
        self.assertEqual(len(cat.motions), 0)

    def test_profile_roundtrip(self):
        values = {"scale": 1.5, "formats": ["webp"]}
        target = save_profile(self.model, values)
        self.assertEqual(target, profile_path(self.model))
        self.assertEqual(load_profile(self.model)["scale"], 1.5)


if __name__ == "__main__":
    unittest.main()
