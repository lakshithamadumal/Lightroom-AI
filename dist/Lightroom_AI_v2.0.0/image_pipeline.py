"""
Lightroom AI - Studio Edition 2.0
Unified Two-Stage Processing, Smart Crop & Color Ingestion Pipeline (image_pipeline.py)

STRICT PRODUCTION PIPELINE ORDER:
1. Dynamic ICC Ingest (Source ICC -> Adobe RGB 1998 Working Space)
2. Stage 1: Immutable Preset Base (64^3 Float32 3D LUT + Spatial Adjustments) -> Full-Frame Stage 1 Base Buffer
3. Stage 2: AI Scene & Exposure Auto-Balancing (Constrained & Style-Preserving) -> Full-Frame Stage 2 Balanced Buffer
4. Optional Smart Crop: Priority 1 Manual Overrides | Priority 2 AI Smart Crop | Priority 3 Full-Frame
5. Delivery Export: Single Final Working Space (Adobe RGB 1998) -> Export Space (sRGB) Conversion
"""

import os
import cv2
import numpy as np
from typing import Dict, Any, Tuple, Optional, Union

from lut_engine import LutEngine
from color_space import ColorSpace, ColorManager
from spatial_adjuster import SpatialAdjuster
from preset_bundle import PresetBundle


class ImagePipeline:
    """Orchestrates Stage 1, Stage 2, Smart Crop, and Delivery Export pipelines."""

    @classmethod
    def ingest_image(
        cls,
        path: str,
        target_space: Union[str, ColorSpace] = ColorSpace.SRGB
    ) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Safely reads an image from disk and normalizes color space based on embedded ICC profile.
        Returns (normalized_bgr_image, metadata_dict).
        """
        return ColorManager.read_image_color_managed(path, target_space=target_space)

    @classmethod
    def render_stage1_preset_base(
        cls,
        image_bgr: np.ndarray,
        bundle: PresetBundle,
        icc_profile: Optional[Union[bytes, str]] = None,
        source_path: Optional[str] = None
    ) -> np.ndarray:
        """
        STAGE 1: Produces the pristine full-frame Preset Base image in Adobe RGB 1998 working space.
        1. Ingests and normalizes input image to LUT declared input color space via ICC color management.
        2. Evaluates 3D LUT in high-precision floating point working space.
        3. Executes runtime spatial filters (Clarity, Texture, Dehaze, Sharpening, Grain).
        This output is immutable and full-frame.
        """
        if image_bgr is None:
            return None

        # 1. Format normalization & Alpha channel extraction
        has_alpha = False
        alpha_channel = None
        if image_bgr.ndim == 2:
            img_bgr = cv2.cvtColor(image_bgr, cv2.COLOR_GRAY2BGR)
        elif len(image_bgr.shape) == 3 and image_bgr.shape[2] == 4:
            has_alpha = True
            alpha_channel = image_bgr[:, :, 3]
            img_bgr = cv2.cvtColor(image_bgr, cv2.COLOR_BGRA2BGR)
        else:
            img_bgr = image_bgr

        # 2. Input ICC Color Management Normalization
        target_input_space = getattr(bundle, "input_color_space", "Adobe_RGB_1998") or "Adobe_RGB_1998"
        
        # If source path given and no explicit ICC profile passed, extract from file
        if icc_profile is None and source_path and os.path.exists(source_path):
            icc_profile = ColorManager.extract_icc_profile(source_path)

        if icc_profile is not None:
            img_bgr = ColorManager.convert_icc(
                img_bgr,
                src_profile=icc_profile,
                target_space=target_input_space,
                is_bgr=True
            )

        # 3. 3D LUT Application (Evaluated directly in declared working space)
        if bundle.lut is not None:
            lut_graded_bgr = LutEngine.apply_lut_3d(img_bgr, bundle.lut, is_bgr=True)
        else:
            lut_graded_bgr = img_bgr.copy()

        # 4. Spatial Processing (Clarity, Texture, Dehaze, Sharpening, Vignette, Grain)
        runtime_spatial = bundle.get_runtime_spatial_params() if hasattr(bundle, 'get_runtime_spatial_params') else (bundle.spatial_params or {})
        if runtime_spatial:
            stage1_out = SpatialAdjuster.apply_spatial_bundle(lut_graded_bgr, runtime_spatial)
        else:
            stage1_out = lut_graded_bgr

        # 5. Restore Alpha channel if originally present
        if has_alpha and alpha_channel is not None:
            stage1_out = np.dstack((stage1_out, alpha_channel))

        return stage1_out

    @classmethod
    def render_stage2_adjustments(
        cls,
        stage1_base_bgr: np.ndarray,
        adjustments: Optional[Dict[str, Any]] = None
    ) -> np.ndarray:
        """
        STAGE 2: Executes interactive fine-tuning and AI balance on top of Stage 1 base
        in the wide-gamut Adobe RGB 1998 working space buffer.
        Produces full-frame Stage 2 Balanced Buffer without spatial crop.
        """
        if stage1_base_bgr is None:
            return None

        adj = adjustments or {}
        # Delegate parametric trims to Stage2Adjuster (color-management-aware Lab/Linear processing)
        from stage2_adjuster import Stage2Adjuster
        stage2_balanced, _ = Stage2Adjuster.apply_stage2_adjustments(stage1_base_bgr, adj)
        return stage2_balanced

    @classmethod
    def apply_crop_stage(
        cls,
        stage2_balanced_bgr: np.ndarray,
        adjustments: Optional[Dict[str, Any]] = None,
        smart_cropper: Optional[Any] = None,
        enable_smart_crop: bool = False
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        OPTIONAL SMART CROP STAGE:
        Executes strictly AFTER Stage 2 on the full-frame Stage 2 Balanced Buffer.
        
        Precedence Hierarchy:
        - Priority 1: User Manual Crop Sliders (crop_top, crop_bottom, crop_left, crop_right)
        - Priority 2: AI Smart Crop (if enable_smart_crop=True)
        - Priority 3: Disabled / Full-Frame Pass-Through (enable_smart_crop=False)
        
        Returns:
            (cropped_working_buffer, crop_telemetry)
        """
        if stage2_balanced_bgr is None:
            return None, {}

        adj = adjustments or {}
        crop_top = float(adj.get("crop_top", 0.0))
        crop_bottom = float(adj.get("crop_bottom", 0.0))
        crop_left = float(adj.get("crop_left", 0.0))
        crop_right = float(adj.get("crop_right", 0.0))

        has_manual_crop = (crop_top > 1e-4 or crop_bottom > 1e-4 or crop_left > 1e-4 or crop_right > 1e-4)

        from smart_cropper import SmartCropper

        # Priority 1: User Manual Crop Overrides
        if has_manual_crop:
            return SmartCropper.apply_manual_crop(
                stage2_balanced_bgr,
                crop_top=crop_top,
                crop_bottom=crop_bottom,
                crop_left=crop_left,
                crop_right=crop_right
            )

        # Priority 2: AI Smart Crop (if enabled)
        if enable_smart_crop:
            cropper = smart_cropper or SmartCropper()
            return cropper.crop_best_landscape(stage2_balanced_bgr, enable_ai=True)

        # Priority 3: Disabled -> exact full-frame Stage 2 buffer
        cropper = smart_cropper or SmartCropper()
        return cropper.crop_best_landscape(stage2_balanced_bgr, enable_ai=False)

    @classmethod
    def export_final_image(
        cls,
        working_img_bgr: np.ndarray,
        bundle: PresetBundle,
        target_export_space: Optional[Union[str, ColorSpace]] = None
    ) -> np.ndarray:
        """
        Converts the Stage 1 / Stage 2 / Cropped working buffer (Adobe RGB 1998)
        to the final delivery export color space (standard sRGB).
        Guarantees exactly ONE final color transformation.
        """
        if working_img_bgr is None:
            return None

        src_space = getattr(bundle, "output_color_space", "Adobe_RGB_1998") or "Adobe_RGB_1998"
        dst_space = target_export_space or getattr(bundle, "export_color_space", "sRGB") or "sRGB"

        return ColorManager.convert_icc(
            working_img_bgr,
            src_profile=src_space,
            target_space=dst_space,
            is_bgr=True
        )

    @classmethod
    def render_pipeline_all_stages(
        cls,
        image_bgr: np.ndarray,
        bundle: PresetBundle,
        adjustments: Optional[Dict[str, Any]] = None,
        icc_profile: Optional[Union[bytes, str]] = None,
        source_path: Optional[str] = None,
        smart_cropper: Optional[Any] = None,
        enable_smart_crop: bool = False
    ) -> Dict[str, Any]:
        """
        Executes full production pipeline exposing all stage buffer snapshots:
        1. Ingest -> Stage 1 Preset Base Buffer (Full-Frame, Adobe RGB 1998)
        2. Stage 2 AI Auto-Balancing -> Stage 2 Balanced Buffer (Full-Frame, Adobe RGB 1998)
        3. Optional Smart Crop -> Smart Crop Output (Adobe RGB 1998)
        4. Final Single Adobe RGB -> sRGB Delivery Export
        """
        stage1_base = cls.render_stage1_preset_base(
            image_bgr, bundle, icc_profile=icc_profile, source_path=source_path
        )
        stage2_balanced = cls.render_stage2_adjustments(stage1_base, adjustments or {})
        cropped_working, crop_telemetry = cls.apply_crop_stage(
            stage2_balanced,
            adjustments=adjustments,
            smart_cropper=smart_cropper,
            enable_smart_crop=enable_smart_crop
        )
        final_export = cls.export_final_image(cropped_working, bundle)

        return {
            "stage1_preset_base": stage1_base,
            "stage2_balanced_buffer": stage2_balanced,
            "smart_crop_output": cropped_working,
            "final_output": final_export,
            "crop_telemetry": crop_telemetry
        }

    @classmethod
    def render_full_pipeline(
        cls,
        image_bgr: np.ndarray,
        bundle: PresetBundle,
        adjustments: Optional[Dict[str, Any]] = None,
        icc_profile: Optional[Union[bytes, str]] = None,
        source_path: Optional[str] = None,
        smart_cropper: Optional[Any] = None,
        enable_smart_crop: bool = False
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Backward-compatible full pipeline entrypoint.
        Returns (final_export_srgb, stage1_base_working).
        """
        res = cls.render_pipeline_all_stages(
            image_bgr,
            bundle,
            adjustments=adjustments,
            icc_profile=icc_profile,
            source_path=source_path,
            smart_cropper=smart_cropper,
            enable_smart_crop=enable_smart_crop
        )
        return res["final_output"], res["stage1_preset_base"]
