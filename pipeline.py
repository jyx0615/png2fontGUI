"""The font generation pipeline, run in a worker thread per job.

PNG glyphs → traced SVGs → FontForge TTF → color tables (addsvg + nanoemoji)
→ post-processing → WOFF2 → ZIP.
"""

import logging
import os
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from config import vertical_metrics
from font_tables import (
    add_sbix_table,
    normalize_color_svg_viewports,
    fix_bitmap_advances,
    subset_drop_unused_tables,
)
from job_store import HEARTBEAT_SECONDS, job_dir, write_job_status
from png2svg import convert_pngs_to_svgs, flatten_svgs_for_outlines, shift_svgs_for_descent

logger = logging.getLogger("png2font-api")


def run_generation_job(
    job_id: str,
    fontname: str,
    fullname: str,
    familyname: str,
    upm: int,
    advance_width: int,
    vertical_raise: int,
    monospace: bool,
    line_height: int | None,
    letter_spacing: int,
):
    """Worker-thread body: runs the full pipeline, updating status.json as it goes."""
    # Ascent/descent come from config.vertical_metrics; line_height is an
    # optional override — anything beyond ascent + descent becomes line gap.
    ascent, descent, default_line_height = vertical_metrics(upm)
    if line_height is None:
        line_height = default_line_height
    temp_dir = str(job_dir(job_id))
    png_folder = Path(temp_dir) / "png_glyphs"
    svg_folder = Path(temp_dir) / "svg_glyphs"
    svg_folder.mkdir(parents=True, exist_ok=True)

    # Heartbeat: refresh updated_at while the pipeline runs so pollers can
    # tell a slow phase (nanoemoji can take 20+ minutes) from a dead thread.
    stop_heartbeat = threading.Event()

    def _heartbeat():
        while not stop_heartbeat.wait(HEARTBEAT_SECONDS):
            try:
                write_job_status(job_id)
            except Exception:
                pass

    threading.Thread(target=_heartbeat, daemon=True).start()

    try:
        # 1. Trace PNGs to SVG outlines
        write_job_status(job_id, status="processing", phase="tracing", detail="Tracing PNGs to SVG outlines")
        convert_pngs_to_svgs(png_folder, svg_folder, target_upm=upm)
        logger.info("PNG to SVG conversion completed.")

        # 1b. Shift traced SVGs for descent/baseline. Separate from tracing
        # so metric changes never require a re-trace; both FontForge and
        # addsvg consume this shifted folder.
        svg_shifted_folder = Path(temp_dir) / "svg_glyphs_shifted"
        shift_svgs_for_descent(svg_folder, svg_shifted_folder, target_upm=upm, descent=descent)
        logger.info("Applied vertical metrics to traced SVGs.")

        # 1c. Flatten each color SVG into one silhouette path for FontForge:
        # tracing produces hundreds of overlapping paths per glyph, which
        # FontForge's removeOverlap chokes on (minutes per glyph) but
        # skia-pathops unions in seconds. addsvg still gets the color folder.
        svg_outline_folder = Path(temp_dir) / "svg_glyphs_outline"
        flatten_svgs_for_outlines(svg_shifted_folder, svg_outline_folder)
        logger.info("Flattened SVGs to silhouettes for FontForge.")

        # 2. Compile the base TTF with FontForge
        write_job_status(job_id, phase="fontforge", detail="Compiling TTF with FontForge")
        output_ttf_filename = f"{fontname}.ttf"
        output_ttf_path = os.path.join(temp_dir, output_ttf_filename)

        fontforge_cmd = [
            "fontforge",
            "-script",
            "font.py",
            str(svg_outline_folder),
            "--output",
            output_ttf_path,
            "--fontname",
            fontname,
            "--fullname",
            fullname,
            "--familyname",
            familyname,
            "--upm",
            str(upm),
            "--advance-width",
            str(advance_width),
            "--vertical-raise",
            str(vertical_raise),
            "--ascent",
            str(ascent),
            "--descent",
            str(descent),
            "--line-height",
            str(line_height),
            "--letter-spacing",
            str(letter_spacing),
        ]
        if monospace:
            fontforge_cmd.append("--monospace")

        logger.info(f"Executing FontForge: {' '.join(fontforge_cmd)}")
        ff_res = subprocess.run(
            fontforge_cmd, capture_output=True, text=True, check=False
        )

        if ff_res.returncode != 0:
            logger.error(f"FontForge failed with error: {ff_res.stderr}")
            raise RuntimeError(
                f"FontForge compilation failed: {ff_res.stderr or ff_res.stdout}"
            )

        logger.info("FontForge TTF generation completed successfully.")

        # 2b. Resize each color SVG's canvas to match its real hmtx advance
        # (now final) so Firefox's width-based OT-SVG sizing lines up with
        # the outline glyph instead of the traced canvas's natural aspect.
        align_color_svg_widths(svg_shifted_folder, output_ttf_path)
        logger.info("Aligned color SVG widths to font advances.")

        # 3. Embed the color SVG documents as an 'SVG ' table (addsvg)
        addsvg_bin = shutil.which("addsvg") or "/opt/miniconda3/envs/genFont/bin/addsvg"
        addsvg_cmd = [addsvg_bin, str(svg_shifted_folder), output_ttf_path]

        logger.info(f"Executing addsvg: {' '.join(addsvg_cmd)}")
        addsvg_res = subprocess.run(
            addsvg_cmd, capture_output=True, text=True, check=False
        )

        if addsvg_res.returncode != 0:
            # Non-fatal: the TTF is still usable without color outlines.
            logger.warning(
                f"addsvg failed with error (Color outlines might be skipped): {addsvg_res.stderr}"
            )
        else:
            logger.info("Successfully embedded color SVG outlines into the TTF.")

        if not os.path.exists(output_ttf_path):
            raise RuntimeError(
                "TTF generation succeeded but the output file could not be found."
            )

        # 4. Add COLR/CBDT color tables with nanoemoji's maximum_color
        write_job_status(job_id, phase="color-optimize", detail="Embedding color layers (nanoemoji)")
        nanoemoji_dir = Path("nanoemoji")
        output_ttf_color_filename = f"{fontname}_color.ttf"
        output_ttf_color_path = os.path.join(temp_dir, output_ttf_color_filename)

        if nanoemoji_dir.exists():
            output_ttf_color_path = run_maximum_color(
                job_id, temp_dir, output_ttf_path, output_ttf_color_path
            )
        else:
            logger.warning("nanoemoji directory not found, using original TTF")
            shutil.copy(output_ttf_path, output_ttf_color_path)

        # 5. Post-process the color TTF: rewrite bitmap advances from hmtx
        # (see fix_bitmap_advances), graft sbix for pre-13 macOS CoreText
        # (see add_sbix_table; no-op if the nanoemoji assets are missing),
        # and drop redundant tables (see subset_drop_unused_tables).
        fix_bitmap_advances(output_ttf_color_path)
        add_sbix_table(output_ttf_color_path, Path(temp_dir) / "build", output_ttf_path)
        subset_drop_unused_tables(output_ttf_color_path, flavor="ttf")

        # 6. Convert TTF to WOFF2 (the one web format all three target
        # browsers — Chrome, Firefox, Safari — support; plain WOFF is
        # legacy-only and no longer produced).
        write_job_status(job_id, phase="woff", detail="Converting TTF to WOFF2")
        output_woff2_path = convert_to_webfont(temp_dir, output_ttf_color_path, fontname)

        # 7. Create ZIP file with color-optimized TTF and WOFF2
        write_job_status(job_id, phase="zipping", detail="Packaging TTF + WOFF2")
        output_zip_filename = f"{fontname}_fonts.zip"
        output_zip_path = os.path.join(temp_dir, output_zip_filename)

        # Each file is added only if its conversion succeeded.
        with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, arcname in (
                (output_ttf_color_path, f"{fontname}.ttf"),
                (output_woff2_path, f"{fontname}.woff2"),
            ):
                if os.path.exists(path):
                    zf.write(path, arcname=arcname)
                    logger.info(f"Added {arcname} to zip")

        logger.info(f"Created ZIP archive: {output_zip_filename}")

        # 8. Mark completed — the result stays on disk until the TTL sweep.
        write_job_status(
            job_id, status="completed", phase="done", detail="", zip_filename=output_zip_filename
        )

    except Exception as e:
        logger.exception(f"Font generation job {job_id} failed:")
        # Keep the job dir (status.json included) so pollers see the failure;
        # the TTL sweep removes it later.
        write_job_status(job_id, status="failed", phase="error", detail=str(e))
    finally:
        stop_heartbeat.set()


