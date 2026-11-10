"""Unit tests for direct per-mesh hide, across every opacity keyform."""
import unittest
from as_live2d.mesh_visibility import apply_visibility, visibility_map


def fake_moc():
    return {
        "art_mesh.ids": ["Body", "Leg", "Eye"],
        "art_mesh.visibles": [True, True, False],
        "art_mesh.keyform_begin_indices": [0, 2, 5],
        "art_mesh.keyform_counts": [2, 3, 1],
        "art_mesh_keyform.opacities": [1., .5, 1., .8, .3, 0.],
    }


class ArtMeshVisibilityTests(unittest.TestCase):
    def test_hide_leg_preserves_body_and_eye(self):
        moc = fake_moc()
        apply_visibility(moc, {"Leg": False})
        self.assertEqual(moc["art_mesh_keyform.opacities"],
                         [1., .5, 0., 0., 0., 0.])
        self.assertEqual(visibility_map(moc),
                         {"Body": True, "Leg": False, "Eye": False})

    def test_explicit_show_restores_hidden_mesh(self):
        moc = fake_moc()
        apply_visibility(moc, {"Eye": True})
        self.assertEqual(moc["art_mesh_keyform.opacities"][-1], 1.0)
        self.assertTrue(moc["art_mesh.visibles"][-1])

    def test_multi_hide(self):
        moc = fake_moc()
        apply_visibility(moc, {"Body": False, "Leg": False})
        self.assertEqual(moc["art_mesh_keyform.opacities"][:5], [0.] * 5)

    def test_invalid_input_cannot_partially_mutate(self):
        for invalid in ({"Missing": False}, {"Leg": 0},
                        {"Body": False, "Missing": False}):
            moc = fake_moc()
            before = list(moc["art_mesh_keyform.opacities"])
            with self.assertRaises(ValueError):
                apply_visibility(moc, invalid)
            self.assertEqual(moc["art_mesh_keyform.opacities"], before)

    def test_bad_ranges_rejected(self):
        moc = fake_moc()
        moc["art_mesh.keyform_begin_indices"][1] = 999
        with self.assertRaises(ValueError):
            apply_visibility(moc, {"Leg": False})

    def test_shared_keyforms_rejected(self):
        moc = fake_moc()
        moc["art_mesh.keyform_begin_indices"][1] = 1
        with self.assertRaises(ValueError):
            apply_visibility(moc, {"Leg": False})


if __name__ == "__main__":
    unittest.main()
