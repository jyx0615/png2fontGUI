#!/usr/bin/env bash
set -euo pipefail

# Usage: ./run.sh [PNG_FOLDER] [FONTNAME]
# Defaults: PNG_FOLDER=glyphs, FONTNAME from config.toml or MyCustomFont

PNG_FOLDER=${1:-glyphs}

# If a font name was provided as the second arg, use it; otherwise try config.toml
if [ "${2:-}" != "" ]; then
	FONTNAME="$2"
else
	FONTNAME=""
	if [ -f config.toml ]; then
		# Find the fontname under the [font] table. Trim spaces and quotes.
		FONTNAME=$(awk -F'=' '
			/^\[font\]/{in_font=1; next}
			in_font && $1 ~ /fontname/ {
				v=$2; gsub(/^[ \t]+|[ \t]+$/,"",v); gsub(/\"/,"",v); print v; exit
			}
		' config.toml)
	fi
	FONTNAME=${FONTNAME:-MyCustomFont}
fi

echo "Converting PNGs in '${PNG_FOLDER}' to SVGs..."
python3 png2svg.py --png_folder "${PNG_FOLDER}" --svg_output "svg_glyphs"

echo "Generating TTF from svg_glyphs with fontname='${FONTNAME}'..."
fontforge -script font.py svg_glyphs --fontname "${FONTNAME}"

echo "Embedding SVGs into ${FONTNAME}.ttf..."
addsvg svg_glyphs "${FONTNAME}.ttf"

echo "Done. Output: ${FONTNAME}.ttf"