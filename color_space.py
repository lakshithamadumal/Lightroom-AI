"""
Lightroom AI - Studio Edition 2.0
Color Management & Color Space Transformation Pipeline

Supports high-precision 32-bit floating point color space conversions:
- Non-linear sRGB (Standard IEC 61966-2-1 piecewise EOTF / OETF)
- Linear sRGB
- Linear ProPhoto RGB (ROMM RGB, ACR / Lightroom internal primary space)
- Linear ACEScg (Academy Color Encoding System)
- Linear Adobe RGB (1998)
- LittleCMS / Pillow ImageCms ICC Color Management (sRGB, Display P3, Adobe RGB 1998, Embedded ICC)
"""

import io
import os
import base64
import numpy as np
from enum import Enum
from typing import Union, Optional, Tuple, Dict, Any
from PIL import Image, ImageCms, ImageOps


class ColorSpace(str, Enum):
    SRGB = "sRGB"
    DISPLAY_P3 = "Display_P3"
    ADOBE_RGB = "Adobe_RGB_1998"
    LINEAR_SRGB = "Linear_sRGB"
    LINEAR_PROPHOTO = "Linear_ProPhoto"
    LINEAR_ACESCG = "Linear_ACEScg"


# Embedded standard reference ICC profiles (base64)
# Display P3 (Apple D65 / DCI-P3 primaries)
ICC_DISPLAY_P3_B64 = (
    "AAACJGFwcGwEAAAAbW50clJHQiBYWVogB+EABwAHAA0AFgAgYWNzcEFQUEwAAAAAQVBQTAAAAAAAAAAAAAAA"
    "AAAAAAAAAPbWAAEAAAAA0y1hcHBsyhqVgiV/EE04mRPV0eoVggAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAKZGVzYwAAAPwAAABlY3BydAAAAWQAAAAjd3RwdAAAAYgAAAAUclhZWgAAAZwAAAAUZ1hZWgAAAbAA"
    "AAAUYlhZWgAAAcQAAAAUclRSQwAAAdgAAAAgY2hhZAAAAfgAAAAsYlRSQwAAAdgAAAAgZ1RSQwAAAdgAAAAg"
    "ZGVzYwAAAAAAAAALRGlzcGxheSBQMwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB0ZXh0AAAAAENvcHlyaWdodCBBcHBs"
    "ZSBJbmMuLCAyMDE3AABYWVogAAAAAAAA81EAAQAAAAEWzFhZWiAAAAAAAACD3wAAPb////+7WFlaIAAAAAAA"
    "AEq/AACxNwAACrlYWVogAAAAAAAAKDgAABELAADIuXBhcmEAAAAAAAMAAAACZmYAAPKnAAANWQAAE9AAAApb"
    "c2YzMgAAAAAAAQxCAAAF3v//8yYAAAeTAAD9kP//+6L///2jAAAD3AAAwG4="
)

# Adobe RGB (1998) (Adobe D65 / Wide Gamut)
ICC_ADOBE_RGB_B64 = (
    "AAACMEFEQkUCEAAAbW50clJHQiBYWVogB88ABgADAAAAAAAAYWNzcEFQUEwAAAAAbm9uZQAAAAAAAAAAAAAAAAAAAAAAAPbWAAEAAAAA"
    "0y1BREJFAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAKY3BydAAAAPwAAAAyZGVzYwAAATAAAABr"
    "d3RwdAAAAZwAAAAUYmtwdAAAAbAAAAAUclRSQwAAAcQAAAAOZ1RSQwAAAdQAAAAOYlRSQwAAAeQAAAAOclhZWgAAAfQAAAAUZ1hZWgAA"
    "AggAAAAUYlhZWgAAAhwAAAAUdGV4dAAAAABDb3B5cmlnaHQgMTk5OSBBZG9iZSBTeXN0ZW1zIEluY29ycG9yYXRlZAAAAGRlc2MAAAAA"
    "AAAAEUFkb2JlIFJHQiAoMTk5OCkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAFhZWiAAAAAAAADzUQABAAAAARbMWFlaIAAAAAAAAAAAAAAAAAAAAABjdXJ2AAAAAAAAAAECMwAA"
    "Y3VydgAAAAAAAAABAjMAAGN1cnYAAAAAAAAAAQIzAABYWVogAAAAAAAAnBgAAE+lAAAE/FhZWiAAAAAAAAA0jQAAoCwAAA+VWFlaIAAA"
    "AAAAACYxAAAQLwAAvpw="
)


