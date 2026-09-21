"""
Lightroom AI - Studio Edition 2.0
Intelligent Landscape Smart Crop Engine (smart_cropper.py)

Strict Rules:
- Executes strictly on the Stage 2 Balanced Buffer in the wide-gamut Adobe RGB 1998 working space.
- Never modifies the input Stage 1 Base or Stage 2 Balanced buffers in-place.
- Purely spatial operation: calculates bounding box [y1:y2, x1:x2] and returns a sliced array.
- Does not modify RGB color values, LUTs, ICC profiles, exposure, WB, or tone curves.
- Enforces strict crop area (>= 40%), width (>= 40%), height (>= 40%), and coordinate boundary validations.
- Automatically rejects invalid AI crops and uses the Rule-of-Thirds fallback with clear telemetry logging.
"""

import os
import cv2
import json
import base64
import time
import requests
import random
import numpy as np
from typing import Dict, Any, Tuple, Optional
from stage2_analyzer import _GLOBAL_STAGE2_PACER, parse_retry_after


class SmartCropper:
    """
    Intelligent Landscape Smart Crop Engine.
    Uses OrcaRouter vision capabilities with Golden-Ratio / Subject Saliency fallback
    to eliminate dead ceiling space, awkward floor margins, and peripheral clutter.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = os.environ.get("ORCA_API_KEY", "") if api_key is None else api_key
        self.api_url = api_url or os.environ.get("ORCA_API_URL", "https://api.groq.com/openai/v1/chat/completions")
        configured_model = model or os.environ.get("ORCA_MODEL", "qwen/qwen3.8-27b")
        if not configured_model or configured_model in ["fusion-flash", "orcarouter/fusion-flash"]:
            self.model = "qwen/qwen3.8-27b"
        else:
            self.model = configured_model

        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.face_cascade = cv2.CascadeClassifier(cascade_path) if os.path.exists(cascade_path) else None

    def detect_faces(self, img: np.ndarray) -> list:
        """
        Detects visible faces in image buffer (BGR).
        Returns list of bounding boxes [(x, y, w, h), ...] in pixel coordinates.
        """
        if self.face_cascade is None or img is None:
            return []
        try:
            h, w = img.shape[:2]
            scale = 1.0
            if max(h, w) > 1000:
                scale = 1000.0 / max(h, w)
                small = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            else:
                small = img
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(25, 25))
            if len(faces) == 0:
                return []
            scaled_faces = []
            for (fx, fy, fw, fh) in faces:
                scaled_faces.append((
                    int(fx / scale),
                    int(fy / scale),
                    int(fw / scale),
                    int(fh / scale)
                ))
            return scaled_faces
        except Exception:
            return []

    @classmethod
    def validate_crop_safety(
        cls,
        crop_box: Optional[list],
        original_width: int,
        original_height: int,
        detected_faces: Optional[list] = None
    ) -> Tuple[bool, str, Optional[Tuple[int, int, int, int, float, float, float]]]:
        """
        Validates crop box against all geometric, compositional, and subject-safety constraints:
        - coordinates within [0.0, 1.0]
        - xmin < xmax, ymin < ymax
        - width ratio >= 0.40, height ratio >= 0.40, crop_area_ratio >= 0.40
        - maximum vertical/horizontal displacement gates
        - subject/headroom/chin/body containment margins for all detected faces
        
        Returns:
            (is_valid, reason, (y1, y2, x1, x2, width_ratio, height_ratio, crop_area_ratio))
        """
        if not crop_box or len(crop_box) != 4:
            return False, "Null or malformed crop box", None

        try:
            ymin, xmin, ymax, xmax = [float(v) for v in crop_box]
        except (ValueError, TypeError):
            return False, "Non-numeric coordinates in crop box", None

        # 1. Bounds check [0.0, 1.0]
        if not (0.0 <= ymin <= 1.0 and 0.0 <= xmin <= 1.0 and 0.0 <= ymax <= 1.0 and 0.0 <= xmax <= 1.0):
            return False, f"Coordinates out of [0, 1] bounds: [{ymin}, {xmin}, {ymax}, {xmax}]", None

        # 2. Coordinate ordering
        if xmin >= xmax:
            return False, f"Invalid horizontal bounds: xmin ({xmin}) >= xmax ({xmax})", None

        if ymin >= ymax:
            return False, f"Invalid vertical bounds: ymin ({ymin}) >= ymax ({ymax})", None

        w_ratio = round(xmax - xmin, 6)
        h_ratio = round(ymax - ymin, 6)
        area_ratio = round(w_ratio * h_ratio, 6)

        # 3. Minimum width, height, and area constraints (>= 40%)
        if w_ratio < 0.40:
            return False, f"Crop width ratio ({w_ratio:.2%}) < 40% threshold", None

        if h_ratio < 0.40:
            return False, f"Crop height ratio ({h_ratio:.2%}) < 40% threshold", None

        if area_ratio < 0.40:
            return False, f"Crop area ratio ({area_ratio:.2%}) < 40% threshold (width {w_ratio:.2%} * height {h_ratio:.2%})", None

        # 4. Subject & Face Protection (Ensures complete visible person/head is preserved)
        if detected_faces and len(detected_faces) > 0:
            for i, (fx, fy, fw, fh) in enumerate(detected_faces):
                f_top_norm = fy / float(original_height)
                f_bottom_norm = (fy + fh) / float(original_height)
                f_left_norm = fx / float(original_width)
                f_right_norm = (fx + fw) / float(original_width)
                f_h_norm = fh / float(original_height)

                # Safe headroom margin above face
                headroom_req = max(0.02, 0.15 * f_h_norm)
                if ymin > (f_top_norm - headroom_req):
                    return False, f"Subject safety violation: crop cuts into head/hair of face #{i+1} (ymin {ymin:.2f} > {f_top_norm - headroom_req:.2f})", None

                # Safe body/chin margin below face
                chin_req = max(0.05, 0.35 * f_h_norm)
                if ymax < (f_bottom_norm + chin_req):
                    return False, f"Subject safety violation: crop decapitates or cuts too close to chin of face #{i+1} (ymax {ymax:.2f} < {f_bottom_norm + chin_req:.2f})", None

                # Safe horizontal margins
                if xmin > (f_left_norm - 0.015):
                    return False, f"Subject safety violation: crop clips left side/ear of face #{i+1}", None

                if xmax < (f_right_norm + 0.015):
                    return False, f"Subject safety violation: crop clips right side/ear of face #{i+1}", None

        # 5. Excessive vertical/horizontal displacement gates (prevent aggressive cropping)
        is_tall_portrait = (original_height > original_width * 1.6)
        max_top_trim = 0.30 if is_tall_portrait else 0.28
        min_bottom_keep = 0.65 if is_tall_portrait else 0.68

        if ymin > max_top_trim:
            return False, f"Aggressive top crop: ymin ({ymin:.2%}) exceeds safe headroom limit ({max_top_trim:.0%})", None

        if ymax < min_bottom_keep:
            return False, f"Aggressive bottom crop: ymax ({ymax:.2%}) cuts below safe baseline ({min_bottom_keep:.0%})", None

        if xmin > 0.30:
            return False, f"Aggressive left crop: xmin ({xmin:.2%}) exceeds safe margin (30%)", None

        if xmax < 0.68:
            return False, f"Aggressive right crop: xmax ({xmax:.2%}) exceeds safe margin (68%)", None

        y1 = max(0, int(ymin * original_height))
        y2 = min(original_height, int(ymax * original_height))
        x1 = max(0, int(xmin * original_width))
        x2 = min(original_width, int(xmax * original_width))

        crop_w_px = x2 - x1
        crop_h_px = y2 - y1

        if crop_w_px < int(original_width * 0.40) or crop_h_px < int(original_height * 0.40):
            return False, f"Pixel dimension constraint violated: {crop_w_px}x{crop_h_px}", None

        return True, "Valid crop box", (y1, y2, x1, x2, w_ratio, h_ratio, area_ratio)

    @classmethod
    def validate_crop_box(
        cls,
        crop_box: Optional[list],
        original_width: int,
        original_height: int
    ) -> Tuple[bool, str, Optional[Tuple[int, int, int, int, float, float, float]]]:
        """Backward-compatible validation wrapper."""
        return cls.validate_crop_safety(crop_box, original_width, original_height, detected_faces=None)

    def crop_best_landscape(
        self,
        img: np.ndarray,
        enable_ai: bool = True,
        allow_deterministic_fallback: bool = False
    ) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Executes Smart Crop on the Stage 2 Balanced Buffer.
        
        Parameters:
            img: Stage 2 Balanced Buffer (Adobe RGB 1998 working space)
            enable_ai: If False, returns the exact full-frame Stage 2 buffer without cropping.
                       If True, queries AI vision. If AI fails, unavailable, or invalid,
                       FAILS SAFELY TO FULL FRAME (never crops silently).
            allow_deterministic_fallback: If explicitly True and AI fails, uses Rule-of-Thirds fallback.
                                          Default is False (preserves full-frame safely on failure).
                       
        Returns:
            (cropped_stage2_buffer, crop_telemetry)
        """
        if img is None:
            return None, {}

        h, w = img.shape[:2]

        # Case A: Smart Crop is disabled -> return exact full-frame Stage 2 buffer (no crop)
        if not enable_ai:
            return img.copy(), {
                "enabled": False,
                "source": "stage2_balanced",
                "applied": False,
                "crop_status": "crop_disabled",
                "crop_source": "none",
                "crop_box": {"ymin": 0.0, "xmin": 0.0, "ymax": 1.0, "xmax": 1.0},
                "ymin": 0.0,
                "xmin": 0.0,
                "ymax": 1.0,
                "xmax": 1.0,
                "original_width": int(w),
                "original_height": int(h),
                "cropped_width": int(w),
                "cropped_height": int(h),
                "crop_area_ratio": 1.0,
                "reason": "Smart Crop disabled in settings (full-frame preserved)",
                "api_error": None,
                "fallback_used": False,
                "method": "Full Frame (No Crop)",
                "trim_x_pct": 0,
                "trim_y_pct": 0,
                "original_size": f"{w}x{h}",
                "cropped_size": f"{w}x{h}",
                "notes": "Smart Crop disabled",
                "model": self.model,
                "latency_ms": 0
            }

        # Case B: Smart Crop is enabled -> attempt AI Vision Composition Analysis
        detected_faces = self.detect_faces(img)
        ai_res = self._get_ai_crop_box(img)

        # Subcase B1: AI failed, unconfigured, or timed out
        if not ai_res.get("success"):
            crop_status = ai_res.get("crop_status", "ai_failed")
            reason_msg = ai_res.get("reason") or "AI Smart Crop unavailable — full frame preserved."

            if allow_deterministic_fallback:
                return self._fallback_smart_crop(img, reject_reason=reason_msg, detected_faces=detected_faces)

            # Strict Safety: Fail safely to FULL FRAME (do NOT silently crop)
            return img.copy(), {
                "enabled": True,
                "source": "stage2_balanced",
                "applied": False,
                "crop_status": crop_status,
                "crop_source": "none",
                "crop_box": {"ymin": 0.0, "xmin": 0.0, "ymax": 1.0, "xmax": 1.0},
                "ymin": 0.0,
                "xmin": 0.0,
                "ymax": 1.0,
                "xmax": 1.0,
                "original_width": int(w),
                "original_height": int(h),
                "cropped_width": int(w),
                "cropped_height": int(h),
                "crop_area_ratio": 1.0,
                "reason": f"AI Smart Crop unavailable ({ai_res.get('api_error') or reason_msg}) — Full frame preserved.",
                "api_error": ai_res.get("api_error"),
                "fallback_used": False,
                "method": "Full Frame (AI Unavailable)",
                "trim_x_pct": 0,
                "trim_y_pct": 0,
                "original_size": f"{w}x{h}",
                "cropped_size": f"{w}x{h}",
                "notes": "No crop applied when AI was unavailable — composition preserved",
                "model": self.model,
                "latency_ms": ai_res.get("latency_ms", 0)
            }

        # Subcase B2: AI succeeded -> validate coordinates against safety gates
        crop_box = ai_res.get("crop_box")
        is_valid, validation_reason, box_data = self.validate_crop_safety(
            crop_box, w, h, detected_faces=detected_faces
        )

        if not is_valid or box_data is None:
            # Strict Safety: Reject invalid AI crop and preserve FULL FRAME
            return img.copy(), {
                "enabled": True,
                "source": "stage2_balanced",
                "applied": False,
                "crop_status": "ai_rejected",
                "crop_source": "none",
                "crop_box": {"ymin": 0.0, "xmin": 0.0, "ymax": 1.0, "xmax": 1.0},
                "ymin": 0.0,
                "xmin": 0.0,
                "ymax": 1.0,
                "xmax": 1.0,
                "original_width": int(w),
                "original_height": int(h),
                "cropped_width": int(w),
                "cropped_height": int(h),
                "crop_area_ratio": 1.0,
                "reason": f"AI Crop rejected ({validation_reason}) — Full frame preserved.",
                "api_error": None,
                "fallback_used": False,
                "method": "Full Frame (AI Crop Rejected)",
                "trim_x_pct": 0,
                "trim_y_pct": 0,
                "original_size": f"{w}x{h}",
                "cropped_size": f"{w}x{h}",
                "notes": f"Safety gate rejected proposed crop: {validation_reason}",
                "model": self.model,
                "latency_ms": ai_res.get("latency_ms", 0)
            }

        # Subcase B3: Valid AI crop -> perform local spatial crop
        y1, y2, x1, x2, w_ratio, h_ratio, area_ratio = box_data
        ymin, xmin, ymax, xmax = crop_box
        crop_w = x2 - x1
        crop_h = y2 - y1

        cropped = img[y1:y2, x1:x2].copy()
        trim_x = int(((w - crop_w) / w) * 100)
        trim_y = int(((h - crop_h) / h) * 100)

        telemetry = {
            "enabled": True,
            "source": "stage2_balanced",
            "applied": True,
            "crop_status": "ai_crop",
            "crop_source": "ai",
            "crop_box": {
                "ymin": round(float(ymin), 4),
                "xmin": round(float(xmin), 4),
                "ymax": round(float(ymax), 4),
                "xmax": round(float(xmax), 4)
            },
            "ymin": round(float(ymin), 4),
            "xmin": round(float(xmin), 4),
            "ymax": round(float(ymax), 4),
            "xmax": round(float(xmax), 4),
            "original_width": int(w),
            "original_height": int(h),
            "cropped_width": int(crop_w),
            "cropped_height": int(crop_h),
            "crop_area_ratio": round(float(area_ratio), 4),
            "reason": ai_res.get("reason") or "Tightened framing around main subjects and trimmed dead space",
            "api_error": None,
            "fallback_used": False,
            "method": f"OrcaRouter AI ({self.model})",
            "trim_x_pct": trim_x,
            "trim_y_pct": trim_y,
            "original_size": f"{w}x{h}",
            "cropped_size": f"{crop_w}x{crop_h}",
            "notes": "AI Smart Crop applied",
            "model": self.model,
            "latency_ms": ai_res.get("latency_ms", 0)
        }
        return cropped, telemetry

    def _get_ai_crop_box(self, img: np.ndarray) -> Dict[str, Any]:
        """Queries OrcaRouter VLM for landscape framing coordinates."""
        import time

        if not self.api_key or self.api_key == "your_actual_api_key_here" or not self.api_key.strip():
            return {
                "success": False,
                "crop_box": None,
                "reason": "OrcaRouter API key not configured.",
                "api_error": "API key not configured",
                "crop_status": "ai_unavailable",
                "http_status": None,
                "latency_ms": 0
            }

        start_time = time.time()
        try:
            h, w = img.shape[:2]
            thumb_w = 480
            thumb_h = int(h * (480 / w))
            thumb = cv2.resize(img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)

            _, buffer = cv2.imencode(".jpg", thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            base64_image = base64.b64encode(buffer).decode("utf-8")

            prompt = (
                "You are an elite press photojournalist and photo editor. "
                "Analyze this photo and calculate the best professional LANDSCAPE crop. "
                "Trim distracting edges, excessive dead headroom/ceiling, awkward floor space, and peripheral items "
                "so the final framing looks tight, clean, and publication-ready according to the rule of thirds. "
                "IMPORTANT: The final crop area MUST be at least 40% of the image (both width and height >= 0.40). "
                "Respond ONLY with a JSON object in this exact format: "
                "{\"ymin\": 0.10, \"xmin\": 0.05, \"ymax\": 0.95, \"xmax\": 0.90, \"reason\": \"Tightened composition on main subjects and trimmed excess ceiling/wall space.\"}"
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
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 4096,
                "response_format": {"type": "json_object"}
            }

            max_attempts = 4
            last_err_msg = None
            last_status = None

            for attempt in range(max_attempts):
                _GLOBAL_STAGE2_PACER.pace()
                try:
                    response = requests.post(self.api_url, headers=headers, json=payload, timeout=35)
                    last_status = response.status_code
                    latency_ms = int((time.time() - start_time) * 1000)

                    # 1. Check for permanent authentication/billing failure (401, 402, 403)
                    if response.status_code in [401, 402, 403]:
                        err_body = response.text.lower()
                        if response.status_code == 401 or "unauthorized" in err_body or "invalid api key" in err_body:
                            err_msg = "AI API request failed — invalid API key."
                        elif response.status_code == 402 or "credit" in err_body or "balance" in err_body or "quota" in err_body:
                            err_msg = "AI API request failed — insufficient credits."
                        else:
                            err_msg = f"AI API access denied (HTTP {response.status_code})."

                        return {
                            "success": False,
                            "crop_box": None,
                            "reason": err_msg,
                            "api_error": err_msg,
                            "crop_status": "ai_unavailable",
                            "http_status": response.status_code,
                            "latency_ms": latency_ms
                        }

                    # 2. Check for rate limit (429) or transient server errors (5xx)
                    if response.status_code == 429 or (500 <= response.status_code < 600):
                        base_wait = min(30.0, 1.5 * (2 ** attempt) + random.uniform(0.1, 0.4))
                        wait_seconds = parse_retry_after(response, default_backoff=base_wait, max_backoff=30.0)

                        if attempt < max_attempts - 1:
                            time.sleep(wait_seconds)
                            continue

                        # Exhausted retries
                        err_msg = f"AI rate limit exceeded (Groq). Retries exhausted ({max_attempts} attempts)."
                        return {
                            "success": False,
                            "crop_box": None,
                            "reason": err_msg,
                            "api_error": err_msg,
                            "crop_status": "ai_unavailable",
                            "http_status": response.status_code,
                            "latency_ms": latency_ms
                        }

                    # 3. Successful response (200)
                    if response.status_code == 200:
                        res_data = response.json()
                        choice = res_data.get("choices", [{}])[0]
                        msg = choice.get("message", {})
                        content = msg.get("content") or msg.get("reasoning") or ""

                        # Clean markdown code fences if present
                        clean_text = content.strip()
                        if clean_text.startswith("```"):
                            clean_text = clean_text.strip("`")
                            if clean_text.startswith("json"):
                                clean_text = clean_text[4:].strip()

                        # Extract JSON substring
                        if "{" in clean_text and "}" in clean_text:
                            json_str = clean_text[clean_text.find("{"):clean_text.rfind("}")+1]
                            data = json.loads(json_str)
                            ymin = float(data.get("ymin", 0.0))
                            xmin = float(data.get("xmin", 0.0))
                            ymax = float(data.get("ymax", 1.0))
                            xmax = float(data.get("xmax", 1.0))
                            reason = data.get("reason", "Composition framed for primary subjects")
                            return {
                                "success": True,
                                "crop_box": [ymin, xmin, ymax, xmax],
                                "reason": reason,
                                "api_error": None,
                                "crop_status": "ai_crop",
                                "http_status": 200,
                                "latency_ms": latency_ms
                            }
                        else:
                            last_err_msg = "Malformed JSON from AI"
                    else:
                        last_err_msg = f"HTTP {response.status_code}"

                except Exception as e:
                    last_err_msg = f"Request exception: {type(e).__name__} ({str(e)})"

                if attempt < max_attempts - 1:
                    backoff_time = min(30.0, 1.5 * (2 ** attempt) + random.uniform(0.1, 0.4))
                    time.sleep(backoff_time)

            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "crop_box": None,
                "reason": last_err_msg or "AI communication failure",
                "api_error": last_err_msg or "AI communication failure",
                "crop_status": "ai_failed",
                "http_status": last_status,
                "latency_ms": latency_ms
            }
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "crop_box": None,
                "reason": f"Request exception: {type(e).__name__} ({str(e)})",
                "api_error": f"{type(e).__name__}: {str(e)}",
                "crop_status": "ai_failed",
                "http_status": None,
                "latency_ms": latency_ms
            }

    def _fallback_smart_crop(
        self,
        img: np.ndarray,
        reject_reason: str = "",
        detected_faces: Optional[list] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Explicit Rule of Thirds & Saliency framing fallback:
        Trims 8% ceiling, 5% floor, and 5% side margins by default,
        with subject/face boundary protection.
        """
        h, w = img.shape[:2]
        
        # Base fallback margins: 8% top, 5% bottom, 5% left, 5% right
        ymin, ymax, xmin, xmax = 0.08, 0.95, 0.05, 0.95

        # If faces exist, ensure fallback bounds never violate headroom, chin, or side bounds
        if detected_faces and len(detected_faces) > 0:
            for fx, fy, fw, fh in detected_faces:
                f_top_norm = fy / float(h)
                f_bottom_norm = (fy + fh) / float(h)
                f_left_norm = fx / float(w)
                f_right_norm = (fx + fw) / float(w)
                f_h_norm = fh / float(h)

                headroom_req = max(0.02, 0.15 * f_h_norm)
                chin_req = max(0.05, 0.35 * f_h_norm)

                if ymin > (f_top_norm - headroom_req):
                    ymin = max(0.0, f_top_norm - headroom_req - 0.02)
                if ymax < (f_bottom_norm + chin_req):
                    ymax = min(1.0, f_bottom_norm + chin_req + 0.02)
                if xmin > (f_left_norm - 0.02):
                    xmin = max(0.0, f_left_norm - 0.02)
                if xmax < (f_right_norm + 0.02):
                    xmax = min(1.0, f_right_norm + 0.02)

        y1 = max(0, int(ymin * h))
        y2 = min(h, int(ymax * h))
        x1 = max(0, int(xmin * w))
        x2 = min(w, int(xmax * w))

        crop_w = max(1, x2 - x1)
        crop_h = max(1, y2 - y1)

        cropped = img[y1:y2, x1:x2].copy()
        trim_x = int(((w - crop_w) / w) * 100)
        trim_y = int(((h - crop_h) / h) * 100)
        area_ratio = round(float((crop_w * crop_h) / (w * h)), 4)

        reason = reject_reason if reject_reason else "Rule-of-Thirds Composition Refinement (fallback)"

        telemetry = {
            "enabled": True,
            "source": "stage2_balanced",
            "applied": True,
            "crop_status": "fallback_crop",
            "crop_source": "deterministic_fallback",
            "crop_box": {
                "ymin": round(float(ymin), 4),
                "xmin": round(float(xmin), 4),
                "ymax": round(float(ymax), 4),
                "xmax": round(float(xmax), 4)
            },
            "ymin": round(float(ymin), 4),
            "xmin": round(float(xmin), 4),
            "ymax": round(float(ymax), 4),
            "xmax": round(float(xmax), 4),
            "original_width": int(w),
            "original_height": int(h),
            "cropped_width": int(crop_w),
            "cropped_height": int(crop_h),
            "crop_area_ratio": area_ratio,
            "reason": reason,
            "api_error": None,
            "fallback_used": True,
            "method": "Rule-of-Thirds Composition Refinement (Fallback)",
            "trim_x_pct": trim_x,
            "trim_y_pct": trim_y,
            "original_size": f"{w}x{h}",
            "cropped_size": f"{crop_w}x{crop_h}",
            "notes": "Deterministic Rule-of-Thirds fallback crop applied",
            "model": self.model,
            "latency_ms": 0
        }

        return cropped, telemetry

    @staticmethod
    def apply_manual_crop(
        img: np.ndarray,
        crop_top: float = 0.0,
        crop_bottom: float = 0.0,
        crop_left: float = 0.0,
        crop_right: float = 0.0
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Applies explicit manual normalized crop to the Stage 2 Balanced Buffer.
        Priority 1 in the crop precedence hierarchy.
        """
        if img is None:
            return None, {}

        h, w = img.shape[:2]
        
        ct = np.clip(float(crop_top), 0.0, 0.45)
        cb = np.clip(float(crop_bottom), 0.0, 0.45)
        cl = np.clip(float(crop_left), 0.0, 0.45)
        cr = np.clip(float(crop_right), 0.0, 0.45)

        y1 = int(h * ct)
        y2 = int(h * (1.0 - cb))
        x1 = int(w * cl)
        x2 = int(w * (1.0 - cr))

        crop_w = max(1, x2 - x1)
        crop_h = max(1, y2 - y1)

        cropped = img[y1:y2, x1:x2].copy()
        trim_x = int(((w - crop_w) / w) * 100)
        trim_y = int(((h - crop_h) / h) * 100)
        area_ratio = round(float((crop_w * crop_h) / (w * h)), 4)

        telemetry = {
            "enabled": True,
            "source": "stage2_balanced",
            "applied": True,
            "crop_status": "manual_crop",
            "crop_source": "manual",
            "crop_box": {
                "ymin": round(ct, 4),
                "xmin": round(cl, 4),
                "ymax": round(1.0 - cb, 4),
                "xmax": round(1.0 - cr, 4)
            },
            "ymin": round(ct, 4),
            "xmin": round(cl, 4),
            "ymax": round(1.0 - cb, 4),
            "xmax": round(1.0 - cr, 4),
            "original_width": int(w),
            "original_height": int(h),
            "cropped_width": int(crop_w),
            "cropped_height": int(crop_h),
            "crop_area_ratio": area_ratio,
            "reason": "Manual crop slider adjustments applied (Priority 1)",
            "api_error": None,
            "fallback_used": False,
            "method": "Manual Crop Overrides",
            "trim_x_pct": trim_x,
            "trim_y_pct": trim_y,
            "original_size": f"{w}x{h}",
            "cropped_size": f"{crop_w}x{crop_h}",
            "notes": "User manual crop overrides"
        }

        return cropped, telemetry
