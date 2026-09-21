"""
Unit tests for the Spatial Adjuster Engine (spatial_adjuster.py).
"""

import unittest
import cv2
import numpy as np

from spatial_adjuster import SpatialAdjuster


class TestSpatialAdjuster(unittest.TestCase):

    def setUp(self):
        # Create a synthetic image with edges and gradients
        self.test_img = np.zeros((100, 100, 3), dtype=np.uint8)
        self.test_img[:50, :] = 100
        self.test_img[50:, :] = 200

    def test_clarity(self):
        out = SpatialAdjuster.apply_clarity(self.test_img, 30.0)
        self.assertEqual(out.shape, self.test_img.shape)
        self.assertEqual(out.dtype, self.test_img.dtype)
        # Should increase edge contrast
        self.assertFalse(np.array_equal(out, self.test_img))

    def test_clarity_gradient_monotonicity(self):
        """Clarity on a smooth linear gradient must remain monotonic without plateau stair-stepping."""
        ramp_1d = np.linspace(50, 200, 120, dtype=np.float32)
        ramp_2d = np.tile(ramp_1d, (120, 1)).astype(np.uint8)
        ramp_bgr = cv2.cvtColor(ramp_2d, cv2.COLOR_GRAY2BGR)
        
        clarity_bgr = SpatialAdjuster.apply_clarity(ramp_bgr, 30.0)
        clarity_gray = cv2.cvtColor(clarity_bgr, cv2.COLOR_BGR2GRAY)
        profile = clarity_gray[60, :].astype(np.float32)
        
        # Profile should be monotonically non-decreasing
        diffs = np.diff(profile)
        self.assertTrue(np.all(diffs >= -1e-3), f"Non-monotonic steps detected: min diff = {np.min(diffs)}")

    def test_texture(self):
        out = SpatialAdjuster.apply_texture(self.test_img, 25.0)
        self.assertEqual(out.shape, self.test_img.shape)
        self.assertEqual(out.dtype, self.test_img.dtype)

    def test_dehaze(self):
        out = SpatialAdjuster.apply_dehaze(self.test_img, 20.0)
        self.assertEqual(out.shape, self.test_img.shape)

    def test_sharpening_with_masking(self):
        out = SpatialAdjuster.apply_sharpening(self.test_img, amount=50.0, radius=1.0, masking=50.0)
        self.assertEqual(out.shape, self.test_img.shape)

    def test_vignette(self):
        out = SpatialAdjuster.apply_vignette(self.test_img, amount=-30.0)
        # Corners should be darker than center
        center_val = out[50, 50, 0]
        corner_val = out[0, 0, 0]
        self.assertLess(corner_val, center_val)

    def test_grain(self):
        out = SpatialAdjuster.apply_grain(self.test_img, amount=25.0)
        self.assertEqual(out.shape, self.test_img.shape)
        # Uniform areas should have noise variance
        std_orig = np.std(self.test_img[:40, :40, 0])
        std_grain = np.std(out[:40, :40, 0])
        self.assertGreater(std_grain, std_orig)


if __name__ == "__main__":
    unittest.main()
