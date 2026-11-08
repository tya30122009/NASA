import sys, numpy as np
from astropy.io import fits
from astropy.wcs import WCS

path, ra, dec = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
with fits.open(path) as hdul:
    im = hdul["IMAGE"]; hdr = im.header
    w = WCS(hdr)
    xc, yc = w.all_world2pix(ra, dec, 0)
    # offset of cutout within full detector, via the 'W' alternate WCS linear terms
    offx = hdr["CRPIX1"] - hdr["CRPIX1W"]
    offy = hdr["CRPIX2"] - hdr["CRPIX2W"]
    print(f"cutout px=({xc:.2f},{yc:.2f})  implied full-detector offset=({offx},{offy})")
    fx, fy = xc + offx, yc + offy
    print(f"full-detector px=({fx:.2f},{fy:.2f})  detector={hdr['DETECTOR']}")
    assert 0 <= fx <= 2041 and 0 <= fy <= 2041, "offset mapping out of detector bounds!"

    t = hdul["WCS-WAVE"].data[0]
    X, Y, V = np.asarray(t["X"], float), np.asarray(t["Y"], float), np.asarray(t["VALUES"], float)
    # V indexed [Y, X, (wave,bandwidth)]; bilinear interp on the node grid
    def interp(plane):
        row = [np.interp(fx, X, plane[j, :]) for j in range(len(Y))]
        return float(np.interp(fy, Y, row))
    wave = interp(V[:, :, 0]); bw = interp(V[:, :, 1])
    print(f"\nTARGET WAVELENGTH = {wave:.4f} um   bandwidth = {bw:.4f} um   R = {wave/bw:.1f}")
    print(f"header NCHANNEL={hdr.get('NCHANNEL')} WCHANNEL={hdr.get('WCHANNEL')}")
    print(f"obscore em_min/em_max for D3 = 1.6301-2.4346 um (whole detector span)")
    print(f"-> band name alone is {('INSUFFICIENT' if bw < 0.5 else 'ok')}: detector spans 0.80 um, this pixel samples {bw:.3f} um")
