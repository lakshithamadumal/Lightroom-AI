import os
import sys
import json
import asyncio
import base64
import urllib.parse
import cv2
import numpy as np
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv, set_key

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from preset_manager import PresetManager
from smart_cropper import SmartCropper
from auto_adjuster import AutoAdjuster

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

app = FastAPI(title="Lightroom AI - Studio Edition", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ENV_FILE_PATH = os.path.abspath(".env")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


def get_config():
    load_dotenv(override=True)
    return {
        "ORCA_API_KEY": os.getenv("ORCA_API_KEY", ""),
        "ORCA_API_URL": os.getenv("ORCA_API_URL", "https://api.orcarouter.ai/v1/chat/completions"),
        "ORCA_MODEL": os.getenv("ORCA_MODEL", "fusion-flash"),
        "INPUT_FOLDER": os.getenv("INPUT_FOLDER", "C:/Media_Incoming"),
        "PRESET_FOLDER": os.getenv("PRESET_FOLDER", "C:/Media_Presets"),
        "OUTPUT_FOLDER": os.getenv("OUTPUT_FOLDER", "C:/Media_Output"),
        "ENABLE_AI_SMART_CROP": os.getenv("ENABLE_AI_SMART_CROP", "true").lower() == "true",
        "ENABLE_AUTO_BALANCING": os.getenv("ENABLE_AUTO_BALANCING", "true").lower() == "true",
        "TARGET_MAX_WIDTH": int(os.getenv("TARGET_MAX_WIDTH", "0")),  # 0 = Full original resolution (no downscaling)
        "JPEG_QUALITY": int(os.getenv("JPEG_QUALITY", "100")),        # 100 = Maximum uncompressed studio quality
    }


class ConfigUpdate(BaseModel):
    ORCA_API_KEY: Optional[str] = None
    ORCA_API_URL: Optional[str] = None
    ORCA_MODEL: Optional[str] = None
    INPUT_FOLDER: Optional[str] = None
    PRESET_FOLDER: Optional[str] = None
    OUTPUT_FOLDER: Optional[str] = None
    ENABLE_AI_SMART_CROP: Optional[bool] = None
    ENABLE_AUTO_BALANCING: Optional[bool] = None
    TARGET_MAX_WIDTH: Optional[int] = None
    JPEG_QUALITY: Optional[int] = None


class AdjustRequest(BaseModel):
    filename: str
    exposure: float = 0.0      # EV offset (-2.0 to +2.0)
    contrast: float = 0.0      # Offset (-50 to +50)
    shadows: float = 0.0       # Offset (-50 to +50)
    highlights: float = 0.0    # Offset (-50 to +50)
    temperature: float = 0.0   # Kelvin/Warmth offset (-50 to +50)
    tint: float = 0.0          # Tint offset (-50 to +50)
    vibrance: float = 0.0      # Vibrance offset (-50 to +50)
    clarity: float = 0.0       # Clarity offset (0 to 50)
    crop_top: float = 0.0      # Normalized top crop (0.0 to 0.4)
    crop_bottom: float = 0.0   # Normalized bottom crop (0.0 to 0.4)
    crop_left: float = 0.0     # Normalized left crop (0.0 to 0.4)
    crop_right: float = 0.0    # Normalized right crop (0.0 to 0.4)


def _open_native_dialog(dialog_type: str, initial_dir: str):
    import tkinter as tk
    from tkinter import filedialog
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if dialog_type == "file":
            path = filedialog.askopenfilename(
                initialdir=initial_dir if os.path.exists(initial_dir) else "C:/",
                title="Select 3D LUT or Preset File",
                filetypes=[("LUT / Preset Files", "*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.dng;*.xmp"), ("All Files", "*.*")]
            )
        else:
            path = filedialog.askdirectory(
                initialdir=initial_dir if os.path.exists(initial_dir) else "C:/",
                title="Select Workspace Folder"
            )
        root.destroy()
        return path
    except Exception as e:
        print(f"   > [BROWSE] Native dialog error: {e}")
        return None


@app.post("/api/browse")
async def api_browse(req: Request):
    """
    Opens native Windows folder or file selection dialog.
    """
    body = await req.json()
    dialog_type = body.get("type", "folder")  # 'folder' or 'file'
    initial_dir = body.get("initial_dir", "C:/")

    selected_path = await asyncio.to_thread(_open_native_dialog, dialog_type, initial_dir)
    if selected_path:
        norm_path = selected_path.replace("\\", "/")
        return {"status": "ok", "path": norm_path}
    return {"status": "cancelled", "path": None}


@app.get("/api/config")
def api_get_config():
    cfg = get_config()
    # Mask API key for display safety
    masked = cfg.copy()
    if masked["ORCA_API_KEY"]:
        k = masked["ORCA_API_KEY"]
        masked["ORCA_API_KEY_MASKED"] = f"{k[:7]}...{k[-4:]}" if len(k) > 12 else "***"
    return masked


@app.post("/api/config")
def api_save_config(update: ConfigUpdate):
    data = update.dict(exclude_unset=True)
    
    for key, value in data.items():
        if value is not None:
            val_str = str(value).lower() if isinstance(value, bool) else str(value)
            set_key(ENV_FILE_PATH, key, val_str)

    load_dotenv(override=True)
    return {"status": "ok", "config": get_config()}


@app.get("/api/validate")
def api_validate():
    cfg = get_config()
    input_dir = cfg["INPUT_FOLDER"]
    output_dir = cfg["OUTPUT_FOLDER"]
    preset_dir = cfg["PRESET_FOLDER"]

    errors = []
    warnings = []

    # 1. Incoming Photos Validation
    valid_img_exts = ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG', '.dng', '.DNG')
    photo_count = 0
    if not os.path.exists(input_dir):
        errors.append("Incoming folder not found!")
    else:
        try:
            photos = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_img_exts)]
            photo_count = len(photos)
            if photo_count == 0:
                errors.append("No photos in incoming folder!")
        except Exception:
            errors.append("Cannot access incoming folder!")

    # 2. Output Folder Validation
    if not output_dir or not isinstance(output_dir, str) or output_dir.strip() == "":
        errors.append("Output folder path is empty!")
    else:
        try:
            os.makedirs(output_dir, exist_ok=True)
            test_file = os.path.join(output_dir, ".write_test.tmp")
            with open(test_file, "w") as f:
                f.write("ok")
            if os.path.exists(test_file):
                os.remove(test_file)
        except Exception:
            errors.append("Output folder is not writable!")

    # 3. Presets / 3D LUT Validation (Direct File or Single-LUT folder)
    valid_preset_exts = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.dng', '.xmp')
    preset_count = 0
    preset_files = []

    if not preset_dir or not os.path.exists(preset_dir):
        errors.append("Presets folder / LUT file not found!")
    elif os.path.isfile(preset_dir):
        # Direct file path
        if preset_dir.lower().endswith(valid_preset_exts) and os.path.basename(preset_dir).lower() != 'neutral_lut.png':
            preset_count = 1
            preset_files = [os.path.basename(preset_dir)]
        else:
            errors.append("Selected file is not a valid 3D LUT or Preset!")
    else:
        # Directory
        try:
            preset_files = [
                f for f in os.listdir(preset_dir)
                if f.lower().endswith(valid_preset_exts) and f.lower() != 'neutral_lut.png'
            ]
            preset_count = len(preset_files)
            if preset_count == 0:
                errors.append("No LUT found in Presets folder!")
            elif preset_count > 1:
                errors.append(f"Multiple LUTs found ({preset_count})! Only 1 allowed.")
        except Exception:
            errors.append("Cannot access Presets folder!")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "photo_count": photo_count,
        "preset_count": preset_count,
        "preset_files": preset_files,
        "input_folder": input_dir,
        "output_folder": output_dir,
        "preset_folder": preset_dir
    }


