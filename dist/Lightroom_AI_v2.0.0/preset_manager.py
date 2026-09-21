"""
Lightroom AI - Studio Edition 2.0
Core Preset Manager (preset_manager.py)

Hybrid Production Architecture:
- 32-bit floating point 64^3 3D LUT Evaluation (.cube and Level 8 Hald)
- Vectorized Trilinear Interpolation
- Wide-Gamut Linear Color Space Support (ProPhoto Linear, ACEScg, sRGB)
- Parametric Spatial Engine (Clarity, Texture, Dehaze, Sharpening, Vignette, Grain)
- Fallback Monotonic Spline & HSL Engine for raw XMP recipes
- Full backward-compatibility with existing pipeline
"""

import os
import re
import cv2
import numpy as np
from typing import Optional, Dict, Any

from lut_engine import Lut3D, LutEngine
from color_space import ColorSpace, ColorManager
from spatial_adjuster import SpatialAdjuster
from preset_bundle import PresetBundle
from xmp_parser import XmpParser
from image_pipeline import ImagePipeline


class PresetManager:
    """
    High-Fidelity Adobe Lightroom & Camera Raw Develop Engine.
    Loads and applies calibrated preset bundles, 3D LUTs, and XMP recipes.
    """

    def __init__(self, preset_folder: str = "C:/Media_Presets"):
        self.preset_folder = preset_folder
        self.bundle: PresetBundle = PresetBundle.load_from_file_or_folder(preset_folder)
        self.preset_name = self.bundle.name
        self.lut_image = self.bundle.lut.to_hald_image(level=8, bit_depth=8) if self.bundle.lut else None
        self.params = self._extract_params_dict()

    def _extract_params_dict(self) -> Dict[str, Any]:
        """Extracts legacy params dictionary for backwards compatibility."""
        p = {
            "name": self.bundle.name,
            "exposure": self.bundle.default_sliders.get("exposure", 0.0),
            "contrast": self.bundle.default_sliders.get("contrast", 0.0),
            "highlights": self.bundle.default_sliders.get("highlights", 0.0),
            "shadows": self.bundle.default_sliders.get("shadows", 0.0),
            "whites": self.bundle.default_sliders.get("whites", 0.0),
            "blacks": self.bundle.default_sliders.get("blacks", 0.0),
            "clarity": self.bundle.spatial_params.get("clarity", 0.0),
            "texture": self.bundle.spatial_params.get("texture", 0.0),
            "dehaze": self.bundle.spatial_params.get("dehaze", 0.0),
            "vibrance": self.bundle.default_sliders.get("vibrance", 0.0),
            "saturation": self.bundle.default_sliders.get("saturation", 0.0),
            "temp": self.bundle.default_sliders.get("temperature", 0.0),
            "tint": self.bundle.default_sliders.get("tint", 0.0),
            "vignette": self.bundle.spatial_params.get("vignette", {}).get("amount", 0.0) if isinstance(self.bundle.spatial_params.get("vignette"), dict) else 0.0,
            "is_calibrated": self.bundle.is_calibrated,
            "working_space": self.bundle.working_space,
            "unsupported_parameters": self.bundle.unsupported_parameters
        }
        return p

    def apply_preset(self, img_bgr: np.ndarray) -> np.ndarray:
        """
        STAGE 1: Executes high-fidelity preset rendering (3D LUT + Spatial Adjustments) in float32.
        Returns pristine Stage 1 develop image in declared working space (Adobe RGB 1998).
        """
        if img_bgr is None:
            return None

        # Execute Stage 1 via unified ImagePipeline
        return ImagePipeline.render_stage1_preset_base(img_bgr, self.bundle)

    def export_image(self, working_img_bgr: np.ndarray) -> np.ndarray:
        """
        Converts the wide-gamut working buffer (Adobe RGB 1998)
        to the final export color space (standard sRGB).
        """
        return ImagePipeline.export_final_image(working_img_bgr, self.bundle)

    def get_summary_text(self) -> str:
        """Returns descriptive human-readable summary of the active preset."""
        b = self.bundle
        calib_tag = " [100% Calibrated]" if b.is_calibrated else ""
        lut_tag = f"64³ Float32 LUT ({b.working_space})" if b.lut else "Parametric Splines"
        spatial_items = []
        if b.spatial_params.get("clarity"):
            spatial_items.append(f"Clarity: {b.spatial_params['clarity']:+.0f}")
        if b.spatial_params.get("texture"):
            spatial_items.append(f"Texture: {b.spatial_params['texture']:+.0f}")
        if b.spatial_params.get("dehaze"):
            spatial_items.append(f"Dehaze: {b.spatial_params['dehaze']:+.0f}")

        spatial_str = " | ".join(spatial_items)
        if spatial_str:
            spatial_str = f" | {spatial_str}"

        return f"Preset: {b.name}{calib_tag} | {lut_tag}{spatial_str}"

    def get_diagnostic_info(self) -> Dict[str, Any]:
        """Returns structured diagnostics for API and UI."""
        return self.bundle.get_summary()
