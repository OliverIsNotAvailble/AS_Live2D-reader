"""Regression tests for Cubism Runtime motion target grouping.

Fixtures intentionally describe the small pathological shape of user assets;
no proprietary .moc3, textures or original game motions are stored in Git.
"""
import json
from pathlib import Path
import tempfile
import unittest

from as_live2d.motion_runtime import normalize_motion_data, prepare_motion
from as_live2d.part_visibility import read_part_tracks


class NativeMotionNormalizationTests(unittest.TestCase):
    @staticmethod
    def mixed_motion():
        curves = [
            {"Target": "Parameter", "Id": "Body", "Segments": [0, 2, 0, 9, 8]},
            {"Target": "PartOpacity", "Id": "clothes_1",
             "Segments": [0, 1, 2, 2, 1, 0, 5, 0, 2, 9, 0]},
            {"Target": "Parameter", "Id": "ParamEyeLOpen",
             "Segments": [0, 1, 0, 9, 0]},
            {"Target": "PartOpacity", "Id": "head_1",
             "Segments": [0, 0, 0, 9, 0]},
            {"Target": "PartOpacity", "Id": "head_2",
             "Segments": [0, 1, 0, 9, 1]},
        ]
        return {"Version": 3,
                "Meta": {"Duration": 9, "CurveCount": len(curves)},
                "Curves": curves, "UserData": [{"Time": 0.0, "Value": ""}]}

    def test_all_curves_stable_and_metadata_preserved(self):
        source = self.mixed_motion()
        normalized, changed = normalize_motion_data(source)
        self.assertTrue(changed)
        self.assertEqual([c["Target"] for c in normalized["Curves"]],
                         ["Parameter", "Parameter", "PartOpacity",
                          "PartOpacity", "PartOpacity"])
        self.assertEqual([c["Id"] for c in normalized["Curves"]],
                         ["Body", "ParamEyeLOpen", "clothes_1", "head_1", "head_2"])
        self.assertEqual(source["Meta"], normalized["Meta"])
        self.assertEqual(source["UserData"], normalized["UserData"])
        self.assertEqual(source["Curves"][1]["Id"], "clothes_1")
        # Curves and segments retain their original objects and values.
        for old in source["Curves"]:
            self.assertIn(old, normalized["Curves"])

    def test_temporary_motion_keeps_original_file_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clothes_turnOff.motion3.json"
            original = json.dumps(self.mixed_motion(), indent=2)
            path.write_text(original, encoding="utf-8")
            output, changed = prepare_motion(path, Path(directory) / "runtime")
            self.assertTrue(changed)
            self.assertNotEqual(path, output)
            self.assertEqual(path.read_text("utf-8"), original)
            part_tracks, interleaved = read_part_tracks(output)
            self.assertFalse(interleaved)
            self.assertEqual(part_tracks["head_1"].value_at(7), 0)
            self.assertEqual(part_tracks["head_2"].value_at(7), 1)
            self.assertEqual(part_tracks["clothes_1"].value_at(7), 0)

    def test_already_ordered_file_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "idle.motion3.json"
            motion = self.mixed_motion()
            normalized, _ = normalize_motion_data(motion)
            path.write_text(json.dumps(normalized), encoding="utf-8")
            output, changed = prepare_motion(path, Path(directory) / "runtime")
            self.assertFalse(changed)
            self.assertEqual(output, path.resolve())
            self.assertFalse((Path(directory) / "runtime").exists())

    def test_invalid_file_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_motion_data({})
        with self.assertRaises(ValueError):
            normalize_motion_data({"Curves": "bad"})


if __name__ == "__main__":
    unittest.main()
