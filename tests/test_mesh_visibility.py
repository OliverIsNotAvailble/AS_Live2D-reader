import unittest
from as_live2d.mesh_visibility import apply_visibility, visibility_map

class VisibilityTests(unittest.TestCase):
    def test_one_mesh_hidden_without_touching_other(self):
        model = {"art_mesh.ids": ["Body", "Leg", "Eye"],
                 "art_mesh.visibles": [True, True, False],
                 "art_mesh_keyform.opacities": [1., 0.5, 0.]}
        before = list(model["art_mesh_keyform.opacities"])
        apply_visibility(model, {"Leg": False})
        self.assertEqual(visibility_map(model),
                         {"Body": True, "Leg": False, "Eye": False})
        self.assertEqual(model["art_mesh_keyform.opacities"], before)
        apply_visibility(model, {"Eye": True})
        self.assertTrue(model["art_mesh.visibles"][2])

    def test_invalid_values_do_not_write(self):
        model = {"art_mesh.ids": ["Body"], "art_mesh.visibles": [True]}
        for invalid in ({"Missing": False}, {"Body": 1}, {"Body": "hidden"}):
            with self.assertRaises(ValueError):
                apply_visibility(model, invalid)
            self.assertTrue(model["art_mesh.visibles"][0])
