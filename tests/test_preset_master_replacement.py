"""
Lightroom AI - Studio Edition 2.0
Unit & Regression Tests: Master Preset Replacement Pipeline (test_preset_master_replacement.py)
"""

import os
import shutil
import unittest
import numpy as np
import cv2
import json

from calibration_engine import CalibrationEngine, compute_file_sha256
from lut_engine import Lut3D, LutEngine
from preset_bundle import PresetBundle
from preset_manager import PresetManager
from image_pipeline import ImagePipeline
from color_space import ColorManager


class TestMasterPresetReplacement(unittest.TestCase):

    def setUp(self):
        self.test_root = os.path.join(os.path.dirname(__file__), "tmp_master_preset_test")
        self.calib_dir = os.path.join(self.test_root, "calibration")
        self.backup_dir = os.path.join(self.test_root, "backup")
        os.makedirs(self.calib_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)

        # Create initial test preset files in calib_dir
        ident_lut = Lut3D.create_identity(size=64, title="Old Test Preset")
        ident_lut.to_cube_file(os.path.join(self.calib_dir, "preset.cube"))
        ident_lut.to_cube_file(os.path.join(self.calib_dir, "preset_calibrated.cube"))
        
        init_json = {
            "preset_id": "old_test_preset",
            "preset_name": "Old Test Preset",
            "engine_version": "2.0",
            "working_space": "Adobe_RGB_1998",
            "export_color_space": "sRGB",
            "is_calibrated": True
        }
        with open(os.path.join(self.calib_dir, "preset.json"), "w", encoding="utf-8") as f:
            json.dump(init_json, f)
        
        with open(os.path.join(self.calib_dir, "calibration_metadata.json"), "w", encoding="utf-8") as f:
            json.dump({"engine": "Test"}, f)

    def tearDown(self):
        if os.path.exists(self.test_root):
            shutil.rmtree(self.test_root, ignore_errors=True)

    def test_hald_validation_valid(self):
        """Valid 512x512 HALD PNG must pass validation."""
        chart_path = os.path.join(self.test_root, "valid_chart.png")
        CalibrationEngine.generate_calibration_chart(chart_path, level=8, bit_depth=8)
        
        is_valid, err, lut = CalibrationEngine.validate_hald(chart_path, level=8)
        self.assertTrue(is_valid)
        self.assertIsNone(err)
        self.assertIsNotNone(lut)
        self.assertEqual(lut.size, 64)
        self.assertEqual(lut.table.shape, (64, 64, 64, 3))
        self.assertEqual(lut.table.dtype, np.float32)

    def test_hald_validation_corrupt_or_missing(self):
        """Missing or non-image files must fail validation cleanly without crashing."""
        # Missing file
        is_valid, err, _ = CalibrationEngine.validate_hald(os.path.join(self.test_root, "nonexistent.png"))
        self.assertFalse(is_valid)
        self.assertIn("not found", err.lower())

        # Empty/corrupt file
        corrupt_path = os.path.join(self.test_root, "corrupt.png")
        with open(corrupt_path, "wb") as f:
            f.write(b"not an image file")
        is_valid, err, _ = CalibrationEngine.validate_hald(corrupt_path)
        self.assertFalse(is_valid)

    def test_hald_validation_nan_or_inf(self):
        """Array containing NaN or Inf must be rejected."""
        nan_array = np.zeros((512, 512, 3), dtype=np.float32)
        nan_array[10, 10, 0] = np.nan
        is_valid, err, _ = CalibrationEngine.validate_hald(nan_array)
        self.assertFalse(is_valid)
        self.assertIn("non-finite", err.lower())

    def test_backup_and_atomic_installation(self):
        """Atomic master preset installation must create verified backup, stage, and replace."""
        # 1. Create a simulated processed HALD (subtle warm grade)
        chart_path = os.path.join(self.test_root, "processed_hald.png")
        lut_warm = Lut3D.create_identity(size=64)
        lut_warm.table[:, :, :, 0] = np.clip(lut_warm.table[:, :, :, 0] * 1.05, 0.0, 1.0) # Boost Red
        lut_warm.table[:, :, :, 2] = np.clip(lut_warm.table[:, :, :, 2] * 0.95, 0.0, 1.0) # Reduce Blue
        lut_warm.to_hald_file(chart_path, level=8, bit_depth=8)

        old_cube_sha = compute_file_sha256(os.path.join(self.calib_dir, "preset.cube"))

        # 2. Run install_master_preset
        res = CalibrationEngine.install_master_preset(
            hald_source=chart_path,
            calibration_dir=self.calib_dir,
            backup_dir=self.backup_dir,
            preset_name="Final Master Studio Preset"
        )

        self.assertTrue(res["installed"])
        self.assertEqual(res["status"], "success")

        # 3. Verify backup contains old preset
        backup_cube = os.path.join(self.backup_dir, "preset.cube")
        self.assertTrue(os.path.exists(backup_cube))
        self.assertEqual(compute_file_sha256(backup_cube), old_cube_sha)

        # 4. Verify new preset in calibration_dir
        new_cube_path = os.path.join(self.calib_dir, "preset.cube")
        new_cube_sha = compute_file_sha256(new_cube_path)
        self.assertNotEqual(new_cube_sha, old_cube_sha)
        self.assertEqual(new_cube_sha, res["sha256_preset_cube"])

        # 5. Verify preset.json
        with open(os.path.join(self.calib_dir, "preset.json"), "r", encoding="utf-8") as f:
            pj = json.load(f)
        self.assertEqual(pj["preset_name"], "Final Master Studio Preset")
        self.assertTrue(pj["is_calibrated"])

    def test_full_pipeline_with_master_preset(self):
        """Verify Stage 1 base -> Stage 2 AI fine-tuning -> Smart Crop -> sRGB export with installed master preset."""
        # Install master preset
        chart_path = os.path.join(self.test_root, "master_chart.png")
        CalibrationEngine.generate_calibration_chart(chart_path, level=8, bit_depth=8)
        CalibrationEngine.install_master_preset(
            hald_source=chart_path,
            calibration_dir=self.calib_dir,
            backup_dir=self.backup_dir,
            preset_name="Master Studio Preset"
        )

        # Ingest test image
        test_img = np.random.randint(40, 200, size=(120, 160, 3), dtype=np.uint8)

        # Load bundle via PresetManager
        pm = PresetManager(preset_folder=self.calib_dir)
        self.assertEqual(pm.preset_name, "Master Studio Preset")

        # Stage 1
        stage1_base = pm.apply_preset(test_img)
        self.assertEqual(stage1_base.shape, (120, 160, 3))
        self.assertEqual(stage1_base.dtype, np.uint8)

        # Stage 2 Adjustments
        adj_dict = {"exposure": 0.1, "shadows": 5.0, "highlights": -5.0}
        stage2_out = ImagePipeline.render_stage2_adjustments(stage1_base, adj_dict)
        self.assertEqual(stage2_out.shape, stage1_base.shape)

        # Crop Stage
        crop_dict = {"crop_top": 0.05, "crop_bottom": 0.05, "crop_left": 0.05, "crop_right": 0.05}
        cropped_out, _ = ImagePipeline.apply_crop_stage(stage2_out, crop_dict, enable_smart_crop=False)
        self.assertLess(cropped_out.shape[0], stage2_out.shape[0])
        self.assertLess(cropped_out.shape[1], stage2_out.shape[1])

        # Final sRGB Export
        final_export = pm.export_image(cropped_out)
        self.assertEqual(final_export.shape, cropped_out.shape)
        self.assertEqual(final_export.dtype, np.uint8)


if __name__ == "__main__":
    unittest.main()
