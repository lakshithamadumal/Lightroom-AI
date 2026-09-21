"""
Lightroom AI - Studio Edition 2.0
Preset Converter CLI: convert_lr_preset.py

Usage:
    python convert_lr_preset.py path/to/preset.xmp [output_dir]
"""

import os
import sys
import json
import argparse

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from xmp_parser import XmpParser


def convert_preset(xmp_path: str, output_dir: str = None) -> str:
    if not os.path.exists(xmp_path):
        print(f"Error: File not found: {xmp_path}")
        sys.exit(1)

    parsed = XmpParser.parse_file(xmp_path)
    base_name = os.path.splitext(os.path.basename(xmp_path))[0]
    out_dir = output_dir or os.path.join(os.path.dirname(xmp_path), base_name)
    os.makedirs(out_dir, exist_ok=True)

    json_path = os.path.join(out_dir, "preset.json")
    preset_def = {
        "preset_id": base_name.lower().replace(" ", "_"),
        "preset_name": base_name,
        "engine_version": "2.0",
        "source_xmp": os.path.basename(xmp_path),
        "lut_file": f"{base_name}.cube",
        "lut_hald_png": f"{base_name}_hald.png",
        "lut_size": 64,
        "working_space": "Linear_ProPhoto",
        "spatial": parsed["spatial"],
        "default_sliders": parsed["default_sliders"],
        "tone_curves": parsed["tone_curves"],
        "hsl_hue": parsed["hsl_hue"],
        "hsl_sat": parsed["hsl_sat"],
        "hsl_lum": parsed["hsl_lum"],
        "calibration_recommended": parsed["calibration_recommended"],
        "calibration_reasons": parsed["calibration_reasons"],
        "unsupported_parameters": parsed["unsupported_parameters"],
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(preset_def, f, indent=2)

    print(f"\n✅ Converted Preset: {base_name}")
    print(f"📁 Output bundle definition: {json_path}")
    print(f"⚙️  Supported crs parameters: {len(parsed['supported_parameters'])}")
    print(f"⚠️  Unsupported / proprietary parameters: {len(parsed['unsupported_parameters'])}")
    if parsed["calibration_recommended"]:
        print(f"🔬 Calibration Status: Adobe Lightroom Reference Chart Calibration Recommended.")
        for r in parsed["calibration_reasons"]:
            print(f"   - {r}")
    else:
        print(f"✨ Calibration Status: Fully direct-reproducible parameters.")

    return json_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert Lightroom XMP preset to Lightroom AI Studio 2.0 preset bundle.")
    parser.add_argument("xmp_path", help="Path to .xmp or .dng preset file")
    parser.add_argument("-o", "--output", help="Optional output directory", default=None)
    args = parser.parse_args()

    convert_preset(args.xmp_path, args.output)
