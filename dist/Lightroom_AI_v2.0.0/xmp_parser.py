"""
Lightroom AI - Studio Edition 2.0
Lightroom XMP Preset Parser & Parameter Classifier

Features:
- Robust XML / RDF crs:* Camera Raw Settings extraction.
- Automatic parameter categorization: COLOR, TONE, SPATIAL, GEOMETRIC, OPTICAL, NOISE, MASK, PROFILE, UNSUPPORTED.
- Diagnostic reporting of parameters requiring calibration.
- Full ToneCurvePV2012 (Master & RGB splines) parsing.
- 8-Band HSL matrix and Color Grading (Split Toning) parsing.
"""

import re
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Tuple


class XmpCategory:
    COLOR = "COLOR"
    TONE = "TONE"
    SPATIAL = "SPATIAL"
    GEOMETRIC = "GEOMETRIC"
    OPTICAL = "OPTICAL"
    NOISE = "NOISE"
    MASK = "MASK"
    PROFILE = "PROFILE"
    UNSUPPORTED = "UNSUPPORTED"


# Parameter schema classifications
PARAMETER_SCHEMA = {
    # TONE
    "Exposure2012": XmpCategory.TONE,
    "Contrast2012": XmpCategory.TONE,
    "Highlights2012": XmpCategory.TONE,
    "Shadows2012": XmpCategory.TONE,
    "Whites2012": XmpCategory.TONE,
    "Blacks2012": XmpCategory.TONE,
    "ToneCurvePV2012": XmpCategory.TONE,
    "ToneCurvePV2012Red": XmpCategory.TONE,
    "ToneCurvePV2012Green": XmpCategory.TONE,
    "ToneCurvePV2012Blue": XmpCategory.TONE,

    # COLOR
    "Temperature": XmpCategory.COLOR,
    "Tint": XmpCategory.COLOR,
    "IncrementalTemperature": XmpCategory.COLOR,
    "IncrementalTint": XmpCategory.COLOR,
    "Vibrance": XmpCategory.COLOR,
    "Saturation": XmpCategory.COLOR,
    "SplitToningHighlightHue": XmpCategory.COLOR,
    "SplitToningHighlightSaturation": XmpCategory.COLOR,
    "SplitToningShadowHue": XmpCategory.COLOR,
    "SplitToningShadowSaturation": XmpCategory.COLOR,
    "SplitToningBalance": XmpCategory.COLOR,
    "ColorGradeMidtoneHue": XmpCategory.COLOR,
    "ColorGradeMidtoneSat": XmpCategory.COLOR,
    "ColorGradeShadowLum": XmpCategory.COLOR,
    "ColorGradeMidtoneLum": XmpCategory.COLOR,
    "ColorGradeHighlightLum": XmpCategory.COLOR,
    "ColorGradeBlending": XmpCategory.COLOR,
    "ColorGradeGlobalHue": XmpCategory.COLOR,
    "ColorGradeGlobalSat": XmpCategory.COLOR,
    "ColorGradeGlobalLum": XmpCategory.COLOR,

    # 8-Band HSL
    "HueAdjustmentRed": XmpCategory.COLOR,
    "HueAdjustmentOrange": XmpCategory.COLOR,
    "HueAdjustmentYellow": XmpCategory.COLOR,
    "HueAdjustmentGreen": XmpCategory.COLOR,
    "HueAdjustmentAqua": XmpCategory.COLOR,
    "HueAdjustmentBlue": XmpCategory.COLOR,
    "HueAdjustmentPurple": XmpCategory.COLOR,
    "HueAdjustmentMagenta": XmpCategory.COLOR,
    "SaturationAdjustmentRed": XmpCategory.COLOR,
    "SaturationAdjustmentOrange": XmpCategory.COLOR,
    "SaturationAdjustmentYellow": XmpCategory.COLOR,
    "SaturationAdjustmentGreen": XmpCategory.COLOR,
    "SaturationAdjustmentAqua": XmpCategory.COLOR,
    "SaturationAdjustmentBlue": XmpCategory.COLOR,
    "SaturationAdjustmentPurple": XmpCategory.COLOR,
    "SaturationAdjustmentMagenta": XmpCategory.COLOR,
    "LuminanceAdjustmentRed": XmpCategory.COLOR,
    "LuminanceAdjustmentOrange": XmpCategory.COLOR,
    "LuminanceAdjustmentYellow": XmpCategory.COLOR,
    "LuminanceAdjustmentGreen": XmpCategory.COLOR,
    "LuminanceAdjustmentAqua": XmpCategory.COLOR,
    "LuminanceAdjustmentBlue": XmpCategory.COLOR,
    "LuminanceAdjustmentPurple": XmpCategory.COLOR,
    "LuminanceAdjustmentMagenta": XmpCategory.COLOR,

    # SPATIAL
    "Clarity2012": XmpCategory.SPATIAL,
    "Texture": XmpCategory.SPATIAL,
    "Dehaze": XmpCategory.SPATIAL,
    "Sharpness": XmpCategory.SPATIAL,
    "SharpenRadius": XmpCategory.SPATIAL,
    "SharpenDetail": XmpCategory.SPATIAL,
    "SharpenEdgeMasking": XmpCategory.SPATIAL,

    # NOISE & GRAIN
    "LuminanceSmoothing": XmpCategory.NOISE,
    "ColorNoiseReduction": XmpCategory.NOISE,
    "GrainAmount": XmpCategory.NOISE,
    "GrainSize": XmpCategory.NOISE,
    "GrainFrequency": XmpCategory.NOISE,

    # GEOMETRIC & VIGNETTE
    "PostCropVignetteAmount": XmpCategory.GEOMETRIC,
    "PostCropVignetteMidpoint": XmpCategory.GEOMETRIC,
    "PostCropVignetteFeather": XmpCategory.GEOMETRIC,
    "PostCropVignetteRoundness": XmpCategory.GEOMETRIC,
    "PostCropVignetteStyle": XmpCategory.GEOMETRIC,
    "PerspectiveVertical": XmpCategory.GEOMETRIC,
    "PerspectiveHorizontal": XmpCategory.GEOMETRIC,

    # OPTICAL
    "LensProfileEnable": XmpCategory.OPTICAL,
    "AutoLateralCA": XmpCategory.OPTICAL,
    "Defringe": XmpCategory.OPTICAL,

    # PROFILE
    "CameraProfile": XmpCategory.PROFILE,
    "Look": XmpCategory.PROFILE,

    # MASK
    "MaskGroupBasedCorrections": XmpCategory.MASK,
    "CircularGradientBasedCorrections": XmpCategory.MASK,
    "PaintBasedCorrections": XmpCategory.MASK,
}


