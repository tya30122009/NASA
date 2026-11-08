# STATE

Updated: 2026-11-08 · Project complete (Phases 0 to 5) + wavelength false colour

## Done
- Phase 0: Service verification & live endpoint testing (IRSA TAP, IBE, MOST, NED, JPL SBDB). Discovered and proved the 15.7-bandwidth wavelength spread across visits.
- Phase 1: Backend pipeline (FastAPI, schemas, fetcher with SSRF protection & allow-list, cutout background jobs, caching, LVF wavelength interpolation, SIP alignment, asinh stretch, difference mode, unit tests).
- Phase 2: Frontend viewer & Liquid Glass UI (index.html, vanilla ES modules, canvas blinker, metadata badge, responsiveness).
- Phase 3: Extras & science features (spectrum inspection, moving object queries via MOST & JPL SBDB).
- Phase 4: Security hardening (SECURITY.md, strict CSP, rate limiting, token buckets, input sanitization).
- Phase 5: Testing, README, service findings, demo script.
- Wavelength false colour: `color` job flag, cache-safe re-render (no IRSA re-fetch on toggle), UI toggle with false-colour label, poll retry on transient errors. Verified live in browser (M51): grayscale ↔ tint ↔ difference.

All tests pass successfully.
