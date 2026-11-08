"""Dump every alternate-'W' WCS key and try using it directly for wavelength."""
import sys, numpy as np
from astropy.io import fits
from astropy.wcs import WCS

with fits.open(sys.argv[1]) as hd:
    h = hd["IMAGE"].header
    print("=== all *W / *A keys ===")
    for k in sorted(h.keys()):
        if k.endswith("W") or k.endswith("A"):
            print(f"  {k:12s} = {h[k]!r}")
    print("\n=== try WCS(key='W') ===")
    try:
        ww = WCS(h, key="W")
        print("  ctype:", ww.wcs.ctype, "cunit:", ww.wcs.cunit)
        print("  crpix:", ww.wcs.crpix, "crval:", ww.wcs.crval, "cdelt:", ww.wcs.cdelt)
        n1, n2 = h["NAXIS1"], h["NAXIS2"]
        for (px, py) in [(0, 0), (n1//2, n2//2), (n1-1, n2-1)]:
            print(f"  pix({px},{py}) -> {ww.wcs_pix2world([[px, py]], 0)}")
    except Exception as e:
        print("  FAILED:", type(e).__name__, e)
    print("\n=== WCS-WAVE grid value at cutout centre vs W-WCS ===")
    t = hd["WCS-WAVE"].data[0]
    X, Y, V = (np.asarray(t[k], float) for k in ("X", "Y", "VALUES"))
    print("  node wave corners:", V[0,0,0], V[0,-1,0], V[-1,0,0], V[-1,-1,0])
