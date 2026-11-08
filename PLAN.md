# QuickX — Plan

A free public web tool: pick a spot in the sky, watch how it changes across NASA
SPHEREx observations. No coding or astronomy background needed.

## The problem it solves

SPHEREx maps the whole sky in 102 near-infrared bands, all public via NASA/IPAC
IRSA — but as 71 MB FITS files behind archive queries and spectral-channel
bookkeeping. A naive blink comparison is also scientifically wrong: SPHEREx uses a
linear variable filter, so wavelength changes across each detector face. Two visits
can sample different colours at the same sky point, and a pure colour difference
then looks like motion. QuickX must never present that as change.

## Core science rule

Match epochs on **per-pixel LVF wavelength**, read from each file's `WCS-WAVE`
table at the target's detector position — never on the band name. Phase 0 measured
why: detector D3 spans 1.63–2.43 µm while a single pixel samples ~0.049 µm
(R≈41), so the band name is ~16 bandwidths too coarse. Wavelength is shown on
every frame. If no matching epochs exist, say so and offer nearest alternatives.
Tolerance is configurable, defaults to one bandwidth, and is displayed.

## Verified ground truth (Phase 0, all live calls — see docs/service-findings.md)

- `spherex.obscore` via IRSA TAP: 1.6 M rows, QR2 + QR3, cone search 15 s
- DataLink → IBE cutout `ra/dec/size/path`; cutouts 31–120 s each
- `WCS-WAVE` BinTableHDU: 9×14 node grid of (wavelength, bandwidth) in µm
- Full-detector pixel comes from the `A` alternate WCS, not a CRPIX difference
- MOST `catalog=spherex`: 359 real matched frames for 3I/ATLAS with `ra_obj`/`dec_obj`
- JPL SBDB: 3I/ATLAS e=6.12, hyperbolic → genuinely interstellar
- Name resolution: NED works; all CDS hosts unreachable from here

## Architecture

```
frontend (static, Vite, vanilla ES modules)  ──►  backend (FastAPI)  ──►  IRSA / JPL / NED
     Aladin Lite · canvas blink                    jobs · cache · allow-list
```

**Backend pipeline.** resolve name or coords → TAP cone search (always spatially
constrained) → group by detector, sort by time → fetch small cutouts through a
bounded-concurrency background job → compute per-pixel wavelength → group into
matched spectral sets → align by SIP-aware WCS → optional difference of
matched-band frames after normalisation → serve PNG frames + metadata (time,
band, wavelength, bandwidth, WCS, image ID, attribution).

Latency drives the design: cutouts take 31–120 s, so a blink sequence is a
**background job streaming frames as they arrive**, never a blocking request.
Persistent cache keyed by position/band/size only. Circuit breaker when IRSA is
slow. `PSF`/`ZODI` HDUs are discarded after parsing (~97 % of bytes).

**Frontend.** Static site, separate origin. Aladin Lite sky map; canvas for fast
blinking; lazy loading; low-data mode. All view state in the URL, so every view is
shareable. Modes: Blink, Flicker, Timeline, Difference.

**UI.** Liquid Glass translated to CSS: full-bleed content layer, never blurred;
controls float above as glass (`backdrop-filter` blur + saturation, 1 px specular
border, soft shadow), grouped to keep ≤4 backdrop layers. Falls back to opaque
surfaces under `prefers-reduced-transparency`, `prefers-contrast`, `forced-colors`,
low-data mode, or missing `backdrop-filter`. Beginner and Expert modes.

**Security.** No accounts, uploads or personal data; share state lives only in the
URL. Strict input schemas; users never supply URLs; outbound allow-list with
redirect, private-IP and metadata-address blocking; per-IP and global rate limits;
strict CSP, HSTS, CORS; pinned deps; non-root read-only container.

## Phases

| Phase | Deliverable |
|---|---|
| 0 | Service verification, PLAN/STATE, batched question — *done* |
| 1 | Backend: resolve, search, match, cutout jobs, cache, difference |
| 2 | Frontend viewer + Liquid Glass UI, keyboard + a11y |
| 3 | Spectrum, solar-system overlays, 3I/ATLAS tour, sharing |
| 4 | Security hardening, SECURITY.md, privacy.md |
| 5 | Tests, README, service-findings, demo script |

## Non-negotiables

Real data only — no fabricated, simulated or placeholder science values; on service
failure show a clear error and a retry. Fixtures are recorded real responses,
labelled as recorded. Attribution (NASA/IPAC IRSA, SPHEREx, JPL) with date, band
and image ID on every frame. Never silently mix bands.
