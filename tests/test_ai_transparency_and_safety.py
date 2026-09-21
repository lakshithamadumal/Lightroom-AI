"""
Lightroom AI - AI Execution Transparency and Smart Crop Fail-Safe Test Suite
Validates Stage 2 explicit states, Smart Crop fail-safe to full frame,
error classification (e.g. credit failure), and zero-leak logging.
"""

import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import urllib.error
import io

from stage2_analyzer import Stage2Analyzer
from auto_adjuster import AutoAdjuster
from smart_cropper import SmartCropper


class TestAITransparencyAndSafety(unittest.TestCase):

    def setUp(self):
        # Create a synthetic 100x100 BGR test buffer with values that trigger analysis (not pre-gated)
        self.test_img = np.full((100, 100, 3), 40, dtype=np.uint8)

    # -------------------------------------------------------------------------
    # CASE A: API returns valid corrections -> ai_status = "ai_analyzed"
    # -------------------------------------------------------------------------
    @patch.object(Stage2Analyzer, '_query_vlm')
    def test_case_a_ai_analyzed(self, mock_vlm):
        mock_vlm.return_value = {
            "success": True,
            "parsed": {
                "scene_type": "portrait",
                "needs_correction": True,
                "confidence": 0.88,
                "adjustments": {"exposure_ev": 0.12, "shadows": 4.0},
                "reasoning": "Slight underexposure detected"
            },
            "latency_ms": 320,
            "http_status": 200,
            "finish_reason": "stop"
        }

        analyzer = Stage2Analyzer(api_key="mock_key")
        res = analyzer.analyze_stage2(self.test_img, preset_name="Test Preset", enable_ai=True)

        self.assertEqual(res["ai_status"], "ai_analyzed")
        self.assertTrue(res["needs_correction"])
        self.assertEqual(res["confidence"], 0.88)
        self.assertEqual(res["adjustments"]["exposure_ev"], 0.12)
        self.assertIsNone(res["api_error"])

        # Verify AutoAdjuster wraps correctly
        adjuster = AutoAdjuster(api_key="mock_key")
        with patch.object(adjuster.analyzer, 'analyze_stage2', return_value=res):
            params = adjuster.analyze_params(self.test_img, enable_ai=True)
            self.assertEqual(params["ai_status"], "ai_analyzed")
            self.assertEqual(params["exposure"], 0.12)
            self.assertEqual(params["telemetry"]["ai_status"], "ai_analyzed")

    # -------------------------------------------------------------------------
    # CASE B: API returns zero corrections -> ai_status = "ai_no_correction"
    # -------------------------------------------------------------------------
    @patch.object(Stage2Analyzer, '_query_vlm')
    def test_case_b_ai_no_correction(self, mock_vlm):
        mock_vlm.return_value = {
            "success": True,
            "parsed": {
                "scene_type": "landscape",
                "needs_correction": False,
                "confidence": 0.95,
                "adjustments": {"exposure_ev": 0.0, "shadows": 0.0, "highlights": 0.0},
                "reasoning": "Scene exposure is already optimal"
            },
            "latency_ms": 280,
            "http_status": 200,
            "finish_reason": "stop"
        }

        analyzer = Stage2Analyzer(api_key="mock_key")
        res = analyzer.analyze_stage2(self.test_img, preset_name="Test Preset", enable_ai=True)

        self.assertEqual(res["ai_status"], "ai_no_correction")
        self.assertFalse(res["needs_correction"])
        self.assertEqual(res["confidence"], 0.95)
        self.assertEqual(res["adjustments"]["exposure_ev"], 0.0)
        self.assertIn("Scene exposure is already optimal", res["reason"])

    # -------------------------------------------------------------------------
    # CASE C: Credit failure (HTTP 402 / 401 / quota) -> ai_status = "ai_unavailable"
    # -------------------------------------------------------------------------
    @patch('requests.post')
    def test_case_c_credit_failure_categorization(self, mock_post):
        # Simulate HTTP 402 Payment Required (OrcaRouter credit exhausted)
        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.text = '{"error": {"message": "Insufficient credit balance. Please add credits to your OrcaRouter account."}}'
        mock_post.return_value = mock_resp

        analyzer = Stage2Analyzer(api_key="secret_orca_key_12345")
        res = analyzer.analyze_stage2(self.test_img, preset_name="Test Preset", enable_ai=True)

        self.assertEqual(res["ai_status"], "ai_unavailable")
        self.assertEqual(res["confidence"], 0.0)
        self.assertFalse(res["needs_correction"])
        self.assertEqual(res["adjustments"]["exposure_ev"], 0.0)
        self.assertEqual(res["adjustments"]["shadows"], 0.0)
        # Ensure API key is NEVER leaked in error or reason
        self.assertNotIn("secret_orca_key_12345", str(res["api_error"]))
        self.assertNotIn("secret_orca_key_12345", str(res["reason"]))
        self.assertIn("credit", str(res["api_error"]).lower())

    # -------------------------------------------------------------------------
    # CASE D: Smart crop returns valid crop box -> crop_source = "ai", crop_status = "ai_crop"
    # -------------------------------------------------------------------------
    @patch.object(SmartCropper, '_get_ai_crop_box')
    def test_case_d_smart_crop_success(self, mock_ai_crop):
        mock_ai_crop.return_value = {
            "success": True,
            "crop_box": [0.1, 0.05, 0.9, 0.95],
            "reason": "Golden ratio portrait focus",
            "crop_status": "ai_crop",
            "api_error": None,
            "latency_ms": 310
        }

        cropper = SmartCropper(api_key="mock_key")
        cropped, tele = cropper.crop_best_landscape(self.test_img, enable_ai=True)

        self.assertEqual(tele["crop_status"], "ai_crop")
        self.assertEqual(tele["crop_source"], "ai")
        self.assertTrue(tele["applied"])
        self.assertFalse(tele["fallback_used"])
        self.assertLess(tele["crop_area_ratio"], 1.0)
        self.assertGreater(tele["crop_area_ratio"], 0.40)
        self.assertEqual(cropped.shape[0], 80)
        self.assertEqual(cropped.shape[1], 90)

    # -------------------------------------------------------------------------
    # CASE E: Smart crop API fails (e.g. credit/timeout) -> Fail safely to FULL FRAME
    # -------------------------------------------------------------------------
    @patch('requests.post')
    def test_case_e_smart_crop_api_failure_full_frame(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.text = '{"error": "Insufficient credit balance"}'
        mock_post.return_value = mock_resp

        cropper = SmartCropper(api_key="mock_key")
        cropped, tele = cropper.crop_best_landscape(self.test_img, enable_ai=True)

        # Invariant: FAIL SAFE TO FULL FRAME. Do NOT silently crop.
        self.assertEqual(tele["crop_status"], "ai_unavailable")
        self.assertEqual(tele["crop_source"], "none")
        self.assertFalse(tele["applied"])
        self.assertFalse(tele["fallback_used"])
        self.assertEqual(tele["crop_area_ratio"], 1.0)
        self.assertEqual(tele["ymin"], 0.0)
        self.assertEqual(tele["xmin"], 0.0)
        self.assertEqual(tele["ymax"], 1.0)
        self.assertEqual(tele["xmax"], 1.0)
        # Dimensions must match original exactly
        self.assertEqual(cropped.shape, self.test_img.shape)
        np.testing.assert_array_equal(cropped, self.test_img)

    # -------------------------------------------------------------------------
    # CASE F: Smart crop violates safety gate (<40% area) -> Fail safely to FULL FRAME
    # -------------------------------------------------------------------------
    @patch.object(SmartCropper, '_get_ai_crop_box')
    def test_case_f_smart_crop_safety_gate_rejection(self, mock_ai_crop):
        # Return an aggressive crop covering only 4% area
        mock_ai_crop.return_value = {
            "success": True,
            "crop_box": [0.4, 0.4, 0.6, 0.6],
            "reason": "Extreme macro crop",
            "crop_status": "ai_crop",
            "api_error": None
        }

        cropper = SmartCropper(api_key="mock_key")
        cropped, tele = cropper.crop_best_landscape(self.test_img, enable_ai=True)

        # Rejected by safety gate -> Must revert to FULL FRAME
        self.assertEqual(tele["crop_status"], "ai_rejected")
        self.assertEqual(tele["crop_source"], "none")
        self.assertFalse(tele["applied"])
        self.assertEqual(tele["crop_area_ratio"], 1.0)
        self.assertEqual(cropped.shape, self.test_img.shape)
        np.testing.assert_array_equal(cropped, self.test_img)

    # -------------------------------------------------------------------------
    # CASE G: AI Disabled in Settings -> ai_status = "ai_disabled", crop_status = "crop_disabled"
    # -------------------------------------------------------------------------
    def test_case_g_ai_disabled_in_settings(self):
        analyzer = Stage2Analyzer(api_key="mock_key")
        res = analyzer.analyze_stage2(self.test_img, enable_ai=False)
        self.assertEqual(res["ai_status"], "ai_disabled")
        self.assertFalse(res["needs_correction"])
        self.assertEqual(res["confidence"], 0.0)

        cropper = SmartCropper(api_key="mock_key")
        cropped, tele = cropper.crop_best_landscape(self.test_img, enable_ai=False)
        self.assertEqual(tele["crop_status"], "crop_disabled")
        self.assertEqual(tele["crop_source"], "none")
        self.assertFalse(tele["applied"])
        self.assertEqual(tele["crop_area_ratio"], 1.0)
        np.testing.assert_array_equal(cropped, self.test_img)


if __name__ == "__main__":
    unittest.main()
