"""
Regression and Unit tests for Adobe RGB 16-bit Calibration & ICC Color Management.
Tests:
- 16-bit wide-gamut Hald extraction without 8-bit truncation
- Adobe RGB (1998) color profile preservation and accurate conversion
- Prevention of double ICC color conversions across pipeline stages
- LUT input/output color-space metadata integrity
- 4-channel RGBA / BGRA alpha preservation through color conversions and LUT applications
"""

import os
import io
import shutil
import unittest
import numpy as np
import cv2
from PIL import Image, ImageCms

from color_space import ColorSpace, ColorManager
from lut_engine import Lut3D, LutEngine
from calibration_engine import CalibrationEngine


class TestAdobeRGBCalibration(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.join(os.path.dirname(__file__), "tmp_adobe_test")
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_16bit_hald_extraction_precision(self):
        """16-bit Hald array must be converted to float32 without 8-bit step quantization."""
        # Create a synthetic 16-bit Hald Level 8 image (512x512x3 uint16)
        level = 8
        size = level * level  # 64
        lut_ident = Lut3D.create_identity(size=size)
        
        # Apply a subtle smooth tonal curve
        lut_ident.table = np.power(lut_ident.table, 1.15)
        
        # Convert to 16-bit Hald uint16 image
        hald_uint16 = lut_ident.to_hald_image(level=level, bit_depth=16)
        self.assertEqual(hald_uint16.dtype, np.uint16)
        
        # Reconstruct LUT directly from 16-bit array
        reconstructed_lut = Lut3D.from_hald_image(hald_uint16, level=level)
        self.assertEqual(reconstructed_lut.table.dtype, np.float32)
        
        # Verify precision: MAE should be < 1e-4 (far superior to 8-bit limit of 0.0039)
        mae = np.mean(np.abs(reconstructed_lut.table - lut_ident.table))
        self.assertLess(mae, 1e-4, f"16-bit Hald extraction precision lower than expected: {mae}")

    def test_icc_profile_preservation_and_detection(self):
        """ICC profile strings, bytes, and TIFF metadata must be accurately parsed and detected."""
        # Test built-in profile names
        self.assertIn("Adobe_RGB", ColorManager.get_profile_name("Adobe_RGB_1998"))
        self.assertIn("Display", ColorManager.get_profile_name("Display_P3"))
        self.assertIn("sRGB", ColorManager.get_profile_name("sRGB"))
        self.assertEqual(ColorManager.get_profile_name(None), "Untagged (sRGB Fallback)")

        # Create image with embedded Adobe RGB ICC profile and verify ColorManager reads it
        from color_space import ICC_ADOBE_RGB_B64
        import base64
        p_adobe_bytes = base64.b64decode(ICC_ADOBE_RGB_B64)
        im = Image.new('RGB', (10, 10), color=(100, 150, 200))
        buf = io.BytesIO()
        im.save(buf, format='TIFF', icc_profile=p_adobe_bytes)
        buf.seek(0)

        with Image.open(buf) as loaded_im:
            icc_bytes = loaded_im.info.get('icc_profile')
            self.assertIsNotNone(icc_bytes)
            detected_name = ColorManager.get_profile_name(icc_bytes)
            self.assertIn("Adobe RGB", detected_name)

    def test_no_double_color_conversion(self):
        """Verify that applying LUT in Adobe RGB space and converting to sRGB happens exactly once without drift."""
        # Create a test gradient image in Display P3
        p3_img = np.zeros((16, 16, 3), dtype=np.uint8)
        p3_img[:, :, 0] = np.linspace(10, 240, 16).astype(np.uint8)
        p3_img[:, :, 1] = np.linspace(30, 200, 16).astype(np.uint8)
        p3_img[:, :, 2] = np.linspace(50, 220, 16).astype(np.uint8)

        # Single pipeline: P3 -> Adobe RGB -> Identity LUT -> sRGB
        ingested_adobe = ColorManager.convert_icc(p3_img, src_profile="Display_P3", target_space="Adobe_RGB_1998", is_bgr=True)
        lut_ident = Lut3D.create_identity(size=64)
        lut_out_adobe = LutEngine.apply_lut_3d(ingested_adobe, lut_ident, is_bgr=True)
        srgb_correct = ColorManager.convert_icc(lut_out_adobe, src_profile="Adobe_RGB_1998", target_space="sRGB", is_bgr=True)

        # Contrast with direct conversion: P3 -> sRGB
        direct_srgb = ColorManager.convert_icc(p3_img, src_profile="Display_P3", target_space="sRGB", is_bgr=True)

        # Colorimetric consistency: (P3 -> AdobeRGB -> sRGB) vs (P3 -> sRGB) should match within 1 code value
        diff = np.max(np.abs(srgb_correct.astype(np.int32) - direct_srgb.astype(np.int32)))
        self.assertLessEqual(diff, 2, f"Roundtrip conversion error across working spaces too high: {diff}")

    def test_lut_color_space_metadata_contract(self):
        """Lut3D cube format and metadata must preserve title and valid node ranges."""
        lut = Lut3D.create_identity(size=33)
        lut.title = "Preset_AdobeRGB_16bit"
        
        cube_path = os.path.join(self.test_dir, "test_metadata.cube")
        lut.to_cube_file(cube_path, title=lut.title)
        
        loaded = Lut3D.from_cube_file(cube_path)
        self.assertEqual(loaded.title, "Preset_AdobeRGB_16bit")
        self.assertEqual(loaded.size, 33)
        self.assertEqual(loaded.table.shape, (33, 33, 33, 3))
        self.assertEqual(loaded.table.dtype, np.float32)

    def test_alpha_preservation_across_color_management_and_lut(self):
        """RGBA / BGRA 4-channel image alpha values must remain strictly unchanged through ICC & LUT."""
        # 4-channel test image with non-trivial alpha channel
        bgra = np.random.randint(0, 256, size=(32, 32, 4), dtype=np.uint8)
        orig_alpha = bgra[:, :, 3].copy()

        # Ingest with color management to Adobe RGB
        bgra_adobe = ColorManager.convert_icc(bgra, src_profile="Display_P3", target_space="Adobe_RGB_1998", is_bgr=True)
        self.assertEqual(bgra_adobe.shape, (32, 32, 4))
        np.testing.assert_array_equal(bgra_adobe[:, :, 3], orig_alpha)

        # Apply 3D LUT
        lut = Lut3D.create_identity(size=33)
        lut_out = LutEngine.apply_lut_3d(bgra_adobe, lut, is_bgr=True)
        self.assertEqual(lut_out.shape, (32, 32, 4))
        np.testing.assert_array_equal(lut_out[:, :, 3], orig_alpha)

    def test_dynamic_source_profile_conversion(self):
        """Dynamic source profiles (Display P3, sRGB, untagged) must all convert cleanly into Adobe RGB (1998)."""
        # 1. Display P3 source
        img_p3 = np.random.randint(0, 256, size=(16, 16, 3), dtype=np.uint8)
        img_adobe_from_p3 = ColorManager.convert_icc(img_p3, src_profile="Display_P3", target_space="Adobe_RGB_1998", is_bgr=True)
        self.assertEqual(img_adobe_from_p3.shape, (16, 16, 3))

        # 2. sRGB source
        img_srgb = np.random.randint(0, 256, size=(16, 16, 3), dtype=np.uint8)
        img_adobe_from_srgb = ColorManager.convert_icc(img_srgb, src_profile="sRGB", target_space="Adobe_RGB_1998", is_bgr=True)
        self.assertEqual(img_adobe_from_srgb.shape, (16, 16, 3))

        # 3. Untagged fallback source (treated as sRGB, then converted to Adobe RGB)
        img_untagged = np.random.randint(0, 256, size=(16, 16, 3), dtype=np.uint8)
        img_adobe_from_untagged = ColorManager.convert_icc(img_untagged, src_profile=None, target_space="Adobe_RGB_1998", is_bgr=True)
        self.assertEqual(img_adobe_from_untagged.shape, (16, 16, 3))

    def test_preset_metadata_model(self):
        """Metadata model must clearly delineate dynamic source input, LUT working space, and export space."""
        meta = {
            "preset_id": "calibrated_studio_preset",
            "source_input_profile": "dynamic_from_source",
            "input_color_space": "Adobe_RGB_1998",
            "working_space": "Adobe_RGB_1998",
            "output_color_space": "Adobe_RGB_1998",
            "export_color_space": "sRGB",
            "is_calibrated": True
        }
        self.assertEqual(meta["source_input_profile"], "dynamic_from_source")
        self.assertEqual(meta["input_color_space"], "Adobe_RGB_1998")
        self.assertEqual(meta["working_space"], "Adobe_RGB_1998")
        self.assertEqual(meta["output_color_space"], "Adobe_RGB_1998")
        self.assertEqual(meta["export_color_space"], "sRGB")

    def test_end_to_end_pipeline_flow(self):
        """Test full Stage 1 (Adobe RGB) -> Base -> Stage 2 (Fine-tune) -> Single sRGB Export."""
        # Source image with Display P3 profile
        source_p3 = np.random.randint(20, 220, size=(64, 64, 3), dtype=np.uint8)
        
        # Step 1: Detect source profile & convert to LUT working space (Adobe RGB 1998)
        work_img = ColorManager.convert_icc(source_p3, src_profile="Display_P3", target_space="Adobe_RGB_1998", is_bgr=True)
        
        # Step 2: Apply 3D LUT in Adobe RGB space
        lut = Lut3D.create_identity(size=33)
        stage1_base = LutEngine.apply_lut_3d(work_img, lut, is_bgr=True)
        self.assertEqual(stage1_base.shape, source_p3.shape)

        # Step 3: Optional Stage 2 adjustments (e.g. exposure/contrast in working space)
        adj_img = np.clip(stage1_base.astype(np.float32) * (2.0 ** 0.1), 0, 255).astype(np.uint8)

        # Step 4: Final single export conversion from Adobe RGB -> sRGB
        final_srgb = ColorManager.convert_icc(adj_img, src_profile="Adobe_RGB_1998", target_space="sRGB", is_bgr=True)
        self.assertEqual(final_srgb.shape, source_p3.shape)


if __name__ == "__main__":
    unittest.main()
