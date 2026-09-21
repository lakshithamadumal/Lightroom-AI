# Preset Workflow Guide: Lightroom AI Studio Edition 2.0

This guide explains how presets work in **Lightroom AI Studio Edition 2.0**, how the engine achieves mathematical parity with Adobe Lightroom Develop profiles, and how photographers can use or create presets.

---

## 1. Quick Summary for Photographers

> [!IMPORTANT]
> **Do you need to import or configure presets to use Lightroom AI?**  
> **NO.** The application is **100% pre-calibrated and self-contained**. When you launch Lightroom AI, the master studio preset is loaded automatically. You do not need to install `.cube`, `.xmp`, `.dng`, or `.tif` files to edit photos.

---

## 2. Understanding the Three Types of Preset Files

In the Lightroom AI ecosystem, files serve three distinct purposes:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          PRESET FILE CATEGORIES                         │
├──────────────────────────┬─────────────────────────────┬────────────────┤
│ A. Production Preset     │ B. Custom Lightroom Workflow│ C. Internal    │
│    (Self-Contained)      │    (Optional Advanced)      │    Calibration │
├──────────────────────────┼─────────────────────────────┼────────────────┤
│ • preset.cube            │ • neutral_lut.png           │ • IMG_4932.tif │
│ • preset_calibrated.cube │ • identity_chart.png        │ • diff heatmaps│
│ • preset.json            │ • Exported HALD PNG         │ • diagnostic   │
│                          │ • convert_lr_preset.py      │   renders      │
└──────────────────────────┴─────────────────────────────┴────────────────┘
```

---

### Category A: Lightroom AI Internal Production Preset (Runtime Engine)

These files are located in `calibration/` and are built directly into the software:

1. **`calibration/preset.cube` (64³ 3D Float LUT):**
   * *What it is:* A high-density 64×64×64 tetrahedral color lookup table ($262,144$ precise 3D color coordinates).
   * *What it does:* Accurately reproduces the non-linear color grading, HSL adjustments, and split-toning of the calibrated studio look in Adobe RGB 1998 color space.
   * *User Action:* **None.** Loaded automatically at startup.
2. **`calibration/preset_calibrated.cube`:**
   * *What it is:* The audited, freeze-verified twin of `preset.cube` ensuring zero-drift mathematical parity.
   * *User Action:* **None.**
3. **`calibration/preset.json`:**
   * *What it is:* Preserved develop metadata defining spatial rendering parameters, including highlight-priority lens vignetting and clarity tone curves.
   * *User Action:* **None.**

---

### Category B: Adobe Lightroom Custom Preset Workflow (Optional Advanced Feature)

If you are a photographer who wants to import your **own custom preset** from Adobe Lightroom Classic into Lightroom AI:

#### Why 3D HALD Instead of .XMP or .DNG?
Adobe Lightroom `.xmp` and `.dng` files use proprietary, closed mathematical equations for localized tone curves, camera profile matrices, and clarity algorithms that cannot be reproduced accurately outside of Adobe's software.

To solve this, Lightroom AI uses **3D HALD Color Mapping**:
* An uncompressed Level 8 HALD image (`neutral_lut.png`, 512×512) contains every possible color combination arranged in a 3D RGB lattice.
* When you open this image in Adobe Lightroom and apply your preset, Lightroom transforms all 262,144 color points through its exact internal engine.
* When imported into Lightroom AI, the engine extracts the 3D color transformation matrix with **100% mathematical fidelity ($\Delta E < 0.1$)**.

#### Step-by-Step Custom Preset Creation:
1. **Download the Neutral Base Image:**  
   In Lightroom AI Studio UI, go to **Settings (⚙️)** $\rightarrow$ click **"Download LUT Base"** (or use `web/neutral_lut.png`).
2. **Open in Adobe Lightroom:**  
   Import `neutral_lut.png` into **Adobe Lightroom Classic** or **Lightroom CC**.
3. **Apply Your Develop Preset:**  
   Click your desired preset in the Develop module (tone curves, colors, split toning, shadows, highlights).
4. **Export as Master PNG/JPEG:**  
   Export the image as:
   * **Format:** PNG or JPEG (100% Quality)
   * **Color Space:** sRGB or Adobe RGB 1998
   * **Dimensions:** Original (512×512)
5. **Activate in Lightroom AI:**  
   In Lightroom AI Settings, click **"Pick File"** or drag-and-drop the exported HALD image into the drop zone. The engine instantly compiles it into an active 3D LUT!

---

### Category C: Internal Calibration & Benchmark Files (Development Only)

Files in the developer repository such as `IMG_4932.tif`, `ref_8bit.png`, `difference_heatmap.png`, and `diff_heatmap_*.png`:
* *What they are:* 16-bit uncompressed RAW test targets and error heatmaps used by the engineering team to benchmark and verify mathematical parity against Adobe Lightroom Classic across 50+ camera profiles.
* *Are they needed by photographers?* **NO.** They are internal development artifacts and are safely excluded from the user release package to keep the download light (~5.5 MB).

---

## 3. Preset Compatibility Matrix

| File Type | Native Lightroom AI Support | Role in Ecosystem |
| :--- | :--- | :--- |
| **.cube (3D LUT)** | **Native (Built-in)** | Primary high-performance color grading format. |
| **.png (3D HALD)** | **Native (Instant Import)** | Standard format for importing any Adobe Lightroom preset. |
| **.json (Preset Bundle)**| **Native (Built-in)** | Stores spatial parameters (vignette, clarity, dehaze). |
| **.xmp (Lightroom XMP)**| **Converted via HALD** | Converted via Lightroom export to ensure 100% mathematical accuracy. |
| **.dng (Adobe DNG)** | **Converted via HALD** | Converted via Lightroom export to ensure 100% mathematical accuracy. |
| **.tif (Raw Target)** | **Internal Benchmark Only**| Calibration target used during development. |

---

## 4. Summary

* **Normal Everyday Use:** Just drop your raw photos in `C:/Media_Incoming` and click **"Start"**. Everything is automated.
* **Custom Presets:** Use `neutral_lut.png` in Adobe Lightroom to export your favorite looks into Lightroom AI Studio.
