"""
Lightroom AI - Studio Edition 2.0
Stage 2: AI Scene & Exposure Auto-Balancing Analyzer (stage2_analyzer.py)

Strict Rules:
- Evaluates strictly on the LOCKED Stage 1 Base Buffer.
- Never re-runs or modifies Stage 1.
- Converts visual proxy to sRGB for VLM visual comprehension.
- Computes deterministic objective telemetry.
- Enforces confidence gating and no-op conditions.
- Strict fallback to complete no-op on failure.
"""

import os
import json
import base64
import time
import re
import random
import threading
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import cv2
import numpy as np
import requests
from typing import Dict, Any, Tuple, Optional

from color_space import ColorManager
from stage2_schema import (
    STAGE2_LIMITS,
    CONFIDENCE_THRESHOLD,
    ZERO_ADJUSTMENTS,
    sanitize_and_clamp_adjustments,
    compute_stage1_buffer_hash
)


class RequestPacer:
    """Thread-safe request pacer to prevent TPM/RPM burst rate-limits."""
    def __init__(self, min_interval_seconds: float = 1.0):
        self.min_interval = min_interval_seconds
        self._last_request_time = 0.0
        self._lock = threading.Lock()

    def pace(self):
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request_time = time.time()


def parse_retry_after(response: Optional[requests.Response], default_backoff: float = 2.0, max_backoff: float = 30.0) -> float:
    """
    Parses Retry-After header or rate limit body message from HTTP response.
    Returns bounded seconds to wait (between 0.5s and max_backoff).
    """
    if response is None:
        return default_backoff

    # 1. Check Retry-After header
    header_val = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if header_val:
        header_val = header_val.strip()
        # Try numeric seconds
        try:
            val = float(header_val)
            if val > 0:
                return min(max(val, 0.5), max_backoff)
        except ValueError:
            # Try HTTP date format
            try:
                dt = parsedate_to_datetime(header_val)
                now_dt = datetime.now(timezone.utc)
                delta = (dt - now_dt).total_seconds()
                if delta > 0:
                    return min(delta, max_backoff)
            except Exception:
                pass

    # 2. Check X-RateLimit-Reset headers if present
    for reset_header in ["x-ratelimit-reset-requests", "x-ratelimit-reset-tokens", "x-ratelimit-reset"]:
        hv = response.headers.get(reset_header)
        if hv:
            try:
                hv_clean = hv.strip().rstrip("s")
                val = float(hv_clean)
                if val > 0:
                    return min(max(val, 0.5), max_backoff)
            except Exception:
                pass

    # 3. Check JSON error body message for "try again in X.XXs" or "try again in Xms"
    try:
        body = response.text
        m = re.search(r"try again in ([\d\.]+)\s*(s|sec|seconds|ms)", body, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            unit = m.group(2).lower()
            if "ms" in unit:
                val = val / 1000.0
            if val > 0:
                return min(max(val, 0.5), max_backoff)
    except Exception:
        pass

    return min(default_backoff, max_backoff)


_GLOBAL_STAGE2_PACER = RequestPacer(min_interval_seconds=1.2)


class Stage2Analyzer:
    """
    Analyzes Stage 1 Base develop buffer and determines subtle, corrective auto-balancing trims.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 4096
    ):
        self.api_key = os.getenv("ORCA_API_KEY", "") if api_key is None else api_key
        self.api_url = api_url or os.getenv("ORCA_API_URL", "https://api.groq.com/openai/v1/chat/completions")
        # Resolve deprecated/unsupported model aliases
        configured_model = model or os.getenv("ORCA_MODEL", "qwen/qwen3.8-27b")
        if not configured_model or configured_model in ["fusion-flash", "orcarouter/fusion-flash"]:
            self.model = "qwen/qwen3.8-27b"
        else:
            self.model = configured_model
        self.max_tokens = max_tokens or int(os.getenv("ORCA_MAX_TOKENS", "4096"))

    @staticmethod
    def compute_objective_telemetry(stage1_base_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Computes exact objective photometric & colorimetric telemetry from Stage 1 Base Buffer.
        Operates in CIELAB color space.
        """
        if stage1_base_bgr is None:
            return {}

        lab = cv2.cvtColor(stage1_base_bgr, cv2.COLOR_BGR2LAB).astype(np.float64)
        L = lab[:, :, 0] * (100.0 / 255.0)
        a = lab[:, :, 1] - 128.0
        b = lab[:, :, 2] - 128.0

        # Midtone mask for white-balance drift evaluation (L* in [35, 75])
        midtone_mask = (L >= 35.0) & (L <= 75.0)
        if np.sum(midtone_mask) > 0:
            midtone_a_mean = float(np.mean(a[midtone_mask]))
            midtone_b_mean = float(np.mean(b[midtone_mask]))
        else:
            midtone_a_mean = float(np.mean(a))
            midtone_b_mean = float(np.mean(b))

        total_pixels = float(L.size)
        hl_clip_pct = float(np.sum(L >= 98.0) / total_pixels * 100.0)
        sh_clip_pct = float(np.sum(L <= 2.0) / total_pixels * 100.0)

        return {
            "l_mean": round(float(np.mean(L)), 2),
            "l_median": round(float(np.median(L)), 2),
            "l_p5": round(float(np.percentile(L, 5)), 2),
            "l_p95": round(float(np.percentile(L, 95)), 2),
            "highlight_clipping_pct": round(hl_clip_pct, 2),
            "shadow_clipping_pct": round(sh_clip_pct, 2),
            "midtone_a_drift": round(midtone_a_mean, 2),
            "midtone_b_drift": round(midtone_b_mean, 2),
        }

    @staticmethod
    def check_pre_noop_conditions(telemetry: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Evaluates deterministic no-op conditions prior to / in conjunction with VLM analysis.
        Protects balanced midtones, intentional low-key / moody dark scenes, and high-key scenes.
        """
        l_mean = telemetry.get("l_mean", 50.0)
        l_median = telemetry.get("l_median", 50.0)
        hl_clip = telemetry.get("highlight_clipping_pct", 0.0)
        sh_clip = telemetry.get("shadow_clipping_pct", 0.0)
        a_drift = abs(telemetry.get("midtone_a_drift", 0.0))
        b_drift = abs(telemetry.get("midtone_b_drift", 0.0))

        # Check if already within ideal balance window
        is_exp_balanced = (45.0 <= l_median <= 60.0) and (hl_clip < 0.5)
        is_wb_balanced = (a_drift < 2.0) and (b_drift < 3.0)

        if is_exp_balanced and is_wb_balanced:
            return True, "Image is already well-balanced (L* median in [45, 60], neutral midtones)."

        # Special Low-Light / Moody Scene Protection:
        # If L* mean is very low (< 8.0) and shadow clipping is severe (> 60%), this indicates intentional
        # night / low-key / dark background photography where forced exposure brightening destroys the mood.
        if l_mean < 8.0 and sh_clip > 60.0:
            return True, "Intentional low-key / dark moody scene preserved (L* mean < 8, shadow-dominant)."

        return False, ""

    def generate_srgb_visual_proxy(self, stage1_base_bgr: np.ndarray, target_width: int = 768) -> Tuple[np.ndarray, str]:
        """
        Generates an sRGB visual proxy at ~768px width for VLM visual comprehension.
        Converts from Adobe RGB 1998 -> sRGB via LittleCMS.
        """
        h, w = stage1_base_bgr.shape[:2]
        if w > target_width:
            target_h = int(h * (target_width / w))
            proxy_work = cv2.resize(stage1_base_bgr, (target_width, target_h), interpolation=cv2.INTER_AREA)
        else:
            proxy_work = stage1_base_bgr.copy()

        # Convert working buffer (Adobe RGB 1998) to standard sRGB for VLM visual evaluation
        proxy_srgb = ColorManager.convert_icc(proxy_work, src_profile="Adobe_RGB_1998", target_space="sRGB", is_bgr=True)

        _, buf = cv2.imencode(".jpg", proxy_srgb, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        b64_str = base64.b64encode(buf).decode("utf-8")
        return proxy_srgb, b64_str

    def analyze_stage2(
        self,
        stage1_base_bgr: np.ndarray,
        preset_name: str = "Calibrated Studio Preset",
        enable_ai: bool = True
    ) -> Dict[str, Any]:
        """
        Executes complete Stage 2 analysis on the Stage 1 Base Buffer.
        Returns complete structured Stage 2 metadata dictionary.
        """
        if stage1_base_bgr is None:
            return {
                "stage": 2,
                "scene_type": "unknown",
                "confidence": 0.0,
                "needs_correction": False,
                "adjustments_requested": ZERO_ADJUSTMENTS.copy(),
                "adjustments_applied": ZERO_ADJUSTMENTS.copy(),
                "clamped": False,
                "no_op": True,
                "reason": "Input buffer is None",
                "stage1_base_hash": "",
                "telemetry": {},
                "model": self.model,
                "vlm_succeeded": False,
                "http_status": None,
                "finish_reason": None
            }

        # 1. Compute Base Buffer Hash & Objective Telemetry
        base_hash = compute_stage1_buffer_hash(stage1_base_bgr)
        telemetry = self.compute_objective_telemetry(stage1_base_bgr)

        # 2. Check explicit disabled or unconfigured states
        if not enable_ai:
            return {
                "stage": 2,
                "ai_status": "ai_disabled",
                "scene_type": "general",
                "confidence": 0.0,
                "needs_correction": False,
                "adjustments": ZERO_ADJUSTMENTS.copy(),
                "adjustments_requested": ZERO_ADJUSTMENTS.copy(),
                "adjustments_applied": ZERO_ADJUSTMENTS.copy(),
                "clamped": False,
                "no_op": True,
                "reason": "AI Auto-Balancing disabled in settings.",
                "api_error": None,
                "stage1_base_hash": base_hash,
                "telemetry": telemetry,
                "model": self.model,
                "latency_ms": 0,
                "vlm_succeeded": False,
                "http_status": None,
                "finish_reason": None
            }

        if not self.api_key or self.api_key == "your_actual_api_key_here" or not self.api_key.strip():
            return {
                "stage": 2,
                "ai_status": "ai_unavailable",
                "scene_type": "general",
                "confidence": 0.0,
                "needs_correction": False,
                "adjustments": ZERO_ADJUSTMENTS.copy(),
                "adjustments_requested": ZERO_ADJUSTMENTS.copy(),
                "adjustments_applied": ZERO_ADJUSTMENTS.copy(),
                "clamped": False,
                "no_op": True,
                "reason": "AI API key not configured — Stage 1 preset preserved.",
                "api_error": "API key not configured",
                "stage1_base_hash": base_hash,
                "telemetry": telemetry,
                "model": self.model,
                "latency_ms": 0,
                "vlm_succeeded": False,
                "http_status": None,
                "finish_reason": None
            }

        # 3. Check deterministic no-op criteria (intentional moody dark or pre-balanced scene)
        is_noop, noop_reason = self.check_pre_noop_conditions(telemetry)
        if is_noop:
            return {
                "stage": 2,
                "ai_status": "ai_no_correction",
                "scene_type": "dark_low_light" if "low-key" in noop_reason else "general",
                "confidence": 0.95,
                "needs_correction": False,
                "adjustments": ZERO_ADJUSTMENTS.copy(),
                "adjustments_requested": ZERO_ADJUSTMENTS.copy(),
                "adjustments_applied": ZERO_ADJUSTMENTS.copy(),
                "clamped": False,
                "no_op": True,
                "reason": noop_reason,
                "api_error": None,
                "stage1_base_hash": base_hash,
                "telemetry": telemetry,
                "model": self.model,
                "latency_ms": 0,
                "vlm_succeeded": True,
                "http_status": 200,
                "finish_reason": "pre_gated"
            }

        # 4. Generate sRGB Visual Proxy
        _, b64_proxy = self.generate_srgb_visual_proxy(stage1_base_bgr, target_width=768)

        # 5. Query OrcaRouter VLM
        vlm_res = self._query_vlm(b64_proxy, telemetry, preset_name)

        if not vlm_res.get("success") or not vlm_res.get("parsed"):
            ai_status = vlm_res.get("ai_status", "ai_failed")
            err_msg = vlm_res.get("error") or "VLM request failed (safe fallback: Stage 1 preset preserved)."
            return {
                "stage": 2,
                "ai_status": ai_status,
                "scene_type": "general",
                "confidence": 0.0,
                "needs_correction": False,
                "adjustments": ZERO_ADJUSTMENTS.copy(),
                "adjustments_requested": ZERO_ADJUSTMENTS.copy(),
                "adjustments_applied": ZERO_ADJUSTMENTS.copy(),
                "clamped": False,
                "no_op": True,
                "reason": err_msg,
                "api_error": err_msg,
                "stage1_base_hash": base_hash,
                "telemetry": telemetry,
                "model": self.model,
                "latency_ms": vlm_res.get("latency_ms", 0),
                "vlm_succeeded": False,
                "http_status": vlm_res.get("http_status"),
                "finish_reason": vlm_res.get("finish_reason")
            }

        # 6. Extract & Sanitize Response
        raw_response = vlm_res["parsed"]
        scene_type = raw_response.get("scene_type", "general")
        confidence = float(raw_response.get("confidence", 0.0))
        needs_correction = bool(raw_response.get("needs_correction", False))
        reasoning = raw_response.get("reasoning", "")
        raw_adj = raw_response.get("adjustments", {})

        clamped_adj, was_clamped, is_no_op = sanitize_and_clamp_adjustments(
            raw_adj, confidence=confidence, needs_correction=needs_correction, use_operational_limits=True
        )

        has_non_zero = any(abs(v) > 1e-4 for v in clamped_adj.values())
        if is_no_op or not needs_correction or not has_non_zero:
            ai_status = "ai_no_correction"
            final_reason = reasoning or "Scene is well-balanced. No AI correction needed."
        else:
            ai_status = "ai_analyzed"
            final_reason = reasoning or "AI micro-adjustments applied."

        return {
            "stage": 2,
            "ai_status": ai_status,
            "scene_type": scene_type,
            "confidence": round(confidence, 2),
            "needs_correction": needs_correction,
            "adjustments": clamped_adj,
            "adjustments_requested": raw_adj,
            "adjustments_applied": clamped_adj,
            "clamped": was_clamped,
            "no_op": is_no_op or not has_non_zero,
            "reason": final_reason,
            "api_error": None,
            "stage1_base_hash": base_hash,
            "telemetry": telemetry,
            "model": self.model,
            "latency_ms": vlm_res.get("latency_ms", 0),
            "vlm_succeeded": True,
            "http_status": vlm_res.get("http_status"),
            "finish_reason": vlm_res.get("finish_reason")
        }

    def _query_vlm(self, b64_jpeg: str, telemetry: Dict[str, Any], preset_name: str) -> Dict[str, Any]:
        """Sends request to VLM endpoint with retry handling and strict JSON contract."""
        import time

        prompt = (
            f"You are a master colorist assistant working on Stage 2 AI Auto-Balancing for a photo that already has "
            f"a locked, calibrated Lightroom preset applied ('{preset_name}').\n"
            f"IMPORTANT: The Lightroom preset aesthetic is primary and must NOT be restyled or altered.\n"
            f"Stage 2 is strictly a SUBTLE MICRO-CORRECTION assistant. Do NOT force generic average midtones.\n"
            f"Objective Telemetry:\n"
            f"- L* Mean: {telemetry.get('l_mean')}, L* Median: {telemetry.get('l_median')} (nominal: 45-60)\n"
            f"- L* 5th percentile: {telemetry.get('l_p5')}, 95th percentile: {telemetry.get('l_p95')}\n"
            f"- Highlight Clipping: {telemetry.get('highlight_clipping_pct')}%, Shadow Clipping: {telemetry.get('shadow_clipping_pct')}%\n"
            f"- Midtone a* drift (green-magenta): {telemetry.get('midtone_a_drift')}, b* drift (blue-yellow): {telemetry.get('midtone_b_drift')}\n\n"
            f"Rules & Instructions:\n"
            f"1. Preserving Intentional Lighting:\n"
            f"   - If this is a dark, moody, or low-key scene (e.g. night, shadows, concert), preserve the darkness (needs_correction: false).\n"
            f"   - If this is a warm indoor or golden-hour scene, preserve the warmth.\n"
            f"   - If this is a bright high-key scene, preserve the brightness.\n"
            f"2. Only request micro-corrections if there is clear, unmistakable evidence of accidental camera exposure failure or accidental color cast.\n"
            f"3. Operational trim limits:\n"
            f"   - exposure_ev: range [-0.25, +0.25] EV\n"
            f"   - temperature: range [-6.0, +6.0] (negative = cool down, positive = warm up)\n"
            f"   - tint: range [-4.0, +4.0] (negative = add green, positive = add magenta)\n"
            f"   - highlights: range [-8.0, +3.0]\n"
            f"   - shadows: range [-5.0, +8.0]\n"
            f"4. Confidence must be between 0.0 and 1.0 (threshold >= 0.70).\n"
            f"5. If no correction is strictly necessary, set needs_correction: false and all adjustments to 0.0.\n\n"
            f"Respond ONLY with a valid JSON object matching this schema. Do NOT include markdown code blocks, preamble, or commentary:\n"
            f"{{\n"
            f'  "scene_type": "outdoor_foliage" | "indoor_warm" | "portrait_skin" | "bright_high_key" | "dark_low_light" | "general",\n'
            f'  "needs_correction": true | false,\n'
            f'  "confidence": float,\n'
            f'  "reasoning": "brief explanation",\n'
            f'  "adjustments": {{\n'
            f'    "exposure_ev": float,\n'
            f'    "temperature": float,\n'
            f'    "tint": float,\n'
            f'    "highlights": float,\n'
            f'    "shadows": float\n'
            f'  }}\n'
            f"}}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_jpeg}"}}
                    ]
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": self.max_tokens
        }

        last_error = None
        last_status = None
        last_finish_reason = None
        start_time = time.time()
        max_attempts = 4

        for attempt in range(max_attempts):
            _GLOBAL_STAGE2_PACER.pace()
            try:
                r = requests.post(self.api_url, headers=headers, json=payload, timeout=35)
                last_status = r.status_code
                latency_ms = int((time.time() - start_time) * 1000)

                # 1. Check for permanent authentication/billing failure (401, 402, 403)
                if r.status_code in [401, 402, 403]:
                    err_body = r.text.lower()
                    if r.status_code == 401 or "unauthorized" in err_body or "invalid_api_key" in err_body:
                        err_msg = "AI API request failed — invalid API key."
                    elif r.status_code == 402 or "credit" in err_body or "balance" in err_body or "quota" in err_body:
                        err_msg = "AI API request failed — insufficient credits."
                    else:
                        err_msg = f"AI API access denied (HTTP {r.status_code})."

                    return {
                        "success": False,
                        "ai_status": "ai_unavailable",
                        "http_status": r.status_code,
                        "finish_reason": "rate_limit_or_auth_failure",
                        "parsed": None,
                        "error": err_msg,
                        "latency_ms": latency_ms
                    }

                # 2. Check for rate limit (429) or transient server errors (5xx)
                if r.status_code == 429 or (500 <= r.status_code < 600):
                    base_wait = min(30.0, 1.5 * (2 ** attempt) + random.uniform(0.1, 0.4))
                    wait_seconds = parse_retry_after(r, default_backoff=base_wait, max_backoff=30.0)

                    if attempt < max_attempts - 1:
                        time.sleep(wait_seconds)
                        continue

                    # Exhausted retries on 429 / 5xx
                    err_msg = f"AI rate limit / quota exceeded (Groq). Retries exhausted ({max_attempts} attempts). Stage 1 preset preserved."
                    return {
                        "success": False,
                        "ai_status": "ai_unavailable",
                        "http_status": r.status_code,
                        "finish_reason": "rate_limit_or_auth_failure",
                        "parsed": None,
                        "error": err_msg,
                        "latency_ms": latency_ms
                    }

                # 3. Successful response (200)
                if r.status_code == 200:
                    resp_json = r.json()
                    choice = resp_json.get("choices", [{}])[0]
                    last_finish_reason = choice.get("finish_reason")
                    raw_text = choice.get("message", {}).get("content", "")

                    # Clean markdown code fences if model returned them
                    clean_text = raw_text.strip()
                    if clean_text.startswith("```"):
                        clean_text = clean_text.strip("`")
                        if clean_text.startswith("json"):
                            clean_text = clean_text[4:].strip()

                    start = clean_text.find("{")
                    end = clean_text.rfind("}")
                    if start != -1 and end != -1:
                        parsed = json.loads(clean_text[start:end+1])
                        return {
                            "success": True,
                            "ai_status": "ai_analyzed",
                            "http_status": 200,
                            "finish_reason": last_finish_reason,
                            "parsed": parsed,
                            "error": None,
                            "latency_ms": latency_ms
                        }
                    else:
                        last_error = f"Malformed JSON content from AI (finish_reason: {last_finish_reason})"
                else:
                    last_error = f"HTTP {r.status_code}: {r.text[:120]}"

            except Exception as e:
                last_error = f"Request exception: {type(e).__name__} ({str(e)})"

            if attempt < max_attempts - 1:
                backoff_time = min(30.0, 1.5 * (2 ** attempt) + random.uniform(0.1, 0.4))
                time.sleep(backoff_time)

        latency_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "ai_status": "ai_failed",
            "http_status": last_status,
            "finish_reason": last_finish_reason,
            "parsed": None,
            "error": last_error or "VLM communication failure",
            "latency_ms": latency_ms
        }
