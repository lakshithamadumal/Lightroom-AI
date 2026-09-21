"""
Lightroom AI - Studio Edition 2.0
Production-Grade 32-Bit Floating Point 3D LUT Engine

Features:
- Native 32-bit floating point precision throughout the pipeline.
- High-performance vectorized trilinear interpolation (no stair-stepping/banding).
- Full 64^3 (262,144 points), 33^3, and arbitrary-sized 3D LUT support.
- Full .cube file reader and writer with validation.
- Full Hald CLUT (Level 8 = 512x512, Level 16, Level N) decoder and encoder.
- Identity LUT generation for reference calibration.
- Full alpha-channel preservation (RGBA / BGRA).
- Out-of-range value handling and safe gamut clipping at final stage only.
"""

import os
import re
import cv2
import numpy as np
from typing import Tuple, Optional, Union


class Lut3D:
    """
    Encapsulates a 3D Color Lookup Table (RGB -> RGB) stored as a float32 array
    of shape (size, size, size, 3), indexed by [r_idx, g_idx, b_idx].
    All color channels are normalized to [0.0, 1.0].
    """

    def __init__(self, size: int = 64, table: Optional[np.ndarray] = None, title: str = "3D LUT"):
        self.size = size
        self.title = title
        if table is not None:
            if table.shape != (size, size, size, 3):
                raise ValueError(f"Table shape {table.shape} does not match size ({size}, {size}, {size}, 3)")
            self.table = table.astype(np.float32)
        else:
            self.table = self._generate_identity_table(size)

    @staticmethod
    def _generate_identity_table(size: int) -> np.ndarray:
        """Generates a pure 3D identity lattice where output RGB == input RGB."""
        coords = np.linspace(0.0, 1.0, size, dtype=np.float32)
        # r: axis 0, g: axis 1, b: axis 2
        r_grid, g_grid, b_grid = np.meshgrid(coords, coords, coords, indexing='ij')
        table = np.stack([r_grid, g_grid, b_grid], axis=-1).astype(np.float32)
        return table

    @classmethod
    def create_identity(cls, size: int = 64, title: str = "Identity 3D LUT") -> "Lut3D":
        return cls(size=size, title=title)

    @classmethod
    def from_cube_file(cls, filepath: str) -> "Lut3D":
        """Parses an Adobe / DaVinci .cube 3D LUT file."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f".cube file not found: {filepath}")

        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        size = None
        title = os.path.splitext(os.path.basename(filepath))[0]
        data_lines = []

        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith('#'):
                continue
            if line_str.startswith('TITLE'):
                parts = line_str.split(None, 1)
                if len(parts) > 1:
                    title = parts[1].strip('"\'')
                continue
            if line_str.startswith('LUT_3D_SIZE'):
                parts = line_str.split()
                size = int(parts[1])
                continue
            if line_str.startswith('LUT_1D_SIZE') or line_str.startswith('LUT_2D_SIZE'):
                raise ValueError(f"Only 3D LUTs are supported. Found: {line_str}")
            if line_str.startswith('DOMAIN_MIN') or line_str.startswith('DOMAIN_MAX'):
                continue  # Handled as standard [0, 1]

            # Read RGB float triplets
            parts = line_str.split()
            if len(parts) >= 3:
                try:
                    r, g, b = float(parts[0]), float(parts[1]), float(parts[2])
                    data_lines.append((r, g, b))
                except ValueError:
                    continue

        if size is None:
            # Estimate size from data count: N^3 == len(data_lines)
            total = len(data_lines)
            cube_root = round(total ** (1.0 / 3.0))
            if cube_root ** 3 == total:
                size = cube_root
            else:
                raise ValueError(f"Could not determine LUT_3D_SIZE from header and point count ({total})")

        expected_count = size ** 3
        if len(data_lines) != expected_count:
            raise ValueError(f"Expected {expected_count} points for size {size}^3, found {len(data_lines)}")

        raw_array = np.array(data_lines, dtype=np.float32)
        # .cube specification order: R iterates fastest, then G, then B.
        # Reshape to (B, G, R, 3) and transpose to (R, G, B, 3) for standard [r, g, b] indexing
        table_bgr = raw_array.reshape((size, size, size, 3))
        table_rgb = np.transpose(table_bgr, (2, 1, 0, 3))

        return cls(size=size, table=table_rgb, title=title)

    def to_cube_file(self, filepath: str, title: Optional[str] = None):
        """Saves the 3D LUT to a standardized Adobe .cube file."""
        lut_title = title or self.title
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        size = self.size

        # Invert transpose to (B, G, R, 3) where R changes fastest
        table_bgr = np.transpose(self.table, (2, 1, 0, 3))
        data_flat = table_bgr.reshape((-1, 3))

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Created by Lightroom AI Studio 2.0 Color Engine\n")
            f.write(f"TITLE \"{lut_title}\"\n")
            f.write(f"LUT_3D_SIZE {size}\n")
            f.write(f"DOMAIN_MIN 0.0 0.0 0.0\n")
            f.write(f"DOMAIN_MAX 1.0 1.0 1.0\n\n")
            for r, g, b in data_flat:
                f.write(f"{r:.6f} {g:.6f} {b:.6f}\n")

    @classmethod
    def from_hald_image(cls, hald_img: np.ndarray, level: int = 8, title: str = "Hald 3D LUT") -> "Lut3D":
        """
        Decodes a 2D Hald CLUT image into a 3D LUT.
        Hald Level 8 has dimensions 512x512 with grid size 64^3 (level^2 = 64).
        Supports both 8-bit and 16-bit / 32-bit float Hald images.
        """
        if hald_img is None:
            raise ValueError("Input Hald image is None")

        if hald_img.ndim == 2:
            hald_img = cv2.cvtColor(hald_img, cv2.COLOR_GRAY2RGB)
        elif hald_img.shape[2] == 4:
            hald_img = cv2.cvtColor(hald_img, cv2.COLOR_RGBA2RGB)

        h, w = hald_img.shape[:2]
        size = level * level  # e.g., 8*8 = 64
        expected_dim = level * size  # e.g., 8*64 = 512

        if h != expected_dim or w != expected_dim:
            # Resize if slightly off
            hald_img = cv2.resize(hald_img, (expected_dim, expected_dim), interpolation=cv2.INTER_LANCZOS4)

        # Normalize to float32 [0.0, 1.0]
        if hald_img.dtype == np.uint8:
            hald_norm = hald_img.astype(np.float32) / 255.0
        elif hald_img.dtype == np.uint16:
            hald_norm = hald_img.astype(np.float32) / 65535.0
        else:
            hald_norm = hald_img.astype(np.float32)

        # Build 3D array of shape (size, size, size, 3) indexed by [r, g, b]
        # In Hald layout:
        # For a given (r, g, b) grid coordinate:
        # y = (b // level) * size + g
        # x = (b % level) * size + r
        table = np.zeros((size, size, size, 3), dtype=np.float32)

        for b in range(size):
            y_start = (b // level) * size
            x_start = (b % level) * size
            tile = hald_norm[y_start:y_start + size, x_start:x_start + size]  # shape (size, size, 3), y=g, x=r
            # tile is indexed by [g, r, :]
            # Transpose to [r, g, :] and store at table[:, :, b, :]
            table[:, :, b, :] = np.transpose(tile, (1, 0, 2))

        return cls(size=size, table=table, title=title)

    @classmethod
    def from_hald_file(cls, filepath: str, level: int = 8) -> "Lut3D":
        """Loads a Hald image file (PNG, TIFF, JPG) into a 3D LUT."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Hald file not found: {filepath}")

        # Try 16-bit uncompressed read first with cv2.IMREAD_UNCHANGED
        img = cv2.imread(filepath, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError(f"Failed to decode Hald image at: {filepath}")

        # Convert OpenCV BGR(A) to RGB(A)
        if img.ndim == 3:
            if img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            elif img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)

        title = os.path.splitext(os.path.basename(filepath))[0]
        return cls.from_hald_image(img, level=level, title=title)

    def to_hald_image(self, level: int = 8, bit_depth: int = 8) -> np.ndarray:
        """
        Encodes the 3D LUT into a 2D Hald CLUT image array (RGB).
        bit_depth: 8 (uint8) or 16 (uint16) or 32 (float32).
        """
        size = self.size
        expected_size = level * level
        if size != expected_size:
            # Resample 3D LUT to expected size if needed
            lut_to_render = self.resample(expected_size)
        else:
            lut_to_render = self

        dim = level * expected_size  # e.g., 512 for level 8
        hald_out = np.zeros((dim, dim, 3), dtype=np.float32)

        for b in range(expected_size):
            y_start = (b // level) * expected_size
            x_start = (b % level) * expected_size
            # table[:, :, b, :] has shape [r, g, 3] -> transpose to [g, r, 3] for image tile
            tile = np.transpose(lut_to_render.table[:, :, b, :], (1, 0, 2))
            hald_out[y_start:y_start + expected_size, x_start:x_start + expected_size] = tile

        if bit_depth == 8:
            return np.clip(np.round(hald_out * 255.0), 0, 255).astype(np.uint8)
        elif bit_depth == 16:
            return np.clip(np.round(hald_out * 65535.0), 0, 65535).astype(np.uint16)
        else:
            return hald_out

    def to_hald_file(self, filepath: str, level: int = 8, bit_depth: int = 8):
        """Saves Hald CLUT as PNG or TIFF."""
        hald_rgb = self.to_hald_image(level=level, bit_depth=bit_depth)
        hald_bgr = cv2.cvtColor(hald_rgb, cv2.COLOR_RGB2BGR)
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        cv2.imwrite(filepath, hald_bgr)

    def resample(self, new_size: int) -> "Lut3D":
        """Resamples the 3D LUT to a new grid dimension using trilinear interpolation."""
        if new_size == self.size:
            return Lut3D(size=self.size, table=self.table.copy(), title=self.title)

        identity_new = Lut3D.create_identity(size=new_size)
        resampled_table = LutEngine.apply_lut_3d(identity_new.table, self)
        return Lut3D(size=new_size, table=resampled_table, title=f"{self.title}_resampled_{new_size}")


class LutEngine:
    """
    High-Performance Vectorized 3D LUT Evaluation Engine.
    Executes sub-cell trilinear interpolation in 32-bit floating point space.
    """

    @staticmethod
    def apply_lut_3d(image: np.ndarray, lut: Lut3D, is_bgr: bool = False) -> np.ndarray:
        """
        Applies a 3D LUT to an image with full sub-cell trilinear interpolation.
        
        Parameters:
        - image: np.ndarray of shape (H, W, 3) or (H, W, 4) or (..., 3) in float32 [0.0, 1.0] or uint8/uint16.
        - lut: Lut3D object with table shape (N, N, N, 3) indexed by [r, g, b].
        - is_bgr: True if channels are ordered Blue, Green, Red (OpenCV standard).
        
        Returns:
        - Transformed image matching input dtype and channel count.
        """
        orig_dtype = image.dtype
        orig_shape = image.shape
        has_alpha = len(orig_shape) >= 3 and orig_shape[-1] == 4

        # Separate alpha channel if present
        if has_alpha:
            alpha = image[..., 3]
            color_channels = image[..., :3]
            if orig_dtype == np.uint8:
                alpha_norm = alpha.astype(np.float32) / 255.0
            elif orig_dtype == np.uint16:
                alpha_norm = alpha.astype(np.float32) / 65535.0
            else:
                alpha_norm = alpha.astype(np.float32)
        else:
            alpha_norm = None
            color_channels = image

        # Convert to float32 normalized [0.0, 1.0]
        if orig_dtype == np.uint8:
            img_float = color_channels.astype(np.float32) / 255.0
        elif orig_dtype == np.uint16:
            img_float = color_channels.astype(np.float32) / 65535.0
        else:
            img_float = color_channels.astype(np.float32)

        # Extract normalized R, G, B coordinates
        if is_bgr:
            b_norm = img_float[..., 0]
            g_norm = img_float[..., 1]
            r_norm = img_float[..., 2]
        else:
            r_norm = img_float[..., 0]
            g_norm = img_float[..., 1]
            b_norm = img_float[..., 2]

        N = lut.size
        scale = float(N - 1)

        # Clamp input coords to [0.0, 1.0] for lookup
        r_clamped = np.clip(r_norm, 0.0, 1.0)
        g_clamped = np.clip(g_norm, 0.0, 1.0)
        b_clamped = np.clip(b_norm, 0.0, 1.0)

        # Scale to continuous lattice coordinates [0.0, N-1]
        r_grid = r_clamped * scale
        g_grid = g_clamped * scale
        b_grid = b_clamped * scale

        # Base indices (floor)
        r0 = np.floor(r_grid).astype(np.int32)
        g0 = np.floor(g_grid).astype(np.int32)
        b0 = np.floor(b_grid).astype(np.int32)

        # Ensure bounds for floor
        r0 = np.clip(r0, 0, N - 1)
        g0 = np.clip(g0, 0, N - 1)
        b0 = np.clip(b0, 0, N - 1)

        # Ceiling indices (next lattice point)
        r1 = np.minimum(r0 + 1, N - 1)
        g1 = np.minimum(g0 + 1, N - 1)
        b1 = np.minimum(b0 + 1, N - 1)

        # Sub-cell fractional offsets [0.0, 1.0]
        dr = (r_grid - r0.astype(np.float32))[..., np.newaxis]
        dg = (g_grid - g0.astype(np.float32))[..., np.newaxis]
        db = (b_grid - b0.astype(np.float32))[..., np.newaxis]

        om_dr = 1.0 - dr
        om_dg = 1.0 - dg
        om_db = 1.0 - db

        table = lut.table  # (N, N, N, 3)

        # Fetch 8 bounding cube vertices from 3D lattice
        c000 = table[r0, g0, b0]
        c100 = table[r1, g0, b0]
        c010 = table[r0, g1, b0]
        c110 = table[r1, g1, b0]
        c001 = table[r0, g0, b1]
        c101 = table[r1, g0, b1]
        c011 = table[r0, g1, b1]
        c111 = table[r1, g1, b1]

        # Vectorized trilinear interpolation:
        # Interpolate along R-axis
        c00 = c000 * om_dr + c100 * dr
        c10 = c010 * om_dr + c110 * dr
        c01 = c001 * om_dr + c101 * dr
        c11 = c011 * om_dr + c111 * dr

        # Interpolate along G-axis
        c0 = c00 * om_dg + c10 * dg
        c1 = c01 * om_dg + c11 * dg

        # Interpolate along B-axis
        out_rgb = c0 * om_db + c1 * db

        # Handle BGR channel format
        if is_bgr:
            out_channels = out_rgb[..., ::-1]  # Swap RGB to BGR
        else:
            out_channels = out_rgb

        # Re-attach alpha channel if present
        if has_alpha:
            out_channels = np.concatenate([out_channels, alpha_norm[..., np.newaxis]], axis=-1)

        # Convert back to original dtype
        if orig_dtype == np.uint8:
            return np.clip(np.round(out_channels * 255.0), 0, 255).astype(np.uint8)
        elif orig_dtype == np.uint16:
            return np.clip(np.round(out_channels * 65535.0), 0, 65535).astype(np.uint16)
        else:
            return out_channels.astype(np.float32)