@app.get("/api/presets")
def api_list_presets():
    cfg = get_config()
    preset_dir = cfg["PRESET_FOLDER"]
    
    files = []
    if os.path.isdir(preset_dir):
        files = [f for f in os.listdir(preset_dir) if f.lower().endswith(('.dng', '.xmp'))]
    elif os.path.isfile(preset_dir):
        files = [os.path.basename(preset_dir)]
    
    preset_mgr = PresetManager(preset_folder=preset_dir)

    return {
        "active_preset": preset_mgr.preset_name,
        "summary": preset_mgr.get_summary_text(),
        "params": preset_mgr.params,
        "available_presets": files
    }


@app.post("/api/presets/upload")
async def api_upload_preset(file: UploadFile = File(...)):
    cfg = get_config()
    target_dir = os.path.dirname(preset_dir) if os.path.isfile(preset_dir) else preset_dir
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    dest_path = os.path.join(target_dir, file.filename)
    with open(dest_path, "wb") as f:
        content = await file.read()
        f.write(content)

    preset_mgr = PresetManager(preset_folder=preset_dir)
    return {
        "status": "uploaded",
        "filename": file.filename,
        "summary": preset_mgr.get_summary_text()
    }


@app.get("/api/photos/incoming")
def api_get_incoming_photos():
    cfg = get_config()
    input_dir = cfg["INPUT_FOLDER"]
    output_dir = cfg["OUTPUT_FOLDER"]
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    valid_exts = ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG', '.dng', '.DNG')
    files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_exts)]

    items = []
    for f in sorted(files):
        in_path = os.path.join(input_dir, f)
        base, _ = os.path.splitext(f)
        out_name = f"{base}.jpg"
        out_path = os.path.join(output_dir, out_name)
        is_processed = os.path.exists(out_path)

        size_mb = round(os.path.getsize(in_path) / (1024 * 1024), 2)
        items.append({
            "filename": f,
            "output_filename": out_name,
            "is_processed": is_processed,
            "size_mb": size_mb,
            "input_url": f"/api/image/incoming/{urllib.parse.quote(f)}",
            "output_url": f"/api/image/output/{urllib.parse.quote(out_name)}" if is_processed else None
        })

    return {
        "total": len(items),
        "processed_count": sum(1 for i in items if i["is_processed"]),
        "input_folder": input_dir,
        "output_folder": output_dir,
        "photos": items
    }


