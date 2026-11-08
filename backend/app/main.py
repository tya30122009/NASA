"""FastAPI application with strict security headers, CORS, rate limiting,
SSRF protection, and clear JSON error responses.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Callable
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, jobs, schemas, services

app = FastAPI(
    title="QuickX API",
    description="Backend pipeline for NASA SPHEREx spectral-image blink comparator.",
    version="1.0.0",
)

# --- CORS -------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# --- Security Headers Middleware --------------------------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next: Callable) -> Response:
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Relax CSP slightly to allow inline styles/scripts for the simple frontend
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self' https://aladin.u-strasbg.fr; "
        "style-src 'self' 'unsafe-inline' https://aladin.u-strasbg.fr; "
        "script-src 'self' 'unsafe-inline' https://aladin.u-strasbg.fr; "
        "img-src 'self' blob: data: https://*;"
    )
    return resp

# --- Rate Limiter (token bucket) --------------------------------------------
class TokenBucket:
    def __init__(self, rpm: int, burst: int):
        self.rpm = rpm
        self.burst = burst
        self.buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        tokens, last = self.buckets.get(key, (float(self.burst), now))
        elapsed = now - last
        tokens = min(float(self.burst), tokens + elapsed * (self.rpm / 60.0))
        if tokens >= 1.0:
            self.buckets[key] = (tokens - 1.0, now)
            return True
        self.buckets[key] = (tokens, now)
        return False

LIMITER = TokenBucket(config.RATE_LIMIT_RPM, config.RATE_LIMIT_BURST)

@app.middleware("http")
async def enforce_rate_limit(request: Request, call_next: Callable) -> Response:
    client_ip = request.client.host if request.client else "unknown"
    if not LIMITER.allow(client_ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please wait a moment and try again."},
        )
    return await call_next(request)

# --- Routes -----------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": time.time(), "attribution": config.ATTRIBUTION}


@app.post("/api/resolve")
def resolve_name(query: schemas.ResolveQuery):
    try:
        return services.resolve_object_name(query.name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/search")
def search_coverage(query: schemas.SearchQuery):
    try:
        results = services.query_obscore_cone(
            ra=query.ra,
            dec=query.dec,
            detector=query.detector,
            collection=query.collection,
        )
        return {
            "ra": query.ra,
            "dec": query.dec,
            "count": len(results),
            "observations": results,
            "attribution": config.ATTRIBUTION,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IRSA query failed: {e}")


@app.post("/api/jobs")
def create_job(req: schemas.JobRequest, bg_tasks: BackgroundTasks):
    job = jobs.JOB_MANAGER.create_job(req)
    bg_tasks.add_task(jobs.JOB_MANAGER.run_job, job, req)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "message": "Job created. Poll /api/jobs/{job_id} for progress.",
    }


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    job = jobs.JOB_MANAGER.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
        "error": job.error,
        "frames": job.frames,
        "difference_frames": job.difference_frames,
        "spectrum": job.spectrum,
        "matching_diagnostic": job.matching_diagnostic,
        "attribution": config.ATTRIBUTION,
    }


@app.post("/api/moving-object")
def search_moving_object(query: schemas.MovingObjectQuery):
    try:
        orbit = services.query_jpl_orbit(query.name)
        matches = services.query_most_moving_object(query.name)
        return {
            "object": query.name,
            "orbit": orbit,
            "match_count": len(matches),
            "matches": matches,
            "attribution": config.ATTRIBUTION,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

# --- Static Files Mounting (Frontend) ---------------------------------------
frontend_dir = os.path.normpath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
)
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
