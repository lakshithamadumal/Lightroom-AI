"""
Lightroom AI - Studio Edition 2.0
Stage 2: AI Scene & Exposure Auto-Balancing Schema and Constraints (stage2_schema.py)
"""

from typing import Dict, Any, Tuple, Optional
import hashlib
import numpy as np
import cv2

# ================= HARD PARAMETER SAFETY CLAMPS =================
# Stage 2 is strictly a subtle corrective assistant.
# Large alterations, color grading changes, and contrast restructuring are permanently forbidden.

# Schema-level outer bounds (for backward compatibility)
STAGE2_LIMITS = {
    "exposure_ev": (-0.50, 0.50),
    "temperature": (-12.0, 12.0),
    "tint": (-8.0, 8.0),
    "highlights": (-15.0, 5.0),
    "shadows": (-5.0, 15.0),
    # Permanently locked parameters (cannot be changed by Stage 2)
    "contrast": 0.0,
    "saturation": 0.0,
    "vibrance": 0.0,
}

# Tight Production Operational Limits (conservative assistant trims)
STAGE2_OPERATIONAL_LIMITS = {
    "exposure_ev": (-0.25, 0.25),
    "temperature": (-6.0, 6.0),
    "tint": (-4.0, 4.0),
    "highlights": (-8.0, 3.0),
    "shadows": (-5.0, 8.0),
    "contrast": 0.0,
    "saturation": 0.0,
    "vibrance": 0.0,
}

# Preset-Preservation Safety Gate Thresholds
PRESET_PRESERVATION_LIMITS = {
    "max_mean_delta_e": 2.0,
    "max_p95_delta_e": 5.0,
    "max_luminance_shift": 4.0,
    "max_chroma_shift": 3.0,
}

CONFIDENCE_THRESHOLD = 0.70

ZERO_ADJUSTMENTS = {
    "exposure_ev": 0.0,
    "temperature": 0.0,
    "tint": 0.0,
    "highlights": 0.0,
    "shadows": 0.0,
}


def apply_total_budget_scaling(
    adjustments: Dict[str, float],
    max_budget: float = 1.0
) -> Tuple[Dict[str, float], bool]:
    """
    Applies a combined multi-parameter correction budget.
    Prevents simultaneous large exposure + large shadow + large WB corrections.
    If the combined normalized correction exceeds max_budget, scales the adjustment vector down proportionally.
    """
    exp_val = abs(adjustments.get("exposure_ev", 0.0))
    temp_val = abs(adjustments.get("temperature", 0.0))
    tint_val = abs(adjustments.get("tint", 0.0))
    hl_val = adjustments.get("highlights", 0.0)
    sh_val = adjustments.get("shadows", 0.0)

    # Normalized consumption against operational max limits
    u_exp = exp_val / 0.25 if 0.25 > 0 else 0.0
    u_temp = temp_val / 6.0 if 6.0 > 0 else 0.0
    u_tint = tint_val / 4.0 if 4.0 > 0 else 0.0
    u_hl = abs(hl_val) / (8.0 if hl_val < 0 else 3.0) if (8.0 if hl_val < 0 else 3.0) > 0 else 0.0
    u_sh = abs(sh_val) / (5.0 if sh_val < 0 else 8.0) if (5.0 if sh_val < 0 else 8.0) > 0 else 0.0

    total_consumption = u_exp + u_temp + u_tint + u_hl + u_sh

    if total_consumption > max_budget and total_consumption > 1e-4:
        scale_factor = max_budget / total_consumption
        scaled = {
            "exposure_ev": round(adjustments.get("exposure_ev", 0.0) * scale_factor, 2),
            "temperature": round(adjustments.get("temperature", 0.0) * scale_factor, 2),
            "tint": round(adjustments.get("tint", 0.0) * scale_factor, 2),
            "highlights": round(adjustments.get("highlights", 0.0) * scale_factor, 2),
            "shadows": round(adjustments.get("shadows", 0.0) * scale_factor, 2),
        }
        return scaled, True

    return adjustments.copy(), False


def sanitize_and_clamp_adjustments(
    raw_adjustments: Optional[Dict[str, Any]],
    confidence: float,
    needs_correction: bool,
    use_operational_limits: bool = True
) -> Tuple[Dict[str, float], bool, bool]:
    """
    Applies strict confidence gating, no-op checks, conservative operational clamps,
    and multi-parameter total budget scaling to Stage 2 adjustments.
    
    Returns:
        (clamped_adjustments, was_clamped, is_no_op)
    """
    if not needs_correction or confidence < CONFIDENCE_THRESHOLD or not raw_adjustments:
        return ZERO_ADJUSTMENTS.copy(), False, True

    limits_dict = STAGE2_OPERATIONAL_LIMITS if use_operational_limits else STAGE2_LIMITS

    clamped = {}
    was_clamped = False

    for param in ["exposure_ev", "temperature", "tint", "highlights", "shadows"]:
        min_val, max_val = limits_dict[param]
        val = raw_adjustments.get(param, 0.0)
        try:
            val_float = float(val)
        except (ValueError, TypeError):
            val_float = 0.0

        if val_float < min_val:
            clamped[param] = min_val
            was_clamped = True
        elif val_float > max_val:
            clamped[param] = max_val
            was_clamped = True
        else:
            clamped[param] = round(val_float, 2)

    # Apply total budget scaling across simultaneous parameters
    scaled_adj, was_scaled = apply_total_budget_scaling(clamped, max_budget=1.0)
    if was_scaled:
        was_clamped = True
        clamped = scaled_adj

    # Check if effectively no-op (all values zero)
    is_no_op = all(abs(v) < 1e-4 for v in clamped.values())
    if is_no_op:
        return ZERO_ADJUSTMENTS.copy(), was_clamped, True

    return clamped, was_clamped, False


