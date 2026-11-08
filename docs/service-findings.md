# Service Findings

All results below come from **live calls made during Phase 0** (2026-11-08) from a
macOS client on a residential-type connection. Nothing here is guessed or copied
from documentation; every endpoint, parameter name and field name was observed in
a real response. Latencies are single-sample and should be read as rough orders of
magnitude, not benchmarks.

Descriptive User-Agent sent on every call:
`QuickX/0.1 (service discovery; NASA SPHEREx blink comparator)`

---

## 1. IRSA TAP — SPHEREx catalogue

**Endpoint:** `https://irsa.ipac.caltech.edu/TAP/sync` (GET, `QUERY=` ADQL, `FORMAT=csv|json`)

Liveness check `SELECT 1`: **HTTP 200 in 1.7 s**.

### Tables that exist

`TAP_SCHEMA.tables WHERE table_name LIKE '%spherex%'` returned exactly:

```
spherex.artifact
spherex.obscore
spherex.observation
spherex.plane
spherex.provenance_input
```

`spherex.obscore` is the IVOA ObsCore view and is the one QuickX queries.

**Row count:** `SELECT COUNT(*) FROM spherex.obscore` → **1,607,635** rows.

### Collections present

`SELECT DISTINCT obs_collection` → `spherex_qr2`, `spherex_qr2_deep`,
`spherex_qr2_cal`, `spherex_qr3`, `spherex_qr3_deep`, `spherex_qr3_cal`.
So both Quick Release 2 and 3 are live, each with a deep and a calibration variant.
QuickX uses the science collections (`spherex_qr2`, `spherex_qr3`) and their `_deep`
counterparts; `_cal` is excluded by default.

**Latency note:** `SELECT DISTINCT obs_collection` over 1.6 M rows took **106 s**.
A `GROUP BY` over the whole table was still running at 120 s. Lesson recorded:
**never issue an unconstrained aggregate at request time.** Every user-facing query
must carry a spatial constraint.

### Columns actually available (verified)

`TAP_SCHEMA.columns WHERE table_name='spherex.obscore'` lists 60 columns. The ones
QuickX depends on:

