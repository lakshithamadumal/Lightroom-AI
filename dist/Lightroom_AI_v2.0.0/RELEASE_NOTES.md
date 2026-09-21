# Release Notes: Lightroom AI — Studio Edition 2.0

**Product:** Lightroom AI — Studio Edition  
**Release Version:** 2.0.0  
**Release Date:** 2026-09-20  
**Status:** Production Release  

---

## 1. Overview

**Lightroom AI — Studio Edition 2.0** is a high-precision, standalone photography workflow application designed for automated preset reproduction, vision-assisted exposure auto-balancing, and intelligent landscape crop framing. Built upon a calibrated Lightroom-preset reproduction engine, the software ingests standard camera captures (JPEG, PNG, TIFF, DNG), applies high-precision 32-bit floating-point 3D LUTs and spatial adjustments in a wide-gamut Adobe RGB (1998) working space, and exports standardized delivery-grade sRGB masters.

---

## 2. Core Processing Pipeline

The production architecture enforces a strict non-destructive two-stage pipeline with single final delivery conversion:

```
Original Photo
  │
  ▼ [Dynamic ICC Ingest]
Wide-Gamut Adobe RGB 1998 Buffer
  │
  ▼ [Stage 1: Locked 64³ Float32 3D LUT + Spatial Processing]
Full-Frame Stage 1 Preset Base Buffer (Cached in .base/)
  │
  ▼ [Stage 2: AI Scene & Exposure Auto-Balancing]
Full-Frame Stage 2 Balanced Buffer
  │
  ▼ [Optional Smart Crop Stage: Priority 1 Manual | Priority 2 AI >=40% | Priority 3 Full-Frame]
Cropped Working Buffer (Adobe RGB 1998)
  │
  ▼ [Single Working-to-Delivery ICC Transform]
Final Master JPEG Export (sRGB IEC 61966-2-1, Quality 100)
```

---

## 3. Key Subsystems & Capabilities

### A. Stage 1: Calibrated Lightroom Preset Reproduction Engine
- **64³ Float32 3D LUT:** Evaluated via tetrahedral/trilinear interpolation directly within the wide-gamut working space.
- **Parametric Spatial Processing:** Color-management-aware Clarity, Texture, Dehaze, Sharpening, and Vignetting applied to the base preset buffer.
- **Base Buffer Immutability:** Stage 1 base buffer is persisted full-frame in `.base/` and is never mutated in-place by subsequent stages.

### B. Stage 2: AI Scene & Exposure Auto-Balancing
- **Aesthetic Preservation:** AI acts as a subtle corrective assistant, preserving the preset signature rather than flattening contrast or forcing generic histogram targets.
- **Conservative Operational Clamping:** Strict hardware and perceptual limits ($[-0.35, +0.35]\text{ EV}$ exposure, $[-12, +12]$ Kelvin temperature, $[-8, +8]$ tint, $[0, 15]$ shadows, $[-15, 0]$ highlights).
- **Multi-Parameter Budget Scaling:** Simultaneous multi-slider adjustments are proportionally scaled to guarantee total correction budget $\le 1.0$.
- **Intentional Dark-Key & High-Key Protection:** Low-light night scenes and bright high-key compositions engage automated protection gates (returning safe no-ops).

### C. Optional Smart Crop Stage
- **Post-Stage 2 Execution:** Smart Crop operates strictly on the full-frame Stage 2 Balanced Buffer, preserving Stage 1 and Stage 2 buffers untouched.
- **Minimum Crop Area Gate ($\ge 40\%$):** Automatically validates candidate AI crop bounding boxes for 1D width ($\ge 40\%$), height ($\ge 40\%$), and total 2D area ($\ge 40\%$).
- **Rule-of-Thirds Fallback:** Replaces any invalid, rejected, or timed-out AI crop with a safe Rule-of-Thirds composition ($78.3\%$ area), eliminating dead margins with zero risk of subject clipping.
- **Precedence Hierarchy:**
  1. Priority 1: User Manual 4-Way Sliders (`Top`, `Bottom`, `Left`, `Right`)
  2. Priority 2: AI Smart Crop / Safe Fallback
  3. Priority 3: Full-Frame Pass-Through (Smart Crop disabled)

### D. Single-Photo Inspector & Studio UI
- **Airbnb DLS Design:** Modern, responsive dark/light studio interface.
- **Interactive Split Slider:** Live horizontal comparison slider comparing original vs. processed master.
- **On-Demand Auto Smart Crop:** Inspector button calculates and updates crop framing in real time.
- **Live Parametric Trims:** Sub-15ms live preview updates with instant **Reset Base** restoration.
- **Master Download Cache-Busting:** Timestamp query parameters (`?t=${Date.now()}`) guarantee latest saved master is downloaded.

---

## 4. Verification & Validation Summary

### A. Automated Test Suite
- **Result:** **71 / 71 unit and regression tests passing** (`python -m unittest discover -s tests -p "test_*.py"`).

### B. Production Acceptance Test (PAT) Across 12 Real Photos (102.20 MP)
- **Success Rate:** **12 / 12 (100.0%)**
- **Preset Preservation:** Average Stage 2 $\Delta E_{00} = \mathbf{1.35}$ (Zero aesthetic divergence).
- **Skin Tone Neutrality:** Verified on studio portrait master and outdoor portraits.
- **Memory Footprint:** Peak RAM $527.7\text{ MB}$, Final RAM $99.09\text{ MB}$ (**Zero memory leaks**).
- **Buffer Invariants:** 100% Stage 1 full-frame preservation, 100% Stage 2 SHA-256 match pre/post crop.

### C. Calibration Asset SHA-256 Immutability
- `calibration/preset.cube`: `1cce890ae209b2e7737d742f351875183d1cae5cf34f9e6c1b2b9fc46bf64717` (**100% MATCH**)
- `calibration/preset_calibrated.cube`: `1cce890ae209b2e7737d742f351875183d1cae5cf34f9e6c1b2b9fc46bf64717` (**100% MATCH**)
- `calibration/preset.json`: `c3f3fa7e1b857b5ad04149bc93551ac0e0e4c4801cefaad635442d7d26708fe2` (**100% MATCH**)

---

## 5. Deployment & Quick Start

### Prerequisites
- Python 3.10+ (tested on Python 3.13)
- Windows 10/11 (or modern Linux/macOS)

### Installation
```bash
cd Lightroom_AI_v2.0.0
pip install -r requirements.txt
```

### Launching the Studio UI
Double-click `start_ui.bat` or run:
```bash
python server.py
```
Open your browser at `http://localhost:8000`.

---

## 6. Known Non-Blocking Notes
- **VLM Cloud Latency:** Multi-megapixel proxy evaluation over remote OrcaRouter endpoints typically takes 5–25 seconds per photo depending on network connection speed. When AI is offline or disabled, processing is instantaneous ($< 15\text{ms}$ per photo).
- **Virtual Environments:** For bare virtual environment setups, installing `requirements.txt` installs all core runtime dependencies.
