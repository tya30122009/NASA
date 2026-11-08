"""SSRF-safe HTTP client with allow-list, redirect inspection, circuit breaker,
size limits, and CA bundle via certifi.
"""
from __future__ import annotations

import io
import time
import urllib.parse
from typing import Optional
import certifi
import urllib3

from . import config

_POOL = urllib3.PoolManager(
    ca_certs=certifi.where(),
    maxsize=16,
    retries=urllib3.Retry(
        total=config.MAX_RETRIES,
        backoff_factor=0.5,
        status_forcelist=(502, 503, 504),
        raise_on_status=False,
    ),
    timeout=urllib3.Timeout(connect=10.0, read=config.CUTOUT_TIMEOUT),
)


class SSRFError(ValueError):
    pass


class UpstreamError(RuntimeError):
    pass


class CircuitBreakerOpen(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(self, threshold: int = config.BREAKER_FAILURES, reset_sec: float = config.BREAKER_RESET_SECONDS):
        self.threshold = threshold
        self.reset_sec = reset_sec
        self.failures = 0
        self.opened_at: Optional[float] = None

    def record_success(self):
        self.failures = 0
        self.opened_at = None

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.time()

    def check(self):
        if self.opened_at is None:
            return
        if time.time() - self.opened_at > self.reset_sec:
            # half-open
            return
        raise CircuitBreakerOpen(
            f"IRSA circuit breaker open after {self.failures} consecutive failures. "
            f"Auto-resets in {int(self.reset_sec - (time.time() - self.opened_at))}s."
        )


IRSA_BREAKER = CircuitBreaker()


def validate_url(url: str) -> urllib.parse.ParseResult:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise SSRFError(f"Disallowed scheme: {p.scheme}")
    host = (p.hostname or "").lower()
    if not host or host not in config.ALLOWED_HOSTS:
        raise SSRFError(f"Host '{host}' is not in the outbound allow-list")
    return p


def safe_fetch(
    url: str,
    params: Optional[dict] = None,
    timeout: float = 60.0,
    max_bytes: int = config.MAX_RESPONSE_BYTES,
    use_breaker: bool = False,
) -> bytes:
    if params:
        query_str = urllib.parse.urlencode(params)
        sep = "&" if ("?" in url) else "?"
        url = f"{url}{sep}{query_str}"

    current = url
    for _ in range(config.MAX_REDIRECTS + 1):
        parsed = validate_url(current)
        if use_breaker and "ipac.caltech.edu" in (parsed.hostname or ""):
            IRSA_BREAKER.check()

        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept": "*/*",
        }
        try:
            resp = _POOL.request(
                "GET",
                current,
                headers=headers,
                timeout=urllib3.Timeout(connect=10.0, read=timeout),
                redirect=False,
                preload_content=False,
            )
        except Exception as e:
            if use_breaker and "ipac.caltech.edu" in (parsed.hostname or ""):
                IRSA_BREAKER.record_failure()
            raise UpstreamError(f"Connection to {parsed.hostname} failed: {e}") from e

        # Handle redirects manually to enforce allow-list on every hop
        if resp.status in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            resp.release_conn()
            if not loc:
                raise UpstreamError(f"Redirect {resp.status} without Location header")
            current = urllib.parse.urljoin(current, loc)
            continue

        if resp.status >= 400:
            body = resp.read(2048).decode("utf-8", "replace")
            resp.release_conn()
            if use_breaker and "ipac.caltech.edu" in (parsed.hostname or ""):
                IRSA_BREAKER.record_failure()
            raise UpstreamError(f"Upstream returned HTTP {resp.status}: {body[:200]}")

        # Stream body with byte limit
        buf = io.BytesIO()
        total = 0
        try:
            for chunk in resp.stream(65536):
                total += len(chunk)
                if total > max_bytes:
                    raise UpstreamError(f"Response exceeded size limit ({max_bytes} bytes)")
                buf.write(chunk)
        finally:
            resp.release_conn()

        if use_breaker and "ipac.caltech.edu" in (parsed.hostname or ""):
            IRSA_BREAKER.record_success()
        return buf.getvalue()

    raise UpstreamError(f"Too many redirects (max {config.MAX_REDIRECTS})")
