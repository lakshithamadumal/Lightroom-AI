# 📸 Lightroom AI • Web Studio Edition

<p align="center">
  <img src="web/logo.svg" alt="Lightroom AI Logo" width="280" />
</p>

<p align="center">
  <strong>Automated Batch Photo Processing Studio powered by 3D Hald LUTs & Multimodal Vision AI</strong>
</p>

<p align="center">
  <a href="https://github.com/lakshithamadumal/Lightroom-AI/stargazers"><img src="https://img.shields.io/github/stars/lakshithamadumal/Lightroom-AI?color=FF385C&style=for-the-badge" alt="Stars"></a>
  <a href="https://github.com/lakshithamadumal/Lightroom-AI/network/members"><img src="https://img.shields.io/github/forks/lakshithamadumal/Lightroom-AI?color=008489&style=for-the-badge" alt="Forks"></a>
  <a href="https://github.com/lakshithamadumal/Lightroom-AI/issues"><img src="https://img.shields.io/github/issues/lakshithamadumal/Lightroom-AI?color=FC642D&style=for-the-badge" alt="Issues"></a>
  <a href="https://github.com/lakshithamadumal/Lightroom-AI/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-black?style=for-the-badge" alt="License"></a>
</p>

---

## 🌟 Overview

**Lightroom AI** is a professional-grade web studio designed for media teams, event photographers, and content creators. It bridges the gap between **100% exact Adobe Lightroom color grading** and **autonomous AI-driven post-processing**.

Crafted in an authentic **Airbnb Design Language System (DLS)** Light Mode interface, it enables real-time SSE batch pipeline processing, style-preserving dynamic auto-balancing, and intelligent Rule-of-Thirds composition cropping.

---

## ✨ Key Features

- 🎨 **100% Exact Adobe Lightroom Engine (3D Hald LUT)**
  - Direct 3D RGB color cube mapping with zero color drift or approximation.
  - Supports Adobe Lightroom presets exported via standard 8-level Hald CLUT charts (`.png`, `.jpg`, `.tif`, `.dng`, `.xmp`).
- ⚖️ **Style-Preserving Auto Balancing**
  - Evaluates luminance exclusively in $L^*$ space while locking chromatic ratios ($a^*$ and $b^*$).
  - Preserves artistic mood, saturation curves, and skin tones without blowout.
- 📐 **Smart Landscape AI Cropping**
  - Powered by **OrcaRouter Multimodal Vision** (`fusion-flash`, `gemini-2.5-flash`, `gpt-4o`).
  - Automatically eliminates dead ceiling headroom (12-13%) and peripheral distractions while enforcing Rule of Thirds.
- ⚡ **Real-time Server-Sent Events (SSE) Streaming**
  - Live 4-step progress timeline: `3D LUT Graded ── Auto Balance ── Smart Crop ── Master Export`.
  - Non-blocking Start / Stop controls with instantaneous abort capability.
- 🔍 **Interactive Single-Photo Inspector & Split Comparison**
  - Interactive Before/After slider.
  - Live fine-tuning sliders: Exposure (EV), Contrast, Shadows Lift, Highlights Recovery, Temperature, Vibrance, Clarity, and Crop Trimming.
- 📁 **Native Windows Folder & LUT File Picker**
  - Direct native OS dialogs to browse incoming, output, or preset paths.

---

## 🛠️ Tech Stack

- **Backend:** Python 3.10+, FastAPI, Uvicorn, OpenCV (`cv2`), NumPy, SciPy (Pchip Monotonic Cubic Splines)
- **Frontend:** Vanilla JS, HTML5, Tailwind CSS (Airbnb DLS Palette), Lucide Icons, Canvas Confetti, Web Audio API
- **AI Vision Engine:** [OrcaRouter](https://www.orcarouter.ai/) Multimodal Gateway (`fusion-flash`, `fusion-pro`, `gemini-2.5-flash`, `gpt-4o`, `claude-3-5-sonnet`)

---

## 🚀 Quick Start Guide

### 1. Clone the Repository
```bash
git clone https://github.com/lakshithamadumal/Lightroom-AI.git
cd Lightroom-AI
```

### 2. Set Up Virtual Environment & Dependencies
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 3. Launch the Studio
```bash
python server.py
```
*(Or double-click `start_ui.bat` on Windows)*

Open your browser at: **`http://localhost:8000`**

---

## 📖 How It Works

### Step 1: Obtain OrcaRouter Vision API Key
1. Visit **[orcarouter.ai/console/token](https://www.orcarouter.ai/console/token)** and sign in with GitHub.
2. Generate your access token (`sk-orca-...`).
3. In the Lightroom AI web UI, open **Settings (⚙️)**, paste your token, and click **Save Settings**.

### Step 2: Create a 100% Adobe Lightroom 3D LUT
1. Click **"How it Works"** in the top navigation bar and click **"Download LUT Base"** (or download `web/neutral_lut.png`).
2. Import `neutral_lut.png` into **Adobe Lightroom Classic** or **Lightroom CC**.
3. Apply your desired Lightroom preset (Tone Curve, Colors, HSL, Exposure, Vibrance).
4. Export the image as a **JPG or PNG (100% Quality, sRGB, 512×512)**.
5. Place the exported file into `C:/Media_Presets` (or click **"Pick File"** in Settings to select it directly).

### Step 3: Run the Automation Pipeline
1. Place unedited raw photos in `C:/Media_Incoming`.
2. Toggle your preferences in Settings:
   - **AI Smart Landscape Crop** (Default: `ON`)
   - **Auto Balancing & Luminance** (Default: `ON`)
3. Click **"Start"** in the top capsule control bar.
4. Processed master photographs will be saved to `C:/Media_Output`.

---

## ⚙️ Configuration (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ORCA_API_KEY` | `""` | OrcaRouter Vision API key |
| `ORCA_MODEL` | `fusion-flash` | Default Vision Model |
| `INPUT_FOLDER` | `C:/Media_Incoming` | Source folder for incoming photos |
| `PRESET_FOLDER` | `C:/Media_Presets` | Folder or direct path for 3D LUT preset |
| `OUTPUT_FOLDER` | `C:/Media_Output` | Destination directory for master exports |
| `ENABLE_AI_SMART_CROP` | `true` | Enables AI landscape composition cropping |
| `ENABLE_AUTO_BALANCING`| `true` | Enables dynamic luminance auto-balancing |
| `TARGET_MAX_WIDTH` | `1920` | Maximum pixel width for exported masters |

---

## 👨‍💻 Developer & Author

**Developed with ❤️ by Lakshitha**

- 🌐 **Portfolio:** [https://lakshitha-murex.vercel.app/](https://lakshitha-murex.vercel.app/)
- 🐙 **GitHub:** [@lakshithamadumal](https://github.com/lakshithamadumal)

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.