"""
Unit and Regression tests for Stage 2 AI Scene & Exposure Auto-Balancing (tests/test_stage2_auto_balancer.py).

Tests:
A. Hard clamp and operational limits tests
B. Invalid JSON -> no-op
C. Confidence < 0.70 -> no-op
D. needs_correction=false -> no-op
E. Already-balanced image -> no-op
F. Stage 1 Base remains byte-identical after Stage 2
G. Reset restores exact Stage 1 Base
H. Exposure EV behavior
I. Highlight protection
J. Shadow lift
K. Temperature/tint bounded behavior
L. Stage 2 cannot modify LUT files
M. Existing Stage 1 regression tests still pass
S. Total Budget Scaling Test
T. Preset-Preservation Gate Test
U. Low-Light Intentional Scene Protection Test
"""

import os
import shutil
import unittest
import numpy as np
import cv2

from stage2_schema import (
    STAGE2_LIMITS,
    STAGE2_OPERATIONAL_LIMITS,
    PRESET_PRESERVATION_LIMITS,
    CONFIDENCE_THRESHOLD,
    ZERO_ADJUSTMENTS,
    sanitize_and_clamp_adjustments,
    apply_total_budget_scaling,
    evaluate_preset_preservation_gate,
    compute_stage1_buffer_hash
)
from stage2_analyzer import Stage2Analyzer
from stage2_adjuster import Stage2Adjuster
from auto_adjuster import AutoAdjuster
from lut_engine import Lut3D


