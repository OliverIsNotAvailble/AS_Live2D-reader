"""Cubism Part-to-ArtMesh hierarchy and invalid section regression tests."""
import unittest
from as_live2d.part_hierarchy import build_part_hierarchy


class PartHierarchyTests(unittest.TestCase):
    def test_nested_parts_and_ungrouped_mesh(self):
        h = build_part_hierarchy(
            ["Root", "Part2", "Shirt"], [-1, 0, 1],
            ["Body", "Sleeve", "Free"], [1, 2, -1])
        self.assertEqual(h.meshes_by_part["Part2"], ("Body",))
        self.assertEqual(h.meshes_by_part["Shirt"], ("Sleeve",))
        self.assertEqual(h.ungrouped, ("Free",))
        self.assertEqual(h.descendants_count("Root"), 2)
        self.assertEqual(h.descendants_count("Part2"), 2)

    def test_inherited_from_deformer(self):
        h = build_part_hierarchy(
            ["Root", "Face"], [-1, 0], ["Eye"], [-1],
            [1], [1, -1], [-1, 0])
        self.assertEqual(h.meshes_by_part["Face"], ("Eye",))

    def test_cycles_and_bad_section_length(self):
        h = build_part_hierarchy(["A", "B"], [1, 0], ["M"], [0])
        self.assertEqual(h.descendants_count("A"), 1)
        with self.assertRaises(ValueError):
            build_part_hierarchy(["A"], [], [], [])
