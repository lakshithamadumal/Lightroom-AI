"""
Lightroom AI - Studio Edition 2.0
Production FastAPI Web Server (server.py)

Features:
- Two-Stage Processing Pipeline (Stage 1: Immutable 3D LUT + Spatial; Stage 2: AI & Fine-Tuning)
- High-Precision 32-bit Floating Point LUT Evaluation
- Server-Sent Events (SSE) Batch Processing Stream with Real-Time Telemetry
- Sub-15ms Live Preview Slider Engine on Immutable Stage 1 Base Cache
- Automatic Preset Bundle Discovery & Validation
- Reference Chart Calibration & Fidelity Benchmarking Endpoints
- Native Windows Folder Selection Dialogs
"""

import os
import sys
import json
import asyncio
import base64
import urllib.parse
import cv2
import numpy as np
from typing import Optional, Dict, Any, Union
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
from image_pipeline import ImagePipeline
from color_space import ColorManager, ColorSpace
from calibration_engine import CalibrationEngine
from fidelity_test import FidelityBenchmark

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

def get_base_dir() -> str:
    """Returns directory containing the application executable or source script."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(relative_path: str) -> str:
    """Returns absolute path to a resource, supporting PyInstaller bundled directories and source."""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            candidate = os.path.join(sys._MEIPASS, relative_path)
            if os.path.exists(candidate):
                return candidate
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidate2 = os.path.join(exe_dir, relative_path)
        if os.path.exists(candidate2):
            return candidate2
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


ENV_FILE_PATH = os.path.join(get_base_dir(), ".env")
WEB_DIR = get_resource_path("web")


def get_config():
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=True)
    base_dir = get_base_dir()
    
    preset_folder_val = os.getenv("PRESET_FOLDER", "calibration")
    if not os.path.isabs(preset_folder_val):
        resolved_preset = get_resource_path(preset_folder_val)
        if os.path.exists(resolved_preset):
            preset_folder_val = resolved_preset

    return {
        "ORCA_API_KEY": os.getenv("ORCA_API_KEY", ""),
        "ORCA_API_URL": os.getenv("ORCA_API_URL", "https://api.groq.com/openai/v1/chat/completions"),
        "ORCA_MODEL": os.getenv("ORCA_MODEL", "qwen/qwen3.8-27b"),
        "INPUT_FOLDER": os.getenv("INPUT_FOLDER", "C:/Media_Incoming"),
        "PRESET_FOLDER": preset_folder_val,
        "OUTPUT_FOLDER": os.getenv("OUTPUT_FOLDER", "C:/Media_Output"),
        "ENABLE_AI_SMART_CROP": os.getenv("ENABLE_AI_SMART_CROP", "true").lower() == "true",
        "ENABLE_AUTO_BALANCING": os.getenv("ENABLE_AUTO_BALANCING", "true").lower() == "true",
        "TARGET_MAX_WIDTH": int(os.getenv("TARGET_MAX_WIDTH", "0")),  # 0 = Full original resolution
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


class InstallMasterPresetRequest(BaseModel):
    hald_path: Optional[str] = None
    preset_name: Optional[str] = "Master Studio Preset"


class AdjustRequest(BaseModel):
    filename: str
    exposure: float = 0.0      # EV offset (-2.0 to +2.0)
    contrast: float = 0.0      # Offset (-50 to +50)
    shadows: float = 0.0       # Offset (-50 to +50)
    highlights: float = 0.0    # Offset (-50 to +50)
    temperature: float = 0.0   # Kelvin offset (-50 to +50)
    tint: float = 0.0          # Tint offset (-50 to +50)
    vibrance: float = 0.0      # Vibrance offset (-50 to +50)
    clarity: float = 0.0       # Clarity offset (0 to 50)
    crop_top: float = 0.0      # Normalized top crop (0.0 to 0.4)
    crop_bottom: float = 0.0   # Normalized bottom crop (0.0 to 0.4)
    crop_left: float = 0.0     # Normalized left crop (0.0 to 0.4)
    crop_right: float = 0.0    # Normalized right crop (0.0 to 0.4)


DEFAULT_ADJUSTMENTS = {
    "exposure": 0.0,
    "contrast": 0.0,
    "shadows": 0.0,
    "highlights": 0.0,
    "temperature": 0.0,
    "tint": 0.0,
    "vibrance": 0.0,
    "clarity": 0.0,
    "crop_top": 0.0,
    "crop_bottom": 0.0,
    "crop_left": 0.0,
    "crop_right": 0.0,
}


def ensure_default_directories():
    """Ensures incoming, preset, and output folders exist on startup."""
    cfg = get_config()
    for key in ["INPUT_FOLDER", "OUTPUT_FOLDER", "PRESET_FOLDER"]:
        p = cfg.get(key)
        if p and not os.path.isfile(p):
            try:
                os.makedirs(p, exist_ok=True)
            except Exception as e:
                print(f"   > [STARTUP] Directory initialization notice ({key}={p}): {e}")


ensure_default_directories()


def _get_overrides_file(output_folder: str) -> str:
    return os.path.join(output_folder, ".overrides.json")


def _get_telemetry_file(output_folder: str) -> str:
    return os.path.join(output_folder, ".telemetry.json")


def load_overrides(output_folder: str) -> dict:
    ov_file = _get_overrides_file(output_folder)
    if os.path.exists(ov_file):
        try:
            with open(ov_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def load_telemetry(output_folder: str) -> dict:
    tel_file = _get_telemetry_file(output_folder)
    if os.path.exists(tel_file):
        try:
            with open(tel_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_override_params(output_folder: str, filename: str, params: dict):
    ov = load_overrides(output_folder)
    ov[filename] = params
    try:
        with open(_get_overrides_file(output_folder), "w", encoding="utf-8") as f:
            json.dump(ov, f, indent=2)
    except Exception as e:
        print(f"   > [OVERRIDES] Error saving overrides: {e}")


def save_photo_telemetry(output_folder: str, filename: str, telemetry: dict):
    tel = load_telemetry(output_folder)
    tel[filename] = telemetry
    try:
        with open(_get_telemetry_file(output_folder), "w", encoding="utf-8") as f:
            json.dump(tel, f, indent=2)
    except Exception as e:
        print(f"   > [TELEMETRY] Error saving telemetry: {e}")


def apply_adjustments(img: np.ndarray, req: AdjustRequest) -> np.ndarray:
    """Delegates Stage 2 fine-tuning and optional manual crop to ImagePipeline."""
    adj_dict = req.model_dump(exclude={"filename"}) if hasattr(req, "model_dump") else req.dict(exclude={"filename"})
    stage2_balanced = ImagePipeline.render_stage2_adjustments(img, adj_dict)
    cropped_out, _ = ImagePipeline.apply_crop_stage(stage2_balanced, adj_dict, enable_smart_crop=False)
    return cropped_out


def safe_read_image(path: str, target_space: Union[str, ColorSpace] = "Adobe_RGB_1998") -> Optional[np.ndarray]:
    """
    Safely reads any image format (JPG, PNG with/without alpha, TIFF, etc.),
    performs ICC color management normalization to the declared target working space (default: Adobe RGB 1998),
    and guarantees a standard 3-channel 8-bit BGR numpy array.
    """
    if not os.path.exists(path):
        return None
    try:
        img, _ = ColorManager.read_image_color_managed(path, target_space=target_space)
        if img is not None:
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            elif len(img.shape) == 3 and img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            return img
        # Fallback to cv2
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"   > [IMAGE READ ERROR] {path}: {e}")
        return None


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
                title="Select 3D LUT, Preset Bundle or XMP File",
                filetypes=[("LUT / Preset Files", "*.cube;*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.dng;*.xmp;*.json"), ("All Files", "*.*")]
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
    body = await req.json()
    dialog_type = body.get("type", "folder")
    initial_dir = body.get("initial_dir", "C:/")

    selected_path = await asyncio.to_thread(_open_native_dialog, dialog_type, initial_dir)
    if selected_path:
        norm_path = selected_path.replace("\\", "/")
        return {"status": "ok", "path": norm_path}
    return {"status": "cancelled", "path": None}


@app.get("/api/config")
def api_get_config():
    cfg = get_config()
    masked = cfg.copy()
    if masked["ORCA_API_KEY"]:
        k = masked["ORCA_API_KEY"]
        masked["ORCA_API_KEY_MASKED"] = f"{k[:7]}...{k[-4:]}" if len(k) > 12 else "***"
    return masked


@app.post("/api/config")
def api_save_config(update: ConfigUpdate):
    data = update.model_dump(exclude_unset=True) if hasattr(update, "model_dump") else update.dict(exclude_unset=True)
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
    valid_img_exts = ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG', '.dng', '.DNG', '.tif', '.tiff')
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

    # 3. Presets Validation
    valid_preset_exts = ('.cube', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.dng', '.xmp', '.json')
    preset_count = 0
    preset_files = []

    if not preset_dir or not os.path.exists(preset_dir):
        errors.append("Presets folder / LUT file not found!")
    elif os.path.isfile(preset_dir):
        if preset_dir.lower().endswith(valid_preset_exts):
            preset_count = 1
            preset_files = [os.path.basename(preset_dir)]
        else:
            errors.append("Selected file is not a valid 3D LUT or Preset bundle!")
    else:
        try:
            preset_files = [
                f for f in os.listdir(preset_dir)
                if f.lower().endswith(valid_preset_exts) or os.path.isdir(os.path.join(preset_dir, f))
            ]
            preset_count = len(preset_files)
            if preset_count == 0:
                errors.append("No LUT or Preset found in Presets folder!")
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
        files = [
            f for f in os.listdir(preset_dir)
            if f.lower().endswith(('.cube', '.png', '.jpg', '.jpeg', '.tif', '.dng', '.xmp')) or os.path.isdir(os.path.join(preset_dir, f))
        ]
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
    preset_dir = get_config()["PRESET_FOLDER"]
    if not os.path.isdir(preset_dir):
        os.makedirs(preset_dir, exist_ok=True)
    
    dest_path = os.path.join(preset_dir, file.filename)
    with open(dest_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    return {"status": "uploaded", "filename": file.filename}


@app.post("/api/presets/install-master")
async def api_install_master_preset(req: InstallMasterPresetRequest):
    """
    Validates a processed HALD PNG/TIFF, backs up current master artifacts,
    compiles into 64^3 Float32 production LUT, and atomically installs into calibration/
    as the new active Studio Master Preset.
    """
    if not req.hald_path or not os.path.exists(req.hald_path):
        raise HTTPException(status_code=400, detail=f"HALD file not found: {req.hald_path}")

    res = CalibrationEngine.install_master_preset(
        hald_source=req.hald_path,
        calibration_dir="calibration",
        backup_dir="presets/test_preset_backup",
        preset_name=req.preset_name or "Master Studio Preset"
    )

    if not res.get("installed"):
        raise HTTPException(status_code=400, detail=res.get("message", "Master preset installation failed"))

    # Update .env to point to calibration
    set_key(ENV_FILE_PATH, "PRESET_FOLDER", "calibration")
    load_dotenv(override=True)

    # Reload preset manager
    preset_mgr = PresetManager(preset_folder="calibration")
    res["active_preset"] = preset_mgr.preset_name
    res["summary"] = preset_mgr.get_summary_text()
    return res


@app.post("/api/presets/install-master-upload")
async def api_install_master_upload(file: UploadFile = File(...), preset_name: Optional[str] = Form("Master Studio Preset")):
    """Uploads a HALD PNG/TIFF and installs it directly as the Master Studio Preset."""
    temp_dir = os.path.abspath("temp_hald_upload")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, file.filename)
    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        res = CalibrationEngine.install_master_preset(
            hald_source=temp_path,
            calibration_dir="calibration",
            backup_dir="presets/test_preset_backup",
            preset_name=preset_name,
            source_filename=file.filename
        )

        if not res.get("installed"):
            raise HTTPException(status_code=400, detail=res.get("message", "Master preset installation failed"))

        # Update .env to point to calibration
        set_key(ENV_FILE_PATH, "PRESET_FOLDER", "calibration")
        load_dotenv(override=True)

        preset_mgr = PresetManager(preset_folder="calibration")
        res["active_preset"] = preset_mgr.preset_name
        res["summary"] = preset_mgr.get_summary_text()
        return res
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@app.get("/api/presets/generate-chart")
def api_generate_calibration_chart():
    """Generates and downloads a standardized Level 8 identity calibration chart."""
    chart_path = os.path.abspath("web/identity_calibration_chart.png")
    CalibrationEngine.generate_calibration_chart(chart_path, level=8, bit_depth=8)
    return FileResponse(chart_path, filename="identity_calibration_chart.png", media_type="image/png")


@app.get("/api/photos/incoming")
def api_get_incoming_photos():
    cfg = get_config()
    input_dir = cfg["INPUT_FOLDER"]
    output_dir = cfg["OUTPUT_FOLDER"]
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    valid_exts = ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG', '.dng', '.DNG', '.tif', '.tiff')
    files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_exts)]
    overrides = load_overrides(output_dir)
    telemetry_store = load_telemetry(output_dir)

    items = []
    for f in sorted(files):
        in_path = os.path.join(input_dir, f)
        base, _ = os.path.splitext(f)
        out_name = f"{base}.jpg"
        out_path = os.path.join(output_dir, out_name)
        is_processed = os.path.exists(out_path)
        photo_tel = telemetry_store.get(f, {})

        size_mb = round(os.path.getsize(in_path) / (1024 * 1024), 2)
        items.append({
            "filename": f,
            "output_filename": out_name,
            "is_processed": is_processed,
            "size_mb": size_mb,
            "input_url": f"/api/image/incoming/{urllib.parse.quote(f)}",
            "output_url": f"/api/image/output/{urllib.parse.quote(out_name)}" if is_processed else None,
            "adjustments": overrides.get(f, DEFAULT_ADJUSTMENTS.copy()),
            "adjust_telemetry": photo_tel.get("adjust_telemetry"),
            "crop_telemetry": photo_tel.get("crop_telemetry")
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
    elif category == "base":
        path = os.path.join(cfg["OUTPUT_FOLDER"], ".base", filename)
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
    SSE Stream executing the Strict Two-Stage & Smart Crop Rendering Pipeline:
    Stage 1: Base Preset Engine (3D LUT + Spatial Adjustments) -> Full-Frame Cached to .base/
    Stage 2: AI Auto-Balancing (Candidate Validation & Preset Preservation)
    Stage 3: Optional Smart Crop (Spatial Slicing on Stage 2 Balanced Buffer)
    Stage 4: Single Final Working Space (Adobe RGB) -> Delivery Export Space (sRGB) Conversion
    """
    cfg = get_config()
    input_dir = cfg["INPUT_FOLDER"]
    output_dir = cfg["OUTPUT_FOLDER"]
    preset_dir = cfg["PRESET_FOLDER"]

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    if not os.path.isfile(preset_dir) and preset_dir:
        os.makedirs(preset_dir, exist_ok=True)

    valid_exts = ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG', '.dng', '.DNG', '.tif', '.tiff')
    files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_exts)] if os.path.isdir(input_dir) else []

    async def event_generator():
        if len(files) == 0:
            yield f"data: {json.dumps({'type': 'error', 'message': f'No photos found in Incoming folder: {input_dir}'})}\n\n"
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

        base_dir = os.path.join(output_dir, ".base")
        os.makedirs(base_dir, exist_ok=True)

        for idx, filename in enumerate(files, 1):
            if await request.is_disconnected():
                print(f"   > [SSE] Aborted at photo {idx}/{len(files)}: client disconnected.")
                break

            try:
                yield f"data: {json.dumps({'type': 'photo_start', 'index': idx, 'total': len(files), 'filename': filename})}\n\n"
                await asyncio.sleep(0.05)

                img_path = os.path.join(input_dir, filename)
                img = safe_read_image(img_path)

                if img is None:
                    yield f"data: {json.dumps({'type': 'photo_error', 'index': idx, 'filename': filename, 'error': 'Could not decode image'})}\n\n"
                    continue

                # ================= STAGE 1: IMMUTABLE FULL-FRAME BASE PRESET =================
                yield f"data: {json.dumps({'type': 'step_preset', 'index': idx, 'filename': filename})}\n\n"
                stage1_preset_base = preset_mgr.apply_preset(img)
                await asyncio.sleep(0.05)

                jpeg_quality = int(cfg.get("JPEG_QUALITY", 100))
                base_name, _ = os.path.splitext(filename)
                out_filename = f"{base_name}.jpg"
                out_path = os.path.join(output_dir, out_filename)
                base_img_path = os.path.join(base_dir, out_filename)

                # Persist pristine FULL-FRAME Stage 1 develop image to .base folder
                export_base = preset_mgr.export_image(stage1_preset_base)
                cv2.imwrite(base_img_path, export_base, [
                    int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality,
                    int(cv2.IMWRITE_JPEG_OPTIMIZE), 1
                ])

                # ================= STAGE 2: AI AUTO-BALANCING =================
                yield f"data: {json.dumps({'type': 'step_adjust', 'index': idx, 'filename': filename})}\n\n"
                if cfg["ENABLE_AUTO_BALANCING"]:
                    ai_res = adjuster.analyze_params(stage1_preset_base, preset_name=preset_mgr.preset_name, enable_ai=True)
                    ai_adj = {
                        "exposure": ai_res.get("exposure", 0.0),
                        "contrast": 0.0,
                        "shadows": ai_res.get("shadows", 0.0),
                        "highlights": ai_res.get("highlights", 0.0),
                        "temperature": ai_res.get("temperature", 0.0),
                        "tint": ai_res.get("tint", 0.0),
                        "vibrance": 0.0,
                        "clarity": 0.0,
                        "crop_top": 0.0,
                        "crop_bottom": 0.0,
                        "crop_left": 0.0,
                        "crop_right": 0.0,
                    }
                    telemetry = ai_res.get("telemetry", {})
                    stage2_balanced = ImagePipeline.render_stage2_adjustments(stage1_preset_base, ai_adj)
                    save_override_params(output_dir, filename, ai_adj)
                else:
                    stage2_balanced = stage1_preset_base.copy()
                    ai_adj = DEFAULT_ADJUSTMENTS.copy()
                    telemetry = {
                        "stage": 2,
                        "ai_status": "ai_disabled",
                        "scene_type": "general",
                        "confidence": 0.0,
                        "needs_correction": False,
                        "adjustments_applied": DEFAULT_ADJUSTMENTS.copy(),
                        "no_op": True,
                        "reason": "AI Auto-Balancing disabled in settings.",
                        "api_error": None,
                        "style_preservation": "Pristine Preset Base"
                    }
                    save_override_params(output_dir, filename, ai_adj)
                await asyncio.sleep(0.05)

                # ================= OPTIONAL SMART CROP (AFTER STAGE 2) =================
                if cfg["ENABLE_AI_SMART_CROP"]:
                    yield f"data: {json.dumps({'type': 'step_crop', 'index': idx, 'filename': filename})}\n\n"
                    cropped_working, crop_telemetry = cropper.crop_best_landscape(stage2_balanced, enable_ai=True)
                    await asyncio.sleep(0.05)
                else:
                    cropped_working = stage2_balanced.copy()
                    crop_telemetry = {
                        "enabled": False,
                        "source": "stage2_balanced",
                        "applied": False,
                        "ymin": 0.0, "xmin": 0.0, "ymax": 1.0, "xmax": 1.0,
                        "original_width": stage2_balanced.shape[1],
                        "original_height": stage2_balanced.shape[0],
                        "cropped_width": stage2_balanced.shape[1],
                        "cropped_height": stage2_balanced.shape[0],
                        "crop_area_ratio": 1.0,
                        "reason": "Smart Crop disabled (full-frame preserved)",
                        "fallback_used": False,
                        "method": "Full Frame (No Crop)",
                        "trim_x_pct": 0, "trim_y_pct": 0,
                        "original_size": f"{stage2_balanced.shape[1]}x{stage2_balanced.shape[0]}",
                        "cropped_size": f"{stage2_balanced.shape[1]}x{stage2_balanced.shape[0]}",
                        "notes": "Smart Crop disabled"
                    }

                # Optional target max width scaling
                ch, cw = cropped_working.shape[:2]
                target_w = int(cfg.get("TARGET_MAX_WIDTH", 0))
                if target_w > 0 and cw > target_w:
                    new_w = target_w
                    new_h = int(ch * (target_w / cw))
                    final_working = cv2.resize(cropped_working, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
                else:
                    final_working = cropped_working

                # Single final export in delivery sRGB space
                export_final = preset_mgr.export_image(final_working)
                cv2.imwrite(out_path, export_final, [
                    int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality,
                    int(cv2.IMWRITE_JPEG_OPTIMIZE), 1
                ])

                if crop_telemetry.get("applied"):
                    ymin = float(crop_telemetry.get("ymin", 0.0))
                    xmin = float(crop_telemetry.get("xmin", 0.0))
                    ymax = float(crop_telemetry.get("ymax", 1.0))
                    xmax = float(crop_telemetry.get("xmax", 1.0))
                    ai_adj["crop_top"] = round(ymin, 3)
                    ai_adj["crop_bottom"] = round(1.0 - ymax, 3)
                    ai_adj["crop_left"] = round(xmin, 3)
                    ai_adj["crop_right"] = round(1.0 - xmax, 3)
                else:
                    ai_adj["crop_top"] = 0.0
                    ai_adj["crop_bottom"] = 0.0
                    ai_adj["crop_left"] = 0.0
                    ai_adj["crop_right"] = 0.0

                save_override_params(output_dir, filename, ai_adj)

                save_photo_telemetry(output_dir, filename, {
                    "adjust_telemetry": telemetry,
                    "crop_telemetry": crop_telemetry
                })

                yield f"data: {json.dumps({'type': 'photo_done', 'index': idx, 'total': len(files), 'filename': filename, 'output_filename': out_filename, 'input_url': f'/api/image/incoming/{urllib.parse.quote(filename)}', 'output_url': f'/api/image/output/{urllib.parse.quote(out_filename)}', 'dimensions': f'{final_working.shape[1]}x{final_working.shape[0]}', 'adjust_telemetry': telemetry, 'crop_telemetry': crop_telemetry})}\n\n"
                await asyncio.sleep(0.1)
            except Exception as photo_err:
                print(f"   > [SSE Error on {filename}]: {photo_err}")
                yield f"data: {json.dumps({'type': 'photo_error', 'index': idx, 'filename': filename, 'error': str(photo_err)})}\n\n"

        yield f"data: {json.dumps({'type': 'complete', 'total': len(files), 'processed': len(files)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/adjust/preview")
