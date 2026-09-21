"""
Lightroom AI - Studio Edition 2.0
Regression Tests: Subject-Safe Smart Crop Validation (test_smart_crop_safety.py)
"""

import unittest
import numpy as np
from smart_cropper import SmartCropper


class TestSmartCropSafety(unittest.TestCase):
    """Verifies subject-safe bounding box gates and face protection."""

    def setUp(self):
        self.cropper = SmartCropper()
        self.orig_w = 4000
        self.orig_h = 3000

    def test_valid_conservative_crop(self):
        """Standard valid 3:2 landscape framing crop."""
        crop_box = [0.08, 0.05, 0.95, 0.95]
        is_valid, reason, box_data = SmartCropper.validate_crop_safety(
            crop_box, self.orig_w, self.orig_h
        )
        self.assertTrue(is_valid)
        self.assertIsNotNone(box_data)
        y1, y2, x1, x2, w_ratio, h_ratio, area_ratio = box_data
        self.assertAlmostEqual(area_ratio, 0.90 * 0.87, places=3)

    def test_area_under_40_percent_rejected(self):
        """Reject crop that preserves less than 40% area."""
        crop_box = [0.2, 0.2, 0.7, 0.7] # 0.5 * 0.5 = 0.25 (25%)
        is_valid, reason, box_data = SmartCropper.validate_crop_safety(
            crop_box, self.orig_w, self.orig_h
        )
        self.assertFalse(is_valid)
        self.assertIn("40%", reason)
        self.assertIsNone(box_data)

    def test_aggressive_vertical_top_crop_rejected(self):
        """Reject crop that cuts more than safe top headroom."""
        # ymin = 0.35 (35% top trim exceeds 22% limit)
        crop_box = [0.35, 0.05, 0.98, 0.95]
        is_valid, reason, box_data = SmartCropper.validate_crop_safety(
            crop_box, self.orig_w, self.orig_h
        )
        self.assertFalse(is_valid)
        self.assertIn("Aggressive top crop", reason)

    def test_aggressive_vertical_bottom_crop_rejected(self):
        """Reject crop that cuts below safe baseline."""
        # ymax = 0.65 (35% bottom trim cuts below 78% limit)
        crop_box = [0.05, 0.05, 0.65, 0.95]
        is_valid, reason, box_data = SmartCropper.validate_crop_safety(
            crop_box, self.orig_w, self.orig_h
        )
        self.assertFalse(is_valid)
        self.assertIn("Aggressive bottom crop", reason)

    def test_face_headroom_violation_rejected(self):
        """Reject crop that cuts into detected face headroom/hair."""
        # Face at y=300 (top=10%), height=600 (20%) -> headroom requirement = 3% -> safe top <= 7%
        faces = [(1000, 300, 600, 600)]
        crop_box = [0.15, 0.05, 0.95, 0.95] # ymin=0.15 cuts through top of head
        is_valid, reason, box_data = SmartCropper.validate_crop_safety(
            crop_box, self.orig_w, self.orig_h, detected_faces=faces
        )
        self.assertFalse(is_valid)
        self.assertIn("head/hair", reason)

    def test_face_chin_decapitation_rejected(self):
        """Reject crop that decapitates or cuts chin of detected face."""
        # Face at y=1500 (bottom=2100 / 70%) -> chin req = 7% -> safe ymax >= 77%
        faces = [(1000, 1500, 600, 600)]
        crop_box = [0.05, 0.05, 0.72, 0.95] # ymax=0.72 cuts too close to chin
        is_valid, reason, box_data = SmartCropper.validate_crop_safety(
            crop_box, self.orig_w, self.orig_h, detected_faces=faces
        )
        self.assertFalse(is_valid)
        self.assertIn("decapitates", reason)

    def test_multiple_faces_group_containment(self):
        """Crop must safely contain all people in group shots."""
        faces = [
            (500, 600, 400, 400),   # Left person
            (2500, 600, 400, 400),  # Right person
        ]
        # Crop trimming right person's face
        crop_box = [0.05, 0.05, 0.95, 0.60] # xmax = 0.60 (2400px), cuts right face at x=2500
        is_valid, reason, box_data = SmartCropper.validate_crop_safety(
            crop_box, self.orig_w, self.orig_h, detected_faces=faces
        )
        self.assertFalse(is_valid)
        self.assertIn("Subject safety violation", reason)

    def test_fallback_with_faces_preserves_subject(self):
        """Fallback smart crop automatically adapts boundaries to detected faces."""
        dummy_img = np.zeros((3000, 4000, 3), dtype=np.uint8)
        # Face near top edge (y=100..400)
        faces = [(1500, 100, 300, 300)]
        cropped, tele = self.cropper._fallback_smart_crop(dummy_img, detected_faces=faces)
        self.assertIsNotNone(cropped)
        # Default ymin would be 0.08 (240px), which would cut face at 100px.
        # Fallback should shift ymin lower to protect the face!
        self.assertLess(tele["ymin"], 0.08)
        self.assertTrue(tele["fallback_used"])

    def test_backward_compatibility_wrapper(self):
        """validate_crop_box delegates cleanly without errors."""
        crop_box = [0.1, 0.1, 0.9, 0.9]
        is_valid, reason, box_data = SmartCropper.validate_crop_box(crop_box, 1000, 1000)
        self.assertTrue(is_valid)
        self.assertIsNotNone(box_data)


if __name__ == "__main__":
    unittest.main()
