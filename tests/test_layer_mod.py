"""Draw-order edits modify only nominated ArtMesh keyforms (no other fields)."""
import unittest
from as_live2d.layer_mod import set_artmesh_draw_depths


class MutableMoc(dict):
    pass


class LayerEditTests(unittest.TestCase):
    def setUp(self):
        self.moc = MutableMoc({
            "art_mesh.ids": ["Body", "Leg", "Face"],
            "art_mesh.keyform_begin_indices": [0, 2, 5],
            "art_mesh.keyform_counts": [2, 3, 1],
            "art_mesh_keyform.draw_orders": [400., 450., 500., 510., 520., 600.],
        })

    def test_forward_only_changes_selected_mesh(self):
        touched = set_artmesh_draw_depths(self.moc, {"Body": 1000})
        self.assertEqual(touched, {"Body": 2})
        self.assertEqual(self.moc["art_mesh_keyform.draw_orders"],
                         [1000., 1000., 500., 510., 520., 600.])

    def test_multiple_meshes_and_custom_depth(self):
        set_artmesh_draw_depths(self.moc, {"Body": 0, "Leg": 611})
        self.assertEqual(self.moc["art_mesh_keyform.draw_orders"],
                         [0., 0., 611., 611., 611., 600.])

    def test_reject_unknown_or_illegal_depth(self):
        for bad in ({"Missing": 100}, {"Body": -1},
                    {"Body": 1001}, {"Body": 400.5}):
            with self.assertRaises(ValueError):
                set_artmesh_draw_depths(self.moc, bad)

    def test_invalid_keyform_offset_rejected(self):
        self.moc["art_mesh.keyform_begin_indices"][0] = 99
        with self.assertRaises(ValueError):
            set_artmesh_draw_depths(self.moc, {"Body": 900})


if __name__ == "__main__":
    unittest.main()