def run_maximum_color(
    job_id: str, temp_dir: str, output_ttf_path: str, output_ttf_color_path: str
) -> str:
    """Run nanoemoji's maximum_color, streaming progress into the job status.

    Falls back to copying the non-color TTF if the run fails. Returns
    output_ttf_color_path (always written, one way or the other).

    cwd=<job workspace> keeps nanoemoji's build/ per-job (concurrent jobs
    otherwise clobber each other's Font.ttf). Output is streamed line by
    line — this phase can run 20+ minutes — and kept in full at
    <job>/nanoemoji.log.
    """
    maximum_color_cmd = [
        "maximum_color",
        "--bitmaps",
        str(output_ttf_path),
    ]
    mc_log_path = Path(temp_dir) / "nanoemoji.log"
    logger.info(f"Executing maximum_color: {' '.join(maximum_color_cmd)} (full log: {mc_log_path})")
    last_line = ""
    last_status_write = 0.0
    with mc_log_path.open("w") as mc_log:
        mc_proc = subprocess.Popen(
            maximum_color_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=temp_dir,
        )
        for raw_line in mc_proc.stdout:
            mc_log.write(raw_line)
            mc_log.flush()
            line = raw_line.strip()
            if not line:
                continue
            last_line = line
            logger.info(f"[nanoemoji {job_id[:8]}] {line}")
            # Surface progress to pollers, throttled to every 2s.
            if time.time() - last_status_write > 2:
                write_job_status(job_id, detail=f"nanoemoji: {line[:200]}")
                last_status_write = time.time()
        mc_proc.wait()

    nanoemoji_output = Path(temp_dir) / "build" / "Font.ttf"
    if mc_proc.returncode == 0 and nanoemoji_output.exists():
        shutil.copy(nanoemoji_output, output_ttf_color_path)
        logger.info("Successfully applied maximum_color optimization.")
    else:
        logger.warning(
            f"maximum_color failed (exit {mc_proc.returncode}); "
            f"last output: {last_line!r} — falling back to non-color TTF. "
            f"Full log: {mc_log_path}"
        )
        write_job_status(
            job_id,
            detail=f"nanoemoji failed (exit {mc_proc.returncode}) — continuing with non-color TTF",
        )
        shutil.copy(output_ttf_path, output_ttf_color_path)
    return output_ttf_color_path


