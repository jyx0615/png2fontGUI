# png2font

## Overview

**png2font** converts bitmap glyph PNGs into monospace TTF (TrueType Font) files with color support. It traces PNG images to SVG, normalizes them, flattens them for outline generation, and embeds both SVG and COLR (v0) color table data into the final font for maximum browser and OS compatibility.

The service is a **TypeScript/Node.js HTTP API** that orchestrates job management and the multi-step generation pipeline, delegating font engineering to proven external tools (FontForge, nanoemoji, fontTools) as subprocesses. See [CLAUDE.md](CLAUDE.md) for the full architecture writeup.

## Prerequisites

- **Node.js**: v18.0.0 or later
- **npm**: v9.0.0 or later
- **FontForge**: required before any other setup. Install it using the [official instructions](https://github.com/fontforge/fontforge/blob/master/INSTALL.md).
- **Python environment** (managed via conda, provisioned by `setup_env.sh`): nanoemoji, vtracer, fontTools, and the other Python-side tools.

## Quick Start

### 1. Initialize the environment

```bash
# Provisions FontForge, nanoemoji, ttf2woff2, and Python packages (recommended with conda)
./setup_env.sh
```

### 2. Install Node dependencies

```bash
npm install
```

### 3. Build and run

```bash
npm run build   # Compiles static CSS (Tailwind) and TypeScript (src/ -> dist/)
npm start        # Runs dist/server.js
```

For local development with hot-reload:

```bash
npm run dev      # tsx watch src/server.ts + Tailwind watch
```

Or use the wrapper script, which activates the conda env first:

```bash
./run.sh
```

The server starts on **`http://127.0.0.1:8000`**.

### 4. Test it

```bash
# Health check
curl http://127.0.0.1:8000/health

# Upload PNGs and start a generation job
curl -F "files=@glyphs/A.png" \
     -F "fontname=TestFont" \
     -F "fullname=Test Font" \
     http://127.0.0.1:8000/api/generate-font
# => { "job_id": "abcd1234...", "status": "queued" }

# Poll job status
curl http://127.0.0.1:8000/api/job/abcd1234

# Download the result once status="completed"
curl http://127.0.0.1:8000/api/job/abcd1234/result -o fonts.zip
unzip fonts.zip
```

## Web UI & API

### Accessing the Interface

- **Browser UI**: http://127.0.0.1:8000/
  - Drag-and-drop PNG uploads
  - Live parameter controls
  - Tab-based font preview (TTF/WOFF/WOFF2) with size, letter-spacing, and line-height controls

### API Reference

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/health` | Health check — returns `{ "status": "ok" }` |
| `POST` | `/api/generate-font` | Upload PNGs (`files` field, multipart/form-data) and kick off a generation job |
| `GET` | `/api/job/:id` | Poll job status — `{ status, phase, detail, updated_at }` |
| `GET` | `/api/job/:id/result` | Download the result ZIP once `status="completed"` |

## Dependencies & Tools

### External Binaries

These tools must be installed separately (see `setup_env.sh`):

| Tool | Purpose | Installation |
|------|---------|--------------|
| **FontForge** | Font generation and scripting | [Official guide](https://github.com/fontforge/fontforge/blob/master/INSTALL.md) |
| **svgcleaner** | SVG normalization and optimization | [Download](https://github.com/RazrFalcon/svgcleaner/releases), place in project root, run `chmod +x svgcleaner` |
| **addsvg** | Embed SVG tables into TTF | Included in [opentype-svg](https://github.com/adobe-type-tools/opentype-svg) tools |
| **nanoemoji** | COLR v1 color-font table compiler | Installed via `setup_env.sh` / pip |
| **ttf2woff2** | TTF → WOFF2 conversion | Installed via `setup_env.sh` |

## Configuration

Font generation settings are defined in [`config.toml`](config.toml). Request parameters (from the API/UI) override config file values.

### Key Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `[font].upm` | Units-per-em for SVG normalization | 1000 |
| `[font].advance_width` | Monospace advance width per glyph (lower = tighter spacing) | Varies |
| `[font].fontname` | Internal font name (no spaces) | `DefaultFont` |
| `[font].fullname` | Full display name for the font | `Default Font` |
| `[font].familyname` | Font family name | `Default` |

### Performance Tuning (environment variables)

Tracing precision is the dominant cost driver in the whole pipeline: every colour
region VTracer emits becomes a separate COLR layer, and therefore a separate glyph
in the final font. 162 source PNGs at `color_precision=8` produce a **39,404-glyph**
font; the two single-threaded nanoemoji steps that compile it account for ~84% of
job wall time.

| Variable | Description | Default |
|----------|-------------|---------|
| `VT_COLOR_PRECISION` | VTracer significant bits per RGB channel. Lower = fewer colour layers = fewer glyphs = faster and smaller. | `8` |
| `VT_FILTER_SPECKLE` | VTracer minimum region size. No measurable effect on this artwork (the 2x nearest-neighbour upscale leaves no sub-threshold specks). | `2` |
| `PORT` | HTTP listen port | `8000` |

Measured on 162 chenille glyphs, 8-core host, submit -> ZIP:

| `VT_COLOR_PRECISION` | Job time | paths/glyph | numGlyphs | TTF | WOFF2 | Visual cost |
|---|---|---|---|---|---|---|
| 8 (default) | 834s | 241 | 39,404 | 13.29 MB | 1.40 MB | — |
| 6 | 494s | 190 | 31,216 | 10.50 MB | 1.08 MB | none measurable |
| 5 | 448s | 160 | 26,188 | 9.15 MB | 0.96 MB | negligible |
| 4 | 320s | 67 | 11,118 | 5.83 MB | 0.63 MB | loses fine stipple texture |
| 3 | — | — | — | — | — | **unusable** — glyphs collapse |

`6` is free: fidelity (RMSE against the source bitmap) is unchanged from `8`. `4` is
2.6x faster and 2.3x smaller and is indistinguishable at <=96px, but flattens fine
interior texture at display sizes — check it against your artwork before adopting.

## Deployment (Google Cloud Run)

```bash
gcloud run deploy png2font-api \
  --source . \
  --region us-central1 \
  --cpu=4 --memory=8Gi \
  --no-cpu-throttling \
  --timeout=3600 \
  --concurrency=80 \
  --max-instances=1 \
  --min-instances=0 \
  --set-env-vars VT_COLOR_PRECISION=6
```

Why each flag matters:

- **`--no-cpu-throttling`** (instance-based billing) is **required**, not an
  optimisation. `runGenerationJob()` is fire-and-forget: the handler returns `202`
  immediately and the pipeline continues in the background. Under the default
  request-based billing, Cloud Run throttles CPU the moment the response is sent, so
  the job would crawl between status polls.
- **`--cpu=4`** — the bottleneck is single-threaded (`write_combined_part_files` and
  `write_font`), which is 81-84% of nanoemoji's wall time in every configuration.
  Only the ~334 parallel ninja edges scale with cores, so doubling 4 -> 8 vCPU buys
  roughly 13-15% on total job time for 2x the compute cost.
- **`--timeout=3600`** covers the polling requests; the background job itself is not
  bound by it.
- **`--max-instances=1`** is currently **mandatory**. Job state lives on instance-local
  disk (`JOBS_ROOT` in `src/constants.ts`), so a status poll routed to a second
  instance returns 404. This also serialises jobs — see below.
- **`--min-instances=0`** — scale to zero. A 10-30 minute job amortises any cold
  start, and idling one 4 vCPU instance costs ~$231/month.

### Known limitation: one job at a time

`max-instances=1` means concurrent submissions queue behind each other. Fixing this
requires moving job state off local disk — status to Firestore, artifacts to GCS —
after which `--max-instances` can be raised. `src/jobStore.ts` is the seam
(`jobDir()`, `writeJobStatus()`, `readJobStatus()`, `sweepStaleJobs()`).

Note also that `/tmp` on Cloud Run is an in-memory filesystem, so job directories
count against the memory limit while a job runs.

### Cost estimate

Instance-based billing, Tier-1 region (e.g. `us-central1`), at
$0.000018/vCPU-second + $0.000002/GiB-second. The monthly free tier is
240,000 vCPU-seconds + 450,000 GiB-seconds, which at 4 vCPU / 8 GiB is about
**16.7 free instance-hours per month**.

At 4 vCPU / 8 GiB:

| Config | Per job | 100 jobs/mo | 500 jobs/mo | 1000 jobs/mo |
|---|---|---|---|---|
| Untuned (~30 min) | $0.158 | $10.62 | $73.98 | $153.18 |
| `VT_COLOR_PRECISION=6` (~13 min) | $0.069 | $1.64 | $29.10 | $63.42 |
| `VT_COLOR_PRECISION=4` (~9 min) | $0.048 | free | $18.54 | $42.30 |

Egress is negligible (a ~4 MB ZIP per job — roughly $0.50 per 1000 jobs). Container
image storage in Artifact Registry and Cloud Build minutes are billed separately and
are minor for this workload.

> Rates change; confirm against the [Cloud Run pricing page](https://cloud.google.com/run/pricing)
> before budgeting. Job durations above are extrapolated from an 8-core workstation,
> which has faster single-thread performance than a Cloud Run vCPU — since the
> bottleneck is single-threaded, real times will skew longer.

## Project Structure

```
src/
├── server.ts               # Express app, CORS, routes, listen()
├── pipeline.ts              # runGenerationJob(): phase-machine orchestrator + heartbeat
├── jobStore.ts               # Disk-backed job status (atomic writes, TTL sweep, orphan detection)
├── config.ts                  # Pure config utilities ported from python/config.py
├── types.ts                    # JobStatus, FontConfig, GenerateFontParams, RunProcessResult
├── constants.ts                 # JOBS_ROOT, JOB_TTL_SECONDS, CORS_ORIGINS, PORT, etc.
├── routes/
│   ├── generateFont.ts           # POST /api/generate-font
│   ├── jobStatus.ts               # GET /api/job/:id
│   ├── jobResult.ts                # GET /api/job/:id/result
│   └── staticIndex.ts                # GET / and /static mount
└── subprocess/
    ├── runProcess.ts                  # Shared spawn + capture-output helper
    ├── toolPaths.ts                    # Binary path resolution (env-var -> which -> fallback)
    ├── fontforge.ts                     # fontforge -script python/font.py ...
    ├── addsvg.ts                         # addsvg <svgFolder> <ttfPath>
    ├── maximumColor.ts                    # nanoemoji maximum_color (streamed progress)
    ├── ttf2woff2.ts                         # TTF -> WOFF2 pipe
    ├── png2svgCli.ts                         # python/png2svg.py {trace,shift,flatten}
    └── fontTablesCli.ts                       # python/font_tables.py drop-tables

# Python scripts invoked as subprocesses from TypeScript:
python/png2svg.py       # Argparse subcommands: trace, shift, flatten
python/font_tables.py    # Argparse subcommand: drop-tables
python/font.py            # FontForge script (unchanged, invoked by fontforge.ts)
python/config.py            # Shared config utilities (imported by the Python scripts)
```

See [CLAUDE.md](CLAUDE.md) for the full architecture, key design decisions, and troubleshooting reference.

## Generation Pipeline

The complete font generation process, orchestrated by `pipeline.ts`'s `runGenerationJob()`:

### Step 1: PNG to SVG Tracing
```
python3 python/png2svg.py trace
```
Uses VTracer to trace each PNG into a color SVG with:
- Baseline at y=0
- Ink positioned at negative y (above baseline)

### Step 2: Baseline Adjustment for Font Metrics
```
python3 python/png2svg.py shift
```
Shifts every SVG down by the font's descent value. This allows metric adjustments without re-tracing (faster pipeline).

### Step 3: Flatten to Monochrome Outlines
```
python3 python/png2svg.py flatten
```
Unions each color glyph into a single monochrome silhouette for FontForge. FontForge cannot efficiently handle hundreds of overlapping paths, so flattening (parallelized per glyph) is required. This step is computationally intensive.

### Step 4: Generate Base Font
```
fontforge -script python/font.py
```
FontForge imports the flattened silhouettes and produces the base TTF:
- Scales and positions each glyph
- Sets advance widths
- Writes `<fontname>.ttf`

### Step 5: Embed SVG Outlines
```
addsvg [ttf] [svg_folder]
```
Embeds the color SVGs (still at original aspect ratio, not flattened) into the TTF as an `'SVG '` table. Non-fatal if it fails.

### Step 6: Generate COLR Table
```
nanoemoji maximum_color --colr_version=0 --reuse_tolerance=-1 [ttf]
```
Generates a `COLR`/`CPAL` (v0) table from the `'SVG '` table that was embedded in step 5. COLR v0 is broadly supported (including Safari 12.1+), so no bitmap (`sbix`) fallback table is needed. Falls back to the non-color TTF if it fails.

`--reuse_tolerance=-1` disables nanoemoji's cross-glyph shape reuse search. Traced
artwork never produces affine-identical paths across glyphs, so the search finds
nothing while costing ~160s per job; disabling it yields a structurally identical
font (verified: same glyph count, same COLR layer count).

**This is the slowest step in the pipeline** — see
[Performance Tuning](#performance-tuning-environment-variables).

### Step 7: Remove Unused Tables
```
python3 python/font_tables.py drop-tables
```
For web distribution, removes:
- `'SVG '` table when `COLR` is present (Chrome/Firefox use `COLR`; Chrome never supported `SVG`)
- Any stray `sbix` table (never intentionally produced, dropped defensively)
- FontForge's `FFTM` metadata table (always)

### Step 8: Package & Export
- Convert TTF → WOFF2 (web format) via `ttf2woff2`
- Zip both `.ttf` and `.woff2` files for download

## Color Support & Browser Compatibility

### Color Table Support Matrix

| Table | Chrome | Firefox | Safari | Best Used For |
|-------|--------|---------|--------|---------------|
| **COLR v0** | 32+ | 26+ | 12.1+ | Web fonts (`.woff2`) & installed fonts |
| **SVG** | ✗ | 31+ | 12.1+ | Installed fonts (macOS 13+) |

### Web Flavor (`.woff2`)

Includes: `COLR` (v0) + `CPAL` only.

- **Chrome/Firefox/Safari**: All read `COLR` v0 directly — no fallback table needed.
- The `'SVG '` table is dropped for web delivery since `COLR` already covers every browser that would otherwise use it.

### Installed Flavor (`.ttf`)

Includes: `COLR` (v0) + `CPAL` + `'SVG '`.

- **macOS 13+** (CoreText): Prefers `'SVG '`.
- **Other systems**: Fall back to `COLR`.

### Implementation Notes

- **Bitmap positioning** no longer applies — the pipeline doesn't produce an `sbix` bitmap table, only vector `COLR`/`SVG` tables.

## Examples

### Before & After

**Source PNGs** → **Generated Font in macOS**

<p align="center">
  <img src="assets/png.png" alt="Source PNG glyphs" width="900" />
</p>

<p align="center">
  <img src="assets/pages.png" alt="Generated font used in macOS Pages" width="900" />
</p>

## Troubleshooting

### "Connection refused" / server won't start
**Problem**: `npm start` fails or the browser can't reach `http://127.0.0.1:8000`

**Solution**: Confirm the build succeeded (`npm run build`) and check server logs for errors on startup.

### Port already in use
**Problem**: `EADDRINUSE` error on port 8000

**Solution**: Use a different port:
```bash
PORT=8001 npm start
```

### TypeScript compilation errors
**Problem**: Errors during `npm run build`

**Solution**: Check `tsconfig.json` (`.js` extensions are required on all relative imports — ES module requirement) and ensure all dependencies are installed:
```bash
npm install
npm run build
```

### `job not found (404)`
**Problem**: Polling `/api/job/:id` returns 404

**Solution**: The job directory may have been deleted by the TTL sweep (2-hour expiry), or the job ID is malformed (must be 32 lowercase hex chars).

### FontForge Import Errors
**Problem:** `fontforge` Python imports crash or segfault when run inside the interpreter.

**Solution:** Use the supported CLI invocation instead (this is exactly what `fontforge.ts` does under the hood):
```bash
fontforge -script python/font.py
```

### Missing Python Packages
**Problem:** `ModuleNotFoundError` for packages like `vtracer`, `tomli`, etc.

**Solution:** Install the package into the same environment used by `setup_env.sh`:
```bash
pip install vtracer tomli pillow fontTools
```

### svgcleaner Not Found
**Problem:** Pipeline fails with "svgcleaner: command not found"

**Solution:**
1. Download from https://github.com/RazrFalcon/svgcleaner/releases
2. Place in project root directory
3. Make executable: `chmod +x svgcleaner`

### nanoemoji fails
**Problem:** Color-optimize phase fails or falls back to a non-color TTF

**Solution:** Check `nanoemoji` is installed in the conda env:
```bash
pip list | grep nanoemoji
```

## Additional Resources

- [CLAUDE.md](CLAUDE.md) — Full architecture, key design decisions, and development guide
- [config.toml](config.toml) — Font generation defaults
- [package.json](package.json) — Dependencies and scripts

## Credits

- **[svgcleaner](https://github.com/RazrFalcon/svgcleaner)** — RazrFalcon (SVG cleaning and normalization)
- **[FontForge](https://fontforge.org/)** — FontForge project (font editing and scripting)
- **[addsvg / OpenType-SVG](https://github.com/adobe-type-tools/opentype-svg)** — Adobe type tools (SVG embedding into fonts)
- **[nanoemoji](https://github.com/googlei18n/nanoemoji)** — Google Fonts (color table generation)