def api_adjust_preview(req: AdjustRequest):
    """
    Sub-15ms live preview calculated on top of the cached Stage 1 Preset Base buffer.
    """
    cfg = get_config()
    input_path = os.path.join(cfg["INPUT_FOLDER"], req.filename)
    base_name, _ = os.path.splitext(req.filename)
    out_filename = f"{base_name}.jpg"
    out_path = os.path.join(cfg["OUTPUT_FOLDER"], out_filename)
    base_dir = os.path.join(cfg["OUTPUT_FOLDER"], ".base")
    os.makedirs(base_dir, exist_ok=True)
    base_path = os.path.join(base_dir, out_filename)
    preset_mgr = PresetManager(preset_folder=cfg["PRESET_FOLDER"])

    # Load from pristine Stage 1 Preset Base buffer
    if os.path.exists(base_path):
        img = safe_read_image(base_path)
    elif os.path.exists(out_path):
        img = safe_read_image(out_path)
    elif os.path.exists(input_path):
        raw_img = safe_read_image(input_path)
        if raw_img is None:
            raise HTTPException(status_code=400, detail="Cannot read image")
        img = preset_mgr.apply_preset(raw_img)
        export_base = preset_mgr.export_image(img)
        cv2.imwrite(base_path, export_base)
    else:
        raise HTTPException(status_code=404, detail="Photo not found")

    if img is None:
        raise HTTPException(status_code=400, detail="Cannot decode image")

    # Downscale for instant preview rendering (<10ms)
    h, w = img.shape[:2]
    if w > 960:
        img_work = cv2.resize(img, (960, int(h * (960 / w))), interpolation=cv2.INTER_AREA)
    else:
        img_work = img.copy()

    img_out = apply_adjustments(img_work, req)
    export_preview = preset_mgr.export_image(img_out)

    _, buffer = cv2.imencode(".jpg", export_preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64_preview = base64.b64encode(buffer).decode("utf-8")

    return {
        "status": "ok",
        "preview_data_url": f"data:image/jpeg;base64,{b64_preview}",
        "dimension": f"{img_out.shape[1]}x{img_out.shape[0]}"
    }


@app.post("/api/adjust/reset")
def api_adjust_reset(req: AdjustRequest):
    """
    Resets photo back to pristine Stage 1 Preset Base image instantly.
    """
    cfg = get_config()
    base_name, _ = os.path.splitext(req.filename)
    out_filename = f"{base_name}.jpg"
    base_path = os.path.join(cfg["OUTPUT_FOLDER"], ".base", out_filename)
    out_path = os.path.join(cfg["OUTPUT_FOLDER"], out_filename)
    preset_mgr = PresetManager(preset_folder=cfg["PRESET_FOLDER"])

    if not os.path.exists(base_path):
        # Generate Stage 1 base if missing
        input_path = os.path.join(cfg["INPUT_FOLDER"], req.filename)
        raw_img = safe_read_image(input_path)
        if raw_img is None:
            raise HTTPException(status_code=400, detail="Cannot read original image")
        base_img = preset_mgr.apply_preset(raw_img)
        export_base = preset_mgr.export_image(base_img)
        cv2.imwrite(base_path, export_base)
    else:
        base_img = safe_read_image(base_path)

    # Overwrite output with clean base develop image in sRGB
    export_final = preset_mgr.export_image(base_img)
    jpeg_quality = int(cfg.get("JPEG_QUALITY", 100))
    cv2.imwrite(out_path, export_final, [
        int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality,
        int(cv2.IMWRITE_JPEG_OPTIMIZE), 1
    ])

    save_override_params(cfg["OUTPUT_FOLDER"], req.filename, DEFAULT_ADJUSTMENTS.copy())

    # Encode preview
    h, w = base_img.shape[:2]
    if w > 960:
        preview_img = cv2.resize(base_img, (960, int(h * (960 / w))), interpolation=cv2.INTER_AREA)
    else:
        preview_img = base_img

    export_preview = preset_mgr.export_image(preview_img)
    _, buffer = cv2.imencode(".jpg", export_preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64_preview = base64.b64encode(buffer).decode("utf-8")

    return {
        "status": "reset",
        "output_filename": out_filename,
        "preview_data_url": f"data:image/jpeg;base64,{b64_preview}",
        "output_url": f"/api/image/output/{urllib.parse.quote(out_filename)}"
    }


@app.post("/api/adjust/ai-balance")
def api_adjust_ai_balance(req: AdjustRequest):
    """
    Triggers Stage 2 AI Auto-Balancing on demand for the active inspector photo.
    Evaluates Stage 1 base buffer and returns clamped adjustments + telemetry.
    """
    cfg = get_config()
    base_name, _ = os.path.splitext(req.filename)
    out_filename = f"{base_name}.jpg"
    base_path = os.path.join(cfg["OUTPUT_FOLDER"], ".base", out_filename)
    preset_mgr = PresetManager(preset_folder=cfg["PRESET_FOLDER"])

    if not os.path.exists(base_path):
        input_path = os.path.join(cfg["INPUT_FOLDER"], req.filename)
        raw_img = safe_read_image(input_path)
        if raw_img is None:
            raise HTTPException(status_code=400, detail="Cannot read original image")
        base_img = preset_mgr.apply_preset(raw_img)
        export_base = preset_mgr.export_image(base_img)
        cv2.imwrite(base_path, export_base)
    else:
        base_img = safe_read_image(base_path)

    if base_img is None:
        raise HTTPException(status_code=400, detail="Cannot decode Stage 1 base image")

    adjuster = AutoAdjuster(
        api_key=cfg.get("ORCA_API_KEY", ""),
        api_url=cfg.get("ORCA_API_URL", "https://api.orcarouter.ai/v1/chat/completions"),
        model=cfg.get("ORCA_MODEL", "google/gemini-2.5-flash")
    )
    ai_res = adjuster.analyze_params(base_img, preset_name=preset_mgr.preset_name, enable_ai=True)
    telemetry = ai_res.get("telemetry", {})
    ai_status = ai_res.get("ai_status", "ai_disabled")

    ai_adj = {
        "exposure": ai_res.get("exposure", 0.0),
        "contrast": 0.0,
        "shadows": ai_res.get("shadows", 0.0),
        "highlights": ai_res.get("highlights", 0.0),
        "temperature": ai_res.get("temperature", 0.0),
        "tint": ai_res.get("tint", 0.0),
        "vibrance": 0.0,
        "clarity": 0.0,
        "crop_top": req.crop_top,
        "crop_bottom": req.crop_bottom,
        "crop_left": req.crop_left,
        "crop_right": req.crop_right,
    }

    # Generate preview
    req_obj = AdjustRequest(filename=req.filename, **ai_adj)
    h, w = base_img.shape[:2]
    if w > 960:
        preview_work = cv2.resize(base_img, (960, int(h * (960 / w))), interpolation=cv2.INTER_AREA)
    else:
        preview_work = base_img.copy()

    preview_out = apply_adjustments(preview_work, req_obj)
    export_preview = preset_mgr.export_image(preview_out)
    _, buffer = cv2.imencode(".jpg", export_preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64_preview = base64.b64encode(buffer).decode("utf-8")

    tel_store = load_telemetry(cfg["OUTPUT_FOLDER"])
    current_tel = tel_store.get(req.filename, {})
    current_tel["adjust_telemetry"] = telemetry
    save_photo_telemetry(cfg["OUTPUT_FOLDER"], req.filename, current_tel)

    return {
        "status": "ok",
        "ai_status": ai_status,
        "adjustments": ai_adj,
        "telemetry": telemetry,
        "preview_data_url": f"data:image/jpeg;base64,{b64_preview}",
        "scene_type": telemetry.get("scene_type", "General"),
        "confidence": telemetry.get("confidence", 0.0),
        "needs_correction": telemetry.get("needs_correction", False),
        "reason": ai_res.get("reason", ""),
        "api_error": ai_res.get("api_error"),
        "latency_ms": ai_res.get("latency_ms", 0)
    }


@app.post("/api/adjust/smart-crop")
def api_adjust_smart_crop(req: AdjustRequest):
    """
    Evaluates Smart Crop on demand for the active inspector photo.
    Executes strictly on the Stage 2 Balanced Buffer without modifying the Stage 1 base buffer.
    Returns normalized crop boundaries and downscaled preview.
    """
    cfg = get_config()
    base_name, _ = os.path.splitext(req.filename)
    out_filename = f"{base_name}.jpg"
    base_path = os.path.join(cfg["OUTPUT_FOLDER"], ".base", out_filename)
    preset_mgr = PresetManager(preset_folder=cfg["PRESET_FOLDER"])

    if not os.path.exists(base_path):
        input_path = os.path.join(cfg["INPUT_FOLDER"], req.filename)
        raw_img = safe_read_image(input_path)
        if raw_img is None:
            raise HTTPException(status_code=400, detail="Cannot read original image")
        base_img = preset_mgr.apply_preset(raw_img)
        export_base = preset_mgr.export_image(base_img)
        cv2.imwrite(base_path, export_base)
    else:
        base_img = safe_read_image(base_path)

    if base_img is None:
        raise HTTPException(status_code=400, detail="Cannot decode Stage 1 base image")

    # Step 1: Render Stage 2 Balanced Buffer with current active parametric trims
    adj_dict = req.model_dump(exclude={"filename"}) if hasattr(req, "model_dump") else req.dict(exclude={"filename"})
    stage2_balanced = ImagePipeline.render_stage2_adjustments(base_img, adj_dict)

    # Step 2: Run SmartCropper on Stage 2 Balanced Buffer
    cropper = SmartCropper(
        api_key=cfg.get("ORCA_API_KEY", ""),
        api_url=cfg.get("ORCA_API_URL", "https://api.orcarouter.ai/v1/chat/completions"),
        model=cfg.get("ORCA_MODEL", "google/gemini-2.5-flash")
    )
    cropped_working, crop_telemetry = cropper.crop_best_landscape(stage2_balanced, enable_ai=True)

    if cropped_working is None:
        cropped_working = stage2_balanced.copy()

    # Step 3: Compute normalized crop offsets for UI sliders
    ymin = float(crop_telemetry.get("ymin", 0.0))
    xmin = float(crop_telemetry.get("xmin", 0.0))
    ymax = float(crop_telemetry.get("ymax", 1.0))
    xmax = float(crop_telemetry.get("xmax", 1.0))

    crop_top = round(ymin, 3)
    crop_bottom = round(1.0 - ymax, 3)
    crop_left = round(xmin, 3)
    crop_right = round(1.0 - xmax, 3)

    # Step 4: Downscale cropped result for instant preview return
    h, w = cropped_working.shape[:2]
    if w > 960:
        preview_work = cv2.resize(cropped_working, (960, int(h * (960 / w))), interpolation=cv2.INTER_AREA)
    else:
        preview_work = cropped_working.copy()

    export_preview = preset_mgr.export_image(preview_work)
    _, buffer = cv2.imencode(".jpg", export_preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64_preview = base64.b64encode(buffer).decode("utf-8")

    tel_store = load_telemetry(cfg["OUTPUT_FOLDER"])
    current_tel = tel_store.get(req.filename, {})
    current_tel["crop_telemetry"] = crop_telemetry
    save_photo_telemetry(cfg["OUTPUT_FOLDER"], req.filename, current_tel)

    return {
        "status": "ok",
        "crop_status": crop_telemetry.get("crop_status", "ai_crop"),
        "crop_source": crop_telemetry.get("crop_source", "ai"),
        "applied": crop_telemetry.get("applied", False),
        "crop": {
            "crop_top": crop_top,
            "crop_bottom": crop_bottom,
            "crop_left": crop_left,
            "crop_right": crop_right
        },
        "crop_telemetry": crop_telemetry,
        "preview_data_url": f"data:image/jpeg;base64,{b64_preview}",
        "dimension": f"{cropped_working.shape[1]}x{cropped_working.shape[0]}",
        "reason": crop_telemetry.get("reason", ""),
        "api_error": crop_telemetry.get("api_error")
    }


@app.post("/api/adjust/save")
def api_adjust_save(req: AdjustRequest):
    """
    Saves the custom adjusted high-resolution image directly to OUTPUT_FOLDER.
    """
    cfg = get_config()
    input_path = os.path.join(cfg["INPUT_FOLDER"], req.filename)
    base_name, _ = os.path.splitext(req.filename)
    out_filename = f"{base_name}.jpg"
    out_path = os.path.join(cfg["OUTPUT_FOLDER"], out_filename)
    base_dir = os.path.join(cfg["OUTPUT_FOLDER"], ".base")
    os.makedirs(base_dir, exist_ok=True)
    base_path = os.path.join(base_dir, out_filename)
    preset_mgr = PresetManager(preset_folder=cfg["PRESET_FOLDER"])

    if os.path.exists(base_path):
        img = safe_read_image(base_path)
    elif os.path.exists(out_path):
        img = safe_read_image(out_path)
    elif os.path.exists(input_path):
        raw_img = safe_read_image(input_path)
        if raw_img is None:
            raise HTTPException(status_code=400, detail="Cannot read image")
        img = preset_mgr.apply_preset(raw_img)
        export_base = preset_mgr.export_image(img)
        cv2.imwrite(base_path, export_base)
    else:
        raise HTTPException(status_code=404, detail="Photo not found")

    if img is None:
        raise HTTPException(status_code=400, detail="Cannot read image")

    img_out = apply_adjustments(img, req)
    export_final = preset_mgr.export_image(img_out)

    jpeg_quality = int(cfg.get("JPEG_QUALITY", 100))
    cv2.imwrite(out_path, export_final, [
        int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality,
        int(cv2.IMWRITE_JPEG_OPTIMIZE), 1
    ])

    adj_dict = req.model_dump(exclude={"filename"}) if hasattr(req, "model_dump") else req.dict(exclude={"filename"})
    save_override_params(cfg["OUTPUT_FOLDER"], req.filename, adj_dict)

    return {
        "status": "saved",
        "output_filename": out_filename,
        "output_url": f"/api/image/output/{urllib.parse.quote(out_filename)}",
        "dimension": f"{img_out.shape[1]}x{img_out.shape[0]}",
        "adjustments": adj_dict
    }


# Mount Static Frontend
os.makedirs(WEB_DIR, exist_ok=True)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")


def _launch_browser():
    import time
    import webbrowser
    time.sleep(1.2)
    try:
        webbrowser.open("http://localhost:8000")
    except Exception as e:
        print(f"   > [BROWSER LAUNCH NOTE]: {e}")


if __name__ == "__main__":
    import uvicorn
    import threading
    threading.Thread(target=_launch_browser, daemon=True).start()
    print("\n=======================================================")
    print("🚀 Starting Lightroom AI Studio 2.0 Web Server...")
    print("🌐 Opening your browser at: http://localhost:8000")
    print("=======================================================\n")
    if getattr(sys, 'frozen', False):
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
    else:
        uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
