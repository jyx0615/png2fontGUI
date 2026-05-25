import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import vtracer
import subprocess
import argparse
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


UPSCALE_FACTOR = 4  # Lanczos upscale multiplier before tracing


def _is_near_white(color: str, threshold: int = 230) -> bool:
    """Return True if `color` (CSS hex) is near-white."""
    c = color.strip().lstrip("#").lower()
    if c in ("fff", "ffffff", "white"):
        return True
    if len(c) == 6:
        try:
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            return r >= threshold and g >= threshold and b >= threshold
        except ValueError:
            pass
    return False


def upscale_png(png_path: Path, scale: int = UPSCALE_FACTOR, alpha_threshold: int = 128) -> str:
    """Return path to a temp PNG upscaled by `scale`x using Lanczos resampling.

    Order of operations:
      1. Upscale first with Lanczos so edge gradients are interpolated smoothly.
      2. Apply a hard binary alpha threshold on the high-res image.
      3. Composite glyph over a pure-white background so that transparent pixels
         carry white RGB values. vtracer then sees clean white in those areas
         instead of bleed colours from PNG anti-aliasing, ensuring any background
         layer it generates is reliably white (and safe to remove later).
    """
    img = Image.open(png_path).convert("RGBA")

    # Step 1: Upscale with Lanczos for maximum sharpness
    new_size = (img.width * scale, img.height * scale)
    upscaled = img.resize(new_size, Image.LANCZOS)

    # Step 2: Hard-edge alpha on the high-res image to kill the anti-aliased fringe
    r, g, b, a = upscaled.split()
    hard_alpha = a.point(lambda v: 255 if v >= alpha_threshold else 0)

    # Step 3: Paste glyph over white so transparent pixels' RGB becomes white.
    # This prevents vtracer from picking up bleed colours from the transparent
    # border pixels and generating a coloured background layer.
    white_bg = Image.new("RGBA", upscaled.size, (255, 255, 255, 255))
    white_bg.paste(upscaled, mask=hard_alpha)   # glyph over white; transparent → white RGB
    r_clean, g_clean, b_clean, _ = white_bg.split()
    # Re-attach the binary alpha so the PNG still carries proper transparency
    upscaled = Image.merge("RGBA", (r_clean, g_clean, b_clean, hard_alpha))

    handle, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    upscaled.save(tmp_path, format="PNG")
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
            mode="polygon",             # Polygon mode: FontForge-safe (spline causes SSAddPoints crash)
            filter_speckle=2,           # Minimal speckle removal — preserves more regions
            color_precision=6,          # Fewer clusters → larger solid fills → no gaps
            corner_threshold=25,        # Capture sharper corners (default 60 is too blunt)
            length_threshold=2.0,       # Finer segment resolution for sharper edges
            splice_threshold=45,        # Prevent unwanted spline loops at corners
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
        path_tag = f"{{{namespace}}}path" if namespace else "path"
        children = list(root)
        if children and children[0].tag == path_tag:
            fill = children[0].attrib.get("fill", "")
            if _is_near_white(fill):
                root.remove(children[0])

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
