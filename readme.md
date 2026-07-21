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
  - `font_tables.py` — TTF post-processing (sbix grafting, table trimming).
- `png2svg.py` — trace PNGs to normalized SVGs.
  - Default: `python3 png2svg.py`
  - Options: `--png_folder <dir>` and `--svg_output <dir>` (defaults: `glyphs`, `svg_glyphs`).
- `font.py` — FontForge script that imports SVGs and generates `<fontname>.ttf`.
  - Default: `fontforge -script font.py` (reads naming from `config.toml`).
  - Override font names: `fontforge -script font.py svg_glyphs --fontname MyFont --fullname "My Font" --familyname "My Family"`.
- `run.sh` — end-to-end pipeline wrapper. Usage:

```bash
./run.sh [PNG_FOLDER] [FONTNAME]
# Examples
./run.sh                # use `glyphs` and fontname from config.toml
./run.sh my_pngs MyType # use folder `my_pngs` and produce `MyType.ttf`
```

**Color tables & browser support**

No single OpenType color table is understood by Chrome, Firefox, *and* Safari, so the pipeline ships two and lets each browser pick the one it understands:

| Table    | Chrome | Firefox | Safari | Used for |
| -------- | ------ | ------- | ------ | -------- |
| `COLR` (v1) | 98+ | 107+ | ✗ | Web (`.woff2`) |
| `sbix`   | 66+ | ✗ | 9.1+ | Web (`.woff2`); also the older-macOS fallback in the installed `.ttf` |
| `SVG `   | ✗ | 31+ | 12.1+ | Installed `.ttf` only (CoreText, macOS 13+) |

- The **web flavor** (`.woff2`) ships `COLR` + `sbix`: together they cover Chrome, Firefox, and Safari with only Chrome carrying a few redundant (and ignored — Chrome prefers `COLR`) `sbix` bytes. `SVG ` is dropped — Firefox already has `COLR`, and Chrome never implemented `SVG ` at all, so keeping it would be pure dead weight.
- The **installed flavor** (`.ttf`) keeps every table nanoemoji/`add_sbix_table` produce (`COLR`, `SVG `, `sbix`): CoreText prefers `SVG ` on macOS 13+ and falls back to `sbix` on older macOS.
- `sbix` isn't something nanoemoji's own `maximum_color` CLI exposes (its bitmap flag only builds `CBDT`, which none of the three target browsers need once `sbix` covers Safari) — `add_sbix_table` in `font_tables.py` builds it directly from the same picosvg assets nanoemoji already extracts for `COLR`, positioning each bitmap centered on its outline glyph's own bounding box (nanoemoji's own horizontal placement always left-anchors at x=0, which only looks right for a glyph that fills its whole advance box).

**Pipeline (what each step does)**

Run by `pipeline.py`'s `run_generation_job`, per job:

1. `png2svg.convert_pngs_to_svgs` — traces each PNG with VTracer into a color SVG (baseline at y=0, ink at negative y).
2. `png2svg.shift_svgs_for_descent` — shifts every traced SVG down by the font's descent, reserving descender room without needing a re-trace on metric changes.
3. `png2svg.flatten_svgs_for_outlines` — unions each glyph's color regions into a single monochrome silhouette (parallelized across glyphs — the union itself is the slow part per glyph) for FontForge, which can't handle hundreds of overlapping paths efficiently.
4. `font.py` (via `fontforge -script`) imports the flattened silhouettes, scales/positions each glyph, sets advance widths, and writes the base `<fontname>.ttf`.
5. `addsvg` embeds the (still color, natural-aspect-ratio) shifted SVGs into that TTF as an `'SVG '` table.
6. `nanoemoji`'s `maximum_color` builds a `COLR` (v1) table from that same `'SVG '` table.
7. `font_tables.add_sbix_table` grafts an `sbix` table, built from the picosvg assets nanoemoji already extracted for step 6 — nanoemoji's own merge tooling can't add `sbix`, so a donor font is built and merged in with `fontTools`.
8. `font_tables.subset_drop_unused_tables` drops `'SVG '` from the web flavor (see table above) and FontForge's `FFTM` metadata table always.
9. The color TTF is converted to `.woff2`, then both files are zipped for download.

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