class XmpParser:
    """Parses Lightroom XMP Preset XML and extracts categorised parameters."""

    @classmethod
    def parse_xmp_content(cls, content: str) -> Dict[str, Any]:
        """Parses XMP XML text content."""
        # Clean up XMP XML wrapper if embedded
        xmp_start = content.find('<x:xmpmeta')
        xmp_end = content.find('</x:xmpmeta>')
        if xmp_start != -1 and xmp_end != -1:
            xmp_text = content[xmp_start:xmp_end + 12]
        else:
            xmp_text = content

        supported_params: Dict[str, Any] = {}
        unsupported_params: List[str] = []
        raw_attributes: Dict[str, str] = {}

        # 1. Extract all crs:* attributes via regex
        attr_matches = re.findall(r'crs:([A-Za-z0-9_]+)="([^"]*)"', xmp_text)
        for key, val in attr_matches:
            raw_attributes[key] = val

        # 2. Extract Seq lists (e.g. ToneCurvePV2012, ToneCurvePV2012Red, etc.)
        seq_matches = re.findall(r'<crs:([A-Za-z0-9_]+)>\s*<rdf:Seq>([\s\S]*?)</rdf:Seq>\s*</crs:\1>', xmp_text)
        for key, seq_inner in seq_matches:
            pts = re.findall(r'<rdf:li>\s*([+-]?\d*\.?\d+)\s*,\s*([+-]?\d*\.?\d+)\s*</rdf:li>', seq_inner)
            if pts:
                parsed_pts = [(float(px), float(py)) for px, py in pts]
                supported_params[key] = parsed_pts

        # 3. Classify and parse attributes
        for key, val_str in raw_attributes.items():
            category = PARAMETER_SCHEMA.get(key, XmpCategory.UNSUPPORTED)
            try:
                if '.' in val_str:
                    num_val = float(val_str)
                else:
                    num_val = int(val_str) if val_str.lstrip('-+').isdigit() else val_str
            except ValueError:
                num_val = val_str

            if category != XmpCategory.UNSUPPORTED:
                supported_params[key] = num_val
            else:
                unsupported_params.append(key)

        # 4. Extract structured HSL matrices
        hsl_hue = {}
        hsl_sat = {}
        hsl_lum = {}
        color_names = ["Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta"]

        for c in color_names:
            if f"HueAdjustment{c}" in supported_params:
                hsl_hue[c] = float(supported_params[f"HueAdjustment{c}"])
            if f"SaturationAdjustment{c}" in supported_params:
                hsl_sat[c] = float(supported_params[f"SaturationAdjustment{c}"])
            if f"LuminanceAdjustment{c}" in supported_params:
                hsl_lum[c] = float(supported_params[f"LuminanceAdjustment{c}"])

        # 5. Extract spatial adjustments
        spatial = {
            "clarity": float(supported_params.get("Clarity2012", 0.0)),
            "texture": float(supported_params.get("Texture", 0.0)),
            "dehaze": float(supported_params.get("Dehaze", 0.0)),
            "sharpening": {
                "amount": float(supported_params.get("Sharpness", 0.0)),
                "radius": float(supported_params.get("SharpenRadius", 1.0)),
                "detail": float(supported_params.get("SharpenDetail", 25.0)),
                "masking": float(supported_params.get("SharpenEdgeMasking", 0.0))
            },
            "vignette": {
                "amount": float(supported_params.get("PostCropVignetteAmount", 0.0)),
                "midpoint": float(supported_params.get("PostCropVignetteMidpoint", 50.0)),
                "feather": float(supported_params.get("PostCropVignetteFeather", 50.0)),
                "roundness": float(supported_params.get("PostCropVignetteRoundness", 0.0))
            },
            "grain": {
                "amount": float(supported_params.get("GrainAmount", 0.0)),
                "size": float(supported_params.get("GrainSize", 25.0)),
                "frequency": float(supported_params.get("GrainFrequency", 50.0))
            }
        }

        # 6. Default sliders
        default_sliders = {
            "exposure": float(supported_params.get("Exposure2012", 0.0)),
            "contrast": float(supported_params.get("Contrast2012", 0.0)),
            "highlights": float(supported_params.get("Highlights2012", 0.0)),
            "shadows": float(supported_params.get("Shadows2012", 0.0)),
            "whites": float(supported_params.get("Whites2012", 0.0)),
            "blacks": float(supported_params.get("Blacks2012", 0.0)),
            "temperature": float(supported_params.get("IncrementalTemperature", supported_params.get("Temperature", 0.0))),
            "tint": float(supported_params.get("IncrementalTint", supported_params.get("Tint", 0.0))),
            "vibrance": float(supported_params.get("Vibrance", 0.0)),
            "saturation": float(supported_params.get("Saturation", 0.0)),
        }

        # 7. Generate diagnostic calibration warnings
        calibration_needed_reasons = []
        if "Look" in supported_params or "CameraProfile" in supported_params:
            calibration_needed_reasons.append("Preset references Adobe proprietary Look or Camera Profile table.")
        if supported_params.get("Highlights2012", 0.0) != 0 or supported_params.get("Shadows2012", 0.0) != 0:
            calibration_needed_reasons.append("Preset uses adaptive Highlights/Shadows2012 curves requiring reference chart calibration.")
        if any(supported_params.get(f"HueAdjustment{c}", 0) != 0 for c in color_names):
            calibration_needed_reasons.append("Preset uses multi-color HSL twists.")

        return {
            "supported_parameters": supported_params,
            "unsupported_parameters": unsupported_params,
            "hsl_hue": hsl_hue,
            "hsl_sat": hsl_sat,
            "hsl_lum": hsl_lum,
            "tone_curves": {
                "master": supported_params.get("ToneCurvePV2012", [(0, 0), (255, 255)]),
                "red": supported_params.get("ToneCurvePV2012Red", None),
                "green": supported_params.get("ToneCurvePV2012Green", None),
                "blue": supported_params.get("ToneCurvePV2012Blue", None)
            },
            "spatial": spatial,
            "default_sliders": default_sliders,
            "calibration_recommended": len(calibration_needed_reasons) > 0,
            "calibration_reasons": calibration_needed_reasons,
        }

    @classmethod
    def parse_file(cls, filepath: str) -> Dict[str, Any]:
        """Loads and parses an XMP or DNG file."""
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        res = cls.parse_xmp_content(content)
        res["source_file"] = filepath
        return res
