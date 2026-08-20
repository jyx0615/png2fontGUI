"""Post-processing of the built TTF: table trimming."""

import logging

from fontTools.ttLib import TTFont

logger = logging.getLogger("png2font-api")


def subset_drop_unused_tables(font_path: str, flavor: str) -> None:
    """Drop redundant tables in place, per delivery flavor.

    FFTM (FontForge metadata) always goes.

    The web flavors (woff/woff2) additionally drop:
    - 'sbix': maximum_color builds COLR v0 only (broadly supported,
      including Safari 12.1+ — see maximum_color.ts), so no bitmap
      fallback table is ever intentionally produced. Dropped defensively
      in case one leaks in from an upstream tool.
    - 'SVG ' (only when COLR is present): per caniuse's actual @font-face
      support matrix, COLR (v1) covers Chrome 98+/Firefox 107+ but not
      Safari, while 'SVG ' covers Firefox 31+/Safari 12.1+ but not Chrome
      (never implemented) — so with COLR already present, 'SVG ' is
      redundant for every browser that would otherwise use it.

    The TTF keeps everything: it's installed rather than web-served, and
    CoreText renders it from 'SVG ' (macOS 13+) or sbix (older macOS) if
    either is present.
    """
    tables = ("FFTM",)
    try:
        font = TTFont(font_path)
        for table in tables:
            if table in font:
                del font[table]
        if flavor != "ttf":
            if "sbix" in font:
                del font["sbix"]
            if "COLR" in font and "SVG " in font:
                del font["SVG "]
        font.save(font_path)
    except Exception as exc:
        logger.warning(f"Failed to drop unused tables for {font_path}: {exc}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Font table operations: table dropping.")
    subparsers = parser.add_subparsers(dest="command", help="Sub-command to execute")

    drop_tables_parser = subparsers.add_parser("drop-tables", help="Drop unused tables")
    drop_tables_parser.add_argument(
        "--font-path",
        dest="font_path",
        required=True,
        help="Path to the font file",
    )
    drop_tables_parser.add_argument(
        "--flavor",
        dest="flavor",
        required=True,
        choices=["ttf", "woff2"],
        help="Font flavor (ttf or woff2)",
    )

    args = parser.parse_args()

    if args.command == "drop-tables":
        subset_drop_unused_tables(args.font_path, args.flavor)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
