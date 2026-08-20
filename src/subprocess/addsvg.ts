/**
 * addsvg CLI wrapper — embeds SVG outlines into TTF as an 'SVG ' table.
 *
 * Passes -k (keep viewBox): our shifted SVGs carry
 * viewBox="0 -{ascent} {width} {upm}" to position content with the baseline
 * at the SVG's local y=0. Without a viewBox, the OT-SVG spec defines a
 * glyph's local y=0 as the ASCENT line instead — addsvg strips the viewBox
 * by default, which silently shifts every embedded glyph up by a full
 * ascent in any renderer that reads the 'SVG ' table directly (e.g. Safari
 * / CoreText).
 */

import { runProcess } from "./runProcess.js";
import { ADDSVG_BIN } from "./toolPaths.js";

export async function runAddsvg(svgFolder: string, ttfPath: string): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return runProcess(ADDSVG_BIN, ["-k", svgFolder, ttfPath]);
}