# Chromaticity matrices and transformation constants (float32)

# sRGB (D65) <-> XYZ (D65)
M_SRGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041]
], dtype=np.float32)

M_XYZ_TO_SRGB = np.linalg.inv(M_SRGB_TO_XYZ).astype(np.float32)

# ProPhoto RGB / ROMM RGB (D50 adapted to D65 via Bradford transform) <-> XYZ (D65)
M_PROPHOTO_TO_XYZ_D65 = np.array([
    [0.7976749, 0.1351917, 0.0313534],
    [0.2880402, 0.7118741, 0.0000857],
    [0.0000000, 0.0000000, 0.8252100]
], dtype=np.float32)

# Direct sRGB Linear <-> ProPhoto Linear (D65)
M_SRGB_TO_PROPHOTO = np.array([
    [0.5293465, 0.3300760, 0.1405775],
    [0.0983636, 0.8734652, 0.0281712],
    [0.0168798, 0.1176632, 0.8654570]
], dtype=np.float32)

M_PROPHOTO_TO_SRGB = np.linalg.inv(M_SRGB_TO_PROPHOTO).astype(np.float32)

# ACEScg (AP1 primaries, D60 adapted to D65) <-> sRGB Linear
M_SRGB_TO_ACESCG = np.array([
    [0.613097, 0.339523, 0.047379],
    [0.070194, 0.916354, 0.013452],
    [0.020616, 0.109570, 0.869814]
], dtype=np.float32)

M_ACESCG_TO_SRGB = np.linalg.inv(M_SRGB_TO_ACESCG).astype(np.float32)