def convert_to_webfont(temp_dir: str, ttf_path: str, fontname: str) -> str:
    """Convert the final TTF to WOFF2.

    Returns the woff2_path target; the file may be missing if conversion
    failed (callers must check existence).
    """
    font_ttf_input = os.path.join(temp_dir, "font.ttf")
    shutil.copy(ttf_path, font_ttf_input)

    output_woff2_path = os.path.join(temp_dir, f"{fontname}.woff2")

    # ttf2woff2 reads stdin and writes stdout
    ttf2woff2_bin = shutil.which("ttf2woff2") or os.path.expanduser(
        "~/.nvm/versions/node/v24.15.0/bin/ttf2woff2"
    )
    logger.info(f"Executing ttf2woff2: {font_ttf_input} -> {output_woff2_path}")
    with open(font_ttf_input, "rb") as ttf_in, open(output_woff2_path, "wb") as woff2_out:
        ttf2woff2_res = subprocess.run(
            [ttf2woff2_bin],
            stdin=ttf_in,
            stdout=woff2_out,
            stderr=subprocess.PIPE,
            check=False,
        )

    if ttf2woff2_res.returncode != 0:
        logger.warning(
            f"ttf2woff2 failed with error: {ttf2woff2_res.stderr.decode(errors='replace')}"
        )
        # Don't let a partial output end up in the ZIP
        if os.path.exists(output_woff2_path):
            os.remove(output_woff2_path)
    elif os.path.exists(output_woff2_path):
        subset_drop_unused_tables(output_woff2_path, flavor="woff2")

    return output_woff2_path
