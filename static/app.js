lucide.createIcons();

// Dark mode toggle
const themeToggle = document.getElementById('theme-toggle');
const html = document.documentElement;
const isDark = localStorage.getItem('theme') === 'dark' || (!localStorage.getItem('theme') && window.matchMedia('(prefers-color-scheme: dark)').matches);
if (isDark) html.classList.add('dark');
themeToggle.addEventListener('click', () => {
    html.classList.toggle('dark');
    localStorage.setItem('theme', html.classList.contains('dark') ? 'dark' : 'light');
    lucide.createIcons();
});

// Tab navigation
const tabGenerate = document.getElementById('tab-generate');
const tabPreview = document.getElementById('tab-preview');
const contentGenerate = document.getElementById('tab-content-generate');
const contentPreview = document.getElementById('tab-content-preview');

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active', 'border-blue-600', 'text-blue-600'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active', 'border-blue-600', 'text-blue-600');
    if (tab === tabGenerate) {
        contentGenerate.classList.add('active');
    } else {
        contentPreview.classList.add('active');
    }
}

tabGenerate.addEventListener('click', () => switchTab(tabGenerate));
tabPreview.addEventListener('click', () => switchTab(tabPreview));

// State
let uploadedFiles = [];
let currentFont = null;
let currentFontName = null;

// DOM Elements
const upmInput = document.getElementById('upm');
const upmVal = document.getElementById('upm-val');
const widthInput = document.getElementById('advance_width');
const widthVal = document.getElementById('width-val');
const raiseInput = document.getElementById('vertical_raise');
const raiseVal = document.getElementById('raise-val');
const monospaceToggle = document.getElementById('monospace-toggle');
const advanceWidthGroup = document.getElementById('advance-width-group');

const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');
const previewCard = document.getElementById('preview-card');
const fileCount = document.getElementById('file-count');
const glyphGrid = document.getElementById('glyph-grid');
const generateBtn = document.getElementById('generate-btn');
const clearBtn = document.getElementById('clear-btn');

const loadingModal = document.getElementById('loading-modal');
const successModal = document.getElementById('success-modal');
const modalStatus = document.getElementById('modal-status');
const closeSuccessBtn = document.getElementById('close-success-btn');
const testText = document.getElementById('test-text');
const charsetGrid = document.getElementById('charset-grid');

const fontnameInput = document.getElementById('fontname');
const fullnameInput = document.getElementById('fullname');
const familynameInput = document.getElementById('familyname');

// Preview controls
const previewFontSize = document.getElementById('preview-font-size');
const sizeVal = document.getElementById('size-val');
const previewLetterSpacing = document.getElementById('preview-letter-spacing');
const spacingVal = document.getElementById('spacing-val');
const previewLineHeight = document.getElementById('preview-line-height');
const lineHeightVal = document.getElementById('line-height-val');
const previewDisplay = document.getElementById('preview-display');
const previewCharset = document.getElementById('preview-charset');
const previewTestText = document.getElementById('preview-test-text');

// Event listeners for sliders
upmInput.addEventListener('input', e => upmVal.textContent = e.target.value);
widthInput.addEventListener('input', e => widthVal.textContent = e.target.value);
raiseInput.addEventListener('input', e => raiseVal.textContent = e.target.value);

// Monospace toggle
monospaceToggle.addEventListener('change', () => {
    widthInput.disabled = !monospaceToggle.checked;
    advanceWidthGroup.classList.toggle('opacity-50');
});

// Preview size controls
previewFontSize.addEventListener('input', e => {
    sizeVal.textContent = e.target.value;
    updatePreviewStyle();
});

previewLetterSpacing.addEventListener('input', e => {
    spacingVal.textContent = e.target.value;
    updatePreviewStyle();
});

previewLineHeight.addEventListener('input', e => {
    lineHeightVal.textContent = e.target.value;
    updatePreviewStyle();
});

previewTestText.addEventListener('input', e => {
    previewDisplay.textContent = e.target.value || 'The quick brown fox jumps over the lazy dog';
});

function updatePreviewStyle() {
    if (previewDisplay) {
        previewDisplay.style.fontSize = previewFontSize.value + 'px';
        previewDisplay.style.letterSpacing = previewLetterSpacing.value + 'px';
        previewDisplay.style.lineHeight = previewLineHeight.value;
    }
    if (previewCharset) {
        previewCharset.style.fontSize = previewFontSize.value + 'px';
        previewCharset.style.letterSpacing = previewLetterSpacing.value + 'px';
        previewCharset.style.lineHeight = previewLineHeight.value;
    }
}

