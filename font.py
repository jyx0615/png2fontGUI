import fontforge
import os
import re
import argparse

from config import CONFIG

def svg_filename_to_codepoint(filename: str) -> int:
    stem = filename.rsplit(".", 1)[0]
    prefix = stem.split("_", 1)[0]

    if len(prefix) == 1:
        return ord(prefix)

    if re.fullmatch(r"u[0-9a-fA-F]{4,6}", prefix):
        return int(prefix[1:], 16)

    if re.fullmatch(r"[0-9a-fA-F]{4,6}", prefix):
        return int(prefix, 16)

    raise ValueError(f"Cannot infer a Unicode code point from {filename!r}.")


def import_glyphs_from_svg(folder, output_path, fontname, fullname, familyname, upm, advance_width, vertical_raise):
    font = fontforge.font()
    font.fontname = fontname
    font.fullname = fullname
    font.familyname = familyname
    font.em = upm

    for filename in os.listdir(folder):
        if filename.endswith(".svg"):
            # resize the svg to fit the em square
            svg_path = os.path.join(folder, filename)
            try:
                char_code = svg_filename_to_codepoint(filename)
            except ValueError as e:
                print(f"Skipping {filename}: {e}")
                continue

            glyph = font.createChar(char_code)
            glyph.glyphname = f"{filename.rsplit('.', 1)[0]}"
            glyph.importOutlines(svg_path)

            xmin, ymin, xmax, ymax = glyph.boundingBox()
            width = xmax - xmin
            height = ymax - ymin

            if width > 0 and height > 0:
                # png2svg.py already scaled every SVG so that the PNG canvas
                # height maps to UPM — all glyphs share the same vertical
                # reference.  Do NOT re-scale here; that would blow up short
                # glyphs (=, –, …) to enormous widths.
                # Just shift the glyph so its left ink edge starts at x = 0.
                glyph.transform((1, 0, 0, 1, -xmin, 0))

            if char_code == 32:
                glyph.width = CONFIG.space_width
            else:
                # Advance width = actual ink width (no sidebearing).
                xmin2, _, xmax2, _ = glyph.boundingBox()
                glyph.width = max(1, round(xmax2 - xmin2))
            print(
                f"Successfully imported {filename} to Unicode {char_code} {chr(char_code)}"
            )

    font.generate(output_path)
    print(f"Font generated at {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate monospace TTF from SVG folder.")
    parser.add_argument("svg_folder", nargs="?", default="svg_glyphs/", help="Folder containing SVG glyphs")
    parser.add_argument("--output", default=None, help="Output TTF file path")
    parser.add_argument("--fontname", default=CONFIG.fontname, help="Font name")
    parser.add_argument("--fullname", default=CONFIG.fullname, help="Full font name")
    parser.add_argument("--familyname", default=CONFIG.familyname, help="Font family name")
    parser.add_argument("--upm", type=int, default=CONFIG.upm, help="Units per em")
    parser.add_argument("--advance-width", type=int, default=CONFIG.advance_width, help="Monospace advance width")
    parser.add_argument("--vertical-raise", type=int, default=120, help="Vertical raise offset")

    args, unknown = parser.parse_known_args()

    # If FontForge script runner adds extra args or if there are unexpected positional args
    # we filter and handle them safely
    output_ttf = args.output if args.output else f"{args.fontname}.ttf"

    import_glyphs_from_svg(
        folder=args.svg_folder,
        output_path=output_ttf,
        fontname=args.fontname,
        fullname=args.fullname,
        familyname=args.familyname,
        upm=args.upm,
        advance_width=args.advance_width,
        vertical_raise=args.vertical_raise
    )


if __name__ == "__main__":
    main()
