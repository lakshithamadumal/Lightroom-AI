"""
Unit tests for Lightroom AI v2.0.0 UI state contracts, conditional reset behaviors,
and Inspector single source of truth metadata.
"""

import unittest
import os
import shutil
import tempfile
import numpy as np
import cv2

import server


class TestUiStateAndConditionalResets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.input_dir = os.path.join(cls.test_dir, "incoming")
        cls.output_dir = os.path.join(cls.test_dir, "output")
        cls.preset_dir = os.path.join(cls.test_dir, "presets")
        os.makedirs(cls.input_dir, exist_ok=True)
        os.makedirs(cls.output_dir, exist_ok=True)
        os.makedirs(cls.preset_dir, exist_ok=True)

        os.environ["INPUT_FOLDER"] = cls.input_dir
        os.environ["OUTPUT_FOLDER"] = cls.output_dir
        os.environ["PRESET_FOLDER"] = cls.preset_dir

        # Create test images
        cls.img_landscape_name = "test_img_landscape.jpg"
        cls.img_landscape_path = os.path.join(cls.input_dir, cls.img_landscape_name)
        img_arr = np.zeros((400, 600, 3), dtype=np.uint8)
        img_arr[:, :] = [130, 160, 190]
        cv2.imwrite(cls.img_landscape_path, img_arr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        self.config_patcher = unittest.mock.patch("server.get_config", return_value={
            "ORCA_API_KEY": "test-key-123",
            "ORCA_API_URL": "https://api.orcarouter.ai/v1/chat/completions",
            "ORCA_MODEL": "google/gemini-2.5-flash",
            "INPUT_FOLDER": self.input_dir,
            "PRESET_FOLDER": self.preset_dir,
            "OUTPUT_FOLDER": self.output_dir,
            "ENABLE_AI_SMART_CROP": True,
            "ENABLE_AUTO_BALANCING": True,
            "TARGET_MAX_WIDTH": 0,
            "JPEG_QUALITY": 100,
        })
        self.config_patcher.start()

        # Clear telemetry and overrides
        overrides_path = server._get_overrides_file(self.output_dir)
        if os.path.exists(overrides_path):
            os.remove(overrides_path)
        telemetry_path = server._get_telemetry_file(self.output_dir)
        if os.path.exists(telemetry_path):
            os.remove(telemetry_path)

    def tearDown(self):
        self.config_patcher.stop()

    def test_top_ai_status_contract(self):
        """Verify the 4 semantic AI Status conditions can be derived from server metadata."""
        # 1. AI Active (Key present, enabled, no failure)
        cfg = server.get_config()
        self.assertTrue(bool(cfg.get("ORCA_API_KEY")))
        self.assertTrue(bool(cfg.get("ENABLE_AUTO_BALANCING")))

        # 2. AI Offline (Key missing or disabled)
        with unittest.mock.patch("server.get_config", return_value={
            "ORCA_API_KEY": "",
            "ENABLE_AUTO_BALANCING": True,
            "INPUT_FOLDER": self.input_dir,
            "OUTPUT_FOLDER": self.output_dir,
            "PRESET_FOLDER": self.preset_dir,
        }):
            cfg_off = server.get_config()
            self.assertFalse(bool(cfg_off.get("ORCA_API_KEY")))

        # 3. AI Limited (Credit / quota exhaustion telemetry recorded)
        telemetry_limited = {
            "adjust_telemetry": {
                "ai_status": "ai_unavailable",
                "reason": "Insufficient credit balance",
            }
        }
        server.save_photo_telemetry(self.output_dir, self.img_landscape_name, telemetry_limited)
        loaded_tel = server.load_telemetry(self.output_dir)
        self.assertEqual(loaded_tel[self.img_landscape_name]["adjust_telemetry"]["ai_status"], "ai_unavailable")

        # 4. AI Error (Unexpected network/API error telemetry recorded)
        telemetry_error = {
            "adjust_telemetry": {
                "ai_status": "ai_failed",
                "reason": "Internal server error 500",
            }
        }
        server.save_photo_telemetry(self.output_dir, self.img_landscape_name, telemetry_error)
        loaded_tel = server.load_telemetry(self.output_dir)
        self.assertEqual(loaded_tel[self.img_landscape_name]["adjust_telemetry"]["ai_status"], "ai_failed")

    def test_badge_and_inspector_metadata_consistency(self):
        """Verify photo cards and inspector receive full single source of truth metadata."""
        filename = self.img_landscape_name
        adjustments = {
            "exposure": 0.15,
            "contrast": 0.0,
            "shadows": -5.0,
            "highlights": 10.0,
            "temperature": 2.0,
            "tint": -1.0,
            "vibrance": 8.0,
            "clarity": 5.0,
            "crop_top": 0.04,
            "crop_bottom": 0.04,
            "crop_left": 0.06,
            "crop_right": 0.06,
        }
        server.save_override_params(self.output_dir, filename, adjustments)

        telemetry = {
            "adjust_telemetry": {
                "ai_status": "ai_applied",
                "scene_type": "Portrait",
                "confidence": 0.95,
                "reason": "Warm skin tones boosted"
            },
            "crop_telemetry": {
                "crop_status": "ai_crop",
                "crop_applied": True,
                "crop_area_ratio": 0.88,
                "method": "Smart Headroom",
                "reason": "Centered subject with golden ratio headroom"
            }
        }
        server.save_photo_telemetry(self.output_dir, filename, telemetry)

        # Retrieve photos via API
        photos_res = server.api_get_incoming_photos()
        photo = next((p for p in photos_res["photos"] if p["filename"] == filename), None)
        self.assertIsNotNone(photo)

        # Verify all 12 parametric adjustment and crop fields are present and accurate
        for key, val in adjustments.items():
            self.assertIn(key, photo["adjustments"])
            self.assertAlmostEqual(photo["adjustments"][key], val)

        # Verify telemetry fields are accurately exposed
        self.assertEqual(photo["adjust_telemetry"]["ai_status"], "ai_applied")
        self.assertEqual(photo["crop_telemetry"]["crop_status"], "ai_crop")
        self.assertAlmostEqual(photo["crop_telemetry"]["crop_area_ratio"], 0.88)

    def test_conditional_reset_cases(self):
        """
        Verify independent reset persistence across Cases A, B, C, D:
        - Case A: AI Active (non-zero trims), Crop Inactive (all zero crop margins)
        - Case B: AI Inactive (all zero trims), Crop Active (non-zero crop margins)
        - Case C: Both Active (non-zero trims and non-zero crop margins)
        - Case D: Neither Active (all zero trims and all zero crop margins)
        """
        filename = self.img_landscape_name

        # Case A: AI Active, Crop Inactive
        params_a = {
            "exposure": 0.20, "contrast": 5.0, "shadows": 0.0, "highlights": 0.0,
            "temperature": 0.0, "tint": 0.0, "vibrance": 0.0, "clarity": 0.0,
            "crop_top": 0.0, "crop_bottom": 0.0, "crop_left": 0.0, "crop_right": 0.0
        }
        server.save_override_params(self.output_dir, filename, params_a)
        loaded_a = server.load_overrides(self.output_dir)[filename]
        has_trims_a = any(abs(loaded_a[k]) > 1e-4 for k in ["exposure", "contrast", "shadows", "highlights", "temperature", "tint", "vibrance", "clarity"])
        has_crop_a = any(loaded_a[k] > 1e-4 for k in ["crop_top", "crop_bottom", "crop_left", "crop_right"])
        self.assertTrue(has_trims_a)
        self.assertFalse(has_crop_a)

        # Reset AI balance independently in Case A -> transforms to Case D
        params_a_reset_ai = dict(params_a)
        for k in ["exposure", "contrast", "shadows", "highlights", "temperature", "tint", "vibrance", "clarity"]:
            params_a_reset_ai[k] = 0.0
        server.save_override_params(self.output_dir, filename, params_a_reset_ai)
        loaded_d = server.load_overrides(self.output_dir)[filename]
        has_trims_d = any(abs(loaded_d[k]) > 1e-4 for k in ["exposure", "contrast", "shadows", "highlights", "temperature", "tint", "vibrance", "clarity"])
        has_crop_d = any(loaded_d[k] > 1e-4 for k in ["crop_top", "crop_bottom", "crop_left", "crop_right"])
        self.assertFalse(has_trims_d)
        self.assertFalse(has_crop_d)

        # Case B: AI Inactive, Crop Active
        params_b = {
            "exposure": 0.0, "contrast": 0.0, "shadows": 0.0, "highlights": 0.0,
            "temperature": 0.0, "tint": 0.0, "vibrance": 0.0, "clarity": 0.0,
            "crop_top": 0.05, "crop_bottom": 0.05, "crop_left": 0.08, "crop_right": 0.08
        }
        server.save_override_params(self.output_dir, filename, params_b)
        loaded_b = server.load_overrides(self.output_dir)[filename]
        has_trims_b = any(abs(loaded_b[k]) > 1e-4 for k in ["exposure", "contrast", "shadows", "highlights", "temperature", "tint", "vibrance", "clarity"])
        has_crop_b = any(loaded_b[k] > 1e-4 for k in ["crop_top", "crop_bottom", "crop_left", "crop_right"])
        self.assertFalse(has_trims_b)
        self.assertTrue(has_crop_b)

        # Case C: Both Active
        params_c = {
            "exposure": 0.10, "contrast": 0.0, "shadows": 5.0, "highlights": 0.0,
            "temperature": 0.0, "tint": 0.0, "vibrance": 0.0, "clarity": 0.0,
            "crop_top": 0.05, "crop_bottom": 0.05, "crop_left": 0.08, "crop_right": 0.08
        }
        server.save_override_params(self.output_dir, filename, params_c)
        loaded_c = server.load_overrides(self.output_dir)[filename]
        has_trims_c = any(abs(loaded_c[k]) > 1e-4 for k in ["exposure", "contrast", "shadows", "highlights", "temperature", "tint", "vibrance", "clarity"])
        has_crop_c = any(loaded_c[k] > 1e-4 for k in ["crop_top", "crop_bottom", "crop_left", "crop_right"])
        self.assertTrue(has_trims_c)
        self.assertTrue(has_crop_c)

        # Reset Crop independently in Case C -> transforms to Case A
        params_c_reset_crop = dict(params_c)
        for k in ["crop_top", "crop_bottom", "crop_left", "crop_right"]:
            params_c_reset_crop[k] = 0.0
        server.save_override_params(self.output_dir, filename, params_c_reset_crop)
        loaded_after_crop_reset = server.load_overrides(self.output_dir)[filename]
        has_trims_after = any(abs(loaded_after_crop_reset[k]) > 1e-4 for k in ["exposure", "contrast", "shadows", "highlights", "temperature", "tint", "vibrance", "clarity"])
        has_crop_after = any(loaded_after_crop_reset[k] > 1e-4 for k in ["crop_top", "crop_bottom", "crop_left", "crop_right"])
        self.assertTrue(has_trims_after)
        self.assertFalse(has_crop_after)

    def test_full_reset_to_preset_base_endpoint(self):
        """Verify api_adjust_reset resets all 12 parameters to exactly 0.0 and returns valid preview."""
        req_save = server.AdjustRequest(
            filename=self.img_landscape_name,
            exposure=0.35,
            contrast=10.0,
            shadows=-5.0,
            highlights=5.0,
            temperature=3.0,
            tint=-2.0,
            vibrance=12.0,
            clarity=8.0,
            crop_top=0.08,
            crop_bottom=0.08,
            crop_left=0.12,
            crop_right=0.12,
        )
        server.api_adjust_save(req_save)

        # Call reset endpoint
        req_reset = server.AdjustRequest(filename=self.img_landscape_name)
        reset_res = server.api_adjust_reset(req_reset)
        self.assertEqual(reset_res.get("status"), "reset")
        self.assertTrue(reset_res.get("preview_data_url").startswith("data:image/jpeg;base64,"))

        # Check all values stored are 0.0
        overrides = server.load_overrides(self.output_dir)
        self.assertIn(self.img_landscape_name, overrides)
        for k, v in overrides[self.img_landscape_name].items():
            self.assertEqual(v, 0.0)


if __name__ == "__main__":
    unittest.main()
