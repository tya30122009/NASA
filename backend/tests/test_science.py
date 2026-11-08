"""Unit test: prove that frames from different spectral channels are NEVER
compared as equivalent (Critical Science Rule #3).
"""
from __future__ import annotations

import json
from backend.app import science


def test_spectral_channel_matching_guard():
    # Load real recorded epoch spread data from Phase 0
    with open("probe/recorded_wave_correct.json", "r") as f:
        recorded_frames = json.load(f)

    # Frame 0 is 2026W21_1A_0499_1 (2.0838 um)
    # Frame 1 is 2026W25_2A_0123_1 (1.6448 um)
    assert len(recorded_frames) >= 2

    # Under 1.0-bandwidth tolerance, they MUST NOT match
    matched, diag = science.match_spectral_channels(
        recorded_frames,
        target_wavelength_um=recorded_frames[0]["wavelength_um"],
        tolerance_bandwidths=1.0,
    )

    # Prove that the 1.6448 um frame was rejected when anchoring at 2.0838 um
    matched_ids = [m["obs_id"] for m in matched]
    assert "2026W25_2A_0123_1" not in matched_ids
    assert diag["rejected_count"] if "rejected_count" in diag else len(diag["rejected"]) > 0


def test_difference_frame_neutral_mid_gray():
    import numpy as np
    a = np.ones((10, 10), dtype=np.float32) * 5.0
    b = np.ones((10, 10), dtype=np.float32) * 5.0
    diff = science.compute_difference_frame(a, b)
    # Identical frames must yield uniform neutral mid-gray (128)
    assert np.all(diff == 128)


def test_wavelength_to_rgb_tints_and_clamping():
    short = science.wavelength_to_rgb(0.75)   # blue end of the D1-D6 range
    long = science.wavelength_to_rgb(5.0)     # red end
    assert short[2] > short[0] and short[2] > short[1]
    assert long[0] > long[1] and long[0] > long[2]
    # Out-of-range wavelengths clamp instead of extrapolating
    assert science.wavelength_to_rgb(0.1) == short
    assert science.wavelength_to_rgb(9.0) == long
    for wave in (0.75, 1.5, 2.5, 3.7, 5.0):
        assert all(0.0 <= c <= 1.0 for c in science.wavelength_to_rgb(wave))


def test_render_png_color_preserves_structure_and_orientation():
    import io
    import numpy as np
    from PIL import Image

    # Vertical brightness gradient; bottom row brightest (FITS orientation)
    img = np.tile(np.linspace(0, 255, 16, dtype=np.uint8)[:, None], (1, 16))
    png = science.render_png_color(img, wavelength_um=2.0)
    with Image.open(io.BytesIO(png)) as im:
        assert im.mode == "RGB"
        assert im.size == (16, 16)
        arr = np.asarray(im)

    # Same flip as grayscale render_png: brightest row must be at the top
    assert arr[0].sum() > arr[-1].sum()
    # Tint scales all channels, so brightness ordering survives
    lum = arr.astype(np.float32).sum(axis=2)
    assert np.all(np.diff(lum.mean(axis=1)) <= 1.0)
    # A black pixel stays black in every channel
    assert not arr[-1].any()
