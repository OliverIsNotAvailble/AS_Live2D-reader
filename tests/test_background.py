"""Regression tests for the shared preview/export background crop."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from as_live2d.background import fitted_background


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "background.png"
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        image[:, :100, :] = [200, 20, 20]
        image[:, 100:, :] = [20, 200, 20]
        Image.fromarray(image, "RGB").save(self.path)

    def test_exact_export_dimensions(self):
        rgb = fitted_background(self.path, 400, 200)
        self.assertEqual(rgb.shape, (200, 400, 3))
        self.assertEqual(tuple(rgb[100, 20]), (200, 20, 20))
        self.assertEqual(tuple(rgb[100, 380]), (20, 200, 20))

    def test_preview_crop_matches_export(self):
        export = fitted_background(self.path, 200, 100)
        preview = fitted_background(self.path, 2000, 1000, max_dimension=200)
        self.assertEqual(export.shape, preview.shape)
        np.testing.assert_array_equal(export, preview)

    def test_portrait_center_crop(self):
        image = fitted_background(self.path, 100, 200)
        self.assertEqual(image.shape, (200, 100, 3))
        # The center crop spans both colored halves.
        self.assertGreater(image[100, 10, 0], image[100, 10, 1])
        self.assertGreater(image[100, 90, 1], image[100, 90, 0])

    def test_missing_file_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            fitted_background(self.path.with_name("missing.png"), 100, 100)

    def test_preview_dimension_cap(self):
        image = fitted_background(self.path, 3840, 2160, max_dimension=2048)
        self.assertEqual(image.shape, (1152, 2048, 3))


if __name__ == "__main__":
    unittest.main()
