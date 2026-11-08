/**
 * Client for the QuickX backend.
 */
export class QuickXClient {
  constructor(baseUrl = '') {
    // Relative URL so it automatically uses window.location origin (works under same-port serving)
    this.baseUrl = baseUrl;
  }

  async fetch(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const resp = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
  }

  async resolve(name) {
    return this.fetch('/api/resolve', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  async search(ra, dec, detector = null) {
    return this.fetch('/api/search', {
      method: 'POST',
      body: JSON.stringify({ ra, dec, detector }),
    });
  }

  async createJob(params) {
    return this.fetch('/api/jobs', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  }

  async getJob(jobId) {
    return this.fetch(`/api/jobs/${jobId}`);
  }

  async getMovingObject(name) {
    return this.fetch('/api/moving-object', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }
}

/**
 * Image processing and canvas rendering.
 */
export class Viewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.frames = [];
    this.differenceFrames = [];
    this.mode = 'blink';
    this.currentIdx = 0;
    this.isPlaying = false;
    this.intervalId = null;
    this.speed = 400;
  }

  setFrames(frames, differenceFrames = []) {
    this.frames = frames.map(f => ({
      ...f,
      img: this.decodePng(f.png_b64)
    }));
    this.differenceFrames = differenceFrames.map(df => ({
      ...df,
      img: this.decodePng(df.png_b64)
    }));
    this.currentIdx = 0;
    this.drawCurrent();
  }

  decodePng(hex) {
    const bytes = new Uint8Array(hex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
    const blob = new Blob([bytes], { type: 'image/png' });
    const img = new Image();
    img.src = URL.createObjectURL(blob);
    return img;
  }

  setMode(mode) {
    this.mode = mode;
    this.currentIdx = 0;
    this.drawCurrent();
  }

  drawCurrent() {
    const list = (this.mode === 'difference' && this.differenceFrames.length > 0)
      ? this.differenceFrames
      : this.frames;

    if (!list.length) return;
    const item = list[this.currentIdx];
    const img = item.img;

    if (!img.complete) {
      img.onload = () => this.drawCurrent();
      return;
    }

    this.canvas.width = img.naturalWidth;
    this.canvas.height = img.naturalHeight;
    this.ctx.imageSmoothingEnabled = false;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.ctx.drawImage(img, 0, 0);

    // Update metadata badge safely if elements exist
    const bObs = document.getElementById('badge-obsid');
    const bDate = document.getElementById('badge-date');
    const bWave = document.getElementById('badge-wave');

    if (bObs) bObs.textContent = item.obs_id || (item.pair ? item.pair.join(' − ') : '');
    if (bDate) bDate.textContent = item.date_obs ? new Date(item.date_obs).toLocaleDateString() : '';
    if (bWave) bWave.textContent = `${item.wavelength_um} µm`;

    // Highlight current in list
    document.querySelectorAll('.epoch-item').forEach((el, i) => {
      el.classList.toggle('border-cyan-500', i === this.currentIdx);
      el.classList.toggle('bg-cyan-500/10', i === this.currentIdx);
    });
  }

  start() {
    const list = (this.mode === 'difference' && this.differenceFrames.length > 0)
      ? this.differenceFrames
      : this.frames;

    if (this.isPlaying || list.length < 2) return;
    this.isPlaying = true;
    this.intervalId = setInterval(() => {
      this.currentIdx = (this.currentIdx + 1) % list.length;
      this.drawCurrent();
    }, this.speed);
  }

  stop() {
    this.isPlaying = false;
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  setSpeed(ms) {
    this.speed = ms;
    if (this.isPlaying) {
      this.stop();
      this.start();
    }
  }
}
