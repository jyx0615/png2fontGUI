import os
import shutil
import tempfile
import subprocess
import logging
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("png2font-api")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="png2font API",
    description="Convert PNG glyphs into a monospace TTF font with embedded SVG outlines.",
    version="1.0.0",
)

# Allow localhost:3000 and 127.0.0.1:3000 to access the endpoint (CORS)
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import png2svg conversion function
from png2svg import convert_pngs_to_svgs

# Helper to remove a directory tree
def cleanup_temp_dir(temp_dir_path: str):
    try:
        if os.path.exists(temp_dir_path):
            shutil.rmtree(temp_dir_path)
            logger.info(f"Cleaned up temporary workspace: {temp_dir_path}")
    except Exception as e:
        logger.error(f"Error cleaning up temporary workspace {temp_dir_path}: {e}")

@app.post("/api/generate-font", summary="Convert uploaded PNG glyphs to a TTF font")
async def generate_font(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(
        ...,
        description="List of PNG glyph files. File names must reflect their characters (e.g. 'A.png' or hex codepoints 'u0041.png')"
    ),
    fontname: str = Form("MyCustomFont", description="Sleek, URL-safe font identifier"),
    fullname: str = Form("My Custom Font", description="Full display name of the font"),
    familyname: str = Form("My Family", description="Font family name group"),
    upm: int = Form(1000, description="Units per EM (square canvas height/width)"),
    advance_width: int = Form(600, description="Monospace advance character width"),
    vertical_raise: int = Form(120, description="Baseline raise offset to align glyphs"),
):
    # Validate uploaded files are PNGs
    for file in files:
        filename = os.path.basename(file.filename)
        if not filename.lower().endswith(".png"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file format: {file.filename}. Only PNG files are supported."
            )

    # 1. Create a unique isolated temporary workspace
    temp_dir = tempfile.mkdtemp()
    png_folder = Path(temp_dir) / "png_glyphs"
    svg_folder = Path(temp_dir) / "svg_glyphs"

    png_folder.mkdir(parents=True, exist_ok=True)
    svg_folder.mkdir(parents=True, exist_ok=True)

    try:
        # 2. Write uploaded PNGs to the temp folder
        for file in files:
            filename = os.path.basename(file.filename)
            if not filename or filename == ".png":
                # If name is empty or only extension, fallback to a safe name
                filename = "glyph.png"
            file_path = png_folder / filename
            with file_path.open("wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"Saved {len(files)} PNGs to temporary workspace.")

        # 3. Run PNG to SVG tracing conversion
        convert_pngs_to_svgs(png_folder, svg_folder, target_upm=upm)
        logger.info("PNG to SVG conversion completed.")

        # 4. Generate TTF using FontForge
        output_ttf_filename = f"{fontname}.ttf"
        output_ttf_path = os.path.join(temp_dir, output_ttf_filename)

        fontforge_cmd = [
            "fontforge", "-script", "font.py",
            str(svg_folder),
            "--output", output_ttf_path,
            "--fontname", fontname,
            "--fullname", fullname,
            "--familyname", familyname,
            "--upm", str(upm),
            "--advance-width", str(advance_width),
            "--vertical-raise", str(vertical_raise)
        ]

        logger.info(f"Executing FontForge: {' '.join(fontforge_cmd)}")
        ff_res = subprocess.run(fontforge_cmd, capture_output=True, text=True, check=False)
        
        if ff_res.returncode != 0:
            logger.error(f"FontForge failed with error: {ff_res.stderr}")
            raise HTTPException(
                status_code=500,
                detail=f"FontForge compilation failed: {ff_res.stderr or ff_res.stdout}"
            )
        
        logger.info("FontForge TTF generation completed successfully.")

        # 5. Embed SVG outlines back into the TTF using addsvg
        # Discover addsvg bin or fallback
        addsvg_bin = shutil.which("addsvg") or "/opt/miniconda3/envs/genFont/bin/addsvg"
        addsvg_cmd = [addsvg_bin, str(svg_folder), output_ttf_path]

        logger.info(f"Executing addsvg: {' '.join(addsvg_cmd)}")
        addsvg_res = subprocess.run(addsvg_cmd, capture_output=True, text=True, check=False)

        if addsvg_res.returncode != 0:
            # We can log this but still return the TTF since TTF is technically generated
            logger.warning(f"addsvg failed with error (Color outlines might be skipped): {addsvg_res.stderr}")
        else:
            logger.info("Successfully embedded color SVG outlines into the TTF.")

        if not os.path.exists(output_ttf_path):
            raise HTTPException(
                status_code=500,
                detail="TTF generation succeeded but the output file could not be found."
            )

        # 6. Return the file as response, clean up when completed
        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(
            path=output_ttf_path,
            filename=output_ttf_filename,
            media_type="font/ttf"
        )

    except HTTPException:
        # Re-raise known HTTP exceptions
        cleanup_temp_dir(temp_dir)
        raise
    except Exception as e:
        cleanup_temp_dir(temp_dir)
        logger.exception("Unexpected error during font generation:")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )

# Fallback UI serve (GET /)
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index():
    index_path = Path("static/index.html")
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    
    # Elegant fallback page in case static files are loading
    return HTMLResponse(
        content="""
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
        """
    )

# Serve static directory if it exists
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
