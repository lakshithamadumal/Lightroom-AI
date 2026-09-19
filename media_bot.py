import os
import sys
import cv2
from dotenv import load_dotenv

from preset_manager import PresetManager
from smart_cropper import SmartCropper
from auto_adjuster import AutoAdjuster

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Load configuration from .env
load_dotenv()

ORCA_API_KEY = os.getenv("ORCA_API_KEY", "")
ORCA_API_URL = os.getenv("ORCA_API_URL", "https://api.orcarouter.ai/v1/chat/completions")
ORCA_MODEL = os.getenv("ORCA_MODEL", "fusion-flash")

INPUT_FOLDER = os.getenv("INPUT_FOLDER", "D:/Media_Incoming")
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "D:/Media_Output")
PRESET_FOLDER = os.getenv("PRESET_FOLDER", "D:/Media_Presets")

ENABLE_AI_SMART_CROP = os.getenv("ENABLE_AI_SMART_CROP", "true").lower() == "true"
ENABLE_AUTO_BALANCING = os.getenv("ENABLE_AUTO_BALANCING", "true").lower() == "true"
TARGET_MAX_WIDTH = int(os.getenv("TARGET_MAX_WIDTH", "0"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "100"))


def process_images():
    # Ensure directories exist
    os.makedirs(INPUT_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    os.makedirs(PRESET_FOLDER, exist_ok=True)

    print("================================================================================")
    print(" [PIPELINE] Media Automation Pipeline - Ministry Edition")
    print(f" [AI MODEL]  {ORCA_MODEL}")
    print(f" [INPUT]     {INPUT_FOLDER}")
    print(f" [PRESET]    {PRESET_FOLDER}")
    print(f" [OUTPUT]    {OUTPUT_FOLDER}")
    print("================================================================================")

    # Initialize components
    preset_mgr = PresetManager(preset_folder=PRESET_FOLDER)
    cropper = SmartCropper(api_key=ORCA_API_KEY, api_url=ORCA_API_URL, model=ORCA_MODEL)
    adjuster = AutoAdjuster(api_key=ORCA_API_KEY, api_url=ORCA_API_URL, model=ORCA_MODEL)

    print(f"\n[PRESET LOADED] {preset_mgr.get_summary_text()}")

    valid_extensions = ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG', '.dng', '.DNG')
    files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith(valid_extensions)]

    if not files:
        print(f"\n[INFO] No photos found in '{INPUT_FOLDER}'.")
        print(f"👉 Please place raw/event photos in: {INPUT_FOLDER}")
        print(f"👉 Place your Lightroom DNG preset in: {PRESET_FOLDER}")
        return

    print(f"\n[INFO] Found {len(files)} photos to process.\n")
    processed_count = 0

    for idx, filename in enumerate(files, 1):
        img_path = os.path.join(INPUT_FOLDER, filename)
        img = cv2.imread(img_path)

        if img is None:
            print(f"[{idx}/{len(files)}] [ERROR] Could not read image: {filename}")
            continue

        h, w = img.shape[:2]

        print("--------------------------------------------------------------------------------")
        print(f"📸 [{idx}/{len(files)}] Processing: {filename} | Original Dimension: {w}x{h}")
        print("--------------------------------------------------------------------------------")

        # STEP 1: Apply Master Preset
        print(" [STEP 1: PRESET COLOR GRADING]")
        preset_applied = preset_mgr.apply_preset(img)
        print(f"   > Applied Master Profile: {preset_mgr.preset_name}")
        print(f"   > Tone S-Curve, 8-Color HSL Matrix, Vibrance, Clarity & Dehaze Applied.")

        # STEP 2: Per-Photo Dynamic Auto-Adjustment
        print(" [STEP 2: PER-PHOTO DYNAMIC AUTO-ADJUSTMENT]")
        if ENABLE_AUTO_BALANCING:
            adjusted, telemetry = adjuster.fine_tune(preset_applied)
            print(f"   > Lighting Analyzed: Median={telemetry['initial_median']} -> Auto-Exposure Shift: {telemetry['exp_shift_ev']:+.2f} EV ({telemetry.get('engine', 'Auto')})")
            print(f"   > Shadow Lift: +{telemetry['shadow_lift_pct']}% | Highlight Protection: -{telemetry['highlight_comp_pct']}%")
            print(f"   > Style Preservation: {telemetry.get('style_preservation', '100% LUT Intact')}")
        else:
            adjusted = preset_applied
            print("   > Skipped per-photo balancing (disabled in .env).")

        # STEP 3 & 4: Best View / AI Smart Crop
        print(" [STEP 3: COMPOSITION & BEST VIEW SELECTION]")
        cropped, crop_telemetry = cropper.crop_best_landscape(adjusted, enable_ai=ENABLE_AI_SMART_CROP)
        print(f"   > Framing Method: {crop_telemetry.get('method', 'Smart Crop')}")
        print(f"   > Trimmed Distractions: {crop_telemetry.get('trim_x_pct', 0)}% Width, {crop_telemetry.get('trim_y_pct', 0)}% Height")
        if 'notes' in crop_telemetry:
            print(f"   > Framing Notes: {crop_telemetry['notes']}")

        # STEP 5: Resize to High Resolution Master & Save
        print(" [STEP 4: FINAL MASTER EXPORT]")
        ch, cw = cropped.shape[:2]
        if TARGET_MAX_WIDTH > 0 and cw > TARGET_MAX_WIDTH:
            new_w = TARGET_MAX_WIDTH
            new_h = int(ch * (TARGET_MAX_WIDTH / cw))
            final_output = cv2.resize(cropped, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        else:
            final_output = cropped

        base_name, _ = os.path.splitext(filename)
        output_filename = f"{base_name}.jpg"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        cv2.imwrite(output_path, final_output, [
            int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY,
            int(cv2.IMWRITE_JPEG_OPTIMIZE), 1
        ])

        processed_count += 1
        print(f"   > [SAVED] {output_path} ({final_output.shape[1]}x{final_output.shape[0]} px)")

    print("\n================================================================================")
    print(f" [SUCCESS] Finished processing {processed_count}/{len(files)} photos successfully!")
    print(f" [OUTPUT LOCATION] {OUTPUT_FOLDER}")
    print("================================================================================")


if __name__ == "__main__":
    process_images()
