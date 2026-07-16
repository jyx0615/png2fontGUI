import argparse
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import vtracer
from PIL import Image
from picosvg.svg import SVG
from picosvg import svg_pathops
from picosvg.svg_types import SVGPath

from config import CONFIG

SVG_NS = "http://www.w3.org/2000/svg"
UPM = CONFIG.upm
ET.register_namespace("", SVG_NS)


def normalize_svg_root(svg_path: str) -> str:
    tree = ET.parse(svg_path)
    root = tree.getroot()

    handle, temp_path = tempfile.mkstemp(suffix=".svg")
    os.close(handle)

    tree.write(temp_path, encoding="utf-8", xml_declaration=False)
    return temp_path


def create_empty_svg(
    svg_output_path: Path, width: int = UPM, height: int = UPM
) -> None:
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 -{height} {width} {height}",
        },
    )
    tree = ET.ElementTree(root)
    tree.write(svg_output_path, encoding="utf-8", xml_declaration=False)


UPSCALE_FACTOR = 2  # nearest-neighbor upscale before tracing

# Same-fill stroke width (traced-pixel units, ~0.6% of the em). Cutout tracing
# tiles regions edge-to-edge, so anti-aliasing shows the background through
# shared edges as hairline seams; stroking each region with its own fill
# overlaps neighbors just enough to hide them.
SEAM_STROKE_WIDTH = 2
ALPHA_THRESHOLD = 220

def upscale_png(png_path: Path, scale: int = UPSCALE_FACTOR, alpha_threshold: int = ALPHA_THRESHOLD) -> str:
    """Return path to a temp PNG prepared for tracing: defringe, binarize alpha,
    composite over white, then upscale `scale`x with nearest-neighbor."""
    img = Image.open(png_path).convert("RGBA")

    # Defringe: background removal leaves semi-transparent edge pixels blended
    # with the original background. Un-premultiplying (fg = observed × 255 / alpha)
    # recovers the true color, but only if the background was dark — on a light
    # background it would wash out the colors instead. Use the mean brightness
    # of semi-transparent pixels to decide.
    data = np.array(img, dtype=np.float32)
    rgb, alpha_ch = data[:, :, :3], data[:, :, 3]

    edge_mask = (alpha_ch > 0) & (alpha_ch < 200)
    mean_brightness = rgb[edge_mask].mean() if edge_mask.any() else 255.0

    DARK_BG_THRESHOLD = 100
    if mean_brightness < DARK_BG_THRESHOLD:
        full_mask = alpha_ch > 0
        rgb[full_mask] = np.clip(
            rgb[full_mask] * (255.0 / alpha_ch[full_mask, np.newaxis]), 0, 255
        )
        img = Image.fromarray(data.astype(np.uint8), "RGBA")

    # Binarize alpha at the original resolution, then composite over white so
    # transparent pixels carry white RGB.
    r, g, b, a = img.split()
    hard_alpha = a.point(lambda v: 255 if v >= alpha_threshold else 0)

    white_bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    white_bg.paste(img, mask=hard_alpha)
    r_clean, g_clean, b_clean, _ = white_bg.split()
    cleaned = Image.merge("RGBA", (r_clean, g_clean, b_clean, hard_alpha))

    # Nearest-neighbor replicates pixels exactly — no color blending.
    if scale > 1:
        new_size = (cleaned.width * scale, cleaned.height * scale)
        cleaned = cleaned.resize(new_size, Image.NEAREST)

    handle, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    cleaned.save(tmp_path, format="PNG")
    return tmp_path


def wrap_png_to_svg(png_path, svg_output_path, width=150, height=150, target_upm=UPM):
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as temp_file:
        temp_svg_path = temp_file.name

    upscaled_png_path = upscale_png(png_path)

    try:
        vtracer.convert_image_to_svg_py(
            upscaled_png_path,
            str(temp_svg_path),
            colormode="color",
            hierarchical="cutout",      # exact region edges; seams covered by strokes below
            mode="spline",              # smooth Bézier curves
            filter_speckle=1,           # keep tiny detail regions (fur/texture)
            color_precision=8,          # many color clusters → rich gradients
            corner_threshold=60,
            length_threshold=3.0,
            splice_threshold=45,
        )

        tree = ET.parse(temp_svg_path)
        root = tree.getroot()
        namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""

        # Cover cutout-mode seams: stroke every region with its own fill so
        # adjacent regions overlap slightly (see SEAM_STROKE_WIDTH).
        path_tag = f"{{{namespace}}}path" if namespace else "path"
        for path in root.iter(path_tag):
            fill = path.get("fill")
            if fill and fill != "none":
                path.set("stroke", fill)
                path.set("stroke-width", str(SEAM_STROKE_WIDTH))
                path.set("stroke-linejoin", "round")

        view_box = root.attrib.get("viewBox")
        if view_box:
            _, _, source_width, source_height = map(float, view_box.split())
        else:
            source_width = float(root.attrib.get("width", width))
            source_height = float(root.attrib.get("height", height))

        # Scale by height only so the glyph keeps its natural aspect ratio;
        # the SVG width becomes the glyph's advance width.
        scale = target_upm / source_height
        scaled_width = round(source_width * scale)

        children = list(root)

        # Keep traced SVGs metric-independent: canvas bottom on y=0, ink at
        # negative y. Vertical metrics are applied later by
        # shift_svgs_for_descent(), so changing metrics never requires re-tracing.
        wrapper_tag = f"{{{namespace}}}g" if namespace else "g"
        wrapper = ET.Element(
            wrapper_tag,
            {
                "transform": f"scale({scale}) translate(0,-{source_height})",
            },
        )

        for child in children:
            root.remove(child)
            wrapper.append(child)

        root.append(wrapper)
        root.set("viewBox", f"0 -{target_upm} {scaled_width} {target_upm}")
        root.set("width", str(scaled_width))
        root.set("height", str(target_upm))

        ET.indent(tree, space="  ")
        tree.write(temp_svg_path, encoding="utf-8", xml_declaration=True)
        normalized_svg_path = normalize_svg_root(temp_svg_path)
        
        try:
            result = subprocess.run(
                ["./svgcleaner", normalized_svg_path, svg_output_path], check=True
            )
            # If svgcleaner failed or didn't produce output, fall back to copying
            if result.returncode != 0 or not os.path.exists(svg_output_path):
                shutil.copy(normalized_svg_path, svg_output_path)
        finally:
            if os.path.exists(normalized_svg_path):
                os.remove(normalized_svg_path)
    finally:
        if os.path.exists(temp_svg_path):
            os.remove(temp_svg_path)
        if os.path.exists(upscaled_png_path):
            os.remove(upscaled_png_path)