@app.get("/api/image/{category}/{filename:path}")
def api_serve_image(category: str, filename: str):
    cfg = get_config()
    filename = urllib.parse.unquote(filename)
    
    if category == "incoming":
        path = os.path.join(cfg["INPUT_FOLDER"], filename)
    elif category == "output":
        path = os.path.join(cfg["OUTPUT_FOLDER"], filename)
    elif category == "preset":
        path = os.path.join(cfg["PRESET_FOLDER"], filename)
    else:
        raise HTTPException(status_code=400, detail="Invalid category")

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@app.get("/api/process/stream")
async def api_process_stream(request: Request):
    """
    Server-Sent Events (SSE) streaming real-time batch processing progress.
    """
    cfg = get_config()
    input_dir = cfg["INPUT_FOLDER"]
    output_dir = cfg["OUTPUT_FOLDER"]
    preset_dir = cfg["PRESET_FOLDER"]

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    if not os.path.isfile(preset_dir) and preset_dir:
        os.makedirs(preset_dir, exist_ok=True)

    valid_exts = ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG', '.dng', '.DNG')
    files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_exts)] if os.path.isdir(input_dir) else []

    async def event_generator():
        valid_preset_exts = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.dng', '.xmp')
        preset_files = []
        if os.path.isfile(preset_dir):
            if preset_dir.lower().endswith(valid_preset_exts) and os.path.basename(preset_dir).lower() != 'neutral_lut.png':
                preset_files = [os.path.basename(preset_dir)]
        elif os.path.isdir(preset_dir):
            preset_files = [
                f for f in os.listdir(preset_dir)
                if f.lower().endswith(valid_preset_exts) and f.lower() != 'neutral_lut.png'
            ]

        if len(files) == 0:
            yield f"data: {json.dumps({'type': 'error', 'message': f'No photos found in Incoming folder: {input_dir}'})}\n\n"
            return

        if len(preset_files) == 0:
            yield f"data: {json.dumps({'type': 'error', 'message': f'No 3D LUT or Preset file found in Presets location: {preset_dir}'})}\n\n"
            return

        if len(preset_files) > 1:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Multiple LUT files detected ({len(preset_files)} found). Only 1 active LUT is allowed.'})}\n\n"
            return

        try:
            preset_mgr = PresetManager(preset_folder=preset_dir)
            cropper = SmartCropper(api_key=cfg["ORCA_API_KEY"], api_url=cfg["ORCA_API_URL"], model=cfg["ORCA_MODEL"])
            adjuster = AutoAdjuster(api_key=cfg["ORCA_API_KEY"], api_url=cfg["ORCA_API_URL"], model=cfg["ORCA_MODEL"])
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Failed to initialize AI Engine: {str(e)}'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'init', 'total': len(files), 'preset': preset_mgr.preset_name, 'preset_summary': preset_mgr.get_summary_text()})}\n\n"
        await asyncio.sleep(0.05)

        for idx, filename in enumerate(files, 1):
            if await request.is_disconnected():
                print(f"   > [SSE] Aborted at photo {idx}/{len(files)}: client disconnected.")
                break

            try:
                yield f"data: {json.dumps({'type': 'photo_start', 'index': idx, 'total': len(files), 'filename': filename})}\n\n"
                await asyncio.sleep(0.05)

                img_path = os.path.join(input_dir, filename)
                img = cv2.imread(img_path)

                if img is None:
                    yield f"data: {json.dumps({'type': 'photo_error', 'index': idx, 'filename': filename, 'error': 'Could not decode image'})}\n\n"
                    continue

                h, w = img.shape[:2]

                # Step 1: Preset Color Grading
                yield f"data: {json.dumps({'type': 'step_preset', 'index': idx, 'filename': filename})}\n\n"
                preset_applied = preset_mgr.apply_preset(img)
                await asyncio.sleep(0.05)

                # Step 2: Per-Photo Dynamic Adjustment
                yield f"data: {json.dumps({'type': 'step_adjust', 'index': idx, 'filename': filename})}\n\n"
                if cfg["ENABLE_AUTO_BALANCING"]:
                    adjusted, telemetry = adjuster.fine_tune(preset_applied)
                else:
                    adjusted = preset_applied
                    telemetry = {"exp_shift_ev": 0.0, "shadow_lift_pct": 0, "highlight_comp_pct": 0, "wb_status": "Manual"}
                await asyncio.sleep(0.05)

                # Step 3: Smart Landscape AI Cropping
                if cfg["ENABLE_AI_SMART_CROP"]:
                    yield f"data: {json.dumps({'type': 'step_crop', 'index': idx, 'filename': filename})}\n\n"
                    cropped, crop_telemetry = cropper.crop_best_landscape(adjusted, enable_ai=True)
                    await asyncio.sleep(0.05)
                else:
                    cropped = adjusted
                    crop_telemetry = {"method": "Original (No Crop)", "trim_x_pct": 0, "trim_y_pct": 0, "notes": "AI Crop disabled in settings"}

                # Step 4: Scale to High-Res Master & Export (Preserves 100% Full Resolution if TARGET_MAX_WIDTH is 0)
                ch, cw = cropped.shape[:2]
                target_w = int(cfg.get("TARGET_MAX_WIDTH", 0))
                if target_w > 0 and cw > target_w:
                    new_w = target_w
                    new_h = int(ch * (target_w / cw))
                    final_img = cv2.resize(cropped, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
                else:
                    final_img = cropped

                jpeg_quality = int(cfg.get("JPEG_QUALITY", 100))
                base_name, _ = os.path.splitext(filename)
                out_filename = f"{base_name}.jpg"
                out_path = os.path.join(output_dir, out_filename)
                cv2.imwrite(out_path, final_img, [
                    int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality,
                    int(cv2.IMWRITE_JPEG_OPTIMIZE), 1
                ])

                yield f"data: {json.dumps({'type': 'photo_done', 'index': idx, 'total': len(files), 'filename': filename, 'output_filename': out_filename, 'input_url': f'/api/image/incoming/{urllib.parse.quote(filename)}', 'output_url': f'/api/image/output/{urllib.parse.quote(out_filename)}', 'dimensions': f'{final_img.shape[1]}x{final_img.shape[0]}', 'adjust_telemetry': telemetry, 'crop_telemetry': crop_telemetry})}\n\n"
                await asyncio.sleep(0.1)
            except Exception as photo_err:
                print(f"   > [SSE Error on {filename}]: {photo_err}")
                yield f"data: {json.dumps({'type': 'photo_error', 'index': idx, 'filename': filename, 'error': str(photo_err)})}\n\n"

        yield f"data: {json.dumps({'type': 'complete', 'total': len(files), 'processed': len(files)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/adjust/preview")
