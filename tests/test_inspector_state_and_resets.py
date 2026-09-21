import unittest
import os
import shutil
import tempfile
import json
import numpy as np
import cv2
from PIL import Image

import server


class TestInspectorStateAndResets(unittest.TestCase):
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

        # Create a sample test image (landscape 600x400)
        cls.sample_img_name = "test_landscape.jpg"
        cls.sample_img_path = os.path.join(cls.input_dir, cls.sample_img_name)
        img_arr = np.zeros((400, 600, 3), dtype=np.uint8)
        img_arr[:, :] = [120, 150, 180]  # BGR
        cv2.imwrite(cls.sample_img_path, img_arr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        self.config_patcher = unittest.mock.patch("server.get_config", return_value={
            "ORCA_API_KEY": "",
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

        # Clean overrides and telemetry files
        overrides_path = server._get_overrides_file(self.output_dir)
        if os.path.exists(overrides_path):
            os.remove(overrides_path)
        telemetry_path = server._get_telemetry_file(self.output_dir)
        if os.path.exists(telemetry_path):
            os.remove(telemetry_path)

    def tearDown(self):
        self.config_patcher.stop()

    def test_overrides_round_trip_and_persistence(self):
        filename = self.sample_img_name
        params = {
            "exposure": 0.20,
            "contrast": 10.0,
            "shadows": 5.0,
            "highlights": -10.0,
            "temperature": 4.0,
            "tint": -2.0,
            "vibrance": 15.0,
            "clarity": 10.0,
            "crop_top": 0.05,
            "crop_bottom": 0.05,
            "crop_left": 0.10,
            "crop_right": 0.10,
        }
        server.save_override_params(self.output_dir, filename, params)
        loaded = server.load_overrides(self.output_dir)
        self.assertIn(filename, loaded)
        self.assertAlmostEqual(loaded[filename]["exposure"], 0.20)
        self.assertAlmostEqual(loaded[filename]["crop_left"], 0.10)
        self.assertAlmostEqual(loaded[filename]["crop_top"], 0.05)

    def test_telemetry_round_trip_and_persistence(self):
        filename = self.sample_img_name
        adj_tel = {
            "ai_status": "ai_analyzed",
            "scene_type": "Landscape",
            "confidence": 0.92,
            "reason": "Clear sky and warm lighting"
        }
        crop_tel = {
            "crop_status": "ai_crop",
            "crop_applied": True,
            "crop_area_ratio": 0.85,
            "method": "Smart Landscape",
            "reason": "Rule of thirds alignment"
        }
        tele_combined = {
            "adjust_telemetry": adj_tel,
            "crop_telemetry": crop_tel,
        }
        server.save_photo_telemetry(self.output_dir, filename, tele_combined)
        loaded = server.load_telemetry(self.output_dir)
        self.assertIn(filename, loaded)
        self.assertEqual(loaded[filename]["adjust_telemetry"]["ai_status"], "ai_analyzed")
        self.assertEqual(loaded[filename]["crop_telemetry"]["crop_status"], "ai_crop")
        self.assertAlmostEqual(loaded[filename]["crop_telemetry"]["crop_area_ratio"], 0.85)

    def test_api_adjust_preview_rendering(self):
        req = server.AdjustRequest(
            filename=self.sample_img_name,
            exposure=0.15,
            contrast=5.0,
            shadows=0.0,
            highlights=0.0,
            temperature=0.0,
            tint=0.0,
            vibrance=0.0,
            clarity=0.0,
            crop_top=0.05,
            crop_bottom=0.05,
            crop_left=0.05,
            crop_right=0.05,
        )

        res = server.api_adjust_preview(req)
        self.assertEqual(res.get("status"), "ok")
        self.assertTrue(res.get("preview_data_url").startswith("data:image/jpeg;base64,"))

    def test_api_adjust_save_and_get_photos(self):
        req = server.AdjustRequest(
            filename=self.sample_img_name,
            exposure=-0.10,
            contrast=0.0,
            shadows=10.0,
            highlights=-5.0,
            temperature=-2.0,
            tint=1.0,
            vibrance=5.0,
            clarity=0.0,
            crop_top=0.02,
            crop_bottom=0.02,
            crop_left=0.04,
            crop_right=0.04,
        )

        save_res = server.api_adjust_save(req)
        self.assertEqual(save_res.get("status"), "saved")
        self.assertAlmostEqual(save_res["adjustments"]["exposure"], -0.10)
        self.assertAlmostEqual(save_res["adjustments"]["crop_left"], 0.04)

        # Verify api_get_incoming_photos includes saved adjustments
        photos_res = server.api_get_incoming_photos()
        self.assertGreaterEqual(photos_res["total"], 1)
        found = next((p for p in photos_res["photos"] if p["filename"] == self.sample_img_name), None)
        self.assertIsNotNone(found)
        self.assertTrue(found["is_processed"])
        self.assertAlmostEqual(found["adjustments"]["exposure"], -0.10)
        self.assertAlmostEqual(found["adjustments"]["crop_top"], 0.02)

    def test_api_adjust_reset(self):
        req = server.AdjustRequest(
            filename=self.sample_img_name,
            exposure=0.30,
            contrast=15.0,
            shadows=0.0,
            highlights=0.0,
            temperature=0.0,
            tint=0.0,
            vibrance=0.0,
            clarity=0.0,
            crop_top=0.10,
            crop_bottom=0.10,
            crop_left=0.10,
            crop_right=0.10,
        )

        server.api_adjust_save(req)

        req_reset = server.AdjustRequest(filename=self.sample_img_name)
        reset_res = server.api_adjust_reset(req_reset)
        self.assertEqual(reset_res.get("status"), "reset")
        self.assertTrue(reset_res.get("preview_data_url").startswith("data:image/jpeg;base64,"))

        # Check that overrides file has all zero adjustments for this file
        overrides = server.load_overrides(self.output_dir)
        self.assertIn(self.sample_img_name, overrides)
        for val in overrides[self.sample_img_name].values():
            self.assertEqual(val, 0.0)


if __name__ == "__main__":
    unittest.main()
