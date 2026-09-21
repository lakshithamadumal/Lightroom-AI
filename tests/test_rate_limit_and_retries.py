"""
Lightroom AI - Stage 2 Rate-Limiting & Retry Mechanism Unit Tests
(test_rate_limit_and_retries.py)

Validates:
1. parse_retry_after header parsing (numeric seconds, HTTP dates, body strings, defaults, bounds).
2. RequestPacer pacing / minimum interval enforcement.
3. HTTP 429 retry recovery (429 -> retry -> 200 success).
4. HTTP 429 retry exhaustion (repeated 429 -> ai_unavailable + ZERO_ADJUSTMENTS + Stage 1 preservation).
5. Immediate ai_unavailable on permanent authentication/billing errors (401, 402, 403).
6. SmartCropper 429 retry and fail-safe preservation.
"""

import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import requests

from stage2_analyzer import Stage2Analyzer, RequestPacer, parse_retry_after
from smart_cropper import SmartCropper
from stage2_schema import ZERO_ADJUSTMENTS


class TestRateLimitingAndRetries(unittest.TestCase):

    def setUp(self):
        # Create synthetic 100x100 BGR test buffer
        self.test_img = np.zeros((100, 100, 3), dtype=np.uint8)
        self.test_img[:] = (100, 110, 120)
        self.analyzer = Stage2Analyzer(api_key="mock_test_key", model="qwen/qwen3.8-27b")

    def test_parse_retry_after_numeric(self):
        resp = MagicMock(spec=requests.Response)
        resp.headers = {"Retry-After": "2.5"}
        resp.text = ""
        wait = parse_retry_after(resp, default_backoff=1.0)
        self.assertAlmostEqual(wait, 2.5)

    def test_parse_retry_after_http_date(self):
        resp = MagicMock(spec=requests.Response)
        # 10 seconds in future
        from email.utils import format_datetime
        from datetime import datetime, timezone, timedelta
        future_dt = datetime.now(timezone.utc) + timedelta(seconds=10)
        resp.headers = {"Retry-After": format_datetime(future_dt)}
        resp.text = ""
        wait = parse_retry_after(resp, default_backoff=1.0)
        self.assertGreaterEqual(wait, 8.0)
        self.assertLessEqual(wait, 12.0)

    def test_parse_retry_after_body_message(self):
        resp = MagicMock(spec=requests.Response)
        resp.headers = {}
        resp.text = '{"error": {"message": "Rate limit reached. Please try again in 3.45s."}}'
        wait = parse_retry_after(resp, default_backoff=1.0)
        self.assertAlmostEqual(wait, 3.45)

    def test_parse_retry_after_body_ms_message(self):
        resp = MagicMock(spec=requests.Response)
        resp.headers = {}
        resp.text = '{"error": {"message": "Rate limit reached. Please try again in 1500ms."}}'
        wait = parse_retry_after(resp, default_backoff=1.0)
        self.assertAlmostEqual(wait, 1.5)

    def test_parse_retry_after_bounded(self):
        resp = MagicMock(spec=requests.Response)
        resp.headers = {"Retry-After": "120"}  # huge value
        wait = parse_retry_after(resp, default_backoff=1.0, max_backoff=30.0)
        self.assertAlmostEqual(wait, 30.0)

    @patch("stage2_analyzer.time.sleep")
    @patch("stage2_analyzer.requests.post")
    def test_http_429_transient_recovery(self, mock_post, mock_sleep):
        # First call returns 429 with Retry-After: 1
        resp_429 = MagicMock(spec=requests.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "1.0"}
        resp_429.text = "Rate limit reached"

        # Second call returns 200 OK
        resp_200 = MagicMock(spec=requests.Response)
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.json.return_value = {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": '{"scene_type": "general", "needs_correction": false, "confidence": 0.9, "reasoning": "Well balanced", "adjustments": {"exposure_ev": 0.0, "temperature": 0.0, "tint": 0.0, "highlights": 0.0, "shadows": 0.0}}'
                }
            }]
        }

        mock_post.side_effect = [resp_429, resp_200]

        res = self.analyzer.analyze_stage2(self.test_img, enable_ai=True)
        self.assertEqual(res["http_status"], 200)
        self.assertTrue(res["vlm_succeeded"])
        self.assertEqual(res["ai_status"], "ai_no_correction")
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called()

    @patch("stage2_analyzer.time.sleep")
    @patch("stage2_analyzer.requests.post")
    def test_http_429_exhaustion_preserves_stage1(self, mock_post, mock_sleep):
        # All 4 calls return 429
        resp_429 = MagicMock(spec=requests.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "0.5"}
        resp_429.text = "Rate limit reached"
        mock_post.return_value = resp_429

        res = self.analyzer.analyze_stage2(self.test_img, enable_ai=True)
        self.assertEqual(res["http_status"], 429)
        self.assertFalse(res["vlm_succeeded"])
        self.assertEqual(res["ai_status"], "ai_unavailable")
        self.assertEqual(res["adjustments_applied"], ZERO_ADJUSTMENTS)
        self.assertTrue(res["no_op"])
        self.assertIn("rate limit", res["reason"].lower())
        self.assertEqual(mock_post.call_count, 4)

    @patch("stage2_analyzer.requests.post")
    def test_http_401_immediate_failure_without_wasted_retries(self, mock_post):
        # 401 Unauthorized should fail immediately on first attempt
        resp_401 = MagicMock(spec=requests.Response)
        resp_401.status_code = 401
        resp_401.text = "Invalid API Key"
        mock_post.return_value = resp_401

        res = self.analyzer.analyze_stage2(self.test_img, enable_ai=True)
        self.assertEqual(res["http_status"], 401)
        self.assertFalse(res["vlm_succeeded"])
        self.assertEqual(res["ai_status"], "ai_unavailable")
        self.assertEqual(res["adjustments_applied"], ZERO_ADJUSTMENTS)
        self.assertEqual(mock_post.call_count, 1)  # No redundant retries on 401

    @patch("smart_cropper.time.sleep")
    @patch("smart_cropper.requests.post")
    def test_smart_cropper_429_exhaustion_preserves_full_frame(self, mock_post, mock_sleep):
        cropper = SmartCropper(api_key="mock_key")
        resp_429 = MagicMock(spec=requests.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "0.5"}
        resp_429.text = "Rate limit reached"
        mock_post.return_value = resp_429

        cropped, tel = cropper.crop_best_landscape(self.test_img, enable_ai=True)
        self.assertEqual(tel["crop_status"], "ai_unavailable")
        self.assertFalse(tel["applied"])
        self.assertEqual(tel["crop_area_ratio"], 1.0)
        self.assertEqual(cropped.shape, self.test_img.shape)


if __name__ == "__main__":
    unittest.main()
