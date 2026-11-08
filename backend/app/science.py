"""Science-core: WCS-WAVE interpolation, A-WCS detector pixel recovery,
SIP-aware alignment, normalization, difference, and contrast stretch.

All math derived from and verified against real SPHEREx cutouts
(docs/service-findings.md §2 and §5).
"""
from __future__ import annotations

import io
import math
import warnings
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

from . import config


@dataclass
class WaveSolution:
    wavelength_um: float
    bandwidth_um: float
    resolving_power: float
    detector: int
    det_x: float
    det_y: float


def build_detector_wcs(header: fits.Header) -> WCS:
    """Build linear 'A' WCS for 0-based active pixel coordinates with SIP stripped.
    Celestial SIP polynomial belongs to celestial WCS only.
    """
    hh = header.copy()
    for k in list(hh.keys()):
        if k[:2] in ("A_", "B_", "AP", "BP") or k in ("A_ORDER", "B_ORDER", "AP_ORDER", "BP_ORDER"):
            del hh[k]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return WCS(hh, key="A", relax=True)


def compute_target_wavelength(
    hdul: fits.HDUList,
    target_ra: float,
    target_dec: float,
) -> WaveSolution:
    """Read celestial WCS + A-WCS + WCS-WAVE node grid to compute real LVF wavelength
    and bandwidth at the target's position on the detector face.
    """
    image_hdu = hdul["IMAGE"]
    hdr = image_hdu.header
    detector = int(hdr.get("DETECTOR", 0))

    # 1. Target coordinate in cutout pixel space (0-based)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        celestial_wcs = WCS(hdr)
        cutout_xy = celestial_wcs.all_world2pix([[target_ra, target_dec]], 0)[0]
    cx, cy = float(cutout_xy[0]), float(cutout_xy[1])

    # 2. Map cutout pixel to full-detector pixel via 'A' WCS
    det_wcs = build_detector_wcs(hdr)
    det_xy = det_wcs.wcs_pix2world([[cx, cy]], 0)[0]
    dx, dy = float(det_xy[0]), float(det_xy[1])

    # SPHEREx detector is 2040x2040
    dx_clamped = max(0.0, min(float(config.DETECTOR_PIXELS - 1), dx))
    dy_clamped = max(0.0, min(float(config.DETECTOR_PIXELS - 1), dy))

    # 3. Interpolate on WCS-WAVE node grid (1-based X/Y nodes)
    table_data = hdul["WCS-WAVE"].data[0]
    nodes_x = np.asarray(table_data["X"], dtype=float)
    nodes_y = np.asarray(table_data["Y"], dtype=float)
    values = np.asarray(table_data["VALUES"], dtype=float)  # (14, 9, 2)

    # Convert 0-based detector pixel to 1-based for node interpolation
    target_node_x = dx_clamped + 1.0
    target_node_y = dy_clamped + 1.0

    def interp2d(plane: np.ndarray) -> float:
        # plane is shape (len(nodes_y), len(nodes_x))
        row_interps = [float(np.interp(target_node_x, nodes_x, plane[j, :])) for j in range(len(nodes_y))]
        return float(np.interp(target_node_y, nodes_y, row_interps))

    wave_um = interp2d(values[:, :, 0])
    bw_um = interp2d(values[:, :, 1])
    r_power = wave_um / bw_um if bw_um > 0 else 0.0

    return WaveSolution(
        wavelength_um=wave_um,
        bandwidth_um=bw_um,
        resolving_power=r_power,
        detector=detector,
        det_x=dx,
        det_y=dy,
    )


def match_spectral_channels(
    frames: list[dict],
    target_wavelength_um: Optional[float] = None,
    tolerance_bandwidths: float = config.DEFAULT_TOLERANCE_BANDWIDTHS,
) -> tuple[list[dict], dict]:
    """Group frames by matching per-pixel wavelength within tolerance.
    NEVER silently mix bands. If no match, returns ([], diagnostic).
    """
    if not frames:
        return [], {"error": "no_frames", "message": "No frames provided"}

    # Sort chronologically
    sorted_frames = sorted(frames, key=lambda f: f.get("mjd", 0.0))

    # Choose anchor wavelength
    if target_wavelength_um is not None:
        anchor_wave = target_wavelength_um
        # Find representative bandwidth near anchor
        bws = [f["bandwidth_um"] for f in sorted_frames if f.get("bandwidth_um")]
        ref_bw = float(np.median(bws)) if bws else 0.05
    else:
        # Default anchor is the earliest frame
        anchor = sorted_frames[0]
        anchor_wave = anchor["wavelength_um"]
        ref_bw = anchor["bandwidth_um"]

    tol_um = tolerance_bandwidths * ref_bw

    matched = []
    rejected = []
    for f in sorted_frames:
        diff_um = abs(f["wavelength_um"] - anchor_wave)
        diff_bw = diff_um / ref_bw if ref_bw > 0 else 999.0
        if diff_um <= tol_um:
            matched.append(f)
        else:
            rejected.append({
                "obs_id": f.get("obs_id"),
                "wavelength_um": f.get("wavelength_um"),
                "diff_bandwidths": round(diff_bw, 2),
            })

    diagnostic = {
        "anchor_wavelength_um": anchor_wave,
        "reference_bandwidth_um": ref_bw,
        "tolerance_um": tol_um,
        "tolerance_bandwidths": tolerance_bandwidths,
        "matched_count": len(matched),
        "total_count": len(frames),
        "rejected": rejected[:5],
    }
    return matched, diagnostic


