# png2font

## Overview

**png2font** converts bitmap glyph PNGs into monospace TTF (TrueType Font) files with color support. It traces PNG images to SVG, normalizes them, flattens them for outline generation, and embeds both SVG and color table data (COLR, sbix, SVG) into the final font for maximum browser and OS compatibility.

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
    └── fontTablesCli.ts                       # python/font_tables.py {add-sbix,drop-tables}

# Python scripts invoked as subprocesses from TypeScript:
python/png2svg.py       # Argparse subcommands: trace, shift, flatten
python/font_tables.py    # Argparse subcommands: add-sbix, drop-tables
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
nanoemoji maximum_color [ttf]
```
Generates a `COLR` (v1) table from the `'SVG '` table that was embedded in step 5. Falls back to the non-color TTF if it fails.

### Step 7: Add sbix Table
```
python3 python/font_tables.py add-sbix
```
Custom script that grafts an `sbix` table (built from nanoemoji's extracted picosvg assets). Nanoemoji's own tools can't add sbix, so a donor font is built and merged in using fontTools. Non-fatal.

### Step 8: Remove Unused Tables
```
python3 python/font_tables.py drop-tables
```
For web distribution, removes:
- `'SVG '` table (Firefox uses `COLR`, Chrome never supported `SVG`)
- FontForge's `FFTM` metadata table (always)

### Step 9: Package & Export
- Convert TTF → WOFF2 (web format) via `ttf2woff2`
- Zip both `.ttf` and `.woff2` files for download

## Color Support & Browser Compatibility

### The Multi-Table Strategy

Since no single OpenType color table is universally supported across all browsers, the pipeline generates multiple color tables and includes them in both web and installed fonts. Each browser uses the one it understands best.

### Color Table Support Matrix

| Table | Chrome | Firefox | Safari | Best Used For |
|-------|--------|---------|--------|---------------|
| **COLR v1** | 98+ | 107+ | ✗ | Web fonts (`.woff2`) |
| **sbix** | 66+ | ✗ | 9.1+ | Web & installed fallback |
| **SVG** | ✗ | 31+ | 12.1+ | Installed fonts (macOS 13+) |

### Web Flavor (`.woff2`)

Includes: `COLR` + `sbix`

This combination provides universal coverage:
- **Chrome 98+**: Uses `COLR` (preferred modern format)
- **Firefox 107+**: Uses `COLR`
- **Safari 9.1+**: Uses `sbix` as fallback
- The `SVG ` table is intentionally omitted to reduce file size (Firefox already has `COLR`, and Chrome never supported `SVG `)

### Installed Flavor (`.ttf`)

Includes: `COLR` + `SVG ` + `sbix`

This preserves maximum compatibility with system font renderers:
- **macOS 13+** (CoreText): Prefers `SVG `, falls back to `sbix` on older versions
- **Other systems**: Fall back through `COLR` → `sbix`

### Implementation Notes

- The `sbix` table is built custom by `python/font_tables.py` (nanoemoji's CLI doesn't expose this) from the same SVG assets nanoemoji uses for `COLR`
- **Bitmap positioning**: Each bitmap is centered on its outline glyph's bounding box (nanoemoji's default left-anchors at x=0, which only looks correct for glyphs that fill their entire advance width)

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
