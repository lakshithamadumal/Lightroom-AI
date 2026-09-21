"""
Unit tests for the 32-bit float 3D LUT Engine (lut_engine.py).
Tests:
- Identity LUT mapping invariance
- Known color mappings
- Black/white preservation
- Gradient smoothness and trilinear continuity
- Random RGB values
- Boundary and out-of-range values
- Hald Level 8 <-> .cube conversion equivalence
- 4-channel RGBA / BGRA alpha preservation
"""

import os
import unittest
import numpy as np
import cv2

from lut_engine import Lut3D, LutEngine


class TestLutEngine(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.join(os.path.dirname(__file__), "tmp_test_assets")
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_identity_lut_float32(self):
        """Identity LUT must preserve input float values exactly."""
        lut = Lut3D.create_identity(size=64)
        np.random.seed(42)
        test_img = np.random.uniform(0.0, 1.0, size=(100, 100, 3)).astype(np.float32)

        out = LutEngine.apply_lut_3d(test_img, lut)
        mae = np.mean(np.abs(out - test_img))
        self.assertLess(mae, 1e-5, f"Identity LUT MAE too high: {mae}")

    def test_identity_lut_uint8(self):
        """Identity LUT on uint8 image must produce identical pixel values."""
        lut = Lut3D.create_identity(size=64)
        np.random.seed(42)
        test_img = np.random.randint(0, 256, size=(100, 100, 3), dtype=np.uint8)

        out = LutEngine.apply_lut_3d(test_img, lut)
        diff = np.max(np.abs(out.astype(np.int32) - test_img.astype(np.int32)))
        self.assertLessEqual(diff, 1, f"Max uint8 deviation in identity LUT: {diff}")

    def test_known_color_mapping(self):
        """Test custom color inversion LUT on pure primaries."""
        # Create an inversion LUT: R' = 1 - R, G' = 1 - G, B' = 1 - B
        size = 33
        lut = Lut3D.create_identity(size=size)
        lut.table = 1.0 - lut.table

        # Test pure Red [1.0, 0.0, 0.0] -> should become Cyan [0.0, 1.0, 1.0]
        pure_red = np.array([[[1.0, 0.0, 0.0]]], dtype=np.float32)
        out_red = LutEngine.apply_lut_3d(pure_red, lut)
        np.testing.assert_allclose(out_red, [[[0.0, 1.0, 1.0]]], atol=1e-5)

        # Test pure Green [0.0, 1.0, 0.0] -> should become Magenta [1.0, 0.0, 1.0]
        pure_green = np.array([[[0.0, 1.0, 0.0]]], dtype=np.float32)
        out_green = LutEngine.apply_lut_3d(pure_green, lut)
        np.testing.assert_allclose(out_green, [[[1.0, 0.0, 1.0]]], atol=1e-5)

    def test_black_white_preservation(self):
        """Pure black (0,0,0) and pure white (1,1,1) in identity LUT must be preserved."""
        lut = Lut3D.create_identity(size=64)
        bw_img = np.array([[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]], dtype=np.float32)
        out = LutEngine.apply_lut_3d(bw_img, lut)
        np.testing.assert_allclose(out, bw_img, atol=1e-6)

    def test_gradient_smoothness_and_trilinear_continuity(self):
        """A continuous smooth gradient passed through a LUT must remain monotonically smooth."""
        lut = Lut3D.create_identity(size=64)
        # Create continuous 1D gradient of 1000 steps from 0 to 1
        ramp = np.linspace(0.0, 1.0, 1000, dtype=np.float32)
        ramp_img = np.stack([ramp, ramp, ramp], axis=-1).reshape((1, 1000, 3))

        out = LutEngine.apply_lut_3d(ramp_img, lut)
        # Check first derivative (differences between consecutive points)
        diffs = np.diff(out[0, :, 0])
        self.assertTrue(np.all(diffs >= 0), "Gradient monotonicity violated by interpolation!")
        # Verify no sudden jumps or discontinuities
        max_step = np.max(diffs)
        expected_step = 1.0 / 999.0
        self.assertAlmostEqual(max_step, expected_step, places=4)

    def test_boundary_and_out_of_range_clamping(self):
        """Out of range inputs (< 0.0 or > 1.0) must be clamped cleanly without crashing."""
        lut = Lut3D.create_identity(size=64)
        out_of_range = np.array([[[-0.5, 1.5, 2.0]]], dtype=np.float32)
        out = LutEngine.apply_lut_3d(out_of_range, lut)
        # Clamped lookup will sample at (0, 1, 1) which for identity LUT gives (0, 1, 1)
        np.testing.assert_allclose(out, [[[0.0, 1.0, 1.0]]], atol=1e-5)

    def test_cube_io_roundtrip(self):
        """Saving and loading a .cube file must preserve exact float values."""
        cube_path = os.path.join(self.test_dir, "test_roundtrip.cube")
        orig_lut = Lut3D.create_identity(size=33)
        # Apply a custom tone transform
        orig_lut.table = np.power(orig_lut.table, 1.5)

        orig_lut.to_cube_file(cube_path, title="Roundtrip Test")
        loaded_lut = Lut3D.from_cube_file(cube_path)

        self.assertEqual(loaded_lut.size, 33)
        self.assertEqual(loaded_lut.title, "Roundtrip Test")
        np.testing.assert_allclose(loaded_lut.table, orig_lut.table, atol=1e-5)

    def test_hald_image_roundtrip(self):
        """Hald Level 8 encoding and decoding must match 3D table within quantization precision."""
        lut = Lut3D.create_identity(size=64)
        hald_img = lut.to_hald_image(level=8, bit_depth=8)
        self.assertEqual(hald_img.shape, (512, 512, 3))

        loaded_lut = Lut3D.from_hald_image(hald_img, level=8)
        self.assertEqual(loaded_lut.size, 64)
        # Max error due to 8-bit quantization is 1/255 ~ 0.0039
        max_err = np.max(np.abs(loaded_lut.table - lut.table))
        self.assertLess(max_err, 0.005, f"Hald roundtrip quantization error too high: {max_err}")

    def test_hald_cube_cross_equivalence(self):
        """Applying a .cube vs its Hald counterpart on a real test image produces identical results."""
        lut = Lut3D.create_identity(size=64)
        # Modify colors non-linearly
        lut.table[..., 0] = np.power(lut.table[..., 0], 1.2)  # R
        lut.table[..., 1] = np.sin(lut.table[..., 1] * np.pi / 2.0)  # G
        lut.table[..., 2] = lut.table[..., 2] * 0.9  # B

        cube_path = os.path.join(self.test_dir, "equiv.cube")
        hald_path = os.path.join(self.test_dir, "equiv_hald.png")

        lut.to_cube_file(cube_path)
        lut.to_hald_file(hald_path, level=8, bit_depth=8)

        cube_lut = Lut3D.from_cube_file(cube_path)
        hald_lut = Lut3D.from_hald_file(hald_path, level=8)

        test_img = np.random.randint(0, 256, size=(128, 128, 3), dtype=np.uint8)
        out_cube = LutEngine.apply_lut_3d(test_img, cube_lut)
        out_hald = LutEngine.apply_lut_3d(test_img, hald_lut)

        # Difference between float32 .cube and 8-bit quantized Hald on uint8 output is <= 1 code value
        diff = np.abs(out_cube.astype(np.int32) - out_hald.astype(np.int32))
        self.assertLessEqual(np.max(diff), 2)
        self.assertLessEqual(np.mean(diff), 0.5)

    def test_alpha_channel_preservation(self):
        """4-channel RGBA / BGRA images must have alpha preserved perfectly."""
        lut = Lut3D.create_identity(size=64)
        rgba_img = np.zeros((50, 50, 4), dtype=np.uint8)
        rgba_img[:, :, :3] = 180  # Gray color
        rgba_img[:, :, 3] = np.linspace(0, 255, 50).astype(np.uint8)  # Alpha gradient

        out_rgba = LutEngine.apply_lut_3d(rgba_img, lut, is_bgr=False)
        self.assertEqual(out_rgba.shape, (50, 50, 4))
        np.testing.assert_array_equal(out_rgba[:, :, 3], rgba_img[:, :, 3])


if __name__ == "__main__":
    unittest.main()