def evaluate_preset_preservation_gate(
    stage1_base_bgr: np.ndarray,
    stage2_candidate_bgr: np.ndarray
) -> Dict[str, Any]:
    """
    Preset-Preservation Safety Gate:
    Compares Stage 2 Candidate against Stage 1 Base in CIELAB color space.
    Computes:
    - Mean Delta E
    - P95 Delta E
    - Mean Luminance shift (Delta L*)
    - Mean Chroma shift (Delta C*)
    
    Returns gate decision:
        accepted: bool (True if within safety thresholds, False if rejected)
    """
    if stage1_base_bgr is None or stage2_candidate_bgr is None:
        return {"accepted": False, "reason": "Null buffer", "mean_delta_e": 0.0, "p95_delta_e": 0.0, "lum_shift": 0.0, "chroma_shift": 0.0}

    # Resize if needed
    if stage1_base_bgr.shape != stage2_candidate_bgr.shape:
        stage2_candidate_bgr = cv2.resize(
            stage2_candidate_bgr,
            (stage1_base_bgr.shape[1], stage1_base_bgr.shape[0]),
            interpolation=cv2.INTER_AREA
        )

    # Subsample large images to 400px for instant sub-5ms gate evaluation
    h, w = stage1_base_bgr.shape[:2]
    if w > 400:
        scale = 400.0 / w
        s1_eval = cv2.resize(stage1_base_bgr, (400, int(h * scale)), interpolation=cv2.INTER_AREA)
        s2_eval = cv2.resize(stage2_candidate_bgr, (400, int(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        s1_eval = stage1_base_bgr
        s2_eval = stage2_candidate_bgr

    lab1 = cv2.cvtColor(s1_eval[:, :, :3], cv2.COLOR_BGR2LAB).astype(np.float64)
    lab2 = cv2.cvtColor(s2_eval[:, :, :3], cv2.COLOR_BGR2LAB).astype(np.float64)

    L1 = lab1[:, :, 0] * (100.0 / 255.0)
    a1 = lab1[:, :, 1] - 128.0
    b1 = lab1[:, :, 2] - 128.0

    L2 = lab2[:, :, 0] * (100.0 / 255.0)
    a2 = lab2[:, :, 1] - 128.0
    b2 = lab2[:, :, 2] - 128.0

    delta_e = np.sqrt((L1 - L2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2)
    mean_de = float(np.mean(delta_e))
    p95_de = float(np.percentile(delta_e, 95))

    lum_shift = float(np.mean(np.abs(L2 - L1)))
    chroma1 = np.sqrt(a1 ** 2 + b1 ** 2)
    chroma2 = np.sqrt(a2 ** 2 + b2 ** 2)
    chroma_shift = float(np.mean(np.abs(chroma2 - chroma1)))

    max_mean_de = PRESET_PRESERVATION_LIMITS["max_mean_delta_e"]
    max_p95_de = PRESET_PRESERVATION_LIMITS["max_p95_delta_e"]
    max_lum = PRESET_PRESERVATION_LIMITS["max_luminance_shift"]
    max_chroma = PRESET_PRESERVATION_LIMITS["max_chroma_shift"]

    accepted = (
        mean_de <= max_mean_de and
        p95_de <= max_p95_de and
        lum_shift <= max_lum and
        chroma_shift <= max_chroma
    )

    reason = "Passed Preset-Preservation Gate" if accepted else (
        f"Rejected: Mean dE ({mean_de:.2f} > {max_mean_de}) or P95 dE ({p95_de:.2f} > {max_p95_de})"
    )

    return {
        "accepted": accepted,
        "reason": reason,
        "mean_delta_e": round(mean_de, 3),
        "p95_delta_e": round(p95_de, 3),
        "lum_shift": round(lum_shift, 3),
        "chroma_shift": round(chroma_shift, 3)
    }


def compute_stage1_buffer_hash(image_bgr: np.ndarray) -> str:
    """Computes deterministic SHA-256 hash of the Stage 1 Base Buffer for integrity auditing."""
    if image_bgr is None:
        return ""
    # Use contiguous memory bytes
    return hashlib.sha256(np.ascontiguousarray(image_bgr).tobytes()).hexdigest()

