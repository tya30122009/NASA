"""Sample D3 epochs spread across the FULL time baseline (not one visit) and
measure the wavelength each sampled at a fixed sky point."""
import re, json, time, urllib.parse, urllib.request
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

UA = "QuickX/0.1 (service discovery; NASA SPHEREx blink comparator)"
RA, DEC = 180.0, 0.0

def get(url, timeout=300):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout).read()

q = urllib.parse.urlencode({"QUERY": f"SELECT obs_id, t_min, access_url FROM spherex.obscore "
    f"WHERE CONTAINS(POINT('ICRS',{RA},{DEC}), s_region)=1 AND energy_bandpassname='SPHEREx-D3' "
    f"ORDER BY t_min", "FORMAT": "csv"})
rows = [r.split(",") for r in
        get(f"https://irsa.ipac.caltech.edu/TAP/sync?{q}").decode().strip().splitlines()[1:]]
print(f"{len(rows)} D3 frames; MJD {float(rows[0][1]):.2f} .. {float(rows[-1][1]):.2f} "
      f"({float(rows[-1][1])-float(rows[0][1]):.0f} day baseline)")

# pick epochs spread across the baseline, one per distinct visit prefix
seen, picks = set(), []
for obs_id, t_min, url in rows:
    visit = obs_id.rsplit("_", 1)[0]
    if visit not in seen:
        seen.add(visit); picks.append((obs_id, float(t_min), url))
print(f"{len(picks)} distinct visits; sampling {min(6,len(picks))} across the baseline")
idx = np.linspace(0, len(picks) - 1, min(6, len(picks))).astype(int)

out = []
for obs_id, t_min, dl in [picks[i] for i in idx]:
    try:
        paths = re.findall(r"<TD>(spherex/[^<]+\.fits)</TD>", get(dl, 120).decode())
        if not paths: print(f"  {obs_id}: no path"); continue
        cu = urllib.parse.urlencode({"path": paths[0], "ra": RA, "dec": DEC, "size": 0.02})
        t0 = time.time()
        blob = get(f"https://irsa.ipac.caltech.edu/ibe/cutout?{cu}", 300)
        open("/tmp/_s.fits", "wb").write(blob)
        with fits.open("/tmp/_s.fits") as hd:
            h = hd["IMAGE"].header
            x, y = WCS(h).all_world2pix(RA, DEC, 0)
            fx = x + (h["CRPIX1"] - h["CRPIX1W"]); fy = y + (h["CRPIX2"] - h["CRPIX2W"])
            t = hd["WCS-WAVE"].data[0]
            X, Y, V = (np.asarray(t[k], float) for k in ("X", "Y", "VALUES"))
            ip = lambda p: float(np.interp(fy, Y, [np.interp(fx, X, p[j]) for j in range(len(Y))]))
            w_, b_ = ip(V[:, :, 0]), ip(V[:, :, 1])
            out.append(dict(obs_id=obs_id, mjd=t_min, date_obs=h["DATE-OBS"], det_x=fx, det_y=fy,
                            wavelength_um=w_, bandwidth_um=b_, bytes=len(blob), seconds=time.time()-t0))
            print(f"  {obs_id} mjd={t_min:.2f} detpx=({fx:7.1f},{fy:7.1f}) WAVE={w_:.4f} bw={b_:.4f}")
    except Exception as e:
        print(f"  {obs_id}: FAIL {type(e).__name__}: {e}")

if len(out) >= 2:
    w = [o["wavelength_um"] for o in out]; b = float(np.median([o["bandwidth_um"] for o in out]))
    s = max(w) - min(w)
    print(f"\n*** wavelength range: {min(w):.4f} .. {max(w):.4f} um  spread={s:.4f} um")
    print(f"*** median bandwidth {b:.4f} um -> spread = {s/b:.1f} bandwidths")
    print(f"*** detector rows spanned: {min(o['det_y'] for o in out):.0f} .. {max(o['det_y'] for o in out):.0f}")
    print("*** VERDICT:", "BAND NAME INSUFFICIENT - epochs sample different colours"
          if s > b else "these visits aligned in wavelength")
json.dump(out, open("/Users/seksatya/quickx/probe/recorded_epoch_spread.json", "w"), indent=2)
