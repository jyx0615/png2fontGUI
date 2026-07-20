# png2font

**Purpose**

- Convert bitmap glyph PNGs into normalized SVG glyphs and assemble them into a monospace TTF. Optionally embed SVG outlines into the TTF for color/SVG-capable fonts.

**Quick setup (recommended with conda)**

Before running anything else, install FontForge first. The project depends on the `fontforge` CLI, and the official install instructions are here: https://github.com/fontforge/fontforge/blob/master/INSTALL.md

```bash
./setup_env.sh

./run.sh [PNG_FOLDER] [FONTNAME]
# Examples
./run.sh                # use `glyphs` and fontname from config.toml
./run.sh my_pngs MyType # use folder `my_pngs` and produce `MyType.ttf`
```

**Web UI**

- Start the FastAPI app with `./run.sh` or `uvicorn app:app --reload`.
- Open `http://127.0.0.1:8000/` for the browser UI.
- Open `http://127.0.0.1:8000/docs` for the interactive API docs.
- The web UI serves the same font-generation pipeline as the CLI, but with drag-and-drop uploads and live parameter controls.

Notes:

- `svgcleaner` is a native binary; download it from https://github.com/RazrFalcon/svgcleaner/releases and place it in the project root, then run `chmod +x svgcleaner`.
- `fontforge` is required for generating TTFs; install via conda or your package manager and use the CLI (`fontforge -script ...`).
- `addsvg` (from opentype-svg tools) is used to embed SVG outlines into the generated TTF.

**Configuration**

- Defaults live in [config.toml](config.toml). Key settings:
  - `[font].upm` — units-per-em used when normalizing SVGs (default 1000).
  - `[font].advance_width` — monospace advance width assigned to each glyph. Lower values make characters sit closer together; try 600 for a tighter font.
  - `[font].fontname`, `[font].fullname`, `[font].familyname` — default font naming.

CLI arguments override values in `config.toml`. Precedence: CLI > `config.toml`.

**Scripts & usage**

- `app.py` — FastAPI routes (submit job, poll status, download result); the actual work lives in:
  - `pipeline.py` — the per-job generation pipeline (trace → FontForge → color tables → WOFF2 → ZIP).
  - `job_store.py` — disk-backed job status store (status.json per job, TTL sweep, orphan detection).
  - `font_tables.py` — TTF post-processing (bitmap advances, sbix grafting, table trimming).
- `png2svg.py` — trace PNGs to normalized SVGs.
  - Default: `python3 png2svg.py`
  - Options: `--png_folder <dir>` and `--svg_output <dir>` (defaults: `glyphs`, `svg_glyphs`).
- `font.py` — FontForge script that imports SVGs and generates `<fontname>.ttf`.
  - Default: `fontforge -script font.py` (reads naming from `config.toml`).
  - Override font names: `fontforge -script font.py svg_glyphs --fontname MyFont --fullname "My Font" --familyname "My Family"`.
- `rename.py` — map SVG filenames to AGL glyph names and copy into `renamed_svg_glyphs/`.
- `run.sh` — end-to-end pipeline wrapper. Usage:

```bash
./run.sh [PNG_FOLDER] [FONTNAME]
# Examples
./run.sh                # use `glyphs` and fontname from config.toml
./run.sh my_pngs MyType # use folder `my_pngs` and produce `MyType.ttf`
```

**Pipeline (what each step does)**

- `png2svg.py`: uses VTracer to convert PNG → temporary SVG, wraps artwork in a <g> transform so baseline is at y=0, sets viewBox to `0 -UPM UPM UPM` and writes a fixed `width`/`height` equal to `UPM` so all glyphs share the same canvas.
- `svgcleaner` is run to normalize and compact the SVGs into `svg_glyphs/`.
- `rename.py` or `clean.py` can be used to convert filenames to AGL names or canonical `uXXXX.svg` forms and place them into `renamed_svg_glyphs/` for packaging.
- `font.py` (via `fontforge -script`) imports SVGs, scales and vertically offsets each glyph to fit the em square, sets each glyph's `width` to `advance_width` from `config.toml` (making the font monospace), and writes `<fontname>.ttf`.
- `addsvg` embeds the SVG outlines back into the produced TTF to create a color-capable font.

**Visual proof**

The first image shows the source PNG glyph set, and the second image shows the generated font installed and used directly in macOS Pages.

<p align="center">
  <img src="assets/png.png" alt="Source PNG glyphs" width="900" />
</p>

<p align="center">
  <img src="assets/pages.png" alt="Generated font used in macOS Pages" width="900" />
</p>

**Troubleshooting**

- If `fontforge` Python imports crash or segfault when run inside the interpreter, run `fontforge -script font.py` instead (this is the supported invocation here).
- If a Python package (`vtracer`, `tomli`, etc.) is missing, install it into the same environment running the scripts.
- Ensure `svgcleaner` is executable and present in the project root.

**Next steps / optional improvements**

- I can add an `environment.yml` or `requirements.txt` that pins known-good package versions for reproducible environments.
- Add a small test harness that runs the pipeline in a dry-run and reports produced glyph counts and warnings.

If you want any of the optional items, tell me which and I will add them.

**Credits**

- [svgcleaner](https://github.com/RazrFalcon/svgcleaner) — RazrFalcon (SVG cleaning and normalization)
- [FontForge](https://fontforge.org/) — FontForge project (font editing and scripting)
- [addsvg / OpenType-SVG](https://github.com/adobe-type-tools/opentype-svg) — Adobe type tools (SVG embedding into fonts)
