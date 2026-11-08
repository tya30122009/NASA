"""CORRECTED: use the 'A' alternate WCS ('0-based active pixel coordinates')
to get the full-detector pixel, then interpolate WCS-WAVE.
Test 1: does detector pixel actually vary with sky position in one frame?
Test 2: wavelength spread for one sky point across many visits."""
import urllib.parse, urllib.request, json, re, time
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

UA = "QuickX/0.1 (service discovery; NASA SPHEREx blink comparator)"
def get(u, t=300):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=t).read()

def cutout(path, ra, dec, size=0.02):
    u = urllib.parse.urlencode({"path": path, "ra": ra, "dec": dec, "size": size})
    return get(f"https://irsa.ipac.caltech.edu/ibe/cutout?{u}")

def measure(blob, ra, dec):
    open("/tmp/_c.fits", "wb").write(blob)
    with fits.open("/tmp/_c.fits") as hd:
        h = hd["IMAGE"].header
        x, y = WCS(h).all_world2pix(ra, dec, 0)          # 0-based cutout pixel
        dx, dy = WCS(h, key="A").wcs_pix2world([[x, y]], 0)[0]   # full-detector 0-based
        t = hd["WCS-WAVE"].data[0]
        X, Y, V = (np.asarray(t[k], float) for k in ("X", "Y", "VALUES"))
        # node grids are 1-based detector pixels -> convert
        ip = lambda p: float(np.interp(dy + 1, Y, [np.interp(dx + 1, X, p[j]) for j in range(len(Y))]))
        return dx, dy, ip(V[:, :, 0]), ip(V[:, :, 1]), h["DATE-OBS"], h["DETECTOR"]

P3 = "spherex/qr2/level2/2025W20_2D/l2b-v20-2025-247/3/level2_2025W20_2D_0234_1D3_spx_l2b-v20-2025-247.fits"
print("TEST 1 - detector pixel vs sky position, SAME frame (centre 180.772,0.363)")
for ra, dec in [(180.772, 0.363), (180.772, 0.9), (180.772, -0.2), (180.2, 0.363), (181.3, 0.363)]:
    try:
        dx, dy, w_, b_, d, det = measure(cutout(P3, ra, dec), ra, dec)
        print(f"  ({ra:8.3f},{dec:6.3f}) -> detpx=({dx:7.1f},{dy:7.1f})  WAVE={w_:.4f} bw={b_:.4f}")
    except Exception as e:
        print(f"  ({ra},{dec}): FAIL {type(e).__name__}: {e}")

RA, DEC = 180.0, 0.0
print(f"\nTEST 2 - one sky point ({RA},{DEC}) across visits, detector D3")
q = urllib.parse.urlencode({"QUERY": f"SELECT obs_id,t_min,access_url FROM spherex.obscore WHERE "
    f"CONTAINS(POINT('ICRS',{RA},{DEC}),s_region)=1 AND energy_bandpassname='SPHEREx-D3' ORDER BY t_min",
    "FORMAT": "csv"})
rows = [r.split(",") for r in get(f"https://irsa.ipac.caltech.edu/TAP/sync?{q}").decode().strip().splitlines()[1:]]
seen, picks = set(), []
for oid, tm, u in rows:
    v = oid.rsplit("_", 1)[0]
    if v not in seen: seen.add(v); picks.append((oid, float(tm), u))
out = []
for oid, tm, dl in [picks[i] for i in np.linspace(0, len(picks)-1, min(8, len(picks))).astype(int)]:
    try:
        pth = re.findall(r"<TD>(spherex/[^<]+\.fits)</TD>", get(dl, 120).decode())
        if not pth: continue
        dx, dy, w_, b_, d, det = measure(cutout(pth[0], RA, DEC), RA, DEC)
        out.append(dict(obs_id=oid, mjd=tm, date_obs=d, det_x=dx, det_y=dy,
                        wavelength_um=w_, bandwidth_um=b_))
        print(f"  {oid} mjd={tm:.2f} detpx=({dx:7.1f},{dy:7.1f}) WAVE={w_:.4f} bw={b_:.4f}")
    except Exception as e:
        print(f"  {oid}: FAIL {type(e).__name__}: {e}")
if len(out) >= 2:
    w = [o["wavelength_um"] for o in out]; b = float(np.median([o["bandwidth_um"] for o in out]))
    s = max(w) - min(w)
    print(f"\n*** wavelength {min(w):.4f}..{max(w):.4f} um  spread={s:.4f} um = {s/b:.1f} bandwidths")
    print(f"*** detector Y spanned: {min(o['det_y'] for o in out):.0f}..{max(o['det_y'] for o in out):.0f}")
    print("*** VERDICT:", "BAND NAME INSUFFICIENT - must match on per-pixel wavelength"
          if s > b else "these visits aligned; per-frame wavelength check still required")
json.dump(out, open("/Users/seksatya/quickx/probe/recorded_wave_correct.json", "w"), indent=2)