def convert_pngs_to_svgs(png_folder: Path | str, svg_output: Path | str, target_upm: int = UPM) -> None:
    png_directory = Path(png_folder)
    svg_output_directory = Path(svg_output)

    svg_output_directory.mkdir(parents=True, exist_ok=True)

    for png_path in sorted(png_directory.glob("*.png")):
        filename = png_path.name
        new_file_name = filename.replace("_alpha", "").rsplit(".", 1)[0] + ".svg"
        svg_output_path = svg_output_directory / new_file_name
        wrap_png_to_svg(png_path, svg_output_path, target_upm=target_upm)
        print(f"Converted {filename} to SVG format.")

    space_svg_output_path = svg_output_directory / "u0020.svg"
    create_empty_svg(space_svg_output_path, width=target_upm, height=target_upm)
    print("Created empty space SVG to preserve monospace width.")


def shift_svgs_for_descent(
    svg_folder: Path | str, out_folder: Path | str, target_upm: int, descent: int
) -> None:
    """Shift traced SVGs down by `descent` units at font-build time.

    Traced SVGs put the canvas bottom on y=0; the font treats the canvas as
    the full em box, so shifting leaves descender room below the baseline.
    Cheap XML rewrite — metric changes never require re-tracing.
    """
    src_directory = Path(svg_folder)
    out_directory = Path(out_folder)
    out_directory.mkdir(parents=True, exist_ok=True)

    for svg_path in sorted(src_directory.glob("*.svg")):
        tree = ET.parse(svg_path)
        root = tree.getroot()

        view_box = root.attrib.get("viewBox", f"0 -{target_upm} {target_upm} {target_upm}")
        _, _, vb_width, _ = view_box.split()

        wrapper = ET.Element(
            f"{{{SVG_NS}}}g", {"transform": f"translate(0,{descent})"}
        )
        for child in list(root):
            root.remove(child)
            wrapper.append(child)
        root.append(wrapper)

        root.set("viewBox", f"0 -{target_upm - descent} {vb_width} {target_upm}")
        tree.write(out_directory / svg_path.name, encoding="utf-8", xml_declaration=False)


def flatten_svgs_for_outlines(svg_folder: Path | str, out_folder: Path | str) -> None:
    """Union each SVG's color regions into one silhouette path for FontForge.

    FontForge only needs the monochrome 'glyf' outline from these SVGs (color
    comes from the 'SVG '/sbix tables), and its removeOverlap() takes minutes
    per glyph on hundreds of overlapping paths. Pre-unioning with skia-pathops
    takes seconds.
    """

    src_directory = Path(svg_folder)
    out_directory = Path(out_folder)
    out_directory.mkdir(parents=True, exist_ok=True)

    for svg_path in sorted(src_directory.glob("*.svg")):
        # Drop the seam-cover strokes: invisible in a monochrome silhouette,
        # but picosvg would convert each into an extra fill shape, doubling
        # the union work.
        tree = ET.parse(svg_path)
        for el in tree.iter():
            for attr in ("stroke", "stroke-width", "stroke-linejoin"):
                el.attrib.pop(attr, None)
        pico = SVG.fromstring(ET.tostring(tree.getroot(), encoding="unicode")).topicosvg()
        shapes = list(pico.shapes())
        vb = pico.view_box()

        if shapes:
            merged = SVGPath.from_commands(
                svg_pathops.union(
                    [s.as_cmd_seq() for s in shapes],
                    [getattr(s, "fill_rule", "nonzero") or "nonzero" for s in shapes],
                )
            )
            path_markup = f'<path d="{merged.d}" fill="black"/>'
        else:
            # Empty glyph (e.g. space) — keep the viewBox so advance width stays intact.
            path_markup = ""

        out_markup = (
            f'<svg xmlns="{SVG_NS}" '
            f'viewBox="{vb.x:g} {vb.y:g} {vb.w:g} {vb.h:g}" '
            f'width="{vb.w:g}" height="{vb.h:g}">'
            f"{path_markup}</svg>"
        )
        (out_directory / svg_path.name).write_text(out_markup, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert PNG glyphs to normalized SVGs."
    )
    parser.add_argument(
        "--png_folder",
        dest="png_folder",
        default="glyphs",
        help="Input folder containing PNG glyphs (default: glyphs)",
    )
    parser.add_argument(
        "--svg_output",
        dest="svg_output",
        default="svg_glyphs",
        help="Output folder for generated SVGs (default: svg_glyphs)",
    )
    args = parser.parse_args()

    convert_pngs_to_svgs(args.png_folder, args.svg_output)


if __name__ == "__main__":
    main()
