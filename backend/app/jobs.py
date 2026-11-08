"""On-disk cache for cutouts and parsed frames, and background job queue
for long-running cutout fetches (31-120s each).
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from astropy.io import fits
import numpy as np

from . import config, science, services


os.makedirs(config.CACHE_DIR, exist_ok=True)


def cache_key(prefix: str, *args) -> str:
    h = hashlib.sha256()
    h.update(prefix.encode())
    for a in args:
        h.update(str(a).encode())
    return h.hexdigest()[:24]


def get_cached(key: str) -> Optional[dict]:
    path = os.path.join(config.CACHE_DIR, f"{key}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("_saved_at", 0) > config.CACHE_TTL_SECONDS:
            os.remove(path)
            return None
        return data
    except Exception:
        return None


def set_cached(key: str, data: dict):
    path = os.path.join(config.CACHE_DIR, f"{key}.json")
    data["_saved_at"] = time.time()
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        pass


@dataclass
class Job:
    job_id: str
    ra: float
    dec: float
    size_deg: float
    stretch: str
    color: bool = False
    status: str = "pending"  # pending, running, completed, failed
    frames: list[dict] = field(default_factory=list)
    difference_frames: list[dict] = field(default_factory=list)
    spectrum: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    progress: int = 0
    total: int = 0
    matching_diagnostic: Optional[dict] = None


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = asyncio.Lock()
        self.sem = asyncio.Semaphore(config.MAX_CONCURRENT_CUTOUTS)

    def create_job(self, req) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            job_id=job_id,
            ra=req.ra,
            dec=req.dec,
            size_deg=req.size_deg,
            stretch=req.stretch,
            color=req.color,
        )
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    async def run_job(self, job: Job, req):
        job.status = "running"
        try:
            # 1. Spatially constrained obscore query
            records = await asyncio.to_thread(
                services.query_obscore_cone,
                ra=req.ra,
                dec=req.dec,
                detector=req.detector,
                collection=req.collection,
                max_rows=req.max_frames * 2,
            )
            if not records:
                job.status = "completed"
                job.error = "No SPHEREx observations cover this position."
                return

            job.total = min(len(records), req.max_frames)

            # 2. Fetch cutouts under semaphore (politeness to IRSA)
            fetched_frames = []
            for rec in records:
                if len(fetched_frames) >= req.max_frames:
                    break
                async with self.sem:
                    frame = await asyncio.to_thread(
                        self._fetch_and_process_frame,
                        rec,
                        req.ra,
                        req.dec,
                        req.size_deg,
                        req.stretch,
                        req.color,
                    )
                if frame:
                    fetched_frames.append(frame)
                    job.progress = len(fetched_frames)

            if not fetched_frames:
                job.status = "failed"
                job.error = "Could not fetch any cutouts from IRSA."
                return

            # 3. CRITICAL SCIENCE RULE: Match on per-pixel LVF wavelength
            matched, diag = science.match_spectral_channels(
                fetched_frames,
                target_wavelength_um=req.wavelength_um,
                tolerance_bandwidths=req.tolerance_bandwidths,
            )
            job.matching_diagnostic = diag
            job.frames = matched

            # 4. Generate difference frames for consecutive matched pairs
            diff_list = []
            for i in range(len(matched) - 1):
                fa, fb = matched[i], matched[i + 1]
                if fa.get("_raw_data") is not None and fb.get("_raw_data") is not None:
                    diff_arr = science.compute_difference_frame(
                        fa["_raw_data"],
                        fb["_raw_data"],
                    )
                    png_bytes = science.render_png(diff_arr)
                    diff_list.append({
                        "pair": [fa["obs_id"], fb["obs_id"]],
                        "mjd_pair": [fa["mjd"], fb["mjd"]],
                        "wavelength_um": fa["wavelength_um"],
                        "png_b64": png_bytes.hex(),
                    })
            job.difference_frames = diff_list

            # 5. Extract spectrum across all fetched frames
            spectrum_points = []
            for f in fetched_frames:
                if f.get("_raw_data") is not None:
                    # Central pixel value in MJy/sr
                    arr = f["_raw_data"]
                    cy, cx = arr.shape[0] // 2, arr.shape[1] // 2
                    val = float(arr[cy, cx])
                    spectrum_points.append({
                        "obs_id": f["obs_id"],
                        "mjd": f["mjd"],
                        "wavelength_um": f["wavelength_um"],
                        "bandwidth_um": f["bandwidth_um"],
                        "flux_mjy_sr": val if np.isfinite(val) else 0.0,
                        "detector": f["detector"],
                    })
            spectrum_points.sort(key=lambda s: s["wavelength_um"])
            job.spectrum = spectrum_points

            # Clean raw arrays from memory before job storage
            for f in job.frames:
                f.pop("_raw_data", None)

            job.status = "completed"
            job.completed_at = time.time()

        except Exception as e:
            job.status = "failed"
            job.error = f"{type(e).__name__}: {str(e)}"

    def _fetch_and_process_frame(
        self,
        rec: dict,
        ra: float,
        dec: float,
        size_deg: float,
        stretch: str,
        color: bool = False,
    ) -> Optional[dict]:
        obs_id = rec["obs_id"]
        ckey = cache_key("cut", obs_id, ra, dec, size_deg, stretch)
        cached = get_cached(ckey)
        if cached:
            # Rehydrate raw numpy data if present in cache
            if "raw_path" in cached and os.path.exists(cached["raw_path"]):
                cached["_raw_data"] = np.load(cached["raw_path"])
            # Colour toggle must never re-fetch the 31-120s cutout: re-render
            # the PNG from cached raw data instead.
            if cached.get("color", False) != color and cached.get("_raw_data") is not None:
                stretched = science.apply_stretch(cached["_raw_data"], stretch=stretch)
                png_bytes = (
                    science.render_png_color(stretched, cached["wavelength_um"])
                    if color else science.render_png(stretched)
                )
                cached["png_b64"] = png_bytes.hex()
                cached["color"] = color
            return cached

        try:
            # 1. DataLink -> cutout path
            cutout_path = services.resolve_datalink_cutout_path(rec["datalink_url"])
            # 2. IBE cutout fetch
            fits_bytes = services.fetch_cutout_fits(cutout_path, ra, dec, size_deg)

            with fits.open(io.BytesIO(fits_bytes)) as hdul:
                # 3. Compute real target wavelength from WCS-WAVE + A-WCS
                sol = science.compute_target_wavelength(hdul, ra, dec)
                # 4. Extract science image and stretch
                image_arr = hdul["IMAGE"].data.astype(np.float32)
                hdr = hdul["IMAGE"].header
                date_obs = hdr.get("DATE-OBS") or ""

            stretched = science.apply_stretch(image_arr, stretch=stretch)
            png_bytes = (
                science.render_png_color(stretched, sol.wavelength_um)
                if color else science.render_png(stretched)
            )

            raw_file = os.path.join(config.CACHE_DIR, f"{ckey}.npy")
            np.save(raw_file, image_arr)

            result = {
                "obs_id": obs_id,
                "mjd": rec["mjd"],
                "date_obs": date_obs,
                "detector": rec["detector"],
                "wavelength_um": round(sol.wavelength_um, 4),
                "bandwidth_um": round(sol.bandwidth_um, 4),
                "resolving_power": round(sol.resolving_power, 1),
                "det_x": round(sol.det_x, 1),
                "det_y": round(sol.det_y, 1),
                "png_b64": png_bytes.hex(),
                "color": color,
                "raw_path": raw_file,
                "_raw_data": image_arr,
                "attribution": config.ATTRIBUTION,
            }
            set_cached(ckey, {k: v for k, v in result.items() if k != "_raw_data"})
            return result
        except Exception:
            return None


JOB_MANAGER = JobManager()
