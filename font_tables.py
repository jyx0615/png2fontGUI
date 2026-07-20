"""Post-processing of the built TTF: bitmap metrics, sbix grafting, table trimming."""

import logging
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from fontTools.ttLib import TTFont

from config import svg_filename_to_codepoint

logger = logging.getLogger("png2font-api")

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def normalize_color_svg_viewports(svg_folder: Path, ttf_path: str) -> None:
    """Force every color SVG's outer viewport (width/height and viewBox
    width) to exactly unitsPerEm, in place. Leaves the artwork's own
    coordinates untouched — only the declared canvas size changes.

    Per the OpenType 'SVG ' table spec ("Coordinate systems and glyph
    metrics"): the render viewport for every glyph is *always* the em
    square (unitsPerEm x unitsPerEm); any viewBox or width/height that
    differs from unitsPerEm "will have the effect of a scale
    transformation." Traced SVGs declare width/viewBox as each glyph's own
    natural (narrower) bounding width, never unitsPerEm — so a strictly
    spec-compliant renderer scales that up to fill the em square, blowing
    the glyph up. Safari's renderer is lenient and just uses the declared
    size directly, which is why this was invisible there.

    Two earlier attempts tried to fix Firefox's *advance/spacing* by
    rewriting width to match hmtx (with or without padding viewBox to
    match) — that was solving the wrong problem: per spec, advance always
    comes from hmtx regardless of what the SVG declares, and it was the
    viewport/em-square scale mismatch causing visual overlap all along.
    """
    font = TTFont(ttf_path)
    upm = font["head"].unitsPerEm

    for svg_path in sorted(Path(svg_folder).glob("*.svg")):
        tree = ET.parse(svg_path)
        root = tree.getroot()
        view_box = root.attrib.get("viewBox")
        if not view_box:
            continue
        x0, y0, w, h = map(float, view_box.split())
        if (
            w == upm
            and h == upm
            and root.attrib.get("width") == f"{upm:g}"
            and root.attrib.get("height") == f"{upm:g}"
        ):
            continue  # already matches, nothing to do

        root.set("viewBox", f"{x0:g} {y0:g} {upm:g} {upm:g}")
        root.set("width", f"{upm:g}")
        root.set("height", f"{upm:g}")
        tree.write(svg_path, encoding="utf-8", xml_declaration=False)


def fix_bitmap_advances(font_path: str) -> None:
    """Copy hmtx advances into the CBDT bitmap glyph metrics.

    nanoemoji sets each bitmap's advance to its image width (emoji-style),
    and Chrome lays out CBDT glyphs with those advances instead of hmtx —
    silently breaking word and letter spacing.
    """
    font = TTFont(font_path)
    if "CBDT" not in font or "CBLC" not in font:
        return
    upm = font["head"].unitsPerEm
    hmtx = font["hmtx"]
    cblc = font["CBLC"]
    for strike_index, strike in enumerate(font["CBDT"].strikeData):
        ppem = cblc.strikes[strike_index].bitmapSizeTable.ppemX
        for glyph_name, rec in strike.items():
            advance, lsb = hmtx[glyph_name]
            rec.decompile()
            # SmallGlyphMetrics fields are uint8/int8 — clamp to be safe.
            rec.metrics.Advance = min(255, max(0, round(advance * ppem / upm)))
            rec.metrics.BearingX = min(127, max(-128, round(lsb * ppem / upm)))
    font.save(font_path)


# sbix strike height in pixels. CoreText upscales sbix to the text size, so
# the strike must stay sharp at display sizes. CBDT can't match it: its uint8
# metrics cap a strike at 255px, so CBDT keeps nanoemoji's 128px default.
SBIX_STRIKE_RESOLUTION = 512


