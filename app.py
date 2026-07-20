import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from job_store import (
    JOB_ID_RE,
    ORPHAN_STALE_SECONDS,
    fail_orphaned_jobs,
    job_dir,
    read_job_status,
    sweep_stale_jobs,
    write_job_status,
)
from pipeline import run_generation_job


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("png2font-api")


app = FastAPI(
    title="png2font API",
    description="Convert PNG glyphs into a TTF font with optional embedded SVG outlines.",
    version="1.0.0",
)

# CORS allowlist
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

fail_orphaned_jobs()


@app.post(
    "/api/generate-font",
    status_code=202,
    summary="Submit a font generation job (PNG glyphs → TTF + WOFF2)",
    description=(
        "Saves the uploaded PNG glyphs, starts generation in the background, and "
        "returns a job_id immediately. Generation can take ~10 minutes: poll "
        "GET /api/job/{job_id}, then download the ZIP (color TTF + WOFF2) from "
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
    line_height: int | None = Form(
        None,
        description=(
            "Default line height in units (ascent + descent + line gap). "
            "Omit for the standard 1.2 em (1.2 x upm) that matches system fonts. "
            "Note: only affects text rendered at line-height:normal; apps that "
            "set an explicit line height override this."
        ),
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
            line_height, letter_spacing,
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
    summary="Download the finished TTF + WOFF2 ZIP for a completed job",
    responses={
        200: {
            "description": "ZIP archive containing TTF and WOFF2 font files",
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

    # Fallback page when static/index.html is missing
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
