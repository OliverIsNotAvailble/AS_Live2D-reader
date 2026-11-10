"""ArtMesh leaves have independent tri-state controls within Parts."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from as_live2d.part_hierarchy import build_part_hierarchy
from as_live2d.window import ReaderWindow


class MeshVisibilityUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hide_single_leaf_without_hiding_parent_or_sibling(self):
        window = ReaderWindow()
        window.viewer.timer.stop()
        try:
            window.viewer._part_ids = {"Part2": 0}
            window.current_path = Path("dummy.model3.json")
            hierarchy = build_part_hierarchy(
                ["Part2"], [-1], ["Body", "Leg", "Eye"], [0, 0, 0],
                mesh_visibles=[True, True, False])
            with patch("as_live2d.window.read_part_hierarchy", return_value=hierarchy):
                window._fill_parts()
            group = window.parts_tree.topLevelItem(0)
            self.assertEqual(group.childCount(), 3)
            body, leg, eye = (group.child(i) for i in range(3))
            self.assertIn("oculta no MOC3", eye.text(1))
            leg.setCheckState(0, Qt.CheckState.Unchecked)
            self.assertEqual(window._mesh_overrides, {"Leg": False})
            self.assertTrue(window.mesh_apply_button.isEnabled())
            self.assertEqual(body.checkState(0), Qt.CheckState.PartiallyChecked)
            self.assertEqual(group.checkState(0), Qt.CheckState.PartiallyChecked)
            leg.setCheckState(0, Qt.CheckState.PartiallyChecked)
            self.assertEqual(window._mesh_overrides, {})
            self.assertFalse(window.mesh_apply_button.isEnabled())
        finally:
            window.viewer.model = None
            window.close()
