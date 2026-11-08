"""Fetch real cutouts for several epochs covering one sky point and compute
the LVF wavelength each epoch actually sampled there. Proves the science rule."""
import sys, re, json, time, urllib.parse, urllib.request
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

UA = "QuickX/0.1 (service discovery; NASA SPHEREx blink comparator)"
RA, DEC = 180.0, 0.0

def get(url, timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def tap(query):
    q = urllib.parse.urlencode({"QUERY": query, "FORMAT": "csv"})
    return get(f"https://irsa.ipac.caltech.edu/TAP/sync?{q}").decode()

rows = tap(f"SELECT obs_id, energy_bandpassname, t_min, access_url, obs_collection "
           f"FROM spherex.obscore "
           f"WHERE CONTAINS(POINT('ICRS',{RA},{DEC}), s_region)=1 "
           f"AND energy_bandpassname='SPHEREx-D3' ORDER BY t_min").strip().splitlines()
hdr, data = rows[0].split(","), [r.split(",") for r in rows[1:]]
print(f"found {len(data)} D3 frames covering ({RA},{DEC})")

results = []
for obs_id, band, t_min, dl_url, coll in data[:5]:
    try:
        xml = get(dl_url, timeout=120).decode()
        paths = re.findall(r"<TD>(spherex/[^<]+\.fits)</TD>", xml)
        if not paths:
            print(f"  {obs_id}: no cutout path"); continue
        cut = urllib.parse.urlencode({"path": paths[0], "ra": RA, "dec": DEC, "size": 0.02})
        t0 = time.time()
        blob = get(f"https://irsa.ipac.caltech.edu/ibe/cutout?{cut}", timeout=300)
        dt = time.time() - t0
        open("/tmp/_e.fits", "wb").write(blob)
        with fits.open("/tmp/_e.fits") as hdul:
            h = hdul["IMAGE"].header
            x, y = WCS(h).all_world2pix(RA, DEC, 0)
            fx, fy = x + (h["CRPIX1"] - h["CRPIX1W"]), y + (h["CRPIX2"] - h["CRPIX2W"])
            t = hdul["WCS-WAVE"].data[0]
            X, Y, V = np.asarray(t["X"], float), np.asarray(t["Y"], float), np.asarray(t["VALUES"], float)
            def ip(p):
                return float(np.interp(fy, Y, [np.interp(fx, X, p[j]) for j in range(len(Y))]))
            wave, bw = ip(V[:, :, 0]), ip(V[:, :, 1])
            results.append((obs_id, float(t_min), h["DATE-OBS"], fx, fy, wave, bw, len(blob), dt))
            print(f"  {obs_id} mjd={float(t_min):.3f} detpx=({fx:7.1f},{fy:7.1f}) "
                  f"WAVE={wave:.4f}um bw={bw:.4f} ({len(blob)/1e6:.1f}MB {dt:.0f}s)")
    except Exception as e:
        print(f"  {obs_id}: FAIL {type(e).__name__}: {e}")

if len(results) >= 2:
    waves = [r[5] for r in results]
    bws = [r[6] for r in results]
    spread = max(waves) - min(waves)
    print(f"\n*** wavelength spread across epochs at SAME sky point, SAME detector: {spread:.4f} um")
    print(f"*** median bandwidth: {np.median(bws):.4f} um -> spread is {spread/np.median(bws):.1f} bandwidths")
    print("*** VERDICT:", "band name is NOT sufficient; must match on per-pixel wavelength"
          if spread > np.median(bws) else "epochs happen to align; still must verify per frame")
json.dump([{"obs_id": r[0], "mjd": r[1], "date_obs": r[2], "det_x": r[3], "det_y": r[4],
            "wavelength_um": r[5], "bandwidth_um": r[6], "bytes": r[7], "seconds": r[8]}
           for r in results], open("/Users/seksatya/quickx/probe/recorded_epoch_waves.json", "w"), indent=2)
