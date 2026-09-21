"""
Lightroom AI - Studio Edition 2.0
Parametric Spatial Processing Engine (spatial_adjuster.py)

Implements Lightroom-calibrated spatial neighborhood operations in float32:
1. Clarity (Guided-filter local contrast enhancement on Luminance)
2. Texture (Mid-frequency multi-scale Laplacian bandpass filtering)
3. Dehaze (Atmospheric dark channel transmission compensation)
4. Sharpening (Edge-masked unsharp masking)
5. Post-Crop Vignette (Radial Euclidean falloff with midpoint & feather)
6. Film Grain (Midtone-weighted stochastic grain synthesis)
"""

import cv2
import numpy as np
from typing import Dict, Any, Optional


class SpatialAdjuster:
    """Executes spatial frequency, geometric, and noise filter operations."""

    @staticmethod
    def _guided_filter(I: np.ndarray, p: np.ndarray, r: int, eps: float) -> np.ndarray:
        """
        Fast Guided Filter (He, Sun, Tang - TPAMI 2013).
        Smooths image p guided by image I with continuous, gradient-preserving weights.
        Guarantees C-infinity gradient continuity and avoids bilateral filter plateaus.
        """
        ksize = (2 * r + 1, 2 * r + 1)
        mean_I = cv2.boxFilter(I, cv2.CV_32F, ksize)
        mean_p = cv2.boxFilter(p, cv2.CV_32F, ksize)
        mean_Ip = cv2.boxFilter(I * p, cv2.CV_32F, ksize)
        cov_Ip = mean_Ip - mean_I * mean_p

        mean_II = cv2.boxFilter(I * I, cv2.CV_32F, ksize)
        var_I = mean_II - mean_I * mean_I

        a = cov_Ip / (var_I + eps)
        b = mean_p - a * mean_I

        mean_a = cv2.boxFilter(a, cv2.CV_32F, ksize)
        mean_b = cv2.boxFilter(b, cv2.CV_32F, ksize)

        q = mean_a * I + mean_b
        return q

    @classmethod
    def apply_clarity(cls, image_bgr: np.ndarray, amount: float) -> np.ndarray:
        """
        Applies edge-preserving local contrast (Clarity) on Luminance channel using Guided Filtering.
        amount: -100 to +100
        """
        if amount == 0:
            return image_bgr

        img_f = image_bgr.astype(np.float32) / 255.0
        lab = cv2.cvtColor(img_f, cv2.COLOR_BGR2LAB)
        l_chan = lab[:, :, 0]  # [0.0, 100.0]
        l_norm = l_chan / 100.0

        # Continuous Guided Filter base layer calculation
        # Radius adaptive to image resolution
        h, w = image_bgr.shape[:2]
        radius = max(5, int(min(h, w) * 0.02))

        # Epsilon controls edge preservation smoothness
        eps = 0.04

        base_norm = cls._guided_filter(l_norm, l_norm, radius, eps)
        base = base_norm * 100.0
        detail = l_chan - base

        # Boost or reduce local detail
        scale = amount / 100.0
        l_new = np.clip(l_chan + detail * scale * 1.25, 0.0, 100.0)

        lab[:, :, 0] = l_new
        out_bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        return np.clip(out_bgr * 255.0, 0, 255).astype(image_bgr.dtype)

    @staticmethod
    def apply_texture(image_bgr: np.ndarray, amount: float) -> np.ndarray:
        """
        Applies mid-frequency bandpass enhancement (Texture).
        Affects pores, fabric, and fine surfaces without creating large halos.
        amount: -100 to +100
        """
        if amount == 0:
            return image_bgr

        img_f = image_bgr.astype(np.float32) / 255.0
        lab = cv2.cvtColor(img_f, cv2.COLOR_BGR2LAB)
        l_chan = lab[:, :, 0]

        # Multi-scale decomposition: Fine blur (sigma=1.2) vs Medium blur (sigma=3.5)
        blur_fine = cv2.GaussianBlur(l_chan, (0, 0), sigmaX=1.2, sigmaY=1.2)
        blur_med = cv2.GaussianBlur(l_chan, (0, 0), sigmaX=3.8, sigmaY=3.8)

        # Mid-frequency bandpass layer
        mid_freq = blur_fine - blur_med

        scale = amount / 100.0
        l_new = np.clip(l_chan + mid_freq * scale * 1.5, 0.0, 100.0)

        lab[:, :, 0] = l_new
        out_bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        return np.clip(out_bgr * 255.0, 0, 255).astype(image_bgr.dtype)

    @staticmethod
    def apply_dehaze(image_bgr: np.ndarray, amount: float) -> np.ndarray:
        """
        Applies atmospheric haze reduction or addition.
        amount: -100 to +100
        """
        if amount == 0:
            return image_bgr

        img_f = image_bgr.astype(np.float32) / 255.0
        # Estimate dark channel
        min_chan = np.min(img_f, axis=2)
        kernel_size = max(5, int(min(image_bgr.shape[:2]) * 0.01) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
        dark_channel = cv2.erode(min_chan, kernel)

        # Estimate transmission map
        omega = 0.75 * (amount / 100.0)
        transmission = np.clip(1.0 - (omega * dark_channel), 0.25, 1.0)
        transmission_smooth = cv2.GaussianBlur(transmission, (0, 0), sigmaX=kernel_size * 2)

        # Atmospheric airlight estimation (brightest pixels in dark channel)
        airlight = np.array([0.9, 0.9, 0.9], dtype=np.float32)

        if amount > 0:
            dehazed = (img_f - airlight) / np.maximum(transmission_smooth[:, :, np.newaxis], 0.3) + airlight
        else:
            dehazed = img_f * (1.0 + (abs(amount) / 100.0) * 0.3)

        out_bgr = np.clip(dehazed, 0.0, 1.0) * 255.0
        return out_bgr.astype(image_bgr.dtype)

    @staticmethod
    def apply_sharpening(
        image_bgr: np.ndarray,
        amount: float = 40.0,
        radius: float = 1.0,
        detail: float = 25.0,
        masking: float = 0.0
    ) -> np.ndarray:
        """
        Applies unsharp masking with edge masking.
        amount: 0 to 150
        radius: 0.5 to 3.0
        detail: 0 to 100
        masking: 0 to 100 (thresholds sharpening to high-contrast edges only)
        """
        if amount <= 0:
            return image_bgr

        img_f = image_bgr.astype(np.float32)
        blurred = cv2.GaussianBlur(img_f, (0, 0), sigmaX=radius, sigmaY=radius)
        high_pass = img_f - blurred

        # High-pass weight
        strength = (amount / 100.0) * (1.0 + (detail / 100.0) * 0.5)

        # Edge masking using Sobel gradient
        if masking > 0:
            gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
            grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            magnitude = np.sqrt(grad_x ** 2 + grad_y ** 2)
            mag_norm = np.clip(magnitude / 255.0, 0.0, 1.0)
            threshold = (masking / 100.0) * 0.25
            edge_mask = np.clip((mag_norm - threshold) / (1.0 - threshold + 1e-5), 0.0, 1.0)
            edge_mask_3c = edge_mask[:, :, np.newaxis]
            sharpened = img_f + high_pass * strength * edge_mask_3c
        else:
            sharpened = img_f + high_pass * strength

        return np.clip(sharpened, 0, 255).astype(image_bgr.dtype)

    @staticmethod
    def apply_vignette(
        image_bgr: np.ndarray,
        amount: float = -15.0,
        midpoint: float = 50.0,
        feather: float = 50.0,
        roundness: float = 0.0
    ) -> np.ndarray:
        """
        Applies post-crop radial vignette.
        amount: -100 (darken) to +100 (brighten)
        midpoint: 0 to 100 (inner circle size)
        feather: 0 to 100 (edge softness)
        roundness: -100 (rectangular) to +100 (circular)
        """
        if amount == 0:
            return image_bgr

        h, w = image_bgr.shape[:2]
        Y, X = np.ogrid[:h, :w]
        center_y, center_x = h / 2.0, w / 2.0

        # Aspect ratio compensation for roundness
        norm_x = (X - center_x) / center_x
        norm_y = (Y - center_y) / center_y

        r_factor = 1.0 + (roundness / 100.0) * (w / h - 1.0)
        norm_x_adj = norm_x / max(r_factor, 0.2)

        dist = np.sqrt(norm_x_adj ** 2 + norm_y ** 2)

        # Midpoint and feather mapping
        r_inner = (midpoint / 100.0) * 0.6
        r_outer = r_inner + (feather / 100.0) * 0.8 + 0.2

        vig_ramp = np.clip((dist - r_inner) / (r_outer - r_inner + 1e-5), 0.0, 1.0)
        vig_smooth = vig_ramp * vig_ramp * (3.0 - 2.0 * vig_ramp)  # Smoothstep

        scale = (amount / 100.0) * 0.6
        vig_mult = 1.0 + (scale * vig_smooth)
        vig_mult = np.clip(vig_mult, 0.0, 2.0)[:, :, np.newaxis]

        out_bgr = image_bgr.astype(np.float32) * vig_mult
        return np.clip(out_bgr, 0, 255).astype(image_bgr.dtype)

    @staticmethod
    def apply_grain(
        image_bgr: np.ndarray,
        amount: float = 20.0,
        size: float = 25.0,
        frequency: float = 50.0
    ) -> np.ndarray:
        """
        Synthesizes film grain weighted by midtone luminance.
        amount: 0 to 100
        size: 0 to 100
        """
        if amount <= 0:
            return image_bgr

        h, w = image_bgr.shape[:2]
        # Generate base Gaussian noise
        noise_scale = 1.0 + (size / 100.0) * 1.5
        down_h = max(16, int(h / noise_scale))
        down_w = max(16, int(w / noise_scale))

        np.random.seed(int((h * w) % 100000))
        raw_noise = np.random.normal(0.0, 1.0, (down_h, down_w)).astype(np.float32)
        noise_resized = cv2.resize(raw_noise, (w, h), interpolation=cv2.INTER_LINEAR)

        # Weight noise by midtone curve: 1.0 at 0.5, 0.0 at 0.0 and 1.0
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        midtone_weight = 4.0 * gray * (1.0 - gray)  # Parabolic curve peaking at 0.5

        noise_intensity = (amount / 100.0) * 22.0
        applied_noise = noise_resized * midtone_weight * noise_intensity

        img_f = image_bgr.astype(np.float32) + applied_noise[:, :, np.newaxis]
        return np.clip(img_f, 0, 255).astype(image_bgr.dtype)

    @classmethod
    def apply_spatial_bundle(cls, image_bgr: np.ndarray, spatial_params: Dict[str, Any]) -> np.ndarray:
        """Executes all active spatial parameters in sequence."""
        if not spatial_params:
            return image_bgr

        res = image_bgr

        # 1. Texture
        texture_amt = spatial_params.get("texture", 0.0)
        if texture_amt != 0:
            res = cls.apply_texture(res, texture_amt)

        # 2. Clarity
        clarity_amt = spatial_params.get("clarity", 0.0)
        if clarity_amt != 0:
            res = cls.apply_clarity(res, clarity_amt)

        # 3. Dehaze
        dehaze_amt = spatial_params.get("dehaze", 0.0)
        if dehaze_amt != 0:
            res = cls.apply_dehaze(res, dehaze_amt)

        # 4. Sharpening
        sharp_cfg = spatial_params.get("sharpening", {})
        if isinstance(sharp_cfg, dict):
            s_amt = sharp_cfg.get("amount", 0.0)
            if s_amt > 0:
                res = cls.apply_sharpening(
                    res,
                    amount=s_amt,
                    radius=sharp_cfg.get("radius", 1.0),
                    detail=sharp_cfg.get("detail", 25.0),
                    masking=sharp_cfg.get("masking", 0.0)
                )

        # 5. Vignette
        vig_cfg = spatial_params.get("vignette", {})
        if isinstance(vig_cfg, dict):
            v_amt = vig_cfg.get("amount", 0.0)
            if v_amt != 0:
                res = cls.apply_vignette(
                    res,
                    amount=v_amt,
                    midpoint=vig_cfg.get("midpoint", 50.0),
                    feather=vig_cfg.get("feather", 50.0),
                    roundness=vig_cfg.get("roundness", 0.0)
                )
        elif isinstance(vig_cfg, (int, float)) and vig_cfg != 0:
            res = cls.apply_vignette(res, amount=float(vig_cfg))

        # 6. Grain
        grain_cfg = spatial_params.get("grain", {})
        if isinstance(grain_cfg, dict):
            g_amt = grain_cfg.get("amount", 0.0)
            if g_amt > 0:
                res = cls.apply_grain(
                    res,
                    amount=g_amt,
                    size=grain_cfg.get("size", 25.0),
                    frequency=grain_cfg.get("frequency", 50.0)
                )
        elif isinstance(grain_cfg, (int, float)) and grain_cfg > 0:
            res = cls.apply_grain(res, amount=float(grain_cfg))

        return res
