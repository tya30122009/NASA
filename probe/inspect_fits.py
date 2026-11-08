import sys
from astropy.io import fits

path = sys.argv[1]
with fits.open(path) as hdul:
    hdul.info()
    print("\n=== PRIMARY HEADER (wavelength / LVF keys) ===")
    h0 = hdul[0].header
    for k in h0:
        if any(s in k.upper() for s in ("WAVE", "LVF", "BAND", "SPEC", "LAMB", "DETECT", "CHANNEL", "MJD", "DATE", "OBSID")):
            print(f"  {k} = {h0[k]!r}")
    for i, hdu in enumerate(hdul):
        name = hdu.name
        print(f"\n=== HDU {i} '{name}' type={type(hdu).__name__} ===")
        hdr = hdu.header
        print("  NAXIS:", [hdr.get(f"NAXIS{j}") for j in (1, 2)], "EXTNAME:", hdr.get("EXTNAME"))
        if hdu.data is not None and hasattr(hdu.data, "shape"):
            print("  data shape:", hdu.data.shape, "dtype:", hdu.data.dtype)
        if isinstance(hdu, fits.BinTableHDU):
            print("  columns:", hdu.columns.names)
            print("  nrows:", len(hdu.data))
            for r in hdu.data[:3]:
                print("   row:", r)
        for k in ("WCSNAME", "CTYPE1", "CTYPE2", "CRVAL1", "CRVAL2", "BUNIT", "COMMENT"):
            if k in hdr:
                print(f"  {k} = {hdr[k]!r}")
