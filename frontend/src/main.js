import { QuickXClient, Viewer } from './app.js';
import { renderSpectrum } from './viz.js';

const client = new QuickXClient();
const viewer = new Viewer(document.getElementById('blink-canvas'));

const state = {
    jobId: null,
    frames: [],
    differenceFrames: [],
    spectrum: [],
    currentIdx: 0,
    playing: false,
    color: false,
    lastTarget: null
};

const statusBar = document.getElementById('status-bar');
const searchBtn = document.getElementById('search-btn');
const objSearch = document.getElementById('obj-search');
const playBtn = document.getElementById('play-btn');
const metaOverlay = document.getElementById('meta-overlay');
const epochsList = document.getElementById('obs-list');

async function search(name) {
    try {
        statusBar.textContent = 'Resolving name via NED...';
        const obj = await client.resolve(name);
        state.lastTarget = { ra: obj.ra, dec: obj.dec };
        await startJob(obj.ra, obj.dec);
    } catch (err) {
        statusBar.textContent = `Error: ${err.message}`;
        console.error(err);
    }
}

async function startJob(ra, dec) {
    statusBar.textContent = 'Creating job...';
    const job = await client.createJob({
        ra,
        dec,
        stretch: 'asinh',
        color: state.color
    });
    state.jobId = job.job_id;
    pollJob();
}

async function pollJob() {
    if (!state.jobId) return;
    try {
        const job = await client.getJob(state.jobId);
        statusBar.textContent = `Job: ${job.status} (${job.progress}/${job.total})`;

        if (job.frames && job.frames.length > 0) {
            state.frames = job.frames;
            state.differenceFrames = job.difference_frames || [];
            state.spectrum = job.spectrum || [];

            viewer.setFrames(job.frames, state.differenceFrames);
            renderEpochList(job.frames);
            renderSpectrum(state.spectrum);
            renderDetails(job);
        }

        if (job.status === 'running' || job.status === 'pending') {
            // 2s cadence: 1s polling alone saturates the per-IP token bucket
            setTimeout(pollJob, 2000);
        }
    } catch (err) {
        statusBar.textContent = `Polling error: ${err.message}`;
        // Transient failures (e.g. 429) must not strand the viewer mid-job
        if (err.message !== 'Job not found') setTimeout(pollJob, 2000);
    }
}

function renderEpochList(frames) {
    epochsList.innerHTML = '';
    frames.forEach((f, i) => {
        const el = document.createElement('div');
        el.className = 'epoch-item p-2 text-xs border-b border-white/5 cursor-pointer hover:bg-white/5 flex justify-between items-center';
        el.innerHTML = `
            <div>
                <div class="font-mono text-cyan-400">${f.obs_id.split('_').slice(-2).join('_')}</div>
                <div class="text-[10px] text-slate-400">${new Date(f.date_obs).toLocaleDateString()}</div>
            </div>
            <div class="text-right">
                <div class="text-amber-300 font-mono">${f.wavelength_um} µm</div>
                <div class="text-[10px] text-slate-500">Det ${f.detector}</div>
            </div>
        `;
        el.onclick = () => {
            viewer.stop();
            playBtn.textContent = 'Play';
            viewer.currentIdx = i;
            viewer.drawCurrent();
        };
        epochsList.appendChild(el);
    });
}

function renderDetails(job) {
    const frameDetails = document.getElementById('frame-details');
    if (!frameDetails) return;

    const diag = job.matching_diagnostic || {};
    frameDetails.innerHTML = `
        <div class="space-y-1 text-xs">
            <div class="text-slate-400">Anchor Wave: <span class="text-white">${diag.anchor_wavelength_um?.toFixed(4) || '--'} µm</span></div>
            <div class="text-slate-400">Bandwidth: <span class="text-white">${diag.reference_bandwidth_um?.toFixed(4) || '--'} µm</span></div>
            <div class="text-slate-400">Matched Frames: <span class="text-cyan-400">${diag.matched_count || 0} / ${diag.total_count || 0}</span></div>
            <div class="text-[10px] text-slate-500 mt-2">Critical science rule applied: LVF per-pixel matching within ±1 bandwidth.</div>
        </div>
    `;
}

searchBtn.onclick = () => {
    const name = objSearch.value.trim();
    if (name) search(name);
};

objSearch.onkeydown = (e) => {
    if (e.key === 'Enter') {
        const name = objSearch.value.trim();
        if (name) search(name);
    }
};

playBtn.onclick = () => {
    if (viewer.isPlaying) {
        viewer.stop();
        playBtn.textContent = 'Play';
    } else {
        viewer.start();
        playBtn.textContent = 'Pause';
    }
};

const colorBtn = document.getElementById('color-btn');
colorBtn.onclick = async () => {
    state.color = !state.color;
    colorBtn.setAttribute('aria-pressed', String(state.color));
    if (!state.lastTarget) return;
    try {
        // Cached cutouts are re-rendered server-side, so this stays fast.
        await startJob(state.lastTarget.ra, state.lastTarget.dec);
    } catch (err) {
        statusBar.textContent = `Error: ${err.message}`;
    }
};

// Mode switching
document.querySelectorAll('.segmented-btn').forEach(btn => {
    btn.onclick = () => {
        document.querySelectorAll('.segmented-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const mode = btn.dataset.mode;
        viewer.setMode(mode);
    };
});

// Override Viewer.drawCurrent to update our specific overlay
const originalDraw = viewer.drawCurrent.bind(viewer);
viewer.drawCurrent = () => {
    originalDraw();
    const list = (viewer.mode === 'difference' && viewer.differenceFrames.length > 0)
        ? viewer.differenceFrames
        : viewer.frames;

    if (list.length > 0) {
        const frame = list[viewer.currentIdx];
        if (viewer.mode === 'difference') {
            metaOverlay.innerHTML = `
                <div class="text-amber-400 font-mono text-[10px]">Difference Pair</div>
                <div class="text-white text-[10px]">${frame.pair ? frame.pair.join(' vs ') : ''}</div>
                <div class="text-cyan-300 text-[10px]">${frame.wavelength_um} µm</div>
            `;
        } else {
            const colorNote = frame.color
                ? '<div class="false-color-note">False colour · wavelength tint</div>'
                : '';
            metaOverlay.innerHTML = `
                <div class="text-cyan-400 font-mono text-[10px]">${frame.obs_id}</div>
                <div class="text-white text-[10px]">${frame.wavelength_um} µm ± ${frame.bandwidth_um}</div>
                <div class="text-slate-400 text-[10px]">${new Date(frame.date_obs).toLocaleString()}</div>
                ${colorNote}
            `;
        }
    }
};
