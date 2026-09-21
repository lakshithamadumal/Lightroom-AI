"""
Lightroom AI - Studio Edition 2.0
Unit and Regression Tests for EXIF Orientation Ingestion Normalization.

Covers:
- EXIF Orientation 1 (Normal / Unchanged)
- EXIF Orientation 3 (180 deg)
- EXIF Orientation 6 (90 deg CW display / portrait sensor)
- EXIF Orientation 8 (90 deg CCW / 270 deg CW display)
- Smartphone portrait photo (sensor landscape + EXIF 6 -> physical portrait buffer)
- Smartphone landscape photo (sensor landscape + EXIF 1 -> physical landscape buffer)
- Pipeline end-to-end processing with Stage 1, Stage 2, and Smart Crop
- Real test photo (2024_10_22_16_20_IMG_4543.JPG) if present on disk
"""

import os
import io
import unittest
import tempfile
import numpy as np
from PIL import Image

from color_space import ColorSpace, ColorManager
from image_pipeline import ImagePipeline
from smart_cropper import SmartCropper


class TestExifOrientation(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_test_image(self, width: int, height: int, orientation: int) -> str:
        """
        Creates an asymmetric test image with distinct quadrant colors and an EXIF orientation tag.
        Top-Left: Red (255, 0, 0)
        Top-Right: Green (0, 255, 0)
        Bottom-Left: Blue (0, 0, 255)
        Bottom-Right: Yellow (255, 255, 0)
        """
        img_arr = np.zeros((height, width, 3), dtype=np.uint8)
        half_h = height // 2
        half_w = width // 2

        img_arr[:half_h, :half_w] = [255, 0, 0]      # Top-Left: Red
        img_arr[:half_h, half_w:] = [0, 255, 0]      # Top-Right: Green
        img_arr[half_h:, :half_w] = [0, 0, 255]      # Bottom-Left: Blue
        img_arr[half_h:, half_w:] = [255, 255, 0]    # Bottom-Right: Yellow

        pil_img = Image.fromarray(img_arr)
        exif = pil_img.getexif()
        exif[0x0112] = orientation

        file_path = os.path.join(self.temp_dir.name, f"test_orient_{orientation}.jpg")
        pil_img.save(file_path, format="JPEG", exif=exif)
        return file_path

    def test_orientation_1_normal(self):
        """Orientation 1 (normal): pixel buffer and dimensions remain unchanged."""
        path = self._create_test_image(width=100, height=60, orientation=1)
        bgr, meta = ColorManager.read_image_color_managed(path, target_space=ColorSpace.SRGB)

        self.assertIsNotNone(bgr)
        self.assertEqual(meta["dimensions"], (100, 60))
        self.assertEqual(bgr.shape, (60, 100, 3))
        # Top-left is Red in RGB -> [0, 0, 255] in BGR (or near due to JPEG)
        self.assertGreater(int(bgr[10, 10, 2]), 200)  # Red channel
        self.assertLess(int(bgr[10, 10, 0]), 50)      # Blue channel

    def test_orientation_3_180_deg(self):
        """Orientation 3 (180 deg): pixel buffer rotated 180 degrees."""
        path = self._create_test_image(width=100, height=60, orientation=3)
        bgr, meta = ColorManager.read_image_color_managed(path, target_space=ColorSpace.SRGB)

        self.assertIsNotNone(bgr)
        self.assertEqual(meta["dimensions"], (100, 60))
        self.assertEqual(bgr.shape, (60, 100, 3))
        # With 180 deg rotation, original Bottom-Right (Yellow [255, 255, 0]) moves to Top-Left
        self.assertGreater(int(bgr[10, 10, 2]), 200)  # Red
        self.assertGreater(int(bgr[10, 10, 1]), 200)  # Green
        # Original Top-Left (Red [255, 0, 0]) moves to Bottom-Right
        self.assertGreater(int(bgr[50, 90, 2]), 200)  # Red
        self.assertLess(int(bgr[50, 90, 0]), 50)      # Blue
        self.assertLess(int(bgr[50, 90, 1]), 50)      # Green

    def test_orientation_6_90_deg_cw(self):
        """Orientation 6 (90 deg CW): sensor landscape (100x60) becomes upright portrait (60x100)."""
        path = self._create_test_image(width=100, height=60, orientation=6)
        bgr, meta = ColorManager.read_image_color_managed(path, target_space=ColorSpace.SRGB)

        self.assertIsNotNone(bgr)
        self.assertEqual(meta["dimensions"], (60, 100))  # (W, H)
        self.assertEqual(bgr.shape, (100, 60, 3))        # (H, W, C)
        # Orientation 6 rotates 90 deg CW:
        # Original Bottom-Left (Blue [0, 0, 255]) becomes Top-Left
        self.assertGreater(int(bgr[10, 10, 0]), 200)  # Blue channel high
        self.assertLess(int(bgr[10, 10, 2]), 50)      # Red channel low

    def test_orientation_8_90_deg_ccw(self):
        """Orientation 8 (90 deg CCW / 270 deg CW): sensor portrait (60x100) becomes landscape (100x60)."""
        path = self._create_test_image(width=60, height=100, orientation=8)
        bgr, meta = ColorManager.read_image_color_managed(path, target_space=ColorSpace.SRGB)

        self.assertIsNotNone(bgr)
        self.assertEqual(meta["dimensions"], (100, 60))  # (W, H)
        self.assertEqual(bgr.shape, (60, 100, 3))        # (H, W, C)
        # Orientation 8 rotates 90 deg CCW:
        # Original Top-Right (Green [0, 255, 0]) becomes Top-Left
        self.assertGreater(int(bgr[10, 10, 1]), 200)  # Green channel high
        self.assertLess(int(bgr[10, 10, 2]), 50)      # Red channel low

    def test_phone_portrait_photo_simulation(self):
        """Smartphone portrait photo: sensor saves 400x300 landscape with EXIF orientation 6."""
        path = self._create_test_image(width=400, height=300, orientation=6)
        bgr, meta = ColorManager.read_image_color_managed(path, target_space=ColorSpace.ADOBE_RGB)

        self.assertIsNotNone(bgr)
        # Physical buffer must be upright portrait: height=400, width=300
        self.assertEqual(bgr.shape, (400, 300, 3))
        self.assertEqual(meta["dimensions"], (300, 400))

    def test_phone_landscape_photo_simulation(self):
        """Smartphone landscape photo: sensor saves 400x300 landscape with EXIF orientation 1."""
        path = self._create_test_image(width=400, height=300, orientation=1)
        bgr, meta = ColorManager.read_image_color_managed(path, target_space=ColorSpace.ADOBE_RGB)

        self.assertIsNotNone(bgr)
        # Physical buffer must be upright landscape: height=300, width=400
        self.assertEqual(bgr.shape, (300, 400, 3))
        self.assertEqual(meta["dimensions"], (400, 300))

    def test_pipeline_end_to_end_orientation_preservation(self):
        """
        End-to-end pipeline test:
        Ingest EXIF-oriented photo -> Stage 1 Base -> Stage 2 Balanced -> Smart Crop -> Export.
        Verify that image dimensions and orientation remain stable and upright throughout all stages.
        """
        from stage2_adjuster import Stage2Adjuster
        path = self._create_test_image(width=200, height=120, orientation=6)
        # Ingest in Adobe RGB working space
        bgr_adobe, meta = ColorManager.read_image_color_managed(path, target_space=ColorSpace.ADOBE_RGB)
        self.assertEqual(bgr_adobe.shape, (200, 120, 3))

        # Stage 1: Preset application (identity / base)
        stage1_base = bgr_adobe.copy()
        self.assertEqual(stage1_base.shape, (200, 120, 3))

        # Stage 2: Balanced buffer
        stage2_balanced, stage2_meta = Stage2Adjuster.apply_stage2_adjustments(
            stage1_base,
            {"exposure_ev": 0.1, "highlights": -2.0, "shadows": 2.0}
        )
        self.assertEqual(stage2_balanced.shape, (200, 120, 3))

        # Smart Crop stage (Priority 3: full frame or Priority 1 manual)
        crop_stage_out, crop_meta = ImagePipeline.apply_crop_stage(
            stage2_balanced_bgr=stage2_balanced,
            adjustments={"crop_top": 0.05, "crop_bottom": 0.05, "crop_left": 0.05, "crop_right": 0.05},
            enable_smart_crop=False
        )
        # Verify crop output is upright (180, 108, 3)
        self.assertEqual(crop_stage_out.shape, (180, 108, 3))

        # Export to sRGB
        srgb_export = ColorManager.convert_icc(
            crop_stage_out,
            src_profile=ColorSpace.ADOBE_RGB.value,
            target_space=ColorSpace.SRGB,
            is_bgr=True
        )
        self.assertEqual(srgb_export.shape, crop_stage_out.shape)

    def test_real_photo_img_4543_if_available(self):
        """If 2024_10_22_16_20_IMG_4543.JPG is present on disk, verify orientation normalization."""
        real_path = "D:/Media_Incoming/2024_10_22_16_20_IMG_4543.JPG"
        if not os.path.exists(real_path):
            self.skipTest(f"Real test file {real_path} not found.")

        bgr, meta = ColorManager.read_image_color_managed(real_path, target_space=ColorSpace.ADOBE_RGB)
        self.assertIsNotNone(bgr)
        # Raw sensor is (1242, 2208) with EXIF 8 -> Normalized physical buffer must be (1242, 2208, 3) (H: 1242, W: 2208)
        self.assertEqual(meta["dimensions"], (2208, 1242))
        self.assertEqual(bgr.shape, (1242, 2208, 3))


if __name__ == "__main__":
    unittest.main()
