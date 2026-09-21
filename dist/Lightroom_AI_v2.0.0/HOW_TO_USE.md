# Lightroom AI Studio Edition 2.0 — Photographer's User Guide

Welcome to **Lightroom AI Studio Edition 2.0**! This guide is written for photographers of all experience levels to get you up and running in minutes.

---

## 1. What is Lightroom AI Studio?

Lightroom AI Studio is an automated, high-fidelity color grading and batch processing application designed for professional photography workflows.

It works in three streamlined stages:
1. **Stage 1 (Exact Studio Preset):** Instantly color-grades your photos using a high-precision 64³ 3D Color Engine that mathematically replicates the exact tone curves, color palette, and highlight-priority lens vignetting of professional Adobe Lightroom Develop profiles.
2. **Stage 2 (AI Auto-Balance):** An intelligent vision model (powered by Groq / Qwen 27B Vision) inspects each photo, detects scene context (portraits, landscapes, low-light, high-key skies), and applies subtle micro-trims to exposure and white balance while strictly preserving the signature look of the preset.
3. **Smart Crop:** Intelligently centers subjects, applies rule-of-thirds composition, and protects faces and edges from accidental cuts.

---

## 2. System Requirements

* **Operating System:** Windows 10 or Windows 11 (64-bit), macOS 12+, or Linux.
* **Python:** Python 3.10, 3.11, 3.12, or 3.13 installed on your machine.
* **RAM:** 4 GB minimum (8 GB+ recommended for high-resolution 40MP+ RAW/JPEG photos).
* **Browser:** Any modern browser (Google Chrome, Microsoft Edge, Brave, Firefox, Safari).
* **Internet Connection:** Optional. (Required only if you wish to use AI Vision features; the core Stage 1 preset engine works **100% offline** with zero internet needed).

---

## 3. Installation & Setup

1. **Extract the Package:**  
   Download and unzip `Lightroom_AI_Studio_v2.0.0.zip` to any folder on your computer (e.g. `C:\Lightroom_AI` or `~/Lightroom_AI`).
2. **Install Required Packages (One-Time Setup):**  
   Open a terminal or command prompt in the folder and run:
   ```bash
   pip install -r requirements.txt
   ```

> [!IMPORTANT]
> **Do I need to install or import any .cube, .dng, .tif, or .xmp files?**  
> **NO.** Lightroom AI Studio comes **100% pre-calibrated out of the box**. The master studio preset is already built into the engine. You do NOT need to touch or import any technical LUT or calibration files to start grading photos immediately.

---

## 4. How to Start the Application

* **On Windows:** Simply double-click `start_ui.bat`.
* **On macOS / Linux / Terminal:** Run:
  ```bash
  python server.py
  ```
Your web browser will automatically open to `http://127.0.0.1:8000`.

---

## 5. How to Grade Your Photos (Step-by-Step Workflow)

### Step 1: Place Photos in Your Incoming Folder
By default, Lightroom AI looks for photos in `C:/Media_Incoming` (or your chosen folder):
* Drop your unedited photos (`.jpg`, `.jpeg`, `.png`, `.tif`) into the incoming folder.
* Click **Refresh** in the top navigation bar. Your photos will appear in the gallery ready to process.

### Step 2: (Optional) Configure Settings
Click the **Settings (⚙️)** button in the top right to configure:
* **Workspace Folders:** Change your Incoming, Output, or Preset folder paths using the built-in **Browse** button.
* **Export Resolution:** Choose **Original (100% Full Res)** for master camera resolution, or pick **4K**, **2K**, or **1080p**.
* **JPEG Quality:** Choose **100% Studio Max** for lossless quality, or **98% High Quality**.
* **AI Vision API Key:** Enter your free Groq API key (`gsk_...`) to enable Stage 2 AI Auto-Balancing and AI Smart Crop.

