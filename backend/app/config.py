"""Configuration and the outbound allow-list.

Every value here is derived from the live service probing recorded in
docs/service-findings.md. Users never supply URLs or hostnames.
"""
from __future__ import annotations

import os

USER_AGENT = "QuickX/1.0 (+https://github.com/quickx/quickx; NASA SPHEREx blink comparator)"

# --- Outbound allow-list (SSRF control) -------------------------------------
# Only these hosts may ever be contacted. Verified reachable in Phase 0 except
# the CDS hosts, which are an optional fallback and must never be blocking.
ALLOWED_HOSTS = frozenset({
    "irsa.ipac.caltech.edu",                       # TAP, DataLink, IBE cutout, MOST
    "ned.ipac.caltech.edu",                        # name resolution (primary)
    "ssd-api.jpl.nasa.gov",                        # JPL Small-Body Database
    "nasa-irsa-spherex.s3.us-east-1.amazonaws.com",  # SPHEREx mirror
    "simbad.cds.unistra.fr",                       # optional fallback
    "cds.unistra.fr",                              # optional fallback
})

IRSA_TAP = "https://irsa.ipac.caltech.edu/TAP/sync"
IRSA_CUTOUT = "https://irsa.ipac.caltech.edu/ibe/cutout"
IRSA_MOST = "https://irsa.ipac.caltech.edu/cgi-bin/MOST/nph-most"
NED_LOOKUP = "https://ned.ipac.caltech.edu/srs/ObjectLookup"
JPL_SBDB = "https://ssd-api.jpl.nasa.gov/sbdb.api"

# --- SPHEREx facts (measured, not assumed) ---------------------------------
DETECTOR_PIXELS = 2040
PIXEL_SCALE_ARCSEC = 6.15
DETECTORS = ("D1", "D2", "D3", "D4", "D5", "D6")
SCIENCE_COLLECTIONS = ("spherex_qr2", "spherex_qr2_deep", "spherex_qr3", "spherex_qr3_deep")

# --- Limits -----------------------------------------------------------------
# Cutouts were measured at 31-120s each, so timeouts are generous and all
# cutout work happens in background jobs.
TAP_TIMEOUT = 90.0
DATALINK_TIMEOUT = 60.0
CUTOUT_TIMEOUT = 300.0
RESOLVE_TIMEOUT = 30.0
MOST_TIMEOUT = 120.0

MAX_RESPONSE_BYTES = 64 * 1024 * 1024   # a full frame is 71MB; cutouts are ~5MB
MAX_REDIRECTS = 3
MAX_RETRIES = 1

MAX_CUTOUT_SIZE_DEG = 0.2
DEFAULT_CUTOUT_SIZE_DEG = 0.05          # ~30px at 6.15"/px for higher detail
MAX_FRAMES_PER_JOB = 24
MAX_CONCURRENT_CUTOUTS = 3              # politeness toward IRSA
MAX_CONCURRENT_JOBS = 8
MAX_OBJECT_NAME_LEN = 64

# Spectral matching: default tolerance is one bandwidth. Phase 0 measured a
# 15.7-bandwidth spread at one sky point, so this is the load-bearing setting.
DEFAULT_TOLERANCE_BANDWIDTHS = 1.0
MAX_TOLERANCE_BANDWIDTHS = 5.0

# Rate limits (per IP, token bucket) and the stricter cutout/difference budget.
RATE_LIMIT_RPM = 60
RATE_LIMIT_BURST = 20
JOB_RATE_LIMIT_RPM = 6
JOB_RATE_LIMIT_BURST = 3
GLOBAL_JOB_RATE_RPM = 120

# Circuit breaker: trip after repeated upstream failures, recover after a pause.
BREAKER_FAILURES = 5
BREAKER_RESET_SECONDS = 60.0

CACHE_DIR = os.environ.get("QUICKX_CACHE_DIR", "/tmp/quickx-cache")
CACHE_TTL_SECONDS = 7 * 24 * 3600
JOB_TTL_SECONDS = 3600

FRONTEND_ORIGINS = tuple(
    o.strip() for o in os.environ.get(
        "QUICKX_FRONTEND_ORIGINS", "http://localhost:5173"
    ).split(",") if o.strip()
)

ATTRIBUTION = (
    "SPHEREx data courtesy NASA/IPAC IRSA. Orbits courtesy NASA/JPL Solar System "
    "Dynamics. Name resolution courtesy NASA/IPAC NED."
)
