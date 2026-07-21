"""Post-processing of the built TTF: bitmap metrics, sbix grafting, table trimming."""

import io, logging, shutil, subprocess, sys
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image

from config import svg_filename_to_codepoint

logger = logging.getLogger("png2font-api")


# sbix strike height in pixels. CoreText upscales sbix to the text size, so
# the strike must stay sharp at display sizes.
SBIX_STRIKE_RESOLUTION = 512


def write_sbix_glyphmap(build_dir: Path, source_glyphmap: Path, sbix_glyphmap: Path) -> int | None:
    """Write SBIX.glyphmap, rendering each glyph's picosvg at
    SBIX_STRIKE_RESOLUTION via resvg.

    source_glyphmap is nanoemoji's own COLR glyphmap (COLR_1.glyphmap) —
    its rows already list every color glyph's picosvg path; we don't need
    a separate CBDT/bitmap build just to learn that mapping. Falls back to
    leaving rows without a bitmap column if resvg is missing or a render
    fails (nanoemoji.write_font then renders nothing for that glyph — this
    only ever means a best-effort sbix, never a hard failure). Returns the
    rendered strike height, or None if resvg isn't available at all.
    """
    # resvg comes from the resvg-cli pip package, installed alongside the
    # interpreter — fall back there when the env isn't on PATH.
    resvg_bin = shutil.which("resvg") or str(Path(sys.executable).parent / "resvg")
    if not Path(resvg_bin).exists():
        logger.warning("sbix: resvg not found, skipping strike rendering")
        shutil.copy(source_glyphmap, sbix_glyphmap)
        return None

    bitmap_dir = build_dir / "sbix_bitmap"
    bitmap_dir.mkdir(exist_ok=True)
    rows = []
    for line in source_glyphmap.read_text().splitlines():
        if not line.strip():
            continue
        columns = line.split(",")
        svg_rel = columns[0]
        if not svg_rel:
            # Bitmap-less row (e.g. the blank space glyph) — keep as-is.
            rows.append(line)
            continue
        out_png = bitmap_dir / f"{Path(svg_rel).stem}.png"
        render = subprocess.run(
            [resvg_bin, "-h", str(SBIX_STRIKE_RESOLUTION), str(build_dir / svg_rel), str(out_png)],
            capture_output=True, text=True, check=False,
        )
        if render.returncode != 0 or not out_png.exists():
            logger.warning(
                "sbix: resvg failed on %s (%s), leaving glyph without a strike",
                svg_rel, (render.stderr or "").strip(),
            )
            rows.append(line)
            continue
        columns[1] = f"sbix_bitmap/{out_png.name}"
        rows.append(",".join(columns))
    sbix_glyphmap.write_text("\n".join(rows) + "\n")
    return SBIX_STRIKE_RESOLUTION