// Helper functions
function inferCharacter(filename) {
    const stem = filename.replace(/\.png$/i, '').split('_')[0];
    if (stem.length === 1) return { char: stem, code: '0x' + stem.charCodeAt(0).toString(16).toUpperCase() };
    const uMatch = stem.match(/^u([0-9a-fA-F]+)$/);
    if (uMatch) {
        const val = parseInt(uMatch[1], 16);
        return { char: String.fromCodePoint(val), code: '0x' + val.toString(16).toUpperCase() };
    }
    const hexMatch = stem.match(/^([0-9a-fA-F]+)$/);
    if (hexMatch) {
        const val = parseInt(hexMatch[1], 16);
        return { char: String.fromCodePoint(val), code: '0x' + val.toString(16).toUpperCase() };
    }
    return { char: '?', code: 'Unknown' };
}

function handleFiles(files) {
    Array.from(files).forEach(file => {
        if (!file.name.toLowerCase().endsWith('.png')) return;
        if (uploadedFiles.some(f => f.name === file.name)) return;
        uploadedFiles.push(file);
    });
    updateGrid();
}

function updateGrid() {
    if (uploadedFiles.length === 0) {
        previewCard.classList.add('hidden');
        generateBtn.disabled = true;
        return;
    }
    previewCard.classList.remove('hidden');
    generateBtn.disabled = false;
    fileCount.textContent = uploadedFiles.length;
    glyphGrid.innerHTML = '';
    uploadedFiles.sort((a, b) => a.name.localeCompare(b.name));
    uploadedFiles.forEach((file, i) => {
        const reader = new FileReader();
        const card = document.createElement('div');
        card.className = 'relative p-2 bg-gray-100 dark:bg-gray-700 rounded text-center';
        const { char, code } = inferCharacter(file.name);
        card.innerHTML = `
            <button class="remove-glyph absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white rounded-full text-xs" data-index="${i}">×</button>
            <img id="img-${i}" class="w-full h-12 object-contain mb-1">
            <div class="text-xs"><span class="font-bold">${char}</span><br><span class="text-gray-500 dark:text-gray-400">${code}</span></div>
        `;
        glyphGrid.appendChild(card);
        reader.onload = e => document.getElementById(`img-${i}`).src = e.target.result;
        reader.readAsDataURL(file);
    });
    document.querySelectorAll('.remove-glyph').forEach(btn => {
        btn.addEventListener('click', () => {
            uploadedFiles.splice(parseInt(btn.dataset.index), 1);
            updateGrid();
        });
    });
}

function setupDropZone(zone, handler) {
    zone.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); zone.classList.add('border-blue-500', 'bg-blue-50', 'dark:bg-blue-900/10'); }, false);
    zone.addEventListener('dragleave', e => { e.preventDefault(); e.stopPropagation(); if (e.target === zone) zone.classList.remove('border-blue-500', 'bg-blue-50', 'dark:bg-blue-900/10'); }, false);
    zone.addEventListener('drop', e => { e.preventDefault(); e.stopPropagation(); zone.classList.remove('border-blue-500', 'bg-blue-50', 'dark:bg-blue-900/10'); handler(e.dataTransfer.files); }, false);
}

// Setup main dropzone
setupDropZone(dropzone, handleFiles);
dropzone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', e => { handleFiles(e.target.files); e.target.value = ''; });
clearBtn.addEventListener('click', () => { uploadedFiles = []; updateGrid(); });

// Pipeline step tracking
function setStepActive(id) {
    document.querySelectorAll('.step-item').forEach(el => el.classList.remove('active', 'completed'));
    const step = document.getElementById(id);
    if (step) {
        step.classList.add('active');
        let prev = step.previousElementSibling;
        while (prev) { prev.classList.add('completed'); prev = prev.previousElementSibling; }
    }
}

const PHASE_MAP = {
    queued: 'step-upload',
    tracing: 'step-trace',
    shifting: 'step-shift',
    flattening: 'step-flatten',
    fontforge: 'step-compile',
    'svg-embed': 'step-embed',
    'color-optimize': 'step-color',
    woff: 'step-optimize',
    woff2: 'step-optimize',
    zipping: 'step-optimize',
    done: 'step-optimize'
};

const sleep = ms => new Promise(r => setTimeout(r, ms));
const formatSize = bytes => bytes < 1024 ? bytes + ' B' : bytes < 1024*1024 ? (bytes/1024).toFixed(1) + ' KB' : (bytes/(1024*1024)).toFixed(2) + ' MB';

async function pollJob(jobId) {
    while (true) {
        await sleep(2000);
        try {
            const res = await fetch(`/api/job/${jobId}`);
            if (!res.ok) continue;
            const status = await res.json();
            if (status.status === 'completed') return;
            if (status.status === 'failed') throw new Error(status.detail || 'Failed');
            const stepId = PHASE_MAP[status.phase];
            if (stepId) setStepActive(stepId);
            if (status.detail) modalStatus.textContent = status.detail;
        } catch (e) {
            if (e instanceof TypeError) continue;
            throw e;
        }
    }
}

