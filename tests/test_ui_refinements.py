"""Regression checks for dark dropdowns, FPS defaults and preserved Meshes UI."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QSplitter

from as_live2d.part_hierarchy import build_part_hierarchy
from as_live2d.theme import DARK_STYLESHEET, apply_dark_theme
from as_live2d.window import ReaderWindow


class UserInterfaceRefinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_dark_theme(cls.app)

    def setUp(self):
        self.win = ReaderWindow()
        self.win.viewer.timer.stop()

    def tearDown(self):
        self.win.viewer.model = None
        self.win.close()

    def test_bold_white_text_and_dark_combo_popup(self):
        self.assertTrue(self.app.font().bold())
        self.assertEqual(
            self.app.palette().color(QPalette.ColorRole.Text).name(), "#ffffff")
        self.assertEqual(
            self.app.palette().color(QPalette.ColorRole.Base).name(), "#101820")
        self.assertIn("QComboBox QAbstractItemView", DARK_STYLESHEET)
        self.assertIn("QComboBox QAbstractItemView::item:selected",
                      DARK_STYLESHEET)
        self.assertNotIn("#F6F8FC", self.win.sidebar_tabs.styleSheet())
        combo = QComboBox()
        combo.addItem("ArtMesh2")
        self.assertEqual(combo.palette().color(QPalette.ColorRole.Base).name(),
                         "#101820")

    def test_mesh_column_has_adjustable_sections_and_more_space(self):
        splitter = self.win.mesh_sections
        self.assertIsInstance(splitter, QSplitter)
        self.assertEqual(splitter.orientation(), Qt.Orientation.Vertical)
        self.assertFalse(splitter.childrenCollapsible())
        self.assertGreaterEqual(self.win.sidebar_tabs.maximumWidth(), 850)
        self.assertGreaterEqual(self.win.parts_tree.minimumHeight(), 400)
        self.assertGreaterEqual(splitter.count(), 2)

    def test_default_fps_30_and_not_inherited_from_motion(self):
        self.assertEqual(self.win.fps.value(), 30)
        self.assertEqual(self.win.fps.minimum(), 1)
        self.win.fps.setValue(60)
        self.assertEqual(self.win.fps.value(), 60)
        self.win.current_path = Path("no-real.model3.json")
        with patch("as_live2d.window.load_profile", return_value={"fps": 0}):
            self.win._restore_profile()
        self.assertEqual(self.win.fps.value(), 30)
        self.win.fps.setValue(75)
        with patch("as_live2d.window.load_profile", return_value={}):
            self.win._restore_profile()
        self.assertEqual(self.win.fps.value(), 30)

    def test_nested_part_expansion_and_selection_survive_rebuild(self):
        tree = self.win.parts_tree
        self.win.viewer._part_ids = {"Root": 0, "Part2": 1, "Other": 2}
        self.win.current_path = Path("dummy.model3.json")
        structure = build_part_hierarchy(
            ["Root", "Part2", "Other"], [-1, 0, -1],
            ["ArtMesh1", "ArtMesh2", "ArtMesh3"], [1, 1, 2],
            mesh_visibles=[True, True, True])
        with patch("as_live2d.window.read_part_hierarchy",
                   return_value=structure):
            self.win._fill_parts()
            root = tree.topLevelItem(0)
            subgroup = root.child(0)
            self.assertEqual(subgroup.data(0, Qt.ItemDataRole.UserRole), "Part2")
            root.setExpanded(True)
            subgroup.setExpanded(True)
            leaf = subgroup.child(1)
            leaf.setSelected(True)
            tree.setCurrentItem(leaf)
            self.win._fill_parts()

        root = tree.topLevelItem(0)
        subgroup = root.child(0)
        leaf = subgroup.child(1)
        self.assertTrue(root.isExpanded())
        self.assertTrue(subgroup.isExpanded())
        self.assertTrue(leaf.isSelected())
        self.assertIs(tree.currentItem(), leaf)
        # New model = fresh tree, not inherited open state.
        self.win._parts_tree_model = None
        with patch("as_live2d.window.read_part_hierarchy",
                   return_value=structure):
            self.win._fill_parts()
        self.assertFalse(tree.topLevelItem(0).isExpanded())


if __name__ == "__main__":
    unittest.main()
