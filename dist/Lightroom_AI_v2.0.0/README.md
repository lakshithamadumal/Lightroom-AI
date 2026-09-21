# 📸 Lightroom AI Studio

<p align="center">
  <img src="web/logo.svg" alt="Lightroom AI Logo" width="260" />
</p>

<p align="center">
  <strong>Automated Batch Photo Processing Studio powered by 3D Color LUTs & Vision AI (Groq + Qwen 27B)</strong>
</p>

---

## What it is

**Lightroom AI Studio Edition 2.0 (v2.0.0)** is an automated photo grading and batch-processing web application designed for professional photography workflows. It combines a 100% exact mathematical 64³ 3D Color Engine (Adobe RGB 1998) with multimodal Vision AI for style-preserving exposure auto-balancing and Rule-of-Thirds composition cropping.

---

## Quick Start

### 1. Installation
```bash
# Clone repository
git clone https://github.com/lakshithamadumal/Lightroom-AI.git
cd Lightroom-AI

# Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Launch
* **On Windows:** Double-click `start_ui.bat`
* **Or run:**
```bash
python server.py
```
Open your browser at **`http://localhost:8000`**.

### 3. Process Photos
1. Place unedited photos (`.jpg`, `.png`, `.tif`, `.dng`) in `C:/Media_Incoming`.
2. Click **Start** in the web studio to batch process.
3. Master exports will be saved in `C:/Media_Output`.

---

## Presets

Lightroom AI comes pre-calibrated with a built-in **64³ 3D Studio Preset** (`calibration/preset.cube`) that replicates a calibrated develop look in wide-gamut Adobe RGB (1998) color space. No initial setup is required.

---

## Custom Preset Workflow

To compile and install your own Lightroom preset as the Master Studio Preset:

1. **Download Base HALD:** Click **How it Works** in the UI to download `neutral_lut.png` (512×512 Level 8 identity HALD).
2. **Open in Adobe Lightroom:** Import `neutral_lut.png` into **Adobe Lightroom Classic** or **Lightroom CC**.
3. **Apply Your Develop Preset:** Apply your desired color grading, tone curves, shadows, and highlights.
4. **Export:** Export the image as a **100% Quality PNG or TIFF/JPEG** (512×512, sRGB or Adobe RGB).
5. **Pick File in Lightroom AI:** In **Settings (⚙️)**, click **Pick File** and select your exported HALD image.
6. **Automatic Compilation:** The backend automatically validates the HALD, compiles it into a 64³ Float32 3D LUT, and installs it into `calibration/` as the active Master Studio Preset.
7. **Production Ready:** Stage 1 automatically applies the new Master Preset to incoming photos with full Stage 2 AI, Smart Crop, and sRGB export capabilities.

---

## AI Auto-Balance

* **Provider:** Groq Cloud
* **Model:** `qwen/qwen3.8-27b`
* **API Key:** Free API key from [console.groq.com/keys](https://console.groq.com/keys) (`gsk_...`).

Stage 2 Vision AI analyzes scene lighting (portraits, landscapes, high-key, low-light) and applies micro-trims to exposure and shadows ($\le 2.0\ \Delta E$) while strictly preserving the signature look and chromatic balance of the preset.

---

## Smart Crop

* **Composition:** Automatically crops dead ceiling headroom and enforces Rule-of-Thirds framing.
* **Face Safety Gate:** Detects human subjects to guarantee faces, chins, and ears are never clipped.
* **Full-Frame Fail-Safe:** If an image is already well-framed or a crop would cut too much area ($<40\%$), full frame is preserved.

---

## Output

* **Master Export:** Delivered as 100% quality sRGB JPEGs with full camera resolution and EXIF orientation preserved.
* **Inspector & Split Slider:** Click **Inspect & Fine-Tune** on any photo card to compare Before/After with a live split slider and fine-tune exposure, temperature, tint, shadows, highlights, or crop margins.

---

## Requirements

* **OS:** Windows 10/11 (64-bit), macOS 12+, or Linux.
* **Python:** Python 3.10, 3.11, 3.12, or 3.13.
* **Browser:** Chrome, Edge, Brave, Firefox, Safari.
* **Offline Operation:** The core preset engine runs 100% offline without internet. (Internet is only used if Vision AI features are enabled).

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.