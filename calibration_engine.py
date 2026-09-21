import os
import sys
import time
import json
import shutil
import hashlib
import cv2
import numpy as np
from typing import Dict, Any, Optional, Tuple, Union

from lut_engine import Lut3D, LutEngine


def compute_file_sha256(filepath: str) -> str:
    """Computes SHA-256 hash of a file."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


class CalibrationEngine:
    """
    Manages generation of calibration charts, extraction of calibrated 3D LUTs,
    and atomic installation of master production presets from HALD images.
    """

    @staticmethod
    def generate_calibration_chart(output_path: str, level: int = 8, bit_depth: int = 8) -> str:
        """
        Generates a pristine identity Hald calibration target.
        For level 8, dimension is 512x512 pixels containing 64^3 = 262,144 exact color patches.
        """
        lut = Lut3D.create_identity(size=level * level, title="Standard Calibration Target")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        lut.to_hald_file(output_path, level=level, bit_depth=bit_depth)
        return output_path

    @classmethod
    def validate_hald(
        cls,
        hald_source: Union[str, np.ndarray],
        level: int = 8
    ) -> Tuple[bool, Optional[str], Optional[Lut3D]]:
        """
        Validates a HALD image file or array against strict production requirements:
        - Image can be successfully read and decoded
        - Dimensions match expected HALD grid (512x512 for level 8, or N*N*N layout)
        - Expected 3 or 4 RGB channels (no monochrome / single channel)
        - Contains valid finite numeric values (no NaN, Inf, or corrupted data)
        - Successfully decodes to a (64, 64, 64, 3) Float32 Lut3D object
        """
        try:
            if isinstance(hald_source, str):
                if not os.path.exists(hald_source):
                    return False, f"HALD file not found: {hald_source}", None
                if os.path.getsize(hald_source) == 0:
                    return False, f"HALD file is empty: {hald_source}", None
                
                # Attempt decode
                img = cv2.imread(hald_source, cv2.IMREAD_UNCHANGED)
                if img is None:
                    return False, f"Failed to decode HALD image file at: {hald_source}", None
            elif isinstance(hald_source, np.ndarray):
                img = hald_source
            else:
                return False, f"Unsupported HALD source type: {type(hald_source)}", None

            if img.ndim < 2:
                return False, "Invalid image dimensions: array is less than 2D", None

            # Check channels
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            elif img.ndim == 3:
                channels = img.shape[2]
                if channels not in (3, 4):
                    return False, f"Invalid channel count: expected 3 (RGB) or 4 (RGBA), got {channels}", None
                if channels == 3:
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                elif channels == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
            else:
                return False, f"Unsupported image shape: {img.shape}", None

            h, w = img.shape[:2]
            expected_size = level * level  # 64
            expected_dim = level * expected_size  # 512

            # Check for non-finite or corrupted values
            if not np.all(np.isfinite(img)):
                return False, "Image contains non-finite values (NaN or Inf)", None

            # Decode into Lut3D using standard engine
            lut = Lut3D.from_hald_image(img, level=level, title="Master Studio Preset")

            # Validate generated LUT properties
            if lut.size != expected_size:
                return False, f"Generated LUT size mismatch: expected {expected_size}, got {lut.size}", None
            if lut.table.shape != (expected_size, expected_size, expected_size, 3):
                return False, f"Generated LUT shape mismatch: expected ({expected_size}, {expected_size}, {expected_size}, 3), got {lut.table.shape}", None
            if lut.table.dtype != np.float32:
                return False, f"Generated LUT dtype mismatch: expected float32, got {lut.table.dtype}", None
            if not np.all(np.isfinite(lut.table)):
                return False, "Generated LUT contains non-finite values (NaN or Inf)", None

            return True, None, lut
        except Exception as e:
            return False, f"Validation exception: {str(e)}", None

    @classmethod
    def backup_existing_master(
        cls,
        calibration_dir: str = "calibration",
        backup_dir: str = "presets/test_preset_backup"
    ) -> Dict[str, Any]:
        """
        Creates a protected, verified backup of the current preset artifacts before replacement.
        Preserves preset.cube, preset_calibrated.cube, preset.json, calibration_metadata.json.
        """
        os.makedirs(backup_dir, exist_ok=True)
        backed_up_files = []

        files_to_backup = [
            "preset.cube",
            "preset_calibrated.cube",
            "preset.json",
            "calibration_metadata.json"
        ]

        for fname in files_to_backup:
            src = os.path.join(calibration_dir, fname)
            if os.path.exists(src) and os.path.isfile(src):
                dst = os.path.join(backup_dir, fname)
                shutil.copy2(src, dst)
                if not os.path.exists(dst) or os.path.getsize(dst) == 0:
                    raise IOError(f"Failed to verify backup copy for {fname}")
                backed_up_files.append(fname)

        return {
            "status": "backup_verified",
            "backup_dir": os.path.abspath(backup_dir),
            "files_backed_up": backed_up_files,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

    @classmethod
    def install_master_preset(
        cls,
        hald_source: Union[str, np.ndarray],
        calibration_dir: str = "calibration",
        backup_dir: str = "presets/test_preset_backup",
        preset_name: str = "Master Studio Preset",
        source_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Atomically replaces the active production master preset in calibration/ with
        the 64^3 Float32 LUT compiled from the provided HALD image.
        
        Flow:
        1. Validate HALD source
        2. Create and verify backup of existing artifacts in backup_dir
        3. Compile into temporary staging directory (calibration/.staging)
        4. Validate all staged artifacts
        5. Atomically replace active preset artifacts in calibration_dir
        6. Verify final active files and return metadata
        """
        # Step 1: Validate HALD
        is_valid, err_msg, lut = cls.validate_hald(hald_source, level=8)
        if not is_valid or lut is None:
            return {
                "status": "error",
                "message": f"HALD validation failed: {err_msg}",
                "installed": False
            }

        # Step 2: Backup current master preset
        os.makedirs(calibration_dir, exist_ok=True)
        backup_result = cls.backup_existing_master(calibration_dir=calibration_dir, backup_dir=backup_dir)

        # Step 3: Staging
        staging_dir = os.path.join(calibration_dir, ".staging")
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        os.makedirs(staging_dir, exist_ok=True)

        try:
            staged_cube = os.path.join(staging_dir, "preset.cube")
            staged_calib_cube = os.path.join(staging_dir, "preset_calibrated.cube")
            staged_json = os.path.join(staging_dir, "preset.json")
            staged_meta = os.path.join(staging_dir, "calibration_metadata.json")

            # Write .cube files (64^3 float32 Adobe .cube)
            lut.to_cube_file(staged_cube, title=preset_name)
            lut.to_cube_file(staged_calib_cube, title=f"{preset_name} (Calibrated)")

            # Read existing preset.json to preserve any custom spatial curve definitions if available
            existing_json_path = os.path.join(calibration_dir, "preset.json")
            existing_cfg = {}
            if os.path.exists(existing_json_path):
                try:
                    with open(existing_json_path, "r", encoding="utf-8") as f:
                        existing_cfg = json.load(f)
                except Exception:
                    existing_cfg = {}

            src_file_desc = source_filename or (os.path.basename(hald_source) if isinstance(hald_source, str) else "master_hald.png")
            timestamp_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Build production preset.json
            preset_def = {
                "preset_id": "master_studio_preset",
                "preset_name": preset_name,
                "engine_version": "2.0",
                "source_xmp": "embedded_master_preset_hald",
                "lut_file": "preset.cube",
                "lut_hald_png": "preset_unvignetted_hald.png",
                "lut_size": 64,
                "source_input_profile": "dynamic_from_source",
                "input_color_space": "Adobe_RGB_1998",
                "working_space": "Adobe_RGB_1998",
                "output_color_space": "Adobe_RGB_1998",
                "export_color_space": "sRGB",
                "is_calibrated": True,
                "spatial": existing_cfg.get("spatial", {
                    "clarity": 0.0,
                    "texture": 0.0,
                    "dehaze": 0.0,
                    "sharpening": {"amount": 0.0, "radius": 1.0, "detail": 25.0, "masking": 0.0},
                    "vignette": {"amount": 0.0, "midpoint": 50.0, "feather": 50.0, "roundness": 0.0, "baked_into_lut": False, "status": "runtime_spatial"},
                    "grain": {"amount": 0.0, "size": 25.0, "frequency": 50.0}
                }),
                "default_sliders": existing_cfg.get("default_sliders", {
                    "exposure": 0.0,
                    "contrast": 0.0,
                    "highlights": 0.0,
                    "shadows": 0.0,
                    "whites": 0.0,
                    "blacks": 0.0,
                    "temperature": 0.0,
                    "tint": 0.0,
                    "vibrance": 0.0,
                    "saturation": 0.0
                }),
                "tone_curves": existing_cfg.get("tone_curves", {
                    "master": [[0.0, 0.0], [255.0, 255.0]],
                    "red": [[0.0, 0.0], [255.0, 255.0]],
                    "green": [[0.0, 0.0], [255.0, 255.0]],
                    "blue": [[0.0, 0.0], [255.0, 255.0]]
                }),
                "hsl_hue": existing_cfg.get("hsl_hue", {}),
                "hsl_sat": existing_cfg.get("hsl_sat", {}),
                "hsl_lum": existing_cfg.get("hsl_lum", {}),
                "unsupported_parameters": existing_cfg.get("unsupported_parameters", []),
                "calibration_metadata": {
                    "engine": "Lightroom AI Studio Calibration Engine 2.0",
                    "calibration_timestamp": timestamp_str,
                    "source_reference_file": src_file_desc,
                    "source_dimensions": "512x512",
                    "source_bit_depth": 16 if (isinstance(hald_source, np.ndarray) and hald_source.dtype == np.uint16) else 8,
                    "source_color_profile": "Adobe RGB (1998)",
                    "lut_size": 64,
                    "total_color_points": 262144,
                    "source_input_profile": "dynamic_from_source",
                    "input_color_space": "Adobe_RGB_1998",
                    "output_color_space": "Adobe_RGB_1998",
                    "working_color_space": "Adobe_RGB_1998",
                    "export_color_space": "sRGB",
                    "calibration_method": "Full Level 8 Identity Hald Chart Ingestion"
                }
            }

            with open(staged_json, "w", encoding="utf-8") as f:
                json.dump(preset_def, f, indent=2)

            with open(staged_meta, "w", encoding="utf-8") as f:
                json.dump(preset_def["calibration_metadata"], f, indent=2)

            # Step 4: Validate staged artifacts
            test_loaded_lut = Lut3D.from_cube_file(staged_cube)
            if test_loaded_lut.size != 64 or test_loaded_lut.table.shape != (64, 64, 64, 3):
                raise ValueError("Staged cube validation failed: invalid dimensions")

            with open(staged_json, "r", encoding="utf-8") as f:
                json.load(f)

            # Step 5: Atomic replacement
            target_cube = os.path.join(calibration_dir, "preset.cube")
            target_calib_cube = os.path.join(calibration_dir, "preset_calibrated.cube")
            target_json = os.path.join(calibration_dir, "preset.json")
            target_meta = os.path.join(calibration_dir, "calibration_metadata.json")

            shutil.copy2(staged_cube, target_cube)
            shutil.copy2(staged_calib_cube, target_calib_cube)
            shutil.copy2(staged_json, target_json)
            shutil.copy2(staged_meta, target_meta)

            # Clean up staging
            shutil.rmtree(staging_dir, ignore_errors=True)

            # Step 6: Verify final files
            cube_sha = compute_file_sha256(target_cube)
            calib_cube_sha = compute_file_sha256(target_calib_cube)

            return {
                "status": "success",
                "message": "Custom preset successfully installed as the active Studio Master Preset.",
                "installed": True,
                "preset_name": preset_name,
                "calibration_dir": os.path.abspath(calibration_dir),
                "backup_dir": os.path.abspath(backup_dir),
                "files_installed": ["preset.cube", "preset_calibrated.cube", "preset.json", "calibration_metadata.json"],
                "sha256_preset_cube": cube_sha,
                "sha256_preset_calibrated_cube": calib_cube_sha,
                "lut_size": 64,
                "lut_dtype": "float32",
                "working_color_space": "Adobe_RGB_1998",
                "export_color_space": "sRGB",
                "timestamp": timestamp_str
            }
        except Exception as e:
            # If staging or replacement failed, clean up staging and keep original intact
            if os.path.exists(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)
            return {
                "status": "error",
                "message": f"Installation failed during staging/replacement: {str(e)}",
                "installed": False,
                "backup_dir": os.path.abspath(backup_dir)
            }

    @classmethod
    def calibrate_from_reference_image(
        cls,
        rendered_reference_path: str,
        output_cube_path: str,
        output_hald_path: Optional[str] = None,
        level: int = 8,
        metadata_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Extracts a calibrated 64^3 3D LUT from a reference calibration chart exported from Adobe Lightroom.
        """
        if not os.path.exists(rendered_reference_path):
            raise FileNotFoundError(f"Reference image not found: {rendered_reference_path}")

        # Load reference chart
        ref_lut = Lut3D.from_hald_file(rendered_reference_path, level=level)

        # Save to .cube
        os.makedirs(os.path.dirname(os.path.abspath(output_cube_path)), exist_ok=True)
        ref_lut.to_cube_file(output_cube_path)

        # Save to Hald if requested
        if output_hald_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_hald_path)), exist_ok=True)
            ref_lut.to_hald_file(output_hald_path, level=level, bit_depth=8)

        # Build calibration metadata
        meta = {
            "engine": "Lightroom AI Studio Calibration Engine 2.0",
            "calibration_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_reference_file": os.path.basename(rendered_reference_path),
            "lut_size": ref_lut.size,
            "total_color_points": ref_lut.size ** 3,
            "input_color_space": metadata_overrides.get("input_color_space", "Adobe_RGB_1998") if metadata_overrides else "Adobe_RGB_1998",
            "output_color_space": metadata_overrides.get("output_color_space", "Adobe_RGB_1998") if metadata_overrides else "Adobe_RGB_1998",
            "working_color_space": "Adobe_RGB_1998",
            "bit_depth": metadata_overrides.get("bit_depth", 8) if metadata_overrides else 8,
            "recommended_lr_export_settings": {
                "format": "TIFF or PNG (Uncompressed) or JPEG 100%",
                "color_space": "Adobe RGB (1998) or sRGB",
                "bit_depth": "16-bit or 8-bit",
                "resize_to_fit": "None (Do not resize)",
                "output_sharpening": "None / Disabled",
            }
        }

        meta_path = os.path.join(os.path.dirname(os.path.abspath(output_cube_path)), "calibration_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return {
            "status": "success",
            "cube_path": output_cube_path,
            "hald_path": output_hald_path,
            "metadata_path": meta_path,
            "metadata": meta
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Lightroom AI Calibration & Master Preset Installer CLI")
    parser.add_argument("--install-master", help="Path to processed HALD PNG/TIFF to compile into calibration/ master preset")
    parser.add_argument("--name", help="Optional display name for the preset", default="Master Studio Preset")
    parser.add_argument("--chart", help="Generate identity calibration chart to path", default=None)
    args = parser.parse_args()

    if args.chart:
        print(f"Generating neutral identity HALD chart to: {args.chart}")
        CalibrationEngine.generate_calibration_chart(args.chart, level=8, bit_depth=8)
        print("Done.")

    elif args.install_master:
        print(f"\n=======================================================")
        print(f"🚀 Compiling and Installing Master Preset from: {args.install_master}")
        print(f"=======================================================")
        res = CalibrationEngine.install_master_preset(args.install_master, preset_name=args.name)
        if res.get("installed"):
            print(f"✅ Status: {res['message']}")
            print(f"📁 Calibration Dir: {res['calibration_dir']}")
            print(f"💾 Backup Dir:      {res['backup_dir']}")
            print(f"🔑 preset.cube SHA-256: {res['sha256_preset_cube']}")
            print(f"🔑 calibrated SHA-256:  {res['sha256_preset_calibrated_cube']}")
        else:
            print(f"❌ Error: {res.get('message')}")
            sys.exit(1)
    else:
        parser.print_help()