class ColorManager:
    """Manages color space transformations, EOTF/OETF, and LittleCMS ICC color management."""

    _cached_profiles: Dict[str, Any] = {}

    @staticmethod
    def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
        """
        Exact IEC 61966-2-1 piecewise electro-optical transfer function (EOTF).
        Converts non-linear sRGB [0.0, 1.0] to scene-linear intensity [0.0, 1.0].
        """
        rgb_f = rgb.astype(np.float32)
        linear = np.where(
            rgb_f <= 0.04045,
            rgb_f / 12.92,
            np.power(np.maximum((rgb_f + 0.055) / 1.055, 0.0), 2.4)
        )
        return linear.astype(np.float32)

    @staticmethod
    def linear_to_srgb(linear_rgb: np.ndarray) -> np.ndarray:
        """
        Exact IEC 61966-2-1 piecewise opto-electronic transfer function (OETF).
        Converts scene-linear intensity [0.0, 1.0] back to non-linear sRGB.
        """
        lin_f = np.maximum(linear_rgb.astype(np.float32), 0.0)
        srgb = np.where(
            lin_f <= 0.0031308,
            lin_f * 12.92,
            1.055 * np.power(lin_f, 1.0 / 2.4) - 0.055
        )
        return srgb.astype(np.float32)

    @classmethod
    def extract_icc_profile(cls, image_source: Union[str, bytes, Image.Image, io.BytesIO]) -> Optional[bytes]:
        """
        Extracts raw ICC profile bytes from a file path, file buffer, or PIL Image.
        Returns None if image is untagged or ICC profile is absent.
        """
        if isinstance(image_source, Image.Image):
            return image_source.info.get("icc_profile")

        if isinstance(image_source, (str, bytes, io.BytesIO)):
            try:
                if isinstance(image_source, str):
                    if not os.path.exists(image_source):
                        return None
                    with Image.open(image_source) as im:
                        return im.info.get("icc_profile")
                elif isinstance(image_source, bytes):
                    # Check if raw ICC header ('acsp' tag at offset 36)
                    if len(image_source) >= 128 and image_source[36:40] == b"acsp":
                        return image_source
                    with Image.open(io.BytesIO(image_source)) as im:
                        return im.info.get("icc_profile")
                elif isinstance(image_source, io.BytesIO):
                    with Image.open(image_source) as im:
                        return im.info.get("icc_profile")
            except Exception:
                return None
        return None

    @classmethod
    def get_profile_name(cls, icc_input: Union[bytes, Any, str, None]) -> str:
        """
        Detects and returns a human-readable profile description/name.
        Explicit fallback: Returns 'Untagged (sRGB Fallback)' if no ICC profile is present.
        """
        if icc_input is None:
            return "Untagged (sRGB Fallback)"

        if isinstance(icc_input, str):
            clean_str = icc_input.strip()
            if clean_str in ["sRGB", "Display_P3", "Display P3", "Adobe_RGB_1998", "Adobe RGB (1998)"]:
                return clean_str
            return clean_str

        try:
            if isinstance(icc_input, bytes):
                prof = ImageCms.getOpenProfile(io.BytesIO(icc_input))
            else:
                prof = icc_input

            desc = ImageCms.getProfileDescription(prof).strip()
            name = ImageCms.getProfileName(prof).strip()
            return desc or name or "ICC Profile"
        except Exception:
            return "Untagged (sRGB Fallback)"

    @classmethod
    def get_cms_profile(cls, profile_spec: Union[str, bytes, Any, None]) -> Any:
        """
        Retrieves or instantiates an ImageCms profile object.
        Supports standard profile names ('sRGB', 'Display_P3', 'Display P3', 'Adobe_RGB_1998', 'Adobe RGB (1998)'),
        raw ICC bytes, or existing ImageCmsProfile instances.
        Documented fallback: If None or unrecognized, returns standard sRGB profile.
        """
        if isinstance(profile_spec, ImageCms.ImageCmsProfile):
            return profile_spec

        if profile_spec is None:
            if "sRGB" not in cls._cached_profiles:
                cls._cached_profiles["sRGB"] = ImageCms.createProfile("sRGB")
            return cls._cached_profiles["sRGB"]

        if isinstance(profile_spec, bytes):
            return ImageCms.getOpenProfile(io.BytesIO(profile_spec))

        if isinstance(profile_spec, str):
            norm_name = profile_spec.strip().lower().replace("-", "_").replace(" ", "_")
            if norm_name in ["srgb", "srgb_iec61966_2.1", "untagged", "default", "none"]:
                if "sRGB" not in cls._cached_profiles:
                    cls._cached_profiles["sRGB"] = ImageCms.createProfile("sRGB")
                return cls._cached_profiles["sRGB"]
            elif norm_name in ["display_p3", "displayp3", "p3", "dci_p3"]:
                if "Display_P3" not in cls._cached_profiles:
                    p3_bytes = base64.b64decode(ICC_DISPLAY_P3_B64)
                    cls._cached_profiles["Display_P3"] = ImageCms.getOpenProfile(io.BytesIO(p3_bytes))
                return cls._cached_profiles["Display_P3"]
            elif norm_name in ["adobe_rgb", "adobe_rgb_1998", "adobergb", "adobergb1998"]:
                if "Adobe_RGB_1998" not in cls._cached_profiles:
                    adobe_bytes = base64.b64decode(ICC_ADOBE_RGB_B64)
                    cls._cached_profiles["Adobe_RGB_1998"] = ImageCms.getOpenProfile(io.BytesIO(adobe_bytes))
                return cls._cached_profiles["Adobe_RGB_1998"]
            elif os.path.exists(profile_spec):
                with open(profile_spec, "rb") as f:
                    return ImageCms.getOpenProfile(f)

        # Default fallback
        if "sRGB" not in cls._cached_profiles:
            cls._cached_profiles["sRGB"] = ImageCms.createProfile("sRGB")
        return cls._cached_profiles["sRGB"]

    @classmethod
    def convert_icc(
        cls,
        image: np.ndarray,
        src_profile: Union[str, bytes, Any, None] = None,
        target_space: Union[str, ColorSpace] = ColorSpace.SRGB,
        is_bgr: bool = True
    ) -> np.ndarray:
        """
        Performs high-precision LittleCMS ICC profile color transformation.
        - Supports sRGB, Display P3, Adobe RGB (1998), and embedded custom ICC profiles.
        - Preserves Alpha channel 100% intact for RGBA / BGRA images.
        - Preserves numerical stability (no-op identity if src == target).
        - Documented fallback: Untagged images default to sRGB without modification.
        """
        if image is None or image.size == 0:
            return image

        target_name = str(target_space.value if isinstance(target_space, ColorSpace) else target_space)
        src_name = cls.get_profile_name(src_profile)

        # Check if source is untagged or already matches target space
        is_src_srgb = (src_profile is None) or ("sRGB" in src_name) or (src_name == "Untagged (sRGB Fallback)")
        is_target_srgb = (target_name.lower() in ["srgb", "linear_srgb", "default"])

        if is_src_srgb and is_target_srgb:
            # Numerically identical no-op
            return image.copy() if not isinstance(image, np.ndarray) else image

        # Separate Alpha channel if present (BGRA / RGBA)
        has_alpha = (image.ndim == 3 and image.shape[2] == 4)
        if has_alpha:
            color_channels = image[:, :, :3]
            alpha_channel = image[:, :, 3]
        elif image.ndim == 2:
            color_channels = np.stack([image, image, image], axis=2)
            has_alpha = False
            alpha_channel = None
        else:
            color_channels = image
            alpha_channel = None

        # Convert to standard RGB uint8 for LittleCMS transformation
        orig_dtype = color_channels.dtype
        if is_bgr:
            rgb_arr = color_channels[:, :, ::-1]
        else:
            rgb_arr = color_channels

        if orig_dtype == np.uint8:
            pil_img = Image.fromarray(rgb_arr)
        elif orig_dtype == np.uint16:
            pil_img = Image.fromarray((rgb_arr >> 8).astype(np.uint8))
        elif orig_dtype in (np.float32, np.float64):
            pil_img = Image.fromarray(np.clip(rgb_arr * 255.0, 0, 255).astype(np.uint8))
        else:
            pil_img = Image.fromarray(rgb_arr.astype(np.uint8))

        # Build and apply LittleCMS transform
        prof_src = cls.get_cms_profile(src_profile)
        prof_dst = cls.get_cms_profile(target_name)

        transform = ImageCms.buildTransform(prof_src, prof_dst, "RGB", "RGB", renderingIntent=0)
        transformed_pil = ImageCms.applyTransform(pil_img, transform)
        transformed_rgb = np.array(transformed_pil)

        # Convert back to requested color channel ordering and dtype
        if is_bgr:
            transformed_color = transformed_rgb[:, :, ::-1]
        else:
            transformed_color = transformed_rgb

        if orig_dtype in (np.float32, np.float64):
            transformed_color = (transformed_color.astype(np.float32) / 255.0)

        # Re-attach Alpha channel if original had alpha
        if has_alpha and alpha_channel is not None:
            if orig_dtype in (np.float32, np.float64) and alpha_channel.dtype != transformed_color.dtype:
                alpha_norm = alpha_channel.astype(np.float32) / 255.0 if alpha_channel.dtype == np.uint8 else alpha_channel
                return np.dstack((transformed_color, alpha_norm))
            return np.dstack((transformed_color, alpha_channel))

        return transformed_color

    @classmethod
    def read_image_color_managed(
        cls,
        path: str,
        target_space: Union[str, ColorSpace] = ColorSpace.SRGB
    ) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Safely ingests an image from disk, extracts its embedded ICC profile,
        and converts it to the requested target color space (default: sRGB).
        Returns (image_bgr, metadata_dict).
        """
        if not os.path.exists(path):
            return None, {"error": "File not found"}

        try:
            with Image.open(path) as pil_img:
                icc_bytes = pil_img.info.get("icc_profile")
                pil_img = ImageOps.exif_transpose(pil_img)
                profile_name = cls.get_profile_name(icc_bytes)
                has_icc = (icc_bytes is not None and len(icc_bytes) > 0)
                width, height = pil_img.size

                # Convert PIL to numpy RGB
                rgb_arr = np.array(pil_img.convert("RGB"))
                bgr_arr = rgb_arr[:, :, ::-1]

            if has_icc:
                normalized_bgr = cls.convert_icc(
                    bgr_arr,
                    src_profile=icc_bytes,
                    target_space=target_space,
                    is_bgr=True
                )
            else:
                normalized_bgr = bgr_arr

            metadata = {
                "path": path,
                "dimensions": (width, height),
                "source_profile": profile_name,
                "has_icc": has_icc,
                "target_space": str(target_space.value if isinstance(target_space, ColorSpace) else target_space),
                "dtype": str(normalized_bgr.dtype)
            }
            return normalized_bgr, metadata
        except Exception as e:
            # Fallback to OpenCV if PIL fails
            try:
                import cv2
                bgr = cv2.imread(path, cv2.IMREAD_COLOR)
                return bgr, {"path": path, "source_profile": "Untagged (sRGB Fallback)", "has_icc": False, "fallback": True}
            except Exception:
                return None, {"error": str(e)}

    @classmethod
    def convert(cls, img_rgb: np.ndarray, from_space: Union[str, ColorSpace], to_space: Union[str, ColorSpace]) -> np.ndarray:
        """
        Converts an image between color spaces in 32-bit floating point.
        Expects RGB channel ordering with values normalized to [0.0, 1.0].
        """
        from_space = ColorSpace(from_space)
        to_space = ColorSpace(to_space)

        if from_space == to_space:
            return img_rgb.copy().astype(np.float32)

        # 1. Step A: Convert from source space to Linear sRGB
        if from_space == ColorSpace.SRGB:
            lin_srgb = cls.srgb_to_linear(img_rgb)
        elif from_space == ColorSpace.LINEAR_SRGB:
            lin_srgb = img_rgb.astype(np.float32)
        elif from_space == ColorSpace.LINEAR_PROPHOTO:
            lin_srgb = np.matmul(img_rgb.astype(np.float32), M_PROPHOTO_TO_SRGB.T)
        elif from_space == ColorSpace.LINEAR_ACESCG:
            lin_srgb = np.matmul(img_rgb.astype(np.float32), M_ACESCG_TO_SRGB.T)
        elif from_space == ColorSpace.ADOBE_RGB:
            lin_adobe = np.power(np.maximum(img_rgb.astype(np.float32), 0.0), 2.19921875)
            m_adobe_to_srgb = np.array([
                [1.3982931, -0.3874381, -0.0108550],
                [-0.0429447, 1.0514467, -0.0085020],
                [-0.0032590, -0.0457635, 1.0490225]
            ], dtype=np.float32)
            lin_srgb = np.matmul(lin_adobe, m_adobe_to_srgb.T)
        elif from_space == ColorSpace.DISPLAY_P3:
            # Convert non-linear Display P3 to sRGB via ICC transform
            srgb_conv = cls.convert_icc(img_rgb, src_profile="Display_P3", target_space=ColorSpace.SRGB, is_bgr=False)
            lin_srgb = cls.srgb_to_linear(srgb_conv)
        else:
            raise ValueError(f"Unsupported source color space: {from_space}")

        # 2. Step B: Convert from Linear sRGB to target space
        if to_space == ColorSpace.SRGB:
            return cls.linear_to_srgb(lin_srgb)
        elif to_space == ColorSpace.LINEAR_SRGB:
            return lin_srgb
        elif to_space == ColorSpace.LINEAR_PROPHOTO:
            return np.matmul(lin_srgb, M_SRGB_TO_PROPHOTO.T).astype(np.float32)
        elif to_space == ColorSpace.LINEAR_ACESCG:
            return np.matmul(lin_srgb, M_SRGB_TO_ACESCG.T).astype(np.float32)
        elif to_space == ColorSpace.ADOBE_RGB:
            m_srgb_to_adobe = np.array([
                [0.715160, 0.284840, 0.000000],
                [0.000000, 1.000000, 0.000000],
                [0.000000, 0.041158, 0.958842]
            ], dtype=np.float32)
            lin_adobe = np.matmul(lin_srgb, m_srgb_to_adobe.T)
            return np.power(np.maximum(lin_adobe, 0.0), 1.0 / 2.19921875).astype(np.float32)
        elif to_space == ColorSpace.DISPLAY_P3:
            srgb_out = cls.linear_to_srgb(lin_srgb)
            return cls.convert_icc(srgb_out, src_profile="sRGB", target_space="Display_P3", is_bgr=False)
        else:
            raise ValueError(f"Unsupported destination color space: {to_space}")