### Step 3: Click "Start"
Click the **"Start"** button in the top capsule. The batch engine will grade every photo automatically. You will see live progress indicators for every processing step.

---

## 6. Understanding AI Features & Safety Controls

### AI Auto-Balance (Stage 2)
The AI vision engine checks each photo to ensure exposure and white balance are optimal.
* If a scene is already well-balanced, it leaves it alone (**Optimal / No-Op**), protecting the pristine preset look.
* If an underexposed shadow or color cast is detected, it applies a subtle trim within strict safety limits ($\le 2.0\ \Delta E$).
* **Locked Tone Controls:** Saturation, Vibrance, and Base Contrast remain locked to prevent cartoonish or unnatural over-processing.

### Smart Crop
Smart Crop analyzes composition:
* Tightens wide shots using golden ratio and rule-of-thirds framing.
* **Face Safety Gate:** Automatically detects human faces and ensures ears, chins, and foreheads are never cut off.
* If a crop would cut too much of the image ($<40\%$ area), the safety gate rejects the crop and preserves the **Full Frame**.

---

## 7. Using the Single Photo Inspector

Click **"Inspect & Fine-Tune"** on any processed photo card to open the **Inspector Modal**.

### Features in Inspector:
1. **Side-by-Side & Split Comparison:** Drag the vertical divider left or right to see a real-time before-and-after split comparison.
2. **View Exact AI Values:** See the exact numerical trims chosen by the AI (e.g., Shadows `+4`, Exposure `-0.03`, Temperature `+0.9`).
3. **Manual Fine-Tuning:** Use the parametric sliders to tweak exposure, temperature, tint, shadows, highlights, or crop margins.
4. **Instant Live Preview:** Sliders update the preview in real-time as you drag.
5. **Save Overrides:** Click **"Save Overrides"** to apply your custom adjustments and instantly update the master export.

---

## 8. The Three Independent Reset Buttons

In the Inspector, you have complete control over resets:

* **Reset AI Balance:**
  * Sets all AI tone adjustments back to zero.
  * **Preserves your crop framing** unchanged.
* **Reset Crop:**
  * Returns crop margins to 100% Full Frame.
  * **Preserves your AI tone balance** unchanged.
* **Reset All to Stage 1 Preset Base:**
  * Resets all sliders and crop margins to zero.
  * Instantly restores the pure, pristine Stage 1 studio preset look.

---

## 9. Where Are Exported Images Saved?

* All master exported images are automatically saved in your configured **Export Output Folder** (default: `C:/Media_Output`).
* Each master image is saved as a high-resolution, color-managed sRGB JPEG with full EXIF orientation preserved.
* You can also click the **"Download Master"** button on any photo card to download the photo directly through your web browser.

---

## 10. What Happens if AI is Offline or Rate-Limited?

Lightroom AI Studio features **100% Fail-Safe Architecture**:
* If you have no internet, have no API key, or hit free-tier rate limits, the application **never crashes, stalls, or corrupts your photos**.
* It automatically enters **AI Offline / Preset Base Mode**: your photos still receive the 100% exact mathematical Stage 1 studio color grade and export with full resolution and pristine quality.

---

## 11. Troubleshooting & Quick FAQ

| Issue | Solution |
| :--- | :--- |
| **"No photos found" in gallery** | Check that your incoming folder path in Settings matches where your photos are saved, and click **Refresh Incoming Folder**. |
| **Port 8000 is already in use** | Set `PORT=8080` before starting, or run `python server.py --port 8080`. |
| **Top capsule shows "AI Offline"** | AI Vision is optional. If you want AI auto-balancing, paste your Groq API key into Settings (⚙️) and click Save. |
| **I want full camera resolution** | In Settings $\rightarrow$ Export Resolution, select **Original (100% Full Res)**. |
| **Are my original raw files modified?** | **Never.** Lightroom AI is 100% non-destructive. Your original files in the incoming folder are never altered or overwritten. |
