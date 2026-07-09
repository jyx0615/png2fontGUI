import fontforge
import os
import re
import argparse

from config import CONFIG, vertical_metrics

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


def import_glyphs_from_svg(
    folder, output_path, fontname, fullname, familyname, upm, advance_width, vertical_raise,
    monospace=False, ascent=None, descent=None, line_height=None, letter_spacing=0,
):
    font = fontforge.font()
    font.fontname = fontname
    font.fullname = fullname
    font.familyname = familyname
    font.em = upm
    font.encoding = "UnicodeFull"

    # Ascent/descent define the glyphs' natural vertical placement; any
    # extra room the caller wants for line spacing (e.g. a tuned line-height
    # multiplier) goes into the line gap instead, so apps that respect it
    # get the padded spacing while single-glyph metrics stay accurate.
    if ascent is not None and descent is not None:
        font.ascent = ascent
        font.descent = descent
        # Pin hhea to the requested metrics; otherwise FontForge derives them
        # from ink extents, and browsers that size line boxes from hhea
        # (e.g. Chrome on macOS) get a wildly different line height than the
        # one the caller asked for.
        font.hhea_ascent_add = False
        font.hhea_descent_add = False
        font.hhea_ascent = ascent
        font.hhea_descent = -descent
        if line_height is not None:
            line_gap = max(0, line_height - (ascent + descent))
            font.hhea_linegap = line_gap
            font.os2_typolinegap = line_gap

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
                # png2svg authors SVGs in the OT-SVG convention (y=0 is the
                # baseline, ink above it at negative y), but FontForge's SVG
                # import maps SVG y=0 to the ASCENT line, landing every glyph
                # a full ascent too high — shift down by font.ascent to put
                # the outlines back where the SVG (and the color tables built
                # from it) say they belong.  vertical_raise stays a caller
                # tunable on top of that.
                dy = vertical_raise - font.ascent
                if monospace:
                    # Center the glyph within the monospace advance_width
                    dx = -xmin + round((advance_width - width) / 2)
                    glyph.transform((1, 0, 0, 1, dx, dy))
                else:
                    # Just shift the glyph so its left ink edge starts at x = 0.
                    glyph.transform((1, 0, 0, 1, -xmin, dy))

            if char_code == 32:
                glyph.width = advance_width if monospace else CONFIG.space_width
            else:
                if monospace:
                    glyph.width = advance_width
                else:
                    # Advance width = actual ink width (no sidebearing) plus
                    # the tuned letter-spacing, so the default (untracked)
                    # rendering already carries the Studio's Spacing slider
                    # value baked in as real advance width.
                    xmin2, _, xmax2, _ = glyph.boundingBox()
                    ink_width = xmax2 - xmin2
                    glyph.width = max(1, round(ink_width + letter_spacing))
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
    parser.add_argument("--vertical-raise", type=int, default=0, help="Vertical raise offset")
    parser.add_argument("--monospace", action="store_true", default=False, help="Generate monospace font")
    parser.add_argument("--ascent", type=int, default=None, help="Font-wide ascent in units (default: standard proportions from UPM)")
    parser.add_argument("--descent", type=int, default=None, help="Font-wide descent in units (default: standard proportions from UPM)")
    parser.add_argument("--line-height", type=int, default=None, help="Target default line height in units (default: standard proportions from UPM)")
    parser.add_argument("--letter-spacing", type=int, default=0, help="Extra advance added after each glyph, in units")

    args, unknown = parser.parse_known_args()

    # If FontForge script runner adds extra args or if there are unexpected positional args
    # we filter and handle them safely
    output_ttf = args.output if args.output else f"{args.fontname}.ttf"

    # Vertical metrics default to fixed standard proportions so generated
    # fonts mix with system fonts without changing line spacing; the CLI
    # flags remain as expert overrides.
    default_ascent, default_descent, default_line_height = vertical_metrics(args.upm)
    ascent = args.ascent if args.ascent is not None else default_ascent
    descent = args.descent if args.descent is not None else default_descent
    line_height = args.line_height if args.line_height is not None else default_line_height

    import_glyphs_from_svg(
        folder=args.svg_folder,
        output_path=output_ttf,
        fontname=args.fontname,
        fullname=args.fullname,
        familyname=args.familyname,
        upm=args.upm,
        advance_width=args.advance_width,
        vertical_raise=args.vertical_raise,
        monospace=args.monospace,
        ascent=ascent,
        descent=descent,
        line_height=line_height,
        letter_spacing=args.letter_spacing,
    )


if __name__ == "__main__":
    main()
