"""
Lightroom AI - Studio Edition 2.0
Core Auto Adjuster (auto_adjuster.py)
Delegates to the dedicated Stage 2 AI Scene & Exposure Auto-Balancing engine.
"""

import os
import cv2
import numpy as np
from typing import Dict, Any, Tuple, Optional

from stage2_analyzer import Stage2Analyzer
from stage2_adjuster import Stage2Adjuster
from stage2_schema import STAGE2_LIMITS, ZERO_ADJUSTMENTS


class AutoAdjuster:
    """
    Stage 2 AI-Assisted Style-Preserving Auto Balancer.
    Calculates and applies low-amplitude corrective trims (Exposure, WB, Highlights, Shadows)
    strictly on top of the LOCKED Stage 1 Base Buffer.
    """

    def __init__(
        self,
        target_median_lum: float = 126.0,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.target_median_lum = target_median_lum
        self.api_key = os.getenv("ORCA_API_KEY", "") if api_key is None else api_key
        self.api_url = api_url or os.getenv("ORCA_API_URL", "https://api.groq.com/openai/v1/chat/completions")
        self.model = model or os.getenv("ORCA_MODEL", "qwen/qwen3.8-27b")
        self.analyzer = Stage2Analyzer(api_key=self.api_key, api_url=self.api_url, model=self.model)

    def analyze_params(self, stage1_base_bgr: np.ndarray, preset_name: str = "Calibrated Studio Preset", enable_ai: bool = True) -> Dict[str, Any]:
        """
        Analyzes Stage 1 Base develop buffer and returns structured Stage 2 adjustment metadata.
        """
        res = self.analyzer.analyze_stage2(stage1_base_bgr, preset_name=preset_name, enable_ai=enable_ai)
        applied = res.get("adjustments_applied", ZERO_ADJUSTMENTS)

        return {
            "ai_status": res.get("ai_status", "ai_disabled"),
            "exposure": applied.get("exposure_ev", 0.0),
            "contrast": 0.0,
            "shadows": applied.get("shadows", 0.0),
            "highlights": applied.get("highlights", 0.0),
            "temperature": applied.get("temperature", 0.0),
            "tint": applied.get("tint", 0.0),
            "vibrance": 0.0,
            "clarity": 0.0,
            "crop_top": 0.0,
            "crop_bottom": 0.0,
            "crop_left": 0.0,
            "crop_right": 0.0,
            "confidence": res.get("confidence", 0.0),
            "reason": res.get("reason", ""),
            "api_error": res.get("api_error"),
            "model": res.get("model", self.model),
            "latency_ms": res.get("latency_ms", 0),
            "telemetry": res
        }

    def fine_tune(self, stage1_base_bgr: np.ndarray, preset_name: str = "Calibrated Studio Preset", enable_ai: bool = True) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Analyzes and applies Stage 2 adjustments.
        Returns (stage2_balanced_bgr, stage2_metadata).
        """
        analysis = self.analyze_params(stage1_base_bgr, preset_name=preset_name, enable_ai=enable_ai)
        adj_dict = {
            "exposure_ev": analysis["exposure"],
            "temperature": analysis["temperature"],
            "tint": analysis["tint"],
            "highlights": analysis["highlights"],
            "shadows": analysis["shadows"]
        }
        balanced_bgr, _ = Stage2Adjuster.apply_stage2_adjustments(stage1_base_bgr, adj_dict)
        return balanced_bgr, analysis["telemetry"]
