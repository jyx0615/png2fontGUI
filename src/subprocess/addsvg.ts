/**
 * addsvg CLI wrapper — embeds SVG outlines into TTF as an 'SVG ' table
 */

import { runProcess } from "./runProcess.js";
import { ADDSVG_BIN } from "./toolPaths.js";

export async function runAddsvg(svgFolder: string, ttfPath: string): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return runProcess(ADDSVG_BIN, [svgFolder, ttfPath]);
}