| Column | Type | Meaning (from the archive's own description) |
|---|---|---|
| `obs_id` | char | Observation ID, e.g. `2025W20_2D_0234_1` |
| `s_ra`, `s_dec` | double | Central RA/Dec, ICRS |
| `s_region` | char | Sky region covered — used with `CONTAINS(POINT(...), s_region)` |
| `energy_bandpassname` | char | **Detector** name, e.g. `SPHEREx-D3` (see §2) |
| `em_min`, `em_max` | double | Wavelength bounds **in metres** |
| `t_min`, `t_max` | double | Observation start/end, **MJD** |
| `t_exptime` | double | Exposure time |
| `access_url` | char | DataLink URL (not the FITS file) |
| `access_format` | char | `application/x-votable+xml;content=datalink` |
| `calib_level` | short | `2` for the Level-2 spectral images |
| `obs_collection` | char | e.g. `spherex_qr2` |
| `s_xel1`, `s_xel2` | long | `2040 × 2040` pixels |
| `s_pixel_scale` | double | `6.15` arcsec/pixel |
| `target_moving` | boolean | Intended target is moving |

### Cone search — works, and is the right pattern

```sql
SELECT TOP 6 obs_id, s_ra, s_dec, energy_bandpassname, em_min, em_max,
       t_min, calib_level, obs_collection, access_url
FROM spherex.obscore
WHERE CONTAINS(POINT('ICRS', 180.0, 0.0), s_region) = 1
```

**HTTP 200 in 15.6 s.** Returned real rows, e.g.

```
2025W20_2D_0234_1, 180.772136, 0.363313, SPHEREx-D3,
1.6301e-06, 2.4346e-06, 60811.905839, 2, spherex_qr2, <datalink url>
```

Note `em_min`/`em_max` are metres (1.6301e-06 m = 1.6301 µm). QuickX converts once,
at the boundary, and works in µm internally.

### Bandpass distribution

```
SPHEREx-D1 270830   SPHEREx-D2 272333   SPHEREx-D3 267727
SPHEREx-D4 266723   SPHEREx-D5 267482   SPHEREx-D6 262536
SPHEREx-All      4
```

Six detectors, roughly evenly covered, plus 4 anomalous `SPHEREx-All` rows that
QuickX filters out.

---

## 2. THE CRITICAL FINDING — band name is not a colour

This is the single most important result of Phase 0 and it drives the whole design.

`energy_bandpassname` identifies the **detector** (D1–D6), *not* the wavelength.
For `SPHEREx-D3`, obscore reports `em_min=1.6301 µm`, `em_max=2.4346 µm` — an
**0.80 µm span** — because SPHEREx uses a linear variable filter (LVF) and the
wavelength changes continuously across the detector face.

The real wavelength solution ships inside each FITS file, in a `WCS-WAVE`
`BinTableHDU`:

```
WCS-WAVE  BinTableHDU  1R x 3C  [9J, 14J, 252E]
  X      : 9  node columns  [1, 256, 511, 766, 1021, 1275, 1530, 1785, 2040]
  Y      : 14 node rows     [1, 36, 71, 105, 140, 141, 379, ..., 2040]
  VALUES : (14, 9, 2) -> (wavelength_um, bandwidth_um) at each node
```

Observed behaviour on a real D3 frame: wavelength falls monotonically along **Y**
(2.4192 → 1.6163 µm) and varies only weakly along **X** (2.1485 → 2.1736 µm).
So *where a target lands on the detector sets its colour.*

### Measured for one real target position

Cutout of `2025W20_2D_0234_1` D3 at RA 180.0, Dec 0.0:

```
cutout pixel         = (8.73, 8.01)   in an 18x18 cutout
full-detector pixel  = (691.7, 1408.0)
WAVELENGTH           = 1.8373 um
BANDWIDTH            = 0.0456 um      ->  R = 40.3
```

The detector's advertised span is 0.80 µm; this pixel samples 0.049 µm.
**The band name is ~16 bandwidths too coarse to be used as a colour key.**
Matching two epochs by `energy_bandpassname` alone could compare 1.63 µm against
2.43 µm and render a pure colour difference as apparent motion — exactly the
false positive QuickX exists to prevent.

### How to recover the full-detector pixel from a cutout

Each cutout carries two alternate WCSs besides the celestial one:

```
WCSNAMEA = '0-based active pixel coordinates'   CTYPE1A/2A = 'LINEAR'
WCSNAMEW = 'Approximated per-pixel wavelength and bandwidth'
CTYPE1W/2W = 'WAVE-TAB'   CNAME1W = 'Wavelength'   CNAME2W = 'Bandwidth'
PS1_0W = 'WCS-WAVE'  PS1_1W = 'VALUES'  PS1_2W = 'X'   (and PS2_*W for Y)
```

**Use the `A` WCS.** It maps cutout pixels to full-detector pixels directly:

```python
det = WCS(header_without_sip, key="A").wcs_pix2world([[x, y]], 0)[0]
```

Verified on a real cutout — the detector position genuinely varies across the
cutout and stays inside `1..2040`:

```
cutout( 0, 0) -> det( 683.0, 1400.0)  WAVE=1.8404  bw=0.0457
cutout( 9, 9) -> det( 692.0, 1409.0)  WAVE=1.8370  bw=0.0456
cutout(17,17) -> det( 700.0, 1417.0)  WAVE=1.8339  bw=0.0455
```

**A wrong method that looked right — recorded so it is not repeated.** An
intuitive-seeming shortcut is `offset = CRPIX1 - CRPIX1W`. It is a **tautology**:
`CRPIX1` and `CRPIX1W` are both shifted by the same amount when a cutout is made,
so the difference is a constant and always yields detector pixel ≈ (1020, 1020) —
the detector centre — no matter which target or which frame. It silently produced
a plausible but wrong 1.9799 µm instead of the correct 1.8373 µm (an error of ~3
bandwidths), and made every epoch look identically centred. The giveaway was that
the "detector position" came out as 1025 for every frame and every sky position.
Detected by fetching cutouts at different sky points from the *same* frame and
checking whether the computed detector pixel moved. It did not. **Any future
change to this mapping must keep that test.**

Two further details, both observed:

- Astropy warns that SIP coefficients are present while `CTYPE1A` lacks a `-SIP`
  suffix, and would apply the celestial SIP distortion to the linear `A` WCS.
  SIP belongs to the celestial solution only, so the `A*`/`B*` SIP keys are
  stripped from a copy of the header before constructing the `A` WCS.
- The `WCS-WAVE` `X`/`Y` node arrays start at `1`, i.e. 1-based detector pixels,
  while the `A` WCS is documented as *0-based*. QuickX converts explicitly rather
  than relying on the one-pixel difference being negligible.

Then bilinear-interpolate `VALUES` on the `(X, Y)` node grid for both wavelength
and bandwidth. `VALUES` is indexed `[Y, X, component]`.

### Useful per-frame header keys (observed on the `IMAGE` HDU)

```
DETECTOR = 3                      OBSID    = '2025W20_2D_0234_1'
NCHANNEL = 32                     WCHANNEL = 64
DATE-OBS = '2025-05-16T21:44:24'  MJD-OBS  = 60811.905838657
MJD-AVG  = 60811.906504847        MJD-END  = 60811.907171036
BUNIT    = 'MJy / sr'             CTYPE1/2 = 'RA---TAN-SIP' / 'DEC--TAN-SIP'
CRPIX1W / CRPIX2W = -682.0 / -1399.0   CUNIT1W = 'um'
```

`BUNIT = MJy/sr` is a surface brightness, so frames are photometrically
comparable without rescaling. WCS carries **SIP** distortion, so alignment must
use the full polynomial (`all_world2pix`), not a linear approximation.

---

## 3. IRSA DataLink — obscore row to FITS path

`access_url` is a DataLink document, not a file. Resolving one:

```
GET https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=ivo://irsa.ipac/spherex_qr2?2025W20_2D_0234_1/D3
```

**HTTP 200.** The VOTable declares a cutout service and lists the file:

- `#this` → full science image,
  `https://irsa.ipac.caltech.edu/ibe/data/spherex/qr2/level2/2025W20_2D/l2b-v20-2025-247/3/level2_2025W20_2D_0234_1D3_spx_l2b-v20-2025-247.fits`,
  `image/fits`, **71,634,240 bytes (71 MB)**
- `#cutout` → `service_def = ibe-cutout`, with the IBE-relative path
  `spherex/qr2/level2/.../level2_..._spx_l2b-v20-2025-247.fits`
- AWS mirror, as JSON in the DataLink row:
  `{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "qr2/level2/...", "region": "us-east-1"}}`

The declared cutout service and its input parameters:

```
accessURL = https://irsa.ipac.caltech.edu/ibe/cutout
inputParams: ra (double), dec (double), size (double, default 0.01), path (char)
```

**71 MB per full frame confirms the product requirement:** the browser must never
touch these, and even the backend should only ever request cutouts.

Note the two path spellings. The `#this` URL contains `/ibe/data/spherex/...`
while the cutout `path` parameter takes `spherex/...`. QuickX reads the path from
the DataLink `#cutout` row rather than string-editing the `#this` URL.

---

## 4. IRSA IBE cutout service

**Endpoint:** `https://irsa.ipac.caltech.edu/ibe/cutout`
**Parameters (observed):** `path`, `ra`, `dec`, `size` (degrees), `extension` (optional)

Real call: `ra=180.0, dec=0.0, size=0.03` on the D3 path above.

| Request | HTTP | Time | Bytes |
|---|---|---|---|
| no `extension` | 200 | 31.3 s | 5,060,160 |
| no `extension` (repeat) | 200 | 120.0 s* | 2,885,590* |
| `extension=0` | 200 | 45.6 s | 5,060,160 |
| `extension=1` | 200 | — | 1,617,920 |

\* this repeat hit the 120 s client timeout mid-transfer; the byte count is a
partial read, not a smaller product. Recorded because it is a real failure mode.

A `size=0.03` request yields an **18 × 18** pixel image at 6.15″/px, consistent
with the pixel scale.

### What a cutout actually contains

```
0 PRIMARY        5 cards   (empty)
1 IMAGE        239 cards   (18, 18)          float32   MJy/sr
2 FLAGS        146 cards   (18, 18)          int32
3 VARIANCE     119 cards   (18, 18)          float32   MJy2/sr2
4 ZODI         119 cards   (18, 18)          float32   MJy/sr
5 PSF          509 cards   (101, 101, 121)   float32
6 WCS-WAVE      18 cards   1R x 3C
```

The 5 MB is almost entirely the **PSF cube** — `101 × 101 × 121` float32 ≈ 4.9 MB
— which dwarfs the 1.3 kB science image. `extension=1` cuts the payload to 1.6 MB.

**Important caveat found by inspection:** `extension=1` still returned all seven
HDUs in this test, so it did not isolate the image as hoped. It is therefore not
a reliable way to drop the PSF, and QuickX does not depend on it. The backend
instead keeps only `IMAGE`, `VARIANCE`, `FLAGS` and `WCS-WAVE` after parsing, and
discards `PSF` and `ZODI` before caching, so cache footprint is small even though
the download is not.

### Latency is the dominant design constraint

Observed cutout times: **31 s, 46 s, >120 s** for a single 18 × 18 image. A blink
sequence needs 5–20 frames. Serial fetching would mean 3–10 minutes of silence.
Consequences, carried into the design:

- cutout fetching must be a **background job with progressive results**, not a
  blocking request/response
- frames stream to the client as they arrive
- aggressive on-disk caching keyed by position/band/size
- bounded concurrency per job, with a global cap, to stay polite to IRSA
- a circuit breaker for when IRSA slows down, plus honest "still fetching" UI
- generous timeouts (300 s), well above the default of most HTTP clients

---

## 5. Multi-epoch wavelength test — the false-motion mechanism, measured

Script: `probe/wave_correct.py`. It queries every D3 frame covering
(180.0, 0.0), picks one frame per distinct visit spread across the whole time
baseline, fetches real cutouts, and computes the wavelength each visit actually
sampled at that exact sky point. Recorded output:
`probe/recorded_wave_correct.json` (real responses, labelled as recorded).

The catalogue holds **57 D3 frames** covering that point, over a **398-day
baseline** (MJD 60811.91 → 61210.12), in 20 distinct visits.

**Result:**

```
wavelength range at one fixed sky point, one detector:
    1.6258 .. 2.4126 um      spread = 0.7868 um
median bandwidth           = 0.050 um
    -> spread = 15.7 bandwidths
detector rows spanned      = 28 .. 2018   (of 2040)
```

Examples from that run:

```
2026W21_1A_0499_1  mjd=61181.27  det=( 572.3,  781.0)  WAVE=2.0838  bw=0.0520
2026W25_2A_0123_1  mjd=61210.12  det=( 576.5, 1965.3)  WAVE=1.6448  bw=0.0394
```

**This is the quantitative justification for the whole design.** The same patch of
sky, observed by the same detector, is sampled anywhere from 1.63 µm to 2.41 µm
depending on the visit, because SPHEREx revisits fields at different spacecraft
orientations and the target lands almost anywhere along the detector's 2040 rows.
Two such frames blinked against each other would differ enormously in brightness
for any source with colour — a pure spectral artefact that an untrained viewer
would read as the object moving, appearing or vanishing.

Matching on `energy_bandpassname` would happily pair the two frames above, which
are **15.7 bandwidths apart**. Only per-pixel wavelength matching prevents it.

### Earlier flawed run, kept as a caution

A first attempt reported a spread of 0.0004 µm and concluded epochs "happen to
align". It was wrong twice over: it used the tautological CRPIX offset (§2), and
it sampled five *consecutive* exposures from a single visit rather than across the
baseline. Both errors pushed the answer toward "no problem here". Recorded because
a test that cannot fail is worse than no test — the real spread is ~2000× larger.

---

## 6. JPL Small-Body Database — orbits and ephemerides

**Endpoint:** `https://ssd-api.jpl.nasa.gov/sbdb.api?sstr=<designation>`

`sstr=3I/ATLAS`, `full-prec=true` → **HTTP 200, fast (< 1 s), JSON.**

Real orbital elements returned:

```
e (eccentricity)        = 6.123467394525528   ± 4.3958e-5
a (semi-major axis)     = -0.2638835217034532 au
q (perihelion distance) = 1.351998619400212 au
i (inclination)         = 175.2403121571192 deg
node                    = 323.0251782090054 deg
peri                    = 128.7969426041922 deg
cov_epoch               = 2461340.5 (JD)
moid_jup                = 0.246551
```

**e = 6.12 with a negative semi-major axis is a hyperbolic orbit** — this is the
archive confirming 3I/ATLAS is genuinely interstellar, not bound to the Sun.
Inclination 175° means it is retrograde. These are the real numbers the guided
tour quotes.

SBDB returns *elements*, not positions. For predicted sky positions at specific
observation times QuickX needs an ephemeris, so §7 matters.

---

## 7. Moving Object Search Tool (MOST) — verified, works

**Endpoint:** `https://irsa.ipac.caltech.edu/cgi-bin/MOST/nph-most` (GET)

Parameters established by probing, not guessed:

```
catalog     = spherex          # NOT 'spherex_qr2' -> HTTP 400 "unknown catalog name"
input_type  = name_input
obj_name    = 3I               # resolved via JPL HORIZONS
output_mode = Brief | Regular
obs_begin, obs_end             # optional, ISO dates
```

Two discoveries that would have cost time if guessed:

- `catalog=spherex_qr2` returns **HTTP 400, "unknown catalog name"**. The valid
  value is the bare `spherex`. Usefully, MOST echoed back the parameter it
  rejected, which confirmed the rest of the parameter names were right.
- `obj_name=3I/ATLAS` fails with "HORIZONS name lookup failed". `3I`,
  `C/2025 N1` and the SPK id `1004083` all succeed and resolve to the same object,
  `ATLAS (C/2025 N1)`. So QuickX passes designations HORIZONS accepts, and does
  not pass the common informal name through unchanged.

Successful call (`obj_name=3I`, **HTTP 200 in ~7 s**) returns a header block with
the orbit MOST actually used:

```
object_name       = "ATLAS (C/2025 N1)"
element_epoch     = 60776.0 (2025-Apr-11)
eccentricity      = 6.139668459770622
inclination       = 175.112899123431390
perihelion_distance = 1.356398266204739
perihelion_time   = 2460977.978829147760
output_url        = https://irsa.ipac.caltech.edu/workspace/TMP_.../MOST/pid...
```

### Results are files in a workspace, not the response body

`output_mode=Regular` returns an **HTML page**, not a table — parsing it for
science values would be fragile. The real products are files under `output_url`:

```
imgframes_matched_final_table.tbl   <- the one QuickX uses
ephemeris_table.txt                 ephemeris_decimal_degrees.txt
imgframes_nearby.tbl                orbitElm.txt
ds9region/  fitsimage/  jpegimage/   download_fits.sh
```

`imgframes_matched_final_table.tbl` (**HTTP 200, 466 kB**) is an IPAC-format table
with **359 matched SPHEREx frames for 3I/ATLAS**, spread across all six detectors
(D1 61, D2 62, D3 59, D4 61, D5 62, D6 54). Columns:

```
ra_obj dec_obj sun_dist geo_dist dist_ctr phase vmag match
proposal_id target_name target_moving
observationid planeid productid instrument
start_date end_date mjd_start mjd_end exposure_time
ra dec ra1 dec1 ra2 dec2 ra3 dec3 ra4 dec4 uri
```

`ra_obj`/`dec_obj` are the **predicted** position of the object at that frame's
epoch — exactly the overlay feature 6 needs. `observationid` and `productid`
(e.g. `2025W31_2A_0156_1`, `D3`) join directly to `spherex.obscore.obs_id` and
`energy_bandpassname`, so a MOST result can be turned into QuickX cutout jobs
without a second archive search.

Real matched rows, e.g. `2025W31_2A_0156_1` D3 and D6 at
`ra_obj=252.664196, dec_obj=-17.490529`, `vmag=14.04`, `geo_dist=2.81 au`.

**Caveat:** the workspace URL is a temporary job directory. QuickX treats it as
short-lived — read it immediately, cache what it needs, never store the URL as a
durable reference.

---

## 8. Name resolution — CDS is unreachable, NED works

| Service | Result |
|---|---|
| `cds.unistra.fr/cgi-bin/nph-sesame` | **HTTP 000, timeout at 45 s** |
| `vizier.cds.unistra.fr/viz-bin/nph-sesame` | **HTTP 000, timeout at 30 s** |
| `simbad.cds.unistra.fr/simbad/sim-tap/sync` | **HTTP 000, timeout at 40 s** |
| `ned.ipac.caltech.edu/srs/ObjectLookup` | **HTTP 200, JSON, fast** |

All three CDS endpoints are unreachable from this network, so `astroquery.simbad`
cannot be relied on as the primary resolver. NED's lookup works and is hosted at
IPAC alongside IRSA:

```
GET https://ned.ipac.caltech.edu/srs/ObjectLookup?json={"name":{"v":"M51"}}
-> {"Supplied": "M51", "NameResolver": "NED-NNS",
    "Interpreted": {"Name": "MESSIER 051"},
    "Preferred": {"Name": "Messier 051",
                  "Position": {"RA": 202.4841667, "Dec": 47.23055556, ...}}}
```

**Design decision:** resolve names through NED first, fall back to SIMBAD/Sesame
when reachable, and report a clear, specific error when every resolver fails. Both
hosts go on the SSRF allow-list. Note that the `json=` parameter is a structured
query, so it is built with `json.dumps` and URL-encoded, never by string
concatenation.

---

## 9. Summary of design consequences

1. **Match on per-pixel LVF wavelength from `WCS-WAVE`, never on band name.**
   Measured: 15.7 bandwidths of spread at one sky point on one detector (§5).
2. **Get the detector pixel from the `A` WCS, with SIP stripped.** The CRPIX-difference
   shortcut is a tautology that always returns the detector centre (§2).
3. **Never block a request on a cutout.** 31–120 s each; use background jobs,
   progressive streaming and a persistent cache.
4. **Never run an unconstrained TAP aggregate.** 106 s for one `DISTINCT`.
5. **Full frames are 71 MB.** Cutouts only, everywhere.
6. **Discard `PSF`/`ZODI` after parsing.** They are ~97 % of the payload.
7. **Use SIP-aware WCS for celestial alignment**, via `all_world2pix`.
8. **NED for name resolution**, CDS as an optional fallback (CDS unreachable here).
9. **MOST: `catalog=spherex`, HORIZONS-style designations, read results from the
   workspace `.tbl` file**, not the HTML response.
10. **Python needs `certifi` explicitly** — the framework install has no CA bundle,
    so `urllib`/`requests` fail with `CERTIFICATE_VERIFY_FAILED` while `curl` works.
11. Allow-list: `irsa.ipac.caltech.edu`, `ned.ipac.caltech.edu`,
    `ssd-api.jpl.nasa.gov`, `nasa-irsa-spherex.s3.us-east-1.amazonaws.com`,
    and CDS hosts for the optional fallback.

## 10. Failure modes observed (for error handling and the circuit breaker)

| Symptom | Cause | QuickX response |
|---|---|---|
| HTTP 200 but truncated body at 120 s | cutout slower than client timeout | 300 s timeout, retry once, then honest error |
| HTTP 400 "unknown catalog name" | wrong MOST `catalog` value | fixed at source; validated against allow-listed values |
| "HORIZONS name lookup failed" | informal designation (`3I/ATLAS`) | try known-good alternates, then report "object not found" |
| HTTP 000 after 30–45 s | CDS hosts unreachable from network | fall back to NED; never block on CDS |
| `CERTIFICATE_VERIFY_FAILED` | no system CA bundle for Python | `certifi` pinned as an explicit dependency |
| TAP query runs > 100 s | unconstrained aggregate | all queries carry a spatial constraint |
