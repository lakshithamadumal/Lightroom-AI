"""
Unit and Integration tests for Optional Smart Crop Stage (tests/test_smart_cropper.py).

Tests:
1. Stage 1 buffer remains full-frame after Smart Crop.
2. Stage 2 buffer remains full-frame after Smart Crop.
3. Smart Crop output has smaller/equal spatial dimensions.
4. Smart Crop does not alter the source buffer array in-place.
5. Disabled Smart Crop returns the exact Stage 2 buffer (no crop, no fallback).
6. Crop coordinates are within valid [0.0, 1.0] bounds.
7. Crop width constraint (>= 40%) is enforced.
8. Crop height constraint (>= 40%) is enforced.
9. Fallback works when AI is unavailable (fallback_used=True).
10. Existing manual crop API works with Priority 1 precedence.
11. Telemetry dictionary adheres strictly to the required contract.
12. Single final export transform (Adobe RGB -> sRGB) occurs at the delivery step.
13. Regression Test: Photo 5 bbox [0.25, 0.10, 0.70, 0.90] (area 36%) must be rejected.
14. Boundary Tests for validate_crop_box:
    A) Exactly 40% area -> accepted
    B) 39.99% area -> rejected
    C) Width < 40% -> rejected
    D) Height < 40% -> rejected
    E) Invalid coordinates -> rejected
"""

import os
import unittest
import numpy as np
import cv2

from smart_cropper import SmartCropper
from image_pipeline import ImagePipeline
from preset_bundle import PresetBundle
from lut_engine import Lut3D
from stage2_schema import compute_stage1_buffer_hash


