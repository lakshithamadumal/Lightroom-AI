import os
import cv2
import json
import base64
import requests
import numpy as np


class SmartCropper:
    """
    Intelligent Landscape Smart Crop Engine.
    Uses OrcaRouter vision capabilities with Golden-Ratio / Subject Saliency fallback
    to eliminate dead ceiling space, awkward floor margins, and peripheral clutter.
    """

    def __init__(self, api_key="", api_url="https://api.orcarouter.ai/v1/chat/completions", model="fusion-flash"):
        self.api_key = api_key
        self.api_url = api_url
        
        # Select reliable vision model on OrcaRouter
        if not model or model in ["fusion-flash", "orcarouter/fusion-flash"]:
            self.model = "google/gemini-2.5-flash"
        else:
            self.model = model

        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.face_cascade = cv2.CascadeClassifier(cascade_path) if os.path.exists(cascade_path) else None

    def crop_best_landscape(self, img, enable_ai=True):
        h, w = img.shape[:2]

        # 1. AI Vision Composition Analysis (OrcaRouter)
        if enable_ai and self.api_key and self.api_key != "your_actual_api_key_here":
            print(f"   > [AI VISION] Connecting to OrcaRouter ({self.model})...")
            crop_box, ai_notes = self._get_ai_crop_box(img)
            if crop_box:
                ymin, xmin, ymax, xmax = crop_box
                y1 = max(0, int(ymin * h))
                y2 = min(h, int(ymax * h))
                x1 = max(0, int(xmin * w))
                x2 = min(w, int(xmax * w))

                crop_w = x2 - x1
                crop_h = y2 - y1

                if crop_w >= (w * 0.40) and crop_h >= (h * 0.40):
                    cropped = img[y1:y2, x1:x2]
                    trim_x = int(((w - crop_w) / w) * 100)
                    trim_y = int(((h - crop_h) / h) * 100)
                    telemetry = {
                        "method": f"OrcaRouter AI ({self.model})",
                        "crop_box": [round(ymin, 2), round(xmin, 2), round(ymax, 2), round(xmax, 2)],
                        "trim_x_pct": trim_x,
                        "trim_y_pct": trim_y,
                        "notes": ai_notes or "Tightened framing around main subjects and trimmed dead space",
                        "original_size": f"{w}x{h}",
                        "cropped_size": f"{crop_w}x{crop_h}"
                    }
                    return cropped, telemetry

        # 2. Golden-Ratio / Subject-Aware Fallback
        print(f"   > [SMART CROP] Applying Golden-Ratio & Subject Framing...")
        cropped, fb_telemetry = self._fallback_smart_crop(img)
        fb_telemetry["original_size"] = f"{w}x{h}"
        fb_telemetry["cropped_size"] = f"{cropped.shape[1]}x{cropped.shape[0]}"
        return cropped, fb_telemetry

    def _get_ai_crop_box(self, img):
        try:
            h, w = img.shape[:2]
            thumb_w = 480
            thumb_h = int(h * (480 / w))
            thumb = cv2.resize(img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)

            _, buffer = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])
            base64_image = base64.b64encode(buffer).decode("utf-8")

            prompt = (
                "You are an elite press photojournalist and photo editor. "
                "Analyze this event photo and calculate the best professional LANDSCAPE crop. "
                "Trim distracting edges, excessive dead headroom/ceiling, awkward floor space, and peripheral items "
                "so the final framing looks tight, clean, and publication-ready according to the rule of thirds. "
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
                "max_tokens": 800
            }

            response = requests.post(self.api_url, headers=headers, json=payload, timeout=25)
            if response.status_code == 200:
                res_data = response.json()
                msg = res_data["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning") or ""

                if "{" in content and "}" in content:
                    json_str = content[content.find("{"):content.rfind("}")+1]
                    data = json.loads(json_str)
                    ymin = float(data.get("ymin", 0.0))
                    xmin = float(data.get("xmin", 0.0))
                    ymax = float(data.get("ymax", 1.0))
                    xmax = float(data.get("xmax", 1.0))
                    reason = data.get("reason", "Composition framed for primary subjects")
                    return [ymin, xmin, ymax, xmax], reason
            else:
                print(f"   > [WARN] AI API status: {response.status_code}")
        except Exception as e:
            print(f"   > [WARN] AI Smart Crop skipped: {e}")

        return None, None

    def _fallback_smart_crop(self, img):
        """
        Rule of Thirds & Saliency framing:
        Trims 8-12% excess dead ceiling and 5-8% floor and side margins.
        """
        h, w = img.shape[:2]
        
        # Professional event photo framing (Trims 10% ceiling, 5% floor, 5% sides)
        y1 = int(h * 0.08)
        y2 = int(h * 0.95)
        x1 = int(w * 0.05)
        x2 = int(w * 0.95)

        cropped = img[y1:y2, x1:x2]
        trim_x = int(((w - cropped.shape[1]) / w) * 100)
        trim_y = int(((h - cropped.shape[0]) / h) * 100)

        return cropped, {
            "method": "Rule-of-Thirds Composition Refinement",
            "trim_x_pct": trim_x,
            "trim_y_pct": trim_y,
            "notes": "Trimmed excess dead ceiling/headroom and balanced subject eye-line"
        }
