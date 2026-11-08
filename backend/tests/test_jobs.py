"""Colour-toggle pipeline test: switching render mode must re-use the cached
cutout (31-120s to fetch from IRSA), never trigger a re-fetch.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from backend.app import config, jobs, science


def test_color_toggle_rerenders_from_cache_without_refetch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", str(tmp_path))

    raw = np.tile(np.linspace(0.0, 10.0, 20, dtype=np.float32)[:, None], (1, 20))
    raw_path = str(tmp_path / "raw.npy")
    np.save(raw_path, raw)

    stretched = science.apply_stretch(raw, stretch="asinh")
    gray_png = science.render_png(stretched)

    rec = {"obs_id": "test_obs_1", "mjd": 60000.0}
    ckey = jobs.cache_key("cut", rec["obs_id"], 10.0, 20.0, 0.05, "asinh")
    jobs.set_cached(ckey, {
        "obs_id": rec["obs_id"],
        "mjd": rec["mjd"],
        "wavelength_um": 2.0,
        "bandwidth_um": 0.05,
        "png_b64": gray_png.hex(),
        "color": False,
        "raw_path": raw_path,
    })

    def no_network(*args, **kwargs):
        raise AssertionError("colour toggle must not re-fetch from IRSA")

    monkeypatch.setattr(jobs.services, "resolve_datalink_cutout_path", no_network)
    monkeypatch.setattr(jobs.services, "fetch_cutout_fits", no_network)

    mgr = jobs.JobManager()
    frame = mgr._fetch_and_process_frame(rec, 10.0, 20.0, 0.05, "asinh", color=True)

    assert frame is not None
    assert frame["color"] is True
    assert frame["png_b64"] != gray_png.hex()
    with Image.open(io.BytesIO(bytes.fromhex(frame["png_b64"]))) as im:
        assert im.mode == "RGB"

    # Toggling back re-renders the original grayscale PNG, still no network
    back = mgr._fetch_and_process_frame(rec, 10.0, 20.0, 0.05, "asinh", color=False)
    assert back["color"] is False
    assert back["png_b64"] == gray_png.hex()