def write_sbix_glyphmap(build_dir: Path, cbdt_glyphmap: Path, sbix_glyphmap: Path) -> int | None:
    """Write SBIX.glyphmap, re-rendering the strike at SBIX_STRIKE_RESOLUTION.

    Re-renders the same picosvgs behind the 128px CBDT bitmaps with resvg,
    giving CoreText a strike that stays sharp at display sizes. Falls back to
    reusing the CBDT bitmaps if resvg is missing or a render fails. Returns
    the rendered strike height, or None when falling back.
    """
    # resvg comes from the resvg-cli pip package, installed alongside the
    # interpreter — fall back there when the env isn't on PATH.
    resvg_bin = shutil.which("resvg") or str(Path(sys.executable).parent / "resvg")
    if not Path(resvg_bin).exists():
        logger.warning("sbix: resvg not found, reusing CBDT strike bitmaps")
        shutil.copy(cbdt_glyphmap, sbix_glyphmap)
        return None

    bitmap_dir = build_dir / "sbix_bitmap"
    bitmap_dir.mkdir(exist_ok=True)
    rows = []
    for line in cbdt_glyphmap.read_text().splitlines():
        if not line.strip():
            continue
        columns = line.split(",")
        svg_rel, bitmap_rel = columns[0], columns[1]
        if not svg_rel or not bitmap_rel:
            # Bitmap-less row (e.g. the blank space glyph) — keep as-is.
            rows.append(line)
            continue
        out_png = bitmap_dir / Path(bitmap_rel).name
        render = subprocess.run(
            [resvg_bin, "-h", str(SBIX_STRIKE_RESOLUTION), str(build_dir / svg_rel), str(out_png)],
            capture_output=True, text=True, check=False,
        )
        if render.returncode != 0 or not out_png.exists():
            logger.warning(
                "sbix: resvg failed on %s (%s), reusing CBDT strike bitmaps",
                svg_rel, (render.stderr or "").strip(),
            )
            shutil.copy(cbdt_glyphmap, sbix_glyphmap)
            return None
        columns[1] = f"sbix_bitmap/{out_png.name}"
        rows.append(",".join(columns))
    sbix_glyphmap.write_text("\n".join(rows) + "\n")
    return SBIX_STRIKE_RESOLUTION


def add_sbix_table(font_path: str, build_dir: Path, source_ttf_path: str) -> None:
    """Graft an sbix color table onto font_path, built from the picosvg
    assets maximum_color already extracted for CBDT.

    Pre-13 macOS CoreText (Font Book, Preview, ...) draws color glyphs only
    from sbix, which nanoemoji deliberately never generates — without this
    the font renders as plain black outlines there. nanoemoji's merge tool
    can't graft sbix either, so a donor font is built and merged here with
    fontTools, matching glyphs by codepoint (the donor keeps u-XXXX names;
    font_path's names were stripped by nanoemoji).

    Best-effort: any failure just leaves the font without sbix.
    """
    cbdt_glyphmap = build_dir / "CBDT.glyphmap"
    parts_file = build_dir / "parts-merged.json"
    if not cbdt_glyphmap.exists() or not parts_file.exists():
        logger.warning("sbix: missing %s or %s, skipping", cbdt_glyphmap, parts_file)
        return

    sbix_toml = build_dir / "SBIX.toml"
    sbix_glyphmap = build_dir / "SBIX.glyphmap"
    sbix_donor_path = build_dir / "MergeSource.sbix.ttf"

    try:
        strike_res = write_sbix_glyphmap(build_dir, cbdt_glyphmap, sbix_glyphmap)

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
                # CoreText places sbix bitmaps relative to the glyf bbox
                # corner, not the glyph origin nanoemoji assumes (Apple's
                # docs vs. the OpenType spec) — glyphs with different yMin
                # land at different heights. Subtract the bbox corner (in
                # strike pixels) to compensate. Safe to bake in: CoreText is
                # the only renderer that reaches sbix.
                outline = target_glyf[target_name]
                if outline.numberOfContours != 0:
                    glyph.originOffsetX -= round(outline.xMin * strike.ppem / upm)
                    glyph.originOffsetY -= round(outline.yMin * strike.ppem / upm)
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
    - sbix, CBDT/CBLC (only when COLR is present): Chrome and Firefox both
      prefer COLR over the bitmaps, so those tables are dead weight there;
      Safari draws neither COLR nor CBDT/sbix from a web font, but does
      render 'SVG ' — kept (see align_color_svg_widths for why that no
      longer breaks Firefox's layout) so Safari still gets color.

    The TTF keeps everything: it's installed rather than web-served, and
    CoreText renders it from 'SVG ' (macOS 13+, preferred over sbix —
    verified) or sbix (older macOS); CBDT stays as a harmless fallback.
    """
    tables = ("FFTM",)
    try:
        font = TTFont(font_path)
        for table in tables:
            if table in font:
                del font[table]
        if flavor != "ttf" and "COLR" in font:
            for table in ("sbix", "CBDT", "CBLC"):
                if table in font:
                    del font[table]
        font.save(font_path)
    except Exception as exc:
        logger.warning(f"Failed to drop unused tables for {font_path}: {exc}")
