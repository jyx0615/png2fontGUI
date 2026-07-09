import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import vtracer
import subprocess
import argparse
import numpy as np
from PIL import Image
import shutil

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


UPSCALE_FACTOR = 2  # Nearest-neighbor upscale multiplier before tracing
ALPHA_THRESHOLD = 30   # Low threshold preserves soft/feathered glyph edges

def upscale_png(png_path: Path, scale: int = UPSCALE_FACTOR, alpha_threshold: int = ALPHA_THRESHOLD) -> str:
    """Return path to a temp PNG upscaled by `scale`x using nearest-neighbor resampling.

    Order of operations:
      1. Defringe: un-premultiply dark edge pixels left by background removal.
         Background removal tools blend foreground against the original dark/black
         background at semi-transparent edges. This leaves a dark halo whose color
         equals fg_color * alpha. Dividing by alpha/255 recovers the true fg color.
      2. Apply a hard binary alpha threshold on the corrected image.
      3. Composite glyph over pure white so transparent pixels carry white RGB.
      4. Upscale with NEAREST-NEIGHBOR — replicates pixels exactly, no color mixing.
    """
    img = Image.open(png_path).convert("RGBA")

    # Step 1: Adaptive defringe — only correct against a dark background.
    #
    # Background removal tools leave semi-transparent edge pixels whose RGB is
    # blended with the original background color. The un-premultiply formula
    #   fg = observed × 255 / alpha
    # recovers the true fg color — BUT ONLY when the original background was BLACK.
    # If the source was a light/white background (e.g. a product photo on white),
    # the edge pixels are already bright and dividing makes them even brighter,
    # washing out the colors.
    #
    # Heuristic: measure the mean brightness of semi-transparent edge pixels
    # (0 < alpha < 200). If their average RGB is dark → dark background → defringe.
    # If already bright → light background → skip correction.
    data = np.array(img, dtype=np.float32)              # (H, W, 4)
    rgb, alpha_ch = data[:, :, :3], data[:, :, 3]       # views into data

    edge_mask = (alpha_ch > 0) & (alpha_ch < 200)       # semi-transparent pixels only
    if edge_mask.any():
        mean_brightness = rgb[edge_mask].mean()          # 0–255 scale
    else:
        mean_brightness = 255.0                          # no edge pixels → treat as light

    DARK_BG_THRESHOLD = 100   # pixels with mean brightness below this → dark background
    if mean_brightness < DARK_BG_THRESHOLD:
        # Dark background: un-premultiply to recover true fg color.
        # fg = observed × 255 / alpha
        full_mask = alpha_ch > 0
        rgb[full_mask] = np.clip(
            rgb[full_mask] * (255.0 / alpha_ch[full_mask, np.newaxis]), 0, 255
        )
        img = Image.fromarray(data.astype(np.uint8), "RGBA")
    # else: light/white background → no defringing needed, colors are already correct

    # Step 2: Hard-edge alpha on the ORIGINAL resolution to binarize at true boundaries.
    r, g, b, a = img.split()
    hard_alpha = a.point(lambda v: 255 if v >= alpha_threshold else 0)

    # Step 3: Paste glyph over white so transparent pixels' RGB becomes white.
    white_bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    white_bg.paste(img, mask=hard_alpha)
    r_clean, g_clean, b_clean, _ = white_bg.split()
    cleaned = Image.merge("RGBA", (r_clean, g_clean, b_clean, hard_alpha))

    # Step 4: Upscale with NEAREST-NEIGHBOR — replicates pixels exactly, no blending.
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

    # Upscale PNG before tracing so vtracer has more pixels to work with
    upscaled_png_path = upscale_png(png_path)

    try:
        vtracer.convert_image_to_svg_py(
            upscaled_png_path,
            str(temp_svg_path),
            colormode="color",          # Preserve original colors
            hierarchical="cutout",      # Cutout mode avoids layering gaps that cause holes
            mode="spline",              # Spline mode: smooth Bézier curves for natural fur/texture edges
            filter_speckle=1,           # Minimal removal — fur IS made of tiny detail regions
            color_precision=8,          # High precision → many color clusters → rich gradients
            corner_threshold=60,        # vtracer default — let it decide corners naturally
            length_threshold=3.0,       # Fine segment resolution to capture hair-level detail
            splice_threshold=45,        # Prevent unwanted loops at corners
        )

        tree = ET.parse(temp_svg_path)
        root = tree.getroot()
        namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""

        # Remove the first <path> only if it is a near-white background fill.
        # In cutout mode vtracer injects a background rectangle as the first child;
        # since we pre-filled transparent pixels with white, that rectangle will
        # always have a near-white fill and can be safely stripped.
        # Non-white first paths (e.g. the purple body of a donut glyph) are left
        # untouched so we don't clip the actual glyph.
        children = list(root)

        view_box = root.attrib.get("viewBox")
        if view_box:
            _, _, source_width, source_height = map(float, view_box.split())
        else:
            source_width = float(root.attrib.get("width", width))
            source_height = float(root.attrib.get("height", height))

        # Scale by height only — preserves the PNG's natural aspect ratio so
        # that narrow glyphs ("I", "l") stay narrow and wide ones ("W", "M")
        # stay wide.  The SVG width reflects the actual glyph advance width.
        scale = target_upm / source_height
        scaled_width = round(source_width * scale)

        children = list(root)

        # Traced SVGs are metric-independent: the PNG canvas bottom sits on
        # y=0 with all ink above it at negative y.  Vertical font metrics
        # (descent/baseline placement) are applied later at font-build time
        # by shift_svgs_for_descent(), so changing metrics never requires
        # re-tracing.
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
    """Apply vertical font metrics to traced SVGs at font-build time.

    Traced SVGs put the PNG canvas bottom on y=0 (baseline).  The font treats
    the canvas as the full em box (top = ascent line, bottom = -descent), so
    shift the content down by `descent` units: canvas top lands at
    -(upm - descent) and canvas bottom at +descent, leaving descender room
    below the baseline for g/j/p/q/y.  This is a cheap XML rewrite — changing
    ascent/descent/line-height only re-runs this and FontForge, not the trace.
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