// Generate font
generateBtn.addEventListener('click', async () => {
    if (uploadedFiles.length === 0) return;
    const form = new FormData();
    uploadedFiles.forEach(f => form.append('files', f));
    form.append('fontname', fontnameInput.value || 'MyCustomFont');
    form.append('fullname', fullnameInput.value || 'My Custom Font');
    form.append('familyname', familynameInput.value || 'My Family');
    form.append('upm', upmInput.value);
    form.append('advance_width', widthInput.value);
    form.append('vertical_raise', raiseInput.value);
    form.append('monospace', monospaceToggle.checked);

    loadingModal.classList.remove('hidden');
    setStepActive('step-upload');
    modalStatus.textContent = 'Starting...';

    try {
        const res = await fetch(`/api/generate-font`, { method: 'POST', body: form });
        if (!res.ok) throw new Error((await res.json()).detail || 'Failed');
        const { job_id } = await res.json();

        await pollJob(job_id);

        const result = await fetch(`/api/job/${job_id}/result`);
        if (!result.ok) throw new Error((await result.json()).detail || 'Failed');
        const zip = await JSZip.loadAsync(await result.blob());

        let ttf = null, woff2 = null;
        for (const name in zip.files) {
            const data = await zip.files[name].async('blob');
            const url = URL.createObjectURL(data);
            if (name.endsWith('.ttf')) ttf = { blob: data, url, name };
            else if (name.endsWith('.woff2')) woff2 = { blob: data, url, name };
        }

        document.querySelectorAll('.step-item').forEach(el => el.classList.add('completed'));

        const fontName = 'PreviewFont_' + Date.now();
        if (woff2) {
            const ff = new FontFace(fontName, `url(${woff2.url})`);
            await ff.load();
            document.fonts.add(ff);
            testText.style.fontFamily = `"${fontName}"`;
            charsetGrid.style.fontFamily = `"${fontName}"`;
            testText.value = `Hello from your new font!\nThis is "${fullnameInput.value}"`;
        }

        [['ttf', ttf], ['woff2', woff2]].forEach(([fmt, file]) => {
            const link = document.getElementById(`download-${fmt}`);
            if (file) {
                link.href = file.url;
                link.download = file.name;
                link.style.display = 'block';
                document.getElementById(`size-${fmt}`).textContent = formatSize(file.blob.size);
            }
        });

        loadingModal.classList.add('hidden');
        successModal.classList.remove('hidden');
    } catch (e) {
        loadingModal.classList.add('hidden');
        alert('Error: ' + e.message);
    }
});

closeSuccessBtn.addEventListener('click', () => successModal.classList.add('hidden'));

// Font Preview
const fontFileInput = document.getElementById('font-file-input');
const fontDropzone = document.getElementById('font-dropzone');
const fontInfoSection = document.getElementById('font-info-section');
const testBenchSection = document.getElementById('test-bench-section');
const previewControlsSection = document.getElementById('preview-controls-section');
const previewDisplaySection = document.getElementById('preview-display-section');
const charsetSection = document.getElementById('charset-section');

function loadFontFile(file) {
    const reader = new FileReader();
    reader.onload = async e => {
        try {
            const ext = file.name.split('.').pop().toLowerCase();
            const mimeType = { ttf: 'font/ttf', woff: 'font/woff', woff2: 'font/woff2' }[ext] || 'application/octet-stream';
            const blob = new Blob([e.target.result], { type: mimeType });
            const url = URL.createObjectURL(blob);
            currentFontName = 'PreviewFont_' + Date.now();

            const ff = new FontFace(currentFontName, `url(${url})`);
            await ff.load();
            document.fonts.add(ff);

            document.getElementById('info-font-name').textContent = file.name;
            document.getElementById('info-file-size').textContent = formatSize(file.size);
            document.getElementById('info-format').textContent = ext.toUpperCase();
            fontInfoSection.classList.remove('hidden');
            testBenchSection.classList.remove('hidden');
            previewControlsSection.classList.remove('hidden');
            previewDisplaySection.classList.remove('hidden');
            charsetSection.classList.remove('hidden');

            previewTestText.value = 'The quick brown fox jumps over the lazy dog';
            updatePreview();
        } catch (err) {
            alert('Error: ' + err.message);
        }
    };
    reader.readAsArrayBuffer(file);
}

function updatePreview() {
    if (!currentFontName) return;
    const style = `"${currentFontName}"`;
    previewDisplay.style.fontFamily = style;
    previewCharset.style.fontFamily = style;
    updatePreviewStyle();
}

setupDropZone(fontDropzone, files => loadFontFile(Array.from(files).find(f => f.name.endsWith('.ttf') || f.name.endsWith('.woff') || f.name.endsWith('.woff2'))));
fontDropzone.addEventListener('click', () => fontFileInput.click());
fontFileInput.addEventListener('change', e => { if (e.target.files[0]) loadFontFile(e.target.files[0]); e.target.value = ''; });
