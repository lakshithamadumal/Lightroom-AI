"""
Unit tests for the Calibration Engine (calibration_engine.py).
"""

import os
import shutil
import unittest
import numpy as np
import cv2

from calibration_engine import CalibrationEngine
from lut_engine import Lut3D, LutEngine


class TestCalibrationEngine(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.join(os.path.dirname(__file__), "tmp_calib_test")
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_generate_and_calibrate_chart(self):
        """Generates an identity chart, simulates Lightroom applying a known tone transform, and verifies calibration."""
        chart_path = os.path.join(self.test_dir, "identity_chart.png")
        CalibrationEngine.generate_calibration_chart(chart_path, level=8, bit_depth=8)
        self.assertTrue(os.path.exists(chart_path))

        # Simulate Lightroom applying a color transformation to the chart
        chart_img = cv2.imread(chart_path, cv2.IMREAD_COLOR)
        # Apply simulated LR curve: R^1.1, G^0.95, B^1.05
        chart_norm = chart_img.astype(np.float32) / 255.0
        chart_sim = np.zeros_like(chart_norm)
        chart_sim[:, :, 0] = np.power(chart_norm[:, :, 0], 1.05)  # B
        chart_sim[:, :, 1] = np.power(chart_norm[:, :, 1], 0.95)  # G
        chart_sim[:, :, 2] = np.power(chart_norm[:, :, 2], 1.10)  # R
        lr_exported_path = os.path.join(self.test_dir, "simulated_lr_export.png")
        cv2.imwrite(lr_exported_path, (chart_sim * 255.0).astype(np.uint8))

        # Run calibration engine
        cube_path = os.path.join(self.test_dir, "calibrated.cube")
        hald_path = os.path.join(self.test_dir, "calibrated_hald.png")
        res = CalibrationEngine.calibrate_from_reference_image(
            rendered_reference_path=lr_exported_path,
            output_cube_path=cube_path,
            output_hald_path=hald_path,
            level=8
        )

        self.assertEqual(res["status"], "success")
        self.assertTrue(os.path.exists(cube_path))
        self.assertTrue(os.path.exists(hald_path))
        self.assertTrue(os.path.exists(res["metadata_path"]))

        # Verify calibrated LUT applies the exact simulated Lightroom transformation on a new test image
        calibrated_lut = Lut3D.from_cube_file(cube_path)
        test_patch = np.array([[[120, 180, 240]]], dtype=np.uint8)  # B, G, R
        test_patch_norm = test_patch.astype(np.float32) / 255.0

        expected_b = (test_patch_norm[0, 0, 0] ** 1.05) * 255.0
        expected_g = (test_patch_norm[0, 0, 1] ** 0.95) * 255.0
        expected_r = (test_patch_norm[0, 0, 2] ** 1.10) * 255.0

        out_patch = LutEngine.apply_lut_3d(test_patch, calibrated_lut, is_bgr=True)
        self.assertAlmostEqual(out_patch[0, 0, 0], expected_b, delta=2.0)
        self.assertAlmostEqual(out_patch[0, 0, 1], expected_g, delta=2.0)
        self.assertAlmostEqual(out_patch[0, 0, 2], expected_r, delta=2.0)


if __name__ == "__main__":
    unittest.main()
