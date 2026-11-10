"""Checkbox uncheck directly triggers runtime sync, not a mod workflow."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from as_live2d.part_hierarchy import build_part_hierarchy
from as_live2d.window import ReaderWindow


class DirectMeshUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hide_single_leaf_siblings_remain_checked(self):
        window = ReaderWindow()
        window.viewer.timer.stop()
        try:
            window.viewer._part_ids = {"Part2": 0}
            window.current_path = Path("fake.model3.json")
            hierarchy = build_part_hierarchy(
                ["Part2"], [-1], ["Body", "Leg", "Eye"],
                [0, 0, 0], mesh_visibles=[True, True, False])
            with patch("as_live2d.window.read_part_hierarchy",
                       return_value=hierarchy):
                window._fill_parts()
            part = window.parts_tree.topLevelItem(0)
            body, leg, eye = (part.child(i) for i in range(3))
            self.assertFalse(hasattr(window, "mesh_apply_button"))
            self.assertEqual(eye.checkState(0), Qt.CheckState.Unchecked)
            with patch.object(window._mesh_controller, "changed") as sync:
                leg.setCheckState(0, Qt.CheckState.Unchecked)
                self.assertEqual(window._mesh_overrides, {"Leg": False})
                self.assertEqual(leg.text(1), "HIDDEN")
                self.assertEqual(body.checkState(0), Qt.CheckState.Checked)
                self.assertEqual(part.checkState(0), Qt.CheckState.PartiallyChecked)
                sync.assert_called_once()
                leg.setCheckState(0, Qt.CheckState.Checked)
                self.assertEqual(window._mesh_overrides, {})
                self.assertEqual(leg.text(1), "SHOW")
                self.assertEqual(sync.call_count, 2)
        finally:
            window.viewer.model = None
            window.close()

    def test_controller_rejects_export_while_syncing(self):
        window = ReaderWindow()
        window.viewer.timer.stop()
        try:
            controller = window._mesh_controller
            self.assertTrue(controller.can_export())
            controller.revision += 1
            self.assertFalse(controller.can_export())
            controller.applied = controller.revision
            self.assertTrue(controller.can_export())
            controller.error = True
            self.assertFalse(controller.can_export())
        finally:
            window.viewer.model = None
            window.close()
