"""
Lightroom AI - Studio Edition 2.0
Production Preset Bundle Manager (preset_bundle.py)

Manages standard Lightroom AI Studio preset bundles:
- preset.json
- preset.cube (64^3 float32 LUT)
- preset_hald.png (Level 8 Hald PNG)
- source.xmp
- calibration/calibration_metadata.json
"""

import os
import json
import cv2
import numpy as np
from typing import Optional, Dict, Any, List

from lut_engine import Lut3D
from xmp_parser import XmpParser
from color_space import ColorSpace


class PresetBundle:
    """Encapsulates a complete Lightroom AI preset bundle."""

    def __init__(
        self,
        preset_id: str,
        name: str,
        lut: Optional[Lut3D] = None,
        spatial_params: Optional[Dict[str, Any]] = None,
        default_sliders: Optional[Dict[str, Any]] = None,
        working_space: str = "Adobe_RGB_1998",
        input_color_space: str = "Adobe_RGB_1998",
        output_color_space: str = "Adobe_RGB_1998",
        source_input_profile: str = "dynamic_from_source",
        export_color_space: str = "sRGB",
        source_xmp_path: Optional[str] = None,
        calibration_meta: Optional[Dict[str, Any]] = None,
        unsupported_parameters: Optional[List[str]] = None,
        bundle_dir: Optional[str] = None
    ):
        self.preset_id = preset_id
        self.name = name
        self.lut = lut or Lut3D.create_identity(size=64, title=name)
        self.spatial_params = spatial_params or {}
        self.default_sliders = default_sliders or {}
        self.working_space = working_space
        self.input_color_space = input_color_space
        self.output_color_space = output_color_space
        self.source_input_profile = source_input_profile
        self.export_color_space = export_color_space
        self.source_xmp_path = source_xmp_path
        self.calibration_meta = calibration_meta
        self.unsupported_parameters = unsupported_parameters or []
        self.bundle_dir = bundle_dir

    @property
    def is_calibrated(self) -> bool:
        return self.calibration_meta is not None

    def get_runtime_spatial_params(self) -> Dict[str, Any]:
        """
        Returns only the spatial parameters that must be applied at runtime.
        Excludes spatial parameters that are already baked into the calibrated 3D LUT (e.g. baked vignette).
        """
        runtime_params = {}
        for key, val in self.spatial_params.items():
            if isinstance(val, dict):
                # If explicitly marked as baked into LUT, do not apply at runtime
                if val.get("baked_into_lut") is True or val.get("status") == "baked_into_lut":
                    continue
                # If status is unsupported, skip
                if val.get("status") == "unsupported":
                    continue
                runtime_params[key] = val
            elif isinstance(val, (int, float)) and val != 0:
                runtime_params[key] = val
        return runtime_params

    def get_summary(self) -> Dict[str, Any]:
        """Returns structured diagnostic summary for UI and API."""
        runtime_spatial = self.get_runtime_spatial_params()
        return {
            "preset_id": self.preset_id,
            "name": self.name,
            "lut_loaded": self.lut is not None,
            "lut_size": self.lut.size if self.lut else 0,
            "working_space": self.working_space,
            "input_color_space": self.input_color_space,
            "output_color_space": self.output_color_space,
            "source_input_profile": self.source_input_profile,
            "export_color_space": self.export_color_space,
            "is_calibrated": self.is_calibrated,
            "calibration_status": "100% Calibrated Profile" if self.is_calibrated else "Parametric / Standard LUT",
            "spatial_active": len(runtime_spatial) > 0,
            "spatial_parameters": self.spatial_params,
            "runtime_spatial_parameters": runtime_spatial,
            "default_sliders": self.default_sliders,
            "unsupported_parameters": self.unsupported_parameters,
            "has_warnings": len(self.unsupported_parameters) > 0,
            "warning_text": f"{len(self.unsupported_parameters)} proprietary parameters detected (Reference calibration recommended)" if self.unsupported_parameters else "All parameters 100% supported"
        }

    @classmethod
    def load_from_directory(cls, dir_path: str) -> Optional["PresetBundle"]:
        """Loads a preset bundle from a directory."""
        if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            return None

        json_path = os.path.join(dir_path, "preset.json")
        lut_obj = None
        spatial = {}
        sliders = {}
        working_space = "Adobe_RGB_1998"
        input_color_space = "Adobe_RGB_1998"
        output_color_space = "Adobe_RGB_1998"
        source_input_profile = "dynamic_from_source"
        export_color_space = "sRGB"
        unsupported = []
        name = os.path.basename(dir_path)
        preset_id = name.lower().replace(" ", "_")
        calib_meta = None

        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                preset_id = cfg.get("preset_id", preset_id)
                name = cfg.get("preset_name", name)
                spatial = cfg.get("spatial", {})
                sliders = cfg.get("default_sliders", {})
                working_space = cfg.get("working_space", "Adobe_RGB_1998")
                input_color_space = cfg.get("input_color_space", "Adobe_RGB_1998")
                output_color_space = cfg.get("output_color_space", "Adobe_RGB_1998")
                source_input_profile = cfg.get("source_input_profile", "dynamic_from_source")
                export_color_space = cfg.get("export_color_space", "sRGB")
                unsupported = cfg.get("unsupported_parameters", [])
            except Exception as e:
                print(f"   > [PRESET BUNDLE] Error reading {json_path}: {e}")

        # Check for .cube file
        cube_files = [f for f in os.listdir(dir_path) if f.lower().endswith(".cube")]
        if cube_files:
            cube_path = os.path.join(dir_path, cube_files[0])
            try:
                lut_obj = Lut3D.from_cube_file(cube_path)
            except Exception as e:
                print(f"   > [PRESET BUNDLE] Error loading cube {cube_path}: {e}")

        # Check for Hald PNG if no cube
        if lut_obj is None:
            hald_files = [f for f in os.listdir(dir_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tif', '.tiff')) and 'hald' in f.lower()]
            if not hald_files:
                hald_files = [f for f in os.listdir(dir_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tif', '.tiff'))]
            if hald_files:
                hald_path = os.path.join(dir_path, hald_files[0])
                try:
                    lut_obj = Lut3D.from_hald_file(hald_path, level=8)
                except Exception as e:
                    print(f"   > [PRESET BUNDLE] Error loading Hald {hald_path}: {e}")

        # Check calibration metadata
        calib_path = os.path.join(dir_path, "calibration", "calibration_metadata.json")
        if not os.path.exists(calib_path):
            calib_path = os.path.join(dir_path, "calibration_metadata.json")
        if os.path.exists(calib_path):
            try:
                with open(calib_path, "r", encoding="utf-8") as f:
                    calib_meta = json.load(f)
            except Exception:
                pass

        # Check XMP if sliders/spatial not populated
        xmp_files = [f for f in os.listdir(dir_path) if f.lower().endswith(('.xmp', '.dng'))]
        source_xmp = os.path.join(dir_path, xmp_files[0]) if xmp_files else None
        if source_xmp and (not spatial or not sliders):
            try:
                parsed = XmpParser.parse_file(source_xmp)
                if not spatial:
                    spatial = parsed.get("spatial", {})
                if not sliders:
                    sliders = parsed.get("default_sliders", {})
                if not unsupported:
                    unsupported = parsed.get("unsupported_parameters", [])
            except Exception:
                pass

        return cls(
            preset_id=preset_id,
            name=name,
            lut=lut_obj,
            spatial_params=spatial,
            default_sliders=sliders,
            working_space=working_space,
            input_color_space=input_color_space,
            output_color_space=output_color_space,
            source_input_profile=source_input_profile,
            export_color_space=export_color_space,
            source_xmp_path=source_xmp,
            calibration_meta=calib_meta,
            unsupported_parameters=unsupported,
            bundle_dir=dir_path
        )

    @classmethod
    def load_from_file_or_folder(cls, target_path: str) -> "PresetBundle":
        """
        Universal loader that accepts:
        1. A preset bundle directory
        2. A single .cube file
        3. A single Hald PNG/TIFF file
        4. A single .xmp or .dng file
        """
        if not os.path.exists(target_path):
            import sys
            if getattr(sys, 'frozen', False):
                if hasattr(sys, '_MEIPASS'):
                    candidate = os.path.join(sys._MEIPASS, target_path)
                    if os.path.exists(candidate):
                        target_path = candidate
                if not os.path.exists(target_path):
                    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
                    candidate2 = os.path.join(exe_dir, target_path)
                    if os.path.exists(candidate2):
                        target_path = candidate2
            if not os.path.exists(target_path):
                # Fallback default
                return cls(preset_id="default_profile", name="Default Profile")

        if os.path.isdir(target_path):
            bundle = cls.load_from_directory(target_path)
            if bundle:
                return bundle

            # If directory contains loose files
            files = os.listdir(target_path)
            # Check for bundle subdirs
            subdirs = [os.path.join(target_path, d) for d in files if os.path.isdir(os.path.join(target_path, d))]
            for sd in subdirs:
                b = cls.load_from_directory(sd)
                if b and b.lut:
                    return b

            # Check for loose .cube
            cubes = [f for f in files if f.lower().endswith(".cube")]
            if cubes:
                return cls.load_from_single_file(os.path.join(target_path, cubes[0]))

            # Check for loose Hald images
            halds = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tif', '.tiff'))]
            if halds:
                return cls.load_from_single_file(os.path.join(target_path, halds[0]))

            # Check for loose XMP
            xmps = [f for f in files if f.lower().endswith(('.xmp', '.dng'))]
            if xmps:
                return cls.load_from_single_file(os.path.join(target_path, xmps[0]))

            return cls(preset_id="empty_dir", name="Default Profile")

        return cls.load_from_single_file(target_path)

    @classmethod
    def load_from_single_file(cls, filepath: str) -> "PresetBundle":
        """Loads a single LUT or XMP file into a PresetBundle instance."""
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        ext = os.path.splitext(filepath)[1].lower()

        if ext == ".cube":
            lut = Lut3D.from_cube_file(filepath)
            return cls(preset_id=base_name.lower(), name=base_name, lut=lut)

        elif ext in ('.png', '.jpg', '.jpeg', '.tif', '.tiff'):
            lut = Lut3D.from_hald_file(filepath, level=8)
            return cls(preset_id=base_name.lower(), name=base_name, lut=lut)

        elif ext in ('.xmp', '.dng'):
            parsed = XmpParser.parse_file(filepath)
            return cls(
                preset_id=base_name.lower(),
                name=base_name,
                lut=Lut3D.create_identity(size=64, title=base_name),
                spatial_params=parsed.get("spatial", {}),
                default_sliders=parsed.get("default_sliders", {}),
                source_xmp_path=filepath,
                unsupported_parameters=parsed.get("unsupported_parameters", [])
            )

        return cls(preset_id=base_name.lower(), name=base_name)
