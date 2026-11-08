"""Decisive diagnostic: fetch cutouts at DIFFERENT sky points from the SAME frame.
If the computed full-detector pixel is always ~1025, the offset formula is wrong."""
import urllib.parse, urllib.request
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

UA = "QuickX/0.1 (service discovery)"
P = "spherex/qr2/level2/2025W20_2D/l2b-v20-2025-247/3/level2_2025W20_2D_0234_1D3_spx_l2b-v20-2025-247.fits"
# frame centre was s_ra=180.772136 s_dec=0.363313; sample points across the ~3.5deg field
pts = [(180.772, 0.363), (180.2, 0.363), (181.3, 0.363), (180.772, -0.2), (180.772, 0.9)]

for ra, dec in pts:
    u = urllib.parse.urlencode({"path": P, "ra": ra, "dec": dec, "size": 0.02})
    try:
        blob = urllib.request.urlopen(urllib.request.Request(
            f"https://irsa.ipac.caltech.edu/ibe/cutout?{u}",
            headers={"User-Agent": UA}), timeout=300).read()
    except Exception as e:
        print(f"({ra},{dec}): FETCH FAIL {e}"); continue
    open("/tmp/_d.fits", "wb").write(blob)
    with fits.open("/tmp/_d.fits") as hd:
        h = hd["IMAGE"].header
        x, y = WCS(h).all_world2pix(ra, dec, 0)
        offx, offy = h["CRPIX1"] - h["CRPIX1W"], h["CRPIX2"] - h["CRPIX2W"]
        fx, fy = x + offx, y + offy
        t = hd["WCS-WAVE"].data[0]
        X, Y, V = (np.asarray(t[k], float) for k in ("X", "Y", "VALUES"))
        ip = lambda p: float(np.interp(fy, Y, [np.interp(fx, X, p[j]) for j in range(len(Y))]))
        print(f"({ra:8.3f},{dec:6.3f}) cut=({x:5.2f},{y:5.2f}) "
              f"CRPIX=({h['CRPIX1']:8.1f},{h['CRPIX2']:8.1f}) "
              f"CRPIXW=({h['CRPIX1W']:7.1f},{h['CRPIX2W']:7.1f}) "
              f"off=({offx:7.1f},{offy:7.1f}) full=({fx:7.1f},{fy:7.1f}) WAVE={ip(V[:,:,0]):.4f}")