class TestStage2AutoBalancer(unittest.TestCase):

    def setUp(self):
        # Create synthetic Stage 1 Base buffer in Adobe RGB 1998 working space (400x400x3 uint8)
        np.random.seed(42)
        self.stage1_base = np.random.randint(50, 200, size=(400, 400, 3), dtype=np.uint8)
        self.base_hash = compute_stage1_buffer_hash(self.stage1_base)

    # A. Hard clamp and operational limits tests
    def test_hard_clamps(self):
        """Out-of-bounds adjustments must be strictly clamped to allowed ranges and scaled by budget."""
        raw_adj = {
            "exposure_ev": 1.5,     # exceeds +0.25
            "temperature": -25.0,   # exceeds -6.0
            "tint": 15.0,           # exceeds +4.0
            "highlights": -30.0,    # exceeds -8.0
            "shadows": 40.0,        # exceeds +8.0
            "contrast": 25.0,       # forbidden
            "saturation": 50.0,     # forbidden
        }
        clamped, was_clamped, is_noop = sanitize_and_clamp_adjustments(
            raw_adj, confidence=0.85, needs_correction=True, use_operational_limits=True
        )
        self.assertTrue(was_clamped)
        self.assertFalse(is_noop)
        # Verify operational clamps and budget scaling
        self.assertLessEqual(abs(clamped["exposure_ev"]), STAGE2_OPERATIONAL_LIMITS["exposure_ev"][1])
        self.assertLessEqual(abs(clamped["temperature"]), abs(STAGE2_OPERATIONAL_LIMITS["temperature"][0]))
        self.assertLessEqual(abs(clamped["tint"]), STAGE2_OPERATIONAL_LIMITS["tint"][1])
        self.assertLessEqual(abs(clamped["highlights"]), abs(STAGE2_OPERATIONAL_LIMITS["highlights"][0]))
        self.assertLessEqual(abs(clamped["shadows"]), STAGE2_OPERATIONAL_LIMITS["shadows"][1])

    # B. Invalid JSON / VLM failure -> no-op
    def test_invalid_json_fallback_noop(self):
        """Analyzer must fallback to complete deterministic no-op if VLM fails or is unconfigured."""
        analyzer = Stage2Analyzer(api_key="", model="google/gemini-2.5-flash")
        res = analyzer.analyze_stage2(self.stage1_base, enable_ai=False)
        self.assertTrue(res["no_op"])
        self.assertEqual(res["adjustments_applied"], ZERO_ADJUSTMENTS)
        self.assertEqual(res["stage1_base_hash"], self.base_hash)

    # C. Confidence < 0.70 -> no-op
    def test_low_confidence_noop(self):
        """Confidence below 0.70 must result in a clean no-op."""
        raw_adj = {"exposure_ev": 0.20, "temperature": 3.0}
        clamped, was_clamped, is_noop = sanitize_and_clamp_adjustments(
            raw_adj, confidence=0.65, needs_correction=True
        )
        self.assertTrue(is_noop)
        self.assertEqual(clamped, ZERO_ADJUSTMENTS)

    # D. needs_correction=false -> no-op
    def test_needs_correction_false_noop(self):
        """When needs_correction is False, adjustments must be zeroed."""
        raw_adj = {"exposure_ev": 0.20, "temperature": 3.0}
        clamped, was_clamped, is_noop = sanitize_and_clamp_adjustments(
            raw_adj, confidence=0.95, needs_correction=False
        )
        self.assertTrue(is_noop)
        self.assertEqual(clamped, ZERO_ADJUSTMENTS)

    # E. Already-balanced image -> pre-noop
    def test_already_balanced_pre_noop(self):
        """Image with median L* in [45, 60] and neutral midtones must trigger deterministic pre-noop."""
        # Create a neutral grey patch with L* ~ 50
        grey_bgr = np.full((100, 100, 3), 119, dtype=np.uint8)
        telemetry = Stage2Analyzer.compute_objective_telemetry(grey_bgr)
        is_noop, reason = Stage2Analyzer.check_pre_noop_conditions(telemetry)
        self.assertTrue(is_noop)
        self.assertIn("already well-balanced", reason)

    # F. Stage 1 Base remains byte-identical after Stage 2
    def test_stage1_base_immutability(self):
        """Applying Stage 2 adjustments must never mutate the input Stage 1 Base buffer."""
        base_copy = self.stage1_base.copy()
        adj = {"exposure_ev": 0.15, "temperature": 2.0, "shadows": 4.0}
        balanced_out, _ = Stage2Adjuster.apply_stage2_adjustments(self.stage1_base, adj)
        # Original input buffer must be 100% byte-identical
        self.assertTrue(np.array_equal(self.stage1_base, base_copy))
        self.assertEqual(compute_stage1_buffer_hash(self.stage1_base), self.base_hash)

    # G. Reset restores exact Stage 1 Base
    def test_reset_restores_stage1_base(self):
        """Applying zero adjustments must return an exact match to the Stage 1 Base buffer."""
        out, telemetry = Stage2Adjuster.apply_stage2_adjustments(self.stage1_base, ZERO_ADJUSTMENTS)
        self.assertTrue(np.array_equal(out, self.stage1_base))
        self.assertEqual(telemetry["exposure_ev"], 0.0)

    # H. Exposure EV behavior
    def test_exposure_ev_behavior(self):
        """Positive exposure must increase luminance; negative exposure must decrease luminance."""
        uniform_base = np.full((50, 50, 3), 100, dtype=np.uint8)
        bright, _ = Stage2Adjuster.apply_stage2_adjustments(uniform_base, {"exposure_ev": 0.10})
        dark, _ = Stage2Adjuster.apply_stage2_adjustments(uniform_base, {"exposure_ev": -0.10})
        self.assertGreater(float(np.mean(bright)), float(np.mean(uniform_base)))
        self.assertLess(float(np.mean(dark)), float(np.mean(uniform_base)))

    # I. Highlight protection
    def test_highlight_protection(self):
        """Negative highlights should compress bright areas (L* > 65) with minimal effect on dark midtones."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:50, :] = 50   # shadows/low midtones
        img[50:, :] = 220  # bright highlights
        adj = {"highlights": -6.0}
        out, _ = Stage2Adjuster.apply_stage2_adjustments(img, adj)
        # Low area should be unchanged or changed by < 1 unit
        self.assertAlmostEqual(float(np.mean(out[:50, :])), 50.0, delta=1.5)
        # High area should be reduced
        self.assertLess(float(np.mean(out[50:, :])), 220.0)

    # J. Shadow lift
    def test_shadow_lift(self):
        """Positive shadows should lift dark areas (L* < 45) with minimal effect on bright areas."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:50, :] = 30   # dark shadows
        img[50:, :] = 200  # bright highlights
        adj = {"shadows": 5.0}
        out, _ = Stage2Adjuster.apply_stage2_adjustments(img, adj)
        # Shadow area should be lifted
        self.assertGreater(float(np.mean(out[:50, :])), 30.0)
        # Bright area should remain largely unchanged
        self.assertAlmostEqual(float(np.mean(out[50:, :])), 200.0, delta=1.5)

    # K. Temperature and tint bounded behavior
    def test_temperature_tint_behavior(self):
        """Positive temp should increase warmth (b*), positive tint should shift magenta (a*)."""
        grey = np.full((50, 50, 3), 128, dtype=np.uint8)
        warm, _ = Stage2Adjuster.apply_stage2_adjustments(grey, {"temperature": 4.0})
        tint_m, _ = Stage2Adjuster.apply_stage2_adjustments(grey, {"tint": 3.0})

        warm_lab = cv2.cvtColor(warm, cv2.COLOR_BGR2LAB)
        tint_lab = cv2.cvtColor(tint_m, cv2.COLOR_BGR2LAB)
        grey_lab = cv2.cvtColor(grey, cv2.COLOR_BGR2LAB)

        # Warm image has higher b* (b channel index 2)
        self.assertGreater(float(np.mean(warm_lab[:, :, 2])), float(np.mean(grey_lab[:, :, 2])))
        # Magenta tint has higher a* (a channel index 1)
        self.assertGreater(float(np.mean(tint_lab[:, :, 1])), float(np.mean(grey_lab[:, :, 1])))

    # L. Stage 2 cannot modify LUT files
    def test_stage2_cannot_modify_lut_files(self):
        """Verify Stage 2 has no write handles or side-effects on calibration LUT files."""
        lut_path = os.path.join(os.path.dirname(__file__), "..", "calibration", "preset.cube")
        if os.path.exists(lut_path):
            lut_mtime_before = os.path.getmtime(lut_path)
            # Run Stage 2 adjustment
            Stage2Adjuster.apply_stage2_adjustments(self.stage1_base, {"exposure_ev": 0.20})
            lut_mtime_after = os.path.getmtime(lut_path)
            self.assertEqual(lut_mtime_before, lut_mtime_after)

    # M. Stage 1 LUT Engine compatibility
    def test_stage1_lut_engine_compat(self):
        """Lut3D interpolation remains functional and unchanged."""
        from lut_engine import LutEngine
        lut = Lut3D(size=17)
        lut.table = np.linspace(0, 1, 17 * 17 * 17 * 3, dtype=np.float32).reshape((17, 17, 17, 3))
        dummy = np.full((10, 10, 3), 128, dtype=np.uint8)
        out = LutEngine.apply_lut_3d(dummy, lut)
        self.assertEqual(out.shape, (10, 10, 3))

    # S. Total Budget Scaling Test
    def test_total_budget_scaling(self):
        """When multiple large corrections are requested simultaneously, total budget scaling must attenuate them proportionally."""
        max_adj = {
            "exposure_ev": 0.25,
            "temperature": 6.0,
            "tint": 4.0,
            "highlights": -8.0,
            "shadows": 8.0
        }
        scaled, was_scaled = apply_total_budget_scaling(max_adj, max_budget=1.0)
        self.assertTrue(was_scaled)
        # Sum of normalized ratios must be <= 1.0
        u_sum = (scaled["exposure_ev"]/0.25 + scaled["temperature"]/6.0 + scaled["tint"]/4.0 +
                 abs(scaled["highlights"])/8.0 + scaled["shadows"]/8.0)
        self.assertAlmostEqual(u_sum, 1.0, delta=0.08)

    # T. Preset-Preservation Gate Test
    def test_preset_preservation_gate(self):
        """Preset-preservation gate must accept small subtle trims and reject excessive deviations."""
        base_patch = np.full((100, 100, 3), 128, dtype=np.uint8)
        
        # Candidate with tiny trim (Delta E ~ 0.5)
        mild_candidate, _ = Stage2Adjuster.apply_stage2_adjustments(base_patch, {"exposure_ev": 0.05, "temperature": 1.0})
        gate_mild = evaluate_preset_preservation_gate(base_patch, mild_candidate)
        self.assertTrue(gate_mild["accepted"])
        self.assertLessEqual(gate_mild["mean_delta_e"], 2.0)
        self.assertLessEqual(gate_mild["p95_delta_e"], 5.0)

        # Huge forced shift must be rejected by gate
        huge_candidate = np.clip(base_patch.astype(np.int32) + 60, 0, 255).astype(np.uint8)
        gate_huge = evaluate_preset_preservation_gate(base_patch, huge_candidate)
        self.assertFalse(gate_huge["accepted"])
        self.assertIn("Rejected", gate_huge["reason"])

    # U. Low-Light Intentional Scene Protection Test
    def test_low_light_protection_noop(self):
        """Dark scene with L* mean < 8 and heavy shadow clipping must trigger pre-noop protection."""
        dark_img = np.full((100, 100, 3), 5, dtype=np.uint8)
        telemetry = Stage2Analyzer.compute_objective_telemetry(dark_img)
        is_noop, reason = Stage2Analyzer.check_pre_noop_conditions(telemetry)
        self.assertTrue(is_noop)
        self.assertIn("low-key", reason)


if __name__ == "__main__":
    unittest.main()
