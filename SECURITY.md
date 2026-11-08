# Security Policy & Threat Model

QuickX handles no personal data, requires no accounts, and collects no telemetry.
All search state and view options are stored exclusively in the URL query parameters
or hash. No cookies or local storage trackers are used.

## 1. Threat Model & Mitigations

### Server-Side Request Forgery (SSRF)
- **Threat:** Malicious input causing the backend to query internal infrastructure or external arbitrary endpoints.
- **Mitigation:** Strict allow-list (`backend/app/config.py`) restricted to NASA IRSA, NED, JPL SBDB, and the SPHEREx S3 bucket. All outbound URLs pass through `fetcher.py`, which validates schemes, enforces the allow-list, inspects redirects manually, and blocks private IP ranges and metadata endpoints.

### Input Validation & Injection
- **Threat:** Malformed coordinates, SQL injection via archive queries, or XSS via object names.
- **Mitigation:** Pydantic strict schemas (`backend/app/schemas.py`) enforce exact ranges (RA 0–360, Dec -90..90) and character sets (`OBJECT_NAME_RE`). All database queries use parameterized ADQL via Astropy/TAP. User text is rendered using safe DOM primitives (`textContent`) on the frontend.

### Denial of Service (DoS) & Abuse
- **Threat:** Flooding cutout or difference endpoints with heavy requests, exhausting backend threads or upstream IRSA rate limits.
- **Mitigation:** Token-bucket rate limiter per IP, strict caps on cutout size (`<= 0.2°`) and frame counts (`<= 24`), asynchronous background job processing with concurrency semaphores (`MAX_CONCURRENT_CUTOUTS = 3`), persistent on-disk caching, and a circuit breaker that trips when IRSA responds with repeated failures.

### Browser Security & Supply Chain
- Strict Content Security Policy (CSP), HSTS, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and CORS restricted to explicit frontend origins.
- Pinned dependency versions with hashes, regular audits via `pip-audit`, non-root container with read-only filesystem.
