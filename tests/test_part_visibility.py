"""Regressions for Cubism motion PartOpacity and mixed-curve input."""
import json
from pathlib import Path
import tempfile
import unittest

from as_live2d.part_visibility import PartTrack, read_part_tracks


class PartOpacityTests(unittest.TestCase):
    def test_constant_hidden_for_entire_motion(self):
        track = PartTrack([0, 0, 0, 9, 0])
        for t in (0, 0.001, 3, 8.999, 9):
            self.assertEqual(track.value_at(t), 0)

    def test_linear(self):
        curve = PartTrack([0, 0, 0, 2, 1])
        self.assertAlmostEqual(curve.value_at(1), 0.5)

    def test_stepped(self):
        curve = PartTrack([0, 0, 2, 1, 1])
        self.assertEqual(curve.value_at(0.75), 0)
        self.assertEqual(curve.value_at(1), 0)

    def test_inverse_stepped(self):
        curve = PartTrack([0, 0, 3, 1, 1])
        self.assertEqual(curve.value_at(0.1), 1)

    def test_bezier(self):
        curve = PartTrack([0, 0, 1, .25, .25, .75, .75, 1, 1])
        self.assertAlmostEqual(curve.value_at(.5), .5, places=5)

    def test_invalid_segment_rejected(self):
        with self.assertRaises(ValueError):
            PartTrack([0, 0, 1, 1, 1])

    def test_mixed_targets_are_flagged_but_part_curves_not_lost(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.motion3.json"
            curves = [
                {"Target": "Parameter", "Id": "ParamAngleX", "Segments": [0, 0, 0, 9, 3]},
                {"Target": "PartOpacity", "Id": "Part24", "Segments": [0, 0, 0, 9, 0]},
                {"Target": "Parameter", "Id": "ParamEyeLOpen", "Segments": [0, 1, 0, 9, 1]},
                {"Target": "PartOpacity", "Id": "head_1", "Segments": [0, 0, 0, 9, 0]},
            ]
            path.write_text(json.dumps({"Curves": curves}), encoding="utf-8")
            parts, out_of_order = read_part_tracks(path)
            self.assertTrue(out_of_order)
            self.assertEqual(list(parts), ["Part24", "head_1"])
            self.assertEqual(parts["head_1"].value_at(4), 0)

    def test_grouped_targets_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "good.motion3.json"
            path.write_text(json.dumps({"Curves": [
                {"Target": "Parameter", "Id": "X", "Segments": [0, 0]},
                {"Target": "PartOpacity", "Id": "head_1", "Segments": [0, 0, 0, 9, 0]}
            ]}), encoding="utf-8")
            parts, mixed = read_part_tracks(path)
            self.assertFalse(mixed)
            self.assertIn("head_1", parts)


if __name__ == "__main__":
    unittest.main()