def add_sbix_table(font_path: str, build_dir: Path, source_ttf_path: str) -> None:
    """Graft an sbix color table onto font_path, built from the same
    picosvg assets maximum_color already extracted to generate COLR.

    Pre-13 macOS CoreText (Font Book, Preview, ...) draws color glyphs only
    from sbix, which nanoemoji deliberately never generates — without this
    the font renders as plain black outlines there. nanoemoji's merge tool
    can't graft sbix either, so a donor font is built and merged here with
    fontTools, matching glyphs by codepoint (the donor keeps u-XXXX names;
    font_path's names were stripped by nanoemoji).

    Best-effort: any failure just leaves the font without sbix.
    """
    # COLR_1.glyphmap: nanoemoji's own glyphmap from building glyf_colr_1
    # (see maximum_color.py's WriteFontInputs.for_tag) — reused here rather
    # than running a separate --bitmaps/CBDT build just to get the same
    # svg-path-per-glyph mapping.
    colr_glyphmap = build_dir / "COLR_1.glyphmap"
    parts_file = build_dir / "parts-merged.json"
    if not colr_glyphmap.exists() or not parts_file.exists():
        logger.warning("sbix: missing %s or %s, skipping", colr_glyphmap, parts_file)
        return

    sbix_toml = build_dir / "SBIX.toml"
    sbix_glyphmap = build_dir / "SBIX.glyphmap"
    sbix_donor_path = build_dir / "MergeSource.sbix.ttf"

    try:
        strike_res = write_sbix_glyphmap(build_dir, colr_glyphmap, sbix_glyphmap)

        config_cmd = [
            "python3", "-m", "nanoemoji.write_config_for_mergeable",
            "--color_format", "sbix", str(source_ttf_path), str(sbix_toml),
        ]
        config_res = subprocess.run(config_cmd, capture_output=True, text=True, check=False)
        if config_res.returncode != 0:
            logger.warning("sbix: write_config_for_mergeable failed: %s", config_res.stderr)
            return

        write_font_cmd = [
            "python3", "-m", "nanoemoji.write_font",
            "--config_file", "SBIX.toml",
            "--glyphmap_file", "SBIX.glyphmap",
            "--part_file", "parts-merged.json",
            "--output_file", "MergeSource.sbix.ttf",
        ]
        if strike_res is not None:
            write_font_cmd += ["--bitmap_resolution", str(strike_res)]
        write_res = subprocess.run(
            write_font_cmd, capture_output=True, text=True, check=False, cwd=str(build_dir)
        )
        if write_res.returncode != 0 or not sbix_donor_path.exists():
            logger.warning("sbix: write_font failed: %s", write_res.stderr)
            return

        target = TTFont(font_path)
        donor = TTFont(str(sbix_donor_path))
        cmap = target.getBestCmap()
        donor_sbix = donor["sbix"]
        target_glyf = target["glyf"]
        upm = target["head"].unitsPerEm

        for strike in donor_sbix.strikes.values():
            remapped = {}
            for glyph_name, glyph in strike.glyphs.items():
                if glyph_name in (".notdef", ".space"):
                    continue
                try:
                    codepoint = svg_filename_to_codepoint(glyph_name + ".svg")
                except ValueError:
                    continue
                target_name = cmap.get(codepoint)
                if target_name is None:
                    continue
                glyph.glyphName = target_name
                # originOffsetY is left as nanoemoji sets it (always
                # -descent, correct as-is). originOffsetX is always 0 —
                # fine only for a glyph that fills its whole advance box —
                # so re-center the bitmap on the outline's own bbox
                # center, matching glyphs narrower than their advance
                # (e.g. monospace "1").
                outline = target_glyf[target_name]
                if outline.numberOfContours != 0 and glyph.imageData:
                    image = Image.open(io.BytesIO(glyph.imageData))
                    bitmap_w_funits = image.width * upm / strike.ppem
                    outline_w_funits = outline.xMax - outline.xMin
                    offset_funits = (outline_w_funits - bitmap_w_funits) / 2
                    glyph.originOffsetX = round(offset_funits * strike.ppem / upm)
                remapped[target_name] = glyph
            strike.glyphs.clear()
            strike.glyphs.update(remapped)

        target["sbix"] = donor_sbix
        target.save(font_path)
        logger.info("Successfully added sbix color table for macOS compatibility.")
    except Exception as exc:
        logger.warning(f"Failed to add sbix table for {font_path}: {exc}")


def subset_drop_unused_tables(font_path: str, flavor: str) -> None:
    """Drop redundant tables in place, per delivery flavor.

    FFTM (FontForge metadata) always goes.

    The web flavors (woff/woff2) additionally drop:
    - 'SVG ' (only when COLR is present): per caniuse's actual @font-face
      support matrix, no single color table covers Chrome + Firefox +
      Safari — COLR (v1) covers Chrome 98+/Firefox 107+ but not Safari;
      'SVG ' covers Firefox 31+/Safari 12.1+ but not Chrome (never
      implemented); sbix covers Chrome 66+/Safari 9.1+ but not Firefox.
      COLR + sbix covers all three with only Chrome getting redundant
      bytes (small — Chrome prefers COLR and ignores sbix), whereas
      COLR + 'SVG ' would leave Firefox parsing a table it doesn't
      actually need, since it already has COLR.

    The TTF keeps everything: it's installed rather than web-served, and
    CoreText renders it from 'SVG ' (macOS 13+, preferred over sbix —
    verified) or sbix (older macOS).
    """
    tables = ("FFTM",)
    try:
        font = TTFont(font_path)
        for table in tables:
            if table in font:
                del font[table]
        if flavor != "ttf" and "COLR" in font and "SVG " in font:
            del font["SVG "]
        font.save(font_path)
    except Exception as exc:
        logger.warning(f"Failed to drop unused tables for {font_path}: {exc}")
