import json
import os
import re
import shutil
import tempfile
import threading
import time
import subprocess
import logging
import uuid
import zipfile
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("png2font-api")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="png2font API",
    description="Convert PNG glyphs into a TTF font with optional embedded SVG outlines.",
    version="1.0.0",
)

# Allow localhost:3000 and 127.0.0.1:3000 to access the endpoint (CORS)
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://localhost:8000",
    "http://127.0.0.1:8000",
    "https://fonty.cb-playground.workers.dev",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)

# Import png2svg conversion function
from fontTools.ttLib import TTFont

from png2svg import convert_pngs_to_svgs, shift_svgs_for_descent


def fix_bitmap_advances(font_path: str) -> None:
    """Copy hmtx advances into the CBDT bitmap glyph metrics.

    nanoemoji assumes emoji-style square glyphs and sets each bitmap's
    advance to its rendered image width — a full em for the blank space
    glyph. Chrome lays out CBDT color glyphs with those bitmap advances,
    not hmtx, so word spacing and letter spacing were silently ignored.
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


# Helper to remove a directory tree
def cleanup_temp_dir(temp_dir_path: str):
    try:
        if os.path.exists(temp_dir_path):
            shutil.rmtree(temp_dir_path)
            logger.info(f"Cleaned up temporary workspace: {temp_dir_path}")
    except Exception as e:
        logger.error(f"Error cleaning up temporary workspace {temp_dir_path}: {e}")


# ─── Job store ────────────────────────────────────────────────────────────────
# Generation takes minutes, far longer than proxies in front of this server
# allow a request to stay open (Cloudflare tunnels cut it at ~100s → 524).
# So POST /api/generate-font only enqueues: it saves the uploads, spawns a
# worker thread, and returns a job_id immediately. Clients poll
# GET /api/job/{id} and download the ZIP from GET /api/job/{id}/result.
#
# Job state lives on the filesystem (status.json per job) so it survives
# uvicorn --reload restarts and works with multiple workers.

JOBS_ROOT = Path(tempfile.gettempdir()) / "png2font_jobs"
JOB_TTL_SECONDS = 2 * 60 * 60  # keep results around for 2 hours
JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
HEARTBEAT_SECONDS = 15
# A processing job whose status hasn't been touched for this long has a dead
# worker thread (heartbeats refresh updated_at every HEARTBEAT_SECONDS).
ORPHAN_STALE_SECONDS = 90

# Serializes read-modify-write of status.json between the pipeline thread and
# its heartbeat thread, so a heartbeat can never resurrect a terminal status.
_status_write_lock = threading.Lock()


def job_dir(job_id: str) -> Path:
    return JOBS_ROOT / job_id


def write_job_status(job_id: str, **fields):
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    status_path = d / "status.json"
    with _status_write_lock:
        current = read_job_status(job_id) or {}
        current.update(fields)
        current["updated_at"] = time.time()
        tmp = status_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current))
        tmp.replace(status_path)


def read_job_status(job_id: str):
    try:
        return json.loads((job_dir(job_id) / "status.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def sweep_stale_jobs():
    """Delete job workspaces older than the TTL. Called on each new submission."""
    if not JOBS_ROOT.exists():
        return
    cutoff = time.time() - JOB_TTL_SECONDS
    for d in JOBS_ROOT.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                logger.info(f"Swept stale job workspace: {d.name}")
        except OSError:
            pass


def fail_orphaned_jobs():
    """Worker threads die with the process (server restart / --reload), leaving
    their jobs stuck in queued/processing forever — and clients polling them
    forever. A live worker heartbeats status.json every HEARTBEAT_SECONDS, so a
    non-terminal job with a stale updated_at has no thread behind it: mark it
    failed so pollers get a definitive answer. Called at startup and lazily
    from the status endpoint."""
    if not JOBS_ROOT.exists():
        return
    cutoff = time.time() - ORPHAN_STALE_SECONDS
    for d in JOBS_ROOT.iterdir():
        if not d.is_dir():
            continue
        status = read_job_status(d.name)
        if (
            status
            and status.get("status") in ("queued", "processing")
            and status.get("updated_at", 0) < cutoff
        ):
            write_job_status(
                d.name,
                status="failed",
                phase="error",
                detail="The font server restarted during generation — please export again.",
            )
            logger.warning(f"Marked orphaned job as failed: {d.name}")


fail_orphaned_jobs()


def run_generation_job(
    job_id: str,
    fontname: str,
    fullname: str,
    familyname: str,
    upm: int,
    advance_width: int,
    vertical_raise: int,
    monospace: bool,
    ascent: int,
    descent: int,
    line_height: int,
    letter_spacing: int,
):
    """Worker-thread body: runs the full pipeline, updating status.json as it goes."""
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
        # 1. Run PNG to SVG tracing conversion
        write_job_status(job_id, status="processing", phase="tracing", detail="Tracing PNGs to SVG outlines")
        convert_pngs_to_svgs(png_folder, svg_folder, target_upm=upm)
        logger.info("PNG to SVG conversion completed.")

        # 1b. Apply vertical metrics (descent/baseline placement) to the
        # traced SVGs.  Kept separate from tracing so metric changes
        # (ascent/descent/line-height) never require a re-trace — both
        # FontForge and addsvg consume this shifted folder.
        svg_shifted_folder = Path(temp_dir) / "svg_glyphs_shifted"
        shift_svgs_for_descent(svg_folder, svg_shifted_folder, target_upm=upm, descent=descent)
        logger.info("Applied vertical metrics to traced SVGs.")

        # 2. Generate TTF using FontForge
        write_job_status(job_id, phase="fontforge", detail="Compiling TTF with FontForge")
        output_ttf_filename = f"{fontname}.ttf"
        output_ttf_path = os.path.join(temp_dir, output_ttf_filename)

        fontforge_cmd = [
            "fontforge",
            "-script",
            "font.py",
            str(svg_shifted_folder),
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

        # 5. Embed SVG outlines back into the TTF using addsvg
        # Discover addsvg bin or fallback
        addsvg_bin = shutil.which("addsvg") or "/opt/miniconda3/envs/genFont/bin/addsvg"
        addsvg_cmd = [addsvg_bin, str(svg_shifted_folder), output_ttf_path]

        logger.info(f"Executing addsvg: {' '.join(addsvg_cmd)}")
        addsvg_res = subprocess.run(
            addsvg_cmd, capture_output=True, text=True, check=False
        )

        if addsvg_res.returncode != 0:
            # We can log this but still return the TTF since TTF is technically generated
            logger.warning(
                f"addsvg failed with error (Color outlines might be skipped): {addsvg_res.stderr}"
            )
        else:
            logger.info("Successfully embedded color SVG outlines into the TTF.")

        if not os.path.exists(output_ttf_path):
            raise RuntimeError(
                "TTF generation succeeded but the output file could not be found."
            )

        # 4. Run maximum_color from nanoemoji to add color information
        write_job_status(job_id, phase="color-optimize", detail="Embedding color layers (nanoemoji)")
        nanoemoji_dir = Path("nanoemoji")
        output_ttf_color_filename = f"{fontname}_color.ttf"
        output_ttf_color_path = os.path.join(temp_dir, output_ttf_color_filename)

        if nanoemoji_dir.exists():
            # Run with cwd=<job workspace> so nanoemoji's build/ output is
            # per-job — with the shared nanoemoji/build dir, concurrent jobs
            # clobber each other's Font.ttf. Stream the output line by line:
            # this phase can run 20+ minutes and used to be completely silent
            # (and its failures invisible — it silently fell back to the
            # non-color TTF). Full output is kept in <job>/nanoemoji.log.
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
                # Fallback to using original TTF if maximum_color fails
                shutil.copy(output_ttf_path, output_ttf_color_path)
        else:
            logger.warning("nanoemoji directory not found, using original TTF")
            shutil.copy(output_ttf_path, output_ttf_color_path)

        # nanoemoji writes emoji-style bitmap advances (image width, 1 em for
        # the space) — rewrite them from hmtx so Chrome's CBDT layout honors
        # the font's real spacing. No-op if the font has no bitmap tables.
        fix_bitmap_advances(output_ttf_color_path)

        # 5. Convert TTF to WOFF using nanoemoji output
        write_job_status(job_id, phase="woff", detail="Converting TTF to WOFF")
        font_ttf_input = os.path.join(temp_dir, "font.ttf")
        shutil.copy(output_ttf_color_path, font_ttf_input)

        output_woff_filename = f"{fontname}.woff"
        output_woff_path = os.path.join(temp_dir, output_woff_filename)

        ttf2woff_cmd = ["ttf2woff", font_ttf_input, output_woff_path]
        logger.info(f"Executing ttf2woff: {' '.join(ttf2woff_cmd)}")
        ttf2woff_res = subprocess.run(
            ttf2woff_cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if ttf2woff_res.returncode != 0:
            logger.warning(
                f"ttf2woff failed with error: {ttf2woff_res.stderr}"
            )
            
        # 6. Convert TTF to WOFF2 (ttf2woff2 reads the TTF from stdin and
        # writes the WOFF2 to stdout)
        write_job_status(job_id, phase="woff2", detail="Converting TTF to WOFF2")
        output_woff2_filename = f"{fontname}.woff2"
        output_woff2_path = os.path.join(temp_dir, output_woff2_filename)

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
            # Remove the empty/partial output so it doesn't end up in the ZIP
            if os.path.exists(output_woff2_path):
                os.remove(output_woff2_path)

        # 7. Create ZIP file with color-optimized TTF, WOFF and WOFF2
        write_job_status(job_id, phase="zipping", detail="Packaging TTF + WOFF + WOFF2")
        output_zip_filename = f"{fontname}_fonts.zip"
        output_zip_path = os.path.join(temp_dir, output_zip_filename)

        with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add color-optimized TTF
            if os.path.exists(output_ttf_color_path):
                zf.write(output_ttf_color_path, arcname=f"{fontname}.ttf")
                logger.info(f"Added {fontname}.ttf to zip")

            # Add WOFF if conversion succeeded
            if os.path.exists(output_woff_path):
                zf.write(output_woff_path, arcname=output_woff_filename)
                logger.info(f"Added {output_woff_filename} to zip")

            # Add WOFF2 if conversion succeeded
            if os.path.exists(output_woff2_path):
                zf.write(output_woff2_path, arcname=output_woff2_filename)
                logger.info(f"Added {output_woff2_filename} to zip")

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


@app.post(
    "/api/generate-font",
    status_code=202,
    summary="Submit a font generation job (PNG glyphs → TTF + WOFF + WOFF2)",
    description=(
        "Saves the uploaded PNG glyphs, starts generation in the background, and "
        "returns a job_id immediately. Generation can take ~10 minutes: poll "
        "GET /api/job/{job_id}, then download the ZIP (color TTF + WOFF + WOFF2) from "
        "GET /api/job/{job_id}/result."
    ),
    responses={
        202: {
            "description": "Job accepted",
            "content": {"application/json": {"example": {"job_id": "0f3a...", "status": "queued"}}},
        },
        400: {"description": "Invalid input (non-PNG files or missing required fields)"},
    },
)
def generate_font(
    files: list[UploadFile] = File(
        ...,
        description="List of PNG glyph files. File names must reflect their characters (e.g. 'A.png' or hex codepoints 'u0041.png')",
    ),
    fontname: str = Form("MyCustomFont", description="URL-safe font identifier (used in filenames)"),
    fullname: str = Form("My Custom Font", description="Full display name visible in font menus"),
    familyname: str = Form("My Family", description="Font family name for grouping"),
    upm: int = Form(1000, description="Units per EM - canvas grid size (500-2048)"),
    advance_width: int = Form(
        600, description="Character advance width for monospace fonts (500-2048)"
    ),
    vertical_raise: int = Form(
        0, description="Baseline vertical offset in units (-500 to 500)"
    ),
    monospace: bool = Form(False, description="Enable monospace layout with fixed character widths"),
    ascent: int = Form(800, description="Font-wide ascent in units (distance above baseline)"),
    descent: int = Form(200, description="Font-wide descent in units (distance below baseline)"),
    line_height: int = Form(
        1200, description="Target default line height in units (ascent + descent + line gap)"
    ),
    letter_spacing: int = Form(
        0, description="Extra advance width added after each non-space glyph, in units"
    ),
):
    # Validate uploaded files are PNGs
    for file in files:
        filename = os.path.basename(file.filename)
        if not filename.lower().endswith(".png"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file format: {file.filename}. Only PNG files are supported.",
            )

    sweep_stale_jobs()

    # Persist the uploads into the job workspace before returning — the
    # UploadFile streams are only readable while the request is alive.
    job_id = uuid.uuid4().hex
    png_folder = job_dir(job_id) / "png_glyphs"
    png_folder.mkdir(parents=True, exist_ok=True)
    for file in files:
        filename = os.path.basename(file.filename)
        if not filename or filename == ".png":
            filename = "glyph.png"
        with (png_folder / filename).open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    logger.info(f"Job {job_id}: saved {len(files)} PNGs, starting worker thread.")

    write_job_status(job_id, status="queued", phase="queued", detail="Waiting to start")
    threading.Thread(
        target=run_generation_job,
        args=(
            job_id, fontname, fullname, familyname, upm, advance_width, vertical_raise, monospace,
            ascent, descent, line_height, letter_spacing,
        ),
        daemon=True,
    ).start()

    return JSONResponse(status_code=202, content={"job_id": job_id, "status": "queued"})


@app.get(
    "/api/job/{job_id}",
    summary="Poll a font generation job",
    responses={
        200: {
            "description": "Job state",
            "content": {"application/json": {"example": {"status": "processing", "phase": "fontforge", "detail": "Compiling TTF with FontForge"}}},
        },
        404: {"description": "Unknown or expired job"},
    },
)
def get_job_status(job_id: str):
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    status = read_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown or expired job")
    # A non-terminal job with no recent heartbeat has a dead worker thread —
    # report it as failed instead of letting the client poll forever.
    if (
        status.get("status") in ("queued", "processing")
        and status.get("updated_at", 0) < time.time() - ORPHAN_STALE_SECONDS
    ):
        write_job_status(
            job_id,
            status="failed",
            phase="error",
            detail="The font server restarted during generation — please export again.",
        )
        return read_job_status(job_id)
    return status


@app.get(
    "/api/job/{job_id}/result",
    summary="Download the finished TTF + WOFF + WOFF2 ZIP for a completed job",
    responses={
        200: {
            "description": "ZIP archive containing TTF, WOFF and WOFF2 font files",
            "content": {"application/zip": {"example": "fontname_fonts.zip"}},
        },
        404: {"description": "Unknown or expired job"},
        409: {"description": "Job is not completed yet (or failed)"},
    },
)
def get_job_result(job_id: str):
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    status = read_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown or expired job")
    if status.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Job is {status.get('status', 'unknown')} ({status.get('detail', '')})",
        )
    zip_filename = status.get("zip_filename", "")
    zip_path = job_dir(job_id) / zip_filename
    if not zip_filename or not zip_path.exists():
        raise HTTPException(status_code=404, detail="Result file no longer available")
    return FileResponse(path=str(zip_path), filename=zip_filename, media_type="application/zip")


# Fallback UI serve (GET /)
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index():
    index_path = Path("static/index.html")
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))

    # Elegant fallback page in case static files are loading
    return HTMLResponse(content="""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>png2font API Server</title>
            <style>
                body {
                    margin: 0;
                    padding: 0;
                    background: linear-gradient(135deg, #0f0c20 0%, #15102a 100%);
                    color: #fff;
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    text-align: center;
                }
                .card {
                    background: rgba(255, 255, 255, 0.03);
                    border: 1px solid rgba(255, 255, 255, 0.05);
                    border-radius: 20px;
                    padding: 40px;
                    backdrop-filter: blur(10px);
                    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
                }
                h1 {
                    font-size: 2.5rem;
                    margin-bottom: 10px;
                    background: linear-gradient(90deg, #a855f7 0%, #3b82f6 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                }
                p {
                    color: #94a3b8;
                    margin-bottom: 30px;
                }
                a {
                    display: inline-block;
                    background: linear-gradient(90deg, #a855f7 0%, #6366f1 100%);
                    color: #fff;
                    text-decoration: none;
                    padding: 12px 30px;
                    border-radius: 30px;
                    font-weight: 600;
                    transition: transform 0.2s, box-shadow 0.2s;
                    box-shadow: 0 4px 15px rgba(168, 85, 247, 0.4);
                }
                a:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(168, 85, 247, 0.6);
                }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>png2font API Server</h1>
                <p>The font generation backend is fully active and operational.</p>
                <a href="/docs">Explore Interactive API Docs</a>
            </div>
        </body>
        </html>
        """)


# Serve static directory if it exists
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