def api_adjust_preview(req: AdjustRequest):
    """
    Ultra-fast (sub-15ms) live preview with manual slider adjustments for single-photo editing.
    Preserves existing AI Smart Crop & base develop calibration.
    """
    cfg = get_config()
    input_path = os.path.join(cfg["INPUT_FOLDER"], req.filename)
    base_name, _ = os.path.splitext(req.filename)
    out_path = os.path.join(cfg["OUTPUT_FOLDER"], f"{base_name}.jpg")

    # If already processed, start directly from the AI-cropped & graded photo
    if os.path.exists(out_path):
        img = cv2.imread(out_path)
    elif os.path.exists(input_path):
        raw_img = cv2.imread(input_path)
        if raw_img is None:
            raise HTTPException(status_code=400, detail="Cannot read image")
        preset_mgr = PresetManager(preset_folder=cfg["PRESET_FOLDER"])
        img = preset_mgr.apply_preset(raw_img)
    else:
        raise HTTPException(status_code=404, detail="Photo not found")

    if img is None:
        raise HTTPException(status_code=400, detail="Cannot decode image")

    # Downscale first for instant real-time slider speed (< 10ms calculation)
    h, w = img.shape[:2]
    if w > 960:
        img_work = cv2.resize(img, (960, int(h * (960 / w))), interpolation=cv2.INTER_AREA)
    else:
        img_work = img.copy()

    # Apply Overrides on fast working buffer
    img_float = img_work.astype(np.float32)

    # Exposure override
    if req.exposure != 0:
        img_float = img_float * (2 ** req.exposure)

    # Contrast override
    if req.contrast != 0:
        c_mult = 1.0 + (req.contrast / 100.0) * 0.5
        img_float = ((img_float - 128.0) * c_mult) + 128.0

    # Shadows & Highlights
    if req.highlights != 0:
        hl_mask = np.clip((img_float - 128.0) / 127.0, 0, 1) ** 1.3
        img_float += hl_mask * (req.highlights * 0.4)

    if req.shadows != 0:
        sh_mask = np.clip((128.0 - img_float) / 128.0, 0, 1) ** 1.3
        img_float += sh_mask * (req.shadows * 0.5)

    img_out = np.clip(img_float, 0, 255).astype(np.uint8)

    # Temperature & Tint
    if req.temperature != 0 or req.tint != 0:
        b, g, r = cv2.split(img_out.astype(np.float32))
        r = np.clip(r + (req.temperature * 1.2) + (req.tint * 0.5), 0, 255)
        g = np.clip(g - (req.tint * 0.8), 0, 255)
        b = np.clip(b - (req.temperature * 1.2), 0, 255)
        img_out = cv2.merge([b, g, r]).astype(np.uint8)

    # Vibrance override
    if req.vibrance != 0:
        hsv = cv2.cvtColor(img_out, cv2.COLOR_BGR2HSV).astype(np.float32)
        sat_mask = 1.0 - (hsv[:, :, 1] / 255.0)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] + (hsv[:, :, 1] * (req.vibrance / 100.0) * sat_mask * 0.8), 0, 255)
        img_out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # Clarity / Detail
    if req.clarity > 0:
        blurred = cv2.GaussianBlur(img_out, (0, 0), sigmaX=3.0)
        img_out = np.clip(cv2.addWeighted(img_out, 1.0 + (req.clarity / 100.0), blurred, -(req.clarity / 100.0), 0), 0, 255)

    # Crop Overrides (if user explicitly adjusts crop sliders)
    if req.crop_top > 0 or req.crop_bottom > 0 or req.crop_left > 0 or req.crop_right > 0:
        ch, cw = img_out.shape[:2]
        y1 = int(ch * np.clip(req.crop_top, 0.0, 0.45))
        y2 = int(ch * (1.0 - np.clip(req.crop_bottom, 0.0, 0.45)))
        x1 = int(cw * np.clip(req.crop_left, 0.0, 0.45))
        x2 = int(cw * (1.0 - np.clip(req.crop_right, 0.0, 0.45)))
        if (x2 - x1) > 100 and (y2 - y1) > 100:
            img_out = img_out[y1:y2, x1:x2]

    _, buffer = cv2.imencode(".jpg", img_out, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64_preview = base64.b64encode(buffer).decode("utf-8")

    return {
        "status": "ok",
        "preview_data_url": f"data:image/jpeg;base64,{b64_preview}",
        "dimension": f"{img_out.shape[1]}x{img_out.shape[0]}"
    }


@app.post("/api/adjust/save")
def api_adjust_save(req: AdjustRequest):
    """
    Saves the custom adjusted high-resolution image directly to OUTPUT_FOLDER.
    Preserves AI Smart Crop & develops high-fidelity master output.
    """
    cfg = get_config()
    input_path = os.path.join(cfg["INPUT_FOLDER"], req.filename)
    base_name, _ = os.path.splitext(req.filename)
    out_filename = f"{base_name}.jpg"
    out_path = os.path.join(cfg["OUTPUT_FOLDER"], out_filename)

    if os.path.exists(out_path):
        img = cv2.imread(out_path)
    elif os.path.exists(input_path):
        raw_img = cv2.imread(input_path)
        preset_mgr = PresetManager(preset_folder=cfg["PRESET_FOLDER"])
        img = preset_mgr.apply_preset(raw_img)
    else:
        raise HTTPException(status_code=404, detail="Photo not found")

    if img is None:
        raise HTTPException(status_code=400, detail="Cannot read image")

    img_float = img.astype(np.float32)

    if req.exposure != 0:
        img_float = img_float * (2 ** req.exposure)
    if req.contrast != 0:
        c_mult = 1.0 + (req.contrast / 100.0) * 0.5
        img_float = ((img_float - 128.0) * c_mult) + 128.0
    if req.highlights != 0:
        hl_mask = np.clip((img_float - 128.0) / 127.0, 0, 1) ** 1.3
        img_float += hl_mask * (req.highlights * 0.4)
    if req.shadows != 0:
        sh_mask = np.clip((128.0 - img_float) / 128.0, 0, 1) ** 1.3
        img_float += sh_mask * (req.shadows * 0.5)

    img_out = np.clip(img_float, 0, 255).astype(np.uint8)

    if req.temperature != 0 or req.tint != 0:
        b, g, r = cv2.split(img_out.astype(np.float32))
        r = np.clip(r + (req.temperature * 1.2) + (req.tint * 0.5), 0, 255)
        g = np.clip(g - (req.tint * 0.8), 0, 255)
        b = np.clip(b - (req.temperature * 1.2), 0, 255)
        img_out = cv2.merge([b, g, r]).astype(np.uint8)

    if req.vibrance != 0:
        hsv = cv2.cvtColor(img_out, cv2.COLOR_BGR2HSV).astype(np.float32)
        sat_mask = 1.0 - (hsv[:, :, 1] / 255.0)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] + (hsv[:, :, 1] * (req.vibrance / 100.0) * sat_mask * 0.8), 0, 255)
        img_out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    if req.clarity > 0:
        blurred = cv2.GaussianBlur(img_out, (0, 0), sigmaX=3.0)
        img_out = np.clip(cv2.addWeighted(img_out, 1.0 + (req.clarity / 100.0), blurred, -(req.clarity / 100.0), 0), 0, 255)

    if req.crop_top > 0 or req.crop_bottom > 0 or req.crop_left > 0 or req.crop_right > 0:
        ch, cw = img_out.shape[:2]
        y1 = int(ch * np.clip(req.crop_top, 0.0, 0.45))
        y2 = int(ch * (1.0 - np.clip(req.crop_bottom, 0.0, 0.45)))
        x1 = int(cw * np.clip(req.crop_left, 0.0, 0.45))
        x2 = int(cw * (1.0 - np.clip(req.crop_right, 0.0, 0.45)))
        if (x2 - x1) > 100 and (y2 - y1) > 100:
            img_out = img_out[y1:y2, x1:x2]

    # Save directly at 100% maximum quality & full resolution
    jpeg_quality = int(cfg.get("JPEG_QUALITY", 100))
    cv2.imwrite(out_path, img_out, [
        int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality,
        int(cv2.IMWRITE_JPEG_OPTIMIZE), 1
    ])

    return {
        "status": "saved",
        "output_filename": out_filename,
        "output_url": f"/api/image/output/{urllib.parse.quote(out_filename)}",
        "dimension": f"{img_out.shape[1]}x{img_out.shape[0]}"
    }


# Mount Static Frontend
os.makedirs(WEB_DIR, exist_ok=True)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    print("\n=======================================================")
    print("🚀 Starting Lightroom AI Studio Web Server...")
    print("🌐 Open your browser at: http://localhost:8000")
    print("=======================================================\n")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