def apply_stretch(
    data: np.ndarray,
    stretch: str = "asinh",
    pmin: float = 1.0,
    pmax: float = 99.5,
) -> np.ndarray:
    """Convert float surface-brightness image (MJy/sr) into 8-bit grayscale [0..255].
    Handles NaNs, infinities, robust percentile clipping.
    """
    arr = np.nan_to_num(data.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return np.zeros(arr.shape, dtype=np.uint8)

    vmin = float(np.percentile(valid, pmin))
    vmax = float(np.percentile(valid, pmax))
    if vmax <= vmin:
        vmax = vmin + 1e-6

    clipped = np.clip(arr, vmin, vmax)
    norm = (clipped - vmin) / (vmax - vmin)

    if stretch == "asinh":
        # asinh stretch preserves highlights without blowing cores
        beta = 0.05
        stretched = np.arcsinh(norm / beta) / np.arcsinh(1.0 / beta)
    elif stretch == "log":
        stretched = np.log1p(norm * 9.0) / np.log(10.0)
    else:  # linear
        stretched = norm

    return (np.clip(stretched, 0.0, 1.0) * 255.0).astype(np.uint8)


def compute_difference_frame(
    data_a: np.ndarray,
    data_b: np.ndarray,
    stretch: str = "linear",
) -> np.ndarray:
    """Subtract two photometrically calibrated frames (both in MJy/sr).
    Zero difference mapped to neutral mid-gray (128).
    Bright source at epoch A -> bright white; at epoch B -> dark black.
    """
    diff = data_b.astype(np.float32) - data_a.astype(np.float32)
    diff_valid = diff[np.isfinite(diff)]
    if diff_valid.size == 0 or np.all(diff_valid == 0.0):
        return np.full(diff.shape, 128, dtype=np.uint8)

    med = float(np.median(diff_valid))
    mad = float(np.median(np.abs(diff_valid - med)))
    scale = 5.0 * mad if mad > 0 else 1.0

    norm = np.clip((diff - med) / (2.0 * scale), -0.5, 0.5) + 0.5
    return (norm * 255.0 + 0.5).astype(np.uint8)


def render_png(img_uint8: np.ndarray) -> bytes:
    """Encode 2D uint8 numpy array to PNG bytes in memory."""
    # FITS image array typically has Y=0 at bottom; PIL expects Y=0 at top
    flipped = np.flipud(img_uint8)
    im = Image.fromarray(flipped, mode="L")
    bio = io.BytesIO()
    im.save(bio, format="PNG", optimize=True)
    return bio.getvalue()


# False-colour mapping across the SPHEREx D1-D6 range (0.75 - 5.0 um).
# Shorter wavelength -> bluish, longer wavelength -> reddish. Value carries
# the surface brightness, so the source structure stays visible.
_WAVE_MIN_UM = 0.75
_WAVE_MAX_UM = 5.0


def wavelength_to_rgb(wavelength_um: float) -> tuple[float, float, float]:
    """Map a wavelength in µm to a false-colour base tint (R,G,B in 0..1)."""
    import colorsys
    t = (wavelength_um - _WAVE_MIN_UM) / (_WAVE_MAX_UM - _WAVE_MIN_UM)
    t = max(0.0, min(1.0, t))
    # 0.66 (blue) at short wave -> 0.0 (red) at long wave
    hue = (1.0 - t) * 0.66
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
    return (r, g, b)


def render_png_color(img_uint8: np.ndarray, wavelength_um: float) -> bytes:
    """Render an 8-bit science frame as a wavelength-coded false-colour RGB PNG."""
    r, g, b = wavelength_to_rgb(wavelength_um)
    arr = np.flipud(img_uint8)
    norm = arr.astype(np.float32) / 255.0
    rgb = np.zeros((*norm.shape, 3), dtype=np.uint8)
    rgb[:, :, 0] = np.clip(norm * r * 255.0, 0, 255).astype(np.uint8)
    rgb[:, :, 1] = np.clip(norm * g * 255.0, 0, 255).astype(np.uint8)
    rgb[:, :, 2] = np.clip(norm * b * 255.0, 0, 255).astype(np.uint8)
    im = Image.fromarray(rgb, mode="RGB")
    bio = io.BytesIO()
    im.save(bio, format="PNG", optimize=True)
    return bio.getvalue()
