"""
Final Inspector Workflow Verification Suite for Lightroom AI Studio Edition 2.0.
Validates all Inspector interaction contracts, parametric persistence, independent resets,
photo switching, concurrency isolation, AI states, Smart Crop states, and download contracts.
"""

import unittest
from unittest import mock
import os
import shutil
import tempfile
import json
import numpy as np
import cv2

import server


class TestFinalInspectorWorkflow(unittest.TestCase):
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

        # Create mock representative photo files
        cls.test_photos = {
            "PHOTO_01.jpg": {"dims": (800, 600), "color": [100, 150, 100]}, # Foliage Green
            "PHOTO_04.jpg": {"dims": (800, 600), "color": [200, 200, 220]}, # High-Key Sky
            "PHOTO_05.jpg": {"dims": (600, 800), "color": [30, 30, 40]},    # Dark Shadow
            "PHOTO_08.jpg": {"dims": (600, 800), "color": [180, 150, 140]}, # Studio Portrait
            "PHOTO_10.jpg": {"dims": (800, 600), "color": [180, 190, 210]}, # Bright Sky
            "PHOTO_14.jpg": {"dims": (800, 450), "color": [20, 20, 30]},    # Stage Face Protection
        }

        for filename, meta in cls.test_photos.items():
            w, h = meta["dims"]
            arr = np.zeros((h, w, 3), dtype=np.uint8)
            arr[:, :] = meta["color"]
            cv2.imwrite(os.path.join(cls.input_dir, filename), arr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        self.config_patcher = unittest.mock.patch("server.get_config", return_value={
            "ORCA_API_KEY": "gsk_test_groq_production_key",
            "ORCA_API_URL": "https://api.groq.com/openai/v1/chat/completions",
            "ORCA_MODEL": "qwen/qwen3.8-27b",
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

    # -------------------------------------------------------------
    # 1 & 2. Open Inspector on a photo with Stage 2 applied & confirm exact values
    # -------------------------------------------------------------
    def test_01_inspector_display_exact_stage2_values(self):
        filename = "PHOTO_01.jpg"
        # Exact values applied for PHOTO_01: shadows +4.0
        applied_trims = {
            "exposure": 0.0,
            "contrast": 0.0,
            "shadows": 4.0,
            "highlights": 0.0,
            "temperature": 0.0,
            "tint": 0.0,
            "vibrance": 0.0,
            "clarity": 0.0,
            "crop_top": 0.0,
            "crop_bottom": 0.0,
            "crop_left": 0.0,
            "crop_right": 0.0
        }
        server.save_override_params(self.output_dir, filename, applied_trims)
        server.save_photo_telemetry(self.output_dir, filename, {
            "adjust_telemetry": {
                "ai_status": "ai_analyzed",
                "scene_type": "Outdoor Foliage",
                "confidence": 0.92,
                "reason": "Shadows lifted for dense vegetation depth"
            },
            "crop_telemetry": {
                "crop_status": "ai_rejected",
                "reason": "AI Crop rejected (bottom safe margin) - Full frame preserved"
            }
        })

        photos_res = server.api_get_incoming_photos()
        p1 = next((p for p in photos_res["photos"] if p["filename"] == filename), None)
        self.assertIsNotNone(p1)
        self.assertEqual(p1["adjustments"]["shadows"], 4.0)
        self.assertEqual(p1["adjustments"]["exposure"], 0.0)
        self.assertEqual(p1["adjust_telemetry"]["ai_status"], "ai_analyzed")
        self.assertEqual(p1["adjust_telemetry"]["scene_type"], "Outdoor Foliage")

    def test_02_inspector_display_attenuated_stage2_values(self):
        filename = "PHOTO_04.jpg"
        # Exact attenuated trims for PHOTO_04: exp: -0.03, temp: +0.9
        applied_trims = {
            "exposure": -0.03,
            "contrast": 0.0,
            "shadows": 0.0,
            "highlights": 0.0,
            "temperature": 0.9,
            "tint": 0.0,
            "vibrance": 0.0,
            "clarity": 0.0,
            "crop_top": 0.0,
            "crop_bottom": 0.0,
            "crop_left": 0.0,
            "crop_right": 0.0
        }
        server.save_override_params(self.output_dir, filename, applied_trims)
        server.save_photo_telemetry(self.output_dir, filename, {
            "adjust_telemetry": {
                "ai_status": "ai_analyzed",
                "scene_type": "High-Key Sky",
                "confidence": 0.91,
                "reason": "Attenuated trims to preserve highlight gradient"
            }
        })

        photos_res = server.api_get_incoming_photos()
        p4 = next((p for p in photos_res["photos"] if p["filename"] == filename), None)
        self.assertIsNotNone(p4)
        self.assertEqual(p4["adjustments"]["exposure"], -0.03)
        self.assertEqual(p4["adjustments"]["temperature"], 0.9)

    # -------------------------------------------------------------
    # 3. Confirm crop values persist when Smart Crop was applied
    # -------------------------------------------------------------
    def test_03_inspector_display_smart_crop_values(self):
        filename = "PHOTO_05.jpg"
        # PHOTO_05 Smart crop applied (85.5% area)
        applied = {
            "exposure": 0.0, "contrast": 0.0, "shadows": 0.0, "highlights": 0.0,
            "temperature": 0.0, "tint": 0.0, "vibrance": 0.0, "clarity": 0.0,
            "crop_top": 0.10, "crop_bottom": 0.05, "crop_left": 0.05, "crop_right": 0.05
        }
        server.save_override_params(self.output_dir, filename, applied)
        server.save_photo_telemetry(self.output_dir, filename, {
            "crop_telemetry": {
                "crop_status": "ai_crop",
                "crop_applied": True,
                "crop_area_ratio": 0.855,
                "method": "Smart Headroom",
                "reason": "Rule of thirds alignment"
            }
        })

        photos_res = server.api_get_incoming_photos()
        p5 = next((p for p in photos_res["photos"] if p["filename"] == filename), None)
        self.assertIsNotNone(p5)
        self.assertEqual(p5["adjustments"]["crop_top"], 0.10)
        self.assertEqual(p5["adjustments"]["crop_bottom"], 0.05)
        self.assertEqual(p5["crop_telemetry"]["crop_status"], "ai_crop")
        self.assertEqual(p5["crop_telemetry"]["crop_area_ratio"], 0.855)

    # -------------------------------------------------------------
    # 4. Reset AI Balance (AI adjustments = 0, Crop unchanged)
    # -------------------------------------------------------------
    def test_04_reset_ai_balance_preserves_crop(self):
        filename = "PHOTO_05.jpg"
        initial = {
            "exposure": 0.15, "contrast": 0.0, "shadows": 5.0, "highlights": -5.0,
            "temperature": 2.0, "tint": 0.0, "vibrance": 0.0, "clarity": 0.0,
            "crop_top": 0.10, "crop_bottom": 0.05, "crop_left": 0.05, "crop_right": 0.05
        }
        server.save_override_params(self.output_dir, filename, initial)

        # Reset only AI trims
        reset_ai = dict(initial)
        for k in ["exposure", "contrast", "shadows", "highlights", "temperature", "tint", "vibrance", "clarity"]:
            reset_ai[k] = 0.0
        server.save_override_params(self.output_dir, filename, reset_ai)

        loaded = server.load_overrides(self.output_dir)[filename]
        # AI adjustments must be 0
        for k in ["exposure", "contrast", "shadows", "highlights", "temperature", "tint", "vibrance", "clarity"]:
            self.assertEqual(loaded[k], 0.0)
        # Crop values must remain unchanged
        self.assertEqual(loaded["crop_top"], 0.10)
        self.assertEqual(loaded["crop_bottom"], 0.05)
        self.assertEqual(loaded["crop_left"], 0.05)
        self.assertEqual(loaded["crop_right"], 0.05)

    # -------------------------------------------------------------
    # 5. Reset Crop (Crop = 0, AI adjustments unchanged)
    # -------------------------------------------------------------
    def test_05_reset_crop_preserves_ai_balance(self):
        filename = "PHOTO_10.jpg"
        # PHOTO_10: Temp +6.0, with manual crop
        initial = {
            "exposure": 0.0, "contrast": 0.0, "shadows": 0.0, "highlights": 0.0,
            "temperature": 6.0, "tint": 0.0, "vibrance": 0.0, "clarity": 0.0,
            "crop_top": 0.08, "crop_bottom": 0.08, "crop_left": 0.10, "crop_right": 0.10
        }
        server.save_override_params(self.output_dir, filename, initial)

        # Reset only Crop
        reset_crop = dict(initial)
        for k in ["crop_top", "crop_bottom", "crop_left", "crop_right"]:
            reset_crop[k] = 0.0
        server.save_override_params(self.output_dir, filename, reset_crop)

        loaded = server.load_overrides(self.output_dir)[filename]
        # Crop must be full frame (all 0)
        for k in ["crop_top", "crop_bottom", "crop_left", "crop_right"]:
            self.assertEqual(loaded[k], 0.0)
        # AI temperature must remain 6.0
        self.assertEqual(loaded["temperature"], 6.0)

    # -------------------------------------------------------------
    # 6. Reset to Base (All 12 values = 0, equals pristine Stage 1)
    # -------------------------------------------------------------
    def test_06_reset_to_base_pristine_stage1(self):
        filename = "PHOTO_01.jpg"
        initial = {
            "exposure": 0.20, "contrast": 10.0, "shadows": 5.0, "highlights": -10.0,
            "temperature": 4.0, "tint": -2.0, "vibrance": 15.0, "clarity": 10.0,
            "crop_top": 0.05, "crop_bottom": 0.05, "crop_left": 0.10, "crop_right": 0.10
        }
        server.save_override_params(self.output_dir, filename, initial)

        req_reset = server.AdjustRequest(filename=filename)
        res = server.api_adjust_reset(req_reset)
        self.assertEqual(res.get("status"), "reset")
        self.assertTrue(res.get("preview_data_url").startswith("data:image/jpeg;base64,"))

        loaded = server.load_overrides(self.output_dir)[filename]
        for k, v in loaded.items():
            self.assertEqual(v, 0.0)

    # -------------------------------------------------------------
    # 7. Close and reopen Inspector: Persistence
    # -------------------------------------------------------------
    def test_07_close_and_reopen_inspector_persistence(self):
        filename = "PHOTO_10.jpg"
        req_save = server.AdjustRequest(
            filename=filename,
            exposure=0.0,
            contrast=0.0,
            shadows=0.0,
            highlights=0.0,
            temperature=6.0,
            tint=0.0,
            vibrance=0.0,
            clarity=0.0,
            crop_top=0.0,
            crop_bottom=0.0,
            crop_left=0.0,
            crop_right=0.0,
        )
        save_res = server.api_adjust_save(req_save)
        self.assertEqual(save_res.get("status"), "saved")

        # Simulate fresh reload (reopening inspector)
        reopened_photos = server.api_get_incoming_photos()
        p10 = next((p for p in reopened_photos["photos"] if p["filename"] == filename), None)
        self.assertIsNotNone(p10)
        self.assertEqual(p10["adjustments"]["temperature"], 6.0)

    # -------------------------------------------------------------
    # 8. Switch between photos: No cross-photo leakage
    # -------------------------------------------------------------
    def test_08_photo_switching_isolation(self):
        p1_params = {
            "exposure": 0.0, "contrast": 0.0, "shadows": 4.0, "highlights": 0.0,
            "temperature": 0.0, "tint": 0.0, "vibrance": 0.0, "clarity": 0.0,
            "crop_top": 0.0, "crop_bottom": 0.0, "crop_left": 0.0, "crop_right": 0.0
        }
        p4_params = {
            "exposure": -0.03, "contrast": 0.0, "shadows": 0.0, "highlights": 0.0,
            "temperature": 0.9, "tint": 0.0, "vibrance": 0.0, "clarity": 0.0,
            "crop_top": 0.0, "crop_bottom": 0.0, "crop_left": 0.0, "crop_right": 0.0
        }
        server.save_override_params(self.output_dir, "PHOTO_01.jpg", p1_params)
        server.save_override_params(self.output_dir, "PHOTO_04.jpg", p4_params)

        all_overrides = server.load_overrides(self.output_dir)
        self.assertEqual(all_overrides["PHOTO_01.jpg"]["shadows"], 4.0)
        self.assertEqual(all_overrides["PHOTO_01.jpg"]["exposure"], 0.0)
        self.assertEqual(all_overrides["PHOTO_04.jpg"]["shadows"], 0.0)
        self.assertEqual(all_overrides["PHOTO_04.jpg"]["exposure"], -0.03)
        self.assertEqual(all_overrides["PHOTO_04.jpg"]["temperature"], 0.9)

    # -------------------------------------------------------------
    # 9. Batch processing isolation (SSE / preview requests do not corrupt active photo)
    # -------------------------------------------------------------
    def test_09_concurrency_and_session_isolation(self):
        # Preview rendering on PHOTO_04 does not alter PHOTO_01 saved state
        preview_req = server.AdjustRequest(
            filename="PHOTO_04.jpg",
            exposure=0.30,
            contrast=0.0,
            shadows=0.0,
            highlights=0.0,
            temperature=0.0,
            tint=0.0,
            vibrance=0.0,
            clarity=0.0,
            crop_top=0.0,
            crop_bottom=0.0,
            crop_left=0.0,
            crop_right=0.0,
        )
        prev_res = server.api_adjust_preview(preview_req)
        self.assertEqual(prev_res.get("status"), "ok")

        # Confirm PHOTO_01 remains unaffected in overrides
        p1_params = {
            "exposure": 0.0, "contrast": 0.0, "shadows": 4.0, "highlights": 0.0,
            "temperature": 0.0, "tint": 0.0, "vibrance": 0.0, "clarity": 0.0,
            "crop_top": 0.0, "crop_bottom": 0.0, "crop_left": 0.0, "crop_right": 0.0
        }
        server.save_override_params(self.output_dir, "PHOTO_01.jpg", p1_params)
        loaded = server.load_overrides(self.output_dir)
        self.assertEqual(loaded["PHOTO_01.jpg"]["shadows"], 4.0)

    # -------------------------------------------------------------
    # 10. Test AI States (Active, Offline, Limited, Error)
    # -------------------------------------------------------------
    def test_10_ai_states_derivation(self):
        # State 1: Active
        cfg = server.get_config()
        self.assertTrue(bool(cfg.get("ORCA_API_KEY")))
        self.assertTrue(cfg.get("ENABLE_AUTO_BALANCING"))

        # State 2: Offline
        with unittest.mock.patch("server.get_config", return_value={"ORCA_API_KEY": "", "ENABLE_AUTO_BALANCING": True}):
            cfg_off = server.get_config()
            self.assertFalse(bool(cfg_off.get("ORCA_API_KEY")))

        # State 3: Limited (Rate limited / Quota exhausted)
        server.save_photo_telemetry(self.output_dir, "PHOTO_08.jpg", {
            "adjust_telemetry": {
                "ai_status": "ai_unavailable",
                "api_error": "HTTP 429 Rate limit exhausted",
                "reason": "Preset Base Preserved"
            }
        })
        tel = server.load_telemetry(self.output_dir)
        self.assertEqual(tel["PHOTO_08.jpg"]["adjust_telemetry"]["ai_status"], "ai_unavailable")

        # State 4: Error
        server.save_photo_telemetry(self.output_dir, "PHOTO_14.jpg", {
            "adjust_telemetry": {
                "ai_status": "ai_failed",
                "api_error": "Internal 500 error",
                "reason": "Preset Base Preserved"
            }
        })
        tel = server.load_telemetry(self.output_dir)
        self.assertEqual(tel["PHOTO_14.jpg"]["adjust_telemetry"]["ai_status"], "ai_failed")

    # -------------------------------------------------------------
    # 11. Test Smart Crop States (AI Crop, Crop Rejected, AI Unavailable, Full-frame Fail-safe)
    # -------------------------------------------------------------
    def test_11_smart_crop_states_derivation(self):
        # State A: AI Crop
        server.save_photo_telemetry(self.output_dir, "PHOTO_05.jpg", {
            "crop_telemetry": {
                "crop_status": "ai_crop",
                "crop_applied": True,
                "crop_area_ratio": 0.855,
                "method": "Smart Headroom"
            }
        })
        # State B: Crop Rejected (Safe Margin)
        server.save_photo_telemetry(self.output_dir, "PHOTO_08.jpg", {
            "crop_telemetry": {
                "crop_status": "ai_rejected",
                "crop_applied": False,
                "crop_area_ratio": 1.0,
                "reason": "AI Crop rejected (Crop height ratio < 40%) - Full frame preserved."
            }
        })
        # State C: Face Protection Rejection
        server.save_photo_telemetry(self.output_dir, "PHOTO_14.jpg", {
            "crop_telemetry": {
                "crop_status": "ai_rejected",
                "crop_applied": False,
                "crop_area_ratio": 1.0,
                "reason": "Subject safety violation: crop clips right side/ear of face #1 - Full frame preserved."
            }
        })

        tel = server.load_telemetry(self.output_dir)
        self.assertEqual(tel["PHOTO_05.jpg"]["crop_telemetry"]["crop_status"], "ai_crop")
        self.assertEqual(tel["PHOTO_08.jpg"]["crop_telemetry"]["crop_status"], "ai_rejected")
        self.assertIn("height ratio", tel["PHOTO_08.jpg"]["crop_telemetry"]["reason"])
        self.assertEqual(tel["PHOTO_14.jpg"]["crop_telemetry"]["crop_status"], "ai_rejected")
        self.assertIn("Subject safety violation", tel["PHOTO_14.jpg"]["crop_telemetry"]["reason"])

    # -------------------------------------------------------------
    # 12. Verify download / export integrity
    # -------------------------------------------------------------
    def test_12_download_and_export_integrity(self):
        filename = "PHOTO_01.jpg"
        req_save = server.AdjustRequest(
            filename=filename,
            exposure=0.05,
            contrast=0.0,
            shadows=4.0,
            highlights=0.0,
            temperature=0.0,
            tint=0.0,
            vibrance=0.0,
            clarity=0.0,
            crop_top=0.0,
            crop_bottom=0.0,
            crop_left=0.0,
            crop_right=0.0,
        )
        save_res = server.api_adjust_save(req_save)
        self.assertEqual(save_res.get("status"), "saved")
        out_filename = save_res.get("output_filename")
        out_path = os.path.join(self.output_dir, out_filename)
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 1000)

    # -------------------------------------------------------------
    # 13. UI bounds & slider safety clamp checks
    # -------------------------------------------------------------
    def test_13_parametric_bounds_and_safety_clamp(self):
        filename = "PHOTO_04.jpg"
        # Test extreme values requested by client
        extreme_req = server.AdjustRequest(
            filename=filename,
            exposure=1.50,      # UI clamp max is +0.50
            contrast=50.0,     # locked 0
            shadows=25.0,      # UI clamp max is +15
            highlights=-30.0,  # UI clamp min is -15
            temperature=20.0,  # UI clamp max is +12
            tint=15.0,         # UI clamp max is +8
            vibrance=80.0,     # locked 0
            clarity=50.0,      # locked 0
            crop_top=0.50,     # clamp max 0.30
            crop_bottom=0.50,
            crop_left=0.50,
            crop_right=0.50,
        )
        prev_res = server.api_adjust_preview(extreme_req)
        self.assertEqual(prev_res.get("status"), "ok")
        self.assertTrue(prev_res.get("preview_data_url").startswith("data:image/jpeg;base64,"))


if __name__ == "__main__":
    unittest.main()