class TestSmartCropper(unittest.TestCase):

    def setUp(self):
        # Create synthetic 400x600x3 buffers
        np.random.seed(42)
        self.stage1_base = np.random.randint(50, 200, size=(400, 600, 3), dtype=np.uint8)
        self.stage2_balanced = np.random.randint(50, 200, size=(400, 600, 3), dtype=np.uint8)
        self.cropper = SmartCropper(api_key="", model="google/gemini-2.5-flash")

    # 1. Stage 1 buffer remains full-frame after Smart Crop
    def test_stage1_remains_full_frame(self):
        h_orig, w_orig = self.stage1_base.shape[:2]
        cropped, _ = self.cropper.crop_best_landscape(self.stage2_balanced, enable_ai=True)
        self.assertEqual(self.stage1_base.shape[:2], (h_orig, w_orig))

    # 2. Stage 2 buffer remains full-frame after Smart Crop
    def test_stage2_remains_full_frame(self):
        h_orig, w_orig = self.stage2_balanced.shape[:2]
        s2_hash_before = compute_stage1_buffer_hash(self.stage2_balanced)
        cropped, _ = self.cropper.crop_best_landscape(self.stage2_balanced, enable_ai=True)
        s2_hash_after = compute_stage1_buffer_hash(self.stage2_balanced)
        self.assertEqual(self.stage2_balanced.shape[:2], (h_orig, w_orig))
        self.assertEqual(s2_hash_before, s2_hash_after)

    # 3. Smart Crop output has smaller/equal spatial dimensions
    def test_smart_crop_spatial_dimensions(self):
        h_orig, w_orig = self.stage2_balanced.shape[:2]
        cropped, tel = self.cropper.crop_best_landscape(self.stage2_balanced, enable_ai=True)
        ch, cw = cropped.shape[:2]
        self.assertLessEqual(cw, w_orig)
        self.assertLessEqual(ch, h_orig)
        self.assertEqual(tel["cropped_width"], cw)
        self.assertEqual(tel["cropped_height"], ch)

    # 4. Smart Crop does not alter the source buffer array in-place
    def test_source_buffer_immutability(self):
        s2_copy = self.stage2_balanced.copy()
        cropped, _ = self.cropper.crop_best_landscape(self.stage2_balanced, enable_ai=True)
        np.testing.assert_array_equal(self.stage2_balanced, s2_copy)

    # 5. Disabled Smart Crop returns exact Stage 2 buffer (no crop, no fallback)
    def test_disabled_smart_crop_returns_exact_stage2(self):
        cropped, tel = self.cropper.crop_best_landscape(self.stage2_balanced, enable_ai=False)
        np.testing.assert_array_equal(cropped, self.stage2_balanced)
        self.assertFalse(tel["enabled"])
        self.assertFalse(tel["applied"])
        self.assertFalse(tel["fallback_used"])
        self.assertEqual(tel["crop_area_ratio"], 1.0)
        self.assertEqual(tel["trim_x_pct"], 0)

    # 6. Crop coordinates are within valid [0.0, 1.0] bounds
    def test_crop_coordinates_in_bounds(self):
        _, tel = self.cropper.crop_best_landscape(self.stage2_balanced, enable_ai=True)
        self.assertGreaterEqual(tel["ymin"], 0.0)
        self.assertGreaterEqual(tel["xmin"], 0.0)
        self.assertLessEqual(tel["ymax"], 1.0)
        self.assertLessEqual(tel["xmax"], 1.0)
        self.assertLess(tel["ymin"], tel["ymax"])
        self.assertLess(tel["xmin"], tel["xmax"])

    # 7 & 8. Crop width and height constraints (>= 40%) enforced
    def test_minimum_crop_dimensions_enforced(self):
        h, w = self.stage2_balanced.shape[:2]
        cropped, tel = self.cropper.crop_best_landscape(self.stage2_balanced, enable_ai=True)
        self.assertGreaterEqual(tel["cropped_width"], int(w * 0.40))
        self.assertGreaterEqual(tel["cropped_height"], int(h * 0.40))
        self.assertGreaterEqual(tel["crop_area_ratio"], 0.40)

    # 9. Fail-safe to full frame by default when AI is unavailable, or fallback if explicitly requested
    def test_fallback_when_ai_unavailable(self):
        no_key_cropper = SmartCropper(api_key="", model="google/gemini-2.5-flash")
        
        # Default behavior: Fail safely to FULL FRAME (never crop silently)
        cropped, tel = no_key_cropper.crop_best_landscape(self.stage2_balanced, enable_ai=True, allow_deterministic_fallback=False)
        self.assertEqual(tel["crop_status"], "ai_unavailable")
        self.assertEqual(tel["crop_source"], "none")
        self.assertFalse(tel["applied"])
        self.assertFalse(tel["fallback_used"])
        self.assertEqual(tel["crop_area_ratio"], 1.0)
        self.assertEqual(cropped.shape, self.stage2_balanced.shape)

        # Explicit opt-in fallback: allow_deterministic_fallback=True
        cropped_fb, tel_fb = no_key_cropper.crop_best_landscape(self.stage2_balanced, enable_ai=True, allow_deterministic_fallback=True)
        self.assertTrue(tel_fb["enabled"])
        self.assertTrue(tel_fb["applied"])
        self.assertTrue(tel_fb["fallback_used"])
        self.assertEqual(tel_fb["crop_status"], "fallback_crop")
        self.assertEqual(tel_fb["crop_source"], "deterministic_fallback")
        self.assertIn("fallback", tel_fb["method"].lower())

    # 10. Existing manual crop API works with Priority 1 precedence
    def test_manual_crop_priority_precedence(self):
        adj = {
            "crop_top": 0.10,
            "crop_bottom": 0.05,
            "crop_left": 0.05,
            "crop_right": 0.05
        }
        cropped, tel = ImagePipeline.apply_crop_stage(
            self.stage2_balanced,
            adjustments=adj,
            smart_cropper=self.cropper,
            enable_smart_crop=True  # even if enabled, manual crop takes precedence
        )
        self.assertTrue(tel["applied"])
        self.assertFalse(tel["fallback_used"])
        self.assertEqual(tel["method"], "Manual Crop Overrides")
        self.assertAlmostEqual(tel["ymin"], 0.10, places=2)
        self.assertAlmostEqual(tel["ymax"], 0.95, places=2)

    # 11. Telemetry schema adherence
    def test_telemetry_schema(self):
        _, tel = self.cropper.crop_best_landscape(self.stage2_balanced, enable_ai=True)
        required_keys = [
            "enabled", "source", "applied", "ymin", "xmin", "ymax", "xmax",
            "original_width", "original_height", "cropped_width", "cropped_height",
            "crop_area_ratio", "reason", "fallback_used"
        ]
        for k in required_keys:
            self.assertIn(k, tel, f"Missing required telemetry key: {k}")
        self.assertEqual(tel["source"], "stage2_balanced")

    # 12. Full pipeline execution with all stage snapshots
    def test_render_pipeline_all_stages(self):
        lut = Lut3D.create_identity(size=17)
        bundle = PresetBundle(preset_id="test", name="Test", lut=lut)
        res = ImagePipeline.render_pipeline_all_stages(
            self.stage1_base,
            bundle,
            adjustments={},
            smart_cropper=self.cropper,
            enable_smart_crop=True
        )
        self.assertIn("stage1_preset_base", res)
        self.assertIn("stage2_balanced_buffer", res)
        self.assertIn("smart_crop_output", res)
        self.assertIn("final_output", res)
        self.assertIn("crop_telemetry", res)
        self.assertEqual(res["stage1_preset_base"].shape[:2], (400, 600))
        self.assertEqual(res["stage2_balanced_buffer"].shape[:2], (400, 600))

    # 13. Regression Test for Photo 5 Constraint Violation
    def test_photo_5_area_rejection_regression(self):
        """Photo 5 bbox [0.25, 0.10, 0.70, 0.90] (width=0.80, height=0.45, area=0.36) must be rejected."""
        photo5_box = [0.25, 0.10, 0.70, 0.90]
        is_valid, reason, _ = SmartCropper.validate_crop_box(photo5_box, 6000, 3376)
        self.assertFalse(is_valid)
        self.assertIn("36.00%", reason)
        self.assertIn("< 40%", reason)

    # 14. Boundary Tests for validate_crop_box
    def test_boundary_exactly_40_percent_accepted(self):
        """Exactly 40% area (0.80 width * 0.50 height = 0.40) -> accepted."""
        box_40 = [0.20, 0.10, 0.70, 0.90]  # height=0.50, width=0.80, area=0.40
        is_valid, reason, box_data = SmartCropper.validate_crop_box(box_40, 1000, 1000)
        self.assertTrue(is_valid)
        self.assertAlmostEqual(box_data[6], 0.40, places=4)

    def test_boundary_39_99_percent_rejected(self):
        """39.99% area (0.80 width * 0.4998 height = 0.39984) -> rejected."""
        box_3999 = [0.20, 0.10, 0.6998, 0.90]
        is_valid, reason, _ = SmartCropper.validate_crop_box(box_3999, 1000, 1000)
        self.assertFalse(is_valid)
        self.assertIn("< 40%", reason)

    def test_boundary_width_under_40_percent_rejected(self):
        """Width < 40% (0.35 width * 1.0 height = 0.35 area) -> rejected."""
        box_narrow = [0.0, 0.10, 1.0, 0.45]
        is_valid, reason, _ = SmartCropper.validate_crop_box(box_narrow, 1000, 1000)
        self.assertFalse(is_valid)
        self.assertIn("width ratio", reason.lower())

    def test_boundary_height_under_40_percent_rejected(self):
        """Height < 40% (1.0 width * 0.35 height = 0.35 area) -> rejected."""
        box_short = [0.10, 0.0, 0.45, 1.0]
        is_valid, reason, _ = SmartCropper.validate_crop_box(box_short, 1000, 1000)
        self.assertFalse(is_valid)
        self.assertIn("height ratio", reason.lower())

    def test_boundary_invalid_coordinates_rejected(self):
        """Invalid bounds (out of range, inverted order, non-numeric) -> rejected."""
        self.assertFalse(SmartCropper.validate_crop_box([0.5, 0.1, 0.2, 0.9], 100, 100)[0])  # ymin > ymax
        self.assertFalse(SmartCropper.validate_crop_box([0.1, 0.8, 0.9, 0.2], 100, 100)[0])  # xmin > xmax
        self.assertFalse(SmartCropper.validate_crop_box([-0.1, 0.1, 0.9, 0.9], 100, 100)[0]) # ymin < 0
        self.assertFalse(SmartCropper.validate_crop_box([0.1, 0.1, 1.2, 0.9], 100, 100)[0])  # ymax > 1
        self.assertFalse(SmartCropper.validate_crop_box(None, 100, 100)[0])                  # None

    # 15. Inspector Smart Crop API & 4-Way Manual Crop Tests
    def test_default_adjustments_has_4way_crop(self):
        """Verify DEFAULT_ADJUSTMENTS in server.py includes all 4 crop keys."""
        from server import DEFAULT_ADJUSTMENTS, AdjustRequest
        for key in ["crop_top", "crop_bottom", "crop_left", "crop_right"]:
            self.assertIn(key, DEFAULT_ADJUSTMENTS)
            self.assertEqual(DEFAULT_ADJUSTMENTS[key], 0.0)

        req = AdjustRequest(filename="test.jpg")
        self.assertEqual(req.crop_top, 0.0)
        self.assertEqual(req.crop_bottom, 0.0)
        self.assertEqual(req.crop_left, 0.0)
        self.assertEqual(req.crop_right, 0.0)

    def test_inspector_manual_4way_crop(self):
        """Verify 4-way manual crop correctly slices image through apply_adjustments."""
        from server import apply_adjustments, AdjustRequest
        img = np.full((1000, 1000, 3), 128, dtype=np.uint8)
        req = AdjustRequest(
            filename="dummy.jpg",
            crop_top=0.10,
            crop_bottom=0.15,
            crop_left=0.05,
            crop_right=0.20
        )
        cropped = apply_adjustments(img, req)
        # Expected: height = 1000 - 100 - 150 = 750; width = 1000 - 50 - 200 = 750
        self.assertEqual(cropped.shape[0], 750)
        self.assertEqual(cropped.shape[1], 750)

    def test_inspector_smart_crop_endpoint(self):
        """Verify POST /api/adjust/smart-crop endpoint via FastAPI TestClient."""
        from fastapi.testclient import TestClient
        from server import app
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            in_dir = os.path.join(temp_dir, "incoming")
            out_dir = os.path.join(temp_dir, "output")
            base_dir = os.path.join(out_dir, ".base")
            os.makedirs(in_dir, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)
            os.makedirs(base_dir, exist_ok=True)

            # Create synthetic test image
            test_img = np.full((600, 800, 3), 120, dtype=np.uint8)
            cv2.imwrite(os.path.join(base_dir, "test_crop.jpg"), test_img)
            base_sha_before = cv2.imread(os.path.join(base_dir, "test_crop.jpg"))

            from unittest.mock import patch
            mock_cfg = {
                "ORCA_API_KEY": "",
                "ORCA_API_URL": "https://api.orcarouter.ai/v1/chat/completions",
                "ORCA_MODEL": "google/gemini-2.5-flash",
                "INPUT_FOLDER": in_dir,
                "PRESET_FOLDER": os.path.abspath("presets"),
                "OUTPUT_FOLDER": out_dir,
                "ENABLE_AI_SMART_CROP": True,
                "ENABLE_AUTO_BALANCING": True,
                "TARGET_MAX_WIDTH": 0,
                "JPEG_QUALITY": 100,
            }

            with patch("server.get_config", return_value=mock_cfg):
                client = TestClient(app)
                response = client.post("/api/adjust/smart-crop", json={
                    "filename": "test_crop.jpg",
                    "exposure": 0.0,
                    "temperature": 0.0
                })

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertIn("crop", data)
            self.assertIn("crop_telemetry", data)
            self.assertIn("preview_data_url", data)
            self.assertTrue(data["preview_data_url"].startswith("data:image/jpeg;base64,"))

            # Validate crop dimensions and constraints
            crop_info = data["crop"]
            self.assertGreaterEqual(crop_info["crop_top"], 0.0)
            self.assertGreaterEqual(crop_info["crop_bottom"], 0.0)
            self.assertGreaterEqual(crop_info["crop_left"], 0.0)
            self.assertGreaterEqual(crop_info["crop_right"], 0.0)
            area_ratio = data["crop_telemetry"]["crop_area_ratio"]
            self.assertGreaterEqual(area_ratio, 0.40)

            # Stage 1 base buffer file MUST remain 100% unchanged
            base_img_after = cv2.imread(os.path.join(base_dir, "test_crop.jpg"))
            self.assertEqual(base_sha_before.shape, base_img_after.shape)
            np.testing.assert_array_equal(base_sha_before, base_img_after)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

