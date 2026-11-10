"""Temporary preview manifest uses original assets; no mod folder is created."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from as_live2d.live_mesh_preview import write_live_preview


class RuntimePreviewTests(unittest.TestCase):
    def test_shadow_references_all_original_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            src = base / "original"
            src.mkdir()
            (src / "atlas").mkdir()
            (src / "motion").mkdir()
            (src / "model.moc3").write_bytes(b"ORIGINAL")
            (src / "atlas" / "a.png").write_bytes(b"PNG")
            (src / "motion" / "idle.motion3.json").write_text("{}")
            manifest = src / "a.model3.json"
            data = {"FileReferences": {
                "Moc": "model.moc3",
                "Textures": ["atlas/a.png"],
                "Motions": {"Idle": [{"File": "motion/idle.motion3.json"}]}}}
            manifest.write_text(json.dumps(data))
            temp = src / ".runtime"

            def fake_moc(source, dest, override):
                self.assertEqual(source.read_bytes(), b"ORIGINAL")
                self.assertEqual(override, {"ArtMesh0": False})
                dest.write_bytes(b"TEMP")

            with patch("as_live2d.live_mesh_preview.write_visibility_copy",
                       side_effect=fake_moc):
                shadow = write_live_preview(
                    manifest, temp, {"ArtMesh0": False}, 1)

            shadow_refs = json.loads(shadow.read_text())["FileReferences"]
            self.assertEqual((temp / shadow_refs["Moc"]).read_bytes(), b"TEMP")
            self.assertEqual((temp / shadow_refs["Textures"][0]).read_bytes(), b"PNG")
            self.assertEqual(
                (temp / shadow_refs["Motions"]["Idle"][0]["File"]).read_text(),
                "{}")
            self.assertEqual((src / "model.moc3").read_bytes(), b"ORIGINAL")
            self.assertEqual(json.loads(manifest.read_text()), data)
            self.assertFalse((src / "mod").exists())

    def test_empty_selection_returns_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "a.model3.json"
            self.assertEqual(write_live_preview(source, root, {}, 1),
                             source.resolve())


if __name__ == "__main__":
    unittest.main()
