import sys, numpy as np
from astropy.io import fits
from astropy.wcs import WCS

path, ra, dec = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
with fits.open(path) as hdul:
    hdr = hdul["IMAGE"].header
    print("=== cutout origin / time / band keys ===")
    for k in hdr:
        if any(s in k.upper() for s in ("LTV","LTM","CRPIX","NAXIS","MJD","DATE","BAND","DETEC","CHAN","ORIG","XTENSION","OBSID","OBS_ID","UNIT")):
            print(f"  {k} = {hdr[k]!r}")
    w = WCS(hdr)
    x, y = w.all_world2pix(ra, dec, 0)
    print(f"\ncutout pixel for RA/Dec: x={x:.3f} y={y:.3f}  (cutout shape {hdr['NAXIS1']}x{hdr['NAXIS2']})")

    t = hdul["WCS-WAVE"].data[0]
    X, Y, V = np.asarray(t["X"]), np.asarray(t["Y"]), np.asarray(t["VALUES"])
    print("WCS-WAVE X nodes:", X)
    print("WCS-WAVE Y nodes:", Y)
    print("VALUES shape:", V.shape, "wavelength range um:", float(V[...,0].min()), "-", float(V[...,0].max()))
    print("bandwidth range um:", float(V[...,1].min()), "-", float(V[...,1].max()))
    # wavelength varies along which axis?
    print("\nwave vs Y (at mid X):", np.round(V[:, 4, 0], 4))
    print("wave vs X (at mid Y):", np.round(V[7, :, 0], 4))
