"""
Unit tests for the Color Management System (color_space.py).
Tests:
- sRGB piecewise EOTF / OETF invertibility
- Roundtrip conversions: sRGB -> Linear ProPhoto -> sRGB
- ACEScg and Linear sRGB transformations
- Boundary conditions (0.0, 1.0) preservation
"""

import unittest
import numpy as np

from color_space import ColorSpace, ColorManager


class TestColorSpace(unittest.TestCase):

    def test_srgb_eotf_oetf_roundtrip(self):
        """Converting sRGB -> Linear -> sRGB must roundtrip with high precision."""
        np.random.seed(42)
        srgb_in = np.random.uniform(0.0, 1.0, size=(100, 100, 3)).astype(np.float32)
        linear = ColorManager.srgb_to_linear(srgb_in)
        srgb_out = ColorManager.linear_to_srgb(linear)

        mae = np.mean(np.abs(srgb_out - srgb_in))
        self.assertLess(mae, 1e-6, f"sRGB EOTF/OETF roundtrip MAE too high: {mae}")

    def test_prophoto_roundtrip(self):
        """Converting sRGB -> Linear_ProPhoto -> sRGB must roundtrip within gamut with high precision."""
        # Test colors within sRGB gamut
        test_colors = np.array([
            [[0.0, 0.0, 0.0]],
            [[1.0, 1.0, 1.0]],
            [[0.5, 0.5, 0.5]],
            [[0.8, 0.2, 0.1]],
            [[0.1, 0.7, 0.3]],
            [[0.2, 0.3, 0.9]],
        ], dtype=np.float32)

        prophoto = ColorManager.convert(test_colors, ColorSpace.SRGB, ColorSpace.LINEAR_PROPHOTO)
        srgb_back = ColorManager.convert(prophoto, ColorSpace.LINEAR_PROPHOTO, ColorSpace.SRGB)

        np.testing.assert_allclose(srgb_back, test_colors, atol=1e-4)

    def test_acescg_roundtrip(self):
        """Converting sRGB -> Linear_ACEScg -> sRGB must roundtrip cleanly."""
        np.random.seed(123)
        srgb_in = np.random.uniform(0.1, 0.9, size=(50, 50, 3)).astype(np.float32)
        aces = ColorManager.convert(srgb_in, ColorSpace.SRGB, ColorSpace.LINEAR_ACESCG)
        srgb_out = ColorManager.convert(aces, ColorSpace.LINEAR_ACESCG, ColorSpace.SRGB)

        mae = np.mean(np.abs(srgb_out - srgb_in))
        self.assertLess(mae, 1e-4)

    def test_srgb_stability(self):
        """sRGB input transformed to sRGB must be 100% bit-exact and numerically stable."""
        img = np.random.randint(0, 256, size=(64, 64, 3), dtype=np.uint8)
        img_copy = img.copy()

        # sRGB to sRGB via convert_icc
        out_icc = ColorManager.convert_icc(img, src_profile="sRGB", target_space="sRGB", is_bgr=True)
        np.testing.assert_array_equal(out_icc, img_copy)

        # Untagged to sRGB via convert_icc
        out_untagged = ColorManager.convert_icc(img, src_profile=None, target_space="sRGB", is_bgr=True)
        np.testing.assert_array_equal(out_untagged, img_copy)

    def test_display_p3_conversion(self):
        """Display P3 input must convert to sRGB accurately."""
        # Pure red in Display P3 [0, 0, 255] in BGR
        p3_red = np.zeros((10, 10, 3), dtype=np.uint8)
        p3_red[:, :, 2] = 255  # Red channel

        srgb_out = ColorManager.convert_icc(p3_red, src_profile="Display_P3", target_space="sRGB", is_bgr=True)
        # Red in P3 expands outside standard sRGB gamut, so in sRGB R is maxed (255) and B/G are adjusted
        self.assertEqual(srgb_out.shape, (10, 10, 3))
        self.assertGreater(int(srgb_out[0, 0, 2]), 200)

        # Profile description
        prof_name = ColorManager.get_profile_name("Display_P3")
        self.assertIn("Display", prof_name)

    def test_adobe_rgb_conversion(self):
        """Adobe RGB (1998) input must convert to sRGB accurately."""
        # Midtone green in Adobe RGB [0, 128, 0] in BGR
        adobe_green = np.zeros((10, 10, 3), dtype=np.uint8)
        adobe_green[:, :, 1] = 128

        srgb_out = ColorManager.convert_icc(adobe_green, src_profile="Adobe_RGB_1998", target_space="sRGB", is_bgr=True)
        self.assertEqual(srgb_out.shape, (10, 10, 3))
        self.assertGreater(int(srgb_out[0, 0, 1]), 100)

    def test_missing_icc_fallback(self):
        """Untagged images must fall back gracefully to sRGB with documented status."""
        name = ColorManager.get_profile_name(None)
        self.assertEqual(name, "Untagged (sRGB Fallback)")

        # Empty bytes
        name_empty = ColorManager.get_profile_name(b"")
        self.assertEqual(name_empty, "Untagged (sRGB Fallback)")

        # Convert untagged array
        arr = np.ones((5, 5, 3), dtype=np.uint8) * 120
        out = ColorManager.convert_icc(arr, src_profile=None, target_space="sRGB")
        np.testing.assert_array_equal(out, arr)

    def test_alpha_channel_intact(self):
        """4-channel BGRA and RGBA images must preserve their Alpha channel 100% intact."""
        bgra = np.random.randint(0, 256, size=(20, 20, 4), dtype=np.uint8)
        orig_alpha = bgra[:, :, 3].copy()

        # Convert Display P3 BGRA -> sRGB
        out_bgra = ColorManager.convert_icc(bgra, src_profile="Display_P3", target_space="sRGB", is_bgr=True)
        self.assertEqual(out_bgra.shape, (20, 20, 4))
        np.testing.assert_array_equal(out_bgra[:, :, 3], orig_alpha)

        # Convert Adobe RGB BGRA -> sRGB
        out_adobe_bgra = ColorManager.convert_icc(bgra, src_profile="Adobe_RGB_1998", target_space="sRGB", is_bgr=True)
        self.assertEqual(out_adobe_bgra.shape, (20, 20, 4))
        np.testing.assert_array_equal(out_adobe_bgra[:, :, 3], orig_alpha)


if __name__ == "__main__":
    unittest.main()
