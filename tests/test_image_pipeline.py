"""
Unit tests for the Two-Stage Image Pipeline (image_pipeline.py).
"""

import unittest
import numpy as np

from image_pipeline import ImagePipeline
from preset_bundle import PresetBundle
from lut_engine import Lut3D


class TestImagePipeline(unittest.TestCase):

    def test_two_stage_immutability(self):
        """Stage 1 base image must remain identical regardless of Stage 2 adjustments."""
        lut = Lut3D.create_identity(size=33)
        bundle = PresetBundle(
            preset_id="test_preset",
            name="Test Preset",
            lut=lut,
            spatial_params={"clarity": 10.0, "vignette": {"amount": -10.0}}
        )

        test_img = np.random.randint(50, 200, size=(80, 80, 3), dtype=np.uint8)

        # Render Stage 1 base
        stage1_base = ImagePipeline.render_stage1_preset_base(test_img, bundle)
        stage1_copy = stage1_base.copy()

        # Apply aggressive Stage 2 adjustments
        adj = {
            "exposure": 1.2,
            "contrast": 25.0,
            "shadows": 30.0,
            "highlights": -20.0,
            "temperature": 15.0,
            "vibrance": 20.0,
            "clarity": 10.0
        }
        final_img = ImagePipeline.render_stage2_adjustments(stage1_base, adj)

        # Stage 1 copy must be 100% untouched
        np.testing.assert_array_equal(stage1_base, stage1_copy)
        # Final image must reflect adjustments
        self.assertFalse(np.array_equal(final_img, stage1_base))

        # Reset Stage 2: Passing empty dict to render_stage2_adjustments returns exact Stage 1 base
        reset_img = ImagePipeline.render_stage2_adjustments(stage1_base, {})
        np.testing.assert_array_equal(reset_img, stage1_base)


if __name__ == "__main__":
    unittest.main()
