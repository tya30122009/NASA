# QuickX

A free public web tool: pick a spot in the sky and watch how it changes across NASA SPHEREx observations. No coding or astronomy background needed.

## Features
- **Sky Search:** Resolve object names via NED, enter coordinates, or click the map.
- **Blink Comparator:** Flip between observations of the same sky across time.
- **Spectral-Channel Matching:** Automatically matches observations by per-pixel LVF wavelength (`WCS-WAVE`) to prevent false motion signals caused by colour differences (Critical Science Rule #3).
- **Difference Mode:** Subtract matched-band frames so moving objects appear as bright/dark pairs against fixed stars.
- **Wavelength False Colour:** Optional tint coding each frame's LVF wavelength (blue = short, red = long); brightness still carries surface brightness and frames are labelled as false colour. Difference frames stay grayscale.
- **Spectrum Inspector:** View the spectral energy distribution across matched bands.
- **Solar System Overlays:** Compare predicted vs. observed positions for moving targets.

## Running the Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn backend.app.main:app --reload --port 8000
```

## Running Tests
```bash
export PYTHONPATH=.
pytest backend/tests/
```
