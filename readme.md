# png2font

## Overview

**png2font** converts bitmap glyph PNGs into monospace TTF (TrueType Font) files with color support. It traces PNG images to SVG, normalizes them, flattens them for outline generation, and embeds both SVG and color table data (COLR, sbix, SVG) into the final font for maximum browser and OS compatibility.

## Quick Start

### Prerequisites

**FontForge** is required before any other setup. Install it using the [official instructions](https://github.com/fontforge/fontforge/blob/master/INSTALL.md), then proceed with the rest of the setup.

### Setup & First Run

```bash
# Initialize the environment (recommended with conda)
./setup_env.sh

# Generate a font from PNGs
./run.sh [PNG_FOLDER] [FONTNAME]

# Examples:
./run.sh                # Use glyphs folder and font name from config.toml
./run.sh my_pngs MyType # Use folder my_pngs, produce MyType.ttf
```

## Web UI & API

### Starting the Web Application

```bash
./run.sh                    # Uses config.toml for parameters
# or
uvicorn app:app --reload   # For development with hot-reload
```

### Accessing the Interface

- **Browser UI**: http://127.0.0.1:8000/
  - Drag-and-drop PNG uploads
  - Live parameter controls
  - Font preview and download

- **Interactive API Docs**: http://127.0.0.1:8000/docs
  - Swagger/OpenAPI documentation
  - Try API endpoints directly from your browser

## Dependencies & Tools

### External Binaries

These tools must be installed separately:

| Tool | Purpose | Installation |
|------|---------|--------------|
| **FontForge** | Font generation and scripting | [Official guide](https://github.com/fontforge/fontforge/blob/master/INSTALL.md) |
| **svgcleaner** | SVG normalization and optimization | [Download](https://github.com/RazrFalcon/svgcleaner/releases), place in project root, run `chmod +x svgcleaner` |
| **addsvg** | Embed SVG tables into TTF | Included in [opentype-svg](https://github.com/adobe-type-tools/opentype-svg) tools |

## Configuration

Font generation settings are defined in [`config.toml`](config.toml). CLI arguments override config file values.

### Key Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `[font].upm` | Units-per-em for SVG normalization | 1000 |
| `[font].advance_width` | Monospace advance width per glyph (lower = tighter spacing) | Varies |
| `[font].fontname` | Internal font name (no spaces) | `DefaultFont` |
| `[font].fullname` | Full display name for the font | `Default Font` |
| `[font].familyname` | Font family name | `Default` |

**Note:** Command-line arguments take precedence over `config.toml` settings.

## Scripts & Usage

### Main Entry Point

**`run.sh`** — Orchestrates the entire pipeline from PNG images to TTF font.

```bash
./run.sh [PNG_FOLDER] [FONTNAME]
```

| Parameter | Behavior |
|-----------|----------|
| *(none)* | Use folder `glyphs` and font name from `config.toml` |
| `PNG_FOLDER FONTNAME` | Use custom folder and font name |

**Examples:**
```bash
./run.sh                   # Use defaults from config.toml
./run.sh ./my_pngs MyType  # Custom folder and font name
```

### Component Scripts

#### `app.py` — Web API Server
FastAPI application that provides HTTP endpoints for font generation.

**Modules:**
- `pipeline.py` — Per-job font generation pipeline (PNG → SVG → TTF → WOFF2 → ZIP)
- `job_store.py` — Persistent job state management (stores status, TTL expiry, detects orphans)
- `font_tables.py` — TTF post-processing (sbix table grafting, unused table removal)

#### `png2svg.py` — PNG to SVG Tracing
Converts PNG images to normalized SVG outlines using VTracer.

```bash
python3 png2svg.py

# With custom folders:
python3 png2svg.py --png_folder ./my_pngs --svg_output ./my_svgs
```

**Default directories:**
- Input: `glyphs/`
- Output: `svg_glyphs/`

#### `font.py` — TTF Generation
FontForge script that builds the final TTF from SVG outlines.

```bash
# Use config.toml for naming:
fontforge -script font.py

# Override font names:
fontforge -script font.py svg_glyphs --fontname MyFont --fullname "My Font" --familyname "My Family"
```

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

- The `sbix` table is built custom by `font_tables.py` (nanoemoji's CLI doesn't expose this) from the same SVG assets nanoemoji uses for `COLR`
- **Bitmap positioning**: Each bitmap is centered on its outline glyph's bounding box (nanoemoji's default left-anchors at x=0, which only looks correct for glyphs that fill their entire advance width)

## Generation Pipeline

The complete font generation process (orchestrated by `pipeline.py`'s `run_generation_job`):

### Step 1: PNG to SVG Tracing
```
png2svg.convert_pngs_to_svgs()
```
Uses VTracer to trace each PNG into a color SVG with:
- Baseline at y=0
- Ink positioned at negative y (above baseline)

### Step 2: Baseline Adjustment for Font Metrics
```
png2svg.shift_svgs_for_descent()
```
Shifts every SVG down by the font's descent value. This allows metric adjustments without re-tracing (faster pipeline).

### Step 3: Flatten to Monochrome Outlines
```
png2svg.flatten_svgs_for_outlines()
```
Unions each color glyph into a single monochrome silhouette for FontForge. FontForge cannot efficiently handle hundreds of overlapping paths, so flattening (parallelized per glyph) is required. This step is computationally intensive.

### Step 4: Generate Base Font
```
fontforge -script font.py
```
FontForge imports the flattened silhouettes and produces the base TTF:
- Scales and positions each glyph
- Sets advance widths
- Writes `<fontname>.ttf`

### Step 5: Embed SVG Outlines
```
addsvg [ttf] [svg_folder]
```
Embeds the color SVGs (still at original aspect ratio, not flattened) into the TTF as an `'SVG '` table.

### Step 6: Generate COLR Table
```
nanoemoji maximum_color [ttf]
```
Generates a `COLR` (v1) table from the `'SVG '` table that was embedded in step 5.

### Step 7: Add sbix Table
```
font_tables.add_sbix_table()
```
Custom script that grafts an `sbix` table (built from nanoemoji's extracted picosvg assets). Nanoemoji's own tools can't add sbix, so a donor font is built and merged in using fontTools.

### Step 8: Remove Unused Tables (Web Flavor Only)
```
font_tables.subset_drop_unused_tables()
```
For web distribution, removes:
- `'SVG '` table (Firefox uses `COLR`, Chrome never supported `SVG`)
- FontForge's `FFTM` metadata table (always)

### Step 9: Package & Export
- Convert TTF → WOFF2 (web format)
- Zip both `.ttf` and `.woff2` files for download

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

### FontForge Import Errors
**Problem:** `fontforge` Python imports crash or segfault when run inside the interpreter.

**Solution:** Use the supported CLI invocation instead:
```bash
fontforge -script font.py
```

### Missing Python Packages
**Problem:** `ModuleNotFoundError` for packages like `vtracer`, `tomli`, etc.

**Solution:** Install the package into the same environment:
```bash
pip install vtracer tomli pillow fontTools
```

### svgcleaner Not Found
**Problem:** Pipeline fails with "svgcleaner: command not found"

**Solution:**
1. Download from https://github.com/RazrFalcon/svgcleaner/releases
2. Place in project root directory
3. Make executable: `chmod +x svgcleaner`

## Credits

- **[svgcleaner](https://github.com/RazrFalcon/svgcleaner)** — RazrFalcon (SVG cleaning and normalization)
- **[FontForge](https://fontforge.org/)** — FontForge project (font editing and scripting)
- **[addsvg / OpenType-SVG](https://github.com/adobe-type-tools/opentype-svg)** — Adobe type tools (SVG embedding into fonts)
- **[nanoemoji](https://github.com/googlei18n/nanoemoji)** — Google Fonts (color table generation)
